# Bird API

A FastAPI service.

## Project structure

```
app/
├── config.py        Environment-based settings
├── main.py          FastAPI app and routes
├── observability.py Request IDs, request logging, and 500 handler
├── models.py        Bird and bird image tables, request, and response models
└── database/
    ├── db.py        SQLite engine, sessions, and queries
    ├── reset.py     Command that rebuilds the local database
    ├── seed/        Seed data (birds.json, images/) and seed command
    └── birds.db     Local SQLite database (generated, not committed)
migrations/          Alembic migrations
tests/               pytest tests
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness check (no database access) |
| `GET` | `/health/ready` | Readiness check (`SELECT 1`; `503` when the database is unavailable) |
| `GET` | `/api/v1/birds?offset=0&limit=100` | List birds, with optional filters and sort (see below) |
| `GET` | `/api/v1/birds/{bird_id}` | Get one bird |
| `GET` | `/api/v1/birds/{bird_id}/image` | Get a bird's image as raw bytes, with `ETag` and `Cache-Control` (`304` when `If-None-Match` matches; `404` for an unknown bird) |
| `POST` | `/api/v1/birds` | Create a bird (`409` when the `binomial_name` already exists; `422` for invalid input) |

The list returns `{"items": [...], "total": <int>, "offset": <int>, "limit": <int>}`. `total` is the number of birds that match the filters, independent of `offset` and `limit`. The optional exact-match filters are `conservation_status`, `kingdom`, `phylum`, `class`, `order`, `family`, and `genus`, combined with AND. `sort` is `common_name` (default), `binomial_name`, `conservation_status`, `family`, or `genus`; a leading `-` sorts in descending order. Ties are broken by `id`. An unknown `sort` or `conservation_status` value returns `422`. For example:

```sh
curl 'http://localhost:8000/api/v1/birds?class=Aves&conservation_status=Least%20Concern&sort=-binomial_name&limit=10'
```

Bird JSON responses do not contain the image. They contain `image_url` (the image route's path) and the image metadata `image_media_type`, `image_size`, `image_alt_text`, `image_credit`, `image_license`, and `image_source_url`.

`POST` input rules: `conservation_status` must be an IUCN Red List category name (for example `Least Concern`); text fields are trimmed and must have 1 to 200 characters; `binomial_name` must be `"<genus> <species>"`, with a capitalized `genus` and a lowercase `species`; `image` must be a base64 JPEG or PNG of at most 5 MiB; `image_alt_text`, `image_credit`, and `image_license` are required; and `image_source_url` must be an `http` or `https` URL of at most 2000 characters. The server derives `image_media_type`, `image_size`, and the image's SHA-256 from the image.

See [ARCHITECTURE.md](ARCHITECTURE.md) for details.

## Setup

```sh
uv sync
uv run alembic upgrade head
uv run python -m app.database.seed
```

`alembic upgrade head` creates or migrates the database at `BIRD_API_DATABASE_URL`. The seed command inserts the seed birds that are missing. Both are safe to run again.

## Run

```sh
uv run fastapi dev app/main.py
```

The API runs at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `BIRD_API_DATABASE_URL` | `app/database/birds.db` (absolute SQLite URL) | SQLAlchemy database URL |
| `BIRD_API_LOG_LEVEL` | `INFO` | Level of the app's `bird_api` loggers |

Every response has an `X-Request-ID` header. The value is the incoming `X-Request-ID` header, or a new UUID4 when the request has none. The server logs one `bird_api.request` line per request with the request id, method, path, status, and duration.

## Test

```sh
uv run pytest
```

## Development

Local checks only; there is no CI. Install the git hook once, so the checks run on every commit:

```sh
uv run pre-commit install
```

Run all checks on every file:

```sh
uv run pre-commit run --all-files
```

`pre-commit run --all-files` checks only files that git tracks or stages. To include new untracked files, run the individual commands:

```sh
uv run ruff check --fix
uv run ruff format
uv run mypy
uv run pytest -q -W error
```

Rebuild the local database from scratch. This deletes the SQLite file at `BIRD_API_DATABASE_URL`, runs `alembic upgrade head`, and loads the seed data. It refuses non-SQLite and in-memory URLs:

```sh
uv run python -m app.database.reset
```
