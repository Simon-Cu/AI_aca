from __future__ import annotations

from typing import Any

from app.agents.base import compact_json, invoke_json_response, make_result
from app.graph.events import STAGE_LABELS, build_event
from app.graph.state import AcademicState


AGENT_NAMES = (
    "chart_react_agent",
    "search_planner_agent",
    "literature_react_agent",
    "evidence_review_agent",
    "report_agent",
    "end",
)

INTENT_PROFILES = {
    "chart_only": {
        "task_type": "chart_understanding",
        "execution_plan": ["chart_react_agent", "report_agent"],
        "skipped_agents": ["search_planner_agent", "literature_react_agent", "evidence_review_agent"],
    },
    "literature_only": {
        "task_type": "literature_review",
        "execution_plan": [
            "search_planner_agent",
            "literature_react_agent",
            "evidence_review_agent",
            "report_agent",
        ],
        "skipped_agents": ["chart_react_agent"],
    },
    "chart_and_literature": {
        "task_type": "chart_and_literature_review",
        "execution_plan": [
            "chart_react_agent",
            "search_planner_agent",
            "literature_react_agent",
            "evidence_review_agent",
            "report_agent",
        ],
        "skipped_agents": [],
    },
}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _heuristic_intent_profile(state: AcademicState) -> dict[str, Any]:
    text = state["user_message"].lower()
    has_image = bool(state.get("image_url"))
    manual_context = state.get("metadata", {}).get("manual_context")

    literature_keywords = (
        "paper",
        "papers",
        "literature",
        "survey",
        "reference",
        "citation",
        "related work",
        "论文",
        "文献",
        "相关工作",
        "综述",
        "检索",
        "调研",
        "引用",
    )
    chart_keywords = (
        "chart",
        "figure",
        "plot",
        "diagram",
        "axis",
        "metric",
        "图",
        "图表",
        "曲线",
        "柱状",
        "趋势",
        "横轴",
        "纵轴",
        "指标",
        "解读",
        "解析",
    )
    explanation_keywords = ("explain", "interpret", "summarize", "analyze", "解释", "解读", "分析", "总结")

    wants_literature = _contains_any(text, literature_keywords)
    wants_chart_reading = has_image or _contains_any(text, chart_keywords) or _contains_any(text, explanation_keywords)

    if manual_context:
        intent = "literature_only"
        reason = "上一轮停在人工介入节点，本轮优先继续检索和证据整理。"
    elif has_image and wants_literature:
        intent = "chart_and_literature"
        reason = "用户同时提供图表并要求检索论文，需要走完整链路。"
    elif has_image or wants_chart_reading:
        intent = "chart_only"
        reason = "当前任务以图表解读为主，可跳过文献检索与证据审核。"
    else:
        intent = "literature_only"
        reason = "当前任务以文献调研或学术检索为主，无需图表解析。"

    return {"intent": intent, "reason": reason, **INTENT_PROFILES[intent], "confidence": 0.86}


def _resolve_intent_profile(state: AcademicState) -> tuple[dict[str, Any], list[dict]]:
    metadata = state.get("metadata", {})
    if metadata.get("intent_resolved") and state.get("intent"):
        profile = {
            "intent": state["intent"],
            "reason": state.get("intent_reason") or "",
            "task_type": state.get("task_type"),
            "execution_plan": state.get("execution_plan", []),
            "skipped_agents": state.get("skipped_agents", []),
            "confidence": 1.0,
        }
        return profile, []

    fallback = _heuristic_intent_profile(state)
    ambiguous = bool(state.get("image_url")) and not _contains_any(
        state["user_message"].lower(),
        ("论文", "文献", "paper", "literature", "related", "survey", "解读", "解释", "analyze", "interpret"),
    )

    if ambiguous:
        response = invoke_json_response(
            agent_name="IntentRouter",
            system_prompt=(
                "You are an intent classifier for an academic workflow router. "
                "Choose one intent: chart_only, literature_only, chart_and_literature. "
                "Return JSON with intent, reason, task_type, execution_plan, skipped_agents, confidence."
            ),
            user_prompt=(
                f"User request:\n{state['user_message']}\n"
                f"Has image: {bool(state.get('image_url'))}\n"
                f"Existing chart summary: {state.get('chart_summary') or 'none'}\n"
                f"Fallback profile:\n{compact_json(fallback)}"
            ),
            fallback=fallback,
        )
        intent = response.get("intent", fallback["intent"])
        profile = {
            "intent": intent,
            "reason": str(response.get("reason", fallback["reason"])).strip() or fallback["reason"],
            "task_type": str(response.get("task_type", INTENT_PROFILES[intent]["task_type"])).strip()
            or INTENT_PROFILES[intent]["task_type"],
            "execution_plan": response.get("execution_plan", INTENT_PROFILES[intent]["execution_plan"]),
            "skipped_agents": response.get("skipped_agents", INTENT_PROFILES[intent]["skipped_agents"]),
            "confidence": float(response.get("confidence", fallback["confidence"])),
        }
        route_mode = "dynamic"
    else:
        profile = fallback
        route_mode = "static"

    events = [
        build_event(
            "intent_decision",
            agent="orchestrator",
            mode=route_mode,
            intent=profile["intent"],
            reason=profile["reason"],
            confidence=round(float(profile.get("confidence", 0.86)), 3),
            execution_plan=profile["execution_plan"],
            skipped_agents=profile["skipped_agents"],
        )
    ]
    return profile, events


