# Database Schema

PostgreSQL 18. Nothing in the schema is 18-specific, so an older major version works too.

All objects live in the `jobs` schema and are schema-qualified. Points in time are stored as
`timestamptz` in UTC. Terms follow [GLOSSARY.md](../GLOSSARY.md).

Agent configuration is not stored in the database. Scraping is run semi-manually, so crawl
status is not stored either.

## Table `jobs.organizations`

Employers and agencies, each under one canonical English name.

```sql
CREATE TABLE jobs.organizations (
    id   bigint GENERATED ALWAYS AS IDENTITY,
    name text   NOT NULL,

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX organizations_name_key ON jobs.organizations (lower(name));
```

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `bigint` identity | no | Surrogate primary key. |
| `name` | `text` | no | Canonical name, in English, as the organization calls itself. |

One table serves both roles: an organization is an employer or an agency by which column of a
job points to it, and the same organization may be the employer of one job and the agency of
another.

Names are unique ignoring case, so `GoodFriends` and `goodfriends` cannot both be stored. A plain
`UNIQUE` constraint compares case-sensitively, hence the unique index on `lower(name)`. Variants
that differ by more than case (`Check Point` and `Check Point Software`) are not caught by the
database; the agent looks organizations up before creating one.

## Table `jobs.vacancies`

Job postings collected from external sites.

```sql
CREATE TABLE jobs.vacancies (
    id               bigint      GENERATED ALWAYS AS IDENTITY,
    site             text        NOT NULL,
    pos_id           text        NOT NULL,
    url              text        NOT NULL,
    title            text        NOT NULL,
    company          text,
    location         text,
    description      text,
    downloaded_at    timestamptz NOT NULL DEFAULT now(),
    published_at     timestamptz,
    status           text        NOT NULL DEFAULT 'new',
    fit_score        smallint,
    interest_score   smallint,
    management_level text,
    work_mode        text,
    employer_id      bigint      REFERENCES jobs.organizations (id),
    agency_id        bigint      REFERENCES jobs.organizations (id),
    duplicate_of     bigint      REFERENCES jobs.vacancies (id),
    search_text      text,
    digest           text,

    PRIMARY KEY (id),
    UNIQUE (site, pos_id),
    CHECK (status IN ('new', 'unsuitable', 'low_priority', 'applied', 'closed', 'duplicate')),
    CHECK (fit_score BETWEEN 0 AND 100),
    CHECK (interest_score BETWEEN 0 AND 100),
    CHECK (management_level IN ('individual_contributor', 'tech_lead', 'team_lead', 'group_lead')),
    CHECK (work_mode IN ('onsite', 'hybrid', 'remote')),
    CHECK (length(digest) <= 1500),
    CONSTRAINT vacancies_duplicate_of_check CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL))
);

CREATE INDEX vacancies_search_text_fts_idx
    ON jobs.vacancies USING gin (to_tsvector('english', search_text));
```

The table took this shape in changesets `004-add-review-model`, `005-remap-review-statuses`, and
`006-drop-classification`.

| Column | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `bigint` identity | no | Surrogate primary key. The `job_id` the MCP API exposes. |
| `site` | `text` | no | Source site identifier, e.g. `linkedin`. |
| `pos_id` | `text` | no | Job identifier as used by the source site. Text, because sites use non-numeric ids. |
| `url` | `text` | no | Canonical URL of the posting. |
| `title` | `text` | no | Job title. |
| `company` | `text` | yes | Company name as published, not normalized. Nullable: agencies publish without naming the employer. |
| `location` | `text` | yes | Raw location string as published, not normalized. |
| `description` | `text` | yes | Full job description text, in Hebrew or English. |
| `downloaded_at` | `timestamptz` | no | When the record was first stored. Defaults to `now()`, which is the insert time by definition. |
| `published_at` | `timestamptz` | yes | Publication date reported by the site, unknown for some sources. |
| `status` | `text` | no | Outcome of the review: `new`, `unsuitable`, `low_priority`, `applied`, `closed`, `duplicate`. Defaults to `new`. |
| `fit_score` | `smallint` | yes | How well the CV matches what the job asks for, 0 to 100. `NULL` means not scored. |
| `interest_score` | `smallint` | yes | How attractive the job is to the candidate, 0 to 100. `NULL` means not scored. |
| `management_level` | `text` | yes | `individual_contributor`, `tech_lead`, `team_lead`, or `group_lead`. `NULL` means not determined. |
| `work_mode` | `text` | yes | `onsite`, `hybrid`, or `remote`. `NULL` means not determined. |
| `employer_id` | `bigint` | yes | Organization the hired person will work for. |
| `agency_id` | `bigint` | yes | Organization that published the job on the employer's behalf. `NULL` for a direct job. |
| `duplicate_of` | `bigint` | yes | The original job of a duplicate. Set exactly when `status` is `duplicate`. |
| `search_text` | `text` | yes | English text covering the employer, title, location, and description. The only column with full-text search. |
| `digest` | `text` | yes | Russian summary of the required and preferred qualifications, at most 1500 characters. |

### Logic

`(site, pos_id)` is the deduplication key, and it rejects rather than merges: `create_job` is a
plain `INSERT`, and a second attempt to store the same posting fails on the unique constraint.
The database is the arbiter of what is already known, so a re-parse cannot overwrite the title,
the description, or the review state of a job that is already stored. Changing a stored job is
an explicit `update_job`, which sets only the fields it is given and never `downloaded_at`.

