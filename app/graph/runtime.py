from __future__ import annotations

import asyncio
from typing import Iterator

from app.agents.chart_react_agent import run_chart_react_agent
from app.agents.evidence_review_agent import run_evidence_review_agent
from app.agents.literature_react_agent import run_literature_react_agent
from app.agents.orchestrator import run_orchestrator
from app.agents.report_agent import run_report_agent
from app.agents.search_planner_agent import run_search_planner_agent
from app.common.logger import logger
from app.graph.events import build_event, public_state_view, serialize_sse
from app.graph.persistence import (
    append_chat_message,
    clear_thread_data,
    get_thread_bundle,
    get_thread_messages,
    infer_thread_title,
    list_threads,
    load_latest_state,
    rename_thread,
    save_run_state,
    set_thread_status,
    setup_database,
    upsert_thread,
)
from app.graph.state import AcademicState, apply_state_updates, create_initial_state


AGENT_RUNNERS = {
    "chart_react_agent": run_chart_react_agent,
    "search_planner_agent": run_search_planner_agent,
    "literature_react_agent": run_literature_react_agent,
    "evidence_review_agent": run_evidence_review_agent,
    "report_agent": run_report_agent,
}


def _append_trace(state: AcademicState, events: list[dict]) -> AcademicState:
    trace = list(state.get("react_trace", []))
    for event in events:
        if event.get("type") in {"final_token", "done"}:
            continue
        trace.append(event)
    return apply_state_updates(state, {"react_trace": trace})


def _chunk_text(text: str, size: int = 120) -> list[str]:
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def _friendly_error_payload(error_text: str) -> dict[str, object]:
    lowered = error_text.lower()
    if "openai_model" in lowered or "openai_api_key" in lowered:
        return {
            "title": "模型配置缺失",
            "message": "当前无法调用大模型，请检查 .env 中的 OPENAI_MODEL 和 OPENAI_API_KEY。",
            "suggestions": ["确认 OPENAI_MODEL 已填写", "确认 OPENAI_API_KEY 有效并已重启服务"],
        }
    if "tavily_api_key" in lowered:
        return {
            "title": "网页补充检索未启用",
            "message": "主流程仍可运行，但无法使用网页兜底检索。",
            "suggestions": ["如果需要网页补充检索，请补充 TAVILY_API_KEY"],
        }
    if any(token in lowered for token in ("timed out", "timeout", "connection", "reset", "temporary")):
        return {
            "title": "网络请求失败",
            "message": "外部检索接口响应不稳定，系统已自动重试；如果仍失败，建议稍后重试。",
            "suggestions": ["稍后重试", "缩小检索范围，例如补充方法名或数据集名"],
        }
    return {
        "title": "流程执行失败",
        "message": "某个环节未能完成，本轮会保留已得到的结果，便于你继续追问或重试。",
        "suggestions": ["查看右侧 Trace 面板定位失败节点", "补充更明确的任务描述后重试"],
    }


def _derive_thread_status(state: AcademicState) -> str:
    if state.get("pending_user_action"):
        return "needs_input"
    if state.get("errors"):
        return "error"
    if state.get("final_answer"):
        return "completed"
    return "running"


def _progress_event(state: AcademicState, *, agent: str) -> dict:
    state_view = public_state_view(state)
    return build_event(
        "progress_update",
        agent=agent,
        summary=state_view["status_summary"],
        state=state_view,
    )


def _mark_agent_completed(state: AcademicState, agent_name: str) -> AcademicState:
    metadata = dict(state.get("metadata", {}))
    completed = list(metadata.get("completed_agents", []))
    if agent_name not in completed:
        completed.append(agent_name)
    metadata["completed_agents"] = completed
    return apply_state_updates(state, {"metadata": metadata})


def _save_thread_projection(state: AcademicState) -> None:
    thread_status = _derive_thread_status(state)
    preview = state.get("final_answer") or state.get("user_message") or ""
    set_thread_status(state["thread_id"], thread_status, preview=preview[:240])


