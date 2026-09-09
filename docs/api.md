# JobDBMCP MCP API

Write operations are registered only when `JOBDBMCP_ALLOW_WRITES` is set in the server's
environment. Without it the server exposes the read operations alone, and the write tools do
not appear in `tools/list`.

## Write operations

### `save_job`
Store a new job, identified by `(site, pos_id)`.

Inputs:
- `site`
- `pos_id`
- `title`
- `company`
- `location`
- `url`
- `description`
- `published_at` — optional
- other source metadata — optional

Returns:
- internal `job_id`

Fails if `(site, pos_id)` is already stored. A known job is never overwritten, so review state
cannot be lost to a re-parse.

---

### `set_job_status`
Change the user's status for a job.

Inputs:
- `job_id`
- `status`

Possible statuses initially:
- `new`
- `interesting`
- `not_interested`
- `applied`

Do not hard-code this as a PostgreSQL enum unless needed.

---

### `set_job_score`
Set or replace the calculated relevance score.

Inputs:
- `job_id`
- `score` — 0 to 100

Scores can be recalculated: the operation overwrites any previous value.

---

## Read operations

### `job_exists`
Check whether a posting is already stored.

Inputs:
- `site`
- `pos_id`

Returns:
- whether it exists
- internal `job_id` when it does

Intended as the check before `save_job`.

---

### `get_job`
Get one job by internal `job_id`.

Inputs:
- `job_id`

Returns the full stored job, current status, and score.

---

### `find_jobs`
Main query interface for browsing and filtering jobs.

All filters are optional.

Inputs:
- `site`
- `status`
- `min_score`
- `max_score`
- `seen_after`
- `published_after`
- `company`
- `location`
- `title_contains`
- `limit`
- `offset`
- `order_by`

Initial supported ordering:
- `published` — newest publication date first
- `downloaded` — most recently downloaded first
- `score` — highest score first

Crawl state is not stored. The date to resume scraping a site from comes from this tool:
`find_jobs(site=..., order_by="published", limit=1)` returns the newest posting already known
for that site.

Example:

```text
find_jobs(
    min_score=75,
    seen_after="2026-09-01",
    status="new",
    order_by="score",
    limit=50
)
```

---

## Initial MCP tool set

```text
save_job         write, gated
set_job_status   write, gated
set_job_score    write, gated

job_exists
get_job
find_jobs
```

The MCP server should not expose arbitrary SQL.