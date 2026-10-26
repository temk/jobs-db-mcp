import json
from mcp.types import Tool

from jobdbmcp.config import Settings
from jobdbmcp.server import create_server

DATABASE_URL = "postgresql://jobs_rw:secret@127.0.0.1:5432/jobdb"

TOOLS = {
    "create_job",
    "update_job",
    "job_exists",
    "get_job",
    "find_jobs",
    "count_jobs",
    "find_organizations",
    "create_organization",
}


async def list_tools() -> dict[str, Tool]:
    server = create_server(Settings(database_url=DATABASE_URL))
    return {tool.name: tool for tool in await server.list_tools()}


async def test_every_tool_is_registered() -> None:
    assert (await list_tools()).keys() == TOOLS


async def test_tools_returning_jobs_or_organizations_declare_the_content_untrusted() -> None:
    tools = await list_tools()

    for name in ("get_job", "find_jobs", "find_organizations", "create_organization"):
        assert "UNTRUSTED CONTENT" in (tools[name].description or ""), name
        assert "UNTRUSTED CONTENT" in str(tools[name].output_schema), name


async def test_derived_job_fields_are_declared_untrusted() -> None:
    job_schema = str((await list_tools())["get_job"].output_schema)

    assert "search_text, digest, employer, and agency are derived" in job_schema


async def test_find_jobs_returns_cards_without_full_texts() -> None:
    card = (await list_tools())["find_jobs"].output_schema["$defs"]["JobCard"]["properties"]  # type: ignore[index]

    assert "digest" in card
    assert "description" not in card
    assert "search_text" not in card


async def test_list_filters_reject_an_empty_list() -> None:
    tools = await list_tools()

    for tool in ("find_jobs", "count_jobs"):
        properties = tools[tool].input_schema["properties"]
        for name in ("status", "management_level", "work_mode"):
            assert '"minItems": 1' in json.dumps(properties[name]), f"{tool}.{name}"
