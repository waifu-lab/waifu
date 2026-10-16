# waifu_sdk


## Plugin

```python
from waifu_sdk import BaseHook, BasePlugin, CommandDefinition, HookContext, PluginContext, tool


@tool
async def roll_dice(sides: int = 6) -> str:
    """擲一顆骰子"""
    import random

    return str(random.randint(1, sides))


class GreetingHook(BaseHook):
    name = "greeting"
    priority = 30

    async def post(self, ctx: HookContext) -> HookContext:
        ctx.emit({"event": "greeting", "data": {"user": ctx.request.sender.display_name}})
        return ctx


class DicePlugin(BasePlugin):
    name = "dice"

    async def on_load(self, ctx: PluginContext) -> None:
        ctx.register_tool(roll_dice)
        ctx.register_hook(GreetingHook())

        async def dice_command(request, args: str) -> str:
            return await roll_dice.func(int(args or 6))

        ctx.register_command(CommandDefinition("dice", "Roll a dice"), dice_command)
```

插件停用（disable）或卸載（unload）時，透過 `ctx.register_*` 註冊的 hook / tool / 指令 / MCP 會自動移除。

## 自訂輸出標籤

讓 LLM 輸出 `[pose:wave]` 之類的行內標籤，並在送給使用者前移除：

```python
from waifu_sdk import BaseHook, HookContext, InlineTagTransformer


class PoseHook(BaseHook):
    name = "pose"
    priority = 25

    def __init__(self) -> None:
        self._tags = InlineTagTransformer("pose", ["pose"])

    def output_transformers(self):
        return (self._tags,)

    async def post(self, ctx: HookContext) -> HookContext:
        for tag in self._tags.find(ctx.response or ""):
            ctx.emit({"event": "pose", "data": {"pose": tag.value}})
        return ctx
```

`ctx.response` 保留原始輸出；串流 chunk、最終顯示內容、歷史紀錄與 TTS 文字都會經過 `output_transformers()`。

## Gateway Adapter

```python
from waifu_sdk import BaseGatewayAdapter, ConversationMode, GatewayProtocol, IncomingRequest, Sender


class EchoAdapter(BaseGatewayAdapter):
    name = "echo"

    async def start(self, core: GatewayProtocol) -> None:
        async def reply_fn(response=None, *, chunk=None, event=None) -> None:
            if response is not None:
                print(response.content)

        await core.dispatch(
            IncomingRequest(
                conversation_id="echo:1",
                mode=ConversationMode.direct,
                sender=Sender(user_id="echo:user", display_name="User"),
                source=self.name,
                content="hello",
                reply_fn=reply_fn,
            )
        )
```

`reply_fn` 的呼叫方式見 `waifu_sdk.ReplyFn`；需要執行期服務（例如語音）時覆寫 `on_mount(services)`，以 `services.get(VoiceServiceProtocol)` 取得。
