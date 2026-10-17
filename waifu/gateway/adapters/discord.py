import inspect
import uuid
from typing import Any, Optional

from waifu.gateway.adapters._stream import apply_stream_reset
from waifu.logger import logger
from waifu_types import (
    Attachment,
    BaseGatewayAdapter,
    CommandDefinition,
    ConversationMode,
    Event,
    GatewayProtocol,
    IncomingRequest,
    OutgoingResponse,
    ReplyFn,
    Sender,
)


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

    @classmethod
    def default_gateway_config(cls) -> dict[str, object]:
        return {
            "enabled": False,
            "token": "",
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
    def from_gateway_config(cls, config: dict[str, object], **deps: object) -> "DiscordAdapter | None":
        del deps
        if not bool(config.get("enabled", False)):
            return None
        token = str(config.get("token", "") or "")
        if not token:
            return None
        return cls(
            token=token,
            stream_edit=bool(config.get("stream_edit", True)),
            group_sessions_per_user=bool(config.get("group_sessions_per_user", True)),
        )

    def __init__(self, token: str, stream_edit: bool = True, group_sessions_per_user: bool = True) -> None:
        try:
            import discord  # noqa: F401
        except ImportError as e:
            raise ImportError("discord.py is required: pip install discord.py") from e

        self._token = token
        self._stream_edit = stream_edit
        self._group_sessions_per_user = group_sessions_per_user
        self._core: Optional[GatewayProtocol] = None
        self._client: Optional[Any] = None

    async def start(self, core: GatewayProtocol) -> None:  # noqa: C901
        import asyncio

        import discord
        from discord import app_commands

        self._core = core
        intents = discord.Intents.default()
        intents.message_content = True

        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)
        self._client = client
        commands_synced = False

        command_service = core.command_service
        if command_service is not None:
            for definition in command_service.definitions:
                callback = _make_discord_command_callback(core, definition, self._group_sessions_per_user)
                if definition.arguments:
                    callback = app_commands.describe(**{a.name: a.description for a in definition.arguments})(callback)
                tree.add_command(
                    app_commands.Command(
                        name=definition.name,
                        description=definition.description,
                        callback=callback,
                    )
                )

        @client.event
        async def on_ready() -> None:
            nonlocal commands_synced
            logger.info("Discord adapter ready: {}", client.user)
            if command_service is not None and not commands_synced:
                try:
                    await tree.sync()
                    commands_synced = True
                    logger.info("Discord slash commands synced")
                except Exception:
                    logger.exception("Failed to sync Discord slash commands")

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
                conversation_id = _discord_group_conversation_id(
                    message.channel.id,
                    message.author.id,
                    group_sessions_per_user=self._group_sessions_per_user,
                )

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

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()


def _make_discord_command_callback(core: GatewayProtocol, definition: CommandDefinition, group_sessions_per_user: bool):
    """依 definition.arguments 產生 slash command callback；每個參數對應一個字串選項"""
    import discord

    async def callback(interaction: Any, **options: Optional[str]) -> None:
        args = " ".join(str(options[a.name]) for a in definition.arguments if options.get(a.name))
        await _dispatch_discord_interaction_command(
            core,
            interaction,
            definition.name,
            args,
            group_sessions_per_user=group_sessions_per_user,
        )

    # discord.py 由函式簽名推導 slash command 選項
    params = [inspect.Parameter("interaction", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=discord.Interaction)]
    for arg in definition.arguments:
        params.append(
            inspect.Parameter(
                arg.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=str if arg.required else Optional[str],
                default=inspect.Parameter.empty if arg.required else None,
            )
        )
    callback.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return callback


async def _dispatch_discord_interaction_command(
    core: GatewayProtocol,
    interaction: Any,
    command_name: str,
    args: str = "",
    *,
    group_sessions_per_user: bool = True,
) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
    except Exception:
        logger.debug("Discord interaction defer failed")

    mode, conversation_id = _discord_interaction_conversation(
        interaction,
        group_sessions_per_user=group_sessions_per_user,
    )
    user = interaction.user
    content = f"/{command_name}" + (f" {args}" if args else "")
    request = IncomingRequest(
        request_id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        mode=mode,
        sender=Sender(
            user_id=f"discord:user:{user.id}",
            display_name=getattr(user, "display_name", None) or getattr(user, "name", str(user.id)),
        ),
        source=DiscordAdapter.name,
        content=content,
        platform_command=command_name,
        reply_fn=_make_discord_interaction_reply_fn(interaction),
    )
    await core.dispatch(request)


def _discord_interaction_conversation(
    interaction: Any, *, group_sessions_per_user: bool = True
) -> tuple[ConversationMode, str]:
    if getattr(interaction, "guild", None) is None:
        return ConversationMode.direct, f"discord:dm:{interaction.user.id}"
    channel_id = getattr(interaction, "channel_id", None) or getattr(getattr(interaction, "channel", None), "id", None)
    return ConversationMode.group, _discord_group_conversation_id(
        channel_id,
        interaction.user.id,
        group_sessions_per_user=group_sessions_per_user,
    )


def _discord_group_conversation_id(channel_id: Any, user_id: Any, *, group_sessions_per_user: bool) -> str:
    base = f"discord:channel:{channel_id}"
    if group_sessions_per_user:
        return f"{base}:user:{user_id}"
    return base


def _make_discord_interaction_reply_fn(interaction: Any) -> ReplyFn:
    buffer: list[str] = []

    async def reply_fn(
        response: Optional[OutgoingResponse] = None, *, chunk: Optional[str] = None, event: Optional[Event] = None
    ) -> None:
        if event is not None:
            apply_stream_reset(buffer, event)
            return
        if chunk is not None:
            buffer.append(chunk)
            return
        if response is None:
            return
        final = response.content or "".join(buffer)
        if not final:
            return
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(final)
            else:
                await interaction.edit_original_response(content=final)
        except Exception:
            logger.exception("Failed to send Discord interaction response")

    return reply_fn


def _make_discord_reply_fn(message: Any, stream_edit: bool = True) -> ReplyFn:
    """建立綁定到此 Discord 訊息的 reply_fn

    stream_edit=True：每次收到 chunk 時 edit 同一則訊息模擬串流
    stream_edit=False：等最終 response 再一次送出
    """
    sent_message = None
    buffer: list[str] = []

    async def reply_fn(
        response: Optional[OutgoingResponse] = None, *, chunk: Optional[str] = None, event: Optional[Event] = None
    ) -> None:
        nonlocal sent_message, buffer
        if event is not None:
            apply_stream_reset(buffer, event)
            return

        if chunk is not None and stream_edit:
            buffer.append(chunk)
            content = "".join(buffer)
            if sent_message is None:
                sent_message = await message.channel.send(content)
            else:
                await sent_message.edit(content=content)
        elif response is not None:
            final = response.content or "".join(buffer)
            if not final:
                return
            if sent_message is not None:
                await sent_message.edit(content=final)
            else:
                await message.channel.send(final)

    return reply_fn
