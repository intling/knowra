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
- `MAX_UPLOAD_BYTES`: maximum bytes per file, default `52428800` (50 MB)
- `ALLOWED_UPLOAD_CONTENT_TYPES`: comma-separated MIME allow-list

For PPTX uploads, the canonical MIME type is
`application/vnd.openxmlformats-officedocument.presentationml.presentation`.
Some browsers report `.pptx` files as `application/vnd.ms-powerpoint`; the
upload service accepts that compatibility MIME only when the filename has a
`.pptx` extension and the canonical PPTX MIME is enabled.

The stored path is derived from `UPLOAD_STORAGE_DIR` plus the server-generated
`storage_key`. Original filenames are stored for display only and are not used
as filesystem paths. Alembic downgrade removes upload metadata; files already
written under `UPLOAD_STORAGE_DIR` must be cleaned separately when rolling back
or resetting local development data.

## Document parsing

The backend exposes document parsing APIs for converting uploaded files into
structured content using [Docling](https://github.com/DS4SD/docling). Parsing
is triggered per uploaded file and runs asynchronously via FastAPI
`BackgroundTasks`.

### API endpoints

- `POST /api/uploads/{upload_id}/parse` — create a parse job for an uploaded
  file; returns `202 Accepted` with the job record
- `GET /api/document-parse-jobs/{job_id}` — query a parse job's status
- `GET /api/uploads/{upload_id}/parsed-document` — read the latest successful
  parse result for an upload
- `GET /api/parsed-documents/{id}/segments` — paginate through structural
  segments of a parsed document

A running or queued parse job for the same upload returns `409 Conflict` with
the existing job and upload file info. Files that fail format validation return
`415 Unsupported Media Type`.

### Parse configuration

Environment variables control parsing behavior:

- `DOCUMENT_PARSE_ENABLED`: enable or disable parsing, default `true`
- `DOCUMENT_PARSE_ARTIFACT_DIR`: local root for parse output, default
  `storage/parsed`
- `DOCUMENT_PARSE_MAX_BYTES`: maximum input file size, default `52428800` (50 MB)
- `DOCUMENT_PARSE_MAX_PAGES`: maximum pages per document, default `100`
- `DOCUMENT_PARSE_OCR_ENABLED`: enable OCR in Docling, default `false`
- `DOCUMENT_PARSE_DOCLING_CACHE_DIR`: Docling model cache directory, default
  `storage/docling-cache`
- `DOCUMENT_PARSE_DISPATCHER`: dispatcher type, default `background_tasks`
  (only `background_tasks` is supported in this version)
- `DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES`: comma-separated MIME types accepted
  by the parse endpoint (independent of upload allow-list)
- `DOCUMENT_PARSE_ALLOWED_EXTENSIONS`: comma-separated file extensions accepted
  by the parse endpoint

The parse allow-list is **independent** of `ALLOWED_UPLOAD_CONTENT_TYPES`.
PPTX and other formats must be explicitly enabled in **both** lists for
end-to-end support. The upload allow-list is not automatically widened by the
parse configuration.

### Docling model artifacts

PDF parsing initializes Docling's PDF pipeline. On first use, Docling may need
layout and table-structure model artifacts from Hugging Face. If the machine
cannot reach Hugging Face, PDF parsing can fail with a `ConnectTimeout` and a
message saying no local snapshot was found.

For offline or restricted-network development, pre-download the minimum default
PDF artifacts into `DOCUMENT_PARSE_DOCLING_CACHE_DIR`:

```bash
cd backend
uv run docling-tools models download -o storage/docling-cache layout tableformer
```

Keep `DOCUMENT_PARSE_DOCLING_CACHE_DIR=storage/docling-cache` in `.env`, then
restart the backend. The directory must contain downloaded model artifacts; an
empty directory is not enough. If OCR is enabled, also download the OCR artifacts
for the selected OCR engine.

### Parse artifacts

On success, each parse job writes three artifacts under
`DOCUMENT_PARSE_ARTIFACT_DIR`:

- `content.md` — Markdown rendering
- `content.txt` — plain text
- `docling.json` — full Docling JSON output

This version does **not** save PDF page images, chart images, or table
screenshots. The database stores `storage_key` references rather than inline
content.

If Docling returns no Markdown, text, or segment text for a document, the parse
job is marked `failed` instead of writing empty artifacts.

## Document chunking

When document parsing succeeds and `DOCUMENT_CHUNKING_ENABLED=true`, the backend
automatically creates a document chunking job after `parsed_documents` and
`document_segments` have been persisted. The chunking service receives the
transient in-memory Docling document from the same parse run and passes it to
Docling `HybridChunker`; it does not rebuild a Docling document from
`docling.json`, pickle, or any other persisted parse artifact.

### API endpoints

- `GET /api/document-chunk-jobs/{job_id}` — query chunking job status,
  configuration snapshot, chunk count, and failure details
- `GET /api/parsed-documents/{parsed_document_id}/chunk-job` — query the latest
  chunking job for a parsed document, including queued/running/failed states
- `GET /api/parsed-documents/{parsed_document_id}/chunks` — read paginated
  chunks for the latest active successful chunking job
- `GET /api/document-chunks/{chunk_id}` — read a single chunk, including text,
  contextualized text, heading path, page numbers, token count, source segment
  indices, and metadata
- `POST /api/parsed-documents/{parsed_document_id}/rechunk` — create a new
  chunking job with optional config overrides

`/rechunk` validates ownership and original-upload availability, then rereads
the original uploaded file and reparses it to obtain a fresh in-memory Docling
document. If a chunking job for the same parsed document is already `queued` or
`running`, the API returns `409 Conflict` with the existing job. While a new
rechunk job is running, or if it fails, the previous successful job remains the
active result. Only after the new chunk collection is fully persisted does the
backend mark the old successful job as `superseded`.

### Chunk configuration

Environment variables control chunking behavior:

- `DOCUMENT_CHUNKING_ENABLED`: enable automatic chunking after parse success,
  default `true`
- `DOCUMENT_CHUNK_MAX_TOKENS`: HybridChunker max tokens, default `512`
- `DOCUMENT_CHUNK_TOKENIZER_MODEL`: Hugging Face tokenizer model, default
  `Qwen/Qwen2-7B`
- `DOCUMENT_CHUNK_MERGE_PEERS`: HybridChunker peer merge behavior, default
  `true`
- `DOCUMENT_CHUNK_REPEAT_TABLE_HEADER`: repeat table headers in table chunks,
  default `true`
- `DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES`: inline text threshold before using
  chunk artifact storage, default `2048`
- `DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR`: local root for long chunk text
  artifacts, default `storage/chunks`

The configured tokenizer uses the Docling cache directory
`DOCUMENT_PARSE_DOCLING_CACHE_DIR`. In restricted networks, pre-populate that
cache with the tokenizer/model artifacts needed by Docling and Hugging Face
before running parse-and-chunk flows.

### Chunk artifacts and scope

Short `text` and `contextualized_text` values are stored inline in
`document_chunks`. Values larger than `DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES`
are written under `DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR`, and the database stores
the corresponding storage key. Chunking never modifies existing
`document_segments`.

This version only produces durable, previewable chunks. It does not create
embeddings, write pgvector chunk indexes, enable semantic retrieval, run RAG
question answering, or generate final citations.

### Dispatcher limitations

The `background_tasks` dispatcher runs in-process and is intended for local
development and testing only. If the process restarts while a job is running,
the job remains in `running` status. Production deployments should migrate to
an external worker queue when available.

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
