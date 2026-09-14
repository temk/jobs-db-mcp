# JobDBMCP MCP API

Write operations are registered only when `JOBDBMCP_ALLOW_WRITES` is set in the server's
environment. Without it the server exposes the read operations and `update_job_status`, and the
other write tools do not appear in `tools/list`.

## The `Job` object

`create_job` takes a `Job`, and `create_job`, `update_job`, `get_job`, and `find_jobs` return
it.

| Field | Required | Description |
| --- | --- | --- |
| `id` | no | Internal job id. Empty on `create_job`. |
| `site` | yes | Source site identifier, e.g. `linkedin`. |
| `pos_id` | yes | Job identifier as used by the source site. |
| `url` | yes | URL of the posting. |
| `title` | yes | Job title. |
| `company` | no | Employer name. |
| `location` | no | Location as published. |
| `description` | no | Full job description. |
| `english_description` | no | English translation of `description`. Searched by `description_search`. |
| `published_at` | no | Publication time reported by the site. |
| `downloaded_at` | no | When the job was first stored. Set by the database; ignored on input. |
| `score` | no | Relevance score, 0 to 100. Empty means not scored. |
| `status` | no | `new`, `interesting`, `not_interested`, `applied`, or `closed`. Defaults to `new`. |
| `managerial` | no | Whether the role is a management one. |
| `stack` | no | Main technology stack, e.g. `java/spring`. |
| `requirements` | no | List of strings, stored trimmed, deduplicated, and sorted. |

## Untrusted content

Every job field that originates from a source site (`site`, `pos_id`, `url`, `title`,
`company`, `location`, `description`) is text written by whoever posted the vacancy, and
`english_description`, `stack`, and `requirements` are derived from it. It is returned verbatim.

Responses carry no marker. The warning is part of what a client sees when it connects: the
server `instructions` at `initialize`, the descriptions of `get_job` and `find_jobs` in
`tools/list`, and the description of the `Job` schema, which appears in their output schemas
and in the input schema of `create_job`.

This is a mitigation for prompt injection, not a security boundary: it relies on the consuming
model honouring it. The actual boundary is that SQL is parameterised, no arbitrary SQL is
exposed, and write tools are absent unless `JOBDBMCP_ALLOW_WRITES` is set, so injected text
cannot reach the database whatever it says. The one exception, `update_job_status`, stores one
of four fixed values: injected text could at worst get a job's status changed.

## Write operations

### `create_job`
Store a new job, identified by `(site, pos_id)`.

Inputs:
- `job` — a `Job` with an empty `id`

Returns the stored `Job`, with `id` and `downloaded_at` filled in.

Fails if `(site, pos_id)` is already stored. A known job is never overwritten by a re-parse, so
review state cannot be lost that way.

---

### `update_job`
Change some fields of a stored job.

Inputs:
- `job_id`
- `fields` — mapping of field name to new value, e.g. `{"stack": "java/spring", "description": null}`

Only the listed fields change; the rest keep their stored value. `null` clears an optional
field. Any `Job` field except `id` and `downloaded_at` can be listed; unknown names are
rejected, and so is `null` for `site`, `pos_id`, `url`, `title`, and `status`. At least one field
is required. `requirements` replaces the whole list.

Returns the stored `Job`. Fails if no job has that `id`, or if the new `(site, pos_id)` belongs
to another job.

---

### `update_job_status`
Set the review status of a job. Registered on every deployment, including one without
`JOBDBMCP_ALLOW_WRITES`, so jobs can be reviewed through a read-only server.

Inputs:
- `job_id`
- `status` — `new`, `interesting`, `not_interested`, `applied`, or `closed`

Returns the stored `Job`. Fails if no job has that `id`.

The database role of a read-only deployment needs `UPDATE` on the `status` column for this
tool to work; see [docs/db.md](db.md).

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

Intended as the check before `create_job`.

---

### `get_job`
Get one job by internal `job_id`.

Inputs:
- `job_id`

Returns the `Job`.

---

### `find_jobs`
Main query interface for browsing and filtering jobs.

Returns `{jobs, page, page_size, total}`: one page of full `Job` objects and the number of
matching jobs across all pages.

All filters are optional and combine with AND. `company`, `location`, `title_contains`, and
`stack` match case-insensitive substrings. Each entry of `requirements` must match some stored
requirement as a case-insensitive substring, so `["kafka", "java"]` finds jobs that mention both.

`description_search` is an English full-text search over `english_description`, in web search
syntax: plain words must all occur (after stemming, so `developers` finds `developer`),
`"quoted phrases"` match as phrases, `or` separates alternatives, and `-word` excludes. Jobs
without `english_description` never match it.

Inputs:
- `site`
- `status`
- `min_score`
- `max_score`
- `downloaded_after` — stored in the database at or after this moment
- `published_after` — published by the site at or after this moment
- `company`
- `location`
- `title_contains`
- `managerial`
- `stack`
- `requirements`
- `description_search`
- `order_by`
- `page` — numbered from 1, defaults to 1
- `page_size` — 1 to 200, defaults to 50

Initial supported ordering:
- `published` — newest publication date first
- `downloaded` — most recently downloaded first
- `score` — highest score first

Crawl state is not stored. The date to resume scraping a site from comes from this tool:
`find_jobs(site=..., order_by="published", page_size=1)` returns the newest posting already
known for that site.

Example:

```text
find_jobs(
    min_score=75,
    downloaded_after="2026-09-01",
    status="new",
    order_by="score",
    page=2,
    page_size=20
)
```

---

### `count_jobs`
Count the jobs `find_jobs` would match, without fetching them.

Inputs: the same filters as `find_jobs`, with the same matching rules. No `order_by`, `page`,
or `page_size`.

Returns the number of matching jobs.

`job_exists` and `get_job` look a job up by a unique key, so they have no counting variant:
the answer is 0 or 1, which `job_exists` already gives.

---

## Initial MCP tool set

```text
create_job       write, gated
update_job       write, gated
update_job_status  write, always registered

job_exists
get_job
find_jobs
count_jobs
```

The MCP server should not expose arbitrary SQL.
