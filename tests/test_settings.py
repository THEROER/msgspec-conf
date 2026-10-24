"""Tests for env-settings."""

from __future__ import annotations

from pathlib import Path

import msgspec
import pytest

from msgspec_conf import BaseSettings, load_composed_settings, load_settings


class ExampleSettings(BaseSettings):
    debug: bool = False
    host: str = "localhost"
    port: int = 8000
    timeout: float = 5.5
    tags: list[str] = msgspec.field(default_factory=list)


def test_load_from_defaults_only() -> None:
    settings = ExampleSettings.load(defaults={"PORT": "9000", "DEBUG": "true"})
    assert settings.port == 9000
    assert settings.debug is True


def test_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_HOST", "example.com")
    monkeypatch.setenv("APP_PORT", "8100")

    settings = ExampleSettings.load(prefix="APP_")
    assert settings.host == "example.com"
    assert settings.port == 8100


def test_load_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=envfile.example\nDEBUG=true\n")

    settings = ExampleSettings.load(env_file=env_file)
    assert settings.host == "envfile.example"
    assert settings.debug is True


def test_env_precedence_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=9000\n")
    monkeypatch.setenv("PORT", "9100")

    settings = ExampleSettings.load(env_file=env_file)
    assert settings.port == 9100


def test_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("app_timeout", "12.34")

    settings = ExampleSettings.load(prefix="APP_")
    assert settings.timeout == pytest.approx(12.34)


def test_loads_json_list_values() -> None:
    settings = ExampleSettings.load(
        env={"TAGS": '["landing.live_stats","monitoring.live_status"]'}
    )
    assert settings.tags == ["landing.live_stats", "monitoring.live_status"]


def test_loads_delimited_list_values() -> None:
    settings = ExampleSettings.load(env={"TAGS": "alpha; beta\n gamma"})
    assert settings.tags == ["alpha", "beta", "gamma"]


def test_loads_key_value_dict_values() -> None:
    class MetadataSettings(BaseSettings):
        metadata: dict[str, int] = msgspec.field(default_factory=dict)

    settings = MetadataSettings.load(env={"METADATA": "first=1, second:2; third=3"})

    assert settings.metadata == {"first": 1, "second": 2, "third": 3}


def test_loads_complex_json_values() -> None:
    class PolicySettings(BaseSettings):
        rules: list[dict[str, str | int | list[str]]] = msgspec.field(
            default_factory=list
        )

    settings = PolicySettings.load(
        env={
            "RULES": (
                '[{"id":"policy.example","score":95,'
                '"evidence_urls":["https://example.com"]}]'
            )
        }
    )

    assert settings.rules == [
        {
            "id": "policy.example",
            "score": 95,
            "evidence_urls": ["https://example.com"],
        }
    ]


def test_loads_delimited_list_of_dict_values() -> None:
    class RuleSettings(BaseSettings):
        rules: list[dict[str, int]] = msgspec.field(default_factory=list)

    settings = RuleSettings.load(
        env={"RULES": "id=1,score=95; id=2,score=90\nid=3,score=85"}
    )

    assert settings.rules == [
        {"id": 1, "score": 95},
        {"id": 2, "score": 90},
        {"id": 3, "score": 85},
    ]


def test_invalid_bool_raises_validation_error() -> None:
    with pytest.raises(msgspec.ValidationError, match="invalid value for DEBUG"):
        ExampleSettings.load(env={"DEBUG": "treu"})


def test_loads_file_backed_value(tmp_path: Path) -> None:
    class SecretSettings(BaseSettings):
        token: str = ""
        token_file: str | None = None

    secret_file = tmp_path / "token"
    secret_file.write_text("secret-token\n")

    settings = SecretSettings.load(env={"TOKEN_FILE": str(secret_file)})

    assert settings.token == "secret-token"
    assert settings.token_file == str(secret_file)


def test_load_settings_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "helper.example")

    settings = load_settings(ExampleSettings)
    assert settings.host == "helper.example"


