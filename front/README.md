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
