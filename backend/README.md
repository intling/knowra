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

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Database migrations

Start PostgreSQL, then run:

```bash
uv run alembic upgrade head
```
