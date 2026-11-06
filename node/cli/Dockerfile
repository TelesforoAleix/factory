# Build with no credentials, secret mounts, or private build context.
FROM node:22-bookworm-slim AS cli-tools
RUN npm install --global @anthropic-ai/claude-code@2.1.318 @openai/codex@0.162.1 \
    && claude --version && codex --version \
    && npm cache clean --force

FROM ghcr.io/astral-sh/uv:0.11.18 AS uv
FROM python:3.13-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 21000 factory-cli \
    && useradd --uid 21000 --gid 21000 --home-dir /home/agent --create-home factory-cli \
    && mkdir /login /work /run/factory \
    && chown 21000:21000 /login /work /run/factory
COPY --from=cli-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=cli-tools /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude \
    && ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
COPY --from=uv /uv /uvx /usr/local/bin/
USER 21000:21000
ENV HOME=/home/agent UV_PYTHON_DOWNLOADS=never
WORKDIR /work
CMD ["codex", "--version"]
