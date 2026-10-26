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

## Authentication and account management

Run `uv run alembic upgrade head` before starting the server. Users register with
an email, display name and password; public registration always creates a
`member`. Passwords contain 10–128 characters, including a letter and a digit,
and cannot equal the normalized email or its local part. Only argon2id hashes
are stored, in a separate `user_credentials` table.

Login uses an opaque `knowra_session` HttpOnly Cookie (`SameSite=Lax`,
`Path=/api`); the database stores only its SHA-256 hash. Sessions expire after
an absolute lifetime and are checked against the user's current status and role
on each request. There is no fallback to the old default user.

| Endpoint | Behavior |
|---|---|
| `POST /api/auth/register` | `{email, display_name, password}` → 201 user and session |
| `POST /api/auth/login` | `{email, password}` → 200 user and rotated session |
| `POST /api/auth/logout` | 204; revoke current session and clear Cookie; idempotent |
| `GET /api/users/me` | Current user, including `role` and `permissions` |
| `PATCH /api/users/me` | `{display_name}` → updated user |
| `POST /api/users/me/password` | `{current_password, new_password}` → 204; revoke all sessions |
| `GET /api/admin/users?offset=0&limit=20` | Admin-only page; optional `q,role,status`; limit 1–100 |
| `GET /api/admin/users/{id}` | Account, active session count and rolling quota snapshot |
| `GET /api/admin/users/{id}/chat-limit` | Rolling 60-minute quota snapshot |
| `PUT /api/admin/users/{id}/chat-limit` | `{hourly_limit: null}` for unlimited, or integer 1–100000 |
| `POST /api/admin/users/{id}/revoke-sessions` | Revoke active sessions; `{revoked_count}`; self requests return 409 |
| `PATCH /api/admin/users/{id}` | Admin-only `{role?, status?}` update |
| `POST /api/admin/users` | Admin-only `{email, display_name, password, role?, status?}` → 201 user |
| `POST /api/admin/users/{id}/reset-password` | Admin-only `{new_password}` → 204; revoke all target sessions |
| `DELETE /api/admin/users/{id}` | Admin-only soft deletion → 204; disable and revoke all target sessions |

Except for health and auth routes, all business APIs require a session. `admin`
and `member` can read, search, upload and process their own documents; `viewer`
can only read and search. Only `admin` has `users:manage`, `models:manage`,
`operations:read` and `audit:read`. Administration does
not grant access to another user's documents. Foreign resources return 404;
missing sessions return 401 and insufficient permissions return 403. Error
responses use `{detail, code}`; validation errors retain a `detail` list with
`loc`, `msg` and `type`, excluding input values to avoid echoing passwords.

Disabling a user revokes all sessions; enabling them requires a fresh login.
Role changes apply on the next request. The last active administrator cannot
be demoted, disabled or deleted, and administrators cannot disable or delete themselves.
Reset your own password through account settings with the current password.
Deletion retains historical documents and ownership and reserves the email;
there is no restore or physical purge button. Creation conflicts return
`email_conflict`; self reset/delete return `cannot_reset_self` / `cannot_delete_self`.
PostgreSQL transaction locks preserve the last administrator during concurrent changes.

