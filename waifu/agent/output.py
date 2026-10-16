from typing import TYPE_CHECKING, List

from waifu_types import OutputTransformer, StreamTransform

if TYPE_CHECKING:
    from waifu.hook import HookRegistry


class OutputPipeline:
    """串接所有 hook 提供的 OutputTransformer；每次呼叫都重新收集，hook 卸載後立即生效"""

    def __init__(self, hook_registry: "HookRegistry") -> None:
        self._hook_registry = hook_registry

    def transformers(self) -> List[OutputTransformer]:
        return self._hook_registry.output_transformers()

    def apply(self, text: str) -> str:
        """顯示 / TTS 用：套用全部 transformer"""
        for t in self.transformers():
            text = t.apply(text)
        return text

    def apply_history(self, text: str) -> str:
        """存入歷史用：只套用 apply_to_history=True 的 transformer"""
        for t in self.transformers():
            if t.apply_to_history:
                text = t.apply(text)
        return text

    def stream(self) -> StreamTransform:
        return _ChainedStream([t.stream() for t in self.transformers()])


class _ChainedStream(StreamTransform):
    def __init__(self, stages: List[StreamTransform]) -> None:
        self._stages = stages

    def feed(self, chunk: str) -> str:
        for stage in self._stages:
            if not chunk:
                break
            chunk = stage.feed(chunk)
        return chunk

    def flush(self) -> str:
        # 前一階段 flush 出來的內容要再經過後續階段
        out = ""
        for stage in self._stages:
            out = (stage.feed(out) if out else "") + stage.flush()
        return out
