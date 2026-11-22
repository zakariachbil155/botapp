# python-postgresql-template

FastAPI + SQLAlchemy + Alembic + PostgreSQL.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Database migrations

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

## Run

```bash
uvicorn src.main:app --reload
```

## Lint and type check

```bash
ruff check .
mypy
```
