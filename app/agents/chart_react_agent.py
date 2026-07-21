from __future__ import annotations

from app.agents.base import compact_json, invoke_json_response, make_result, trim_text
from app.graph.events import build_event
from app.graph.state import AcademicState


def run_chart_react_agent(state: AcademicState):
    fallback = {
        "chart_type": "unknown",
        "chart_summary": "图像可见信息不足，系统回退到仅依据用户文本做保守判断。",
        "extracted_elements": [],
    }

    response = invoke_json_response(
        agent_name="ChartReActAgent",
        system_prompt=(
            "You analyze academic figures and charts. "
            "Extract only grounded information. Distinguish visible evidence from inference. "
            "Return JSON with chart_type, chart_summary, extracted_elements. "
            "Each extracted element must have category, value, visibility, and evidence."
        ),
        user_prompt=(
            f"用户请求：{state['user_message']}\n"
            f"图表类型提示：{state.get('chart_type_hint') or 'none'}\n"
            "如果图像模糊，请明确说明，并尽量给出保守、可见的要点。"
        ),
        image_url=state.get("image_url"),
        fallback=fallback,
    )

    chart_type = str(response.get("chart_type", "unknown")).strip() or "unknown"
    chart_summary = str(response.get("chart_summary", fallback["chart_summary"])).strip()
    extracted_elements = response.get("extracted_elements", [])
    if not isinstance(extracted_elements, list):
        extracted_elements = []

    notices = list(state.get("notices", []))
    if chart_type == "unknown" and not extracted_elements:
        notices.append(
            {
                "level": "warning",
                "title": "图表解析不充分",
                "message": "图像可能过于模糊或缺少关键区域，建议更换更清晰的图表后重试。",
                "suggestions": ["重新上传更清晰的图表", "手动补充图中方法名、指标名、数据集名"],
            }
        )

    return make_result(
        state_updates={
            "current_agent": "chart_react_agent",
            "chart_type": chart_type,
            "chart_summary": chart_summary,
            "extracted_elements": extracted_elements,
            "notices": notices,
        },
        events=[
            build_event(
                "reasoning_summary",
                agent="chart_react_agent",
                message="先把图表中的结构、方法、指标和数据集抽出来，为后续裁剪或检索提供依据。",
            ),
            build_event(
                "action_start",
                agent="chart_react_agent",
                tool="vision_model",
                input="解析上传图表，抽取方法、指标、数据集和趋势。",
            ),
            build_event(
                "observation",
                agent="chart_react_agent",
                message=trim_text(chart_summary, limit=260),
            ),
            build_event(
                "state_update",
                agent="chart_react_agent",
                changes={
                    "chart_type": chart_type,
                    "chart_summary": chart_summary,
                    "extracted_elements": extracted_elements,
                },
                preview=compact_json(
                    {
                        "chart_type": chart_type,
                        "extracted_count": len(extracted_elements),
                    }
                ),
            ),
        ],
    )
