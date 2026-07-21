from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.chart_react_agent import run_chart_react_agent
from app.agents.evidence_review_agent import run_evidence_review_agent
from app.agents.literature_react_agent import run_literature_react_agent
from app.agents.orchestrator import run_orchestrator
from app.agents.report_agent import run_report_agent
from app.agents.search_planner_agent import run_search_planner_agent
from app.graph.state import AcademicState


def _orchestrator_node(state: AcademicState):
    return run_orchestrator(state)["state_updates"]


def _chart_node(state: AcademicState):
    return run_chart_react_agent(state)["state_updates"]


def _search_planner_node(state: AcademicState):
    return run_search_planner_agent(state)["state_updates"]


def _literature_node(state: AcademicState):
    return run_literature_react_agent(state)["state_updates"]


def _evidence_node(state: AcademicState):
    return run_evidence_review_agent(state)["state_updates"]


def _report_node(state: AcademicState):
    return run_report_agent(state)["state_updates"]


def _route_next_agent(state: AcademicState):
    return state.get("next_agent") or "end"


builder = StateGraph(AcademicState)
builder.add_node("orchestrator", _orchestrator_node)
builder.add_node("chart_react_agent", _chart_node)
builder.add_node("search_planner_agent", _search_planner_node)
builder.add_node("literature_react_agent", _literature_node)
builder.add_node("evidence_review_agent", _evidence_node)
builder.add_node("report_agent", _report_node)
builder.set_entry_point("orchestrator")
builder.add_conditional_edges(
    "orchestrator",
    _route_next_agent,
    {
        "chart_react_agent": "chart_react_agent",
        "search_planner_agent": "search_planner_agent",
        "literature_react_agent": "literature_react_agent",
        "evidence_review_agent": "evidence_review_agent",
        "report_agent": "report_agent",
        "end": END,
    },
)
builder.add_edge("chart_react_agent", "orchestrator")
builder.add_edge("search_planner_agent", "orchestrator")
builder.add_edge("literature_react_agent", "orchestrator")
builder.add_edge("evidence_review_agent", "orchestrator")
builder.add_edge("report_agent", END)

graph = builder.compile()
