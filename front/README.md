# knowra front

Vue 3 frontend for knowra.

## Requirements

- Node.js 24.15.0
- npm 11 or newer

## Setup

```bash
cd front
npm install
cp .env.example .env
```

## Development

```bash
npm run dev
```

The app starts at `http://localhost:5173`. API requests under `/api` are proxied to `http://localhost:8000`.

## Main UI (知寻「书房批注本」)

`/` is the main workspace and `/verify` is the pipeline verification tool.

- **Visual system**: tokens live in `src/style.css` — paper / surface / ink / line / brand (松烟青) / cite (朱砂),
  Tailwind v4 font tokens `--font-display` / `--font-sans` / `--font-mono` with local CJK fallbacks only
  (no web-font requests). `prose-knowra` styles answer Markdown (lists, tables, code). `prefers-reduced-motion` is honoured.
- **Shell**: desktop sidebar (272px) or mobile drawer — only one is mounted. The drawer is `inert` when closed;
  when open it traps Tab, closes on Esc / overlay / close button / selecting or creating a conversation, and returns focus to the menu button.
- **Sidebar**: 新对话, 资料库 (`GET /api/parsed-documents` → "N 份已解析资料", with retry and a 流程验证 link), 最近对话
  (rename; delete asks for confirmation in an accessible dialog).
- **Welcome**: three steps 上传资料 → 提问 → 核对来源. The upload button reuses the composer's file input;
  suggestions only fill the composer and focus it (never auto-send).
- **Composer**: textarea on its own row, toolbar below (资料 / 检索 N 段 settings popover with Top-K and replace-on-upload / send).
  Enter sends, Shift/Ctrl/Cmd+Enter inserts a newline, Enter during IME composition is ignored.
- **Turns**: question bubble → answer (seal + reading column, copy, citation stats, token total with details in tooltip)
  → `SourceList` (grouped by `parsed_document_id`, pages, chunk ids, preview; expand for exact API text and rank)
  → `RetrievalDetails` (collapsed; query rewrite, retrieval results, prompt preview).
  Pending turns show 正在检索资料… / 正在生成回答… with `aria-live`. On an explicit send only the message
  container scrolls the new turn into view; async answers never force scrolling.

## Current user

The frontend loads `GET /api/users/me` on the home view to display the current
user context. Login, registration, logout, and user switching are not part of
this phase.

## File uploads

The welcome-page upload button and the composer attachment button let users choose one or more local files and submit each
to `POST /api/uploads` as `multipart/form-data`. The frontend sends only the
`file` field; upload ownership is resolved by the backend current-user contract.

Upload states are shown in the composer:

- each selected file shows its own uploading, uploaded or failed state
- uploaded files remain as chips until the question is sent or the file is removed
- a failed chip shows the server error; remove it and select the file again to retry
- the settings popover can enable replacement of an existing same-name file (`?force=true`)

An upload success means the file is stored; it does not establish that parsing,
embedding or indexing has completed. Automatic processing is controlled by the backend.

## Document parsing

The current chat workspace uploads files without submitting or polling parse jobs
itself. The sidebar reads `GET /api/parsed-documents` to show the number of parsed
documents. The `/verify` page checks the available parsing, chunking and embedding
results for a selected document. The API adapters below remain available for
explicit parse-job integrations.

Supported file types for both upload and parsing:

- PDF (`application/pdf`)
- Markdown (`text/markdown`)
- Plain text (`text/plain`)
- DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- PPTX (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)

Which formats are actually accepted depends on the server-side allow-lists.
The current file picker does not restrict extensions; the server validates each
upload and may reject formats not enabled in its configuration.

The API module (`documentParsing.ts`) exposes:

- `createDocumentParseJob(uploadId)` — POST to create a parse job
- `getDocumentParseJob(jobId)` — GET job status
- `getParsedDocumentForUpload(uploadId)` — GET latest parse result
- `getParsedDocumentSegments(docId, { offset, limit })` — GET paginated segments

All endpoints use the `/api` prefix and `VITE_API_BASE_URL` convention.

## Document chunking

Chunking is a backend responsibility. The main chat workspace does not expose
chunk-job polling or rechunk controls. It displays retrieved chunks with their
document names, page numbers and sequence indices in each answer's source list.
The `/verify` page exposes the processing chain and chunk/vector pairs for
inspection. The chunking API adapters remain available for future management UI.

The API module (`documentChunking.ts`) exposes:

- `getDocumentChunkJob(jobId)` — GET chunking job status
- `getLatestParsedDocumentChunkJob(docId)` — GET latest chunking job for a parsed document
- `getParsedDocumentChunks(docId, { offset, limit })` — GET paginated chunks
- `getDocumentChunk(chunkId)` — GET one chunk detail
- `rechunkParsedDocument(docId, config)` — POST rechunk config overrides

Parsed-document counts do not describe a document as indexed or ready for
semantic search; they only report successful parsing.

Development requests use `VITE_API_BASE_URL`, defaulting to `/api`. In local
development the Vite proxy forwards `/api` to `http://localhost:8000`, so the
backend must be running for upload and parse testing through the browser.

## Quality gates

```bash
npm run lint
npm run test
npm run build
```

## Structured logging

The frontend provides a unified logging module under `src/shared/logger/`.

### Directory structure

```
src/shared/logger/
├── index.ts            # Entry point — initLogger(), re-exports
├── types.ts            # LogLevel, LogRecord, LoggerOptions types
├── trace-context.ts    # TraceManager — UUID7 + sessionStorage
├── logger.ts           # Logger class + createLogger() factory
├── formatter.ts        # Console formatting + colour styles
├── ring-buffer.ts      # In-memory ring buffer
├── disk-buffer.ts      # IndexedDB persistence layer
└── __tests__/          # Vitest test files
```

### Configuration

Environment variables (set in `.env` or Vite env):

| Variable | Default | Description |
|---|---|---|
| `VITE_LOG_RING_SIZE` | `500` | Max entries in the in-memory ring buffer |
| `VITE_LOG_DISK_MAX_SIZE` | `5242880` | Max bytes of IndexedDB log storage (5 MB) |
| `VITE_LOG_FLUSH_SIZE` | `100` | Batch size for flushing ring → disk |
| `VITE_LOG_CONSOLE_LEVEL` | `debug` | Minimum level for console output |
| `VITE_LOG_BUFFER_LEVEL` | `info` | Minimum level for ring-buffer (and disk) storage |

### Usage

```typescript
import { initLogger, createLogger, getRingBuffer } from "@/shared/logger"

// Call once at app startup (main.ts already does this).
initLogger()

// Create a logger for your module.
const logger = createLogger("stores:user", getRingBuffer())
logger.info("用户登录成功", { userId: "u_123" })
logger.error("API 请求失败", new Error("timeout"), { url: "/api/users" })
```

- `trace_id` and `module` are injected automatically.
- `X-Trace-ID` is added to every API request by the HTTP client (`src/api/client.ts`).
- Unhandled Vue errors and Promise rejections are captured and logged automatically.
