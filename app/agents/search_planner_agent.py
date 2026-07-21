from __future__ import annotations

from app.agents.base import compact_json, invoke_json_response, make_result, trim_text
from app.graph.events import build_event
from app.graph.state import AcademicState


def _fallback_queries(state: AcademicState) -> list[str]:
    extracted = [item.get("value", "") for item in state.get("extracted_elements", []) if isinstance(item, dict)]
    extracted = [value for value in extracted if value]
    manual_context = state.get("metadata", {}).get("manual_context") or {}
    manual_hints = manual_context.get("suggestions", [])
    base_query = state["user_message"].strip()
    candidates = [
        base_query,
        " ".join(extracted[:4]).strip(),
        " ".join([base_query, *manual_hints[:2]]).strip(),
        f"{base_query} benchmark metric survey".strip(),
    ]
    unique: list[str] = []
    for query in candidates:
        normalized = " ".join(str(query).split())
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique[:5]


def run_search_planner_agent(state: AcademicState):
    fallback_queries = _fallback_queries(state)
    manual_context = state.get("metadata", {}).get("manual_context") or {}
    fallback = {
        "task_type": state.get("task_type") or "literature_review",
        "reasoning_summary": "使用启发式规则生成检索词。",
        "search_queries": fallback_queries,
        "needs_dynamic_route": False,
    }

    response = invoke_json_response(
        agent_name="SearchPlannerAgent",
        system_prompt=(
            "You are the search planning agent in a multi-agent academic workflow. "
            "Generate precise academic queries. "
            "Return JSON with task_type, reasoning_summary, search_queries, and needs_dynamic_route."
        ),
        user_prompt=(
            "基于用户目标、图表证据和历史上下文生成检索方案。\n"
            f"用户请求：\n{state['user_message']}\n"
            f"任务类型：{state.get('task_type')}\n"
            f"图表摘要：\n{state.get('chart_summary') or 'none'}\n"
            f"抽取元素：\n{compact_json(state.get('extracted_elements', []))}\n"
            f"上一轮人工介入上下文：\n{compact_json(manual_context)}\n"
            f"最近对话：\n{compact_json(state.get('conversation_history', [])[-4:])}"
        ),
        fallback=fallback,
    )

    queries = response.get("search_queries", fallback_queries)
    if not isinstance(queries, list):
        queries = fallback_queries

    normalized_queries: list[str] = []
    for query in queries:
        if not isinstance(query, str):
            continue
        cleaned = " ".join(query.split())
        if cleaned and cleaned not in normalized_queries:
            normalized_queries.append(cleaned)

    if not normalized_queries:
        normalized_queries = fallback_queries

    task_type = str(response.get("task_type", state.get("task_type") or "literature_review")).strip()
    reasoning_summary = str(response.get("reasoning_summary", fallback["reasoning_summary"])).strip()
    needs_dynamic_route = bool(response.get("needs_dynamic_route", False))

    notices = list(state.get("notices", []))
    if manual_context:
        notices.append(
            {
                "level": "info",
                "title": "已吸收你的补充线索",
                "message": "系统会把这轮输入和上轮建议一起用于检索词规划。",
                "suggestions": normalized_queries[:3],
            }
        )

    return make_result(
        state_updates={
            "current_agent": "search_planner_agent",
            "task_type": task_type,
            "search_queries": normalized_queries[:5],
            "pending_user_action": None,
            "notices": notices,
            "metadata": {
                "needs_dynamic_route": needs_dynamic_route,
                "manual_context": None,
            },
        },
        events=[
            build_event(
                "reasoning_summary",
                agent="search_planner_agent",
                message=trim_text(reasoning_summary, limit=220),
            ),
            build_event(
                "action_start",
                agent="search_planner_agent",
                tool="query_planner",
                input="根据任务意图、图表信息和上下文生成检索词。",
            ),
            build_event(
                "observation",
                agent="search_planner_agent",
                message=f"已准备 {len(normalized_queries[:5])} 组检索词。",
            ),
            build_event(
                "state_update",
                agent="search_planner_agent",
                changes={"task_type": task_type, "search_queries": normalized_queries[:5]},
            ),
        ],
    )
