import os
import sys
from pathlib import Path

_APP = "waifu"


class AppPaths:
    """
    Config dir (config.toml, waifu.db):
    Windows     : %APPDATA%\\waifu\\
    macOS       : ~/Library/Application Support/waifu/
    Linux       : $XDG_DATA_HOME/waifu/  (fallback: ~/.local/share/waifu/)

    Data dir (conversations/, cards/, mcp/, skills/):
    Windows     : %USERPROFILE%\\Documents\\waifu\\
    macOS/Linux : $XDG_CONFIG_HOME/waifu/  (fallback: ~/.config/waifu/)

    Env overrides:
    WAIFU_DATA_DIR    override data directory
    WAIFU_CONFIG_DIR  override config directory
    WAIFU_CONFIG      override full path to config.toml
    WAIFU_GATEWAY_CONFIG override full path to gateway.config.yaml
    """

    def __init__(self, data_dir: Path, config_dir: Path) -> None:
        self.data_dir = data_dir
        self.config_dir = config_dir

    @property
    def config_file(self) -> Path:
        if env := os.environ.get("WAIFU_CONFIG"):
            return Path(env)
        return self.config_dir / "config.toml"

    @property
    def gateway_config_file(self) -> Path:
        if env := os.environ.get("WAIFU_GATEWAY_CONFIG"):
            return Path(env)
        return self.config_dir / "gateway.config.yaml"

    @property
    def db_file(self) -> Path:
        return self.config_dir / "waifu.db"

    @property
    def mcp_config_file(self) -> Path:
        return self.data_dir / "mcp.json"

    @property
    def conversations_dir(self) -> Path:
        return self.data_dir / "conversations"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"

    @property
    def mcp_dir(self) -> Path:
        return self.data_dir / "mcp"

    @property
    def cards_dir(self) -> Path:
        return self.data_dir / "cards"

    @property
    def characters_dir(self) -> Path:
        return self.data_dir / "characters"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    def ensure_dirs(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.mcp_dir.mkdir(parents=True, exist_ok=True)
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.characters_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def resolve(cls) -> "AppPaths":
        """Build AppPaths from environment + platform defaults."""
        if env := os.environ.get("WAIFU_CONFIG_DIR"):
            config_dir = Path(env)
        elif sys.platform == "win32":
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / _APP
        elif sys.platform == "darwin":
            config_dir = Path.home() / "Library" / "Application Support" / _APP
        else:
            config_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / _APP

        if env := os.environ.get("WAIFU_DATA_DIR"):
            data_dir = Path(env)
        elif sys.platform == "win32":
            data_dir = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents" / _APP
        else:
            data_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / _APP

        paths = cls(data_dir=data_dir, config_dir=config_dir)
        paths.ensure_dirs()
        return paths
