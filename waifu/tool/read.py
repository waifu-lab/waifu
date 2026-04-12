from pathlib import Path

from hai.tool import Tool


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"[error] file not found: {path}"
    except PermissionError:
        return f"[error] permission denied: {path}"
    except Exception as e:
        return f"[error] {e}"


read_tool = Tool(
    name="read",
    description="Read the contents of a local file and return it as a string.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to read."},
        },
        "required": ["path"],
    },
    func=_read,
)
