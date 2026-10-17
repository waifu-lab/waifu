import pytest

from waifu_types import InlineTagTransformer


def _stream_all(transformer: InlineTagTransformer, chunks: list[str]) -> str:
    stream = transformer.stream()
    out = "".join(stream.feed(c) for c in chunks)
    return out + stream.flush()


@pytest.mark.unit
def test_inline_tag_apply_and_find():
    t = InlineTagTransformer("emotion", ["emotion"])
    text = "[emotion:happy]你好！[EMOTION:sad]掰掰"
    assert t.apply(text) == "你好！掰掰"
    assert [(tag.name, tag.value) for tag in t.find(text)] == [("emotion", "happy"), ("emotion", "sad")]


@pytest.mark.unit
def test_inline_tag_stream_split_across_chunks():
    t = InlineTagTransformer("emotion", ["emotion"])
    chunks = ["[emo", "tion:ha", "ppy]你好", "！[", "emotion:sad]掰", "掰"]
    assert _stream_all(t, chunks) == "你好！掰掰"


@pytest.mark.unit
def test_inline_tag_stream_never_emits_partial_tag():
    t = InlineTagTransformer("emotion", ["emotion"])
    stream = t.stream()
    assert stream.feed("嗨[emo") == "嗨"
    assert stream.feed("tion:happy]") == ""
    assert stream.feed("！") == "！"


@pytest.mark.unit
def test_inline_tag_stream_releases_non_tag_brackets():
    t = InlineTagTransformer("emotion", ["emotion"])
    assert _stream_all(t, ["請看 [", "1] 與 [e", "xample]"]) == "請看 [1] 與 [example]"
    # 未完成且不可能是標籤的內容在 flush 時原樣送出
    assert _stream_all(t, ["結尾 [emo"]) == "結尾 [emo"


@pytest.mark.unit
def test_inline_tag_ignores_other_tag_names():
    t = InlineTagTransformer("emotion", ["emotion"])
    assert t.apply("[pose:wave]嗨[emotion:happy]") == "[pose:wave]嗨"


@pytest.mark.unit
def test_output_pipeline_chains_hook_transformers():
    from waifu.agent.output import OutputPipeline
    from waifu.hook import HookRegistry
    from waifu_types import BaseHook

    class TagHook(BaseHook):
        def __init__(self, name: str, history: bool) -> None:
            self.name = name
            self._t = InlineTagTransformer(name, [name], apply_to_history=history)

        def output_transformers(self):
            return (self._t,)

    registry = HookRegistry()
    pipeline = OutputPipeline(registry)
    registry.register(TagHook("emotion", history=True))
    pose = TagHook("pose", history=False)
    registry.register(pose)

    text = "[emotion:happy][pose:wave]嗨"
    assert pipeline.apply(text) == "嗨"
    assert pipeline.apply_history(text) == "[pose:wave]嗨"

    stream = pipeline.stream()
    out = "".join(stream.feed(c) for c in ["[emotion:ha", "ppy][po", "se:wave]", "嗨"]) + stream.flush()
    assert out == "嗨"

    # hook 移除後立即失效
    registry.unregister(pose)
    assert pipeline.apply(text) == "[pose:wave]嗨"


@pytest.mark.unit
def test_function_tool_schema_from_signature():
    from typing import Literal, Optional

    from waifu.plugin import as_hai_tool
    from waifu_types import tool

    @tool
    async def search(query: str, limit: int = 5, mode: Literal["a", "b"] = "a", tag: Optional[str] = None) -> str:
        """搜尋資料

        詳細說明不會進 description
        """
        return f"{query} {limit} {mode} {tag}"

    assert search.name == "search"
    assert search.description == "搜尋資料"
    assert search.parameters == {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
            "mode": {"type": "string", "enum": ["a", "b"], "default": "a"},
            "tag": {"type": "string", "default": None},
        },
        "required": ["query"],
    }
    assert as_hai_tool(search).to_dict()["function"]["name"] == "search"


@pytest.mark.unit
def test_span_marker_apply_and_stream():
    from waifu_types import SpanMarkerTransformer

    t = SpanMarkerTransformer("speak", "speak")
    assert t.apply("[speak]查到了[/SPEAK]\n1. a") == "查到了\n1. a"
    stream = t.stream()
    out = "".join(stream.feed(c) for c in ["[spe", "ak]嗨[", "/spea", "k] [1] 結尾 [sp"]) + stream.flush()
    assert out == "嗨 [1] 結尾 [sp"


@pytest.mark.unit
def test_span_splitter_tracks_inside_across_chunks():
    from waifu_types import SpanMarkerTransformer

    splitter = SpanMarkerTransformer("speak", "speak").splitter()
    pieces = []
    for chunk in ["[spe", "ak]唸這", "個[/sp", "eak]不唸"]:
        pieces += splitter.feed(chunk)
    pieces += splitter.flush()
    texts = [(p.text, p.inside) for p in pieces if not p.marker]
    assert "".join(t for t, inside in texts if inside) == "唸這個"
    assert "".join(t for t, inside in texts if not inside) == "不唸"
    assert [p.inside for p in pieces if p.marker] == [True, False]
