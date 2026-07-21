from __future__ import annotations

from statistics import mean

from app.agents.base import compact_json, invoke_json_response, make_result
from app.graph.events import build_event
from app.graph.state import AcademicState


def _fallback_notes(state: AcademicState, papers: list[dict]) -> list[dict]:
    notes: list[dict] = []
    for paper in papers[: state.get("top_k", 5)]:
        notes.append(
            {
                "title": paper.get("title"),
                "relevance_score": round(float(paper.get("score") or 0), 3),
                "reason": "按词面相关性、引用量和年份做了初步排序。",
                "evidence_strength": "medium",
                "risk": "仍建议人工核验摘要和方法细节。",
            }
        )
    return notes


def _average_confidence(notes: list[dict]) -> float:
    if not notes:
        return 0.0
    scores = []
    for note in notes:
        try:
            scores.append(float(note.get("relevance_score") or 0))
        except (TypeError, ValueError):
            continue
    if not scores:
        return 0.0
    return round(mean(scores), 3)


def run_evidence_review_agent(state: AcademicState):
    ranked_papers = sorted(
        state.get("papers", []),
        key=lambda paper: (
            float(paper.get("score") or 0),
            int(paper.get("citations") or 0),
            int(paper.get("year") or 0),
        ),
        reverse=True,
    )
    candidate_papers = ranked_papers[: max(state.get("top_k", 5), 5)]
    fallback_notes = _fallback_notes(state, candidate_papers)

    response = invoke_json_response(
        agent_name="EvidenceReviewAgent",
        system_prompt=(
            "You review literature evidence for an academic assistant. "
            "Return JSON with evidence_notes. "
            "Each note must include title, relevance_score, reason, evidence_strength, and risk."
        ),
        user_prompt=(
            f"用户请求：\n{state['user_message']}\n"
            f"任务类型：{state.get('task_type')}\n"
            f"图表摘要：\n{state.get('chart_summary') or 'none'}\n"
            f"候选文献：\n{compact_json(candidate_papers)}"
        ),
        fallback={"evidence_notes": fallback_notes},
    )

    evidence_notes = response.get("evidence_notes", fallback_notes)
    if not isinstance(evidence_notes, list):
        evidence_notes = fallback_notes
    evidence_notes = evidence_notes[: state.get("top_k", 5)]
    confidence = _average_confidence(evidence_notes)

    pending_user_action = None
    notices = list(state.get("notices", []))
    if confidence < 0.56:
        pending_user_action = {
            "type": "manual_intervention",
            "title": "证据置信度偏低",
            "message": "已有文献和任务目标的匹配度偏低，建议你补充更具体的方法名、数据集或手动筛掉明显不相关的论文后继续。",
            "suggestions": [
                paper.get("title")
                for paper in candidate_papers[:3]
                if paper.get("title")
            ],
        }
        notices.append(
            {
                "level": "warning",
                "title": pending_user_action["title"],
                "message": pending_user_action["message"],
                "suggestions": pending_user_action["suggestions"],
            }
        )

    return make_result(
        state_updates={
            "current_agent": "evidence_review_agent",
            "papers": candidate_papers,
            "evidence_notes": evidence_notes,
            "pending_user_action": pending_user_action,
            "notices": notices,
            "metadata": {
                "needs_dynamic_route": bool(pending_user_action),
                "evidence_confidence": confidence,
            },
        },
        events=[
            build_event(
                "reasoning_summary",
                agent="evidence_review_agent",
                message="对候选文献做相关性梳理，并检查整体证据置信度。",
            ),
            build_event(
                "action_start",
                agent="evidence_review_agent",
                tool="evidence_ranking",
                input=f"Review {len(candidate_papers)} papers against the current task.",
            ),
            build_event(
                "observation",
                agent="evidence_review_agent",
                message=f"已生成 {len(evidence_notes)} 条证据说明，平均置信度 {confidence:.2f}。",
            ),
            *(
                [
                    build_event(
                        "user_action_required",
                        agent="evidence_review_agent",
                        title=pending_user_action["title"],
                        message=pending_user_action["message"],
                        suggestions=pending_user_action["suggestions"],
                    )
                ]
                if pending_user_action
                else []
            ),
            build_event(
                "state_update",
                agent="evidence_review_agent",
                changes={"evidence_notes": evidence_notes},
            ),
        ],
    )
