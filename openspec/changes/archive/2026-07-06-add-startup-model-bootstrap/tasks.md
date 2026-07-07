## 1. Contract and RED Tests

- [x] 1.1 Add Settings tests for all `DOCUMENT_MODEL_*` defaults, environment overrides, CSV parsing, and the rule that bootstrap config never falls back to existing `DOCUMENT_PARSE_*` or `DOCUMENT_CHUNK_*` variables.
- [x] 1.2 Add bootstrap service tests for `ready`, `unavailable`, `skipped`, `check_only`, `download_missing`, `degraded`, and `fail_fast` outcomes using injected fake Docling/tokenizer adapters.
- [x] 1.3 Add tests proving `DOCUMENT_MODEL_HF_ENDPOINT` is applied before Hugging Face or Docling download/check calls and no mirror URL is hardcoded.
- [x] 1.4 Add parser/dispatcher tests proving model-ready PDF parsing uses `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` and model-unavailable parsing fails with `error_code=model_unavailable` without invoking implicit network download.
- [x] 1.5 Add chunking tests proving tokenizer-ready jobs use `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR`, tokenizer-unavailable jobs fail with `error_code=model_unavailable`, and rechunk requests with an unprepared tokenizer are rejected.
- [x] 1.6 Add health API tests proving existing `GET /api/health` includes document model readiness summaries for `ready`, `unavailable`, and `skipped`, and no `/api/health/document-models` route is introduced.
- [x] 1.7 Run the targeted new tests and confirm they fail for the expected missing behavior, then stop at the red-test review point.

## 2. Configuration and Bootstrap Core

- [x] 2.1 Add `DOCUMENT_MODEL_BOOTSTRAP_ENABLED`, `DOCUMENT_MODEL_BOOTSTRAP_STRATEGY`, `DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY`, `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR`, `DOCUMENT_MODEL_HF_ENDPOINT`, `DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS`, `DOCUMENT_MODEL_TOKENIZER_NAME`, and `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` to backend settings.
- [x] 2.2 Implement model readiness result types for Docling, tokenizer, and aggregate bootstrap state with `ready`, `unavailable`, and `skipped` statuses plus missing-model diagnostics.
- [x] 2.3 Implement `DocumentModelBootstrapService` with injected Docling and tokenizer check/download adapters so unit tests do not require network access.
- [x] 2.4 Implement Docling model check/download behavior for required models such as `layout` and `tableformer`, using `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` as the only bootstrap artifacts directory.
- [x] 2.5 Implement tokenizer check/download behavior for `DOCUMENT_MODEL_TOKENIZER_NAME`, using `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` as the only bootstrap tokenizer cache directory.
- [x] 2.6 Implement Hugging Face endpoint configuration from `DOCUMENT_MODEL_HF_ENDPOINT` before any bootstrap download/check call that can reach Hugging Face.

## 3. Startup Integration and Observability

- [x] 3.1 Wire `DocumentModelBootstrapService` into FastAPI lifespan startup and store the aggregate readiness result on application state or an equivalent injectable runtime state.
- [x] 3.2 Implement `fail_fast` startup behavior that aborts app startup when required model readiness is unavailable.
- [x] 3.3 Implement `degraded` startup behavior that allows the app to start while preserving unavailable readiness for later parsing/chunking checks.
- [x] 3.4 Emit structured startup logs through `get_logger` for ready, unavailable, skipped, downloaded, and failed bootstrap outcomes.
- [x] 3.5 Extend the existing `GET /api/health` response with document model readiness summary while preserving existing health fields and avoiding any new model-specific health route.

## 4. Parsing and Chunking Runtime Integration

- [x] 4.1 Update Docling parser construction to use the bootstrap-prepared `DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR` when Docling readiness is ready, and remove dependency on `DOCUMENT_PARSE_DOCLING_CACHE_DIR` for model artifacts.
- [x] 4.2 Update parse job execution so required-model unavailability marks the parse job as `failed` with `error_code=model_unavailable` and a diagnostic `error_message`.
- [x] 4.3 Keep pure text fallback parsing unblocked by Docling artifacts readiness while preserving downstream chunking readiness checks.
- [x] 4.4 Update chunker/tokenizer construction to use `DOCUMENT_MODEL_TOKENIZER_NAME` and `DOCUMENT_MODEL_TOKENIZER_CACHE_DIR` for startup-managed tokenizer execution.
- [x] 4.5 Update automatic chunking and rechunking so tokenizer unavailability marks chunk jobs as `failed` with `error_code=model_unavailable` and no implicit network download is attempted.
- [x] 4.6 Reject rechunk requests that specify a tokenizer outside the startup-prepared tokenizer contract, returning or recording a clear model-unavailable diagnostic.

## 5. Documentation and Verification

- [x] 5.1 Update `backend/.env.example` with the new `DOCUMENT_MODEL_*` variables and make clear they are isolated from existing parse/chunk variables.
- [x] 5.2 Update root README and backend README with model bootstrap behavior, mirror configuration, offline/preheated Docker image guidance, single-process startup assumption, and fail-fast versus degraded strategy guidance.
- [x] 5.3 Confirm no Alembic migration is needed because readiness is process-local and no database schema changes are introduced.
- [x] 5.4 Run targeted backend tests for config, bootstrap, parsing, and chunking.
- [x] 5.5 Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` from `backend/`.
- [x] 5.6 Run `openspec status --change "add-startup-model-bootstrap"` and confirm the change remains apply-ready.
