PORT ?= 8080
export PORT

.PHONY: help install dev test lint format check up down logs

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

install: ## Install Python dependencies
	uv sync

dev: ## Run the API locally with reload on :8000 (no frontend)
	uv run uvicorn prawdowid.app:app --reload

test: ## Run tests
	uv run pytest

lint: ## Check formatting and lint
	uv run ruff format --check .
	uv run ruff check .

format: ## Format and autofix
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Lint and test

up: ## Build and start frontend + backend in Docker
	docker compose up --build -d
	@echo "Open http://localhost:$(PORT)"

down: ## Stop the Docker stack
	docker compose down

logs: ## Follow Docker logs
	docker compose logs -f