def _failure_message(state: AcademicState, error_text: str) -> str:
    notice = _friendly_error_payload(error_text)
    lines = [
        "## 当前状态",
        notice["title"],
        "",
        "## 原因说明",
        notice["message"],
        "",
        "## 建议操作",
    ]
    for suggestion in notice["suggestions"]:
        lines.append(f"- {suggestion}")
    return "\n".join(lines).strip()


def run_academic_workflow(
    *,
    message: str,
    image_url: str | None,
    thread_id: str,
    chart_type_hint: str | None,
    top_k: int,
    max_steps: int,
) -> Iterator[dict]:
    setup_database()
    previous_state = load_latest_state(thread_id)
    conversation_history = get_thread_messages(thread_id)
    state = create_initial_state(
        thread_id=thread_id,
        user_message=message,
        image_url=image_url,
        chart_type_hint=chart_type_hint,
        top_k=top_k,
        max_steps=max_steps,
        conversation_history=conversation_history,
        previous_state=previous_state,
    )

    logger.info("Starting workflow thread_id=%s image=%s", thread_id, bool(image_url))
    upsert_thread(
        thread_id,
        title=infer_thread_title(message),
        preview=message,
        status="running",
    )
    append_chat_message(thread_id, "user", message)

    assistant_saved = False
    yield build_event(
        "session_ready",
        agent="system",
        thread_id=thread_id,
        thread=get_thread_bundle(thread_id)["thread"],
        state=public_state_view(state),
        conversation_history=conversation_history[-10:],
    )
    yield _progress_event(state, agent="system")

    try:
        while True:
            orchestrator_result = run_orchestrator(state)
            state = apply_state_updates(state, orchestrator_result["state_updates"])
            state = _append_trace(state, orchestrator_result["events"])
            for event in orchestrator_result["events"]:
                yield event
            yield _progress_event(state, agent="orchestrator")

            next_agent = state.get("next_agent") or "end"
            if next_agent == "end":
                break

            yield build_event("agent_start", agent=next_agent, state=public_state_view(state))
            runner = AGENT_RUNNERS[next_agent]
            agent_result = runner(state)
            state = apply_state_updates(state, agent_result["state_updates"])
            state = _mark_agent_completed(state, next_agent)
            state = apply_state_updates(
                state,
                {
                    "metadata": {
                        "step_count": int(state.get("metadata", {}).get("step_count", 0)) + 1
                    }
                },
            )
            state = _append_trace(state, agent_result["events"])

            for event in agent_result["events"]:
                yield event

            yield build_event("agent_end", agent=next_agent, state=public_state_view(state))
            yield _progress_event(state, agent=next_agent)
            save_run_state(state)
            _save_thread_projection(state)

            if next_agent == "report_agent":
                final_answer = state.get("final_answer") or ""
                for chunk in _chunk_text(final_answer):
                    yield build_event("final_token", agent="report_agent", content=chunk)
                if final_answer:
                    append_chat_message(thread_id, "assistant", final_answer)
                    assistant_saved = True
                break

        save_run_state(state)
        _save_thread_projection(state)
    except Exception as exc:
        error_text = str(exc)
        logger.exception("Workflow failed thread_id=%s", thread_id)
        notice = _friendly_error_payload(error_text)
        notices = list(state.get("notices", []))
        notices.append({"level": "error", **notice})
        state = apply_state_updates(
            state,
            {
                "errors": [*state.get("errors", []), error_text],
                "notices": notices,
                "final_answer": state.get("final_answer") or _failure_message(state, error_text),
            },
        )
        state = _append_trace(
            state,
            [build_event("error", agent=state.get("current_agent") or "system", message=error_text)],
        )
        save_run_state(state)
        _save_thread_projection(state)
        yield build_event("error", agent=state.get("current_agent") or "system", message=error_text)
        yield build_event(
            "user_notice",
            agent="system",
            level="error",
            title=notice["title"],
            message=notice["message"],
            suggestions=notice["suggestions"],
            state=public_state_view(state),
        )
        yield _progress_event(state, agent="system")
        if state.get("final_answer"):
            for chunk in _chunk_text(state["final_answer"]):
                yield build_event("final_token", agent="report_agent", content=chunk)
            if not assistant_saved:
                append_chat_message(thread_id, "assistant", state["final_answer"])
                assistant_saved = True
    finally:
        if state.get("final_answer") and not assistant_saved:
            append_chat_message(thread_id, "assistant", state["final_answer"])
        save_run_state(state)
        _save_thread_projection(state)
        yield build_event("done", agent="system", state=public_state_view(state))


