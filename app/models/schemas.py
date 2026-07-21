from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    image_url: str | None = None
    thread_id: str
    chart_type_hint: str | None = Field(default=None, description="Optional user hint for the chart type.")
    top_k: int = Field(default=5, ge=1, le=10)
    show_trace: bool = True
    max_react_steps: int = Field(default=8, ge=1, le=20)


class ThreadRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ManualInterventionRequest(BaseModel):
    selected_papers: list[str] = Field(default_factory=list)
