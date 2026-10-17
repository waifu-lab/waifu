from typing import List

from waifu_types import Event


def apply_stream_reset(buffer: List[str], event: Event) -> None:
    """stream_reset 事件：從已累積的 chunk 尾端丟棄中斷那一輪已送出的文字"""
    if event.event != "stream_reset":
        return
    text = "".join(buffer)
    buffer[:] = [text[: max(0, len(text) - int(event.data.get("discard", 0)))]]
