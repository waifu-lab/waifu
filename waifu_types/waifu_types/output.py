import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Optional


class StreamTransform(ABC):
    @abstractmethod
    def feed(self, chunk: str) -> str: ...

    def flush(self) -> str:

        return ""


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


class _InlineTagStream(StreamTransform):
    def __init__(self, transformer: InlineTagTransformer) -> None:
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
