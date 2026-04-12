import httpx

from hai.tool import Tool


async def _webfetch(url: str, max_chars: int = 8000) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
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
        },
        "required": ["url"],
    },
    func=_webfetch,
)
