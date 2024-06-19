import pytest

from v4t_translate.errors import (
    CatalogError,
    CheckFailed,
    ConfigError,
    ParseError,
    SourceError,
    V4TError,
)


def test_every_error_is_a_v4t_error():
    for cls in (ConfigError, SourceError, ParseError, CatalogError, CheckFailed):
        assert issubclass(cls, V4TError)


def test_parse_error_is_a_source_error():
    assert issubclass(ParseError, SourceError)


def test_exit_codes_are_distinct_where_it_matters():
    assert ConfigError.exit_code == 78
    assert CheckFailed.exit_code == 2
    assert V4TError.exit_code == 1


def test_parse_error_location_with_everything():
    err = ParseError("unterminated string", path="V4T.rc", line=412, column=17)
    assert err.location() == "V4T.rc:412:17"
    assert str(err) == "V4T.rc:412:17: unterminated string"


def test_parse_error_location_without_column():
    err = ParseError("bad token", path="V4T.rc", line=9)
    assert err.location() == "V4T.rc:9"
    assert str(err) == "V4T.rc:9: bad token"


def test_parse_error_location_with_nothing():
    err = ParseError("no idea where")
    assert err.location() == ""
    assert str(err) == "no idea where"


def test_parse_error_column_alone_is_not_reported():
    # A column without a line is meaningless, so it is dropped rather than
    # printed as a lone number that reads like a line.
    err = ParseError("odd", path="V4T.rc", column=4)
    assert err.location() == "V4T.rc"


def test_check_failed_carries_counts():
    err = CheckFailed("3 errors", error_count=3, warning_count=11)
    assert err.error_count == 3
    assert err.warning_count == 11
    assert str(err) == "3 errors"


def test_check_failed_counts_default_to_zero():
    err = CheckFailed("nothing in particular")
    assert err.error_count == 0
    assert err.warning_count == 0


def test_errors_can_be_caught_as_one_type():
    with pytest.raises(V4TError):
        raise ParseError("boom", path="x.rc", line=1)
