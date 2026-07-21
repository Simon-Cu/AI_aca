from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from app.agents.base import compact_json, invoke_json_response, make_result
from app.common.settings import ConfigurationError
from app.graph.events import build_event
from app.graph.state import AcademicState
from app.tools.academic_search import run_academic_web_search, search_openalex_papers_raw


NETWORK_RETRIES = 2


def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for paper in papers:
        key = (paper.get("title") or paper.get("url") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique


def _is_network_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("timed out", "timeout", "temporary", "connection", "reset", "503", "502"))


def _call_with_retry(
    func: Callable[[str], list[dict]],
    query: str,
    *,
    retries: int = NETWORK_RETRIES,
) -> tuple[list[dict], list[str], int]:
    errors: list[str] = []
    attempts = 0
    while True:
        attempts += 1
        try:
            return func(query), errors, attempts
        except Exception as exc:
            errors.append(str(exc))
            if attempts > retries or not _is_network_error(exc):
                return [], errors, attempts
            time.sleep(0.35 * attempts)


def _parallel_query_batch(
    queries: list[str],
    search_func: Callable[[str], list[dict]],
) -> list[dict]:
    if not queries:
        return []

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as executor:
        future_to_query = {executor.submit(_call_with_retry, search_func, query): query for query in queries}
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            papers, errors, attempts = future.result()
            results.append(
                {
                    "query": query,
                    "papers": papers,
                    "errors": errors,
                    "attempts": attempts,
                }
            )
    return results


def _build_refined_queries(state: AcademicState, queries: list[str]) -> list[str]:
    extracted = [
        item.get("value", "")
        for item in state.get("extracted_elements", [])
        if isinstance(item, dict) and item.get("category") in {"method", "dataset", "metric", "claim"}
    ]
    extracted = [value for value in extracted if value]
    fallback: list[str] = []
    for query in queries[:2]:
        refined = " ".join([query, *extracted[:3], "benchmark survey"]).strip()
        cleaned = " ".join(refined.split())
        if cleaned and cleaned not in fallback:
            fallback.append(cleaned)

    response = invoke_json_response(
        agent_name="QueryRefiner",
        system_prompt=(
            "You refine academic search queries after a weak first retrieval pass. "
            "Return JSON with refined_queries."
        ),
        user_prompt=(
            f"原始查询：\n{compact_json(queries)}\n"
            f"图表摘要：{state.get('chart_summary') or 'none'}\n"
            f"图表实体：\n{compact_json(extracted)}\n"
            "请输出 2-4 条更聚焦、更具学术语义的英文检索词。"
        ),
        fallback={"refined_queries": fallback},
    )
    refined_queries = response.get("refined_queries", fallback)
    normalized: list[str] = []
    if isinstance(refined_queries, list):
        for query in refined_queries:
            if not isinstance(query, str):
                continue
            cleaned = " ".join(query.split())
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
    return normalized or fallback


def _user_action_payload(title: str, message: str, suggestions: list[str]) -> dict:
    return {
        "type": "manual_intervention",
        "title": title,
        "message": message,
        "suggestions": suggestions[:4],
    }


