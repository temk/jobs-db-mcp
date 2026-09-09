FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN uv sync --frozen --no-dev --no-cache --no-editable


FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

# Run unprivileged. Application files stay root-owned and read-only to this user,
# so the server cannot rewrite its own code.
RUN useradd --system --create-home --uid 10001 app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    JOBDBMCP_HOST=0.0.0.0

EXPOSE 8000

CMD ["job-db-mcp"]
