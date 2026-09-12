FROM python:3.13-slim

# tesseract is a runtime dependency, not a dev convenience: receipt images in the pack are
# photographs of paper bills and OCR is the only way in. pytesseract shells out to this binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so application edits do not invalidate the install.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
# The image has to carry the migrations: the entrypoint runs `alembic upgrade head` before
# uvicorn, and without these the container starts against an empty database and every query
# fails with "no such table".
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
