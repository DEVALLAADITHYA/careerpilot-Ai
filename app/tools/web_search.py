"""Live web search. Default provider: DuckDuckGo (no API key). Optional: Tavily (SEARCH_PROVIDER=tavily)."""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
TAVILY_URL = "https://api.tavily.com/search"


class SearchError(RuntimeError):
    pass


def _timelimit(days: int | None) -> str | None:
    if not days:
        return None
    return "d" if days <= 1 else "w" if days <= 7 else "m" if days <= 31 else "y"


def _ddg_sync(query: str, max_results: int, days: int | None) -> list[dict]:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
    try:
        rows = DDGS().text(query, max_results=max_results, timelimit=_timelimit(days))
    except DDGSException as e:
        if "no results" in str(e).lower():
            return []
        raise SearchError(f"DuckDuckGo search failed: {str(e)[:150]}") from e
    return [{"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""), "content": r.get("body", "")}
            for r in rows or []]


async def ddg_search(query: str, *, max_results: int = 8, days: int | None = None,
                     retries: int = 2, backoff_base: float = 1.0) -> list[dict]:
    for attempt in range(retries + 1):
        try:
            return await asyncio.to_thread(_ddg_sync, query, max_results, days)
        except SearchError as e:
            if attempt == retries:
                raise
            log.warning("DuckDuckGo error, retrying (%s/%s): %s", attempt + 1, retries, e)
            await asyncio.sleep(backoff_base * 2 ** attempt)
        except ImportError as e:
            raise SearchError("Package 'ddgs' is not installed. Run: pip install ddgs") from e
        except Exception as e:  # network/library errors
            if attempt == retries:
                raise SearchError(f"DuckDuckGo request failed: {type(e).__name__}") from e
            await asyncio.sleep(backoff_base * 2 ** attempt)
    return []


async def tavily_search(query: str, *, max_results: int = 8, client: httpx.AsyncClient | None = None,
                        retries: int = 2, backoff_base: float = 1.0) -> list[dict]:
    s = get_settings()
    if not s.tavily_api_key:
        raise SearchError("TAVILY_API_KEY is not configured. Add it to your .env file.")
    own = client is None
    client = client or httpx.AsyncClient(timeout=s.http_timeout * 2)
    payload = {"query": query, "search_depth": "basic", "max_results": max_results,
               "include_answer": False, "include_raw_content": False}
    headers = {"Authorization": f"Bearer {s.tavily_api_key}", "Content-Type": "application/json"}
    try:
        for attempt in range(retries + 1):
            try:
                r = await client.post(TAVILY_URL, json=payload, headers=headers)
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise SearchError(f"Tavily request failed: {type(e).__name__}") from e
                await asyncio.sleep(backoff_base * 2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json().get("results", [])
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(backoff_base * 2 ** attempt)
                continue
            raise SearchError(f"Tavily returned HTTP {r.status_code}")
        raise SearchError("Tavily search failed")
    finally:
        if own:
            await client.aclose()


async def web_search(query: str, *, max_results: int = 8, days: int | None = None) -> list[dict]:
    """Provider-agnostic entry point used by the Job Search Agent."""
    if get_settings().search_provider == "tavily":
        return await tavily_search(query, max_results=max_results)
    return await ddg_search(query, max_results=max_results, days=days)
