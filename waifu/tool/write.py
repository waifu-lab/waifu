from pathlib import Path

from hai.tool import Tool


def _write(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[ok] written {len(content)} chars to {path}"
    except PermissionError:
        return f"[error] permission denied: {path}"
    except Exception as e:
        return f"[error] {e}"


write_tool = Tool(
    name="write",
    description="Write (or overwrite) a local file with the given content.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to write."},
            "content": {"type": "string", "description": "Text content to write into the file."},
        },
        "required": ["path", "content"],
    },
    func=_write,
)
