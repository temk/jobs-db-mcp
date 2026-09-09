import pytest

from jobdbmcp.config import Settings
from jobdbmcp.server import create_server

DATABASE_URL = "postgresql://jobdb:secret@127.0.0.1:5432/jobdb"

READ_ONLY = {"job_exists", "get_job", "find_jobs"}
WRITES = {"save_job", "set_job_status", "set_job_score"}


async def tool_names(*, allow_writes: bool) -> set[str]:
    settings = Settings(database_url=DATABASE_URL, allow_writes=allow_writes)
    return {tool.name for tool in await create_server(settings).list_tools()}


async def test_writes_are_absent_by_default() -> None:
    assert await tool_names(allow_writes=False) == READ_ONLY


async def test_writes_are_registered_when_allowed() -> None:
    assert await tool_names(allow_writes=True) == READ_ONLY | WRITES


def test_allow_writes_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBDBMCP_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("JOBDBMCP_ALLOW_WRITES", "true")

    # _env_file=None so a developer's own .env cannot decide the outcome
    assert Settings(_env_file=None).allow_writes is True


def test_writes_are_off_when_the_variable_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBDBMCP_DATABASE_URL", DATABASE_URL)
    monkeypatch.delenv("JOBDBMCP_ALLOW_WRITES", raising=False)

    assert Settings(_env_file=None).allow_writes is False
