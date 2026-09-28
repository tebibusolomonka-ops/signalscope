# SignalScope

SignalScope is a media intelligence and research platform. The plan is to collect
content from sources such as articles, websites, RSS feeds, documents, audio and
video, and turn it into structured information that can be searched and analyzed.

## Status

Early development. SignalScope can collect RSS feeds and web pages, import
plain text, JSON, HTML, PDF and DOCX files, and search the collected text
through an HTTP API, by words or, with local embeddings, by meaning. There is
no user interface and no authentication yet.

## Development

SignalScope needs Python 3.12 or newer.

Set up a virtual environment and install the package with the dev tools:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The `obsidian/` folder is project knowledge for maintainers and coding agents:
Markdown notes on the architecture, current state, decisions and known issues.
The code and migrations stay the source of truth.

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

Run the checks. This runs pytest, Ruff, the format check and mypy in order,
stops at the first failure and checks that there is one Alembic head:

```bash
python scripts/check.py
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
job, and 1 when the job failed. `schedule-ingestion` does one pass and exits,
so run it from cron or a systemd timer.

Without `--once`, the worker keeps running and takes jobs as they arrive. It
waits `--poll-seconds` (5 by default) when the queue is empty, and
`--max-jobs` makes it exit after that many jobs. A failed job does not stop
it. Press Ctrl+C, or send SIGTERM, to stop it. The worker then finishes the
job it is working on, takes no new one and exits:

```bash
signalscope run-worker --poll-seconds 10
```

Several workers can run at the same time without taking the same job. A
claimed job has a five minute lease. When a worker crashes, the next worker
puts its job back in the queue once the lease has run out.

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
when the job completed or there was no job, and 1 when processing failed.
Without `--once` it keeps working through the queue, with the same
`--poll-seconds` and `--max-jobs` options as `run-worker`:

```bash
signalscope run-processing-worker
```

`DELETE /documents/<id>` also deletes the stored file of an imported document.
If the file cannot be deleted at that moment, it is recorded and can be
removed later:

```bash
signalscope cleanup-blobs --limit 100
```

It prints how many files it checked, deleted and could not delete. Files that
could not be deleted are tried again later, with a longer wait each time.

### Search

Processed text is split into chunks that PostgreSQL full text search can find:

```bash
curl "http://localhost:8000/search?q=climate+policy&limit=10"
```

Each result has the document, chunk and source IDs, the title, the URL, a
short plain text excerpt, a rank and the chunk metadata, which says for
example which PDF page the match came from. All words must match. `"quoted phrases"`,
`or` and `-word` work as on web search engines. `source_id` limits results to
one source.

### Semantic and hybrid search

Semantic search compares meaning instead of words. It uses embeddings: vectors
that an embedding model makes from each chunk. The database stores them with
the pgvector extension, so `compose.yaml` and CI run the
`pgvector/pgvector:pg17` image.

The model for now is `intfloat/multilingual-e5-small`. It handles many
languages and makes vectors with 384 dimensions. E5 models expect `query: `
before a search query and `passage: ` before stored text. SignalScope adds
these itself when it calls the model. They are never stored in document or
chunk text.

Each embedding records its provider, model and number of dimensions, and a
search only compares vectors from the same model. The E5 vectors have an HNSW
index, which keeps their search fast. Vectors from other models are compared
one by one.

#### Turn it on

The model runs on this machine. It is an optional extra, because it brings in
sentence-transformers and PyTorch. Install it and turn it on:

```bash
pip install -e ".[local-embeddings]"
export SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true
```

The model is downloaded the first time it is used, not when SignalScope
starts. Check that it loads and works:

```bash
signalscope check-embedding-model
```

It embeds one query and one passage and prints the model, the number of
dimensions and how similar the two are. See
[docs/configuration.md](docs/configuration.md) for the device, batch size and
cache settings.

#### Embed chunks

The processing worker queues an embedding job for every new chunk. Chunks
that were made before embeddings were turned on have no job yet. Queue them
with:

```bash
signalscope queue-embeddings --limit 1000
```

It checks the chunks in a fixed order, skips those that already have a current
embedding or a waiting job, and prints how many it checked and queued.
`--document-id` limits it to one document. Then run the embedding worker:

```bash
signalscope run-embedding-worker --once
```

It embeds a batch of chunks in one model call and prints the model and how
many jobs completed, failed or were taken over by another worker. Without
`--once` it keeps running, with the same `--poll-seconds` and `--max-jobs`
options as the other workers, where each batch counts as one job.
`--batch-size` sets the most chunks per call.

See how far embedding has got:

```bash
curl "http://localhost:8000/embeddings/coverage"
curl "http://localhost:8000/embeddings/coverage?document_id=<document-id>"
```

It returns the number of chunks, how many have a current E5 embedding, how
many are waiting or failed, and the share that is done. It reads the database
only, so it works without the model installed.

#### Search

```bash
curl "http://localhost:8000/search/semantic?q=flood+risk&provider=sentence_transformers&model=intfloat/multilingual-e5-small"
curl "http://localhost:8000/search/hybrid?q=flood+risk&provider=sentence_transformers&model=intfloat/multilingual-e5-small"
```

`/search/semantic` embeds the query and returns the closest chunks with a
`similarity` between -1 and 1. `/search/hybrid` runs full text search and
vector search and merges both lists with Reciprocal Rank Fusion. Each result
shows its `lexical_rank`, its `vector_similarity` and the fused
`hybrid_score`. Chunks without embeddings can still be found by the full text
part. Both take `limit` and `source_id` like `/search`. They answer 503 when
local embeddings are off.

### Reranking

A reranker reads the query and each candidate chunk together and reorders the
candidates. SignalScope uses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, a
multilingual model that runs on this machine. It needs its own extra and
switch, next to local embeddings:

```bash
pip install -e ".[local-reranking]"
export SIGNALSCOPE_LOCAL_RERANKING_ENABLED=true
```

```bash
curl "http://localhost:8000/search/reranked?q=flood+risk&limit=10"
```

`/search/reranked` runs hybrid search for three candidates per result and
lets the reranker order them by the full chunk text. Each result shows its
`hybrid_score` and its `reranker_score`. It answers 503 when local reranking or
local embeddings are off. The model is loaded, and downloaded the first time,
only when it first scores something.

### Research context

`POST /research/context` collects the evidence for a question, so that a
future answer step can cite it. It does not write answers or summaries, and it
does not call a language model.

```bash
curl -X POST http://localhost:8000/research/context \
  -H "Content-Type: application/json" \
  -d '{"query": "flooding in the harbour", "mode": "hybrid", "limit": 8}'
