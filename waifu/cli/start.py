import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Union

from waifu.logger import setup_logging
from waifu.store.paths import AppPaths


def cmd_start(args: List[str]) -> None:
    parser = argparse.ArgumentParser(prog="waifu start", description="Start the waifu server")
    parser.add_argument("--config", "-c", default="default", help="Config file path)")
    parser.add_argument("--host", default=None, help="Override host")
    parser.add_argument("--port", "-p", type=int, default=None, help="Override port (0 = pick a free port)")
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=_env_int("WAIFU_PARENT_PID"),
        help="Exit when this process exits (or env WAIFU_PARENT_PID)",
    )
    parser.add_argument("--app", default=None, help="FastAPI app import path, e.g. myapp:app")
    parser.add_argument("--reload", action="store_true", help="Enable hot reload (dev)")
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    parser.add_argument("--debug", action="store_true", help="Shorthand for --log-level debug")
    ns = parser.parse_args(args)

    if ns.debug:
        ns.log_level = "debug"

    setup_logging(level=ns.log_level.upper())
    os.environ["WAIFU_LOG_LEVEL"] = ns.log_level.upper()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    paths = AppPaths.resolve()
    config_path = Path(paths.config_file if ns.config == "default" else ns.config)
    config = _load_config(config_path, paths)
    gateway_config = _load_gateway_config(paths.gateway_config_file)
    host = ns.host if ns.host is not None else config.gateway.host
    port = ns.port if ns.port is not None else config.gateway.port

    if ns.reload and (port == 0 or ns.parent_pid is not None):
        print("--port 0 and --parent-pid are not supported with --reload", file=sys.stderr)
        sys.exit(2)

    if ns.app:
        app_path = ns.app
    else:
        app_path = _build_default_app(config, gateway_config, paths, config_path)

    if ns.reload:
        uvicorn.run(
            app_path,
            host=host,
            port=port,
            reload=True,
            log_level=ns.log_level.lower(),
            log_config=None,
            ws="websockets-sansio",
        )
        return

    from waifu.cli._lifecycle import ReadyServer, bind_socket, graceful_exit, watch_parent

    server = ReadyServer(
        uvicorn.Config(
            app_path,
            host=host,
            port=port,
            log_level=ns.log_level.lower(),
            log_config=None,
            ws="websockets-sansio",
        )
    )
    if ns.parent_pid is not None:
        watch_parent(ns.parent_pid, graceful_exit(server))

    sockets = [bind_socket(host, port)] if port == 0 else None
    server.run(sockets=sockets)
    if not server.started:
        sys.exit(3)  # 與 uvicorn.run 的 STARTUP_FAILURE 相同


def _env_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    return int(raw) if raw else None


def _load_config(config_path: Path, paths: AppPaths):
    """
    .toml：與 DB 同步後以 DB 為準（DB 是真實來源，toml 是使用者編輯介面）
    .yaml / .json：一次性指定的設定檔，直接載入（啟動後寫入 DB）
    """
    from waifu.config import WaifuConfig

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        from waifu.config.sync import ConfigError, ConfigSync
        from waifu.store.models import Database
        from waifu.store.repositories import AppConfigRepository

        Database(paths.db_file).init()
        try:
            return ConfigSync(AppConfigRepository(), config_path).load()
        except ConfigError as exc:
            print(f"Invalid config ({config_path}):\n{exc}", file=sys.stderr)
            sys.exit(1)

    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if suffix in (".yaml", ".yml"):
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

    return WaifuConfig(**data)


def _load_gateway_config(path: Union[str, Path]):
    from waifu.gateway.config import GatewayRuntimeConfig

    return GatewayRuntimeConfig.load(Path(path))


def _build_default_app(config, gateway_config, paths: AppPaths, config_path: Path) -> str:
    import waifu._cli_app as cli_app_module

    cli_app_module._config = config
    cli_app_module._gateway_config = gateway_config
    cli_app_module._paths = paths
    cli_app_module._config_path = config_path if config_path.suffix.lower() == ".toml" else None
    return "waifu._cli_app:app"
