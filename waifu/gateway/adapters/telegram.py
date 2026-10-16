import uuid
from typing import Any, Optional

from waifu.logger import logger
from waifu_types import (
    Attachment,
    BaseGatewayAdapter,
    ConversationMode,
    Event,
    GatewayProtocol,
    IncomingRequest,
    OutgoingResponse,
    ReplyFn,
    Sender,
)


class TelegramAdapter(BaseGatewayAdapter):
    """
    Telegram Adapter — 支援 DIRECT（私聊）和 GROUP（群組）模式

    DIRECT：私聊，任何訊息都觸發
    GROUP ：群組，僅 @mention bot 或 /shuvi 指令時觸發

    streaming：連續 edit 同一則訊息模擬串流輸出

    用法：
        adapter = TelegramAdapter(token="BOT_TOKEN")
        waifu.mount(adapter)
        await waifu.start()
    """

    name = "telegram"

    @classmethod
    def default_gateway_config(cls) -> dict[str, object]:
        return {
            "enabled": False,
            "token": "",
            "trigger_command": "shuvi",
            "stream_edit": True,
            "group_sessions_per_user": True,
        }

    @classmethod
    def build_gateway_status(cls, config: dict[str, object]) -> dict[str, object]:
        return {
            "name": cls.name,
            "enabled": bool(config.get("enabled", False)),
            "configured": bool(config.get("token")),
        }

    @classmethod
    def from_gateway_config(cls, config: dict[str, object], **deps: object) -> "TelegramAdapter | None":
        del deps
        if not bool(config.get("enabled", False)):
            return None
        token = str(config.get("token", "") or "")
        if not token:
            return None
        return cls(
            token=token,
            trigger_command=str(config.get("trigger_command", "shuvi") or "shuvi"),
            stream_edit=bool(config.get("stream_edit", True)),
            group_sessions_per_user=bool(config.get("group_sessions_per_user", True)),
        )

    def __init__(
        self,
        token: str,
        trigger_command: str = "shuvi",
        stream_edit: bool = True,
        group_sessions_per_user: bool = True,
    ) -> None:
        try:
            import telegram  # noqa: F401
        except ImportError as e:
            raise ImportError("python-telegram-bot is required: pip install python-telegram-bot") from e

        self._token = token
        self._trigger_command = trigger_command
        self._stream_edit = stream_edit
        self._group_sessions_per_user = group_sessions_per_user
        self._core: Optional[GatewayProtocol] = None
        self._app: Optional[Any] = None
        self._bot_username: Optional[str] = None

    async def start(self, core: GatewayProtocol) -> None:  # noqa: C901
        import asyncio

        from telegram import BotCommand, Update
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

        self._core = core
        app = ApplicationBuilder().token(self._token).build()
        self._app = app

        adapter = self
        command_service = core.command_service

        async def dispatch_update(update: Update, context: Any, *, platform_command: bool = False) -> None:
            if not isinstance(update, Update) or update.message is None:
                return

            msg = update.message
            chat = msg.chat
            user = msg.from_user
            text: str = msg.text or ""

            if user is None:
                return

            is_private = chat.type == "private"

            if is_private:
                mode = ConversationMode.direct
                conversation_id = f"telegram:chat:{chat.id}"
            else:
                # GROUP：@mention 或 /trigger_command 或內建 platform command 才 dispatch
                bot_username = adapter._bot_username or ""
                mentioned = bot_username and f"@{bot_username}" in text
                triggered = text.startswith(f"/{adapter._trigger_command}")
                if not (platform_command or mentioned or triggered):
                    return
                mode = ConversationMode.group
                conversation_id = _telegram_group_conversation_id(
                    chat.id,
                    user.id,
                    group_sessions_per_user=adapter._group_sessions_per_user,
                )

            sender = Sender(
                user_id=f"telegram:user:{user.id}",
                display_name=user.full_name,
            )

            stream_edit = adapter._stream_edit and not platform_command
            reply_fn = _make_telegram_reply_fn(msg, stream_edit=stream_edit)

            attachments = await _telegram_attachments(msg, context)

            request = IncomingRequest(
                request_id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                mode=mode,
                sender=sender,
                source=adapter.name,
                content=text,
                attachments=attachments,
                platform_command=_telegram_command_name(text) if platform_command else None,
                reply_fn=reply_fn,
            )

            if adapter._core is not None:
                await adapter._core.dispatch(request)

        async def on_message(update: Update, context: Any) -> None:
            await dispatch_update(update, context)

        async def on_platform_command(update: Update, context: Any) -> None:
            await dispatch_update(update, context, platform_command=True)

        if command_service is not None:
            for definition in command_service.definitions:
                app.add_handler(CommandHandler(definition.name, on_platform_command), group=0)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message), group=1)
        app.add_handler(CommandHandler(self._trigger_command, on_message), group=1)
        app.add_handler(MessageHandler(filters.PHOTO, on_message), group=1)
        app.add_handler(MessageHandler(filters.Document.IMAGE, on_message), group=1)

        async def _run() -> None:
            await app.initialize()
            me = await app.bot.get_me()
            adapter._bot_username = me.username
            if command_service is not None:
                await app.bot.set_my_commands(
                    [BotCommand(d.name, d.description[:256]) for d in command_service.definitions]
                )
            logger.info("Telegram adapter ready: @{}", me.username)
            await app.start()
            if app.updater is not None:
                await app.updater.start_polling()

        asyncio.create_task(_run())

    async def stop(self) -> None:
        if self._app is not None:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()


