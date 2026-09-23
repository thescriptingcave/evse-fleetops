.PHONY: up down logs ps bootstrap reset-data backend sim dashboard build-dashboard test test-backend test-sim sg-user demo clean

# Port for the FastAPI backend. Not 8000: that is commonly taken by other local
# servers, which then silently answer the simulator and dashboard with 404s.
API_PORT ?= 8010
export EVSE_API_URL ?= http://localhost:$(API_PORT)

# ---- Infrastructure ----------------------------------------------------------

up:
	docker compose up -d
	@echo ""
	@echo "Couchbase console : http://localhost:8091  (Administrator / password)"
	@echo "Sync Gateway admin: http://localhost:4985"

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

bootstrap:
	cd backend && uv run python ../scripts/bootstrap.py

# Wipe stations/telemetry/sessions/work orders and re-seed (keeps volumes, venvs, node_modules).
reset-data:
	sh scripts/reset-dev-data.sh $(if $(YES),--yes,)

sg-user:
	bash scripts/sg_setup.sh tech_garcia password fleet

# ---- Applications ------------------------------------------------------------

backend:
	cd backend && uv run uvicorn app.main:app --reload --port $(API_PORT)

sim:
	cd simulator && uv run python -m sim --url $(EVSE_API_URL)

dashboard:
	cd dashboard && npm run dev

build-dashboard:
	cd dashboard && npm install && npm run build

# ---- Tests -------------------------------------------------------------------

test: test-backend test-sim

test-backend:
	cd backend && uv run pytest -q

test-sim:
	cd simulator && uv run pytest -q

# ---- Demo: bring everything up end-to-end -------------------------------------

demo: up bootstrap
	@cd backend && uv run uvicorn app.main:app --port $(API_PORT) > ../.demo-backend.log 2>&1 & \
	pid=$$!; trap 'kill $$pid 2>/dev/null' EXIT INT TERM; \
	echo "Waiting for backend on $(EVSE_API_URL) (log: .demo-backend.log)..."; \
	for i in $$(seq 1 60); do \
	  curl -fs $(EVSE_API_URL)/healthz >/dev/null && break; \
	  kill -0 $$pid 2>/dev/null || { echo "backend exited; see .demo-backend.log"; exit 1; }; \
	  sleep 1; \
	done; \
	echo "Streaming telemetry for 30s..."; \
	cd simulator && uv run python -m sim --url $(EVSE_API_URL) --duration 30

clean:
	docker compose down -v
	rm -rf backend/.venv simulator/.venv dashboard/node_modules dashboard/dist