import inspect
import types
import typing
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol, Union, overload, runtime_checkable


@runtime_checkable
class ToolLike(Protocol):
    """可註冊給 Agent 的工具；hai.tool.Tool 與 FunctionTool 皆符合"""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema (object)
    func: Callable[..., Any]


@dataclass
class FunctionTool:
    """不依賴 hai 的工具定義，註冊時由 waifu 轉換為 hai.tool.Tool"""

    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[..., Any]


_JSON_TYPES: Dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    tuple: "array",
    dict: "object",
}


def _json_schema_for(annotation: Any) -> Dict[str, Any]:
    origin = typing.get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _json_schema_for(args[0]) if len(args) == 1 else {}
    if origin is typing.Literal:
        values = list(typing.get_args(annotation))
        schema = _json_schema_for(type(values[0])) if values else {}
        return {**schema, "enum": values}
    json_type = _JSON_TYPES.get(origin or annotation)
    return {"type": json_type} if json_type else {}


def schema_from_signature(func: Callable[..., Any]) -> Dict[str, Any]:
    """從函式簽名推導 JSON Schema；僅支援基本型別，複雜參數請自行提供 parameters"""
    hints = typing.get_type_hints(func)
    properties: Dict[str, Any] = {}
    required = []
    for param in inspect.signature(func).parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        properties[param.name] = _json_schema_for(hints.get(param.name, Any))
        if param.default is param.empty:
            required.append(param.name)
        else:
            properties[param.name]["default"] = param.default
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


@overload
def tool(func: Callable[..., Any], /) -> FunctionTool: ...
@overload
def tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Callable[[Callable[..., Any]], FunctionTool]: ...
def tool(
    func: Optional[Callable[..., Any]] = None,
    /,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Union[FunctionTool, Callable[[Callable[..., Any]], FunctionTool]]:

    def wrap(fn: Callable[..., Any]) -> FunctionTool:
        doc = inspect.getdoc(fn) or ""
        return FunctionTool(
            name=name or fn.__name__,
            description=description or doc.split("\n\n", 1)[0].strip(),
            parameters=parameters or schema_from_signature(fn),
            func=fn,
        )

    return wrap(func) if func is not None else wrap
