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
- success clears the selected file and automatically submits a parse job
- failure keeps the selected file for retry
- current-user errors disable upload submission

## Document parsing

After a successful upload, the home view automatically calls
`POST /api/uploads/{upload_id}/parse` to create an asynchronous parse job. While
the parse job is being submitted or polled, the status shows "解析中". After the
job reaches `succeeded`, the status shows "解析成功". If the job reaches `failed`,
the status shows the server-provided error message and a retry button. On
conflict (a job already running), the status shows the server-provided detail.
On other errors, a retry button is shown with a user-readable failure message.

Supported file types for both upload and parsing:

- PDF (`application/pdf`)
- Markdown (`text/markdown`)
- Plain text (`text/plain`)
- DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- PPTX (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)

Which formats are actually accepted depends on the server-side allow-lists.
The frontend `accept` attribute includes both MIME types and filename
extensions for upload and parse targets, but the server may still reject formats
not enabled in its configuration.

The API module (`documentParsing.ts`) exposes:

- `createDocumentParseJob(uploadId)` — POST to create a parse job
- `getDocumentParseJob(jobId)` — GET job status
- `getParsedDocumentForUpload(uploadId)` — GET latest parse result
- `getParsedDocumentSegments(docId, { offset, limit })` — GET paginated segments

All endpoints use the `/api` prefix and `VITE_API_BASE_URL` convention.

Development requests use `VITE_API_BASE_URL`, defaulting to `/api`. In local
development the Vite proxy forwards `/api` to `http://localhost:8000`, so the
backend must be running for upload and parse testing through the browser.

## Quality gates

```bash
npm run lint
npm run test
npm run build
```