Account search trims leading/trailing whitespace, matches literal email/name
substrings case-insensitively, and combines role/status with AND before pagination.
The raw query is limited to 100 characters; `%`, `_` and `\` are literal.
Deleted users are excluded. Details expose no credentials or session tokens.
Revocation affects only unexpired, unrevoked sessions, is repeat-safe (0), and
returns `cannot_revoke_self_sessions` for the caller; use account settings instead.

Quota snapshots contain `hourly_limit,occupied_slots,remaining,window_seconds,observed_at`.
The first three fields are null for unlimited accounts. Occupancy includes in-flight
reservations; it is not an exact successful question count, historical usage or a bill.
Shrinking a limit below occupancy leaves accepted requests intact and blocks new
admissions; increasing it adds room. Removing a limit preserves unexpired reservations,
which count again when a limit is restored. Unlimited requests are never backfilled.
Admission and limit creation/removal share a stable per-account PostgreSQL advisory
transaction lock, including when no quota row exists, and release it before model calls.

### Model administration

Administrators open `/admin/models` to manage system-wide `chat`, `embedding`,
`rerank`, and `query_rewrite` profiles. Apply `uv run alembic upgrade head`
before starting the updated server. The model revision `20261022_0001` creates
`model_profiles` and four empty `model_bindings`; existing users and documents
are retained. With no active profile, each purpose uses its environment configuration.

Generate a master key once, place it in `MODEL_CONFIG_ENCRYPTION_KEY` in the
server environment, and back it up separately from the database:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

All instances must share the same key. API responses expose only `has_api_key`;
stored API keys use Fernet encryption. Omitting or leaving an edit key blank
preserves it; `clear_api_key=true` explicitly clears it. Local services may
use no key. A missing/invalid master key or unreadable active secret returns
503 `model_secret_unavailable`; active configuration never silently falls back.
Restore the original master key alongside database backups. For rotation,
stop model requests and either re-encrypt secrets offline or clear the old
secrets before replacing the master key and re-entering them. Directly
replacing the key makes existing ciphertext unreadable.

| Endpoint | Behavior |
|---|---|
| `GET /api/admin/models?kind=chat&offset=0&limit=20` | Filtered page; limit 1–100 |
| `GET /api/admin/models/effective` | Four purpose summaries: source, enabled, safe model ID, binding/profile revision and latest diagnostic |
| `POST /api/admin/models/{id}/test` | `{expected_revision}`; fixed sample, explicit test, no default change |
| `POST /api/admin/models` | 201 profile; required `name, kind, base_url, model` |
| `PATCH /api/admin/models/{id}` | Partial update; kind is immutable |
| `DELETE /api/admin/models/{id}` | 204; current defaults cannot be deleted |
| `POST /api/admin/models/{id}/activate` | Select the single default for this purpose |
| `POST /api/admin/models/{id}/deactivate` | Restore that purpose's environment fallback |

Optional fields are `api_key`, `enabled`, `timeout_seconds` (1–120),
`max_retries` (0–3), `dimensions` (Embedding only, fixed 2560), and `api_format`
(rerank only: `compatible` or `dashscope`; rerank retries are fixed at zero).
URLs must use HTTP(S) without embedded credentials, query or fragment.
Saving does not contact the model service. Disabled profiles cannot be activated;
current defaults must be replaced or deactivated before disabling or deleting.

Each edit increments the profile `revision`, separately from the purpose's binding
revision. Explicit tests also support disabled profiles and use saved configuration
only, with fixed non-private samples. They may incur a small provider charge;
success checks connectivity/protocol, not retrieval or answer quality. A result is
current only for the tested revision and for 15 minutes; the UI marks expiration
without repeating the call. Editing/deleting a configuration makes old results stale.

| Diagnostic variable | Default | Constraint |
|---|---|---|
| `ADMIN_MODEL_TEST_TIMEOUT_SECONDS` | `10` | Total deadline, greater than 0 and at most 30 seconds; zero retries |
| `ADMIN_MODEL_TEST_COOLDOWN_SECONDS` | `30` | Per-profile cooldown, shared by workers using the same database |
| `ADMIN_MODEL_TEST_MAX_CONCURRENT` | `2` | Global in-flight limit across those workers |

Database leases enforce admission in short transactions; no database lock spans the
network call. Expired running leases read as interrupted and release capacity.
Clients close on completion/cancellation. Local and private deployments are supported;
validated DNS addresses constrain the actual connection, link-local/cloud metadata
targets are blocked, redirects and environment proxies are disabled.

Executed probes return HTTP 200 with `passed/failed` and a safe code, including
`model_test_timeout`, `model_test_auth_failed`, `model_test_unreachable` and
`model_test_invalid_response`. Admission returns 409 `model_revision_conflict`,
429 `model_test_rate_limited` with `Retry-After`, or 503 `model_secret_unavailable`.
Requests cannot supply arbitrary URLs, temporary keys or custom payloads.

Changes affect subsequent search requests and new vectorization tasks. A request
resolves one independent configuration snapshot; queued tasks keep their captured
configuration in memory without putting plaintext keys into job JSON. Search and
rewrite caches, request deduplication and circuit breakers include configuration
revisions while retaining user isolation. Request and task clients close after
use; the shared rewrite pipeline creates and closes a client per LLM call.
Activating a rerank/rewrite profile enables that stage; activating Embedding
enables automatic vectorization after parsing/chunking when those stages are enabled.

If undeleted users have succeeded vectors or queued/running embedding jobs,
changing effective Embedding `(base_url, model, dimensions)` returns 409
`embedding_index_conflict`, including reverting to a different environment model.
Changing name, key or timeout is permitted. No automatic reindexing is performed.
When a managed Embedding default exists, re-embed request overrides of its model
or dimensions return 409 `embedding_configuration_managed`. Admission and default
changes coordinate through the same PostgreSQL binding lock.

For a frontend rollback, keep the migrated backend and database, including defaults,
quota changes and history. Do not downgrade model tables as a code rollback step.
Changing defaults back to environment configuration remains an explicit operation
subject to the same Embedding compatibility checks. Back up the database and original
master key together with the release artifacts.

### Administrative monitoring and audit

`/admin` opens `/admin/overview`; the other pages are `/admin/users`, `/admin/models`,
`/admin/jobs`, `/admin/audit` and `/admin/system`. Existing users/models URLs and write
contracts remain compatible. Operational reads require `operations:read`; audit reads
require `audit:read`. Members/viewers receive 403 and anonymous requests receive 401.

| Endpoint | Safe read behavior |
|---|---|
| `GET /api/admin/overview` | Snapshot time, valid accounts/uploads, original-file logical bytes, per-stage queued/running and 24-hour outcomes, attention links |
| `GET /api/admin/jobs` | `kind,status,owner_user_id,from,to,offset,limit`; default last 24 hours by creation time |
| `GET /api/admin/jobs/{kind}/{id}` | Selected job plus all actual attempts for the same upload; absent stages stay absent |
| `GET /api/admin/audit-events` | `from,to,actor_user_id,action,result,trace_id,offset,limit`; default last 7 days |
| `GET /api/admin/system/status` | Check time, `scope:instance`, instance ID and component statuses |

Time filters use UTC `[from,to)`, at most 31 days. Jobs and audit sort by
`(created_at DESC,id DESC)`; pages return `{items,total,offset,limit}` (20 by
default, at most 100). Jobs use `parse/chunk/embedding`; audit results use
`success/denied/failed`. Invalid ranges return a safe 422 explanation.

Overview counts exclude soft-deleted uploads and owners. Active means login-enabled,
not online. Logical bytes exclude derived files and database overhead. Stage outcomes
use `finished_at` in the preceding 24 hours; a zero-denominator rate is null. Unavailable
blocks remain null and marked unavailable, with other blocks still readable.

Task projections never select private filenames, titles, storage paths, document/chunk
text, vectors, questions, answers or raw errors. Known error codes map to safe details;
unknown errors become a generic processing failure. There is no cross-user content
preview, download, retry, cancel or delete endpoint. Existing document APIs remain
owner-scoped. Long-running jobs are observations, not automatic state repairs.

System checks cap each active dependency probe at 2 seconds and all probes at 5 seconds.
Database and pgvector checks are read-only; document-model readiness belongs to the
responding process. Model source and last explicit tests load separately through
`models/effective`. Refresh never calls model providers. `unknown`, `disabled` and
unavailable states are explicit. If authentication's database is unavailable, the API
returns a safe 503 `admin_dependency_unavailable`; it does not bypass authentication.

Account/model writes, quota changes and session revocation commit with their successful
audit event. Executed model results commit with their result audit. If success auditing
fails, the business transaction rolls back with 503 `admin_audit_unavailable`.
Rejected/failed attempts try a separate safe event after rollback. Audit events keep
actor/resource UUIDs, fixed action/result, safe before/after values, time and trace ID.
Passwords, ciphertext, tokens, account/display names, full URLs and private content are
excluded; reads apply the action whitelist again. No edit, delete, export or raw-log
reader is exposed. This release does not automatically purge audit or probe history;
retention/archival policy is a separate operational decision.

### Administrator bootstrap and recovery

From `backend`, after applying migrations:

```bash
uv run python -m app.cli create-admin --email admin@example.com --display-name 管理员
uv run python -m app.cli reset-password --email admin@example.com
```

These commands prompt for a hidden password and confirmation. Automation may
use `--password-stdin` to read one line from protected stdin; plaintext password
arguments are not accepted. Exit codes: 0 success, 1 invalid input/password,
2 unmet prerequisites (for example, email already taken).

For an existing installation, add `--claim-legacy-user` to `create-admin` to
claim the original default user and retain their UUID and document ownership.
The legacy user must exist, be undeleted and have no credential. Without that
option a separate account is created; registration never inherits old data.
Password resets revoke all sessions, including sessions on other devices.

### Limited demo accounts

Create a member with a rolling hourly chat limit using protected stdin or the
interactive password prompt (never pass a password as a command argument):

```bash
uv run python -m app.cli create-user --email demo@deerfd.com --display-name 演示账号 --hourly-chat-limit 3
```

`create-user` always creates an active member; omitting `--hourly-chat-limit`
leaves it unlimited. A limit must be a positive integer. Account, credential
and quota are committed atomically. Existing users are never changed by this
command; use `reset-password` for password recovery.

`POST /api/search` reserves quota before retrieval or model initialization.
Three successful requests in the preceding 60 minutes block a fourth with
HTTP 429, `{code: "chat_quota_exceeded", detail: "…"}` and a positive
`Retry-After` in seconds. The window rolls from each admission time and is
shared across devices, login sessions and chat threads. Cached successes count;
invalid requests, evidence clarifications, failures and `generation_error`
fallbacks do not. Successful general answers count even without indexed documents. Accounts without a `user_chat_limits` row remain unlimited.

Migration `20261021_0002` adds `user_chat_limits` (positive hourly limit per
user) and `chat_usage` (UTC admission events, indexed by user and time).
PostgreSQL acquires the per-account advisory lock and then the limit row for the short admission transaction; external
calls run after commit. Failed requests release only their own reservation.
Graceful shutdown drains requests. A forced process kill or failed cleanup
can conservatively occupy quota until the 60 minute window expires; expired
events are removed on that account's next admission. No scheduler is required.

The frontend accepts `/login#demo=<base64url JSON>` for the demo identity only;
see [frontend demo links](../front/README.md#demo-interview-link). Share links
contain usable demo credentials and must be generated outside tracked source.

### Auth configuration and deployment

| Variable | Default | Behavior |
|---|---|---|
| `AUTH_COOKIE_SECURE` | `false` | Require HTTPS for the session Cookie |
| `AUTH_SESSION_TTL_HOURS` | `336` | Absolute session lifetime (14 days) |
| `AUTH_LOGIN_MAX_FAILURES` | `5` | Failed logins per normalized email before lockout |
| `AUTH_LOGIN_WINDOW_SECONDS` | `900` | Sliding failure window and lockout duration |

Production requires `APP_ENV=production`, `AUTH_COOKIE_SECURE=true` and HTTPS.
`BACKEND_CORS_ORIGINS` must list exact trusted frontend origins; wildcard `*`
is rejected at startup. Unsafe browser requests validate `Origin`, with
`Sec-Fetch-Site` as a fallback. Cookie deployments should use the same site
for frontend and API (the local Vite proxy already does this).

Login failures return the same error for unknown accounts and wrong passwords.
Rate limiting returns 429 with `Retry-After`. The limiter is process-local;
multiple workers/replicas each have their own window. Deployments needing a
global limit should add a shared limiter at the gateway. Expired/revoked session
rows are retained; schedule database cleanup according to retention needs.

## File uploads

The backend exposes `POST /api/uploads` for single-file uploads. The request
must be `multipart/form-data` with the file field named `file`. The API resolves
ownership through the authenticated session and ignores any client-submitted
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
- `DOCUMENT_PARSE_DOCLING_CACHE_DIR`: legacy parser cache setting, default
  `storage/docling-cache`; document model bootstrap does not read or fallback to
  this value
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

### Document model bootstrap

On FastAPI lifespan startup, the backend runs a document model bootstrap step.
It checks the Docling artifacts needed by PDF parsing and the tokenizer needed
by Docling `HybridChunker`, optionally downloads missing files, then starts a
non-blocking runtime preload that loads the Docling PDF pipeline and tokenizer
into process memory. The app does not wait for runtime preload before finishing
startup. Readiness is stored in process-local state and exposed through the
existing `GET /api/health` response under `document_models`. This change does
not add a separate `/api/health/document-models` endpoint.

Model bootstrap uses only the `DOCUMENT_MODEL_*` namespace. It does not reuse,
extend, or fallback to `DOCUMENT_PARSE_*` or `DOCUMENT_CHUNK_*` variables, so
parse behavior, chunk behavior, and model asset preparation stay isolated.

Environment variables:

- `DOCUMENT_MODEL_BOOTSTRAP_ENABLED`: run startup model checks/downloads,
  default `true`
- `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY`: `download_missing` downloads missing
  models at startup; `check_only` only validates local files, default
  `download_missing`
- `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY`: `degraded` starts the app and
  preserves unavailable readiness; `fail_fast` aborts startup, default
  `degraded`
- `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`: local Docling artifact directory,
  default `storage/document-models/docling`
- `DOCUMENT_MODEL_HF_ENDPOINT`: optional Hugging Face endpoint mirror such as
  `https://hf-mirror.com`; empty uses the Hugging Face default endpoint
- `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS`: comma-separated Docling models,
  default `layout,tableformer`
- `DOCUMENT_MODEL_TOKENIZER_NAME`: startup-prepared tokenizer, default
  `Qwen/Qwen2-7B`
- `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`: tokenizer cache directory, default
  `storage/document-models/tokenizers`
- `DOCUMENT_MODEL_SHUTDOWN_TIMEOUT_SECONDS`: maximum seconds to wait for the
  runtime preload thread during graceful shutdown, default `5.0`

With `degraded`, the app can start even when required model files are missing,
but later parse or chunk jobs fail quickly with `error_code=model_unavailable`.
With `fail_fast`, startup fails if file readiness is unavailable. When file
readiness is `ready`, `/api/health` may temporarily report `loading` while the
background runtime preload initializes in-memory Docling/tokenizer objects.
Requests that require those models fail fast during that window instead of
triggering a long first-use load. For production Docker images or offline
deployments, prefer preheating the model directories during image build or a
single-process init step, then run with `check_only` and usually `fail_fast`.

The first version assumes a single backend process prepares the model
directories. It does not implement cross-process file locks for multiple
workers downloading into the same path.

During graceful shutdown (`Ctrl+C`, `SIGTERM`, or ASGI lifespan teardown), the
backend marks document model readiness as `shutting_down`, waits up to
`DOCUMENT_MODEL_SHUTDOWN_TIMEOUT_SECONDS` for preload work, releases in-process
Docling converter/tokenizer references, and best-effort clears torch/CUDA cache
when available. The process does not delete model files on disk. `SIGKILL`,
host crashes, or a container runtime force-kill after its grace period cannot be
cleaned up inside the Python process.

### Docling model artifacts

PDF parsing initializes Docling's PDF pipeline. The startup bootstrap prepares
the default required Docling artifacts, `layout` and `tableformer`, before user
parse jobs run. If Docling readiness is unavailable, non-text parse jobs fail
with `error_code=model_unavailable` instead of waiting for an implicit network
download in the parse path.

After artifacts are available, runtime preload initializes the same PDF
converter/pipeline that parse jobs later reuse. While Docling runtime readiness
is `loading`, PDF parse requests return `503` and background parse jobs fail as
`model_unavailable`; text and Markdown fallback parsing remain unblocked.

For offline or restricted-network development, pre-download the minimum default
PDF artifacts into `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`:

```bash
cd backend
uv run docling-tools models download -o storage/document-models/docling layout tableformer
```

If you need a Hugging Face mirror while preheating manually, set `HF_ENDPOINT`
for that command, for example:

```bash
HF_ENDPOINT=https://hf-mirror.com uv run docling-tools models download -o storage/document-models/docling layout tableformer
```

Keep `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR=storage/document-models/docling` in
`.env`, then restart the backend. The directory must contain downloaded model
artifacts; an empty directory is not enough. If OCR is enabled in the future,
also add the OCR artifacts to `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS` and
preheat them through the model bootstrap path.

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
- `DOCUMENT_CHUNK_TOKENIZER_MODEL`: legacy chunk configuration default retained
  for compatibility; startup-managed chunking uses
  `DOCUMENT_MODEL_TOKENIZER_NAME`
- `DOCUMENT_CHUNK_MERGE_PEERS`: HybridChunker peer merge behavior, default
  `true`
- `DOCUMENT_CHUNK_REPEAT_TABLE_HEADER`: repeat table headers in table chunks,
  default `true`
- `DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES`: inline text threshold before using
  chunk artifact storage, default `2048`
- `DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR`: local root for long chunk text
  artifacts, default `storage/chunks`

The tokenizer model and cache used by startup-managed chunking are
`DOCUMENT_MODEL_TOKENIZER_NAME` and `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`.
`POST /api/parsed-documents/{parsed_document_id}/rechunk` rejects a tokenizer
override outside that startup-prepared tokenizer contract.

To preheat the default tokenizer manually:

```bash
cd backend
uv run python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('Qwen/Qwen2-7B', cache_dir='storage/document-models/tokenizers')"
```

### Chunk artifacts and scope

Short `text` and `contextualized_text` values are stored inline in
`document_chunks`. Values larger than `DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES`
are written under `DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR`, and the database stores
the corresponding storage key. Chunking never modifies existing
`document_segments`.

This version produces durable, previewable chunks that feed directly into
embedding and semantic search (see below). Chunking itself does not create
embeddings or run retrieval — that happens in the next two pipeline stages.

### Dispatcher limitations

The `background_tasks` dispatcher runs in-process and is intended for local
development and testing only. On graceful shutdown, queued or running parse and
chunk jobs are marked `failed` with `error_code=process_shutdown` so they do not
remain stuck. Production deployments should still migrate to an external worker
queue when available, especially for multi-process or multi-replica execution.

## Document embedding

When document chunking succeeds and `DOCUMENT_EMBEDDING_ENABLED=true`, the
backend automatically creates a vector embedding job. The embedding service
takes each chunk's `contextualized_text` (or `text` as fallback) and converts it
into a dense floating-point vector by calling a cloud embedding API
(OpenAI-compatible interface). Embeddings are stored both as JSON float arrays
and in a pgvector `embedding_vector` column on `document_embeddings`, which
`POST /api/search` (see "Semantic search & RAG generation" below) queries
directly via cosine distance.

### API endpoints

- `GET /api/document-embedding-jobs/{job_id}` — query embedding job status,
  configuration snapshot, embedding count, and failure details
- `GET /api/document-chunk-jobs/{chunk_job_id}/embeddings` — paginate through
  the latest active embedding results for a chunk job, ordered by
  `sequence_index`
- `GET /api/document-chunks/{chunk_id}/embedding` — read a single chunk's
  embedding vector detail (dimensions, model name, and first few dimension
  values; not the full 2560-dimension array)
- `POST /api/document-chunk-jobs/{chunk_job_id}/re-embed` — create a new
  embedding job with `202 Accepted`; validates chunk job ownership and
  shutdown state, returns `409 Conflict` if a running job exists, `503 Service
  Unavailable` during graceful shutdown

`POST /re-embed` does **not** re-parse or re-chunk; it reuses existing chunks
and only re-calls the embedding API. On success the new job becomes the active
result and the previous `succeeded` job is marked `superseded`.

### Embedding configuration

Environment variables control embedding behavior:

- `DOCUMENT_EMBEDDING_ENABLED`: enable automatic embedding after chunk success,
  default `true`
- `DOCUMENT_EMBEDDING_API_BASE_URL`: OpenAI-compatible embeddings API base URL
  (required)
- `DOCUMENT_EMBEDDING_API_KEY`: API key for the embeddings service (sensitive;
  never commit real keys to version control)
- `DOCUMENT_EMBEDDING_MODEL`: model name to request from the API, default
  `Qwen/Qwen3-Embedding-4B`
- `DOCUMENT_EMBEDDING_DIMENSIONS`: expected output vector dimensions, default
  `2560`
- `DOCUMENT_EMBEDDING_ENCODING_FORMAT`: encoding format sent to the API, default
  `float`
- `DOCUMENT_EMBEDDING_BATCH_SIZE`: maximum texts per API call (larger inputs
  are automatically split across multiple calls), default `100`
- `DOCUMENT_EMBEDDING_MAX_RETRIES`: maximum retry attempts with exponential
  backoff for transient failures (network timeout, 5xx), default `3`
- `DOCUMENT_EMBEDDING_REQUEST_TIMEOUT`: per-request timeout in seconds, default
  `60.0`

The adapter does **not** retry on 4xx errors (e.g., authentication failure)
— those fail immediately and the job is marked `failed` with
`error_code=api_error`.

### Error handling and shutdown

If the embedding API call fails after all retries, or the response validation
fails (data length mismatch, dimension mismatch), the embedding job is marked
`failed` with an appropriate `error_code` (`api_error` or `invalid_response`).
The parse and chunk jobs remain `succeeded` — embedding failure never rolls
back upstream results.

During graceful shutdown, `queued` and `running` embedding jobs are marked
`failed` with `error_code=process_shutdown`. Already completed jobs are
left unchanged. The embedding service checks shutdown state at key boundaries
(before API call, before persisting results) to fail fast and avoid blocking
the shutdown sequence.

### Limitations

Embeddings are stored both as JSON float arrays (`embedding_json`, queryable via
the REST endpoints above) and as a pgvector `embedding_vector` column used by
semantic search. There is no ANN index (ivfflat/hnsw) on that column yet —
`POST /api/search` runs an exact cosine-distance scan, which is fine at current
data volumes but will need an index as the corpus grows.

## Semantic search & RAG generation

Optional reranking retains the deployed adapter: enable `RERANK_ENABLED`, set
`RERANK_API_BASE_URL`, `RERANK_API_KEY`, `RERANK_MODEL`, and choose
`RERANK_API_FORMAT=compatible|dashscope` (default `compatible`). Timeout is
`RERANK_REQUEST_TIMEOUT=15` seconds. Reranking takes up to
`min(50, max(top_k, 20))` owned candidates after vector retrieval, uses full
chunk text, and orders sources and answer context identically. Failure falls
back to vector order with a safe fixed event. Scores remain cosine distances.
Keep explicit `DOCUMENT_EMBEDDING_DIMENSIONS=2560` for the deployed schema.

`POST /api/search` 是统一自适应问答入口。问候和明确通用知识请求直接调用对话模型，
不调用改写或 Embedding；其他问题优先检索当前用户资料，无命中或空库仍可生成通用回答。
有相关资料时优先引用真实来源，补充解释须标明“通用知识”。明确依赖私有资料的事实问题
缺少依据时引导上传、选择资料，不猜测文档内容。

“总结这些资料的核心观点”等概览请求直接读取资料，无需向量索引，不受 Top-K 限制。
每份文档仅读取最新成功分块版本，支持外置正文；最多自动总结 20 份，超过时请求缩小范围。
正文预算 60,000 字符，按文档分配，部分覆盖会同时在提示词和界面披露。
新增服务边界为 `services/answer_policy.py` 和 `services/summary_context.py`。

### API endpoint

- `POST /api/search` 请求保留 `query`（1–2000 字符）、`top_k`（1–50，默认 5）、
  `history`（最多 20 条消息）与 `session_id`。
- 可选 `document_ids` 为 1–20 个解析文档 UUID，重复项去重，限定检索、计数、总结与缓存。
  省略时使用当前用户可见范围；全部 ID 都必须归属当前用户且源文件未删除。
- 响应保留结果、正文、真实模型/token 和诊断字段，并新增：

| 字段 | 值 |
|---|---|
| `answer_mode` | `general` / `rag` / `summary` / `clarification` |
| `retrieval_status` | `skipped` / `matched` / `no_match` / `empty` / `unavailable` |
| `summary_coverage` | 总结时含 `document_count`、`included_document_count`、`total_chunks`、`included_chunks`、`truncated`；其他模式为 null |
| `answer_incomplete` | 默认 false；为 true 时 `answer` 是已有的部分正文，与输入侧资料覆盖独立 |

总结读到内容时返回 `summary/matched`，向量预览为空、`total_searched=0`；
其来源 `score` 为兼容占位、`rank` 为上下文顺序，不代表语义分数。
澄清不调用模型，模型与 token 为 null。成功通用回答、资料回答、总结均计入原有账号额度，
澄清、生成失败和服务错误释放本次预留。准入仍先于昂贵依赖。

- `401`：未认证；`422`：范围格式或数量错误，包含字段原因。
- `404`：指定资料不存在或不可访问，请重新选择资料（他人、删除、不存在使用同一说明）。
- `503`：对话模型或 Key 未配置，或总结正文暂不可读取（可重试，不暴露存储路径）。
- Embedding 故障：普通问题返回 `general/unavailable`，私有事实返回重试澄清；
  数据库与权限错误继续保留错误语义。模型失败保留 `generation_error`，不当作成功答案。
- 缓存保留用户、资料指纹、模型版本、会话、历史隔离，增加策略版本与排序去重的文档范围；
  总结缓存同时校验可见文档和最新成功分块版本，未向量化资料的新增、删除、重分块也会失效；
  检索不可用与生成失败不缓存。本次无迁移、新依赖或新增环境变量。

```json
{"query":"总结这些资料的核心观点","top_k":5,"session_id":"my-conversation"}
```

限定资料时在上述请求增加 `"document_ids": ["<解析文档 UUID>"]`。

### Search response — `rewrite_info`

When query rewriting is enabled (`QUERY_REWRITE_ENABLED=true`), the response
includes a `rewrite_info` object with the following fields:

| Field | Type | Description |
|---|---|---|
| `original_query` | `string` | The original query text sent by the user |
| `rewritten_queries` | `RewrittenQuery[]` | Array of rewritten query variants, each with `query`, `strategy`, `duration_ms`, `tokens` |
| `strategies_used` | `string[]` | Names of the rewrite strategies executed (e.g. `normalize`, `term_align`, `expand`) |
| `rewrite_time_ms` | `number` | Total rewrite pipeline duration in milliseconds |
| `cache_hit` | `boolean` | Whether the rewrite result came from cache (L1 exact match or L2 semantic match) |
| `cache_level` | `"L1" \| "L2" \| null` | Which cache tier produced the hit, or `null` on cache miss |
| `error` | `string \| null` | Error message if rewriting failed (graceful degradation — search proceeds with original query) |
| `intent` | `string \| null` | Classified query intent (factual/analytical/comparative/procedural/exploratory/chitchat/ambiguous) |
| `complexity` | `int \| null` | Query complexity score (1–10) |
| `rewrite_model` | `string \| null` | The LLM model used for rewriting |
| `quality_scores` | `QualityScores \| null` | 5-dimension rewrite quality evaluation (semantic_preservation, clarity_improvement, information_gain, term_accuracy, retrievability, plus total_score and verdict) |
| `backtrack_triggered` | `boolean` | Whether automatic backtrack retry was triggered when quality was insufficient |
| `backtrack_strategy` | `string \| null` | The upgraded strategy used for backtrack retry (e.g. `expand`), or `null` |

未执行查询重写时（包括直接通用回答和文档总结），`rewrite_info=null`。

### Query rewriting configuration

Query rewriting enhances search quality by protecting technical terms,
resolving pronoun references from dialogue history, and expanding queries
for better retrieval. See `.env.example` for the full list of
`QUERY_REWRITE_*` variables (~20 items).

Key env variables:

| Variable | Default | Description |
|---|---|---|
| `QUERY_REWRITE_ENABLED` | `false` | Master switch for query rewriting |
| `QUERY_REWRITE_API_BASE_URL` | (required) | OpenAI-compatible API base URL for the rewrite LLM |
| `QUERY_REWRITE_API_KEY` | (required) | API key for the rewrite service |
| `QUERY_REWRITE_MODEL` | `qwen3.5-plus` | Model used for rewriting |
| `QUERY_REWRITE_PIPELINE_TIMEOUT` | `30.0` | Total pipeline timeout in seconds (graceful degradation on timeout) |
| `QUERY_REWRITE_STRATEGY_TIMEOUT` | `15.0` | Per-strategy LLM call timeout in seconds |
| `QUERY_REWRITE_CIRCUIT_BREAKER_THRESHOLD` | `5` | Consecutive failures before circuit breaker opens |
| `QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30.0` | Cooldown period before half-open probe |
| `QUERY_REWRITE_CACHE_TTL_SECONDS` | `1800.0` | L1 exact-match cache TTL (session-bound, 30 min) |
| `QUERY_REWRITE_L2_CACHE_TTL_SECONDS` | `3600.0` | L2 semantic cache TTL (cross-session, 1 hour) |

### Search configuration

- `CHAT_API_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, `CHAT_TEMPERATURE`,
  `CHAT_MAX_TOKENS`, `CHAT_REQUEST_TIMEOUT`, `CHAT_MAX_RETRIES`: OpenAI-compatible
  chat completion endpoint used to generate the answer. `CHAT_MAX_TOKENS` defaults to 4096.
- `CHAT_GENERATION_TIMEOUT`: 整轮生成、403 重试与长度续写共享的总截止时间，默认 120 秒，须大于 0。
  `CHAT_REQUEST_TIMEOUT` 仍控制 HTTP 空闲超时，`CHAT_FIRST_TOKEN_TIMEOUT` 控制首帧等待。
- `SEARCH_SIMILARITY_THRESHOLD`: max cosine distance (0–2) for a chunk to be
  considered relevant; `0` disables the filter, default `0.5`
- `SEARCH_MIN_SCORE_THRESHOLD`: the best-ranked chunk must be at or below this
  cosine distance or the whole result set is treated as "no match"; ordinary questions
  still call the LLM with general knowledge. `0` disables the check, default `0.45`.

当没有相关片段或向量时，普通问题仍可生成通用回答，私有事实缺依据时澄清。

回答完整性：适配器保留 `finish_reason`，长度结束最多续写两次，合并正文并累计实际用量。
正常结束不额外调用。过滤或缺少结束标记的流不自动续写；续写耗尽、失败或超时且已有正文时，
返回 `answer_incomplete=true`，保留正文和来源，不写入成功缓存或计入成功额度。完全没有正文时沿用
`generation_error`。成功续写仍只算一次问答，但产生多次模型调用费用。
“已提供给模型”的文档/片段数只描述输入；`answer_tokens.total_tokens` 包含输入及输出，
部分供应商的 completion 还包含推理 token，均不能据此推断可见正文是否完整。
部署时核对环境对 `CHAT_MAX_TOKENS` 的显式覆盖；旧值 1024 不会被代码默认值替换。
长总结可按模型能力调至 4096–8192，并确保网关/进程超时允许完整请求结束。

### Limitations

- Search, corpus counts and knowledge-base fingerprints follow the authenticated
  owner's visible document chain. Response caches, rewrite L1/L2 caches and
  in-flight deduplication include a user namespace, even if clients reuse a
  `session_id`. Team sharing is not implemented.
- Streaming responses are not implemented (`ChatAdapter.generate(stream=True)`
  raises `NotImplementedError`); the endpoint always returns a complete answer.
- Query rewriting is supported (see "Query rewriting configuration" above),
  but HyDE and reranking are not yet implemented.

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Structured logging

The backend uses `structlog` on top of the Python standard library logging
stack. `get_logger()` returns a structlog logger that automatically injects a
`trace_id` into every log record. Trace IDs are carried across requests via the
`X-Trace-ID` HTTP header (read by `TraceMiddleware`).

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
logger.info("文件上传完成", file_name="notes.pdf", byte_size=2048)
```

Pass dynamic values as keyword fields. Do not use `%s`/`%d` positional
arguments, f-string log messages, or `extra={...}` in application logger calls.
The `trace_id` is automatically injected — callers never need to pass it
manually.

## Database migrations

Start PostgreSQL, then run:

```bash
uv run alembic upgrade head
```

The auth revision `20261021_0001` adds `users.role`, `user_credentials` and
`user_sessions`, preserving all existing user rows and document ownership.
Existing users initially have role `member` and no credentials, so operators
must explicitly bootstrap or claim an administrator before using old data.

后台改版增量迁移 `20261022_0002` 新增 `admin_audit_events`、
`model_probe_results`，并为已有模型配置补齐 `revision NOT NULL DEFAULT 1`。
迁移本身不改变账号、会话、额度、文档、2560 维向量及默认模型绑定。
账号创建、角色/状态调整、重置密码、软删除，以及模型创建、修改、删除和默认切换，
现已由 `app/services/admin_audit.py` 将业务写入和成功审计同事务提交。
审计不可写返回 503 `admin_audit_unavailable`，业务整体回滚；
业务拒绝/失败回滚后尝试独立留痕，不能覆盖原业务错误。
审计按动作裁剪字段，密码重置只记动作，密钥和地址只记布尔变化，
不保存凭据、会话材料、显示名、完整地址或私有资料内容。
六页接口与交互、真实 PostgreSQL 并发、浏览器验收及回退证据见
[验证报告](../openspec/changes/redesign-admin-console/evidence/verification.md)。

发布前备份数据库和模型加密主密钥；代码回退时保留新增表及历史，
不自动撤销已经发生的业务操作。仅在一次性验证库执行
`uv run alembic downgrade 20261022_0001` 再升级，以检查数据保留；
该降级会删除新增审计和诊断历史，不能作为生产代码回退步骤。
若需回退认证体系，应另行制定凭据和会话的数据归档方案，并保持外部访问关闭，
因为旧版默认账号访问方式不具备当前的身份隔离。
