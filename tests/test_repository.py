import pytest
from typing import Any
from datetime import UTC, datetime

from jobdbmcp.models import Job
from jobdbmcp.repository import JobFilters, escape_like, build_filters, prepare_fields, build_assignments


def assign(fields: dict[str, Any]) -> tuple[str, list[Any]]:
    return build_assignments(prepare_fields(fields))


def test_no_filters_produces_empty_clause() -> None:
    where, params = build_filters(JobFilters())

    assert where == ""
    assert params == []


def test_filters_are_numbered_in_order() -> None:
    where, params = build_filters(JobFilters(site="linkedin", status=["new", "low_priority"], min_fit_score=50))

    assert where == "WHERE v.site = $1 AND v.status = ANY($2) AND v.fit_score >= $3"
    assert params == ["linkedin", ["new", "low_priority"], 50]


def test_substring_filters_are_wrapped_in_wildcards() -> None:
    where, params = build_filters(JobFilters(title_contains="Team Lead"))

    assert where == "WHERE v.title ILIKE $1 ESCAPE '\\'"
    assert params == ["%Team Lead%"]


def test_user_wildcards_do_not_widen_the_match() -> None:
    _, params = build_filters(JobFilters(title_contains="100%_bonus"))

    assert params == ["%100\\%\\_bonus%"]


def test_timestamps_are_passed_through_as_parameters() -> None:
    downloaded_after = datetime(2026, 9, 1, tzinfo=UTC)
    where, params = build_filters(JobFilters(downloaded_after=downloaded_after))

    assert where == "WHERE v.downloaded_at >= $1"
    assert params == [downloaded_after]


def test_list_filters_match_any_of_the_values() -> None:
    where, params = build_filters(JobFilters(management_level=["tech_lead", "team_lead"], work_mode=["remote"]))

    assert where == "WHERE v.management_level = ANY($1) AND v.work_mode = ANY($2)"
    assert params == [["tech_lead", "team_lead"], ["remote"]]


def test_minimum_interest_score_is_a_lower_bound() -> None:
    assert build_filters(JobFilters(min_interest_score=60)) == ("WHERE v.interest_score >= $1", [60])


def test_organizations_are_matched_by_id() -> None:
    where, params = build_filters(JobFilters(employer_id=7, agency_id=9))

    assert where == "WHERE v.employer_id = $1 AND v.agency_id = $2"
    assert params == [7, 9]


def test_direct_jobs_have_an_employer_and_no_agency() -> None:
    assert build_filters(JobFilters(direct=True)) == ("WHERE v.agency_id IS NULL AND v.employer_id IS NOT NULL", [])


def test_direct_false_selects_agency_jobs() -> None:
    assert build_filters(JobFilters(direct=False)) == ("WHERE v.agency_id IS NOT NULL", [])


def test_scored_jobs_have_both_scores() -> None:
    where, _ = build_filters(JobFilters(scored=True))

    assert where == "WHERE v.fit_score IS NOT NULL AND v.interest_score IS NOT NULL"


def test_unscored_jobs_miss_either_score() -> None:
    where, _ = build_filters(JobFilters(scored=False))

    assert where == "WHERE (v.fit_score IS NULL OR v.interest_score IS NULL)"


def test_parameterless_filters_keep_the_numbering() -> None:
    where, params = build_filters(JobFilters(site="linkedin", direct=True, min_fit_score=50))

    assert where == "WHERE v.site = $1 AND v.fit_score >= $2 AND v.agency_id IS NULL AND v.employer_id IS NOT NULL"
    assert params == ["linkedin", 50]


def test_company_matches_a_substring() -> None:
    where, params = build_filters(JobFilters(company="check"))

    assert where == "WHERE v.company ILIKE $1 ESCAPE '\\'"
    assert params == ["%check%"]


def test_text_search_uses_the_indexed_expression() -> None:
    where, params = build_filters(JobFilters(text_search='"team lead" -java'))

    assert where == "WHERE to_tsvector('english', v.search_text) @@ websearch_to_tsquery('english', $1)"
    assert params == ['"team lead" -java']


def test_only_given_fields_are_assigned_and_null_clears() -> None:
    fields = {"work_mode": "hybrid", "description": None, "fit_score": 70}

    assert assign(fields) == ("work_mode = $2, description = $3, fit_score = $4", ["hybrid", None, 70])


def test_values_are_converted_to_field_types() -> None:
    _, params = assign({"published_at": "2026-09-01T10:00:00Z"})

    assert params == [datetime(2026, 9, 1, 10, tzinfo=UTC)]


def test_update_without_fields_is_rejected() -> None:
    with pytest.raises(ValueError, match="no fields"):
        assign({})


@pytest.mark.parametrize("name", ["id", "downloaded_at", "employer", "agency", "salary"])
def test_unknown_and_read_only_fields_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match=f"read-only fields: {name}"):
        assign({name: 1})


def test_required_fields_cannot_be_cleared() -> None:
    with pytest.raises(ValueError, match="invalid value for title"):
        assign({"title": None})


def test_field_constraints_apply() -> None:
    with pytest.raises(ValueError, match="invalid value for interest_score"):
        assign({"interest_score": 101})


def test_digest_longer_than_1500_characters_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid value for digest"):
        assign({"digest": "x" * 1501})


def test_a_duplicate_is_assigned_together_with_its_original() -> None:
    fields = {"status": "duplicate", "duplicate_of": 12}

    assert assign(fields) == ("status = $2, duplicate_of = $3", ["duplicate", 12])


def test_a_status_other_than_duplicate_clears_the_original() -> None:
    assert assign({"status": "new"}) == ("status = $2, duplicate_of = $3", ["new", None])


def test_a_duplicate_without_an_original_is_rejected() -> None:
    with pytest.raises(ValueError, match="needs duplicate_of"):
        assign({"status": "duplicate"})


def test_an_original_without_the_duplicate_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="only with status duplicate"):
        assign({"status": "applied", "duplicate_of": 12})


def test_an_original_without_a_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="together with status"):
        assign({"duplicate_of": 12})


def test_escape_like_escapes_backslash_first() -> None:
    assert escape_like("a\\%b") == "a\\\\\\%b"


def test_a_new_job_marked_duplicate_needs_an_original() -> None:
    with pytest.raises(ValueError, match="needs duplicate_of"):
        Job(site="linkedin", pos_id="1", url="https://example.com/1", title="Engineer", status="duplicate")


@pytest.mark.parametrize("name", ["search_text", "digest"])
def test_search_text_and_digest_cannot_be_cleared(name: str) -> None:
    with pytest.raises(ValueError, match=f"{name} cannot be cleared"):
        assign({name: None})
