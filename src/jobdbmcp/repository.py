import asyncpg
from typing import Any
from datetime import datetime
from dataclasses import dataclass

from jobdbmcp.models import (
    Job,
    JobCard,
    OrderBy,
    WorkMode,
    JobStatus,
    Organization,
    ManagementLevel,
    validate_job_fields,
    check_duplicate_pair,
)


class DuplicateJobError(Exception):
    """Raised when a job with the same (site, pos_id) is already stored."""

    def __init__(self, site: str, pos_id: str) -> None:
        super().__init__(f"job {pos_id} from {site} is already stored")


@dataclass
class JobFilters:
    site: str | None = None
    status: list[JobStatus] | None = None
    min_fit_score: int | None = None
    min_interest_score: int | None = None
    downloaded_after: datetime | None = None
    published_after: datetime | None = None
    company: str | None = None
    location: str | None = None
    title_contains: str | None = None
    management_level: list[ManagementLevel] | None = None
    work_mode: list[WorkMode] | None = None
    employer_id: int | None = None
    agency_id: int | None = None
    direct: bool | None = None
    scored: bool | None = None
    text_search: str | None = None


# Jobs are always read as `v` joined with the names of their organizations.
JOB_JOINS = """
    LEFT JOIN jobs.organizations e ON e.id = v.employer_id
    LEFT JOIN jobs.organizations a ON a.id = v.agency_id
"""

JOB_COLUMNS = """
    v.id, v.site, v.pos_id, v.url, v.title, v.company, v.location, v.description, v.search_text, v.digest,
    v.published_at, v.downloaded_at, v.fit_score, v.interest_score, v.management_level, v.work_mode,
    v.employer_id, v.agency_id, e.name AS employer, a.name AS agency, v.status, v.duplicate_of
"""

CARD_COLUMNS = """
    v.id, v.title, v.company, e.name AS employer, a.name AS agency, v.management_level, v.work_mode,
    v.fit_score, v.interest_score, v.digest, v.location, v.status, v.published_at, v.url, v.duplicate_of
"""

ORDER_BY_SQL: dict[OrderBy, str] = {
    "published": "v.published_at DESC NULLS LAST, v.id DESC",
    "downloaded": "v.downloaded_at DESC, v.id DESC",
    "fit_score": "v.fit_score DESC NULLS LAST, v.id DESC",
    "interest_score": "v.interest_score DESC NULLS LAST, v.id DESC",
}


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_filters(filters: JobFilters) -> tuple[str, list[Any]]:
    """Build the WHERE clause and its parameters. Empty clause when no filter is set."""
    conditions: list[str] = []
    params: list[Any] = []

    def add(condition_template: str, value: Any) -> None:
        params.append(value)
        conditions.append(condition_template.format(n=len(params)))

    if filters.site is not None:
        add("v.site = ${n}", filters.site)
    if filters.status is not None:
        add("v.status = ANY(${n})", filters.status)
    if filters.min_fit_score is not None:
        add("v.fit_score >= ${n}", filters.min_fit_score)
    if filters.min_interest_score is not None:
        add("v.interest_score >= ${n}", filters.min_interest_score)
    if filters.downloaded_after is not None:
        add("v.downloaded_at >= ${n}", filters.downloaded_after)
    if filters.published_after is not None:
        add("v.published_at >= ${n}", filters.published_after)
    if filters.company is not None:
        add("v.company ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.company)}%")
    if filters.location is not None:
        add("v.location ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.location)}%")
    if filters.title_contains is not None:
        add("v.title ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.title_contains)}%")
    if filters.management_level is not None:
        add("v.management_level = ANY(${n})", filters.management_level)
    if filters.work_mode is not None:
        add("v.work_mode = ANY(${n})", filters.work_mode)
    if filters.employer_id is not None:
        add("v.employer_id = ${n}", filters.employer_id)
    if filters.agency_id is not None:
        add("v.agency_id = ${n}", filters.agency_id)
    if filters.direct is True:
        conditions.append("v.agency_id IS NULL AND v.employer_id IS NOT NULL")
    if filters.direct is False:
        conditions.append("v.agency_id IS NOT NULL")
    if filters.scored is True:
        conditions.append("v.fit_score IS NOT NULL AND v.interest_score IS NOT NULL")
    if filters.scored is False:
        conditions.append("(v.fit_score IS NULL OR v.interest_score IS NULL)")
    if filters.text_search is not None:
        # Must match the expression of vacancies_search_text_fts_idx to use the index.
        add("to_tsvector('english', v.search_text) @@ websearch_to_tsquery('english', ${n})", filters.text_search)

    if not conditions:
        return "", params
    return "WHERE " + " AND ".join(conditions), params


