# Built from the *repository root*, not from backend/: the image has to carry `pack/`, and a
# build context of ./backend cannot see a sibling directory. Compose sets the context for the
# local path and render.yaml sets it for the hosted one, so both agree.
#
#   docker build -f backend/Dockerfile .
FROM python:3.13-slim

# tesseract is a runtime dependency, not a dev convenience: receipt images in the pack are
# photographs of paper bills and OCR is the only way in. pytesseract shells out to this binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so application edits do not invalidate the install.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/src ./src
# The image has to carry the migrations: the entrypoint runs `alembic upgrade head` before
# uvicorn, and without these the container starts against an empty database and every query
# fails with "no such table".
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/docker-entrypoint.sh ./

# The specification pack, baked in. A deployment has no repository checkout to bind-mount from,
# and the seed reads employee_master.csv, the policy, fifteen .eml files and two receipts out of
# it on every start. Copied, never written to: PACK_DIR points here and nothing in the
# application opens it for writing. Compose still mounts the working copy over this at /pack so
# an edit to the pack shows up without a rebuild.
COPY pack ./pack
ENV PACK_DIR=/app/pack

RUN chmod +x docker-entrypoint.sh && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
