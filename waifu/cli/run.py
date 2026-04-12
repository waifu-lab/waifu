import argparse
import asyncio
import sys
from typing import List

from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from waifu.cli._console import console, err_console


def cmd_run(args: List[str]) -> None:
    parser = argparse.ArgumentParser(prog="waifu run", description="Run an AI completion")
    parser.add_argument("prompt", nargs="*", help="Prompt text (reads stdin if omitted)")
    parser.add_argument(
        "-m", "--model", default=None, metavar="provider:model", help="Override model (e.g. openai:gpt-4o)"
    )
    parser.add_argument("-s", "--system", default=None, metavar="prompt", help="Prepend a system instruction")
    parser.add_argument("-t", "--temperature", type=float, default=None, help="Temperature (0-2)")
    parser.add_argument("--raw", action="store_true", help="Strip markdown, print plain text")
    parser.add_argument("--no-stream", action="store_true", help="Buffer output, print at end")
    parser.add_argument("-l", "--list-models", action="store_true", help="List available models and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show thinking and tool calls")
    ns = parser.parse_args(args)

    if ns.list_models:
        _list_models()
        return

    if ns.prompt:
        prompt = " ".join(ns.prompt)
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    else:
        err_console.print("[red]Error:[/red] no prompt provided. Pass text or pipe via stdin.")
        sys.exit(1)

    asyncio.run(_run_async(prompt, ns))


async def _run_async(prompt: str, ns: argparse.Namespace) -> None:
    from waifu.cli.config import _load_raw
    from waifu.config import ContextConfig, ProviderConfig, WaifuConfig
    from waifu.agent import AgentRunner, ContextBuilder
    from waifu_types import ConversationMode, HookContext, IncomingRequest, Sender
    from waifu.plugin import PluginRegistry
    from hai.providers.providers import ProviderText

    raw_cfg = _load_raw()
    if not raw_cfg.get("provider"):
        err_console.print("[red]No config found.[/red] Run [bold]waifu init[/bold] to get started.")
        sys.exit(1)

    provider_cfg = ProviderConfig(**raw_cfg["provider"])
    if ns.model:
        # accept "provider:model" or just "model"
        parts = ns.model.split(":", 1)
        provider_cfg.model = parts[-1]
    if ns.temperature is not None:
        provider_cfg.temperature = ns.temperature
    if ns.no_stream:
        provider_cfg.stream = False

    context_cfg_data = raw_cfg.get("context", {})
    if ns.system:
        context_cfg_data["system_prompt_template"] = ns.system
    context_cfg = ContextConfig(**context_cfg_data)

    provider = ProviderText(
        name="waifu-run",
        api_key=provider_cfg.api_key,
        base_url=provider_cfg.base_url,
        model=provider_cfg.model,
        temperature=provider_cfg.temperature,
        max_tokens=provider_cfg.max_tokens,
        stream=provider_cfg.stream,
    )

    accumulated = []

    def _chunk_handler(chunk: str) -> None:
        accumulated.append(chunk)
        if not ns.no_stream:
            if ns.raw:
                print(chunk, end="", flush=True)
            else:
                # print raw chunks; Live markdown handled below
                print(chunk, end="", flush=True)

    request = IncomingRequest(
        conversation_id="cli:run",
        mode=ConversationMode.session,
        sender=Sender(user_id="cli", display_name="User"),
        source="cli",
        content=prompt,
        reply_fn=lambda response=None, *, chunk=None: _chunk_handler(chunk) if chunk else None,
    )

    plugin_registry = PluginRegistry()
    context_builder = ContextBuilder(context_cfg)
    agent_runner = AgentRunner(provider)

    from waifu.gateway.session import Session

    session = Session(conversation_id="cli:run")

    ctx = HookContext(request=request, session=session, messages=[])
    agent_input = await context_builder.build(ctx, plugin_registry)

    if ns.verbose:
        console.print(f"[dim]model:[/dim] {provider_cfg.model}  [dim]temp:[/dim] {provider_cfg.temperature}")
        console.print()

    result = await agent_runner.run(ctx, agent_input)

    final = "".join(accumulated)
    if not final:
        for msg in reversed(result.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                final = msg["content"]
                break

    if ns.no_stream:
        if ns.raw:
            print(final)
        else:
            console.print(Markdown(final))
    elif not ns.raw:
        # newline after streaming chunks
        print()


def _list_models() -> None:
    from waifu.cli.config import _load_raw

    raw = _load_raw()
    current = raw.get("provider", {}).get("model", "[dim]not set[/dim]")
    console.print(f"[bold]Current model:[/bold] {current}")
    console.print()
    console.print("[dim]Change with:[/dim] waifu config set provider.model <model>")