async def ensure_original(connection: asyncpg.Connection, original_id: int, job_id: int | None = None) -> None:
    """Reject an original that would make a chain of duplicates: a check constraint cannot see other rows.

    Call inside the transaction that writes duplicate_of. Both rows stay locked until it ends, so two
    concurrent updates cannot each make the other's original a duplicate.
    """
    if original_id == job_id:
        raise ValueError(f"job {job_id} cannot be a duplicate of itself")
    # Locking in id order keeps two such updates from deadlocking on each other's rows.
    rows = await connection.fetch(
        "SELECT id, status FROM jobs.vacancies WHERE id = ANY($1::bigint[]) ORDER BY id FOR UPDATE",
        [original_id] if job_id is None else sorted([original_id, job_id]),
    )
    status = {row["id"]: row["status"] for row in rows}.get(original_id)
    if status is None:
        raise ValueError(f"original job {original_id} not found")
    if status == "duplicate":
        raise ValueError(f"job {original_id} is itself a duplicate; point to its original instead")
    if job_id is not None and await connection.fetchval("SELECT 1 FROM jobs.vacancies WHERE duplicate_of = $1", job_id):
        raise ValueError(f"other jobs are duplicates of job {job_id}, so it cannot become a duplicate")


def foreign_key_error(exc: asyncpg.ForeignKeyViolationError) -> ValueError:
    if exc.constraint_name == "vacancies_duplicate_of_fkey":
        return ValueError("duplicate_of names an unknown job")
    return ValueError("employer_id or agency_id names an unknown organization")


async def create_job(pool: asyncpg.Pool, job: Job) -> Job:
    """Insert a job. downloaded_at is set by the database.

    Raises DuplicateJobError when (site, pos_id) is already stored: a known job is never
    silently overwritten, so review state cannot be lost to a re-parse.
    """
    if job.id is not None:
        raise ValueError("id must be empty when creating a job")
    if job.search_text is None or job.digest is None:
        raise ValueError("search_text and digest are required when creating a job")
    try:
        async with pool.acquire() as connection, connection.transaction():
            if job.duplicate_of is not None:
                await ensure_original(connection, job.duplicate_of)
            row = await connection.fetchrow(
                f"""
            WITH v AS (
                INSERT INTO jobs.vacancies (
                    site, pos_id, url, title, company, location, description, search_text, digest, published_at,
                    fit_score, interest_score, management_level, work_mode, employer_id, agency_id, status,
                    duplicate_of
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                RETURNING *
            )
            SELECT {JOB_COLUMNS} FROM v {JOB_JOINS}
            """,
                job.site,
                job.pos_id,
                job.url,
                job.title,
                job.company,
                job.location,
                job.description,
                job.search_text,
                job.digest,
                job.published_at,
                job.fit_score,
                job.interest_score,
                job.management_level,
                job.work_mode,
                job.employer_id,
                job.agency_id,
                job.status,
                job.duplicate_of,
            )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateJobError(job.site, job.pos_id) from exc
    except asyncpg.ForeignKeyViolationError as exc:
        raise foreign_key_error(exc) from exc
    return Job(**dict(row))


