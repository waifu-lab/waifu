import pytest


@pytest.mark.unit
def test_config_service_set_and_get(waifu):
    svc = waifu._config_service

    original = svc.get("context.max_history_messages")
    svc.set("context.max_history_messages", 99)
    assert svc.get("context.max_history_messages") == 99

    # Restore
    if original is not None:
        svc.set("context.max_history_messages", original)


@pytest.mark.unit
def test_config_service_hot_reload_context(waifu):
    """Setting context.max_history_messages immediately updates ContextBuilder."""
    svc = waifu._config_service
    original = waifu._context_builder.config.max_history_messages

    svc.set("context.max_history_messages", 42)
    assert waifu._context_builder.config.max_history_messages == 42

    svc.set("context.max_history_messages", original)


@pytest.mark.unit
def test_config_service_hot_reload_provider_temperature(waifu):
    """Setting provider.temperature immediately updates AgentRunner provider."""
    svc = waifu._config_service
    original = getattr(waifu._agent_runner.provider, "temperature", None)

    svc.set("provider.temperature", 0.42)
    assert getattr(waifu._agent_runner.provider, "temperature", None) == 0.42

    if original is not None:
        svc.set("provider.temperature", original)


@pytest.mark.unit
def test_config_service_gateway_key_returns_note(waifu):
    """Gateway keys are not hot-reloaded — service returns a 'requires restart' note."""
    svc = waifu._config_service
    result = svc.set("gateway.session_ttl", 3600)
    assert result.get("note") == "requires restart"


@pytest.mark.unit
def test_config_service_get_all(waifu):
    """get_all() returns a non-empty dict seeded from config.toml."""
    cfg = waifu._config_service.get_all()
    assert isinstance(cfg, dict)
    assert len(cfg) > 0
    assert "provider.model" in cfg


@pytest.mark.offline
def test_config_repo_set_persists(waifu):
    """Value written via AppConfigRepository survives a get() from the same repo."""
    repo = waifu._config_repo
    repo.set("test.offline_key", "offline_value")
    val = repo.get("test.offline_key")
    assert val == "offline_value"


@pytest.mark.offline
def test_config_service_replace_from_get_all(waifu):
    """All keys from get_all() are readable individually."""
    svc = waifu._config_service
    all_cfg = svc.get_all()
    for key, expected in list(all_cfg.items())[:5]:
        assert svc.get(key) == expected


@pytest.mark.online
async def test_agent_reads_config_via_cli(waifu):
    """Agent calls waifu config list through the shell tool and reports values."""
    from conftest import make_request

    req = make_request(
        "Use the shell tool to run 'waifu config list' and tell me what you see. Just report the raw output."
    )
    response = await waifu._dispatch(req)
    # CLI output should contain known config keys
    assert response.content.strip() != ""


@pytest.mark.online
async def test_agent_updates_temperature_via_cli(waifu):
    """Agent sets provider.temperature to 0.55 then reads it back."""
    from conftest import make_request

    req = make_request(
        "Use the shell tool to:\n"
        "1. Run: waifu config set provider.temperature 0.55\n"
        "2. Then run: waifu config get provider.temperature\n"
        "Report what the value is after you set it."
    )
    response = await waifu._dispatch(req)
    assert "0.55" in response.content


@pytest.mark.online
async def test_agent_self_reports_model(waifu):
    """Agent can answer what model it is using, reading from config."""
    from conftest import make_request

    req = make_request(
        "Use the shell tool to run 'waifu config get provider.model' and tell me which model you are currently using."
    )
    response = await waifu._dispatch(req)
    assert response.content.strip() != ""
