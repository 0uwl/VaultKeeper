# Stage 1: compile Tailwind + DaisyUI CSS
FROM node:20-slim AS css-builder
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY tailwind.config.js ./
COPY vaultkeeper/web/static/input.css vaultkeeper/web/static/input.css
COPY vaultkeeper/web/templates/ vaultkeeper/web/templates/
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno for Setup URI generation
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:$PATH"

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY vaultkeeper/ vaultkeeper/
COPY gunicorn.conf.py .
RUN pip install --no-cache-dir ".[serve]"

# Copy compiled CSS from builder stage
COPY --from=css-builder /build/vaultkeeper/web/static/app.css vaultkeeper/web/static/app.css

# Download the LiveSync setup URI generator from upstream
RUN mkdir -p /scripts && \
    curl -fsSL https://raw.githubusercontent.com/vrtmrz/obsidian-livesync/main/utils/flyio/generate_setupuri.ts \
    -o /scripts/generate_setupuri.ts

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5985

ENV COUCHDB_HOST=http://localhost:5984
ENV VAULTKEEPER_WEB_PORT=5985

ENTRYPOINT ["/entrypoint.sh"]
