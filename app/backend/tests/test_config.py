import logging

import pytest
from pydantic import SecretStr, ValidationError

from api import config as config_module
from api.config import AppConfig, ComputeConfig, ConfigError, DbConfig, SimConfig, check_config, load_config


@pytest.fixture(autouse=True)
def _fresh_load_config():
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def test_defaults_use_mocks_with_a_warning_each():
    config = AppConfig()

    errors, warnings = check_config(config)

    assert (config.llm.backend, config.sim.backend, config.compute.enabled) == ("mock", "mock", ["mock"])
    assert errors == []
    assert len(warnings) == 3


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


LOCAL_SIM = SimConfig(backend="http", url="http://127.0.0.1:9000")


def test_compute_variables_fill_the_compute_section_and_keep_the_token_secret(monkeypatch, caplog):
    for name, value in {
        "COMPUTE_BACKENDS": "Brev, gb10",
        "COMPUTE_BREV_WSL": "Ubuntu",
        "COMPUTE_BREV_TOKEN": "brev-test-token",
        "COMPUTE_AUTO_STOP_MINUTES": "5",
        "COMPUTE_SIM_ARGS": "--envs 64",
        "COMPUTE_GB10_SIM_PORT": "9012",
        "COMPUTE_GB10_SIM_ARGS": "--envs 16",
        "SIM_BACKEND": "http",
        "SIM_URL": "http://127.0.0.1:9000",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(config_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    caplog.set_level(logging.INFO)

    config = load_config()

    compute = config.compute
    assert compute.enabled == ["brev", "gb10"]
    assert (compute.brev_wsl, compute.auto_stop_minutes, compute.sim_args) == ("Ubuntu", 5, "--envs 64")
    assert (compute.gb10_host, compute.gb10_user, compute.gb10_sim_port, compute.gb10_sim_args) == (
        "spark1.ai.msoe.edu",
        "hackathon11",
        9012,
        "--envs 16",
    )
    assert compute.brev_token.get_secret_value() == "brev-test-token"
    assert "brev-test-token" not in repr(config) and "brev-test-token" not in caplog.text


@pytest.mark.parametrize("backends", ["", "brev,aws", "mock, ,gpu"])
def test_unknown_targets_are_refused(backends):
    with pytest.raises(ValidationError, match="comma-separated"):
        ComputeConfig(backends=backends)


@pytest.mark.parametrize("sim", [SimConfig(), SimConfig(backend="http", url="http://gpu-box:9000")])
@pytest.mark.parametrize("backends", ["brev", "gb10"])
def test_a_real_target_needs_the_http_sim_at_a_local_address(sim, backends, monkeypatch):
    monkeypatch.setattr(config_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    errors, _ = check_config(AppConfig(sim=sim, compute=ComputeConfig(backends=backends)))

    assert any("SIM_BACKEND=http and a local SIM_URL" in error for error in errors)


def test_a_missing_brev_cli_is_an_error_that_says_what_to_set(monkeypatch):
    monkeypatch.setattr(config_module.shutil, "which", lambda name: None)

    errors, _ = check_config(AppConfig(sim=LOCAL_SIM, compute=ComputeConfig(backends="brev")))

    assert len(errors) == 1
    assert "COMPUTE_BREV_CLI" in errors[0] and "COMPUTE_BREV_WSL=Ubuntu" in errors[0]


def test_brev_through_wsl_needs_wsl(monkeypatch):
    monkeypatch.setattr(config_module.shutil, "which", lambda name: None)

    errors, _ = check_config(AppConfig(sim=LOCAL_SIM, compute=ComputeConfig(backends="brev", brev_wsl="Ubuntu")))

    assert len(errors) == 1 and "there's no wsl command" in errors[0]


def test_the_gb10_needs_ssh_and_nothing_else(monkeypatch):
    monkeypatch.setattr(config_module.shutil, "which", lambda name: None if name == "ssh" else f"/usr/bin/{name}")

    errors, warnings = check_config(AppConfig(sim=LOCAL_SIM, compute=ComputeConfig(backends="gb10")))

    assert len(errors) == 1 and "COMPUTE_SSH" in errors[0]
    assert not any("Compute" in warning for warning in warnings)  # implemented: no "not implemented" warning any more


def test_demo_data_runs_in_its_own_directory_and_database(tmp_path):
    config = AppConfig(data_dir=tmp_path, demo_data=True)

    assert config.data_dir == tmp_path / "demo"
    assert config.db.url.get_secret_value().endswith("/demo/app.db")
    assert any("Demo data" in warning for warning in check_config(config)[1])


def test_demo_data_refuses_an_explicit_database(tmp_path):
    with pytest.raises(ValidationError, match="DEMO_DATA"):
        AppConfig(data_dir=tmp_path, demo_data=True, db=DbConfig(url=SecretStr("sqlite:///elsewhere.db")))