def prepare_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate the fields of an update and apply the rules that span several fields.

    status and duplicate_of change together: duplicate_of needs status alongside it, and a status
    other than duplicate clears duplicate_of. search_text and digest are required on create, so an
    update cannot clear them either.
    """
    values = validate_job_fields(fields)
    for name in ("search_text", "digest"):
        if name in values and values[name] is None:
            raise ValueError(f"{name} cannot be cleared")
    if "duplicate_of" in values and "status" not in values:
        raise ValueError("duplicate_of can only be changed together with status")
    if "status" in values:
        values.setdefault("duplicate_of", None)
        check_duplicate_pair(values["status"], values["duplicate_of"])
    return values


def build_assignments(values: dict[str, Any]) -> tuple[str, list[Any]]:
    """Build the SET list for fields checked by prepare_fields, numbered from $2; $1 is the job id."""
    # validate_job_fields admits only Job field names, so they are safe to use as column names.
    assignments = ", ".join(f"{column} = ${n}" for n, column in enumerate(values, start=2))
    return assignments, list(values.values())


async def update_job(pool: asyncpg.Pool, job_id: int, fields: dict[str, Any]) -> Job | None:
    """Change the given fields of a job and leave the rest as stored. None when the job is unknown."""
    values = prepare_fields(fields)
    assignments, params = build_assignments(values)
    original_id = values.get("duplicate_of")
    try:
        async with pool.acquire() as connection, connection.transaction():
            if original_id is not None:
                await ensure_original(connection, original_id, job_id)
            row = await connection.fetchrow(
                f"""
                WITH v AS (UPDATE jobs.vacancies SET {assignments} WHERE id = $1 RETURNING *)
                SELECT {JOB_COLUMNS} FROM v {JOB_JOINS}
                """,
                job_id,
                *params,
            )
    except asyncpg.UniqueViolationError as exc:
        raise ValueError(f"job {job_id} would get the (site, pos_id) of another stored job") from exc
    except asyncpg.ForeignKeyViolationError as exc:
        raise foreign_key_error(exc) from exc
    return Job(**dict(row)) if row is not None else None


async def find_job_id(pool: asyncpg.Pool, site: str, pos_id: str) -> int | None:
    """Look up a job by its source identity. Served by the unique index on (site, pos_id)."""
    row = await pool.fetchrow(
        "SELECT id FROM jobs.vacancies WHERE site = $1 AND pos_id = $2",
        site,
        pos_id,
    )
    return row["id"] if row is not None else None


async def get_job(pool: asyncpg.Pool, job_id: int) -> Job | None:
    row = await pool.fetchrow(f"SELECT {JOB_COLUMNS} FROM jobs.vacancies v {JOB_JOINS} WHERE v.id = $1", job_id)
    return Job(**dict(row)) if row is not None else None


async def find_jobs(
    pool: asyncpg.Pool,
    filters: JobFilters,
    order_by: OrderBy = "published",
    page: int = 1,
    page_size: int = 50,
) -> list[JobCard]:
    """Return one page of matching jobs as cards. Pages are numbered from 1."""
    where, params = build_filters(filters)
    rows = await pool.fetch(
        f"""
        SELECT {CARD_COLUMNS}
        FROM jobs.vacancies v {JOB_JOINS}
        {where}
        ORDER BY {ORDER_BY_SQL[order_by]}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        page_size,
        (page - 1) * page_size,
    )
    return [JobCard(**dict(row)) for row in rows]


async def count_jobs(pool: asyncpg.Pool, filters: JobFilters) -> int:
    where, params = build_filters(filters)
    count: int = await pool.fetchval(f"SELECT count(*) FROM jobs.vacancies v {where}", *params)
    return count


async def find_organizations(pool: asyncpg.Pool, name_contains: str | None = None) -> list[Organization]:
    rows = await pool.fetch(
        "SELECT id, name FROM jobs.organizations WHERE $1::text IS NULL OR name ILIKE $1 ESCAPE '\\' ORDER BY name",
        None if name_contains is None else f"%{escape_like(name_contains)}%",
    )
    return [Organization(**dict(row)) for row in rows]


async def create_organization(pool: asyncpg.Pool, name: str) -> Organization:
    """Store an organization, or return the stored one whose name differs only in case."""
    name = name.strip()
    if not name:
        raise ValueError("organization name is empty")
    row = await pool.fetchrow(
        """
        INSERT INTO jobs.organizations (name) VALUES ($1)
        ON CONFLICT ((lower(name))) DO NOTHING
        RETURNING id, name
        """,
        name,
    )
    if row is None:
        row = await pool.fetchrow("SELECT id, name FROM jobs.organizations WHERE lower(name) = lower($1)", name)
    return Organization(**dict(row))
