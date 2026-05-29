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

The default allow-list covers TXT, Markdown, PDF, DOCX, PPTX, and legacy
PowerPoint MIME types so uploaded files can enter the document-processing flow.

The stored path is derived from `UPLOAD_STORAGE_DIR` plus the server-generated
`storage_key`. Original filenames are stored for display only and are not used
as filesystem paths. Alembic downgrade removes upload metadata; files already
written under `UPLOAD_STORAGE_DIR` must be cleaned separately when rolling back
or resetting local development data.

## Document processing

Document processing consumes existing `uploaded_files` records. The create API
accepts only `uploaded_file_id`; ownership, storage path, parser, chunker, and
tokenizer are all selected server-side.

Supported first-batch parsers:

- TXT and Markdown via UTF-8 text decoding
- PDF via `pypdf` text-layer extraction only
- DOCX via `python-docx`
- PPT/PPTX via `python-pptx`
- BPE chunk sizing via `tiktoken`

APIs:

- `POST /api/documents` returns `201 Created` with a `parsed` or `failed`
  document. Reprocessing the same `uploaded_file_id` returns `409 Conflict`
  with `existing_document`.
- `GET /api/documents` lists the current user's parsed and failed documents.
- `GET /api/documents/{id}` returns current-user-visible document metadata.
- `GET /api/documents/{id}/chunks` returns parsed chunks ordered by
  `chunk_index`; failed documents return an empty list.

Run migrations before using these endpoints:

```bash
uv run alembic upgrade head
```

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Database migrations

Start PostgreSQL, then run:

```bash
uv run alembic upgrade head
```
