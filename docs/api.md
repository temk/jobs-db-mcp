# JobDBMCP MCP API

One local server; every tool is always registered. Terms follow [GLOSSARY.md](../GLOSSARY.md).

## The `Job` object

`create_job` takes a `Job`, and `create_job`, `update_job`, and `get_job` return it.

| Field | Required | Description |
| --- | --- | --- |
| `id` | no | Internal job id. Empty on `create_job`. |
| `site` | yes | Source site identifier, e.g. `linkedin`. |
| `pos_id` | yes | Job identifier as used by the source site. |
| `url` | yes | URL of the posting. |
| `title` | yes | Job title. |
| `company` | no | Company name as published. |
| `location` | no | Location as published. |
| `description` | no | Full job description. |
| `search_text` | on create | English text covering the employer, title, location, and description. Searched by `text_search`. |
| `digest` | on create | Russian summary of the qualifications, five to seven sentences, at most 1500 characters: `Обязательно: ...` with the required ones, then `Желательно: ...` with the preferred ones, omitted when there are none. |
| `published_at` | no | Publication time reported by the site. |
| `downloaded_at` | no | When the job was first stored. Set by the database; ignored on input. |
| `fit_score` | no | How well the CV matches what the job asks for, 0 to 100. Empty means not scored. |
| `interest_score` | no | How attractive the job is to the candidate, 0 to 100. Empty means not scored. |
| `management_level` | no | `individual_contributor`, `tech_lead`, `team_lead`, or `group_lead`. An ambiguous lead role is `tech_lead`. |
| `work_mode` | no | `onsite`, `hybrid`, or `remote`. |
| `employer_id` | no | Organization the hired person will work for. |
| `agency_id` | no | Organization that published the job on the employer's behalf. Empty for a direct job. |
| `employer` | no | Name of `employer_id`. Read-only. |
| `agency` | no | Name of `agency_id`. Read-only. |
| `status` | no | `new`, `unsuitable`, `low_priority`, `applied`, `closed`, or `duplicate`. Defaults to `new`. |
| `duplicate_of` | no | Id of the original job. Set exactly when `status` is `duplicate`. |

## The `JobCard` object

`find_jobs` returns cards: the fields needed to decide on a job, with the `digest` instead of the
full texts. Fields: `id`, `title`, `company`, `employer`, `agency`, `management_level`,
`work_mode`, `fit_score`, `interest_score`, `digest`, `location`, `status`, `published_at`,
`url`, `duplicate_of`. `get_job` returns the whole job.

## The `Organization` object

An employer or an agency: `id` and `name`, the canonical English name.

## Untrusted content

Every job field that originates from a source site (`site`, `pos_id`, `url`, `title`,
`company`, `location`, `description`) is text written by whoever posted the vacancy, and
`search_text`, `digest`, and organization names are derived from it. It is returned verbatim.

Responses carry no marker. The warning is part of what a client sees when it connects: the
server `instructions` at `initialize`, the descriptions of `get_job`, `find_jobs`,
`find_organizations`, and `create_organization` in `tools/list`, and the descriptions of the
`Job`, `JobCard`, and `Organization` schemas, which appear in their output schemas and in the
input schema of `create_job`.

This is a mitigation for prompt injection, not a security boundary: it relies on the consuming
model honouring it. The actual boundary is that SQL is parameterised, no arbitrary SQL is
exposed, and the database role cannot delete anything, so injected text can at worst change
stored fields, never remove jobs.

## Write operations

### `create_job`
Store a new job, identified by `(site, pos_id)`.

Inputs:
- `job`: a `Job` with an empty `id` and with `search_text` and `digest`

Returns the stored `Job`, with `id` and `downloaded_at` filled in.

Fails if `(site, pos_id)` is already stored. A known job is never overwritten by a re-parse, so
review state cannot be lost that way. Also fails if `employer_id` or `agency_id` names an
unknown organization, or if `duplicate_of` names a job that is unknown or itself a duplicate.

---

### `update_job`
Change some fields of a stored job.

