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

## Quality gates

```bash
npm run lint
npm run test
npm run build
```