`url` is deliberately not unique: the same posting is often reachable through several URLs,
while `(site, pos_id)` stays stable.

Everything the parser writes, `title` and `description` included, is text from a third party.
`search_text`, `digest`, and organization names are derived from it, so they are untrusted too.
The database stores it verbatim and the API declares it untrusted in its tool and schema
descriptions; see [docs/api.md](api.md).

#### Scores

The two scores answer different questions and are set independently: a job the candidate fits
but does not want differs from one the candidate wants but barely fits. Both are set by the
scoring agent and are meant to be recalculated, so a new score simply overwrites the previous
one. Management level and work mode feed into the scores rather than replace them: a
Group lead role simply scores low on interest.

#### Status

`status` records the candidate's review, not the life of the posting. Every value except `new` is
final: a reviewed job is not revisited. `applied` therefore stays even if the posting is later
withdrawn; it is what answers whether an employer has already been applied to. `closed` is set
only when the posting is found withdrawn at review time.

`duplicate` marks the same position stored twice, for example posted by the employer and by an
agency, or reposted under a new id. `duplicate_of` points to the original, and
`vacancies_duplicate_of_check` keeps the pair consistent. The original is never itself a
duplicate, so following the link takes one step. A check constraint cannot look at other rows,
so the repository enforces that rule: it rejects an original that is a duplicate, the job itself,
and making a job a duplicate while other jobs point to it.

`status`, the scores, the management level, and the work mode are restricted with `CHECK`
constraints rather than enum types, so adding a value is a plain constraint change instead of a
type change.

#### Employers and agencies

Whether a job is direct follows from the links: with an agency it is an agency job, with an
employer and no agency it is a direct job, with neither it is undetermined. An agency job whose
agency cannot be identified points to an organization named `Unknown agency`. `company` keeps the
name as published, so normalization can be checked against the source.

The links are filled in by the agent at review time, not by the parser, and the agent reuses an
existing organization before creating a new one.

#### Search and digest

Descriptions come in Hebrew and English. PostgreSQL has no Hebrew text search configuration,
and a single configuration cannot stem two languages, so `description` is not searched as is.
The agent stores in `search_text` an English text with the employer, the title, the location,
and the description, translated where needed, and full-text search runs over that column with
the `english` configuration.

`digest` holds a Russian summary of the required and preferred qualifications, five to seven
sentences in two fixed parts. The database cannot count sentences; the length check only stops
a whole description being pasted into it.

Both columns are nullable only until the agent fills them for the jobs stored before they
existed; `create_job` already requires them. A later changeset makes them `NOT NULL`.

#### Resuming a crawl

The date to resume scraping a site from is derived, not stored:

```sql
SELECT max(published_at) FROM jobs.vacancies WHERE site = $1;
```

Sites that do not report a publication date fall back to `max(downloaded_at)` for the same
site. Crawl status, start and finish times are not kept: scraping is semi-manual, and the
timestamps already on the vacancies answer the only question that gets asked.

### Constraints and indexes

Constraint names are left to PostgreSQL, except where a rollback has to refer to them.

- Primary key on `id`, with its implicit index.
- Unique on `(site, pos_id)`, with its implicit index. It rejects duplicate postings on save and
  serves the `job_exists` lookup.
- Foreign keys from `employer_id` and `agency_id` to organizations and from `duplicate_of` to
  vacancies. Rows are never deleted, so they need no `ON DELETE` action.
- GIN index `vacancies_search_text_fts_idx` on `to_tsvector('english', search_text)`. It serves
  `text_search`, whose query repeats that expression exactly; any other expression would not use
  the index. It is named explicitly so the rollback can drop it.
- Unique index `organizations_name_key` on `lower(name)`; see the organizations table.

The foreign key columns, the other `find_jobs` and `count_jobs` filters, and the `max()` query
above are not indexed. At the expected size, a few thousand rows, a sequential scan is cheaper
than maintaining more indexes. Revisit when the table grows or a query is measurably slow.

## Migration to the review model

The review model replaced a single `score`, the `interesting` and `not_interested` statuses, and
the `managerial`, `stack`, `requirements`, and `english_description` columns.

It takes three changesets instead of the usual one per task, because the status remapping is a
data change that has to run between two structural ones: after the status check accepts the new
values and before it stops accepting the old ones.

1. `004-add-review-model` adds organizations, the new columns and the search index, and widens
   the status check to both the old and the new values.
2. `005-remap-review-statuses` turns `not_interested` into `unsuitable` and `interesting` into
   `new`. It has no rollback: the former `interesting` jobs cannot be told apart from other new
   ones afterwards.
3. `006-drop-classification` drops the old columns and narrows the status check. Its rollback
   restores the columns empty.

Back up the database before applying them. Afterwards the agent fills `search_text` and `digest`
for every job, and the scores, organizations, management level, and work mode for the jobs that
still need them; only then can a further changeset make `search_text` and `digest` `NOT NULL`.

## Access

Roles and grants are managed outside this repository. The server connects as `jobs_rw`, which
has `SELECT`, `INSERT`, and `UPDATE` on both tables and `DELETE` on neither:

```sql
GRANT SELECT, INSERT, UPDATE ON jobs.vacancies, jobs.organizations TO jobs_rw;
```

Migrations need DDL rights and connect as a different role.

## Open questions

- `find_jobs` takes `company` and `location` filters as case-insensitive substrings. Whether
  `location` needs normalization as well depends on how filtering by it is used.
