# Nortex Travel Expense Settlement
#
# `make up` is the one-command path a reviewer should use.
# `make dev` is the native two-process path with hot reload, for working on it.
#
# There is no database server to start. The database is a SQLite file this application owns.

BACKEND := backend
FRONTEND := frontend

.DEFAULT_GOAL := help
.PHONY: help bootstrap up down logs dev seed migrate revision reset-db \
        test test-backend test-frontend lint format typecheck check clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Create .env files from the committed examples (idempotent)
	@test -f $(BACKEND)/.env || cp $(BACKEND)/.env.example $(BACKEND)/.env
	@test -f $(FRONTEND)/.env.local || cp $(FRONTEND)/.env.example $(FRONTEND)/.env.local
	@echo "Environment files ready."

# ------------------------------------------------------------------ one command

up: bootstrap ## Bring the whole stack up in Docker (api + ui)
	docker compose up --build

down: ## Stop the stack and remove its volumes
	docker compose down -v

logs: ## Tail logs from the running stack
	docker compose logs -f

# ------------------------------------------------------------ local development

dev: bootstrap migrate seed ## Run api and ui natively with hot reload
	@trap 'kill 0' EXIT; \
	(cd $(BACKEND) && uv run uvicorn expense_api.main:app --reload --port 8000) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

seed: ## Load employees and the policy version from pack/
	cd $(BACKEND) && uv run python -m expense_api.seed.cli

migrate: ## Apply migrations
	cd $(BACKEND) && uv run alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add claims"
	cd $(BACKEND) && uv run alembic revision --autogenerate -m "$(m)"

reset-db: ## Delete the local database file and rebuild it from migrations + seed
	# The -wal and -shm siblings go too. Deleting the database alone leaves SQLite pointing a
	# stale write-ahead log at a new file, and the next connection fails with "disk I/O error".
	rm -f $(BACKEND)/data/expense.db $(BACKEND)/data/expense.db-wal $(BACKEND)/data/expense.db-shm
	$(MAKE) migrate seed

# ----------------------------------------------------------------------- quality

test: test-backend test-frontend ## Run all tests

test-backend:
	cd $(BACKEND) && uv run pytest -q

test-frontend:
	cd $(FRONTEND) && npm test

lint: ## Lint both sides
	cd $(BACKEND) && uv run ruff check .
	# RTK intercepts a bare `eslint` and mangles its output into a JSON parse error.
	# rtk proxy runs the real binary; the fallback covers machines without rtk.
	cd $(FRONTEND) && (rtk proxy "npx eslint ." || npx eslint .)

format: ## Format both sides
	cd $(BACKEND) && uv run ruff format .
	cd $(FRONTEND) && npx prettier --write .

typecheck: ## Type check both sides
	cd $(BACKEND) && uv run mypy
	cd $(FRONTEND) && npm run typecheck

check: lint typecheck test ## Everything CI runs

clean:
	rm -rf $(FRONTEND)/.next $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
