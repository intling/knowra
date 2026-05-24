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

## Quality gates

```bash
npm run lint
npm run test
npm run build
```