def _plan_labels(plan: list[str]) -> str:
    return " → ".join(STAGE_LABELS.get(stage, stage) for stage in plan)


def _static_route(state: AcademicState) -> tuple[str, str, float]:
    if state.get("final_answer"):
        return "end", "最终结果已经生成。", 1.0

    if state.get("pending_user_action") and "report_agent" not in state.get("metadata", {}).get("completed_agents", []):
        return "report_agent", "当前流程需要先向用户给出失败原因和补充建议。", 0.98

    step_count = int(state.get("metadata", {}).get("step_count", 0))
    max_steps = int(state.get("max_steps", 8))
    if step_count >= max_steps:
        if state.get("papers") or state.get("chart_summary"):
            return "report_agent", "达到步骤上限，先输出当前可用结论。", 0.92
        return "end", "达到步骤上限且缺少可用结果，结束本轮。", 0.9

    completed = set(state.get("metadata", {}).get("completed_agents", []))
    for stage in state.get("execution_plan", []):
        if stage not in completed:
            return stage, f"按裁剪后的执行链路推进到“{STAGE_LABELS.get(stage, stage)}”。", 0.96

    return "end", "执行链路中的节点都已完成。", 1.0


def _dynamic_route(state: AcademicState) -> tuple[str, str, float]:
    fallback_agent, fallback_reason, fallback_confidence = _static_route(state)
    fallback = {
        "next_agent": fallback_agent,
        "reason": fallback_reason,
        "confidence": fallback_confidence,
    }
    response = invoke_json_response(
        agent_name="DynamicRouter",
        system_prompt=(
            "You are the fallback router for a multi-agent academic assistant. "
            "Choose one next_agent from chart_react_agent, search_planner_agent, "
            "literature_react_agent, evidence_review_agent, report_agent, end."
        ),
        user_prompt=(
            "根据共享状态选择下一步最合适的节点。\n"
            f"""当前共享状态摘要：
        {compact_json({
                'intent': state.get('intent'),
                'task_type': state.get('task_type'),
                'execution_plan': state.get('execution_plan', []),
                'completed_agents': state.get('metadata', {}).get('completed_agents', []),
                'chart_summary': state.get('chart_summary'),
                'search_queries': state.get('search_queries', []),
                'paper_count': len(state.get('papers', [])),
                'evidence_count': len(state.get('evidence_notes', [])),
                'pending_user_action': state.get('pending_user_action'),
                'errors': state.get('errors', []),
                'metadata': state.get('metadata', {}),
            })}
        """
            f"静态兜底方案：{compact_json(fallback)}\n"
            "返回 JSON：next_agent, reason, confidence。"
        ),
        fallback=fallback,
    )

    next_agent = response.get("next_agent", fallback_agent)
    if next_agent not in AGENT_NAMES:
        next_agent = fallback_agent
    reason = str(response.get("reason", fallback_reason)).strip() or fallback_reason
    try:
        confidence = float(response.get("confidence", fallback_confidence))
    except (TypeError, ValueError):
        confidence = fallback_confidence
    return next_agent, reason, confidence


def run_orchestrator(state: AcademicState):
    profile, intent_events = _resolve_intent_profile(state)
    metadata = {**state.get("metadata", {})}
    metadata["intent_resolved"] = True

    use_dynamic = bool(metadata.get("needs_dynamic_route"))
    if use_dynamic:
        next_agent, reason, confidence = _dynamic_route(state)
        route_mode = "dynamic"
        metadata["needs_dynamic_route"] = False
    else:
        next_agent, reason, confidence = _static_route(
            {
                **state,
                "intent": profile["intent"],
                "intent_reason": profile["reason"],
                "task_type": profile["task_type"],
                "execution_plan": profile["execution_plan"],
                "skipped_agents": profile["skipped_agents"],
                "metadata": metadata,
            }
        )
        route_mode = "static"

    route_history = list(state.get("route_history", []))
    route_history.append(
        {
            "from": state.get("current_agent") or "user",
            "to": next_agent,
            "mode": route_mode,
            "reason": reason,
            "confidence": round(confidence, 3),
        }
    )

    events = [
        *intent_events,
        build_event(
            "reasoning_summary",
            agent="orchestrator",
            message=f"已识别为“{profile['task_type']}”，执行链路为：{_plan_labels(profile['execution_plan'])}。",
        ),
        build_event(
            "route_decision",
            agent="orchestrator",
            next_agent=next_agent,
            mode=route_mode,
            reason=reason,
            confidence=round(confidence, 3),
        ),
    ]

    return make_result(
        state_updates={
            "intent": profile["intent"],
            "intent_reason": profile["reason"],
            "task_type": profile["task_type"],
            "execution_plan": profile["execution_plan"],
            "skipped_agents": profile["skipped_agents"],
            "current_agent": "orchestrator",
            "next_agent": next_agent,
            "route_history": route_history,
            "metadata": metadata,
        },
        events=events,
    )
