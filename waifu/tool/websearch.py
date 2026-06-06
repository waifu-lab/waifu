import json
import re
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from hai.tool import Tool

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_PRELOAD_URL_RE = re.compile(r"https://links\.duckduckgo\.com/d\.js\?[^\"'<>\s]+", re.I)
_JSONP_RE = re.compile(r"DDG\.pageLayout\.load\('d',\s*(\[.*?\])\s*\);", re.S)


def _limit_results(max_results: int) -> int:
    return max(1, min(max_results, 10))


def _is_trusted_preload_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    return (
        parsed.scheme == "https"
        and parsed.hostname == "links.duckduckgo.com"
        and (parsed.port in (None, 443))
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/d.js"
    )


def _extract_preload_url(html: str) -> str | None:
    match = _PRELOAD_URL_RE.search(html)
    if not match:
        return None

    candidate = match.group(0)
    if _is_trusted_preload_url(candidate):
        return candidate
    return None


def _extract_jsonp_results(payload: str) -> list[dict[str, Any]]:
    match = _JSONP_RE.search(payload)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _format_results(query: str, results: list[dict[str, str]]) -> str:
    parts = [f"Query: {query}", "Results:"]
    for i, result in enumerate(results, start=1):
        snippet = result["snippet"]
        source = result["source"]
        block = [f"{i}. {result['title']}", f"   {result['url']}"]
        if snippet:
            block.append(f"   {snippet}")
        if source:
            block.append(f"   source: {source}")
        parts.append("\n".join(block))
    return "\n".join(parts)


async def _fetch_preload_url(client: httpx.AsyncClient, query: str, language: str) -> str | None:
    response = await client.get(
        "https://duckduckgo.com/",
        params={"q": query, "t": "h_", "ia": "web", "kl": language},
    )
    response.raise_for_status()
    return _extract_preload_url(response.text)


async def _fetch_search_results(
    client: httpx.AsyncClient,
    query: str,
    max_results: int,
    language: str,
) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    preload_url = None

    try:
        preload_url = await _fetch_preload_url(client, query, language)
    except Exception as e:
        errors.append(f"search page: {e}")

    if not preload_url:
        return [], errors or ["search page: preload url not found"]

    seen: set[tuple[str, str]] = set()
    results: list[dict[str, str]] = []
    offset = 0

    while len(results) < max_results:
        page_url = re.sub(r"([?&])s=\d+", r"\1s=" + str(offset), preload_url, count=1)
        if "s=" not in page_url:
            sep = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{sep}{urlencode({'s': offset})}"

        try:
            response = await client.get(page_url, headers={"Accept": "*/*", "Referer": "https://duckduckgo.com/"})
            response.raise_for_status()
        except Exception as e:
            errors.append(f"d.js page {offset}: {e}")
            break

        page_items = _extract_jsonp_results(response.text)
        if not page_items:
            break

        valid_count = 0
        added_count = 0
        for item in page_items:
            if item.get("n"):
                continue

            title = _normalize_text(item.get("t"))
            url = _normalize_text(item.get("u"))
            snippet = _normalize_text(item.get("a"))
            source = _normalize_text(item.get("i") or item.get("sn"))
            if not title or not url:
                continue

            valid_count += 1
            key = (title.casefold(), url)
            if key in seen:
                continue
            seen.add(key)
            results.append({"title": title, "url": url, "snippet": snippet, "source": source})
            added_count += 1
            if len(results) >= max_results:
                break

        if valid_count == 0 or added_count == 0:
            break
        offset += valid_count

    return results[:max_results], errors


async def _websearch(query: str, max_results: int = 5, language: str = "zh-TW") -> str:
    query = query.strip()
    if not query:
        return '[error] missing query parameter "query"'

    max_results = _limit_results(max_results)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{language},en;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
        results, errors = await _fetch_search_results(client, query, max_results, language)

    if results:
        return _format_results(query, results)
    if errors:
        return f"[error] websearch failed: {'; '.join(errors)}"
    return "[no results found]"


websearch_tool = Tool(
    name="websearch",
    description="Search DuckDuckGo and return result titles, URLs, snippets, and sources.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5, max 10).",
                "default": 5,
            },
            "language": {
                "type": "string",
                "description": 'DuckDuckGo locale hint, for example "zh-TW" or "en-US".',
                "default": "zh-TW",
            },
        },
        "required": ["query"],
    },
    func=_websearch,
)
