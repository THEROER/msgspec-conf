"""Core settings loading utilities."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import tomllib
import types
import typing
from typing import Any, Mapping, TypeVar, cast
from typing import get_args, get_origin, get_type_hints

import msgspec
import msgspec.yaml

_T = TypeVar("_T", bound="BaseSettings")
_S = TypeVar("_S")

_SENTINEL = object()
_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "f", "no", "n", "off"}
_DEFAULT_DELIMITERS = {",", ";", "\n"}
_RECORD_DELIMITERS = {";", "\n"}

UNION_TYPES: set[Any] = {typing.Union}
if hasattr(types, "UnionType"):
    UNION_TYPES.add(types.UnionType)


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    values = ", ".join(sorted(_TRUE_VALUES | _FALSE_VALUES))
    msg = f"expected one of: {values}"
    raise ValueError(msg)


def _looks_like_json(raw: str) -> bool:
    stripped = raw.strip()
    return bool(stripped) and stripped[0] in "[{"


def _strip_wrapping_quotes(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _strip_wrapping_brackets(raw: str, left: str, right: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == left and value[-1] == right:
        return value[1:-1].strip()
    return value


def _decode_json(raw: str, expected_type: Any) -> Any:  # noqa: ANN401
    decoded = msgspec.json.decode(raw)
    return _coerce_value(expected_type, decoded)


def _try_decode_json(raw: str, expected_type: Any) -> Any:  # noqa: ANN401
    if not _looks_like_json(raw):
        return _SENTINEL
    try:
        return _decode_json(raw, expected_type)
    except msgspec.DecodeError:
        return _SENTINEL


def _split_delimited(raw: str, delimiters: set[str]) -> list[str]:
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0

    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char in "[{(":
            depth += 1
            continue
        if char in "]})" and depth > 0:
            depth -= 1
            continue
        if depth == 0 and char in delimiters:
            item = raw[start:index].strip()
            if item:
                items.append(item)
            start = index + 1

    item = raw[start:].strip()
    if item:
        items.append(item)
    return items


def _find_pair_separator(raw: str) -> int:
    quote: str | None = None
    escaped = False
    depth = 0

    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char in "[{(":
            depth += 1
            continue
        if char in "]})" and depth > 0:
            depth -= 1
            continue
        if depth == 0 and char in {"=", ":"}:
            return index
    return -1


def _parse_pair(raw: str) -> tuple[str, str]:
    index = _find_pair_separator(raw)
    if index <= 0:
        msg = f"expected key=value or key:value pair, got {raw!r}"
        raise ValueError(msg)
    key = _strip_wrapping_quotes(raw[:index])
    value = _strip_wrapping_quotes(raw[index + 1 :])
    if not key:
        msg = f"expected non-empty key in {raw!r}"
        raise ValueError(msg)
    return key, value


def _is_mapping_type(expected_type: Any) -> bool:  # noqa: ANN401
    return expected_type is dict or get_origin(expected_type) is dict


def _parse_mapping_entries(
    expected_type: Any,
    raw: str,
    *,
    delimiters: set[str],
) -> dict[Any, Any]:
    args = get_args(expected_type)
    key_type, value_type = args if len(args) == 2 else (str, Any)
    value = _strip_wrapping_brackets(raw, "{", "}")
    if not value:
        return {}

    result: dict[Any, Any] = {}
    for entry in _split_delimited(value, delimiters):
        key, item = _parse_pair(entry)
        result[_coerce_value(key_type, key)] = _coerce_value(value_type, item)
    return result


def _parse_mapping_records(expected_type: Any, raw: str) -> list[Any]:
    args = get_args(expected_type)
    item_type = args[0] if args else dict
    value = _strip_wrapping_brackets(raw, "[", "]")
    if not value:
        return []
    return [
        _parse_mapping_entries(item_type, record, delimiters={","})
        for record in _split_delimited(value, _RECORD_DELIMITERS)
    ]


def _coerce_mapping(expected_type: Any, raw: Any) -> Any:  # noqa: ANN401
    if isinstance(raw, str):
        decoded = _try_decode_json(raw, expected_type)
        if decoded is not _SENTINEL:
            return decoded
        return _parse_mapping_entries(
            expected_type,
            raw,
            delimiters=_DEFAULT_DELIMITERS,
        )
    if not isinstance(raw, Mapping):
        return raw

    args = get_args(expected_type)
    if len(args) != 2:
        return raw
    key_type, value_type = args
    return {
        _coerce_value(key_type, key): _coerce_value(value_type, value)
        for key, value in raw.items()
    }


def _coerce_sequence(expected_type: Any, raw: Any) -> Any:  # noqa: ANN401
    origin = get_origin(expected_type)
    args = get_args(expected_type)
    item_type = args[0] if args else Any

    if isinstance(raw, str):
        decoded = _try_decode_json(raw, expected_type)
        if decoded is not _SENTINEL:
            return decoded
        if _is_mapping_type(item_type):
            coerced = _parse_mapping_records(expected_type, raw)
        else:
            value = _strip_wrapping_brackets(raw, "[", "]")
            items = _split_delimited(value, _DEFAULT_DELIMITERS)
            coerced = [_coerce_value(item_type, item) for item in items]
    elif isinstance(raw, list | tuple | set):
        coerced = [_coerce_value(item_type, item) for item in raw]
    else:
        return raw

    if origin is tuple:
        return tuple(coerced)
    if origin is set:
        return set(coerced)
    return coerced


def _coerce_union(expected_type: Any, raw: Any) -> Any:  # noqa: ANN401
    args = get_args(expected_type)
    if type(None) in args:
        if isinstance(raw, str) and raw == "":
            return None
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _coerce_value(non_none[0], raw)

    last_error: Exception | None = None
    for arg in args:
        try:
            return _coerce_value(arg, raw)
        except (TypeError, ValueError, msgspec.ValidationError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return raw


def _coerce_value(expected_type: Any, raw: Any) -> Any:  # noqa: ANN401
    origin = get_origin(expected_type)
    if origin is None:
        if not isinstance(raw, str):
            return raw
        if expected_type is str:
            return raw
        if expected_type is int:
            return int(raw)
        if expected_type is float:
            return float(raw)
        if expected_type is bool:
            return _parse_bool(raw)
        return raw

    if origin in {list, tuple, set}:
        return _coerce_sequence(expected_type, raw)

    if origin is dict:
        return _coerce_mapping(expected_type, raw)

    if origin in UNION_TYPES:
        return _coerce_union(expected_type, raw)

    return raw


def _is_yaml_path(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in {".yaml", ".yml"}


def _is_toml_path(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() == ".toml"


def _decode_config_file(path: Path) -> Any:  # noqa: ANN401
    if _is_toml_path(path):
        return tomllib.loads(path.read_text())
    return msgspec.yaml.decode(path.read_bytes())


def _select_config_table(
    decoded: Mapping[str, Any],
    table: str,
    *,
    path: Path,
) -> dict[str, Any]:
    node: Any = decoded
    for part in table.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return {}
        node = node[part]
    if not isinstance(node, Mapping):
        msg = f"config table {table!r} in {path} must be a mapping"
        raise msgspec.ValidationError(msg)
    return dict(node)


def _parse_config_file(path: Path, *, table: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {}
    decoded = _decode_config_file(path)
    if decoded is None:
        return {}
    if not isinstance(decoded, Mapping):
        msg = f"config file {path} must contain a mapping at the top level"
        raise msgspec.ValidationError(msg)
    if table:
        return _select_config_table(decoded, table, path=path)
    return dict(decoded)


def _resolve_config_field(
    key: str,
    *,
    fields: Mapping[str, str],
    case_sensitive: bool,
) -> str | None:
    if case_sensitive:
        return fields.get(key)
    return fields.get(key.upper()) or fields.get(key)


def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        data[key] = value
    return data


def _field_lookup(
    cls: type[Any],
    *,
    case_sensitive: bool,
) -> dict[str, str]:
    return {
        name if case_sensitive else name.upper(): name
        for name in cls.__struct_fields__
    }


def _struct_fields(cls: type[Any]) -> tuple[str, ...]:
    return tuple(getattr(cls, "__struct_fields__", ()))


def _resolve_field(
    key: str,
    *,
    fields: Mapping[str, str],
    prefix: str | None,
    case_sensitive: bool,
    allow_prefix: bool,
) -> str | None:
    key_cmp = key if case_sensitive else key.upper()
    prefix_cmp = prefix if case_sensitive else (prefix.upper() if prefix else None)
    if allow_prefix and prefix_cmp:
        if not key_cmp.startswith(prefix_cmp):
            return None
        key_cmp = key_cmp[len(prefix_cmp) :]
    return fields.get(key_cmp) or (fields.get(key) if not allow_prefix else None)


def _resolve_file_field(
    key: str,
    *,
    fields: Mapping[str, str],
    prefix: str | None,
    case_sensitive: bool,
) -> str | None:
    key_cmp = key if case_sensitive else key.upper()
    prefix_cmp = prefix if case_sensitive else (prefix.upper() if prefix else None)
    if prefix_cmp:
        if not key_cmp.startswith(prefix_cmp):
            return None
        key_cmp = key_cmp[len(prefix_cmp) :]
    if not key_cmp.endswith("_FILE"):
        return None
    return fields.get(key_cmp[: -len("_FILE")])


def _has_value(value: Any) -> bool:  # noqa: ANN401
    return value is not None and value != ""


def _read_file_value(path: str | os.PathLike[str], *, field: str) -> str:
    file_path = Path(path)
    try:
        return file_path.read_text().rstrip("\r\n")
    except OSError as exc:
        msg = f"unable to read file value for {field}: {file_path}"
        raise msgspec.ValidationError(msg) from exc


def _apply_file_values(
    result: dict[str, Any],
    file_refs: Mapping[str, Any],
    fields: Mapping[str, str],
) -> None:
    field_names = set(fields.values())
    for field in field_names:
        if field.endswith("_file") or _has_value(result.get(field)):
            continue

        file_value = file_refs.get(field)
        file_field = f"{field}_file"
        if file_value is None and file_field in result:
            file_value = result[file_field]
        if not _has_value(file_value):
            continue
        if not isinstance(file_value, str | os.PathLike):
            msg = f"file reference for {field} must be a path"
            raise msgspec.ValidationError(msg)

        result[field] = _read_file_value(file_value, field=field)


def _coerce_collected(
    cls: type[Any],
    raw: dict[str, Any],
    *,
    prefix: str | None,
    case_sensitive: bool,
) -> dict[str, Any]:
    if not raw:
        return raw

    type_hints = get_type_hints(cls, include_extras=True)
    for name, hinted_type in type_hints.items():
        if name not in raw:
            continue
        try:
            raw[name] = _coerce_value(hinted_type, raw[name])
        except (TypeError, ValueError, msgspec.ValidationError) as exc:
            env_name = name if case_sensitive else name.upper()
            if prefix:
                env_name = f"{prefix}{env_name}"
            msg = f"invalid value for {env_name} ({cls.__name__}.{name}): {exc}"
            raise msgspec.ValidationError(msg) from exc
    return raw


def _struct_defaults(instance: Any) -> dict[str, Any]:  # noqa: ANN401
    if instance is None:
        return {}
    return msgspec.to_builtins(instance)


def _is_settings_type(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, type) and issubclass(value, BaseSettings)


def _default_instance(cls: type[_S]) -> _S | None:
    try:
        return cls()
    except (TypeError, msgspec.ValidationError):
        return None


class BaseSettings(msgspec.Struct, kw_only=True, omit_defaults=True):
    """Base class for settings definitions."""

    @classmethod
    def _collect_env(
        cls,
        *,
        env: Mapping[str, str] | None,
        env_file: str | os.PathLike[str] | None,
        prefix: str | None,
        case_sensitive: bool,
        defaults: Mapping[str, Any] | None,
        config: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        file_refs: dict[str, Any] = {}

        fields = _field_lookup(cls, case_sensitive=case_sensitive)

        if defaults:
            for key, value in defaults.items():
                field = _resolve_field(
                    key,
                    fields=fields,
                    prefix=prefix,
                    case_sensitive=case_sensitive,
                    allow_prefix=False,
                )
                if field:
                    result[field] = value

        if config:
            for key, value in config.items():
                field = _resolve_config_field(
                    key,
                    fields=fields,
                    case_sensitive=case_sensitive,
                )
                if field:
                    result[field] = value

        if env_file:
            env_path = Path(env_file)
            file_values = _parse_env_file(env_path)
            for key, value in file_values.items():
                field = _resolve_field(
                    key,
                    fields=fields,
                    prefix=prefix,
                    case_sensitive=case_sensitive,
                    allow_prefix=True,
                )
                if field:
                    result[field] = value
                    continue
                file_field = _resolve_file_field(
                    key,
                    fields=fields,
                    prefix=prefix,
                    case_sensitive=case_sensitive,
                )
                if file_field:
                    file_refs[file_field] = value

        source = env or os.environ
        for key, value in source.items():
            field = _resolve_field(
                key,
                fields=fields,
                prefix=prefix,
                case_sensitive=case_sensitive,
                allow_prefix=True,
            )
            if field:
                result[field] = value
                continue
            file_field = _resolve_file_field(
                key,
                fields=fields,
                prefix=prefix,
                case_sensitive=case_sensitive,
            )
            if file_field:
                file_refs[file_field] = value

        _apply_file_values(result, file_refs, fields)

        return result

    @classmethod
    def load(
        cls: type[_T],
        *,
        env: Mapping[str, str] | None = None,
        env_file: str | os.PathLike[str] | None = None,
        config_file: str | os.PathLike[str] | None = None,
        config_table: str | None = None,
        prefix: str | None = None,
        case_sensitive: bool = False,
        defaults: Mapping[str, Any] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> _T:
        """Create settings instance from environment data.

        Values are resolved with the precedence ``env`` > ``env_file`` (.env)
        > ``config_file`` (YAML or TOML) > ``defaults``. ``config_file`` is
        parsed as TOML when it has a ``.toml`` suffix and as YAML otherwise.
        ``config_table`` selects a nested table from the file by dotted path
        (e.g. ``"tool.myservice"`` to read settings from ``pyproject.toml``).
        ``config`` accepts an already-parsed mapping (e.g. a section of a
        larger document) and is merged at the same level as ``config_file``.
        """

        if config_file is not None:
            file_config = _parse_config_file(Path(config_file), table=config_table)
            config = {**file_config, **config} if config else file_config

        raw = cls._collect_env(
            env=env,
            env_file=env_file,
            prefix=prefix,
            case_sensitive=case_sensitive,
            defaults=defaults,
            config=config,
        )
        raw = _coerce_collected(
            cls,
            raw,
            prefix=prefix,
            case_sensitive=case_sensitive,
        )
        try:
            return msgspec.convert(raw, cls)
        except msgspec.ValidationError as exc:
            msg = f"invalid settings for {cls.__name__}: {exc}"
            raise msgspec.ValidationError(msg) from exc


class ServiceDefaultsBase(BaseSettings):
    """Common top-level service defaults used across microservices."""

    debug: bool = False
    sqlalchemy_echo: bool = False
    service_name: str = "service"
    public_base_url: str = "https://leavelocal.com"
    cors_allow_origins: list[str] = msgspec.field(default_factory=list)
    cors_allow_origins_debug: list[str] = msgspec.field(default_factory=list)
    snowflake_worker_id: int = 0
    snowflake_datacenter_id: int = 0


def load_settings(
    cls: type[_T],
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | os.PathLike[str] | None = None,
    config_file: str | os.PathLike[str] | None = None,
    config_table: str | None = None,
    prefix: str | None = None,
    case_sensitive: bool = False,
    defaults: Mapping[str, Any] | None = None,
) -> _T:
    """Convenience helper to instantiate settings."""

    if not issubclass(cls, BaseSettings):
        msg = "cls must derive from BaseSettings"
        raise TypeError(msg)
    return cls.load(
        env=env,
        env_file=env_file,
        config_file=config_file,
        config_table=config_table,
        prefix=prefix,
        case_sensitive=case_sensitive,
        defaults=defaults,
    )


def load_composed_settings(
    cls: type[_S],
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | os.PathLike[str] | None = None,
    config_file: str | os.PathLike[str] | None = None,
    config_table: str | None = None,
    prefixes: Mapping[str, str] | None = None,
    defaults_cls: type[BaseSettings] | None = None,
    case_sensitive: bool = False,
    post_load: Callable[[_S], _S] | None = None,
) -> _S:
    """Load a top-level ``msgspec.Struct`` composed from settings blocks.

    When ``config_file`` is given, top-level keys map to shared fields while
    each nested mapping (keyed by block field name) configures the matching
    settings block. The file is parsed as TOML for a ``.toml`` suffix and as
    YAML otherwise; ``config_table`` selects a nested table by dotted path
    (e.g. ``"tool.myservice"`` for ``pyproject.toml``).
    """

    config: dict[str, Any] = {}
    if config_file is not None:
        config = _parse_config_file(Path(config_file), table=config_table)

    values: dict[str, Any] = {}
    base_values: dict[str, Any] = {}
    base = _default_instance(cls)
    struct_fields = _struct_fields(cls)
    if base is not None:
        base_values = {field: getattr(base, field) for field in struct_fields}

    if defaults_cls is not None:
        defaults = defaults_cls.load(
            env=env,
            env_file=env_file,
            case_sensitive=case_sensitive,
            config=config or None,
        )
        for field in defaults_cls.__struct_fields__:
            if field in struct_fields:
                values[field] = getattr(defaults, field)

    try:
        type_hints = get_type_hints(cls, include_extras=True)
    except NameError:
        type_hints = dict(getattr(cls, "__annotations__", {}))

    for field, prefix in (prefixes or {}).items():
        settings_type = type_hints.get(field)
        if not _is_settings_type(settings_type):
            base_value = base_values.get(field)
            if isinstance(base_value, BaseSettings):
                settings_type = type(base_value)
        if not _is_settings_type(settings_type):
            msg = f"{cls.__name__}.{field} must be a BaseSettings field"
            raise TypeError(msg)
        settings_cls = cast(type[BaseSettings], settings_type)
        default_values = _struct_defaults(base_values.get(field))
        section = config.get(field)
        block_config = section if isinstance(section, Mapping) else None
        values[field] = settings_cls.load(
            env=env,
            env_file=env_file,
            prefix=prefix,
            case_sensitive=case_sensitive,
            defaults=default_values,
            config=block_config,
        )

    try:
        settings = cls(**values)
    except (TypeError, msgspec.ValidationError) as exc:
        msg = f"invalid composed settings for {cls.__name__}: {exc}"
        raise msgspec.ValidationError(msg) from exc

    if post_load is not None:
        return post_load(settings)
    return settings
