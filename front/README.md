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
- **Welcome**: 可直接提问，上传资料可增强回答；three steps 上传资料 → 提问 → 核对来源. The upload button reuses the composer's file input;
  suggestions only fill the composer and focus it (never auto-send).
- **Composer**: textarea on its own row, toolbar below (资料 / 检索 N 段 settings popover with Top-K and replace-on-upload / send).
  Enter sends, Shift/Ctrl/Cmd+Enter inserts a newline, Enter during IME composition is ignored.
- **自适应回答**：`general` 显示正文、复制、真实 token 与“基于通用知识”，省略空来源与零引用；
  `clarification` 展示资料引导，不伪造用量；`summary` 显示真实来源与覆盖统计，部分覆盖说明“基于部分资料总结”，
  不显示语义分数；`rag` 保留来源与折叠诊断。`unavailable` 单独提示检索暂不可用，生成错误保持失败状态。
  响应新增模式/覆盖字段可选，兼容旧 localStorage 对话；`searchChunks` 支持可选 `document_ids`（1–20 个 UUID）。
- **回答完整性**：`answer_incomplete=true` 时显示“回答尚未完成”，保留 Markdown 正文、来源和复制；
  缺少该字段的旧记录沿用原展示。总结覆盖表示已提供给模型的资料范围，与正文是否生成完成独立。
- **Turns**（资料回答）: question bubble → answer (seal + reading column, copy, citation stats, token total with details in tooltip)
  → `SourceList` (grouped by `parsed_document_id`, pages, chunk ids, preview; expand for exact API text and rank)
  → `RetrievalDetails` (collapsed; query rewrite, retrieval results, prompt preview).
  Pending turns show 正在检索资料… / 正在生成回答… with `aria-live`. On an explicit send only the message
  container scrolls the new turn into view; async answers never force scrolling.

## Accounts and permissions

`/login` and `/register` provide email/password authentication. Registration
creates a member and signs in automatically. Private routes first probe
`GET /api/users/me`; anonymous users return to login with a sanitized local
redirect. A temporary probe failure offers retry without mounting private views.

The sidebar account menu opens `/account` for profile/password settings and
logout. Administrators also see “后台管理” at `/admin`, redirecting to
`/admin/overview`. The independent admin workspace has desktop navigation and a
mobile drawer, with six pages: overview, users, models, jobs, audit and system.
The original `/admin/users` and `/admin/models` URLs remain valid.
Users can be created with an initial password and fixed role, have passwords
reset (revoking all sessions), be enabled/disabled, change roles, or be deleted
after exact email confirmation (full account UUID for legacy accounts without email).
Deletion retains historical documents and revokes sessions. Self password changes
use account settings; self deletion and disabling are blocked.
Members see a permission message
when directly opening the admin route. Viewers can ask questions and read their
own sources; upload controls are disabled with an explanation. The backend
enforces the same permissions on every API request.

Model management supports chat, Embedding, reranking and query rewriting with
name, HTTP(S) API address, model ID, optional key, timeout and retries. Embedding
uses the database's fixed 2560 dimensions; reranking selects `compatible` or
`dashscope` format with no retries. Save a profile then explicitly activate it
as the purpose's default. Deactivating restores environment configuration.
Blank keys preserve existing secrets; clearing requires the explicit checkbox.
The UI never receives stored keys and clears entered secrets on success, close
or leaving the page. Backend errors, including incompatible Embedding indexes,
are shown without discarding the current list. See `backend/README.md` for the
required migration and master key setup. Only admins receive `models:manage`.

### Admin workspace

| Route | Purpose |
|---|---|
| `/admin/overview` | Dated account/upload snapshots, original-file logical capacity, per-stage 24-hour results, attention links, effective models and recent audit |
| `/admin/users` | Debounced server search, combined role/status filters, details, rolling quota and device-session controls |
| `/admin/models` | Four effective-purpose cards, configuration revisions, explicit tests, editing and default changes |
| `/admin/jobs` | Read-only parse/chunk/embedding metadata and actual-attempt timelines; no private content or cross-user actions |
| `/admin/audit` | Time, actor UUID, action, result and trace filters with safe before/after values; no export/edit/delete |
| `/admin/system` | Check time and instance-scoped database/pgvector/readiness status plus independently loaded effective model summaries |

