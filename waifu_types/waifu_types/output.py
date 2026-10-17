import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Optional


class StreamTransform(ABC):
    @abstractmethod
    def feed(self, chunk: str) -> str: ...

    def flush(self) -> str:

        return ""


class StreamObserver(ABC):
    """單次請求的串流旁聽者（由 BaseHook.stream_observer 建立），收到的是未經 OutputTransformer 的原始文字"""

    @abstractmethod
    def feed(self, chunk: str) -> None:
        """每個 chunk 送出前同步呼叫，不可阻塞；耗時工作請自行開 task"""
        ...

    def end_turn(self) -> None:
        """agent 一輪結束（例如接著要呼叫工具），前後輪的文字不應接在一起"""
        return None

    def reset(self) -> None:
        """stream_reset：本輪串流中斷並重跑，丟棄本輪尚未處理完的內容"""
        return None

    async def finish(self) -> None:
        """agent 完成且回覆已存檔；處理剩餘內容並等待完成，之後才執行 post hook"""
        return None

    async def aclose(self) -> None:
        """請求結束時一定會呼叫（包含中斷 / 錯誤），釋放尚未完成的工作"""
        return None


class OutputTransformer(ABC):
    name: str
    apply_to_history: bool = True

    @abstractmethod
    def apply(self, text: str) -> str:
        """處理完整文字"""
        ...

    def stream(self) -> StreamTransform:
        return _ChunkwiseStream(self)


class _ChunkwiseStream(StreamTransform):
    def __init__(self, transformer: OutputTransformer) -> None:
        self._transformer = transformer

    def feed(self, chunk: str) -> str:
        return self._transformer.apply(chunk)


@dataclass(frozen=True)
class InlineTag:
    name: str
    value: str
    start: int
    end: int


class InlineTagTransformer(OutputTransformer):
    def __init__(
        self,
        name: str,
        tag_names: Iterable[str],
        *,
        apply_to_history: bool = True,
        max_tag_length: int = 64,
    ) -> None:
        self.name = name
        self.apply_to_history = apply_to_history
        self._tag_names = tuple(n.lower() for n in tag_names)
        if not self._tag_names:
            raise ValueError("InlineTagTransformer requires at least one tag name")
        self._max_tag_length = max_tag_length
        names = "|".join(re.escape(n) for n in self._tag_names)
        self._pattern = re.compile(rf"\[({names}):([^\[\]\s]+)\]", re.IGNORECASE)

    @property
    def tag_names(self) -> tuple[str, ...]:
        return self._tag_names

    def find(self, text: str) -> List[InlineTag]:
        return [InlineTag(m.group(1).lower(), m.group(2), m.start(), m.end()) for m in self._pattern.finditer(text)]

    def first(self, text: str) -> Optional[InlineTag]:
        m = self._pattern.search(text)
        return InlineTag(m.group(1).lower(), m.group(2), m.start(), m.end()) if m else None

    def apply(self, text: str) -> str:
        return self._pattern.sub("", text)

    def stream(self) -> StreamTransform:
        return _InlineTagStream(self)

    def pending_start(self, text: str) -> Optional[int]:

        idx = text.rfind("[")
        if idx < 0 or len(text) - idx > self._max_tag_length:
            return None
        tail = text[idx + 1 :].lower()
        if "]" in tail:
            return None
        for name in self._tag_names:
            prefix = f"{name}:"
            if len(tail) <= len(prefix):
                if prefix.startswith(tail):
                    return idx
            elif tail.startswith(prefix) and not re.search(r"[\s\[]", tail[len(prefix) :]):
                return idx
        return None


@dataclass(frozen=True)
class SpanPiece:
    """SpanSplitter 的輸出：一段文字，或一個標記（text 為空、marker=True）；inside 為該位置是否在區段內"""

    text: str
    inside: bool
    marker: bool = False


class SpanMarkerTransformer(OutputTransformer):
    """成對區段標記，例如 [speak]...[/speak]；apply 只移除標記本身，區段內文字保留"""

    def __init__(self, name: str, tag: str, *, apply_to_history: bool = True) -> None:
        self.name = name
        self.apply_to_history = apply_to_history
        self.tag = tag.lower()
        self._markers = (f"[{self.tag}]", f"[/{self.tag}]")
        self._pattern = re.compile(rf"\[/?{re.escape(self.tag)}\]", re.IGNORECASE)

    def apply(self, text: str) -> str:
        return self._pattern.sub("", text)

    def stream(self) -> StreamTransform:
        return _InlineTagStream(self)

    def splitter(self) -> "SpanSplitter":
        return SpanSplitter(self)

    def pending_start(self, text: str) -> Optional[int]:
        idx = text.rfind("[")
        if idx < 0:
            return None
        tail = text[idx:].lower()
        if tail in self._markers:
            return None
        return idx if any(m.startswith(tail) for m in self._markers) else None


class SpanSplitter:
    """串流切分原始文字為區段內 / 外的片段；標記被拆在 chunk 之間時會暫存到能判斷為止"""

    def __init__(self, transformer: SpanMarkerTransformer) -> None:
        self._transformer = transformer
        self._buf = ""
        self.inside = False

    def feed(self, chunk: str) -> List[SpanPiece]:
        text = self._buf + chunk
        cut = self._transformer.pending_start(text)
        if cut is None:
            self._buf = ""
        else:
            text, self._buf = text[:cut], text[cut:]
        return self._split(text)

    def flush(self) -> List[SpanPiece]:
        text, self._buf = self._buf, ""
        return self._split(text)

    def _split(self, text: str) -> List[SpanPiece]:
        pieces: List[SpanPiece] = []
        pos = 0
        for m in self._transformer._pattern.finditer(text):
            if m.start() > pos:
                pieces.append(SpanPiece(text[pos : m.start()], self.inside))
            self.inside = not m.group(0).startswith("[/")
            pieces.append(SpanPiece("", self.inside, marker=True))
            pos = m.end()
        if pos < len(text):
            pieces.append(SpanPiece(text[pos:], self.inside))
        return pieces


class _InlineTagStream(StreamTransform):
    def __init__(self, transformer: "InlineTagTransformer | SpanMarkerTransformer") -> None:
        self._transformer = transformer
        self._buf = ""

    def feed(self, chunk: str) -> str:
        buf = self._transformer.apply(self._buf + chunk)
        cut = self._transformer.pending_start(buf)
        if cut is None:
            self._buf = ""
            return buf
        self._buf = buf[cut:]
        return buf[:cut]

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return out
