from datetime import UTC, datetime

from jobdbmcp.repository import escape_like, build_filters

NO_FILTERS = (None,) * 9


def test_no_filters_produces_empty_clause() -> None:
    where, params = build_filters(*NO_FILTERS)

    assert where == ""
    assert params == []


def test_filters_are_numbered_in_order() -> None:
    where, params = build_filters("linkedin", "new", 50, None, None, None, None, None, None)

    assert where == "WHERE site = $1 AND status = $2 AND score >= $3"
    assert params == ["linkedin", "new", 50]


def test_substring_filters_are_wrapped_in_wildcards() -> None:
    where, params = build_filters(None, None, None, None, None, None, None, None, "Team Lead")

    assert where == "WHERE title ILIKE $1 ESCAPE '\\'"
    assert params == ["%Team Lead%"]


def test_user_wildcards_do_not_widen_the_match() -> None:
    _, params = build_filters(None, None, None, None, None, None, None, None, "100%_bonus")

    assert params == ["%100\\%\\_bonus%"]


def test_timestamps_are_passed_through_as_parameters() -> None:
    seen_after = datetime(2026, 9, 1, tzinfo=UTC)
    where, params = build_filters(None, None, None, None, seen_after, None, None, None, None)

    assert where == "WHERE downloaded_at >= $1"
    assert params == [seen_after]


def test_escape_like_escapes_backslash_first() -> None:
    assert escape_like("a\\%b") == "a\\\\\\%b"
