# JobDBMCP

MCP server providing controlled access to the job-search PostgreSQL database.

## Stack
- Python
- MCP Python SDK / FastMCP
- PostgreSQL
- Docker
- Streamable HTTP

## Responsibilities
The server exposes domain-specific MCP tools. Do not expose arbitrary SQL execution.

Initial tools:
- save a job
- check whether a job already exists
- get the last successful parse time for a site
- update site parse status/time

Later, the server will also provide tools for searching, filtering, ranking, and reviewing stored jobs.

## Development rules
- Keep the implementation simple; do not introduce abstractions before they are needed.
- Prefer async APIs for database and MCP operations.
- Validate MCP inputs with typed models.
- Keep SQL in the repository/database layer, not in MCP handlers.
- Use PostgreSQL constraints for data integrity and deduplication where appropriate.
- Database credentials and other secrets must come from environment variables.
- Do not commit secrets or `.env` files.
- The application must run in Docker.
- Add dependencies only when they provide clear value.
- Do not add frameworks beyond what is required for MCP, PostgreSQL, configuration, and migrations.
- Before changing database schema, explain the proposed change.
- Do not create indexes unless explicitly requested or clearly necessary; report any index you add.

## Migrations

- All schema changes go through Liquibase. No manual DDL against a deployed database.
- One changeset per file in `db/changelog/changesets/`, named `NNN-<action>.sql`, numbered in
  application order. The root changelog only includes them.
- The root changelog is YAML because `include`/`includeAll` inside a formatted SQL changelog is
  license-gated in Liquibase 5 OSS. Changesets themselves stay formatted SQL.
- All schema changes belonging to one task go into a single changeset.
- Never edit an applied changeset; Liquibase checksums them. Fix forward with a new changeset.
- Every changeset carries a `--rollback`. Document changes that cannot be rolled back safely.
- Keep seed and data migrations in their own changesets, separate from structural changes.
- Review `update-sql` output before running `update`.

## Project structure
```
src/jobdbmcp/
    config.py       environment-backed settings
    db.py           asyncpg pool lifespan
    models.py       typed MCP inputs and outputs
    repository.py   all SQL lives here
    server.py       MCP tools, thin wrappers over the repository
db/changelog/       Liquibase changesets
docs/db.md          schema and its logic
docs/api.md         MCP tool contract
tests/              pytest suite
```

The application connects as the unprivileged `jobdb` role, which has SELECT, INSERT, and
UPDATE on `jobs.vacancies` and no DELETE. Migrations connect as the superuser instead.

## Commands
```bash
uv sync                     # install dependencies
uv run ruff format .        # format
uv run ruff check . --fix   # lint
uv run mypy                 # type check
uv run pytest -q            # tests
```

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues of `temk/jobs-db-mcp`. See `docs/agents/issue-tracker.md`.

### Triage labels

The default five triage labels are used as-is. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