def run_literature_react_agent(state: AcademicState):
    queries = list(state.get("search_queries", []))[:4]
    events: list[dict] = [
        build_event(
            "reasoning_summary",
            agent="literature_react_agent",
            message="先并行检索主数据源；若结果不足，则优化检索词后二次检索，再考虑网页补充。",
        )
    ]

    events.append(
        build_event(
            "action_start",
            agent="literature_react_agent",
            tool="parallel_openalex_batch",
            input=compact_json(queries),
        )
    )
    initial_batches = _parallel_query_batch(queries, search_openalex_papers_raw)
    initial_papers = _deduplicate_papers(
        [paper for batch in initial_batches for paper in batch["papers"]]
    )
    network_retry_count = sum(max(batch["attempts"] - 1, 0) for batch in initial_batches)
    for batch in initial_batches:
        events.append(
            build_event(
                "observation",
                agent="literature_react_agent",
                message=f"OpenAlex 并行检索：{batch['query']} 命中 {len(batch['papers'])} 条，重试 {max(batch['attempts'] - 1, 0)} 次。",
            )
        )

    target_floor = max(2, min(state.get("top_k", 5), 3))
    refined_queries: list[str] = []
    combined_papers = initial_papers

    if len(initial_papers) < target_floor:
        events.append(
            build_event(
                "branch_decision",
                agent="literature_react_agent",
                condition="low_recall",
                message="首轮检索结果不足，触发检索词优化和二次并行检索。",
            )
        )
        refined_queries = _build_refined_queries(state, queries)
        events.append(
            build_event(
                "action_start",
                agent="literature_react_agent",
                tool="query_refinement",
                input=compact_json(refined_queries),
            )
        )
        refined_batches = _parallel_query_batch(refined_queries, search_openalex_papers_raw)
        refined_papers = _deduplicate_papers(
            [paper for batch in refined_batches for paper in batch["papers"]]
        )
        network_retry_count += sum(max(batch["attempts"] - 1, 0) for batch in refined_batches)
        for batch in refined_batches:
            events.append(
                build_event(
                    "observation",
                    agent="literature_react_agent",
                    message=f"二次检索：{batch['query']} 命中 {len(batch['papers'])} 条。",
                )
            )
        queries = list(dict.fromkeys([*queries, *refined_queries]))
        combined_papers = _deduplicate_papers([*initial_papers, *refined_papers])

    web_search_used = False
    web_results: list[dict] = []
    if len(combined_papers) < target_floor:
        try:
            supplemental_queries = (refined_queries or queries)[:2]
            events.append(
                build_event(
                    "action_start",
                    agent="literature_react_agent",
                    tool="parallel_web_search",
                    input=compact_json(supplemental_queries),
                )
            )
            web_batches = _parallel_query_batch(supplemental_queries, run_academic_web_search)
            web_results = _deduplicate_papers(
                [paper for batch in web_batches for paper in batch["papers"]]
            )
            web_search_used = True
            for batch in web_batches:
                events.append(
                    build_event(
                        "observation",
                        agent="literature_react_agent",
                        message=f"网页补充检索：{batch['query']} 返回 {len(batch['papers'])} 条。",
                    )
                )
            combined_papers = _deduplicate_papers([*combined_papers, *web_results])
        except ConfigurationError as exc:
            events.append(
                build_event(
                    "user_notice",
                    agent="literature_react_agent",
                    level="warning",
                    title="未启用网页补充检索",
                    message=str(exc),
                    suggestions=["如需网页兜底，请补充 TAVILY_API_KEY。"],
                )
            )

    sorted_papers = sorted(
        combined_papers,
        key=lambda paper: (
            float(paper.get("score") or 0),
            int(paper.get("citations") or 0),
            int(paper.get("year") or 0),
        ),
        reverse=True,
    )[: max(state.get("top_k", 5), 5)]

    pending_user_action = None
    notices = list(state.get("notices", []))
    if len(sorted_papers) < target_floor:
        pending_user_action = _user_action_payload(
            "检索结果不足",
            "两轮学术检索后仍缺少足够高相关文献，建议你补充方法名、数据集、指标名，或手动给出候选关键词后继续。",
            refined_queries or queries,
        )
        notices.append(
            {
                "level": "warning",
                "title": "检索结果不足",
                "message": pending_user_action["message"],
                "suggestions": pending_user_action["suggestions"],
            }
        )
        events.append(
            build_event(
                "user_action_required",
                agent="literature_react_agent",
                title=pending_user_action["title"],
                message=pending_user_action["message"],
                suggestions=pending_user_action["suggestions"],
            )
        )

    parallel_sources = ["OpenAlex"]
    if web_search_used:
        parallel_sources.append("Tavily")

    return make_result(
        state_updates={
            "current_agent": "literature_react_agent",
            "search_queries": queries,
            "papers": sorted_papers,
            "pending_user_action": pending_user_action,
            "notices": notices,
            "metadata": {
                "search_iterations": int(state.get("metadata", {}).get("search_iterations", 0)) + 1,
                "query_refinement_count": int(state.get("metadata", {}).get("query_refinement_count", 0))
                + (1 if refined_queries else 0),
                "network_retry_count": int(state.get("metadata", {}).get("network_retry_count", 0))
                + network_retry_count,
                "parallel_sources_used": parallel_sources,
                "web_search_used": web_search_used,
                "needs_dynamic_route": bool(pending_user_action),
                "degraded_mode": bool(pending_user_action),
            },
        },
        events=events
        + [
            build_event(
                "state_update",
                agent="literature_react_agent",
                changes={"papers": sorted_papers, "search_queries": queries},
            )
        ],
    )
