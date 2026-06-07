import fnmatch
import re
from pathlib import Path
from typing import List

from hai.tool import Tool


def _grep_files(files: List[Path], content_pattern: str, max_results: int) -> str:
    regex = re.compile(content_pattern, re.IGNORECASE)
    matches: List[str] = []
    for f in files:
        if len(matches) >= max_results:
            break
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{f}:{i}: {line.rstrip()}")
                    if len(matches) >= max_results:
                        break
        except Exception:
            continue
    return "\n".join(matches) or "[no matches found]"


def _file_search(
    path: str,
    pattern: str = "",
    content_pattern: str = "",
    max_results: int = 50,
) -> str:
    root = Path(path)
    if not root.exists():
        return f"[error] path not found: {path}"

    try:
        all_files: List[Path] = [f for f in root.rglob("*") if f.is_file()]
    except PermissionError as e:
        return f"[error] {e}"

    if pattern:
        all_files = [f for f in all_files if fnmatch.fnmatch(f.name, pattern)]

    if not content_pattern:
        hits = [str(f) for f in all_files[:max_results]]
        total = len(all_files)
        suffix = f"\n... [{total - max_results} more]" if total > max_results else ""
        return ("\n".join(hits) + suffix) or "[no files found]"

    return _grep_files(all_files, content_pattern, max_results)


file_search_tool = Tool(
    name="file_search",
    description=(
        "Search for files by name glob pattern and/or grep file contents by regex. "
        "Pass only `pattern` to list matching filenames. "
        "Pass only `content_pattern` to grep inside all files. "
        "Pass both to scope the grep to matching filenames."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Root directory to search under."},
            "pattern": {
                "type": "string",
                "description": "Glob pattern for filenames, e.g. '*.py', 'config.*'. Optional.",
                "default": "",
            },
            "content_pattern": {
                "type": "string",
                "description": "Regex pattern to grep inside file contents. Optional.",
                "default": "",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 50).",
                "default": 50,
            },
        },
        "required": ["path"],
    },
    func=_file_search,
)


def _file_edit(path: str, old_str: str, new_str: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] file not found: {path}"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[error] read failed: {e}"

    count = text.count(old_str)
    if count == 0:
        return f"[error] old_str not found in {path}"
    if count > 1:
        return f"[error] old_str matches {count} locations — make it more specific"

    p.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
    return f"[ok] replaced 1 occurrence in {path}"


file_edit_tool = Tool(
    name="file_edit",
    description=(
        "Replace an exact occurrence of `old_str` with `new_str` in a file. "
        "The match must be unique — include enough surrounding context to disambiguate. "
        "Fails if the string is not found or appears more than once."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path."},
            "old_str": {"type": "string", "description": "Exact text to find and replace."},
            "new_str": {"type": "string", "description": "Text to insert in place of old_str."},
        },
        "required": ["path", "old_str", "new_str"],
    },
    func=_file_edit,
)


def _apply_patch(original: str, patch_text: str) -> str:
    """Apply a unified diff patch to original text. Returns patched text or raises ValueError."""
    lines = original.splitlines(keepends=True)
    patch_lines = patch_text.splitlines()

    i = 0
    while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
        i += 1

    result = list(lines)
    offset = 0

    while i < len(patch_lines):
        line = patch_lines[i]
        if not line.startswith("@@"):
            i += 1
            continue

        # Parse @@ -start,count +start,count @@
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            i += 1
            continue

        orig_start = int(m.group(1)) - 1  # 0-indexed
        i += 1

        chunk_orig: List[str] = []
        chunk_new: List[str] = []

        while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
            pl = patch_lines[i]
            if pl.startswith("-"):
                chunk_orig.append(pl[1:])
            elif pl.startswith("+"):
                chunk_new.append(pl[1:])
            elif pl.startswith(" ") or pl == "":
                ctx = pl[1:] if pl.startswith(" ") else "\n"
                chunk_orig.append(ctx)
                chunk_new.append(ctx)
            i += 1

        # Locate the hunk in result
        pos = orig_start + offset
        orig_slice = [ln.rstrip("\n") for ln in chunk_orig]
        result_slice = [ln.rstrip("\n") for ln in result[pos : pos + len(chunk_orig)]]
        if result_slice != orig_slice:
            raise ValueError(
                f"patch hunk at line {orig_start + 1} does not match: expected {orig_slice!r}, got {result_slice!r}"
            )

        new_lines = [(ln if ln.endswith("\n") else ln + "\n") for ln in chunk_new]
        result[pos : pos + len(chunk_orig)] = new_lines
        offset += len(chunk_new) - len(chunk_orig)

    return "".join(result)


def _file_patch(path: str, patch: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] file not found: {path}"
    try:
        original = p.read_text(encoding="utf-8")
        patched = _apply_patch(original, patch)
        p.write_text(patched, encoding="utf-8")
        return f"[ok] patch applied to {path}"
    except ValueError as e:
        return f"[error] patch failed: {e}"
    except Exception as e:
        return f"[error] {e}"


file_patch_tool = Tool(
    name="file_patch",
    description=(
        "Apply a unified diff patch (--- / +++ / @@ format) to a file. "
        "Use this when you have a diff output and want to apply it directly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to patch."},
            "patch": {
                "type": "string",
                "description": "Unified diff content (the output of `diff -u` or a git diff chunk).",
            },
        },
        "required": ["path", "patch"],
    },
    func=_file_patch,
)
