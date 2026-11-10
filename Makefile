# Developer commands for Linux/macOS. Windows: .\tasks.ps1 <target> (same targets).
PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help venv install lint fmt typecheck test check up down logs produce smoke

help: ## Show available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

venv: ## Create .venv (activate: source .venv/bin/activate)
	$(PYTHON) -m venv .venv

install: ## Install runtime + dev dependencies into the active environment
	$(PYTHON) -m pip install -r requirements-dev.txt

lint: ## ruff: lint + formatting check
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

fmt: ## ruff: apply formatting and safe fixes
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

typecheck: ## mypy --strict
	$(PYTHON) -m mypy

test: ## pytest (integration tests need MongoDB and RabbitMQ, else they are skipped)
	$(PYTHON) -m pytest -rs

check: lint typecheck test ## Everything CI runs on the code

up: ## Build and start the stack, wait until healthy
	docker compose up --build -d --wait

down: ## Stop the stack and remove its volumes
	docker compose down -v

logs: ## Follow application logs
	docker compose logs -f app

produce: ## Publish the 4 demo messages (python producer.py)
	$(PYTHON) producer.py

smoke: up ## Reviewer scenario end to end against the running stack
	$(PYTHON) scripts/smoke_check.py
