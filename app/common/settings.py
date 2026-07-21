from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "app"
DB_PATH = APP_ROOT / "db" / "academic_assistant.db"
STATIC_DIR = APP_ROOT / "static"
ROOT_ENV_PATH = PROJECT_ROOT / ".env"
ROOT_ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
LEGACY_ENV_PATHS = [
    APP_ROOT / "agents" / ".env",
    APP_ROOT / "tools" / ".env",
    APP_ROOT / "api" / "v1" / ".env",
]


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    project_root: Path
    app_root: Path
    db_path: Path
    static_dir: Path
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    tavily_api_key: str
    oss_access_key_id: str
    oss_access_key_secret: str
    oss_bucket: str
    oss_endpoint: str
    react_max_steps: int
    default_top_k: int


def load_environment() -> None:
    for env_path in [ROOT_ENV_PATH, *LEGACY_ENV_PATHS]:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_environment()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        project_root=PROJECT_ROOT,
        app_root=APP_ROOT,
        db_path=DB_PATH,
        static_dir=STATIC_DIR,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "").strip(),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        oss_access_key_id=os.getenv("OSS_ACCESS_KEY_ID", "").strip(),
        oss_access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET", "").strip(),
        oss_bucket=os.getenv("OSS_BUCKET", "").strip(),
        oss_endpoint=os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com").strip(),
        react_max_steps=_read_int("REACT_MAX_STEPS", 8),
        default_top_k=_read_int("DEFAULT_TOP_K", 5),
    )


def require_setting(name: str, value: str) -> str:
    if value:
        return value
    raise ConfigurationError(
        f"Missing {name}. Fill it in {ROOT_ENV_PATH} or keep the legacy nested .env files."
    )
