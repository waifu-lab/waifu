import asyncio
from typing import List

import pytest

from waifu_types import ConversationMode, Feature, HookContext, IncomingRequest, Sender


class _FakeVoice:
    def __init__(self) -> None:
        self.spoken: List[str] = []

    def sentence_stream(self, need_lipsync=False, clean=None):  # noqa: ARG002
        from waifu.voice.service import SentenceStream, SynthesisResult

        async def _one(sentence: str):
            text = clean(sentence).strip() if clean else sentence
            if not text:
                return None
            self.spoken.append(text)
            return SynthesisResult(b"", "mp3", [], sentence=sentence)

        return SentenceStream(_one, 1)

    def build_audio_events(self, result):  # noqa: ARG002
        return []


def _ctx() -> HookContext:
    from waifu.gateway.session import SessionManager

    request = IncomingRequest(
        conversation_id="c",
        mode=ConversationMode.session,
        sender=Sender(user_id="u", display_name="U"),
        source="test",
        content="x",
        features={Feature.LIVE2D},
        reply_fn=lambda *_, **__: None,
    )
    return HookContext(request=request, session=SessionManager().get_or_create("c"), messages=[])


async def _speak(chunks: List[str]) -> List[str]:
    from waifu.agent.output import OutputPipeline
    from waifu.hook import HookRegistry
    from waifu.hook.builtin import TTSHook

    voice = _FakeVoice()
    registry = HookRegistry()
    pipeline = OutputPipeline(registry)
    hook = TTSHook(voice, clean=pipeline.apply)  # type: ignore[arg-type]
    registry.register(hook)
    observer = hook.stream_observer(_ctx())
    assert observer is not None
    for chunk in chunks:
        observer.feed(chunk)
    await asyncio.wait_for(observer.finish(), 1)
    await observer.aclose()
    return voice.spoken


@pytest.mark.unit
async def test_tts_speaks_everything_without_speak_tag():
    assert await _speak(["你好！", "今天想", "聊什麼？"]) == ["你好！", "今天想聊什麼？"]


@pytest.mark.unit
async def test_tts_speaks_only_speak_spans_when_reply_starts_with_tag():
    chunks = [
        "  [spe",
        "ak]查到了，重點",
        "有三個。[/speak]\n1. `pip install x`\n",
        "2. https://a.b\n",
        "[speak]還要說明嗎[/speak]",
    ]
    assert await _speak(chunks) == ["查到了，重點有三個。", "還要說明嗎"]


@pytest.mark.unit
async def test_tts_late_speak_tag_falls_back_to_speaking_all():
    assert await _speak(["好的。", "[speak]這段[/speak]"]) == ["好的。", "這段"]


@pytest.mark.unit
async def test_tts_decision_is_per_turn():
    from waifu.agent.output import OutputPipeline
    from waifu.hook import HookRegistry
    from waifu.hook.builtin import TTSHook

    voice = _FakeVoice()
    registry = HookRegistry()
    hook = TTSHook(voice, clean=OutputPipeline(registry).apply)  # type: ignore[arg-type]
    registry.register(hook)
    observer = hook.stream_observer(_ctx())
    assert observer is not None
    observer.feed("[speak]我查一下。[/speak]工具參數")
    observer.end_turn()
    observer.feed("結果是晴天。")
    await asyncio.wait_for(observer.finish(), 1)
    assert voice.spoken == ["我查一下。", "結果是晴天。"]
