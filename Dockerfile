# Stage 1: Python dependencies
FROM python:3.12-slim AS deps
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

# Install system deps + Node.js (needed for Claude CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget unzip ca-certificates curl git ffmpeg \
        libfontconfig1 libfreetype6 && \
    # Node.js 22 (for Claude CLI)
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    # Godot 4.4 headless
    wget -q https://github.com/godotengine/godot/releases/download/4.4-stable/Godot_v4.4-stable_linux.x86_64.zip && \
    unzip Godot_v4.4-stable_linux.x86_64.zip && \
    mv Godot_v4.4-stable_linux.x86_64 /usr/local/bin/godot && \
    chmod +x /usr/local/bin/godot && \
    rm -f *.zip && \
    # Godot export templates (needed for HTML5 export)
    mkdir -p /root/.local/share/godot/export_templates && \
    wget -q https://github.com/godotengine/godot/releases/download/4.4-stable/Godot_v4.4-stable_export_templates.tpz && \
    unzip Godot_v4.4-stable_export_templates.tpz && \
    mv templates /root/.local/share/godot/export_templates/4.4.stable && \
    rm -f *.tpz && \
    # Claude CLI
    npm install -g @anthropic-ai/claude-code @openai/codex && \
    # Docker CLI — the bevy-builder service shells out to
    # `docker run --rm` against prebuilt sibling images. We mount the
    # host's /var/run/docker.sock; only the static client binary is
    # needed in this image.
    DOCKER_CLI_VERSION=27.5.1 && \
    curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
        | tar -xz -C /tmp docker/docker && \
    mv /tmp/docker/docker /usr/local/bin/docker && \
    rm -rf /tmp/docker && \
    # Cleanup
    apt-get purge -y wget unzip && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Copy Python deps from build stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Chromium and its OS dependencies are required for trusted browser smoke tests.
RUN python -m playwright install --with-deps chromium

WORKDIR /app

# Copy application code
COPY src/ src/
COPY .claude/ .claude/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/agent_asset_broker.py scripts/agent_asset_broker.py
COPY scripts/assign_game_owners.py scripts/assign_game_owners.py
# Pinned generation runtime rendered into each game workspace.
COPY vendor/ vendor/

# Volume mount points for persistent data
RUN mkdir -p generated_games data/game-metadata trusted/asset-budget
VOLUME ["/app/generated_games", "/app/data"]

EXPOSE 8001

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
