import pytest

BASE_TOML = """\
# 我的設定
character = "shuvi"

[provider]
provider = "openai"
api_key = "sk-test"  # 測試用 key
model = "model-a"
"""


@pytest.fixture()
def sync(tmp_dir):
    from waifu.config.sync import ConfigSync
    from waifu.store.models import Database
    from waifu.store.repositories import AppConfigRepository

    Database(tmp_dir / "waifu.db").init()
    path = tmp_dir / "config.toml"
    path.write_text(BASE_TOML, encoding="utf-8")
    return ConfigSync(AppConfigRepository(), path)


def _edit_file(sync, old: str, new: str) -> None:
    text = sync.path.read_text(encoding="utf-8")
    assert old in text
    sync.path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.unit
def test_first_load_imports_toml_and_writes_back_defaults(sync):
    from waifu.store.repositories import AppConfigRepository

    config = sync.load()
    assert config.provider.model == "model-a"
    assert config.character == "shuvi"

    repo = AppConfigRepository()
    assert repo.get("provider.model") == "model-a"
    assert repo.get("gateway.port") == 8765
    assert "__config_toml_snapshot__" not in repo.get_all()

    text = sync.path.read_text(encoding="utf-8")
    assert "# 我的設定" in text and "# 測試用 key" in text
    assert "[gateway]" in text  # 生效中的預設值也寫回，toml 反映真實設定


@pytest.mark.unit
def test_api_change_kept_and_user_edit_applied(sync):
    sync.load()
    sync.set("provider.temperature", 0.3)  # 透過 API 修改
    assert "temperature = 0.3" in sync.path.read_text(encoding="utf-8")

    _edit_file(sync, 'model = "model-a"', 'model = "model-b"')  # 使用者直接改檔
    config = sync.load()
    assert config.provider.model == "model-b"
    assert config.provider.temperature == 0.3


@pytest.mark.unit
def test_user_edit_not_lost_when_api_sets_other_key(sync):
    sync.load()
    _edit_file(sync, 'model = "model-a"', 'model = "model-c"')  # server 運行中使用者改檔
    config = sync.set("context.max_history_messages", 5)  # 接著 API 改別的 key
    assert config.provider.model == "model-c"
    assert 'model = "model-c"' in sync.path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_user_removed_key_falls_back_to_default(sync):
    sync.load()
    sync.set("provider.temperature", 0.3)
    _edit_file(sync, "temperature = 0.3\n", "")
    assert sync.load().provider.temperature == 0.7


@pytest.mark.unit
def test_invalid_set_is_rejected_without_writing(sync):
    from waifu.config.sync import ConfigError

    sync.load()
    before = sync.path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        sync.set("gateway.port", "not-a-port")
    assert sync.path.read_text(encoding="utf-8") == before
    assert sync.load().gateway.port == 8765


@pytest.mark.unit
def test_legacy_voice_config_migrated_in_file(sync):
    _edit_file(
        sync,
        "[provider]",
        '[voice]\ntts_backend = "gptsovits"\n\n[voice.gptsovits_tts]\nbase_url = "http://tts"\n\n[provider]',
    )
    config = sync.load()
    assert config.voice is not None and config.voice.tts is not None
    assert config.voice.tts.backend == "gptsovits"
    text = sync.path.read_text(encoding="utf-8")
    assert "tts_backend" not in text and "gptsovits_tts" not in text
    assert 'backend = "gptsovits"' in text


@pytest.mark.unit
def test_set_without_toml_keeps_db_and_creates_file(sync):
    from waifu.config import ProviderConfig, WaifuConfig

    sync.path.unlink()
    sync.adopt(WaifuConfig(provider=ProviderConfig(provider="openai", api_key="k", model="m")))
    config = sync.set("context.max_history_messages", 7)
    assert config.provider.model == "m"
    assert config.context.max_history_messages == 7
    assert "max_history_messages = 7" in sync.path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_crlf_file_stays_crlf(sync):
    sync.path.write_bytes(BASE_TOML.replace("\n", "\r\n").encode("utf-8"))
    sync.load()
    sync.set("provider.temperature", 0.3)
    raw = sync.path.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.unit
def test_legacy_memory_config_migrated_in_file(sync):
    _edit_file(
        sync,
        "[provider]",
        '[memory]\nbackend = "history_tree"\n\n[memory.history_tree]\ntop_k = 9\n\n[memory.file]\n'
        "share_direct_memories = false\n\n[provider]",
    )
    config = sync.load()
    assert config.memory.backend == "history_tree"
    assert config.memory.top_k == 9  # type: ignore[union-attr]
    text = sync.path.read_text(encoding="utf-8")
    assert "[memory.history_tree]" not in text and "[memory.file]" not in text


@pytest.mark.unit
def test_section_set_replaces_whole_section(sync):
    sync.load()
    config = sync.set("voice", {"tts": {"api_key": "k"}})
    assert config.voice is not None and config.voice.tts is not None
    assert config.voice.tts.backend == "openai"
    assert sync.set("voice", None).voice is None
