FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno for setup URI generation
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:$PATH"

WORKDIR /app

COPY pyproject.toml .
COPY README.md .
COPY vaultkeeper/ vaultkeeper/
RUN pip install --no-cache-dir .

# Download the LiveSync setup URI generator from upstream
RUN mkdir -p /scripts && \
    curl -fsSL https://raw.githubusercontent.com/vrtmrz/obsidian-livesync/main/utils/flyio/generate_setupuri.ts \
    -o /scripts/generate_setupuri.ts

EXPOSE 5985

ENV COUCHDB_HOST=http://localhost:5984
ENV VAULTKEEPER_WEB_PORT=5985

CMD ["vaultkeeper-web"]
