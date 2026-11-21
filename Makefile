PORT ?= 8080
export PORT

.PHONY: help install dev discord test lint format check openapi up down logs db db-migrate db-seed corpus corpus-check index

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

install: ## Install Python dependencies
	uv sync

dev: ## Run the API locally with reload on :8000 (no frontend)
	PYDANTIC_AI_NO_BANNER=1 uv run $(if $(wildcard .env),--env-file .env) uvicorn prawdowid.app:app --reload

discord: ## Run the Discord bot locally against the API from `make dev` (needs DISCORD_BOT_TOKEN)
	uv run $(if $(wildcard .env),--env-file .env) python -m prawdowid.discord_bot

test: ## Run tests
	uv run pytest

lint: ## Check formatting and lint
	uv run ruff format --check .
	uv run ruff check .

format: ## Format and autofix
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Lint and test

openapi: ## Regenerate docs/openapi.json from the app (tests fail while it is stale)
	uv run python -c "import json, pathlib; from prawdowid.app import app; pathlib.Path('docs/openapi.json').write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')"

up: ## Build and start frontend + backend in Docker (add DISCORD=1 for the Discord bot)
	docker compose $(if $(DISCORD),--profile discord) up --build -d
	@echo "Open http://localhost:$(PORT)"

down: ## Stop the Docker stack
	docker compose --profile discord --profile sourcedb down

db: ## Start the Postgres source store on 127.0.0.1:5433 (step 2c, not used by checks yet)
	docker compose --profile sourcedb up -d sourcedb

db-migrate: ## Apply db/migrations/ to the running database (safe to rerun)
	cat db/migrations/*.sql | docker compose --profile sourcedb exec -T sourcedb psql -v ON_ERROR_STOP=1 -U prawdowid -d prawdowid

db-seed: ## Seed the running database from corpus/queries.txt through web search (not run by default)
	uv run $(if $(wildcard .env),--env-file .env) python -m prawdowid.corpus --local-db

logs: ## Follow Docker logs
	docker compose --profile discord logs -f

corpus: ## Rebuild corpus/evidence.jsonl from corpus/catalog.yaml (fetches the sources, cached)
	uv run $(if $(wildcard .env),--env-file .env) python -m corpus.build $(ARGS)

corpus-check: ## Check corpus/evidence.jsonl against the brief's thresholds
	uv run python -m corpus.check

index: ## Load corpus/evidence.jsonl into Postgres for search (needs DATABASE_URL)
	uv run $(if $(wildcard .env),--env-file .env) python -m prawdowid.index corpus/evidence.jsonl
