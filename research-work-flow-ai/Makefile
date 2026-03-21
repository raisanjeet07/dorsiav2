.PHONY: setup db db-stop run dev test lint clean migrate

# ─── Setup ───────────────────────────────────────────────────────────
setup:
	pip install -e ".[dev]"

# ─── Database (Postgres via Docker) ──────────────────────────────────
db:
	docker compose up -d db
	@echo "Waiting for Postgres to be healthy..."
	@until docker compose exec db pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done
	@echo "Postgres is ready on localhost:5432"

db-stop:
	docker compose down

db-reset:
	docker compose down -v
	$(MAKE) db

# ─── Run ─────────────────────────────────────────────────────────────
run:
	python -m app.main

dev:
	RESEARCH_DEBUG=true python -m app.main

# ─── Test ────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

lint:
	ruff check app/ tests/
	ruff format --check app/ tests/

format:
	ruff check --fix app/ tests/
	ruff format app/ tests/

# ─── Migrations (Alembic) ───────────────────────────────────────────
migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(msg)"

# ─── Clean ───────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache dist build *.egg-info
