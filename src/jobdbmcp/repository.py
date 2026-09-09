import asyncpg
from typing import Any
from datetime import datetime

from jobdbmcp.models import Job, OrderBy, SavedJob, JobStatus, JobSummary


class DuplicateJobError(Exception):
    """Raised when a job with the same (site, pos_id) is already stored."""

    def __init__(self, site: str, pos_id: str) -> None:
        super().__init__(f"job {pos_id} from {site} is already stored")


SUMMARY_COLUMNS = """
    id AS job_id, site, pos_id, url, title, company, location,
    downloaded_at, published_at, score, status
"""

ORDER_BY_SQL: dict[OrderBy, str] = {
    "published": "published_at DESC NULLS LAST, id DESC",
    "downloaded": "downloaded_at DESC, id DESC",
    "score": "score DESC NULLS LAST, id DESC",
}


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_filters(
    site: str | None,
    status: JobStatus | None,
    min_score: int | None,
    max_score: int | None,
    downloaded_after: datetime | None,
    published_after: datetime | None,
    company: str | None,
    location: str | None,
    title_contains: str | None,
) -> tuple[str, list[Any]]:
    """Build the WHERE clause and its parameters. Empty clause when no filter is set."""
    conditions: list[str] = []
    params: list[Any] = []

    def add(condition_template: str, value: Any) -> None:
        params.append(value)
        conditions.append(condition_template.format(n=len(params)))

    if site is not None:
        add("site = ${n}", site)
    if status is not None:
        add("status = ${n}", status)
    if min_score is not None:
        add("score >= ${n}", min_score)
    if max_score is not None:
        add("score <= ${n}", max_score)
    if downloaded_after is not None:
        add("downloaded_at >= ${n}", downloaded_after)
    if published_after is not None:
        add("published_at >= ${n}", published_after)
    if company is not None:
        add("company ILIKE ${n} ESCAPE '\\'", f"%{escape_like(company)}%")
    if location is not None:
        add("location ILIKE ${n} ESCAPE '\\'", f"%{escape_like(location)}%")
    if title_contains is not None:
        add("title ILIKE ${n} ESCAPE '\\'", f"%{escape_like(title_contains)}%")

    if not conditions:
        return "", params
    return "WHERE " + " AND ".join(conditions), params


async def save_job(
    pool: asyncpg.Pool,
    site: str,
    pos_id: str,
    url: str,
    title: str,
    company: str | None,
    location: str | None,
    description: str | None,
    published_at: datetime | None,
) -> SavedJob:
    """Insert a job.

    Raises DuplicateJobError when (site, pos_id) is already stored: a known job is never
    silently overwritten, so review state cannot be lost to a re-parse.
    """
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO jobs.vacancies (site, pos_id, url, title, company, location, description, published_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            site,
            pos_id,
            url,
            title,
            company,
            location,
            description,
            published_at,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateJobError(site, pos_id) from exc
    return SavedJob(job_id=row["id"])


async def find_job_id(pool: asyncpg.Pool, site: str, pos_id: str) -> int | None:
    """Look up a job by its source identity. Served by the unique index on (site, pos_id)."""
    row = await pool.fetchrow(
        "SELECT id FROM jobs.vacancies WHERE site = $1 AND pos_id = $2",
        site,
        pos_id,
    )
    return row["id"] if row is not None else None


async def get_job(pool: asyncpg.Pool, job_id: int) -> Job | None:
    row = await pool.fetchrow(
        f"SELECT {SUMMARY_COLUMNS}, description FROM jobs.vacancies WHERE id = $1",
        job_id,
    )
    return Job(**dict(row)) if row is not None else None


async def find_jobs(
    pool: asyncpg.Pool,
    site: str | None = None,
    status: JobStatus | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    downloaded_after: datetime | None = None,
    published_after: datetime | None = None,
    company: str | None = None,
    location: str | None = None,
    title_contains: str | None = None,
    order_by: OrderBy = "published",
    limit: int = 50,
    offset: int = 0,
) -> list[JobSummary]:
    where, params = build_filters(
        site, status, min_score, max_score, downloaded_after, published_after, company, location, title_contains
    )
    rows = await pool.fetch(
        f"""
        SELECT {SUMMARY_COLUMNS}
        FROM jobs.vacancies
        {where}
        ORDER BY {ORDER_BY_SQL[order_by]}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        limit,
        offset,
    )
    return [JobSummary(**dict(row)) for row in rows]


async def set_job_status(pool: asyncpg.Pool, job_id: int, status: JobStatus) -> bool:
    result = await pool.execute("UPDATE jobs.vacancies SET status = $2 WHERE id = $1", job_id, status)
    return result != "UPDATE 0"


async def set_job_score(pool: asyncpg.Pool, job_id: int, score: int) -> bool:
    result = await pool.execute("UPDATE jobs.vacancies SET score = $2 WHERE id = $1", job_id, score)
    return result != "UPDATE 0"
