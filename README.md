# JobDBMCP

MCP server providing controlled access to the job-search PostgreSQL database.

The server exposes domain-specific MCP tools for storing, finding, and reviewing job postings
over Streamable HTTP. Arbitrary SQL execution is intentionally not exposed.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 18
- Docker, to build and run the images

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
| `JOBDBMCP_ALLOW_WRITES` | Register the write tools. Unset means a read-only server that can still change a job's status. |
| `JOBDBMCP_HOST` | Bind address, `127.0.0.1` by default, `0.0.0.0` in the image. |
| `JOBDBMCP_PORT` | Listen port, `8000` by default. |
| `LIQUIBASE_COMMAND_*` | Used only when applying migrations, see below. |

## Running

The server speaks MCP over Streamable HTTP at `/mcp`.

```bash
uv run jobs-db-mcp
```

In Docker:

```bash
docker build -t jobs-db-mcp .
docker run --rm --env-file .env jobs-db-mcp
```

The container needs network access to the database.

Always registered: `job_exists`, `get_job`, `find_jobs`, `count_jobs`, `update_job_status`.
Write tools: `create_job`, `update_job`. They are registered only when
`JOBDBMCP_ALLOW_WRITES` is set; without it they are absent from `tools/list` entirely, so a
read-only deployment does not advertise what it will not do. It can still change a job's
status, which needs `UPDATE (status)` for its database role; see [docs/db.md](docs/db.md).
See [docs/api.md](docs/api.md) for their inputs and outputs.

## Database

See [docs/db.md](docs/db.md) for the schema.

Migrations are Liquibase formatted SQL changesets under `db/changelog/`. The runner image adds
the PostgreSQL JDBC driver, which Liquibase 5 no longer ships:

```bash
docker build -t jobs-db-mcp-liquibase db
```

Connection settings come from `.env`: `LIQUIBASE_COMMAND_URL`, `LIQUIBASE_COMMAND_USERNAME`,
`LIQUIBASE_COMMAND_PASSWORD`, and `LIQUIBASE_COMMAND_CHANGELOG_FILE=changelog-master.yml`.
Migrations need DDL rights, so they connect as a different role than the server does.

```bash
# status of each changeset
docker run --rm --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobs-db-mcp-liquibase status --verbose

# the SQL that would run, for review before applying
docker run --rm --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobs-db-mcp-liquibase update-sql

docker run --rm --env-file .env \
  -v ./db/changelog:/liquibase/changelog -w /liquibase/changelog \
  jobs-db-mcp-liquibase update
```

## Development

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy
uv run pytest -q
```
