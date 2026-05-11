import uuid
from typing import TYPE_CHECKING, Optional

from waifu_types import Attachment, BaseGatewayAdapter, ConversationMode, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from waifu.gateway.core import GatewayCore

from waifu.logger import logger


class DiscordAdapter(BaseGatewayAdapter):
    """
    Discord Adapter — 支援 DIRECT（DM）和 GROUP（伺服器頻道）模式

    DIRECT：私訊，任何訊息都觸發
    GROUP ：伺服器頻道，僅 @mention 或回覆 bot 訊息時觸發

    streaming：連續 edit 同一則訊息模擬串流輸出

    用法：
        adapter = DiscordAdapter(token="BOT_TOKEN")
        waifu.mount(adapter)
        await waifu.start()   # 內部呼叫 adapter.start()，啟動 discord client
    """

    name = "discord"

    def __init__(self, token: str, stream_edit: bool = True) -> None:
        try:
            import discord  # noqa: F401
        except ImportError as e:
            raise ImportError("discord.py is required: pip install discord.py") from e

        self._token = token
        self._stream_edit = stream_edit
        self._core: Optional["GatewayCore"] = None
        self._client: Optional[object] = None

    async def start(self, core: "GatewayCore") -> None:
        import asyncio

        import discord

        self._core = core
        intents = discord.Intents.default()
        intents.message_content = True

        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready() -> None:
            logger.info("Discord adapter ready: {}", client.user)

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == client.user:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)

            if is_dm:
                mode = ConversationMode.direct
                conversation_id = f"discord:dm:{message.author.id}"
            else:
                # GROUP：僅 @mention 或回覆 bot 訊息才 dispatch
                bot_mentioned = client.user in message.mentions
                is_reply_to_bot = (
                    message.reference is not None
                    and message.reference.resolved is not None
                    and getattr(message.reference.resolved, "author", None) == client.user
                )
                if not (bot_mentioned or is_reply_to_bot):
                    return
                mode = ConversationMode.group
                conversation_id = f"discord:channel:{message.channel.id}"

            sender = Sender(
                user_id=f"discord:user:{message.author.id}",
                display_name=message.author.display_name,
            )

            reply_fn = _make_discord_reply_fn(message, stream_edit=self._stream_edit)

            attachments = [
                Attachment(
                    filename=att.filename,
                    content_type=att.content_type or "application/octet-stream",
                    url=att.url,
                )
                for att in message.attachments
            ]

            request = IncomingRequest(
                request_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                mode=mode,
                sender=sender,
                source=self.name,
                content=message.clean_content,
                attachments=attachments,
                reply_fn=reply_fn,
            )

            if self._core is not None:
                await self._core.dispatch(request)

        # discord.py 的 start() 會 block，用 asyncio.create_task 背景執行
        asyncio.create_task(client.start(self._token))

    async def send(self, response: OutgoingResponse) -> None:
        # 傳送由每個訊息的 reply_fn 負責
        pass

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()  # type: ignore[attr-defined]


def _make_discord_reply_fn(message: object, stream_edit: bool = True):
    """建立綁定到此 Discord 訊息的 reply_fn

    stream_edit=True：每次收到 chunk 時 edit 同一則訊息模擬串流
    stream_edit=False：等最終 response 再一次送出
    """
    sent_message = None
    buffer: list[str] = []

    async def reply_fn(response: Optional[OutgoingResponse] = None, *, chunk: Optional[str] = None) -> None:
        nonlocal sent_message, buffer

        if chunk is not None and stream_edit:
            buffer.append(chunk)
            content = "".join(buffer)
            if sent_message is None:
                sent_message = await message.channel.send(content)  # type: ignore[attr-defined]
            else:
                await sent_message.edit(content=content)  # type: ignore[attr-defined]
        elif response is not None:
            final = response.content or "".join(buffer)
            if not final:
                return
            if sent_message is not None:
                await sent_message.edit(content=final)  # type: ignore[attr-defined]
            else:
                await message.channel.send(final)  # type: ignore[attr-defined]

    return reply_fn
