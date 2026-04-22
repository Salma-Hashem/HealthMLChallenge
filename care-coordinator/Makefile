.PHONY: setup install run run-prod frontend dev test eval lint clean docker-up docker-down

# ─── Local Development ────────────────────────────────────────────────────────

## Create virtualenv and install all dependencies
setup:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip --quiet
	venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "✓ Setup complete. Copy .env.example → .env and add your CEREBRAS_API_KEY."
	@echo "  cp .env.example .env"

## Install / sync dependencies into existing venv
install:
	venv/bin/pip install -r requirements.txt

## Run Flask development server (auto-reload)
run:
	venv/bin/python main.py

## Run Flask via gunicorn (production-like)
run-prod:
	venv/bin/gunicorn "main:app" --bind 0.0.0.0:5000 --workers 2

## Build the React frontend (output → frontend/dist)
frontend:
	cd frontend && npm install && npm run build

## Run Flask backend + Vite dev server in parallel
dev:
	@trap 'kill 0' SIGINT; \
	  venv/bin/python main.py & \
	  cd frontend && npm run dev & \
	  wait

## Run the CLI chat interface
chat:
	venv/bin/python scripts/chat_cli.py

# ─── Testing ──────────────────────────────────────────────────────────────────

## Run all unit / integration tests
test:
	venv/bin/pytest tests/ --ignore=tests/eval.py -q

## Run the golden-dataset evaluation (offline cases only)
eval:
	venv/bin/python tests/eval.py

## Run evaluation including live LLM cases (requires CEREBRAS_API_KEY)
eval-live:
	venv/bin/python tests/eval.py --live --verbose

# ─── Docker ───────────────────────────────────────────────────────────────────

## Build and start all containers
docker-up:
	mkdir -p logs && touch logs/audit.jsonl
	docker-compose up --build

## Stop all containers
docker-down:
	docker-compose down

# ─── Housekeeping ─────────────────────────────────────────────────────────────

## Remove build artifacts and cache
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.vite
	rm -f logs/audit.jsonl logs/feedback.jsonl
