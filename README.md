# SignalScope

SignalScope is a media intelligence and research platform. The plan is to collect
content from sources such as articles, websites, RSS feeds, documents, audio and
video, and turn it into structured information that can be searched and analyzed.

## Status

Early development. SignalScope can collect RSS feeds and web pages, import
plain text, JSON, HTML, PDF and DOCX files, and search the collected text
through an HTTP API. There is no user interface and no authentication yet.

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

### Scheduled ingestion

Turn on scheduled ingestion for a web or RSS source through the API, for
example every 60 minutes starting now:

```bash
curl -X PUT http://localhost:8000/sources/<source-id>/schedule \
  -H "Content-Type: application/json" -d '{"interval_minutes": 60}'
```

`DELETE /sources/<source-id>/schedule` turns it off again. Jobs are queued in
PostgreSQL. Queue a job for every source that is due:

```bash
signalscope schedule-ingestion --limit 100
```

It prints how many sources were due and how many jobs it created, for example
`Jobs created: 4`. Then run one queued job:

```bash
signalscope run-worker --once
```

It prints `No ingestion job available.` when there is nothing to do, or the job
ID and its status. The exit code is 0 when the job completed or there was no
job, and 1 when the job failed. Both commands do one pass and exit, so run them
from cron or a systemd timer. Several workers can run at the same time without
taking the same job.

### Importing files

Plain text, JSON, HTML, PDF and DOCX files can be imported into an upload
source. This needs `SIGNALSCOPE_DATABASE_URL` and `SIGNALSCOPE_BLOB_DIR`:

```bash
signalscope import-file <source-id> ./report.pdf
```

The content type is guessed from the file name. Pass `--content-type` when the
name does not tell. The command stores the file and queues it for processing,
then prints the document, asset and processing job IDs. It does not parse the
file itself.

Parse one queued file:

```bash
signalscope run-processing-worker --once
```

It saves the text on the document and prints the job ID, its status and the
document ID, or `No document processing job available.` The exit code is 0
when the job completed or there was no job, and 1 when processing failed. Run
it again, or from a timer, to work through the queue.

### Search

Processed text is split into chunks that PostgreSQL full text search can find:

```bash
curl "http://localhost:8000/search?q=climate+policy&limit=10"
```

Each result has the document, chunk and source IDs, the title, the URL, a
short plain text excerpt and a rank. All words must match. `"quoted phrases"`,
`or` and `-word` work as on web search engines. `source_id` limits results to
one source.

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
