import math
from typing import List, Dict


#TODO: 重寫

_BITRATE_KBPS: Dict[str, int] = {
    "mp3": 24,
    "opus": 16,
    "aac": 32,
    "flac": 256,
    "wav": 256,
    "pcm": 256,
}


def estimate_duration_ms(audio_bytes: bytes, audio_format: str = "mp3") -> int:
    """
    從音訊位元組大小粗估播放時長（毫秒）

    公式：duration = (bytes * 8) / (bitrate_kbps * 1000)

    注意：這是粗估值，實際時長取決於 encoder 設定
    客戶端如需精確時長，應在播放後取 AudioBuffer.duration
    """
    bitrate = _BITRATE_KBPS.get(audio_format.lower(), 24)
    bits = len(audio_bytes) * 8
    duration_s = bits / (bitrate * 1000)
    return max(100, int(duration_s * 1000))


def build_lipsync_events(text: str, duration_ms: int, fps: int = 20) -> List[Dict]:
    """
    根據文字與預估時長生成簡易 viseme 排程

    使用「音節脈衝」模型：
    - 將文字中的有效字元視為近似音節
    - 每個音節佔一段時長，在時段中間達到最大開口值，頭尾為閉合
    - 最後補上一個 value=0.0 的閉合事件

    :param text:        要合成的文字（用於估算音節數）
    :param duration_ms: 預估播放時長（毫秒）
    :param fps:         viseme 幀率（每秒幾個取樣點）
    :return:            viseme 事件列表 [{"time_ms": int, "value": float}, ...]
    """
    if not text or duration_ms <= 0:
        return [{"time_ms": 0, "value": 0.0}]

    # 有效字元數（過濾空白與標點）作為音節近似值
    syllables = max(1, sum(1 for c in text if c.strip() and c not in "，！？,.!?、…"))
    syllable_dur = duration_ms / syllables

    total_frames = max(1, math.ceil(duration_ms / 1000 * fps))
    frame_dur = duration_ms / total_frames

    visemes: List[Dict] = []
    for i in range(total_frames):
        time_ms = int(i * frame_dur)
        # 當前時間在哪個音節
        syllable_idx = int(time_ms / syllable_dur)
        syllable_start = syllable_idx * syllable_dur
        syllable_end = syllable_start + syllable_dur
        syllable_mid = syllable_start + syllable_dur * 0.5
        # 正弦波：在音節中間最大，頭尾為 0
        phase = (time_ms - syllable_start) / (syllable_end - syllable_start)  # 0~1
        value = round(math.sin(phase * math.pi), 3)
        visemes.append({"time_ms": time_ms, "value": max(0.0, value)})

    # 結尾閉合
    visemes.append({"time_ms": duration_ms, "value": 0.0})
    return visemes


__all__ = ["estimate_duration_ms", "build_lipsync_events"]
