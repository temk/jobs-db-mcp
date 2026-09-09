from typing import Literal, Annotated
from datetime import datetime
from pydantic import Field, BaseModel

JobStatus = Literal["new", "interesting", "not_interested", "applied"]
OrderBy = Literal["published", "downloaded", "score"]
Score = Annotated[int, Field(ge=0, le=100)]


class SavedJob(BaseModel):
    job_id: int


class JobExists(BaseModel):
    exists: bool
    job_id: int | None


class JobSummary(BaseModel):
    job_id: int
    site: str
    pos_id: str
    url: str
    title: str
    company: str | None
    location: str | None
    downloaded_at: datetime
    published_at: datetime | None
    score: int | None
    status: JobStatus


class Job(JobSummary):
    description: str | None
