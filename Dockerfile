# Imagem de DEV — o código roda bind-mounted (autoreload do runserver); as deps
# ficam em /venv, FORA de /app, pra não serem sombreadas pelo mount.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/venv \
    UV_LINK_MODE=copy \
    PATH="/venv/bin:$PATH"

# libgl1/libglib2.0-0: OpenCV (dep do insightface). build-essential: fallback pra
# dep sem wheel manylinux. curl: healthcheck do compose.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./

# --no-install-project: o repo não é pacote instalável; só as deps pinadas do lock.
RUN uv sync --frozen --extra dev --no-install-project

# psycopg NÃO está no pyproject/uv.lock (o LXC de prod instala por fora) — sem ele
# o DATABASE_URL postgres não sobe. Camada própria até entrar no lock.
RUN uv pip install "psycopg[binary]>=3.2"

COPY . .

