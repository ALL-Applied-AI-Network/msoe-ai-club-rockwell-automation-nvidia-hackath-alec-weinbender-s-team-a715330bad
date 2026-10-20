import logging

import pytest
from pydantic import SecretStr, ValidationError

from api.config import AppConfig, ConfigError, DbConfig, check_config, load_config


@pytest.fixture(autouse=True)
def _fresh_load_config():
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def test_defaults_use_mocks_with_a_warning_each():
    config = AppConfig()

    errors, warnings = check_config(config)

    assert (config.llm.backend, config.sim.backend) == ("mock", "mock")
    assert errors == []
    assert len(warnings) == 2


def test_existing_variable_names_fill_each_client_config(monkeypatch, tmp_path):
    for name, value in {
        "LLM_BACKEND": "http",
        "LLM_URL": "http://llm:9100/suggest",
        "LLM_MODEL": "custom",
        "SIM_BACKEND": "http",
        "SIM_URL": "http://gpu:9000",
        "SIM_TIMEOUT_S": "5",
        "DATA_DIR": str(tmp_path),
        "LOG_LEVEL": "debug",
    }.items():
        monkeypatch.setenv(name, value)

    config = AppConfig()

    assert (config.llm.backend, config.llm.url, config.llm.model) == ("http", "http://llm:9100/suggest", "custom")
    assert (config.sim.backend, config.sim.url, config.sim.timeout_s) == ("http", "http://gpu:9000", 5)
    assert config.data_dir == tmp_path
    assert config.log_level == "DEBUG"


def test_api_key_selects_claude_and_is_never_shown(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    caplog.set_level(logging.INFO)

    config = load_config()

    assert config.llm.backend == "anthropic"
    assert config.llm.api_key.get_secret_value() == "sk-ant-test-secret"
    assert "sk-ant-test-secret" not in repr(config)
    assert "sk-ant-test-secret" not in caplog.text


def test_selected_backends_missing_settings_are_all_reported(monkeypatch, caplog):
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("SIM_BACKEND", "http")

    with pytest.raises(ConfigError):
        load_config()

    assert "ANTHROPIC_API_KEY" in caplog.text
    assert "SIM_URL" in caplog.text


def test_invalid_value_names_the_variable(monkeypatch, caplog):
    monkeypatch.setenv("SIM_BACKEND", "isaac")

    with pytest.raises(ConfigError):
        load_config()

    assert "SIM_BACKEND" in caplog.text


def test_demo_data_runs_in_its_own_directory_and_database(tmp_path):
    config = AppConfig(data_dir=tmp_path, demo_data=True)

    assert config.data_dir == tmp_path / "demo"
    assert config.db.url.get_secret_value().endswith("/demo/app.db")
    assert any("Demo data" in warning for warning in check_config(config)[1])


def test_demo_data_refuses_an_explicit_database(tmp_path):
    with pytest.raises(ValidationError, match="DEMO_DATA"):
        AppConfig(data_dir=tmp_path, demo_data=True, db=DbConfig(url=SecretStr("sqlite:///elsewhere.db")))
