"""Tests for env-settings."""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Annotated, Literal

import msgspec
import pytest

from msgspec_conf import BaseSettings, load_composed_settings, load_settings


class ExampleSettings(BaseSettings):
    debug: bool = False
    host: str = "localhost"
    port: int = 8000
    timeout: float = 5.5
    tags: list[str] = msgspec.field(default_factory=list)



class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


class Mode(enum.Enum):
    FAST = "fast"
    SAFE = "safe"


class Endpoint(msgspec.Struct):
    host: str = "localhost"
    port: int = 80


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


def test_explicit_empty_env_does_not_read_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST", "from-os-environ")

    settings = ExampleSettings.load(env={})
    assert settings.host == "localhost"


def test_coerces_annotated_values() -> None:
    class PortSettings(BaseSettings):
        port: Annotated[int, msgspec.Meta(ge=1)] = 80

    assert PortSettings.load(env={"PORT": "8080"}).port == 8080
    with pytest.raises(msgspec.ValidationError):
        PortSettings.load(env={"PORT": "0"})


def test_coerces_literal_and_enum_values() -> None:
    class ChoiceSettings(BaseSettings):
        verbosity: Literal[0, 1, 2] = 0
        level: Level = Level.LOW
        mode: Mode = Mode.SAFE

    settings = ChoiceSettings.load(
        env={"VERBOSITY": "2", "LEVEL": "2", "MODE": "fast"}
    )
    assert settings.verbosity == 2
    assert settings.level is Level.HIGH
    assert settings.mode is Mode.FAST


def test_loads_nested_struct_from_json() -> None:
    class EndpointSettings(BaseSettings):
        endpoint: Endpoint = msgspec.field(default_factory=Endpoint)

    settings = EndpointSettings.load(
        env={"ENDPOINT": '{"host": "api.example.com", "port": 443}'}
    )
    assert settings.endpoint == Endpoint(host="api.example.com", port=443)


def test_load_settings_helper_accepts_config() -> None:
    settings = load_settings(ExampleSettings, env={}, config={"host": "from-config"})
    assert settings.host == "from-config"


def test_composed_config_file_without_defaults_cls(tmp_path: Path) -> None:
    class DatabaseSettings(BaseSettings):
        host: str = "localhost"

    class AppSettings(msgspec.Struct, kw_only=True):
        debug: bool = False
        service_name: str = "app"
        database: DatabaseSettings = msgspec.field(default_factory=DatabaseSettings)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "debug: true\nservice_name: from-yaml\ndatabase:\n  host: db.internal\n"
    )

    settings = load_composed_settings(
        AppSettings,
        env={},
        config_file=config_file,
        prefixes={"database": "POSTGRES_"},
    )
    assert settings.debug is True
    assert settings.service_name == "from-yaml"
    assert settings.database.host == "db.internal"


def test_composed_config_file_invalid_shared_value(tmp_path: Path) -> None:
    class AppSettings(msgspec.Struct, kw_only=True):
        workers: int = 1

    config_file = tmp_path / "config.yaml"
    config_file.write_text("workers: many\n")

    with pytest.raises(msgspec.ValidationError, match="AppSettings.workers"):
        load_composed_settings(AppSettings, env={}, config_file=config_file)


def test_files_are_read_as_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a non-UTF-8 locale (e.g. Windows cp1251) for implicit encodings.
    monkeypatch.setattr(
        "io.text_encoding",
        lambda encoding, stacklevel=2: encoding or "cp1251",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=хост.example\n", encoding="utf-8")
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('tags = ["привіт"]\n', encoding="utf-8")

    settings = ExampleSettings.load(env={}, env_file=env_file, config_file=toml_file)
    assert settings.host == "хост.example"
    assert settings.tags == ["привіт"]


def test_env_file_export_and_inline_comments(tmp_path: Path) -> None:
    class DotenvSettings(BaseSettings):
        token: str = ""
        host: str = ""
        color: str = ""
        quoted: str = ""
        single: str = ""
        url: str = ""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "export TOKEN=abc\n"
        "HOST=example.com  # production host\n"
        "COLOR=#ff0000\n"
        'QUOTED="a # not a comment" # comment\n'
        "SINGLE='it''s' \n"
        "URL=https://example.com/page#anchor\n"
    )

    settings = DotenvSettings.load(env={}, env_file=env_file)
    assert settings.token == "abc"
    assert settings.host == "example.com"
    assert settings.color == "#ff0000"
    assert settings.quoted == "a # not a comment"
    assert settings.single == "it''s"
    assert settings.url == "https://example.com/page#anchor"
