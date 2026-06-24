# knowra backend

FastAPI backend for knowra.

## Requirements

- Python 3.14.5
- uv
- PostgreSQL with pgvector

## Setup

```bash
cd backend
uv sync
cp .env.example .env
```

## Development

```bash
uv run uvicorn app.main:app --reload
```

The API is served at `http://localhost:8000`, with routes mounted under `/api`.

## Current user

The backend exposes `GET /api/users/me` as the current user contract. This
initial user foundation does not implement login or registration; it returns the
default active user created by the user migration.

## File uploads

The backend exposes `POST /api/uploads` for single-file uploads. The request
must be `multipart/form-data` with the file field named `file`. The API resolves
ownership through the current user service and ignores any client-submitted
`owner_user_id`.

Successful uploads return `201 Created` with the uploaded file record:

- `id`
- `owner_user_id`
- `original_filename`
- `content_type`
- `byte_size`
- `storage_key`
- `checksum_sha256`
- `status`
- `error_message`
- `deleted_at`
- `created_at`
- `updated_at`

Upload settings are configured through environment variables:

- `UPLOAD_STORAGE_DIR`: local root for original uploaded files, default
  `storage/uploads`
- `MAX_UPLOAD_BYTES`: maximum bytes per file, default `20971520`
- `ALLOWED_UPLOAD_CONTENT_TYPES`: comma-separated MIME allow-list

The stored path is derived from `UPLOAD_STORAGE_DIR` plus the server-generated
`storage_key`. Original filenames are stored for display only and are not used
as filesystem paths. Alembic downgrade removes upload metadata; files already
written under `UPLOAD_STORAGE_DIR` must be cleaned separately when rolling back
or resetting local development data.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Structured logging

The backend uses the Python standard library `logging` with a custom
`LoggerAdapter` (`KnowraLogger`) that automatically injects a `trace_id` into
every log record.  Trace IDs are carried across requests via the `X-Trace-ID`
HTTP header (read by `TraceMiddleware`).

### Configuration

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root logger level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | auto | Output format — `console` (coloured, human-readable) or `json` (JSON Lines).  Default depends on `DEBUG`: `console` when `DEBUG=true`, `json` when `DEBUG=false`. |
| `LOG_FILE_PATH` | `logs/knowra.log` | Path to the log file (parent directory is created automatically). |
| `LOG_FILE_MAX_SIZE` | `10485760` | Max bytes per log file before rotation (10 MB). |
| `LOG_FILE_BACKUP_COUNT` | `5` | Number of rotated backup files to retain. |

Set any of these in `.env` or as environment variables.

### Usage in code

```python
from app.core.logging import get_logger

logger = get_logger(__name__)
logger.info("文件上传完成", extra={"file_name": "notes.pdf", "byte_size": 2048})
```

The `trace_id` is automatically injected — callers never need to pass it
manually.

## Database migrations

Start PostgreSQL, then run:

```bash
uv run alembic upgrade head
```
