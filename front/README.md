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
user context. The home view uses a ChatGPT-like full-screen shell with a left
sidebar; the user avatar sits at the bottom of that sidebar and opens an account
drawer above the avatar with settings, personal knowledge library, and a local
logout action. Settings opens a floating modal with the current user's profile
fields. The logout action clears frontend-only recent conversations, selected
documents, and the displayed personal knowledge library state; it does not call
an authentication API in this phase.

## File uploads

The home view attachment button lets users choose one local file and submit it
to `POST /api/uploads` as `multipart/form-data`. The frontend sends only the
`file` field; upload ownership is resolved by the backend current-user contract.

Upload states are shown in the composer:

- uploading disables repeat submit
- success clears the selected file
- failure keeps the selected file for retry
- current-user errors disable upload submission

After upload succeeds, the home view calls `POST /api/documents` with the
returned upload id. Successful processing refreshes the material list. A
`409 Conflict` response with `existing_document` is shown as existing document
feedback instead of a generic error.

## Material list

The home view loads `GET /api/documents` and exposes the result from the account
drawer's personal knowledge library entry. The library uses a cloud-drive style
long list: each file row shows a file type badge, bold document name, upload
time, file size, chunk count, status, and right-side rename/delete/more icon
actions. Failed documents show their backend failure reason and a retry action.
Rows have hover styling and can be selected with the left checkbox.

Development requests use `VITE_API_BASE_URL`, defaulting to `/api`. In local
development the Vite proxy forwards `/api` to `http://localhost:8000`, so the
backend must be running for upload testing through the browser.

## Quality gates

```bash
npm run lint
npm run test
npm run build
```
