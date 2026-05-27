from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText

from waifu.logger import logger


class UtilityAI:
    def __init__(self, provider: "ProviderText") -> None:
        self._provider = provider

    async def complete(
        self,
        user_message: str,
        *,
        system: Optional[str] = None,
        max_chars: int = 0,
    ) -> str:
        if max_chars > 0:
            user_message = user_message[:max_chars]
        messages = [{"role": "user", "content": user_message}]
        try:
            result = await self._provider.call_once(messages, system_prompt=system)
            return (result.content or "").strip()
        except Exception as exc:
            logger.warning("UtilityAI.complete failed: {}", exc)
            return ""

    async def generate_title(self, user_message: str, assistant_reply: str) -> str:
        system = (
            "You are a conversation title generator. "
            "Given the first user message and the assistant's reply, "
            "produce a concise, descriptive title (≤10 words, no surrounding quotes, "
            "no trailing punctuation). "
            "Reply with ONLY the title text and nothing else."
        )
        prompt = f"User: {user_message[:400]}\nAssistant: {assistant_reply[:400]}"
        title = await self.complete(prompt, system=system)
        return title[:80] if title else ""

    async def summarise(self, text: str, *, max_sentences: int = 3) -> str:
        system = (
            f"Summarise the following text in at most {max_sentences} sentences. "
            "Be concise and factual. Reply with ONLY the summary."
        )
        return await self.complete(text, system=system, max_chars=4000)