def test_invalid_cls_raises() -> None:
    class Other:
        pass

    with pytest.raises(TypeError):
        load_settings(Other)  # type: ignore[type-var]


def test_load_from_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "host: yaml.example\nport: 7000\ntags:\n  - alpha\n  - beta\n"
    )

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.host == "yaml.example"
    assert settings.port == 7000
    assert settings.tags == ["alpha", "beta"]


def test_load_from_config_file_yml_extension(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("debug: true\n")

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.debug is True


def test_env_precedence_over_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("port: 7000\n")
    monkeypatch.setenv("PORT", "9100")

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.port == 9100


def test_env_file_precedence_over_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("host: yaml.example\nport: 7000\n")
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8500\n")

    settings = ExampleSettings.load(env_file=env_file, config_file=config_file)

    # .env overrides the YAML config, YAML still supplies the untouched field.
    assert settings.port == 8500
    assert settings.host == "yaml.example"


def test_config_file_overrides_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("port: 7000\n")

    settings = ExampleSettings.load(
        config_file=config_file,
        defaults={"PORT": "1000", "HOST": "default.example"},
    )

    assert settings.port == 7000
    assert settings.host == "default.example"


def test_config_file_native_types(tmp_path: Path) -> None:
    class NestedSettings(BaseSettings):
        limits: dict[str, int] = msgspec.field(default_factory=dict)
        rules: list[dict[str, int]] = msgspec.field(default_factory=list)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "limits:\n"
        "  checkout: 20\n"
        "  login: 60\n"
        "rules:\n"
        "  - {id: 1, score: 95}\n"
        "  - {id: 2, score: 90}\n"
    )

    settings = NestedSettings.load(config_file=config_file)

    assert settings.limits == {"checkout": 20, "login": 60}
    assert settings.rules == [{"id": 1, "score": 95}, {"id": 2, "score": 90}]


def test_missing_config_file_is_ignored(tmp_path: Path) -> None:
    settings = ExampleSettings.load(config_file=tmp_path / "absent.yaml")

    assert settings.host == "localhost"


def test_config_file_must_be_mapping(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- just\n- a\n- list\n")

    with pytest.raises(msgspec.ValidationError, match="must contain a mapping"):
        ExampleSettings.load(config_file=config_file)


def test_load_composed_settings_from_config_file(tmp_path: Path) -> None:
    class UpstreamSettings(BaseSettings):
        target: str = ""
        timeout_seconds: float = 5.0

    class AppSettings(msgspec.Struct, kw_only=True):
        debug: bool = False
        service_name: str = "app"
        upstream: UpstreamSettings = msgspec.field(default_factory=UpstreamSettings)

    class Defaults(BaseSettings):
        debug: bool = False
        service_name: str = "composed-service"

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "debug: true\n"
        "service_name: from-yaml\n"
        "upstream:\n"
        "  target: yaml:5000\n"
        "  timeout_seconds: 3.5\n"
    )

    settings = load_composed_settings(
        AppSettings,
        config_file=config_file,
        defaults_cls=Defaults,
        prefixes={"upstream": "UPSTREAM_"},
    )

    assert settings.debug is True
    assert settings.service_name == "from-yaml"
    assert settings.upstream.target == "yaml:5000"
    assert settings.upstream.timeout_seconds == pytest.approx(3.5)


def test_composed_env_overrides_config_file(tmp_path: Path) -> None:
    class UpstreamSettings(BaseSettings):
        target: str = ""
        timeout_seconds: float = 5.0

    class AppSettings(msgspec.Struct, kw_only=True):
        upstream: UpstreamSettings = msgspec.field(default_factory=UpstreamSettings)

    config_file = tmp_path / "config.yaml"
    config_file.write_text("upstream:\n  target: yaml:5000\n  timeout_seconds: 3.5\n")

    settings = load_composed_settings(
        AppSettings,
        env={"UPSTREAM_TIMEOUT_SECONDS": "9.0"},
        config_file=config_file,
        prefixes={"upstream": "UPSTREAM_"},
    )

    assert settings.upstream.target == "yaml:5000"
    assert settings.upstream.timeout_seconds == pytest.approx(9.0)


