import sys
from typing import List, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Footer, Header, Input, Label, Markdown, Static

# TODO 重製TUI

_CSS = """
Screen {
    background: $surface;
}

#chat-log {
    height: 1fr;
    padding: 1 2;
    overflow-y: auto;
}

.message-user {
    color: $accent;
    margin-top: 1;
    margin-bottom: 0;
}

.message-assistant {
    color: $text;
    margin-top: 0;
    margin-bottom: 1;
}

.message-label {
    text-style: bold;
    margin-bottom: 0;
}

#input-bar {
    height: 3;
    padding: 0 1;
    dock: bottom;
}

#chat-input {
    width: 1fr;
}

#send-btn {
    width: 8;
    margin-left: 1;
}

#status {
    dock: bottom;
    height: 1;
    padding: 0 2;
    color: $text-muted;
}
"""


class ChatMessage(Static):
    """A single chat bubble (user or assistant)."""

    def __init__(self, role: str, content: str) -> None:
        label = "You" if role == "user" else "Waifu"
        css_class = "message-user" if role == "user" else "message-assistant"
        super().__init__(f"[bold]{label}[/bold]\n{content}", classes=css_class)


class WaifuTUI(App):
    """Waifu interactive chat TUI."""

    CSS = _CSS
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, provider_cfg, context_cfg) -> None:
        super().__init__()
        self._provider_cfg = provider_cfg
        self._context_cfg = context_cfg
        self._history: list = []
        self._agent_runner = None
        self._provider = None
        self._context_builder = None
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(id="chat-log")
        with Horizontal(id="input-bar"):
            yield Input(placeholder="Type a message… (Enter to send)", id="chat-input")
            yield Button("Send", id="send-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._setup_pipeline()
        self.query_one("#chat-input", Input).focus()

    def _setup_pipeline(self) -> None:
        from waifu.agent import AgentRunner, ContextBuilder
        from hai.providers.openai import OpenAI

        # FIXME: 這裡直接用 OpenAI provider，應該改成支援多 provider 的工廠模式
        self._provider = OpenAI(
            name="waifu-tui",
            api_key=self._provider_cfg.api_key,
            model=self._provider_cfg.model,
            temperature=self._provider_cfg.temperature,
            max_tokens=self._provider_cfg.max_tokens,
            stream=True,
        )
        self._context_builder = ContextBuilder(self._context_cfg)
        self._agent_runner = AgentRunner(self._provider)

    @on(Button.Pressed, "#send-btn")
    @on(Input.Submitted, "#chat-input")
    def handle_send(self) -> None:
        inp = self.query_one("#chat-input", Input)
        text = inp.value.strip()
        if not text or self._busy:
            return
        inp.value = ""
        self._send_message(text)

    @work(exclusive=True)
    async def _send_message(self, text: str) -> None:
        from waifu.agent.context import AgentInput
        from waifu.gateway.session import Session
        from waifu.plugin import PluginRegistry
        from waifu_types import ConversationMode, HookContext, IncomingRequest, Sender

        self._busy = True
        log = self.query_one("#chat-log", ScrollableContainer)

        # Display user message
        user_widget = ChatMessage("user", text)
        await log.mount(user_widget)
        log.scroll_end(animate=False)

        # Placeholder for assistant response
        asst_widget = ChatMessage("assistant", "…")
        await log.mount(asst_widget)
        log.scroll_end(animate=False)

        chunks: list[str] = []

        def on_chunk(chunk: str) -> None:
            chunks.append(chunk)
            asst_widget.update("".join(chunks))
            log.scroll_end(animate=False)

        request = IncomingRequest(
            conversation_id="tui:main",
            mode=ConversationMode.session,
            sender=Sender(user_id="tui", display_name="User"),
            source="tui",
            content=text,
            reply_fn=lambda response=None, *, chunk=None: on_chunk(chunk) if chunk else None,
        )

        session = Session(conversation_id="tui:main")
        session.add_messages(self._history)

        ctx = HookContext(request=request, session=session, messages=list(self._history))
        plugin_registry = PluginRegistry()
        agent_input = await self._context_builder.build(ctx, plugin_registry)

        try:
            result = await self._agent_runner.run(ctx, agent_input)
            final = "".join(chunks)
            if not final:
                for msg in reversed(result.messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        final = msg["content"]
                        break
            asst_widget.update(final)

            # Update history
            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": final})

        except Exception as exc:
            asst_widget.update(f"[red]Error:[/red] {exc}")

        log.scroll_end(animate=False)
        self._busy = False
        self.query_one("#chat-input", Input).focus()


def cmd_tui(args: List[str]) -> None:
    from waifu.cli.config import _load_raw
    from waifu.config import ContextConfig, ProviderConfig

    raw = _load_raw()
    if not raw.get("provider"):
        from waifu.cli._console import err_console

        err_console.print("[red]No config found.[/red] Run [bold]waifu init[/bold] to get started.")
        sys.exit(1)

    provider_cfg = ProviderConfig(**raw["provider"])
    context_cfg = ContextConfig(**raw.get("context", {}))

    app = WaifuTUI(provider_cfg=provider_cfg, context_cfg=context_cfg)
    app.run()
