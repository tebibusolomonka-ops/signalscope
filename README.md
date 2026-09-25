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

Run the API locally. SignalScope logs each request itself, so the Uvicorn
access log is turned off:

```bash
uvicorn signalscope.api.app:create_app --factory --reload --no-access-log
```

Start the local PostgreSQL database and point SignalScope at it. The user,
password and database name in `compose.yaml` are all `signalscope`. They are
for local development only, so do not use them anywhere else.

```bash
docker compose up -d postgres
export SIGNALSCOPE_DATABASE_URL=postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope
```

Stop it with `docker compose down`. Add `-v` to delete the data as well.

Apply database migrations. This needs `SIGNALSCOPE_DATABASE_URL`:

```bash
alembic upgrade head
```

Create a new migration:

```bash
alembic revision -m "Describe the change"
```

Run the checks:

```bash
pytest
ruff check .
ruff format --check .
mypy src
```

Database tests run only when `SIGNALSCOPE_TEST_DATABASE_URL` is set. Otherwise
they are skipped. The tests delete data, so the database name must end with
`_test`. With the local Compose database:

```bash
docker compose exec postgres createdb -U signalscope signalscope_test
export SIGNALSCOPE_TEST_DATABASE_URL=postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope_test
pytest
```

## Command line

Fetch new content for one RSS or web source. This needs
`SIGNALSCOPE_DATABASE_URL` and makes real network requests:

```bash
signalscope ingest-source <source-id>
```

It prints the run ID, the status and how many items were seen, created and
skipped as duplicates. The exit code is 0 only when the run completed. Upload
and API sources cannot be ingested from the command line.

Timeouts, connection errors and HTTP 429, 502, 503 and 504 responses are tried
again. A run makes at most 3 attempts and waits 5, then 10 seconds in between.
Documents saved by an earlier attempt are kept and skipped as duplicates.

## Docker

Build and run the API image:

```bash
docker build -t signalscope .
docker run --rm -p 8000:8000 signalscope
```

Pass settings as environment variables, for example
`-e SIGNALSCOPE_LOG_LEVEL=DEBUG`. The same image can run migrations:

```bash
docker run --rm -e SIGNALSCOPE_DATABASE_URL=... signalscope alembic upgrade head
```