def test_load_composed_settings_preserves_nested_defaults() -> None:
    class Defaults(BaseSettings):
        debug: bool = False
        service_name: str = "composed-service"

    class UpstreamSettings(BaseSettings):
        target: str = ""
        timeout_seconds: float = 5.0

    class AppSettings(msgspec.Struct, kw_only=True):
        debug: bool = False
        service_name: str = "app"
        upstream: UpstreamSettings = msgspec.field(
            default_factory=lambda: UpstreamSettings(target="default:5000")
        )

    settings = load_composed_settings(
        AppSettings,
        env={"DEBUG": "true", "UPSTREAM_TIMEOUT_SECONDS": "2.5"},
        defaults_cls=Defaults,
        prefixes={"upstream": "UPSTREAM_"},
    )

    assert settings.debug is True
    assert settings.service_name == "composed-service"
    assert settings.upstream.target == "default:5000"
    assert settings.upstream.timeout_seconds == pytest.approx(2.5)


def test_load_from_toml_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        'host = "toml.example"\nport = 7000\ntags = ["alpha", "beta"]\n'
    )

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.host == "toml.example"
    assert settings.port == 7000
    assert settings.tags == ["alpha", "beta"]


def test_toml_config_file_native_types(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("debug = true\ntimeout = 1.25\n")

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.debug is True
    assert settings.timeout == pytest.approx(1.25)


def test_load_from_toml_config_table(tmp_path: Path) -> None:
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text(
        '[project]\nname = "demo"\n\n'
        '[tool.example]\nhost = "tool.example"\nport = 9100\n'
    )

    settings = ExampleSettings.load(
        config_file=config_file,
        config_table="tool.example",
    )

    assert settings.host == "tool.example"
    assert settings.port == 9100


def test_missing_toml_config_table_is_ignored(tmp_path: Path) -> None:
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text('[project]\nname = "demo"\n')

    settings = ExampleSettings.load(
        config_file=config_file,
        config_table="tool.absent",
    )

    assert settings.host == "localhost"


def test_toml_config_table_must_be_mapping(tmp_path: Path) -> None:
    config_file = tmp_path / "pyproject.toml"
    config_file.write_text('[tool]\nexample = "scalar"\n')

    with pytest.raises(msgspec.ValidationError, match="must be a mapping"):
        ExampleSettings.load(config_file=config_file, config_table="tool.example")


def test_env_precedence_over_toml_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("port = 7000\n")
    monkeypatch.setenv("PORT", "9999")

    settings = ExampleSettings.load(config_file=config_file)

    assert settings.port == 9999


def test_load_composed_settings_from_toml_config_table(tmp_path: Path) -> None:
    class UpstreamSettings(BaseSettings):
        target: str = ""
        timeout_seconds: float = 5.0

    class AppSettings(msgspec.Struct, kw_only=True):
        service_name: str = "app"
        upstream: UpstreamSettings = msgspec.field(default_factory=UpstreamSettings)

    class Defaults(BaseSettings):
        service_name: str = "composed-service"

    config_file = tmp_path / "pyproject.toml"
    config_file.write_text(
        '[tool.app]\nservice_name = "from-toml"\n\n'
        '[tool.app.upstream]\ntarget = "toml:5000"\ntimeout_seconds = 3.5\n'
    )

    settings = load_composed_settings(
        AppSettings,
        config_file=config_file,
        config_table="tool.app",
        defaults_cls=Defaults,
        prefixes={"upstream": "UPSTREAM_"},
    )

    assert settings.service_name == "from-toml"
    assert settings.upstream.target == "toml:5000"
    assert settings.upstream.timeout_seconds == pytest.approx(3.5)
