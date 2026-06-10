import httpx

from waifu.logger import logger


class DeepLTranslator:
    """使用 DeepL API 翻譯文字，api_key 以 ':fx' 結尾為免費版。"""

    def __init__(self, api_key: str, target_lang: str = "JA") -> None:
        self._api_key = api_key
        self._target_lang = target_lang
        base = "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"
        self._url = f"{base}/v2/translate"

    async def translate(self, text: str) -> str:
        if not text.strip():
            return text
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
                data={"text": text, "target_lang": self._target_lang},
            )
            resp.raise_for_status()
            result: str = resp.json()["translations"][0]["text"]
            logger.debug("DeepL translated {!r} -> {!r}", text[:60], result[:60])
            return result


__all__ = ["DeepLTranslator"]
