# JobDBMCP

MCP server providing controlled access to the job-search PostgreSQL database.

The server exposes domain-specific MCP tools (saving jobs, deduplication checks, site parse
status) over Streamable HTTP. Arbitrary SQL execution is intentionally not exposed.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Docker
- PostgreSQL (17.2 in development, 18 targeted)

## Installation

```bash
uv sync
```

## Configuration

Settings come from environment variables. Copy `.env.example` to `.env` and fill it in; `.env`
is not committed.

| Variable | Description |
| --- | --- |
| `JOBDBMCP_DATABASE_URL` | PostgreSQL connection string for the application role. |
| `JOBDBMCP_ALLOW_WRITES` | Register the write tools. Unset means a read-only server. |
| `JOBDBMCP_HOST` | Bind address, `127.0.0.1` by default, `0.0.0.0` in the image. |
| `JOBDBMCP_PORT` | Listen port, `8000` by default. |
| `LIQUIBASE_COMMAND_*` | Used only when applying migrations, see below. |

## Running

The server speaks MCP over Streamable HTTP at `/mcp`.

```bash
uv run jobdbmcp
```

In Docker, joining the database container's network namespace:

```bash
docker build -t jobdbmcp .
docker run --rm --network container:postgres --env-file .env jobdbmcp
```

Read tools: `job_exists`, `get_job`, `find_jobs`.
Write tools: `save_job`, `set_job_status`, `set_job_score`. They are registered only when
`JOBDBMCP_ALLOW_WRITES` is set; without it they are absent from `tools/list` entirely, so a
read-only deployment does not advertise what it will not do.
See [docs/api.md](docs/api.md) for their inputs and outputs.

## Database

Development uses the local PostgreSQL 17.2 container named `postgres`, database `jobdb`.
See [docs/db.md](docs/db.md) for the schema.

Migrations are Liquibase formatted SQL changesets under `db/changelog/`. The runner image adds
the PostgreSQL JDBC driver, which Liquibase 5 no longer ships:

```bash
docker build -t jobdbmcp-liquibase db
```

The container joins the database container's network namespace, where connections from
`127.0.0.1` are trusted and no password is needed. Connection settings come from `.env`, which
is not committed; `.env.example` lists the variables.

```bash
# status of each changeset
docker run --rm --network container:postgres --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobdbmcp-liquibase status --verbose

# the SQL that would run, for review before applying
docker run --rm --network container:postgres --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobdbmcp-liquibase update-sql

docker run --rm --network container:postgres --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobdbmcp-liquibase update
```

Against a database that is not reachable over a trusted loopback, drop `--network
container:postgres`, point `LIQUIBASE_COMMAND_URL` at the host, and add
`LIQUIBASE_COMMAND_PASSWORD`.

## Development

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy
uv run pytest -q
```
