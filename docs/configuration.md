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
