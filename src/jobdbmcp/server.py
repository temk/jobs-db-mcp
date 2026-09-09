from typing import Any, Annotated
from datetime import datetime
from pydantic import Field
from contextlib import asynccontextmanager
from collections.abc import Callable, AsyncIterator
from mcp.server.mcpserver import Context, MCPServer

from jobdbmcp import repository
from jobdbmcp.db import AppContext, pool_lifespan
from jobdbmcp.config import Settings
from jobdbmcp.models import Job, Score, OrderBy, SavedJob, JobExists, JobStatus, JobSummary

INSTRUCTIONS = "Controlled access to the job-search database. Arbitrary SQL is not available."


async def save_job(
    ctx: Context[AppContext],
    site: str,
    pos_id: str,
    url: str,
    title: str,
    company: str | None = None,
    location: str | None = None,
    description: str | None = None,
    published_at: datetime | None = None,
) -> SavedJob:
    """Store a new job.

    Fails if (site, pos_id) is already stored; a known job is never overwritten.
    """
    return await repository.save_job(
        ctx.request_context.lifespan_context.pool,
        site=site,
        pos_id=pos_id,
        url=url,
        title=title,
        company=company,
        location=location,
        description=description,
        published_at=published_at,
    )


async def job_exists(ctx: Context[AppContext], site: str, pos_id: str) -> JobExists:
    """Check whether a posting is already stored, by its site and source id.

    Returns the internal job_id when it is known, so a follow-up call needs no second lookup.
    Use this before save_job, which fails on an already stored posting.
    """
    job_id = await repository.find_job_id(ctx.request_context.lifespan_context.pool, site, pos_id)
    return JobExists(exists=job_id is not None, job_id=job_id)


async def get_job(ctx: Context[AppContext], job_id: int) -> Job:
    """Get one job by its internal id, including description, score, and status."""
    job = await repository.get_job(ctx.request_context.lifespan_context.pool, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    return job


async def find_jobs(
    ctx: Context[AppContext],
    site: str | None = None,
    status: JobStatus | None = None,
    min_score: Score | None = None,
    max_score: Score | None = None,
    seen_after: datetime | None = None,
    published_after: datetime | None = None,
    company: str | None = None,
    location: str | None = None,
    title_contains: str | None = None,
    order_by: OrderBy = "published",
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> list[JobSummary]:
    """Browse and filter stored jobs. All filters are optional and combine with AND.

    company, location, and title_contains match case-insensitive substrings.
    Descriptions are omitted here; use get_job for the full record.
    The newest known posting of a site is find_jobs(site=..., order_by="published", limit=1).
    """
    return await repository.find_jobs(
        ctx.request_context.lifespan_context.pool,
        site=site,
        status=status,
        min_score=min_score,
        max_score=max_score,
        seen_after=seen_after,
        published_after=published_after,
        company=company,
        location=location,
        title_contains=title_contains,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )


async def set_job_status(ctx: Context[AppContext], job_id: int, status: JobStatus) -> str:
    """Set the review status of a job."""
    if not await repository.set_job_status(ctx.request_context.lifespan_context.pool, job_id, status):
        raise ValueError(f"job {job_id} not found")
    return status


async def set_job_score(ctx: Context[AppContext], job_id: int, score: Score) -> int:
    """Set the relevance score of a job, 0 to 100. Replaces any previous score."""
    if not await repository.set_job_score(ctx.request_context.lifespan_context.pool, job_id, score):
        raise ValueError(f"job {job_id} not found")
    return score


READ_TOOLS: list[Callable[..., Any]] = [job_exists, get_job, find_jobs]
WRITE_TOOLS: list[Callable[..., Any]] = [save_job, set_job_status, set_job_score]


def create_server(settings: Settings) -> MCPServer:
    """Build the server. Write tools exist only when JOBDBMCP_ALLOW_WRITES is set."""

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
        async with pool_lifespan(settings) as context:
            yield context

    mcp = MCPServer("JobDBMCP", instructions=INSTRUCTIONS, lifespan=lifespan)
    for tool in READ_TOOLS:
        mcp.add_tool(tool)
    if settings.allow_writes:
        for tool in WRITE_TOOLS:
            mcp.add_tool(tool)
    return mcp


def main() -> None:
    settings = Settings()
    server = create_server(settings)
    server.run(transport="streamable-http", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
