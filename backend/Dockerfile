FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev

COPY backend/app ./app
COPY scripts ./scripts

ENV PYTHONPATH=/app \
    EVSE_CB_HOST=couchbase-server

CMD ["uv", "run", "--no-dev", "python", "scripts/bootstrap.py"]