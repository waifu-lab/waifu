import math
from typing import Dict, List


def build_lipsync_events(text: str, frames: int = 20) -> List[Dict]:
    """
    根據文字生成 normalized viseme 排程（time 為 0.0~1.0，前端乘上實際 AudioBuffer.duration）

    使用「音節脈衝」模型：每個有效字元視為一個音節，用正弦波模擬開口幅度。
    最後補上 time=1.0, value=0.0 的閉合事件。

    :param text:   要合成的文字
    :param frames: viseme 取樣點數量
    :return:       [{"time": float 0~1, "value": float 0~1}, ...]
    """
    if not text:
        return [{"time": 0.0, "value": 0.0}]

    syllables = max(1, sum(1 for c in text if c.strip() and c not in "，！？,.!?、…"))
    syllable_dur = 1.0 / syllables
    total_frames = max(1, frames)
    frame_dur = 1.0 / total_frames

    visemes: List[Dict] = []
    for i in range(total_frames):
        t = i * frame_dur
        syllable_idx = int(t / syllable_dur)
        syllable_start = syllable_idx * syllable_dur
        syllable_end = syllable_start + syllable_dur
        phase = (t - syllable_start) / (syllable_end - syllable_start)
        value = round(math.sin(phase * math.pi), 3)
        visemes.append({"time": round(t, 4), "value": max(0.0, value)})

    visemes.append({"time": 1.0, "value": 0.0})
    return visemes


__all__ = ["build_lipsync_events"]
