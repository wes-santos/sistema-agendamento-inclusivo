# ------------------------------
# Config
# ------------------------------
DC ?= docker compose
COMPOSE_FILE ?= docker-compose.dev.yml
SERVICE ?= api
DB_SERVICE ?= db
ENV_FILE ?= .env.dev

# Use o mesmo compose file em todos os alvos
API_COMPOSE_FILE ?= $(COMPOSE_FILE)

POETRY ?= poetry

# ------------------------------
# Alvos principais
# ------------------------------
.PHONY: help
help:
	@echo "Comandos disponíveis:"
	@echo "  make up            -> sobe o ambiente (api + db + mailhog + pgadmin)"
	@echo "  make down          -> derruba os containers"
	@echo "  make restart       -> reinicia a api"
	@echo "  make logs          -> segue logs da api"
	@echo "  make sh            -> shell dentro do container da api"
	@echo "  make psql          -> abre psql no container do db"
	@echo "  make install       -> poetry install (no serviço api)"
	@echo "  make add PKG=xxx   -> poetry add pacote (no serviço api)"
	@echo "  make add-dev PKG=xxx -> poetry add --group dev pacote"
	@echo "  make run-script FILE=path [ARGS='...'] -> roda script Python"
	@echo "  make run-module MOD=package.module [ARGS='...'] -> roda 'python -m <module>'"
	@echo "  make seed          -> executa scripts/seed.py"
	@echo "  make remind-now    -> executa job remind_t24 imediatamente"
	@echo "  make fmt|lint|test -> format/lint/test"
	@echo "  make makemigration MSG='rev' -> alembic revision --autogenerate"
	@echo "  make migrate       -> alembic upgrade head"
	@echo "  make downgrade REV=base -> alembic downgrade"
	@echo "  make precommit     -> instala pre-commit hooks"
	@echo "  make rebuild       -> build --no-cache da api"
	@echo "  make cron-up       -> sobe reminder-cron"
	@echo "  make logs-cron     -> logs do reminder-cron"
	@echo "  make clean         -> remove .venv local e cache poetry (host)"

.PHONY: up
up:
	$(DC) -f $(COMPOSE_FILE) up -d --build

.PHONY: down
down:
	$(DC) -f $(COMPOSE_FILE) down

.PHONY: restart
restart:
	$(DC) -f $(COMPOSE_FILE) restart $(SERVICE)

.PHONY: logs
logs:
	$(DC) -f $(COMPOSE_FILE) logs -f $(SERVICE)

.PHONY: sh
sh:
	# usa bash que já está instalado na imagem
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) bash

.PHONY: psql
psql:
	$(DC) -f $(COMPOSE_FILE) exec $(DB_SERVICE) psql -U app -d agenda_dev

# ------------------------------
# Scripts / Execuções
# ------------------------------
.PHONY: run-script
run-script:
	@if [ -z "$(FILE)" ]; then echo "Use: make run-script FILE=scripts/seed.py [ARGS='...']"; exit 1; fi
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) poetry run $(FILE) $(ARGS)

.PHONY: run-module
run-module:
	@if [ -z "$(MOD)" ]; then echo "Use: make run-module MOD=app.jobs.remind_t24 [ARGS='...']"; exit 1; fi
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) python -m $(MOD) $(ARGS)

.PHONY: seed
seed:
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) python scripts/seed.py

.PHONY: remind-now
remind-now:
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) python -m app.jobs.remind_t24

# ------------------------------
# Poetry (dentro do serviço api)
# ------------------------------
.PHONY: install
install:
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) poetry install --no-root

.PHONY: add
add:
	@if [ -z "$(PKG)" ]; then echo "Use: make add PKG=nome-do-pacote"; exit 1; fi
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) poetry add $(PKG)

.PHONY: add-dev
add-dev:
	@if [ -z "$(PKG)" ]; then echo "Use: make add-dev PKG=nome-do-pacote"; exit 1; fi
	$(DC) -f $(API_COMPOSE_FILE) run --rm $(SERVICE) poetry add --group dev $(PKG)

# ------------------------------
# Lint/format/test
# ------------------------------
.PHONY: fmt
fmt:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) black .
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) isort .
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) ruff check --fix .

.PHONY: lint
lint:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) ruff check .

.PHONY: test
test:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) pytest -q

# ------------------------------
# Alembic
# ------------------------------
.PHONY: makemigration
makemigration:
	@if [ -z "$(MSG)" ]; then echo "Use: make makemigration MSG='mensagem'"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) alembic revision --autogenerate -m "$(MSG)"

.PHONY: migrate
migrate:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) alembic upgrade head

.PHONY: downgrade
downgrade:
	@if [ -z "$(REV)" ]; then echo "Use: make downgrade REV=<rev|base>"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) alembic downgrade $(REV)

# ------------------------------
# Pre-commit
# ------------------------------
.PHONY: precommit
precommit:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) pre-commit install
	@echo "pre-commit instalado."

# ------------------------------
# Build/clean
# ------------------------------
.PHONY: rebuild
rebuild:
	$(DC) -f $(COMPOSE_FILE) build --no-cache $(SERVICE)

.PHONY: cron-up
cron-up:
	$(DC) -f $(COMPOSE_FILE) up -d reminder-cron

.PHONY: logs-cron
logs-cron:
	$(DC) -f $(COMPOSE_FILE) logs -f reminder-cron

.PHONY: clean
clean:
	@echo "Limpando venv local (.venv) e cache do poetry (host)..."
	@rm -rf .venv
	@$(POETRY) cache clear --all pypi || true
