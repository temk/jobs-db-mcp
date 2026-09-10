import pytest
from datetime import UTC, datetime

from jobdbmcp.repository import JobFilters, escape_like, build_filters, build_assignments, normalize_requirements

REQUIREMENT_MATCH = "EXISTS (SELECT 1 FROM jsonb_array_elements_text(requirements) AS r WHERE r ILIKE ${n} ESCAPE '\\')"


def test_no_filters_produces_empty_clause() -> None:
    where, params = build_filters(JobFilters())

    assert where == ""
    assert params == []


def test_filters_are_numbered_in_order() -> None:
    where, params = build_filters(JobFilters(site="linkedin", status="new", min_score=50))

    assert where == "WHERE site = $1 AND status = $2 AND score >= $3"
    assert params == ["linkedin", "new", 50]


def test_substring_filters_are_wrapped_in_wildcards() -> None:
    where, params = build_filters(JobFilters(title_contains="Team Lead"))

    assert where == "WHERE title ILIKE $1 ESCAPE '\\'"
    assert params == ["%Team Lead%"]


def test_user_wildcards_do_not_widen_the_match() -> None:
    _, params = build_filters(JobFilters(title_contains="100%_bonus"))

    assert params == ["%100\\%\\_bonus%"]


def test_timestamps_are_passed_through_as_parameters() -> None:
    downloaded_after = datetime(2026, 9, 1, tzinfo=UTC)
    where, params = build_filters(JobFilters(downloaded_after=downloaded_after))

    assert where == "WHERE downloaded_at >= $1"
    assert params == [downloaded_after]


def test_managerial_false_is_a_filter_not_an_absent_one() -> None:
    where, params = build_filters(JobFilters(managerial=False))

    assert where == "WHERE managerial = $1"
    assert params == [False]


def test_stack_matches_a_substring() -> None:
    where, params = build_filters(JobFilters(stack="spring"))

    assert where == "WHERE stack ILIKE $1 ESCAPE '\\'"
    assert params == ["%spring%"]


def test_each_requirement_is_a_separate_condition() -> None:
    where, params = build_filters(JobFilters(site="linkedin", requirements=["kafka", "10%"]))

    expected = " AND ".join(["site = $1", REQUIREMENT_MATCH.format(n=2), REQUIREMENT_MATCH.format(n=3)])
    assert where == f"WHERE {expected}"
    assert params == ["linkedin", "%kafka%", "%10\\%%"]


def test_description_search_uses_the_indexed_expression() -> None:
    where, params = build_filters(JobFilters(description_search='"team lead" -java'))

    assert where == "WHERE to_tsvector('english', english_description) @@ websearch_to_tsquery('english', $1)"
    assert params == ['"team lead" -java']


def test_empty_requirements_filter_matches_everything() -> None:
    assert build_filters(JobFilters(requirements=[])) == ("", [])


def test_requirements_are_trimmed_deduplicated_and_sorted() -> None:
    assert normalize_requirements([" kafka", "java", "", "kafka ", "  "]) == ["java", "kafka"]


def test_unknown_requirements_stay_unknown() -> None:
    assert normalize_requirements(None) is None


def test_only_given_fields_are_assigned_and_null_clears() -> None:
    fields = {"stack": "c++", "description": None, "requirements": ["b", "a"]}

    assert build_assignments(fields) == ("stack = $2, description = $3, requirements = $4", ["c++", None, ["a", "b"]])


def test_values_are_converted_to_field_types() -> None:
    _, params = build_assignments({"published_at": "2026-09-01T10:00:00Z"})

    assert params == [datetime(2026, 9, 1, 10, tzinfo=UTC)]


def test_update_without_fields_is_rejected() -> None:
    with pytest.raises(ValueError, match="no fields"):
        build_assignments({})


@pytest.mark.parametrize("name", ["id", "downloaded_at", "salary"])
def test_unknown_and_read_only_fields_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match=f"read-only fields: {name}"):
        build_assignments({name: 1})


def test_required_fields_cannot_be_cleared() -> None:
    with pytest.raises(ValueError, match="invalid value for title"):
        build_assignments({"title": None})


def test_field_constraints_apply() -> None:
    with pytest.raises(ValueError, match="invalid value for score"):
        build_assignments({"score": 101})


def test_escape_like_escapes_backslash_first() -> None:
    assert escape_like("a\\%b") == "a\\\\\\%b"
