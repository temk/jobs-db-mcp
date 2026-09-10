import asyncpg
from typing import Any
from datetime import datetime
from dataclasses import dataclass

from jobdbmcp.models import Job, OrderBy, JobStatus, validate_job_fields


class DuplicateJobError(Exception):
    """Raised when a job with the same (site, pos_id) is already stored."""

    def __init__(self, site: str, pos_id: str) -> None:
        super().__init__(f"job {pos_id} from {site} is already stored")


@dataclass
class JobFilters:
    site: str | None = None
    status: JobStatus | None = None
    min_score: int | None = None
    max_score: int | None = None
    downloaded_after: datetime | None = None
    published_after: datetime | None = None
    company: str | None = None
    location: str | None = None
    title_contains: str | None = None
    managerial: bool | None = None
    stack: str | None = None
    requirements: list[str] | None = None
    description_search: str | None = None


JOB_COLUMNS = """
    id, site, pos_id, url, title, company, location, description, english_description,
    published_at, downloaded_at, score, status, managerial, stack, requirements
"""

ORDER_BY_SQL: dict[OrderBy, str] = {
    "published": "published_at DESC NULLS LAST, id DESC",
    "downloaded": "downloaded_at DESC, id DESC",
    "score": "score DESC NULLS LAST, id DESC",
}


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_requirements(requirements: list[str] | None) -> list[str] | None:
    """Trim, drop empty entries and duplicates, and sort: the stored form of requirements."""
    if requirements is None:
        return None
    return sorted({requirement.strip() for requirement in requirements if requirement.strip()})


def build_filters(filters: JobFilters) -> tuple[str, list[Any]]:
    """Build the WHERE clause and its parameters. Empty clause when no filter is set."""
    conditions: list[str] = []
    params: list[Any] = []

    def add(condition_template: str, value: Any) -> None:
        params.append(value)
        conditions.append(condition_template.format(n=len(params)))

    if filters.site is not None:
        add("site = ${n}", filters.site)
    if filters.status is not None:
        add("status = ${n}", filters.status)
    if filters.min_score is not None:
        add("score >= ${n}", filters.min_score)
    if filters.max_score is not None:
        add("score <= ${n}", filters.max_score)
    if filters.downloaded_after is not None:
        add("downloaded_at >= ${n}", filters.downloaded_after)
    if filters.published_after is not None:
        add("published_at >= ${n}", filters.published_after)
    if filters.company is not None:
        add("company ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.company)}%")
    if filters.location is not None:
        add("location ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.location)}%")
    if filters.title_contains is not None:
        add("title ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.title_contains)}%")
    if filters.managerial is not None:
        add("managerial = ${n}", filters.managerial)
    if filters.stack is not None:
        add("stack ILIKE ${n} ESCAPE '\\'", f"%{escape_like(filters.stack)}%")
    for requirement in filters.requirements or []:
        add(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(requirements) AS r WHERE r ILIKE ${n} ESCAPE '\\')",
            f"%{escape_like(requirement)}%",
        )
    if filters.description_search is not None:
        # Must match the expression of vacancies_english_description_fts_idx to use the index.
        add(
            "to_tsvector('english', english_description) @@ websearch_to_tsquery('english', ${n})",
            filters.description_search,
        )

    if not conditions:
        return "", params
    return "WHERE " + " AND ".join(conditions), params


async def create_job(pool: asyncpg.Pool, job: Job) -> Job:
    """Insert a job. downloaded_at is set by the database.

    Raises DuplicateJobError when (site, pos_id) is already stored: a known job is never
    silently overwritten, so review state cannot be lost to a re-parse.
    """
    if job.id is not None:
        raise ValueError("id must be empty when creating a job")
    try:
        row = await pool.fetchrow(
            f"""
            INSERT INTO jobs.vacancies (
                site, pos_id, url, title, company, location, description, english_description,
                published_at, score, status, managerial, stack, requirements
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING {JOB_COLUMNS}
            """,
            job.site,
            job.pos_id,
            job.url,
            job.title,
            job.company,
            job.location,
            job.description,
            job.english_description,
            job.published_at,
            job.score,
            job.status,
            job.managerial,
            job.stack,
            normalize_requirements(job.requirements),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateJobError(job.site, job.pos_id) from exc
    return Job(**dict(row))


def build_assignments(fields: dict[str, Any]) -> tuple[str, list[Any]]:
    """Build the SET list for the given fields, numbered from $2; $1 is the job id."""
    values = validate_job_fields(fields)
    if "requirements" in values:
        values["requirements"] = normalize_requirements(values["requirements"])
    # validate_job_fields admits only Job field names, so they are safe to use as column names.
    assignments = ", ".join(f"{column} = ${n}" for n, column in enumerate(values, start=2))
    return assignments, list(values.values())


async def update_job(pool: asyncpg.Pool, job_id: int, fields: dict[str, Any]) -> Job | None:
    """Change the given fields of a job and leave the rest as stored. None when the job is unknown."""
    assignments, params = build_assignments(fields)
    try:
        row = await pool.fetchrow(
            f"UPDATE jobs.vacancies SET {assignments} WHERE id = $1 RETURNING {JOB_COLUMNS}",
            job_id,
            *params,
        )
    except asyncpg.UniqueViolationError as exc:
        raise ValueError(f"job {job_id} would get the (site, pos_id) of another stored job") from exc
    return Job(**dict(row)) if row is not None else None


async def update_job_status(pool: asyncpg.Pool, job_id: int, status: JobStatus) -> Job | None:
    row = await pool.fetchrow(
        f"UPDATE jobs.vacancies SET status = $2 WHERE id = $1 RETURNING {JOB_COLUMNS}", job_id, status
    )
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
    row = await pool.fetchrow(f"SELECT {JOB_COLUMNS} FROM jobs.vacancies WHERE id = $1", job_id)
    return Job(**dict(row)) if row is not None else None


async def find_jobs(
    pool: asyncpg.Pool,
    filters: JobFilters,
    order_by: OrderBy = "published",
    page: int = 1,
    page_size: int = 50,
) -> list[Job]:
    """Return one page of matching jobs. Pages are numbered from 1."""
    where, params = build_filters(filters)
    rows = await pool.fetch(
        f"""
        SELECT {JOB_COLUMNS}
        FROM jobs.vacancies
        {where}
        ORDER BY {ORDER_BY_SQL[order_by]}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        page_size,
        (page - 1) * page_size,
    )
    return [Job(**dict(row)) for row in rows]


async def count_jobs(pool: asyncpg.Pool, filters: JobFilters) -> int:
    where, params = build_filters(filters)
    count: int = await pool.fetchval(f"SELECT count(*) FROM jobs.vacancies {where}", *params)
    return count
