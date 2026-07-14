.PHONY: up down logs migrate seed test fmt shell

up:
	cp -n .env.example .env || true
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend worker

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m app.seed.seed_tenants

test:
	docker compose exec backend pytest -xvs

fmt:
	docker compose exec backend ruff check --fix .
	docker compose exec backend ruff format .

shell:
	docker compose exec backend bash
