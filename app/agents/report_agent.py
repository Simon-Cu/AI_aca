from __future__ import annotations

from app.agents.base import compact_json, invoke_text_response, make_result
from app.graph.events import build_event
from app.graph.state import AcademicState


def _fallback_report(state: AcademicState) -> str:
    intent = state.get("intent")
    pending = state.get("pending_user_action")
    lines = []

    if pending:
        lines.extend(
            [
                "## 当前状态",
                f"本轮流程停在“{pending.get('title', '人工介入')}”节点。",
                "",
                "## 失败原因",
                pending.get("message", "需要你提供更多线索后再继续。"),
                "",
                "## 建议操作",
            ]
        )
        for suggestion in pending.get("suggestions", []) or ["补充更具体的关键词后重试。"]:
            lines.append(f"- {suggestion}")
        return "\n".join(lines).strip()

    lines.extend(["## 任务摘要"])
    if intent == "chart_only":
        lines.append(state.get("chart_summary") or "未生成图表摘要。")
    else:
        lines.append(state.get("chart_summary") or "已根据用户请求完成检索与整理。")

    lines.extend(
        [
            "",
            "## 关键元素",
            compact_json(state.get("extracted_elements", [])),
        ]
    )

    if state.get("search_queries"):
        lines.extend(["", "## 检索词", *[f"- {query}" for query in state.get("search_queries", [])]])

    if state.get("papers"):
        lines.append("")
        lines.append("## 推荐文献")
        lines.extend(
            [
                f"- {paper.get('title')} ({paper.get('year') or 'n/a'}) - {paper.get('url')}"
                for paper in state.get("papers", [])[: state.get("top_k", 5)]
            ]
        )

    if state.get("evidence_notes"):
        lines.append("")
        lines.append("## 证据说明")
        lines.extend(
            [
                f"- {note.get('title')}: {note.get('reason')}"
                for note in state.get("evidence_notes", [])[: state.get("top_k", 5)]
            ]
        )

    lines.extend(
        [
            "",
            "## 下一步",
            "- 继续追问某篇论文的细节或方法差异。",
            "- 指定某个指标、方法或数据集做更窄的检索。",
        ]
    )
    return "\n".join(lines).strip()


def run_report_agent(state: AcademicState):
    fallback_report = _fallback_report(state)
    pending_user_action = state.get("pending_user_action")

    if pending_user_action:
        final_answer = fallback_report
    else:
        intent = state.get("intent")
        report_instruction = {
            "chart_only": "请重点输出图表解读结论、关键元素、可继续追问的问题。",
            "literature_only": "请重点输出检索词、推荐文献、推荐理由、可靠性说明和后续建议。",
            "chart_and_literature": "请同时覆盖图表解读与文献推荐，并明确两者的关系。",
        }.get(intent, "请输出完整的总结。")

        try:
            final_answer = invoke_text_response(
                system_prompt=(
                    "你是学术图表理解与文献调研系统的最终报告智能体。"
                    "请使用简洁中文，输出 markdown。"
                    "根据任务意图，只保留有价值的段落，不必机械输出所有章节。"
                ),
                user_prompt=(
                    f"{report_instruction}\n\n"
                    f"用户请求：\n{state['user_message']}\n"
                    f"任务类型：{state.get('task_type')}\n"
                    f"图表摘要：\n{state.get('chart_summary') or 'none'}\n"
                    f"抽取元素：\n{compact_json(state.get('extracted_elements', []))}\n"
                    f"检索词：\n{compact_json(state.get('search_queries', []))}\n"
                    f"文献：\n{compact_json(state.get('papers', [])[: state.get('top_k', 5)])}\n"
                    f"证据说明：\n{compact_json(state.get('evidence_notes', [])[: state.get('top_k', 5)])}\n"
                    f"注意事项：\n{compact_json(state.get('notices', []))}"
                ),
            )
        except Exception:
            final_answer = fallback_report

    return make_result(
        state_updates={
            "current_agent": "report_agent",
            "final_answer": final_answer or fallback_report,
            "next_agent": "end",
        },
        events=[
            build_event(
                "reasoning_summary",
                agent="report_agent",
                message="把当前共享状态整理成用户可直接消费的中文结论。",
            ),
            build_event(
                "action_start",
                agent="report_agent",
                tool="report_generator",
                input="根据共享状态输出中文总结与建议。",
            ),
            build_event(
                "observation",
                agent="report_agent",
                message="最终报告已整理完毕。",
            ),
        ],
    )
