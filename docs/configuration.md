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

Values are not case-sensitive, except for the app name. Leading and trailing
spaces are ignored.

`.env` files are not loaded. Set the variables in your shell or process
manager.
