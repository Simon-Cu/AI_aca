from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from app.common.settings import ConfigurationError, get_settings, require_setting


class AgentRunResult(TypedDict):
    state_updates: dict[str, Any]
    events: list[dict[str, Any]]


def make_result(
    *,
    state_updates: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> AgentRunResult:
    return {
        "state_updates": state_updates or {},
        "events": events or [],
    }


def normalize_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                    continue
                if "content" in item:
                    parts.append(str(item["content"]))
        return "\n".join(part for part in parts if part)
    return str(content)


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@lru_cache(maxsize=1)
def get_chat_model():
    settings = get_settings()
    api_key = require_setting("OPENAI_API_KEY", settings.openai_api_key)
    model_name = require_setting("OPENAI_MODEL", settings.openai_model)

    kwargs: dict[str, Any] = {
        "model": model_name,
        "model_provider": "openai",
        "api_key": api_key,
        "temperature": 0,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return init_chat_model(**kwargs)


def build_user_message(prompt: str, image_url: str | None = None) -> HumanMessage:
    if not image_url:
        return HumanMessage(content=prompt)

    return HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    )


def _extract_json_candidate(text: str) -> str | None:
    candidates = [text.strip()]

    fence_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1].strip())
                    break

    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None


def invoke_json_response(
    *,
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    image_url: str | None = None,
    fallback: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any] | list[Any]:
    try:
        model = get_chat_model()
        message = build_user_message(user_prompt, image_url)
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        f"{system_prompt}\n"
                        "Return only valid JSON. Do not wrap the response in markdown fences."
                    )
                ),
                message,
            ]
        )
        text = normalize_text_content(response.content)
        candidate = _extract_json_candidate(text)
        if candidate:
            return json.loads(candidate)
    except Exception:
        if fallback is not None:
            return fallback
        raise

    if fallback is not None:
        return fallback
    raise ConfigurationError(f"{agent_name} returned non-JSON output.")


def invoke_text_response(
    *,
    system_prompt: str,
    user_prompt: str,
    image_url: str | None = None,
) -> str:
    model = get_chat_model()
    response = model.invoke(
        [
            SystemMessage(content=system_prompt),
            build_user_message(user_prompt, image_url),
        ]
    )
    return normalize_text_content(response.content).strip()


def trim_text(value: str | None, *, limit: int = 400) -> str:
    if not value:
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
