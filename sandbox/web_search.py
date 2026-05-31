"""Web search adapter — currently Tavily; built so other providers can slot in.

Tavily is the default because it is purpose-built for AI-agent retrieval:
- returns clean, deduplicated snippets (not raw HTML)
- supports `search_depth: 'advanced'` for the deeper queries our `external-web`
  pass wants
- free tier is 1000 queries/month, enough for early autopilot
- single endpoint, json-in/json-out

Sign up: https://tavily.com — put the key in sandbox/.env as TAVILY_API_KEY.
The researcher checks for the key at call time and returns a `no-web-access`
warning if missing, so the system stays functional unkeyed.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


class WebSearchUnavailable(Exception):
    """Raised when no web search provider is configured."""


def tavily_search(
    query: str,
    max_results: int = 5,
    depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[dict]:
    """Search the web via Tavily. Returns a list of {title, url, content, score}.

    Raises WebSearchUnavailable if no key is configured.
    """
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise WebSearchUnavailable(
            "TAVILY_API_KEY not set. Get a key at https://tavily.com and add to sandbox/.env"
        )

    payload = {
        "api_key": key,
        "query": query,
        "search_depth": depth,           # "basic" or "advanced"
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    results = body.get("results", [])
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in results
    ]


def search(query: str, **kwargs) -> list[dict]:
    """Provider-agnostic entry point. Currently routes to Tavily only.

    To add Exa / Brave / Serper, branch here on a WEB_SEARCH_PROVIDER env var.
    """
    return tavily_search(query, **kwargs)


def available() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY"))


def format_results_for_prompt(results: list[dict], max_chars_per: int = 800) -> str:
    """Compact rendering of search results for inclusion in a model prompt."""
    if not results:
        return "(no results)"
    blocks = []
    for i, r in enumerate(results, 1):
        content = (r.get("content") or "")[:max_chars_per]
        blocks.append(
            f"[{i}] {r.get('title','(no title)')}\n"
            f"    URL: {r.get('url','')}\n"
            f"    {content}"
        )
    return "\n\n".join(blocks)
