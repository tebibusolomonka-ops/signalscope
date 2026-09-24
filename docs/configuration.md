# Configuration

Settings are read from environment variables by
`signalscope.core.settings.load_settings()`. A variable that is not set, or is
empty, keeps its default value. An invalid value raises `SettingsError`.

| Variable | Default | Allowed values |
| --- | --- | --- |
| `SIGNALSCOPE_APP_NAME` | `SignalScope` | Any non-empty text |
| `SIGNALSCOPE_ENVIRONMENT` | `development` | `development`, `test`, `production` |
| `SIGNALSCOPE_DEBUG` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `SIGNALSCOPE_DATABASE_URL` | Not set | A URL that starts with `postgresql+asyncpg://` |

Values are not case-sensitive, except for the app name and the database URL.
Leading and trailing spaces are ignored.

`.env` files are not loaded. Set the variables in your shell or process
manager.

## Database

SignalScope uses PostgreSQL with the asyncpg driver.

`SIGNALSCOPE_DATABASE_URL` is optional for now, and the API starts without it.
Database features need it and raise `SettingsError` when it is not set.

Example for a local database:

```text
postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope
```
