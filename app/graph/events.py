from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.graph.state import AcademicState


PIPELINE_STAGES = [
    {"id": "intent_router", "label": "意图识别", "description": "识别任务类型并裁剪执行链路", "icon": "🧭"},
    {"id": "chart_react_agent", "label": "图表解析", "description": "抽取图表结构、指标和关键实体", "icon": "🧠"},
    {"id": "search_planner_agent", "label": "检索规划", "description": "生成和优化学术检索词", "icon": "🧩"},
    {"id": "literature_react_agent", "label": "文献检索", "description": "并行检索论文与补充资料", "icon": "🔍"},
    {"id": "evidence_review_agent", "label": "证据整理", "description": "对检索结果做相关性和置信度评估", "icon": "🧪"},
    {"id": "report_agent", "label": "结果汇总", "description": "生成最终结论和下一步建议", "icon": "📝"},
]

STAGE_LABELS = {stage["id"]: stage["label"] for stage in PIPELINE_STAGES}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, "timestamp": utc_timestamp(), **payload}


def serialize_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _stage_status(
    stage_id: str,
    *,
    plan: set[str],
    completed: set[str],
    current_agent: str | None,
    intent_resolved: bool,
    pending_user_action: dict[str, Any] | None,
) -> str:
    if stage_id == "intent_router":
        if intent_resolved:
            return "completed"
        if current_agent in {None, "orchestrator"}:
            return "active"
        return "pending"

    if stage_id not in plan:
        return "skipped"
    if stage_id in completed:
        return "completed"
    if current_agent == stage_id:
        return "active"
    if pending_user_action and stage_id in plan and stage_id not in completed:
        return "attention"
    return "pending"


def build_pipeline_view(state: AcademicState) -> list[dict[str, Any]]:
    metadata = state.get("metadata", {})
    completed = set(metadata.get("completed_agents", []))
    plan = set(state.get("execution_plan", []))
    current_agent = state.get("current_agent")
    intent_resolved = bool(metadata.get("intent_resolved"))
    pending_user_action = state.get("pending_user_action")

    nodes: list[dict[str, Any]] = []
    for stage in PIPELINE_STAGES:
        stage_id = stage["id"]
        nodes.append(
            {
                **stage,
                "status": _stage_status(
                    stage_id,
                    plan=plan,
                    completed=completed,
                    current_agent=current_agent,
                    intent_resolved=intent_resolved,
                    pending_user_action=pending_user_action,
                ),
            }
        )
    return nodes


def build_status_summary(state: AcademicState) -> str:
    pending_user_action = state.get("pending_user_action")
    if pending_user_action:
        return f"⚠️ {pending_user_action.get('title', '等待补充信息')}：{pending_user_action.get('message', '')}".strip()
    if state.get("final_answer"):
        return "✅ 已完成本轮任务，结果已整理到对话区。"
    current_agent = state.get("current_agent")
    if current_agent == "orchestrator" and not state.get("metadata", {}).get("intent_resolved"):
        return "🧭 正在识别任务意图并裁剪执行链路。"

    summaries = {
        "chart_react_agent": "🧠 正在解析图表结构与关键实体。",
        "search_planner_agent": "🧩 正在生成或优化检索词。",
        "literature_react_agent": "🔍 正在并行检索论文和补充资料。",
        "evidence_review_agent": "🧪 正在整理证据并评估可靠性。",
        "report_agent": "📝 正在汇总最终结论。",
    }

    if current_agent in summaries:
        completed = set(state.get("metadata", {}).get("completed_agents", []))
        prefix = []
        if "chart_react_agent" in completed:
            prefix.append("✅ 图表解析完成")
        if "literature_react_agent" in completed:
            prefix.append("✅ 文献检索完成")
        if "evidence_review_agent" in completed:
            prefix.append("✅ 证据整理完成")
        prefix_text = " → ".join(prefix[:2])
        if prefix_text:
            return f"{prefix_text} → {summaries[current_agent]}"
        return summaries[current_agent]

    if state.get("execution_plan"):
        return "⏳ 正在等待下一步执行。"
    return "准备接收任务。"


def public_state_view(state: AcademicState) -> dict[str, Any]:
    return {
        "thread_id": state["thread_id"],
        "intent": state.get("intent"),
        "intent_reason": state.get("intent_reason"),
        "task_type": state.get("task_type"),
        "current_agent": state.get("current_agent"),
        "next_agent": state.get("next_agent"),
        "execution_plan": state.get("execution_plan", []),
        "skipped_agents": state.get("skipped_agents", []),
        "chart_type": state.get("chart_type"),
        "chart_summary": state.get("chart_summary"),
        "extracted_elements": state.get("extracted_elements", []),
        "search_queries": state.get("search_queries", []),
        "papers": state.get("papers", []),
        "evidence_notes": state.get("evidence_notes", []),
        "pending_user_action": state.get("pending_user_action"),
        "notices": state.get("notices", []),
        "errors": state.get("errors", []),
        "metadata": state.get("metadata", {}),
        "route_history": state.get("route_history", []),
        "final_answer": state.get("final_answer"),
        "pipeline": build_pipeline_view(state),
        "status_summary": build_status_summary(state),
    }
