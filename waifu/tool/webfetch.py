import re

import httpx

from hai.tool import Tool

_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_MULTI_NL = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    text = _SCRIPT_STYLE.sub("", html)
    text = _TAG.sub("", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


async def _webfetch(url: str, max_chars: int = 8000, raw: bool = False) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            text = response.text
            if not raw and "html" in content_type:
                text = _html_to_text(text)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n... [truncated, total {len(text)} chars]"
            return text
    except httpx.HTTPStatusError as e:
        return f"[error] HTTP {e.response.status_code}: {url}"
    except httpx.RequestError as e:
        return f"[error] request failed: {e}"
    except Exception as e:
        return f"[error] {e}"


webfetch_tool = Tool(
    name="webfetch",
    description="Fetch the content of a URL via HTTP GET and return the response body as text.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default 8000).",
                "default": 8000,
            },
            "raw": {
                "type": "boolean",
                "description": "Return raw HTML instead of extracted text (default false).",
                "default": False,
            },
        },
        "required": ["url"],
    },
    func=_webfetch,
)