Inputs:
- `job_id`
- `fields`: mapping of field name to new value, e.g. `{"fit_score": 80, "description": null}`

Only the listed fields change; the rest keep their stored value. `null` clears an optional
field. Any `Job` field except `id`, `downloaded_at`, `employer`, and `agency` can be listed;
unknown names are rejected, and so is `null` for `site`, `pos_id`, `url`, `title`, `status`,
`search_text`, and `digest`.
At least one field is required.

`status` and `duplicate_of` change together. `duplicate_of` is accepted only alongside `status`:
`{"status": "duplicate", "duplicate_of": 12}` marks a duplicate, and any other status clears
`duplicate_of`. The original must exist, must not be the job itself, and must not be a
duplicate; a job that other jobs point to cannot become a duplicate.

Returns the stored `Job`. Fails if no job has that `id`, if the new `(site, pos_id)` belongs
to another job, or if an organization id is unknown.

---

### `create_organization`
Store an organization under its canonical English name, as it calls itself.

Inputs:
- `name`

Returns the `Organization`. If a stored name differs only in case, that organization is
returned and nothing is created, so a retry is harmless. Look the name up with
`find_organizations` first: variants that differ by more than case are not caught.

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

Returns `{jobs, page, page_size, total}`: one page of `JobCard` objects and the number of
matching jobs across all pages.

All filters are optional and combine with AND.

- `status`, `management_level`, and `work_mode` take non-empty lists and match any of the values.
- `min_fit_score` and `min_interest_score` are inclusive lower bounds; unscored jobs never match.
- `company` (the name as published), `location`, and `title_contains` match case-insensitive
  substrings.
- `employer_id` and `agency_id` match organizations by id.
- `direct`: `true` selects jobs with an employer and no agency, `false` jobs with an agency.
- `scored`: `false` selects jobs missing either score, `true` jobs with both.
- `text_search` is an English full-text search over `search_text`, in web search syntax: plain
  words must all occur (after stemming, so `developers` finds `developer`), `"quoted phrases"`
  match as phrases, `or` separates alternatives, and `-word` excludes. Jobs without
  `search_text` never match it.

Inputs:
- `site`
- `status`
- `min_fit_score`
- `min_interest_score`
- `downloaded_after`: stored in the database at or after this moment
- `published_after`: published by the site at or after this moment
- `company`
- `location`
- `title_contains`
- `management_level`
- `work_mode`
- `employer_id`
- `agency_id`
- `direct`
- `scored`
- `text_search`
- `order_by`
- `page`: numbered from 1, defaults to 1
- `page_size`: 1 to 200, defaults to 50

Ordering:
- `published`: newest publication date first
- `downloaded`: most recently downloaded first
- `fit_score`: highest Fit score first, unscored last
- `interest_score`: highest Interest score first, unscored last

Crawl state is not stored. The date to resume scraping a site from comes from this tool:
`find_jobs(site=..., order_by="published", page_size=1)` returns the newest posting already
known for that site.

Example, the ten best new direct jobs by fit among those interesting enough:

```text
find_jobs(
    status=["new"],
    min_interest_score=60,
    direct=true,
    order_by="fit_score",
    page_size=10
)
```

---

### `count_jobs`
Count the jobs `find_jobs` would match, without fetching them.

Inputs: the same filters as `find_jobs`, with the same matching rules. No `order_by`, `page`,
or `page_size`.

Returns the number of matching jobs. Whether an employer has already been applied to is
`count_jobs(employer_id=..., status=["applied"])`.

`job_exists` and `get_job` look a job up by a unique key, so they have no counting variant:
the answer is 0 or 1, which `job_exists` already gives.

---

### `find_organizations`
List stored organizations, employers and agencies alike.

Inputs:
- `name_contains`: optional case-insensitive substring

Returns the matching `Organization` objects ordered by name.

---

## Tool set

```text
create_job
update_job
create_organization

job_exists
get_job
find_jobs
count_jobs
find_organizations
```

The MCP server does not expose arbitrary SQL.