Operational pages require `operations:read`, audit requires `audit:read`, and users
requires `users:manage`; only admins have these permissions. Restricted routes show
a permission message without requesting admin data. All APIs still enforce authorization.

Lists use server pagination (20 per page) and request generations so slow old responses
cannot replace a new query. Search waits 300ms and keeps email text in page memory;
API logs omit query strings. Refresh preserves existing results with their snapshot time
and marks stale/error states. Successful saves outside current filters explain why the
object is not visible. Errors offer a copyable response trace ID for investigation.

Details/forms use accessible drawers; confirmation is a separate top layer. Tab cycles
within the top dialog, Esc closes that layer, and focus returns to the trigger. Passwords
and keys clear when forms close, succeed or unmount. Layouts were checked at 320, 768
and 1440px. State labels use text as well as color.

Quota means occupied slots in the preceding 60 minutes, including in-flight requests;
it is not historical usage or billing. Adjustments require confirmation, preserve old
reservations and never backfill unlimited requests. Unlimited snapshots show no usage
estimate. Revoking another user's sessions requires confirmation and refreshes the
active count; account settings handle the caller's own authentication.

Model saving, testing and activating are separate actions. Tests send fixed short samples
and may incur a small fee; passing checks protocol/connectivity only. Results show version
and time, expire after 15 minutes (also while the page stays open), and become stale after
editing. The clock only changes local labels; no automatic model calls occur. Cooldown,
revision conflicts and Embedding space protection show the backend's reason.

For release, migrate the backend before publishing the frontend. Rolling back to the
previous frontend keeps the compatible backend, quotas, defaults, audit and diagnostic
tables intact. It does not reverse account or model actions; never run a destructive
database downgrade as a frontend rollback. See the
[verification report](../openspec/changes/redesign-admin-console/evidence/verification.md).

All API modules use `src/api/client.ts`, which sends same-origin Cookies and
trace IDs and normalizes `ApiError`. A private API 401 clears the local identity
and redirects to login; failed login itself stays on the form. Password changes
revoke all sessions. Logout and password changes broadcast a storage event so
other open tabs also leave private views. Session tokens stay in HttpOnly Cookies
and are never copied into localStorage.

Conversation history uses `knowra:chat:v2:{userId}` in localStorage. Switching
accounts clears the mounted workspace and binds the new account's history.
Only the explicitly claimed legacy default user migrates the old `knowra:chat`
key. Conversations remain local to this browser; they are not synchronized to
the server. Files and retrieved sources are always scoped by the backend.

Administrator bootstrap, recovery and HTTPS/Cookie configuration are documented
in [the backend README](../backend/README.md#administrator-bootstrap-and-recovery).

### Demo interview link

`/login#demo=<payload>` accepts base64url encoded UTF-8 JSON with `email` and
`password`. Only `demo@deerfd.com` is eligible. Generate the actual link outside
tracked source using the current demo password; no production password is built
into the frontend. The fragment is encoding, so anyone with the link can use
the shared demo identity.

On opening the link, the login form fills both inputs and immediately replaces
the address to remove the fragment, preserving a valid local redirect. Visitors
click **登录** themselves. No login is submitted automatically. Invalid or
oversized fragments are ignored and cleared. Credentials stay in form memory
and are never sent to probes or written to logs or browser storage. Reloading
the cleaned address shows an empty form; failed login clears the password.

The demo notice explains the shared limit: at most three successful questions
in the preceding 60 minutes, across all visitors, devices and threads. The
backend enforces it and returns a readable 429 and `Retry-After` when exhausted.

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
