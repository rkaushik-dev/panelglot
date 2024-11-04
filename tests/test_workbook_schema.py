import pytest

from v4t_translate.errors import WorkbookError
from v4t_translate.workbook.schema import Column, detect_schema


def test_the_delivered_taiwan_sheet():
    # Row 1 of "Translation - V4T-TIJ - Taiwan.xlsx", exactly.
    schema = detect_schema(["English", "Taiwan"])
    assert schema.columns[Column.SOURCE] == 0
    assert schema.columns[Column.TARGET] == 1
    assert schema.locale.tag == "zh-TW"
    assert schema.target_heading == "Taiwan"
    assert schema.legacy


def test_the_delivered_german_sheet():
    schema = detect_schema(["English", "German"])
    assert schema.locale.tag == "de-DE"
    assert schema.legacy


def test_the_full_shape_this_tool_writes():
    schema = detect_schema(
        ["Key", "Context", "Source", "German", "Status", "Note", "Limit", "Where"]
    )
    assert not schema.legacy
    assert schema.columns[Column.KEY] == 0
    assert schema.columns[Column.STATUS] == 4
    assert schema.columns[Column.LIMIT] == 6
    assert schema.locale.tag == "de-DE"


def test_columns_are_found_by_heading_not_position():
    schema = detect_schema(["German", "Source", "Key"])
    assert schema.columns[Column.TARGET] == 0
    assert schema.columns[Column.SOURCE] == 1
    assert schema.columns[Column.KEY] == 2


def test_headings_are_case_and_space_insensitive():
    schema = detect_schema(["  KEY  ", "source text", "  german "])
    assert schema.columns[Column.KEY] == 0
    assert schema.columns[Column.SOURCE] == 1


def test_a_trailing_colon_in_a_heading():
    schema = detect_schema(["Source:", "German:"])
    assert schema.columns[Column.SOURCE] == 0


def test_a_footnote_marker_in_a_heading():
    schema = detect_schema(["Source", "German*"])
    assert schema.locale.tag == "de-DE"


def test_a_line_break_in_a_heading():
    schema = detect_schema(["Source", "Traditional\nChinese"])
    assert schema.locale.tag == "zh-TW"


def test_a_locale_tag_as_the_heading():
    schema = detect_schema(["Source", "zh-TW"])
    assert schema.locale.tag == "zh-TW"


def test_blank_columns_between_real_ones():
    schema = detect_schema(["Source", None, "", "German"])
    assert schema.columns[Column.TARGET] == 3


def test_note_aliases():
    for heading in ("Note", "Notes", "Comment", "Comments"):
        schema = detect_schema(["Source", "German", heading])
        assert schema.columns[Column.NOTE] == 2


def test_the_first_of_a_repeated_heading_wins():
    schema = detect_schema(["Source", "German", "Note", "Comment"])
    assert schema.columns[Column.NOTE] == 2


def test_english_is_never_the_target():
    with pytest.raises(WorkbookError, match="no target language column"):
        detect_schema(["Source", "English"])


def test_no_source_column():
    with pytest.raises(WorkbookError, match="no source column"):
        detect_schema(["Key", "German"])


def test_two_language_columns_are_rejected():
    with pytest.raises(WorkbookError, match="several target language columns"):
        detect_schema(["Source", "German", "Taiwan"])


def test_the_error_names_the_sheet():
    with pytest.raises(WorkbookError, match="Sheet1: no source column"):
        detect_schema(["Key"], sheet="Sheet1")


def test_an_empty_header_row():
    with pytest.raises(WorkbookError, match="no source column"):
        detect_schema([])


def test_has_and_index():
    schema = detect_schema(["Source", "German"])
    assert schema.has(Column.SOURCE)
    assert not schema.has(Column.STATUS)
    assert schema.index(Column.STATUS) is None


def test_describe_lists_the_columns_in_order():
    schema = detect_schema(["German", "Source"])
    assert schema.describe() == "Translation@1, Source@2"


def test_the_header_row_number_is_kept():
    assert detect_schema(["Source", "German"], row=3).header_row == 3
