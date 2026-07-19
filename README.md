# BG Data Platform

Production-ready data pipeline for Bulgarian government statistical data.
Scrapes BNB (Bulgarian National Bank) and NSI (National Statistical Institute), processes files, runs quality checks, and serves an analytics dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser → FastAPI (port 8000)                                      │
│           ├── /          Dashboard (Jinja2 + HTMX + ECharts)        │
│           ├── /api/...   REST API (JSON)                            │
│           └── /docs      Swagger UI (auto-generated)                │
├─────────────────────────────────────────────────────────────────────┤
│  Celery workers (Redis broker)                                       │
│           ├── run_scraper(slug) → downloads files → DataFile        │
│           ├── process_file(id) → parses → Dataset + parquet         │
│           └── analyze_dataset(id) → quality score → QualityReport  │
├─────────────────────────────────────────────────────────────────────┤
│  Storage                                                             │
│           ├── PostgreSQL (SQLModel / SQLAlchemy async)              │
│           ├── data/raw/{institution}/{YYYY-MM}/ — raw downloads     │
│           └── data/processed/{filename}/ — parquet files           │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/)
- OR: Python 3.12+, [uv](https://github.com/astral-sh/uv), Redis, PostgreSQL (for local dev)

## Quickstart (Docker — recommended)

```bash
# 1. Clone and enter project
git clone <this-repo> && cd bg-data-platform

# 2. Create env file
cp .env.example .env
# Edit .env if needed — defaults work for local Docker

# 3. Start the full stack
docker compose up --build

# 4. Open the dashboard
open http://localhost:8000

# 5. Trigger the BNB scraper
curl -X POST http://localhost:8000/api/scrapers/bnb/run
```

The stack starts: PostgreSQL + Redis + web (FastAPI) + worker (Celery) + Flower (task monitor at :5555).

## Local development (without Docker)

```bash
# Install uv
pip install uv

# Create venv and install deps
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Install Playwright browser
playwright install chromium

# Copy and edit env
cp .env.example .env
# Set DATABASE_URL=sqlite+aiosqlite:///./data/platform.db for SQLite

# Run the web server
uvicorn bgdata.main:app --reload --port 8000

# In another terminal — run the Celery worker
celery -A bgdata.tasks.celery_app worker --loglevel=info
```

## Running tests

```bash
pytest tests/ -v --cov=bgdata --cov-report=term-missing
```

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/institutions` | List all institutions |
| GET | `/api/institutions/{id}` | Get single institution |
| GET | `/api/files` | List downloaded files (pagination: `?limit=50&offset=0`) |
| GET | `/api/files/{id}` | Get single file |
| GET | `/api/datasets` | List datasets (`?institution_id=1`) |
| GET | `/api/datasets/{id}` | Get dataset metadata |
| GET | `/api/datasets/{id}/data` | Get dataset rows as JSON |
| GET | `/api/datasets/{id}/quality` | Get quality report JSON |
| GET | `/api/datasets/{id}/export` | Download dataset as CSV |
| GET | `/api/scrapers` | List available scrapers |
| POST | `/api/scrapers/{slug}/run` | Trigger scrape task → `{task_id}` |
| GET | `/api/scrapers/tasks/{task_id}` | Poll Celery task status |

Full Swagger UI: http://localhost:8000/docs

## Adding a new scraper

1. Create `src/bgdata/scrapers/my_scraper.py`:

```python
from bgdata.scrapers.base import BaseScraper, ScraperResult

class MyNewScraper(BaseScraper):
    institution_slug = "my_slug"

    async def run(self, db_session, result: ScraperResult) -> None:
        soup = await self.fetch_soup("https://my-institution.bg/data/")
        # extract links, call self.download_file(url, db_session, result, category="...")
```

2. Register it in `src/bgdata/scrapers/registry.py`:

```python
from bgdata.scrapers.my_scraper import MyNewScraper
REGISTRY["my_slug"] = MyNewScraper
```

3. Add the institution to the DB (via API or the seed logic in `main.py`):

```bash
curl -X POST http://localhost:8000/api/institutions \
  -H 'Content-Type: application/json' \
  -d '{"slug":"my_slug","name":"My Institution","base_url":"https://my-institution.bg"}'
```

## Project structure

```
bg-data-platform/
├── pyproject.toml          # uv-managed, all deps in one file
├── Dockerfile
├── docker-compose.yml      # postgres, redis, web, worker, flower
├── .env.example            # all required variables documented
├── alembic/                # DB migrations
│   └── env.py
├── src/bgdata/
│   ├── main.py             # FastAPI app factory + lifespan startup
│   ├── config.py           # pydantic BaseSettings, env-driven
│   ├── database.py         # async SQLModel engine + session
│   ├── models/             # SQLModel table models (3 tables)
│   ├── scrapers/           # BaseScraper + BNB + NSI + registry
│   ├── processors/         # Excel / CSV / PDF → polars DataFrame
│   ├── quality/            # DataQualityChecker + QualityReport
│   ├── tasks/              # Celery app + scrape/process/analyze tasks
│   ├── api/                # FastAPI JSON routers
│   └── dashboard/          # Jinja2 templates + HTMX + ECharts
└── tests/
    ├── conftest.py          # in-memory DB, async client fixtures
    ├── test_scrapers.py     # scraper unit tests
    ├── test_processors.py   # Excel/CSV/PDF processor tests
    ├── test_quality.py      # DataQualityChecker tests
    └── test_api.py          # API + dashboard integration tests
```

## Environment variables

See `.env.example` for the full list with descriptions.
Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | SQLite (dev) | Full async DB URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `DATA_DIR` | `./data` | Root data directory |
| `SCRAPER_REQUEST_DELAY` | `1.5` | Seconds between requests |
| `BNB_BASE_URL` | `https://www.bnb.bg` | BNB website root |
| `NSI_BASE_URL` | `https://www.nsi.bg` | NSI website root |
