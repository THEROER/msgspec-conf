# msgspec-conf

A tiny settings loader inspired by `pydantic_settings`, but implemented with [`msgspec`](https://github.com/jcrist/msgspec). It allows loading structured configuration from environment variables, `.env` files, YAML and TOML config files without depending on Pydantic.

## Features

- Define settings as `msgspec.Struct` classes
- Load values from the current environment, optional `.env` files, YAML or TOML config files, and defaults
- Automatic type coercion for scalar values and common collection formats
- Optional prefixes and case-insensitive matching
- File-backed secret fallback via `*_FILE` variables
- Declarative loading for top-level settings composed from prefixed blocks

## Usage

```python
from typing import Optional
import msgspec

from msgspec_conf import BaseSettings

class AppSettings(BaseSettings):
    debug: bool = False
    database_url: str
    api_key: Optional[str] = None

settings = AppSettings.load(env_file=".env", prefix="APP_")
print(settings.database_url)
```

`.env` values override defaults, while real environment variables take precedence over the file.

## YAML and TOML config files

A config file can supply structured, non-secret configuration — the kind you
commit to git — while `.env` keeps private values out of the repository. The
two sources are independent: each has its own path and either can be used alone
or together. The file is parsed as TOML when it has a `.toml` suffix and as YAML
otherwise.

```python
settings = AppSettings.load(config_file="config.yaml", env_file=".env")
```

```yaml
# config.yaml — safe to commit
debug: false
host: api.example.com
tags:
  - landing
  - monitoring
```

Values resolve with the precedence **real env vars > `.env` file > config file >
defaults**. So if `HOST` appears both in `config.yaml` and the environment, the
environment wins; fields only present in the config file are still applied.

The same applies to TOML. To read settings straight out of `pyproject.toml`,
point `config_file` at it and use `config_table` to select the table (a dotted
path) that holds your settings:

```python
settings = AppSettings.load(
    config_file="pyproject.toml",
    config_table="tool.myservice",
)
```

```toml
# pyproject.toml
[tool.myservice]
debug = false
host = "api.example.com"
tags = ["landing", "monitoring"]
```

`config_table` works with any config file format; without it the whole document
is used. `load_composed_settings` accepts both `config_file` and `config_table`
as well, so each prefixed block can be configured from a nested table.

Because YAML is already structured, native types are used directly — no string
parsing is needed for lists, mappings, or nested records:

```yaml
limits:
  checkout: 20
  login: 60
rules:
  - { id: 1, score: 95 }
  - { id: 2, score: 90 }
```

Top-level YAML keys are matched against field names case-insensitively.

List values can be written as CSV, semicolon/newline-delimited text, or JSON:

```env
APP_ALLOWED_ORIGINS=https://example.com,https://api.example.com
APP_ALLOWED_LOCALES=en;uk;fr
APP_ALLOWED_TOPICS=["landing.live_stats","monitoring.live_status"]
```

Dict values can be written as JSON or delimited key-value pairs:

```env
APP_LIMITS={"checkout":20,"login":60}
APP_LIMITS=checkout=20,login:60;refresh=120
```

`list[dict[...]]` values can be written as JSON or as records separated by
semicolon/newline. Within each record, comma separates key-value pairs:

```env
APP_RULES=[{"id":"policy.example","score":95,"evidence_urls":["https://example.com"]}]
APP_RULES=id=1,score=95;id=2,score=90
```

Prefer JSON when values are deeply nested or may contain delimiters.

Boolean values are parsed strictly. Accepted values are `1/0`, `true/false`,
`yes/no`, `on/off`, and `y/n`.

## File-backed values

If `TOKEN` is empty or unset, `TOKEN_FILE` can point to a file containing the
value:

```python
class SecretSettings(BaseSettings):
    token: str = ""
    token_file: str | None = None

settings = SecretSettings.load()
```

```env
TOKEN_FILE=/run/secrets/api_token
```

The `token_file` field is optional. `TOKEN_FILE` also works when only `token`
is defined.

## Composed settings

Services with a top-level `msgspec.Struct` can load nested settings blocks
declaratively:

```python
from msgspec_conf import BaseSettings, ServiceDefaultsBase, load_composed_settings
import msgspec

class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432

class ServiceDefaults(ServiceDefaultsBase):
    service_name: str = "example-service"

class Settings(msgspec.Struct, kw_only=True):
    debug: bool = False
    service_name: str = "example-service"
    database: DatabaseSettings = msgspec.field(default_factory=DatabaseSettings)

settings = load_composed_settings(
    Settings,
    env_file=".env",
    defaults_cls=ServiceDefaults,
    prefixes={"database": "POSTGRES_"},
)
```

Default factories on nested fields are preserved and then overridden by matching
environment values.

A YAML config file works here too. Top-level keys map to shared fields, while
each nested mapping (keyed by the block's field name) configures that block:

```python
settings = load_composed_settings(
    Settings,
    config_file="config.yaml",
    env_file=".env",
    defaults_cls=ServiceDefaults,
    prefixes={"database": "POSTGRES_"},
)
```

```yaml
debug: false
service_name: example-service
database:
  host: db.internal
  port: 5432
```

Environment variables (e.g. `POSTGRES_HOST`) still override the matching YAML
values.

## Installation

```bash
pip install msgspec-conf
# or
uv add msgspec-conf
```

## Development

```bash
uv sync --dev
uv run pytest
```
