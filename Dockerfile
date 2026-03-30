FROM python:3.12-slim

# System deps for playwright, psycopg2, lxml, pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency spec first for layer caching
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -e ".[dev]"

# Install Playwright browsers (chromium only)
RUN playwright install chromium --with-deps

# Copy source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Ensure data dirs exist
RUN mkdir -p data/raw data/processed

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "bgdata.main:app", "--host", "0.0.0.0", "--port", "8000"]
