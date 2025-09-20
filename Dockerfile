# ========= Dev Image =========
FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.1.4 \
    POETRY_NO_INTERACTION=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# deps úteis p/ dev (psycopg, git, tzdata, bash)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git curl libpq-dev tzdata bash \
    && rm -rf /var/lib/apt/lists/*

# pipx + poetry
RUN pip install --no-cache-dir pipx && pipx install "poetry==${POETRY_VERSION}"
ENV PATH="/root/.local/bin:${PATH}"

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV" && "$VIRTUAL_ENV/bin/pip" install --upgrade pip
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

ENV POETRY_VIRTUALENVS_IN_PROJECT=false

WORKDIR /app

# cache de deps
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.in-project false \
 && poetry install --no-root --no-interaction --no-ansi

# código (fallback; em dev vamos montar via volume)
COPY app ./app

EXPOSE 8000

RUN poetry env activate

CMD ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
