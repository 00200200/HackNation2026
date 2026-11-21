PORT ?= 8080
export PORT

.PHONY: help install dev discord test lint format check up down logs

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

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

up: ## Build and start frontend + backend in Docker (add DISCORD=1 for the Discord bot)
	docker compose $(if $(DISCORD),--profile discord) up --build -d
	@echo "Open http://localhost:$(PORT)"

down: ## Stop the Docker stack
	docker compose --profile discord down

logs: ## Follow Docker logs
	docker compose --profile discord logs -f
