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
| `SIGNALSCOPE_BLOB_DIR` | Not set | A folder path |
| `SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOCAL_EMBEDDING_DEVICE` | `cpu` | A device name, such as `cpu` or `cuda` |
| `SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE` | `32` | A whole number of at least 1 |
| `SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` | Not set | A folder path |
| `SIGNALSCOPE_LOCAL_RERANKING_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOCAL_RERANKING_DEVICE` | `cpu` | A device name, such as `cpu` or `cuda` |
| `SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE` | `16` | A whole number of at least 1 |
| `SIGNALSCOPE_LOCAL_ENTITIES_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOCAL_ENTITY_DEVICE` | `cpu` | A device name, such as `cpu` or `cuda` |
| `SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD` | `0.5` | A number above 0 and at most 1 |
| `SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOCAL_STRUCTURED_DEVICE` | `cpu` | A device name, such as `cpu` or `cuda` |
| `SIGNALSCOPE_LOCAL_ANSWERS_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_LOCAL_ANSWER_DEVICE` | `cpu` | A device name, such as `cpu` or `cuda` |
| `SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS` | `512` | A whole number from 1 to 4096 |
| `SIGNALSCOPE_AUTH_ENABLED` | `false` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` |
| `SIGNALSCOPE_AUTH_SESSION_DAYS` | `7` | A whole number from 1 to 365 |
| `SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS` | `30` | A whole number from 1 to 3650 |
| `SIGNALSCOPE_ORGANIZATION_INVITATION_DAYS` | `7` | A whole number from 1 to 90 |

Values are not case-sensitive, except for the app name, the database URL,
the device and the folders.
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

## File storage

Raw files, such as imported PDFs, are stored as files under
`SIGNALSCOPE_BLOB_DIR`. The database only keeps their metadata. The folder is
created when the first file is written.

The setting is optional, and the API starts without it. Commands that store
or read files fail with a clear error when it is not set.

## Local embeddings

Semantic and hybrid search need embeddings. SignalScope can make them on this
machine with `intfloat/multilingual-e5-small`, a multilingual model with 384
dimensions. The model is fixed for now, because the vector index is built for
it.

It is off by default. To turn it on, install the extra, which brings in
sentence-transformers and PyTorch, and set the variable:

```bash
pip install -e ".[local-embeddings]"
export SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true
```

When it is on:

- the API offers the model to `/search/semantic` and `/search/hybrid`,
- the processing worker queues embedding jobs for the chunks of each document
  it processes.

The model is not loaded when SignalScope starts. It is loaded, and downloaded
into the cache the first time, when it first embeds something.
`SIGNALSCOPE_LOCAL_EMBEDDING_DEVICE` picks where it runs, and a GPU is not
needed. `SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE` sets how many texts it embeds
in one pass. `SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` sets where the model
files are kept.

## Local reranking

A reranker reads the query and each candidate passage together and scores how
well they match. It is slower than vector search, so it only reorders a short
list of candidates. SignalScope uses
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, a multilingual model. It is fixed
for now.

It is off by default and needs its own switch, separate from local
embeddings:

```bash
pip install -e ".[local-reranking]"
export SIGNALSCOPE_LOCAL_RERANKING_ENABLED=true
```

Like the embedding model, it is loaded, and downloaded the first time, only
when it first scores something. Its files go to
`SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` when that is set.
`SIGNALSCOPE_LOCAL_RERANKING_DEVICE` picks where it runs, and
`SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE` how many pairs it scores in one pass.

## Local entity extraction

SignalScope can find people, organizations, places and other entities in
chunks with `urchade/gliner_multi-v2.1`, a multilingual GLiNER model. It looks
for a fixed list of types: person, organization, location, country, city,
product, event and date. Types are stored in lower case.

It is off by default and has its own extra and switch:

```bash
pip install -e ".[local-entities]"
export SIGNALSCOPE_LOCAL_ENTITIES_ENABLED=true
```

The model is loaded, and downloaded the first time, only when it first reads
a chunk. Its files go to `SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` when that is
set. `SIGNALSCOPE_LOCAL_ENTITY_DEVICE` picks where it runs.
`SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD` is the lowest score a span needs to be
kept. Higher values keep fewer, surer entities.

## Local structured extraction

SignalScope can read events and claims out of chunks with
`fastino/gliner2.5-multi-v1`, a multilingual GLiNER2 model. One loaded copy of
the model serves both. The model name is fixed.

It is off by default and has its own extra and switch:

```bash
pip install -e ".[local-structured]"
export SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true
```

Turning it on does not load anything. The model is loaded, and downloaded the
first time, only when it first reads a chunk. Its files go to
`SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` when that is set.
`SIGNALSCOPE_LOCAL_STRUCTURED_DEVICE` picks where it runs.

## Local answer generation

`POST /research/answer` can write answers with `Qwen/Qwen3-4B-Instruct-2507`,
run on this machine with Transformers. The model name is fixed. It is off by
default, and the endpoint answers 503 until it is turned on:

```bash
pip install -e ".[local-answers]"
export SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true
```

Turning it on does not load anything. The model is loaded, and downloaded the
first time, only when it first answers. It is several gigabytes. Its files go
to `SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR` when that is set.
`SIGNALSCOPE_LOCAL_ANSWER_DEVICE` picks where it runs, and
`SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS` caps the length of an answer.

## Authentication

`SIGNALSCOPE_AUTH_ENABLED=true` turns on sign in with email and password,
organizations, and access rules for investigations. It is off by default, and
then the existing APIs work without a login, as before; the sign in,
organization and investigation member routes answer 503.

Sessions are opaque: a random bearer token is given once at login, and only
its SHA-256 hash is stored. They last `SIGNALSCOPE_AUTH_SESSION_DAYS` days and
can be revoked. Passwords are hashed with Argon2id.

`signalscope cleanup-auth-sessions` deletes sessions that expired or were
revoked more than `SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS` days ago. Active
sessions are never deleted. Run it from a scheduler, for example once a day.
