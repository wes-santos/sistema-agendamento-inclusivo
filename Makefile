# ------------------------------
# Config (pode ajustar se quiser)
# ------------------------------
DC ?= docker compose
COMPOSE_FILE ?= docker-compose.dev.yml
SERVICE ?= api
DB_SERVICE ?= db
ENV_FILE ?= .env.dev

# comandos úteis
POETRY ?= poetry

# ------------------------------
# Alvos principais
# ------------------------------
.PHONY: help
help:
	@echo "Comandos disponíveis:"
	@echo "  make up            -> sobe o ambiente de dev (api + db + mailhog)"
	@echo "  make down          -> derruba os containers"
	@echo "  make restart       -> reinicia a api"
	@echo "  make logs          -> segue logs da api"
	@echo "  make sh            -> shell dentro do container da api"
	@echo "  make psql          -> abre psql no container do db"
	@echo "  make install       -> poetry install dentro do container"
	@echo "  make add PKG=xxx   -> poetry add pacote (main)"
	@echo "  make add-dev PKG=xxx -> poetry add --group dev pacote"
	@echo "  make fmt           -> black + isort + ruff"
	@echo "  make lint          -> ruff check"
	@echo "  make test          -> pytest"
	@echo "  make makemigration MSG='minha rev' -> alembic revision --autogenerate"
	@echo "  make migrate       -> alembic upgrade head"
	@echo "  make downgrade REV=base -> alembic downgrade"
	@echo "  make precommit     -> instala pre-commit hooks"
	@echo "  make rebuild       -> rebuilda imagem da api"
	@echo "  make clean         -> remove venv local e cache do poetry (host)"
	@echo ""
	@echo "Dicas:"
	@echo "  - Use DC='docker-compose' se sua máquina usa o binário antigo."
	@echo "  - Edite COMPOSE_FILE se o nome do arquivo do compose for outro."

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
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) bash

.PHONY: psql
psql:
	$(DC) -f $(COMPOSE_FILE) exec $(DB_SERVICE) psql -U app -d agenda_dev

# ------------------------------
# Poetry dentro do container
# ------------------------------
.PHONY: install
install:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) install

.PHONY: add
add:
	@if [ -z "$(PKG)" ]; then echo "Use: make add PKG=nome-do-pacote"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) add $(PKG)

.PHONY: add-dev
add-dev:
	@if [ -z "$(PKG)" ]; then echo "Use: make add-dev PKG=nome-do-pacote"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) add --group dev $(PKG)

# ------------------------------
# Lint/format/test
# ------------------------------
.PHONY: fmt
fmt:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run black .
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run isort .
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run ruff check --fix .

.PHONY: lint
lint:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run ruff check .

.PHONY: test
test:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run pytest -q

# ------------------------------
# Alembic (migrations)
# ------------------------------
.PHONY: makemigration
makemigration:
	@if [ -z "$(MSG)" ]; then echo "Use: make makemigration MSG='mensagem'"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run alembic revision --autogenerate -m "$(MSG)"

.PHONY: migrate
migrate:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run alembic upgrade head

.PHONY: downgrade
downgrade:
	@if [ -z "$(REV)" ]; then echo "Use: make downgrade REV=<rev|base>"; exit 1; fi
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run alembic downgrade $(REV)

# ------------------------------
# Pre-commit
# ------------------------------
.PHONY: precommit
precommit:
	$(DC) -f $(COMPOSE_FILE) exec $(SERVICE) $(POETRY) run pre-commit install
	@echo "pre-commit instalado. Agora cada 'git commit' roda os hooks."

# ------------------------------
# Build/clean
# ------------------------------
.PHONY: rebuild
rebuild:
	$(DC) -f $(COMPOSE_FILE) build --no-cache $(SERVICE)

.PHONY: clean
clean:
	@echo "Limpando venv local (.venv) e cache do poetry (host)..."
	@rm -rf .venv
	@$(POETRY) cache clear --all pypi || true

