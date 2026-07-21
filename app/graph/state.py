from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict


class AcademicState(TypedDict):
    thread_id: str
    user_message: str
    image_url: str | None
    chart_type_hint: str | None
    top_k: int
    max_steps: int
    intent: str | None
    intent_reason: str | None
    task_type: str | None
    current_agent: str | None
    next_agent: str | None
    execution_plan: list[str]
    skipped_agents: list[str]
    conversation_history: list[dict[str, str]]
    route_history: list[dict[str, Any]]
    chart_type: str | None
    chart_summary: str | None
    extracted_elements: list[dict[str, Any]]
    search_queries: list[str]
    papers: list[dict[str, Any]]
    evidence_notes: list[dict[str, Any]]
    react_trace: list[dict[str, Any]]
    final_answer: str | None
    pending_user_action: dict[str, Any] | None
    notices: list[dict[str, Any]]
    errors: list[str]
    metadata: dict[str, Any]


def _default_metadata() -> dict[str, Any]:
    return {
        "step_count": 0,
        "search_iterations": 0,
        "needs_dynamic_route": False,
        "follow_up": False,
        "web_search_used": False,
        "intent_resolved": False,
        "completed_agents": [],
        "parallel_sources_used": [],
        "query_refinement_count": 0,
        "network_retry_count": 0,
        "degraded_mode": False,
        "thread_status": "idle",
        "manual_context": None,
    }


def create_initial_state(
    *,
    thread_id: str,
    user_message: str,
    image_url: str | None,
    chart_type_hint: str | None,
    top_k: int,
    max_steps: int,
    conversation_history: list[dict[str, str]] | None = None,
    previous_state: AcademicState | None = None,
) -> AcademicState:
    history = conversation_history or []
    metadata = _default_metadata()
    notices: list[dict[str, Any]] = []
    pending_user_action: dict[str, Any] | None = None

    state: AcademicState = {
        "thread_id": thread_id,
        "user_message": user_message,
        "image_url": image_url,
        "chart_type_hint": chart_type_hint,
        "top_k": top_k,
        "max_steps": max_steps,
        "intent": None,
        "intent_reason": None,
        "task_type": None,
        "current_agent": None,
        "next_agent": None,
        "execution_plan": [],
        "skipped_agents": [],
        "conversation_history": history,
        "route_history": [],
        "chart_type": None,
        "chart_summary": None,
        "extracted_elements": [],
        "search_queries": [],
        "papers": [],
        "evidence_notes": [],
        "react_trace": [],
        "final_answer": None,
        "pending_user_action": None,
        "notices": notices,
        "errors": [],
        "metadata": metadata,
    }

    if previous_state and not image_url:
        state["chart_type"] = previous_state.get("chart_type")
        state["chart_summary"] = previous_state.get("chart_summary")
        state["extracted_elements"] = deepcopy(previous_state.get("extracted_elements", []))
        state["search_queries"] = deepcopy(previous_state.get("search_queries", []))
        state["papers"] = deepcopy(previous_state.get("papers", []))
        state["evidence_notes"] = deepcopy(previous_state.get("evidence_notes", []))
        state["metadata"]["follow_up"] = True

        if previous_state.get("pending_user_action"):
            previous_pending_action = deepcopy(previous_state["pending_user_action"])
            state["metadata"]["manual_context"] = previous_pending_action
            notices.append(
                {
                    "level": "info",
                    "title": "已接续上一次人工介入节点",
                    "message": "本轮会把你新输入的内容当作补充线索，继续推进之前未完成的检索或证据整理。",
                    "suggestions": previous_pending_action.get("suggestions", []),
                }
            )

    state["pending_user_action"] = pending_user_action
    return state


def apply_state_updates(state: AcademicState, updates: dict[str, Any]) -> AcademicState:
    next_state = deepcopy(state)
    for key, value in updates.items():
        if key == "metadata":
            next_state["metadata"] = {**next_state.get("metadata", {}), **value}
            continue
        if key == "notices":
            next_state["notices"] = list(value)
            continue
        next_state[key] = value
    return next_state
