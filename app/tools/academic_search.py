from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import urlopen

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from app.common.settings import ConfigurationError, get_settings, load_environment

load_environment()


def _keyword_overlap(query: str, text: str) -> float:
    keywords = [word.lower() for word in query.split() if len(word) > 2]
    if not keywords:
        return 0.5
    hits = sum(1 for word in keywords if word in text.lower())
    return hits / len(keywords)


def _recover_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    max_pos = max(pos for positions in inverted_index.values() for pos in positions)
    words = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(word for word in words if word)


def search_openalex_papers_raw(query: str, per_page: int = 8) -> list[dict]:
    url = f"https://api.openalex.org/works?{urlencode({'search': query, 'per-page': per_page})}"
    with urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    current_year = datetime.now().year
    ranked = []

    for item in payload.get("results", []):
        abstract = _recover_abstract(item.get("abstract_inverted_index"))
        title = item.get("display_name", "")
        year = item.get("publication_year") or current_year - 10
        citations = item.get("cited_by_count") or 0
        text = f"{title} {abstract}"

        relevance = _keyword_overlap(query, text)
        citation_score = min(citations / 500, 1.0)
        recency_score = max(0.0, 1 - min(current_year - year, 10) / 10)
        score = round(relevance * 0.5 + citation_score * 0.3 + recency_score * 0.2, 4)

        ranked.append(
            {
                "title": title,
                "year": year,
                "citations": citations,
                "url": item.get("primary_location", {}).get("landing_page_url") or item.get("id"),
                "abstract": abstract[:500],
                "score": score,
                "source": "openalex",
                "matched_query": query,
            }
        )

    ranked.sort(key=lambda paper: paper["score"], reverse=True)
    return ranked[:5]


@lru_cache(maxsize=1)
def _get_tavily_tool() -> TavilySearch:
    settings = get_settings()
    if not settings.tavily_api_key:
        raise ConfigurationError(
            "Missing TAVILY_API_KEY. Fill it in the project root .env if you want web fallback search."
        )
    return TavilySearch(
        max_results=5,
        topic="general",
        tavily_api_key=settings.tavily_api_key,
    )


def run_academic_web_search(query: str, max_results: int = 5) -> list[dict]:
    tool_instance = _get_tavily_tool()
    payload = tool_instance.invoke({"query": query})

    if isinstance(payload, dict):
        results = payload.get("results") or payload.get("items") or []
    elif isinstance(payload, list):
        results = payload
    else:
        results = []

    normalized = []
    for item in results[:max_results]:
        normalized.append(
            {
                "title": item.get("title", ""),
                "year": item.get("published_date") or item.get("year"),
                "citations": None,
                "url": item.get("url", ""),
                "abstract": item.get("content") or item.get("snippet") or "",
                "score": 0.45,
                "source": "tavily",
                "matched_query": query,
            }
        )
    return normalized


@tool
def search_openalex_papers(query: str) -> str:
    """Search OpenAlex for papers related to an academic chart, method, metric, or dataset."""
    return json.dumps(search_openalex_papers_raw(query), ensure_ascii=False)


@tool
def academic_web_search(query: str) -> str:
    """Search the broader web for academic context, project pages, surveys, and code resources."""
    return json.dumps(run_academic_web_search(query), ensure_ascii=False)
