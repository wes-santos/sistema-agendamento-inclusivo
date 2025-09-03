# ========= Builder =========
FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.1.4 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

# deps de sistema para build (psycopg, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# instala poetry via pipx
RUN pip install --no-cache-dir pipx && pipx install "poetry==${POETRY_VERSION}"

WORKDIR /app

# copia somente metadata pra aproveitar cache
COPY pyproject.toml poetry.lock* ./

# instala deps (somente main; as de dev ficam fora da imagem final)
RUN /root/.local/bin/poetry install --no-root --only main

# copia o código
COPY app ./app

# ========= Runtime =========
FROM python:3.13-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# dependências de runtime (psycopg, tzdata p/ BR)
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copia venv pronto do builder
COPY --from=builder /app/.venv /app/.venv
# copia o app
COPY --from=builder /app/app /app/app

# user sem root
RUN useradd -m appuser
USER appuser

# ativa venv no PATH
ENV PATH="/app/.venv/bin:$PATH"

# porta do uvicorn
EXPOSE 8000

# healthcheck simples (ajusta a rota se quiser)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# comando padrão
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

