# SignalScope

SignalScope is a media intelligence and research platform. The plan is to collect
content from sources such as articles, websites, RSS feeds, documents, audio and
video, and turn it into structured information that can be searched and analyzed.

## Status

Early development. Only the project foundation exists so far. There are no
user-facing features yet.

## Development

SignalScope needs Python 3.12 or newer.

Set up a virtual environment and install the package with the dev tools:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Settings come from `SIGNALSCOPE_*` environment variables. See
[docs/configuration.md](docs/configuration.md).

Run the API locally:

```bash
uvicorn signalscope.api.app:create_app --factory --reload
```

Run the checks:

```bash
pytest
ruff check .
ruff format --check .
mypy src
```
