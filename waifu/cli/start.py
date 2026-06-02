import argparse
import sys
from pathlib import Path
from typing import List, Union

from waifu.logger import setup_logging
from waifu.store.paths import AppPaths


def cmd_start(args: List[str]) -> None:
    parser = argparse.ArgumentParser(prog="waifu start", description="Start the waifu server")
    parser.add_argument("--config", "-c", default="default", help="Config file path)")
    parser.add_argument("--host", default=None, help="Override host")
    parser.add_argument("--port", "-p", type=int, default=None, help="Override port")
    parser.add_argument("--app", default=None, help="FastAPI app import path, e.g. myapp:app")
    parser.add_argument("--reload", action="store_true", help="Enable hot reload (dev)")
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    parser.add_argument("--debug", action="store_true", help="Shorthand for --log-level debug")
    ns = parser.parse_args(args)

    if ns.debug:
        ns.log_level = "debug"

    setup_logging(level=ns.log_level.upper())

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    if ns.config == "default":
        config = _load_config(AppPaths.resolve().config_file)
    else:
        config = _load_config(ns.config)
    host = ns.host or config.gateway.host
    port = ns.port or config.gateway.port

    if ns.app:
        app_path = ns.app
    else:
        app_path = _build_default_app(config)

    uvicorn.run(
        app_path,
        host=host,
        port=port,
        reload=ns.reload,
        log_level=ns.log_level.lower(),
    )


def _load_config(path: Union[str, Path]):
    from waifu.config import WaifuConfig

    base_url_defaults = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/chat/completions",
        "google": "https://generativelanguage.googleapis.com/v1beta/chat/completions",
        "ollama": "http://localhost:11434/v1/chat/completions",
    }

    config_path = Path(path)
    if not config_path.exists():
        print(f"Config file not found: {path}", file=sys.stderr)
        sys.exit(1)

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    elif suffix in (".yaml", ".yml"):
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f)
    elif suffix == ".json":
        import json

        with open(config_path) as f:
            data = json.load(f)
    else:
        print(f"Unsupported config format: {suffix}", file=sys.stderr)
        sys.exit(1)

    if "base_url" not in data["provider"]:
        data["provider"]["base_url"] = base_url_defaults.get(data["provider"]["provider"])

    return WaifuConfig(**data)


def _build_default_app(config) -> str:
    import waifu._cli_app as cli_app_module

    cli_app_module._config = config
    return "waifu._cli_app:app"
