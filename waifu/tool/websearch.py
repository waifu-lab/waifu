import re
from urllib.parse import quote

import httpx

from hai.tool import Tool

_TAG = re.compile(r"<[^>]+>")
_RESULT_URL = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S)
_RESULT_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_DDG_REDIRECT = re.compile(r"[?&]uddg=([^&]+)")


def _clean(html: str) -> str:
    return _TAG.sub("", html).strip()


def _resolve_url(href: str) -> str:
    m = _DDG_REDIRECT.search(href)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1))
    return href


async def _websearch(query: str, max_results: int = 5) -> str:
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        return f"[error] websearch failed: {e}"

    html = resp.text
    urls_titles = [(_resolve_url(m.group(1)), _clean(m.group(2))) for m in _RESULT_URL.finditer(html)]
    snippets = [_clean(m.group(1)) for m in _RESULT_SNIPPET.finditer(html)]

    if not urls_titles:
        return "[no results found]"

    parts = []
    for i, (link, title) in enumerate(urls_titles[:max_results]):
        snippet = snippets[i] if i < len(snippets) else ""
        parts.append(f"{i + 1}. {title}\n   {link}\n   {snippet}")
    return "\n\n".join(parts)


websearch_tool = Tool(
    name="websearch",
    description="Search the web using DuckDuckGo and return the top results with titles, URLs, and snippets.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    func=_websearch,
)
