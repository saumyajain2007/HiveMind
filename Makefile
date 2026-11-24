# Common tasks. Windows users without make: run the commands shown here directly.
.PHONY: dev api web up down logs test e2e fixtures demo

dev:            ## API on :8000 and the web dev server on :5173 against it
	VITE_API_MOCK=false $(MAKE) -j2 api web

api:
	uv run uvicorn marketsim_api.main:app --reload --port 8000

web:
	pnpm -C web dev

up:             ## the full stack in Docker on http://localhost:8080
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test:           ## every Python and web unit test
	uv run pytest -q
	pnpm -C web test

e2e:
	pnpm -C web e2e

fixtures:       ## re-export engine results used by the mock API (web/src/mocks/fixtures/results)
	uv run python -m marketsim_api.export_fixtures

demo:
	uv run python -m marketsim.run_demo --agents 10000 --days 5 --runs 20
