from v4t_translate.report.console import format_finding, format_report
from v4t_translate.rules.result import Finding, Report, Severity


def make(rule="fitting", severity=Severity.ERROR, key="a.1", locale="de-DE",
         summary="overflows its control by 12px", source="Bar Height",
         target="Balkenhöhe", detail="", origin=""):
    return Finding(rule=rule, severity=severity, locale=locale, key=key,
                   summary=summary, source_text=source, translated_text=target,
                   detail=detail, origin=origin)


def test_a_clean_report_is_just_the_summary():
    assert format_report(Report(checked=412)) == "412 messages checked, nothing found"


def test_a_finding_shows_both_texts():
    lines = format_finding(make())
    assert "'Bar Height'" in lines[0]
    assert "-> 'Balkenhöhe'" in lines[1]
    assert "overflows its control by 12px" in lines[2]


def test_the_severity_marker():
    assert format_finding(make(severity=Severity.ERROR))[0].strip().startswith("E ")
    assert format_finding(make(severity=Severity.WARNING))[0].strip().startswith("W ")
    assert format_finding(make(severity=Severity.INFO))[0].strip().startswith("i ")


def test_the_locale_is_on_the_first_line():
    assert " de-DE " in format_finding(make())[0]


def test_detail_is_shown_by_default():
    lines = format_finding(make(detail="85px available, 97px needed"))
    assert any("85px available" in line for line in lines)


def test_detail_can_be_suppressed():
    lines = format_finding(make(detail="85px available"), show_detail=False)
    assert all("85px available" not in line for line in lines)


def test_the_origin_is_shown_when_there_is_one():
    lines = format_finding(make(origin="V4T.rc:41 (IDD_BARCODE/IDC_STATIC)"))
    assert any("IDD_BARCODE" in line for line in lines)


def test_an_empty_translation_does_not_get_an_arrow_line():
    lines = format_finding(make(target=""))
    assert all("->" not in line for line in lines)


def test_a_very_long_string_is_truncated():
    lines = format_finding(make(source="x" * 200))
    assert "..." in lines[0]
    assert len(lines[0]) < 100


def test_whitespace_is_visible_in_the_quoting():
    lines = format_finding(make(source="Purge offset "))
    assert "'Purge offset '" in lines[0]


def test_findings_group_under_their_rule():
    report = Report(checked=10)
    report.add(make(rule="fitting"))
    report.add(make(rule="placeholders", key="b.2"))
    report.add(make(rule="fitting", key="c.3"))
    text = format_report(report)
    assert "placeholders (1, worst error)" in text
    assert "fitting (2, worst error)" in text


def test_the_heading_reports_the_worst_severity_in_the_group():
    report = Report(checked=10)
    report.add(make(rule="fitting", severity=Severity.WARNING))
    report.add(make(rule="fitting", severity=Severity.ERROR, key="b.2"))
    assert "fitting (2, worst error)" in format_report(report)


def test_the_limit_truncates_and_counts_the_rest():
    report = Report(checked=100)
    for index in range(20):
        report.add(make(key=f"k.{index}"))
    text = format_report(report, limit=5)
    assert "... and 15 more" in text


def test_a_limit_of_zero_shows_everything():
    report = Report(checked=100)
    for index in range(20):
        report.add(make(key=f"k.{index}"))
    assert "more" not in format_report(report, limit=0)


def test_the_summary_is_at_the_end():
    report = Report(checked=100)
    report.add(make())
    assert format_report(report).rstrip().endswith("1 errors, 0 warnings")


def test_errors_group_before_warnings():
    report = Report(checked=10)
    report.add(make(rule="whitespace", severity=Severity.WARNING))
    report.add(make(rule="placeholders", severity=Severity.ERROR, key="b.2"))
    text = format_report(report)
    assert text.index("placeholders") < text.index("whitespace")