```

`mode` is `lexical`, `semantic`, `hybrid` (the default) or `reranked`, and
`source_id` limits the search to one source. The response lists the evidence
with IDs E1, E2 and so on, each with its document, chunk, title, URL, excerpt,
chunk metadata such as the PDF page, and the search scores. At most two chunks
come from one document, and overlapping or repeated chunks are left out.
`context_text` holds the same evidence as numbered blocks with the full chunk
text:

```text
[E1]
Title: Harbour Report
Page: 2
Text: Water flooded the harbour district.
```

The IDs only hold within one response. Reranked mode needs local reranking,
and the other modes, except lexical, need local embeddings.

### Research answers

`POST /research/answer` takes the same body as `/research/context` and is the
start of answers with citations. It collects the evidence, gives it to an
answer model as structured items and as numbered text blocks, and checks the
answer before returning it:

- every ID in `citation_ids` must belong to the evidence the model was given,
- the text must mark exactly those IDs, like `[E1]`,
- no ID may appear twice.

An answer that fails these checks is never returned; the request fails with
503 instead. The response maps each cited ID to its document, chunk, title,
URL and chunk metadata, such as the PDF page, so a reader never has to guess
which source an ID means. When no evidence is found, the model is not asked
and `answer` is `null`.

The answer model is `Qwen/Qwen3-4B-Instruct-2507`, run on this machine with
Transformers. It is optional and off by default, so the endpoint answers 503
until it is turned on:

```bash
pip install -e ".[local-answers]"
export SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true
signalscope check-answer-model
```

`check-answer-model` loads the model, downloading it the first time (several
gigabytes), answers one small question from one piece of evidence, runs the
same citation checks, and prints the provider, the model and the cited IDs.
`SIGNALSCOPE_LOCAL_ANSWER_DEVICE` picks where it runs, and
`SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS` (default 512) caps the answer
length.

Then ask a question:

```bash
curl -X POST localhost:8000/research/answer   -H "Content-Type: application/json"   -d '{"query": "What flooded the harbour?", "mode": "hybrid", "limit": 5}'
```

Answers stay tied to the evidence. The model is only shown the question and,
for each piece of evidence, its ID, title and text. It is told to answer only
from that evidence and to return JSON with the text and the IDs it cites.
Generation is greedy, so the same evidence gives the same answer. Output that
is not exactly that JSON is rejected, and every answer goes through the
citation checks above before it is returned.

### Entities

SignalScope can find people, organizations, places, countries, cities,
products, events and dates in chunks with `urchade/gliner_multi-v2.1`, a
multilingual model that runs on this machine. It needs its own extra and
switch:

```bash
pip install -e ".[local-entities]"
export SIGNALSCOPE_LOCAL_ENTITIES_ENABLED=true
```

Queue the existing chunks, then run the worker:

```bash
signalscope queue-entities --limit 1000
signalscope run-entity-worker --once
```

`queue-entities` checks chunks in a fixed order, skips those already read or
waiting, and takes `--document-id` and `--limit`. `run-entity-worker` reads
one chunk per job and prints the job, its status and how many mentions it
found. Without `--once` it keeps running, with `--poll-seconds` and
`--max-jobs`, and stops cleanly on Ctrl+C. The model is loaded, and
downloaded the first time, only when a job needs it.

`GET /entities` lists the entities found, with `query` for part of a name,
`entity_type`, `limit` and `offset`. `GET /entities/{id}` shows one entity
with its mentions. Types are stored in lower case. Entities are linked by
normalized name and type only, so two people with the same name share one
entity.

### Events

SignalScope can read events, such as floods or elections, out of chunks with
`fastino/gliner2.5-multi-v1`, a multilingual GLiNER2 model that runs on this
machine. It needs its own extra and switch:

```bash
pip install -e ".[local-structured]"
export SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true
```

Queue the existing chunks, then run the worker:

```bash
signalscope queue-events --limit 1000
signalscope run-event-worker --once
```

`queue-events` checks chunks in a fixed order, skips those already read or
waiting, and takes `--document-id` and `--limit`. It does not load the model.
`run-event-worker` reads one chunk per job and prints the job, its status and
how many events it found. Without `--once` it keeps running, with
`--poll-seconds` and `--max-jobs`, and stops cleanly on Ctrl+C. The model is
loaded, and downloaded the first time, only when a job needs it.

A date is only stored when its meaning is certain, such as `2026-03-04` or
`4 March 2026`. Other dates, such as `04/03/2026`, are kept as written in the
evidence metadata, and the event has no time.

`GET /events` lists events, with `event_type`, `occurred_from`,
`occurred_to`, `limit` and `offset`. `GET /events/{id}` shows one event with
its evidence. `GET /events/coverage` counts how many chunks the model has
read, optionally for one `document_id`, without loading the model.

### Timeline

Events from different documents that report the same thing can be linked
into one cluster. This first linker is strict: the event type and the title
must match after spaces and case are evened out, and when both events have a
time, they must fall on the same UTC day. There is no fuzzy matching yet.
The event worker links the events it finds right after it saves them. If
linking fails, the events stay saved but unclustered. Link them, and any events
from before automatic linking, with:

```bash
signalscope link-events --limit 1000
```

It prints how many events it checked and linked and how many clusters it
created. Running it again when everything is linked changes nothing.

`GET /timeline` lists the clusters in time order, newest first, or oldest
first with `order=oldest_first`. Clusters without a time come last. It takes
`occurred_from`, `occurred_to`, `event_type`, `source_id`, `limit` and
`offset`. Each item gives the title, type, time, and how many events,
sources and evidence rows back it, with the source names. The timeline only
describes what was reported; it does not rank events by importance.

### Source provenance

`GET /sources/{id}/provenance` shows what SignalScope has observed about one
source: how many documents it has, when they were stored and published, how
many distinct entities, claims and events were found in them, how many event
clusters those events belong to, how many of those clusters another source
also reports, and how many document revisions were kept.

These are observed provenance signals, not a credibility score. SignalScope
does not rate sources as reliable or unreliable and does not rank them against
each other. A high count only means more was observed.

`POST /sources/compare` with `{"source_ids": [...]}` (2 to 10 different
sources) shows the same profiles side by side, in the order given, plus how
many event clusters, entities and claims two or more of them have in common.
The comparison is descriptive: there is no score, winner or ranking.

### Claims

The same GLiNER2 model and switch read claims: statements a text makes, such
as a statistic or a prediction. Each claim keeps the exact words it came from
and where they are in the chunk. SignalScope does not judge whether a claim is
true.

```bash
signalscope queue-claims --limit 1000
signalscope run-claim-worker --once
```

`queue-claims` and `run-claim-worker` work like `queue-events` and
`run-event-worker`, with the same options. The worker prints how many claims
it found in each chunk.

`GET /claims` lists claims, with `query`, `claim_type`, `limit` and `offset`.
`GET /claims/{id}` shows one claim with its evidence. `GET /claims/coverage`
counts how many chunks the model has read, like `GET /events/coverage`.

### Retrieval evaluation

A retrieval dataset is a JSON file with documents, queries, and the documents
each query should find. [docs/examples/media-smoke.json](docs/examples/media-smoke.json)
shows the format. Score the search methods on it:

```bash
signalscope evaluate-retrieval docs/examples/media-smoke.json
signalscope evaluate-retrieval data.json --mode lexical --k 1,5,10
```

`--mode` is `lexical`, `semantic`, `hybrid`, `reranked` or `all` (the
default). Lexical mode needs no model. The other modes need local embeddings,
and the reranked mode needs local reranking too. In the `all` mode a missing
reranker skips the reranked mode, and the output says why. For each mode it
prints Recall@k, MRR@k and nDCG@k, and the mean, median (p50) and p95 search
time in milliseconds. The reranked mode also prints the reranker time
separately, because the reranker runs after the search.

`--json-output report.json` also writes the results to a JSON file: the
dataset, the k values, the models used, and for each mode the scores, the
scores of each query and the timings. It holds no vectors and no document
text, so reports from different runs can be compared.

`--quality-gates gates.json` checks the scores against minimums that you
choose, per mode:

```json
{"hybrid": {"recall@10": 0.8, "mrr@10": 0.5}, "reranked": {"ndcg@10": 0.6}}
```

The metrics are `recall@k`, `mrr@k` and `ndcg@k`, and each k must be in
`--k`. The command prints each minimum as passed or missed and exits with 1
when one is missed. SignalScope ships no minimums of its own, because the real
models have not been measured on a reference dataset yet.

The command needs `SIGNALSCOPE_DATABASE_URL`. It writes the dataset into the
database in one transaction, searches it with the normal search code, and
rolls the transaction back at the end, so nothing stays behind. Embeddings are
made before that transaction starts.

The scores describe one dataset. A small dataset, such as the example, only
shows that the pieces work. It does not show which method is better.

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
