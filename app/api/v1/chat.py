from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agents.academic_assistant import research_assistant_stream
from app.graph.events import public_state_view
from app.graph.persistence import delete_thread
from app.graph.runtime import (
    academic_react_event_stream,
    clear_messages,
    continue_with_selected_papers,
    get_messages,
    get_thread_detail,
    list_thread_summaries,
    rename_thread_title,
)
from app.models.schemas import ChatRequest, ManualInterventionRequest, ThreadRenameRequest


router = APIRouter()


@router.post("/chat/stream")
async def chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        research_assistant_stream(
            prompt=request.message,
            image=request.image_url,
            thread_id=request.thread_id,
            chart_type_hint=request.chart_type_hint,
            top_k=request.top_k,
            max_steps=request.max_react_steps,
        ),
        media_type="text/event-stream",
    )


@router.post("/chat/react-stream")
async def react_chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        academic_react_event_stream(
            message=request.message,
            image_url=request.image_url,
            thread_id=request.thread_id,
            chart_type_hint=request.chart_type_hint,
            top_k=request.top_k,
            max_steps=request.max_react_steps,
        ),
        media_type="text/event-stream",
    )


@router.get("/chat/messages")
async def get_chat_messages(thread_id: str):
    detail = get_thread_detail(thread_id)
    return {
        "messages": get_messages(thread_id),
        "thread": detail["thread"] if detail else None,
        "state": public_state_view(detail["state"]) if detail and detail["state"] else None,
    }


@router.delete("/chat/messages")
async def clear_chat_messages(thread_id: str):
    clear_messages(thread_id)
    return {"success": True}


@router.get("/threads")
async def get_threads(limit: int = Query(default=100, ge=1, le=500)):
    return {"threads": list_thread_summaries(limit=limit)}


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    detail = get_thread_detail(thread_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {
        "thread": detail["thread"],
        "messages": detail["messages"],
        "state": public_state_view(detail["state"]) if detail["state"] else None,
        "trace": detail["state"].get("react_trace", []) if detail["state"] else [],
    }


@router.patch("/threads/{thread_id}")
async def rename_thread_endpoint(thread_id: str, request: ThreadRenameRequest):
    rename_thread_title(thread_id, request.title)
    detail = get_thread_detail(thread_id)
    return {"success": True, "thread": detail["thread"] if detail else None}


@router.delete("/threads/{thread_id}")
async def delete_thread_endpoint(thread_id: str):
    delete_thread(thread_id)
    return {"success": True}


@router.post("/threads/{thread_id}/manual-continue")
async def continue_with_manual_selection(thread_id: str, request: ManualInterventionRequest):
    detail = continue_with_selected_papers(thread_id, request.selected_papers)
    if not detail:
        raise HTTPException(status_code=404, detail="Thread not found")
    return detail
