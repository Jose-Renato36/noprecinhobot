# Deploy tudo-em-um: um único serviço servindo a API e o painel React.
#
# Existe para tirar o build da mão da detecção automática de linguagem. A raiz
# deste repositório só contém backend/ e frontend/, então o Railpack não
# identifica linguagem nenhuma e aborta. Havendo um Dockerfile na raiz, a
# Railway usa ele e a detecção deixa de importar — não é preciso configurar
# Root Directory.
#
# Como o painel passa a ser servido pela mesma origem da API, some a
# necessidade de CORS_ORIGINS e de VITE_API_URL: o frontend chama /api por
# caminho relativo (ver frontend/src/api.js).

# --- Etapa 1: compila o painel React ------------------------------------- #
FROM node:20-slim AS frontend

WORKDIR /app/frontend

# Copiar só os manifestos primeiro aproveita o cache de camadas: enquanto as
# dependências não mudarem, o npm ci não roda de novo.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Etapa 2: API + painel compilado ------------------------------------- #
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# O caminho importa: config.py deriva FRONTEND_DIST de <pasta do backend>/../frontend/dist.
# Com o backend em /app/backend, o padrão aponta para /app/frontend/dist, que é
# exatamente onde a etapa anterior deixa o build — sem precisar de variável.
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# A Railway injeta PORT; o padrão cobre o `docker run` local.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
