import sys
from typing import List

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.widgets import Button, Footer, Header, Input, Static

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

    def __init__(self, config) -> None:
        super().__init__()
        from waifu.waifu import Waifu

        self._waifu = Waifu(config, localmode=True)
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(id="chat-log")
        with Horizontal(id="input-bar"):
            yield Input(placeholder="Type a message… (Enter to send)", id="chat-input")
            yield Button("Send", id="send-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._init_waifu()
        self.query_one("#chat-input", Input).focus()

    @work
    async def _init_waifu(self) -> None:
        await self._waifu.start()

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
        from waifu_types import ConversationMode, IncomingRequest, Sender

        self._busy = True
        log = self.query_one("#chat-log", ScrollableContainer)

        user_widget = ChatMessage("user", text)
        await log.mount(user_widget)
        log.scroll_end(animate=False)

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

        try:
            result = await self._waifu.dispatch(request)
            final = "".join(chunks) or result.content
            asst_widget.update(final)
        except Exception as exc:
            asst_widget.update(f"[red]Error:[/red] {exc}")

        log.scroll_end(animate=False)
        self._busy = False
        self.query_one("#chat-input", Input).focus()


def cmd_tui(args: List[str]) -> None:
    from waifu.cli.config import _load_raw
    from waifu.config import WaifuConfig

    raw = _load_raw()
    if not raw.get("provider"):
        from waifu.cli._console import err_console

        err_console.print("[red]No config found.[/red] Run [bold]waifu init[/bold] to get started.")
        sys.exit(1)

    config = WaifuConfig(**raw)
    app = WaifuTUI(config=config)
    app.run()
