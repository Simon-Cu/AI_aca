from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import chat, oss
from app.common.logger import setup_logging
from app.common.settings import get_settings, load_environment
from app.graph.persistence import setup_database

load_environment()
setup_logging()
setup_database()

settings = get_settings()

app = FastAPI(
    title="Academic ReAct Multi-Agent Assistant API",
    description="Academic chart understanding and literature retrieval with shared-state multi-agent orchestration.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(oss.router, prefix="/api/v1", tags=["oss"])

if settings.static_dir.exists():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")


@app.get("/{path:path}", include_in_schema=False)
async def serve_frontend(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": "Not Found"}, status_code=404)

    file_path = settings.static_dir / path
    if file_path.is_file():
        return FileResponse(file_path)

    index_path = settings.static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Academic ReAct assistant is online.", "status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)
