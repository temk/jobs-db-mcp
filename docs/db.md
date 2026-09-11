# Database Schema

PostgreSQL 18. Nothing in the schema is 18-specific, so an older major version works too.

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
    managerial    boolean,
    stack         text,
    requirements  jsonb,
    english_description text,

    PRIMARY KEY (id),
    UNIQUE (site, pos_id),
    CHECK (score BETWEEN 0 AND 100),
    CHECK (status IN ('new', 'interesting', 'not_interested', 'applied')),
    CHECK (
        jsonb_typeof(requirements) = 'array'
        AND NOT jsonb_path_exists(requirements, '$[*] ? (@.type() != "string")')
    )
);

CREATE INDEX vacancies_english_description_fts_idx
    ON jobs.vacancies USING gin (to_tsvector('english', english_description));
```

The last four columns, their check, and the full-text index come from changeset
`002-add-vacancy-classification`.

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
| `downloaded_at` | `timestamptz` | no | When the record was first stored. Defaults to `now()`, which is the insert time by definition. Backs the `downloaded_after` filter. |
| `published_at` | `timestamptz` | yes | Publication date reported by the site, unknown for some sources. |
| `score` | `smallint` | yes | Relevance score, 0 to 100. `NULL` means not scored yet. |
| `status` | `text` | no | Review state: `new`, `interesting`, `not_interested`, `applied`. Defaults to `new`. |
| `managerial` | `boolean` | yes | Whether the role is a management one. `NULL` means not determined. |
| `stack` | `text` | yes | Main technology stack in free form, e.g. `java/spring`, `c++`. |
| `requirements` | `jsonb` | yes | Array of strings, trimmed, deduplicated, and sorted. `NULL` means not extracted yet; `[]` means none. |
| `english_description` | `text` | yes | English translation of `description`. The only column with full-text search. |

### Logic

`(site, pos_id)` is the deduplication key, and it rejects rather than merges: `create_job` is a
plain `INSERT`, and a second attempt to store the same posting fails on the unique constraint.
The database is the arbiter of what is already known, so a re-parse cannot overwrite the title,
the description, or the review state of a job that is already stored. Changing a stored job is
an explicit `update_job`, which sets only the fields it is given and never `downloaded_at`.

Everything the parser writes, `title` and `description` included, is text from a third party.
The database stores it verbatim and the API declares it untrusted in its tool and schema
descriptions; see [docs/api.md](api.md).

`url` is deliberately not unique: the same posting is often reachable through several URLs,
while `(site, pos_id)` stays stable.

`score` and `status` are review state, not parse output. The parser normally leaves them at
their defaults; scoring and review set them afterwards through `update_job`. Scores are meant
to be recalculated, so a new score simply overwrites the previous one.

Both `score` and `status` are restricted with `CHECK` constraints rather than enum types, so
widening the scale or adding a status is a plain constraint change instead of a type change.

`managerial`, `stack`, and `requirements` classify the posting. The parser may pass them to
`create_job`, and `update_job` fills them in or replaces them later, for example for jobs stored
before the columns existed. They are derived from third-party text, so they are untrusted like
the source fields. The database guarantees that `requirements` is an array of strings; the
repository keeps it sorted and free of duplicates, because a check constraint cannot compare
neighbouring elements.

Descriptions come in Hebrew and English. PostgreSQL has no Hebrew text search configuration,
and a single configuration cannot stem two languages, so `description` is not searched as is.
The agent stores an English translation in `english_description`, and full-text search runs
over that column with the `english` configuration. It is also derived text, so untrusted.

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
- Unique on `(site, pos_id)`, with its implicit index. It rejects duplicate postings on save and
  serves the `job_exists` lookup.
- Check that `requirements` is an array whose elements are all strings.
- GIN index `vacancies_english_description_fts_idx` on
  `to_tsvector('english', english_description)`. It serves `description_search`, whose query
  repeats that expression exactly; any other expression would not use the index. It is named
  explicitly so the rollback can drop it.

Other `find_jobs` and `count_jobs` filters and the `max()` query above are not indexed; the
`requirements` filter matches substrings inside array elements, which a GIN index would not
serve anyway. At the expected size, a few thousand rows, a sequential scan is cheaper than
maintaining more indexes. Revisit when the table grows or a query is measurably slow.

## Access

Roles and grants are managed outside this repository. The two deployments connect as different
roles:

- `jobs_rw`, used with `JOBDBMCP_ALLOW_WRITES`: `SELECT`, `INSERT`, and `UPDATE` on
  `jobs.vacancies`, no `DELETE`.
- `jobs_ro`, used without it: `SELECT` on `jobs.vacancies`, plus `UPDATE` on the `status`
  column alone, because `update_job_status` is available on the read-only deployment too:

```sql
GRANT UPDATE (status) ON jobs.vacancies TO jobs_ro;
```

The column-level grant keeps the database itself from accepting any other change through the
read-only role, whatever the server does.

## Open questions

- `find_jobs` takes `company` and `location` filters. Whether those match exactly or by
  substring decides whether they stay plain columns or need normalization later. The
  implementation matches them case-insensitively as substrings, like `title_contains`.
