# Database Schema

Target version PostgreSQL 18. Development runs against the local PostgreSQL 17.2 container;
nothing in the schema is 18-specific.

All objects live in the `jobs` schema and are schema-qualified. Points in time are stored as
`timestamptz` in UTC.

Agent configuration is not stored in the database. Scraping is run semi-manually, so crawl
status is not stored either.

## Table `jobs.vacancies`

Job postings collected from external sites. The only table.

```sql
CREATE TABLE jobs.vacancies (
    id            bigint      GENERATED ALWAYS AS IDENTITY,
    site          text        NOT NULL,
    pos_id        text        NOT NULL,
    url           text        NOT NULL,
    title         text        NOT NULL,
    company       text,
    location      text,
    description   text,
    downloaded_at timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    score         smallint,
    status        text        NOT NULL DEFAULT 'new',

    PRIMARY KEY (id),
    UNIQUE (site, pos_id),
    CHECK (score BETWEEN 0 AND 100),
    CHECK (status IN ('new', 'interesting', 'not_interested', 'applied'))
);
```

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `bigint` identity | no | Surrogate primary key. The `job_id` the MCP API exposes. |
| `site` | `text` | no | Source site identifier, e.g. `linkedin`. |
| `pos_id` | `text` | no | Job identifier as used by the source site. Text, because sites use non-numeric ids. |
| `url` | `text` | no | Canonical URL of the posting. |
| `title` | `text` | no | Job title. |
| `company` | `text` | yes | Employer name. Nullable: agencies publish without naming the client. |
| `location` | `text` | yes | Raw location string as published, not normalized. |
| `description` | `text` | yes | Full job description text. |
| `downloaded_at` | `timestamptz` | no | When the record was first stored. Defaults to `now()`, which is the insert time by definition. Backs the `seen_after` filter. |
| `published_at` | `timestamptz` | yes | Publication date reported by the site, unknown for some sources. |
| `score` | `smallint` | yes | Relevance score, 0 to 100. `NULL` means not scored yet. |
| `status` | `text` | no | Review state: `new`, `interesting`, `not_interested`, `applied`. Defaults to `new`. |

### Logic

`(site, pos_id)` is the deduplication key, and it rejects rather than merges: `save_job` is a
plain `INSERT`, and a second attempt to store the same posting fails on the unique constraint.
The database is the arbiter of what is already known, so a re-parse cannot overwrite the title,
the description, or the review state of a job that is already stored.

`url` is deliberately not unique: the same posting is often reachable through several URLs,
while `(site, pos_id)` stays stable.

`score` and `status` are review state, not parse output. The parser only ever writes their
defaults; the scoring and review tools own them afterwards. Scores are meant to be
recalculated, so `set_job_score` overwrites any previous value.

Both `score` and `status` are restricted with `CHECK` constraints rather than enum types, so
widening the scale or adding a status is a plain constraint change instead of a type change.

The date to resume scraping a site from is derived, not stored:

```sql
SELECT max(published_at) FROM jobs.vacancies WHERE site = $1;
```

Sites that do not report a publication date fall back to `max(downloaded_at)` for the same
site. Crawl status, start and finish times are not kept: scraping is semi-manual, and the
timestamps already on the vacancies answer the only question that gets asked.

### Constraints and indexes

Constraint names are left to PostgreSQL; nothing in the application depends on them.

- Primary key on `id`, with its implicit index.
- Unique on `(site, pos_id)`, with its implicit index. This is the only index besides the
  primary key. It rejects duplicate postings on save and serves the `job_exists` lookup.

`find_jobs` filters on `site`, `status`, `score`, `downloaded_at`, and `published_at`, and the
`max()` query above scans one site's rows. None of that is indexed. At the expected size, a few
thousand rows, a sequential scan is cheaper than maintaining more indexes. Revisit when the
table grows or a query is measurably slow.

## Open questions

- `find_jobs` takes `company` and `location` filters. Whether those match exactly or by
  substring decides whether they stay plain columns or need normalization later. The
  implementation matches them case-insensitively as substrings, like `title_contains`.
