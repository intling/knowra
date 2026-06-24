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

## Current user

The frontend loads `GET /api/users/me` on the home view to display the current
user context. Login, registration, logout, and user switching are not part of
this phase.

## File uploads

The home view attachment button lets users choose one local file and submit it
to `POST /api/uploads` as `multipart/form-data`. The frontend sends only the
`file` field; upload ownership is resolved by the backend current-user contract.

Upload states are shown in the composer:

- uploading disables repeat submit
- success clears the selected file
- failure keeps the selected file for retry
- current-user errors disable upload submission

Development requests use `VITE_API_BASE_URL`, defaulting to `/api`. In local
development the Vite proxy forwards `/api` to `http://localhost:8000`, so the
backend must be running for upload testing through the browser.

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