async def academic_react_event_stream(
    *,
    message: str,
    image_url: str | None,
    thread_id: str,
    chart_type_hint: str | None,
    top_k: int,
    max_steps: int,
):
    for event in run_academic_workflow(
        message=message,
        image_url=image_url,
        thread_id=thread_id,
        chart_type_hint=chart_type_hint,
        top_k=top_k,
        max_steps=max_steps,
    ):
        yield serialize_sse(event)
        await asyncio.sleep(0)


async def academic_text_stream(
    *,
    message: str,
    image_url: str | None,
    thread_id: str,
    chart_type_hint: str | None,
    top_k: int,
    max_steps: int,
):
    for event in run_academic_workflow(
        message=message,
        image_url=image_url,
        thread_id=thread_id,
        chart_type_hint=chart_type_hint,
        top_k=top_k,
        max_steps=max_steps,
    ):
        if event.get("type") == "final_token":
            yield event.get("content", "")
        await asyncio.sleep(0)


def get_messages(thread_id: str) -> list[dict[str, str]]:
    return get_thread_messages(thread_id)


def clear_messages(thread_id: str) -> None:
    clear_thread_data(thread_id)


def get_thread_detail(thread_id: str) -> dict | None:
    return get_thread_bundle(thread_id)


def list_thread_summaries(limit: int = 100) -> list[dict]:
    return list_threads(limit=limit)


def rename_thread_title(thread_id: str, title: str) -> None:
    rename_thread(thread_id, title)


def continue_with_selected_papers(thread_id: str, selected_titles: list[str]) -> dict | None:
    state = load_latest_state(thread_id)
    if not state:
        return None

    filtered_titles = {title.strip() for title in selected_titles if title.strip()}
    if filtered_titles:
        papers = [paper for paper in state.get("papers", []) if paper.get("title") in filtered_titles]
        evidence_notes = [note for note in state.get("evidence_notes", []) if note.get("title") in filtered_titles]
    else:
        papers = state.get("papers", [])
        evidence_notes = state.get("evidence_notes", [])

    notices = list(state.get("notices", []))
    notices.append(
        {
            "level": "info",
            "title": "已采用人工筛选结果",
            "message": "系统将基于你保留的文献重新整理证据并输出总结。",
            "suggestions": list(filtered_titles)[:3],
        }
    )

    state = apply_state_updates(
        state,
        {
            "papers": papers,
            "evidence_notes": evidence_notes,
            "pending_user_action": None,
            "notices": notices,
            "current_agent": "manual_intervention",
            "metadata": {
                "needs_dynamic_route": False,
                "manual_context": None,
            },
        },
    )

    evidence_result = run_evidence_review_agent(state)
    state = apply_state_updates(state, evidence_result["state_updates"])
    state = _append_trace(state, evidence_result["events"])
    state = _mark_agent_completed(state, "evidence_review_agent")

    report_result = run_report_agent(state)
    state = apply_state_updates(state, report_result["state_updates"])
    state = _append_trace(state, report_result["events"])
    state = _mark_agent_completed(state, "report_agent")

    if state.get("final_answer"):
        append_chat_message(thread_id, "assistant", state["final_answer"])
    save_run_state(state)
    _save_thread_projection(state)
    detail = get_thread_bundle(thread_id)
    return {
        "thread": detail["thread"] if detail else None,
        "state": public_state_view(state),
        "trace": state.get("react_trace", []),
        "messages": get_thread_messages(thread_id),
    }