async def _telegram_attachments(msg: Any, context: Any) -> list[Attachment]:
    attachments: list[Attachment] = []
    try:
        if msg.photo:
            largest = msg.photo[-1]
            tg_file = await context.bot.get_file(largest.file_id)
            data = bytes(await tg_file.download_as_bytearray())
            attachments.append(Attachment(filename="photo.jpg", content_type="image/jpeg", data=data))
        elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("image/"):
            tg_file = await context.bot.get_file(msg.document.file_id)
            data = bytes(await tg_file.download_as_bytearray())
            attachments.append(
                Attachment(
                    filename=msg.document.file_name or "document",
                    content_type=msg.document.mime_type,
                    data=data,
                )
            )
    except Exception:
        logger.warning("Failed to download Telegram attachment, skipping")
    return attachments


def _telegram_command_name(text: str) -> str:
    command = (text.strip().split(maxsplit=1)[0] if text.strip() else "").lstrip("/")
    return command.split("@", 1)[0].lower()


def _telegram_group_conversation_id(chat_id: object, user_id: object, *, group_sessions_per_user: bool) -> str:
    base = f"telegram:group:{chat_id}"
    if group_sessions_per_user:
        return f"{base}:user:{user_id}"
    return base


_TELEGRAM_STREAM_INTERVAL = 1.5


def _make_telegram_reply_fn(message: Any, stream_edit: bool = True) -> ReplyFn:
    """建立綁定到此 Telegram 訊息的 reply_fn

    stream_edit=True：每隔 _TELEGRAM_STREAM_INTERVAL 秒 edit 一次訊息模擬串流；
                      最終 response 時強制更新為完整內容。
    stream_edit=False：等最終 response 再一次送出
    """
    import time

    sent_message = None
    buffer: list[str] = []
    last_edit: float = 0.0

    async def reply_fn(
        response: Optional[OutgoingResponse] = None, *, chunk: Optional[str] = None, event: Optional[Event] = None
    ) -> None:
        nonlocal sent_message, buffer, last_edit
        if event is not None:
            return

        if chunk is not None and stream_edit:
            buffer.append(chunk)
            now = time.monotonic()
            try:
                if sent_message is None:
                    sent_message = await message.reply_text("".join(buffer))
                    last_edit = now
                elif now - last_edit >= _TELEGRAM_STREAM_INTERVAL:
                    await sent_message.edit_text("".join(buffer))
                    last_edit = now
            except Exception:
                pass
        elif response is not None:
            final = response.content or "".join(buffer)
            if not final:
                return
            try:
                if sent_message is not None:
                    await sent_message.edit_text(final)
                else:
                    await message.reply_text(final)
            except Exception:
                pass

    return reply_fn
