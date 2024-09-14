import pytest

from v4t_translate.rules.result import Finding, Report, Severity


def make(rule="fitting", severity=Severity.ERROR, key="a.1", locale="de-DE",
         summary="overflows by 12 pixels", detail=""):
    return Finding(rule=rule, severity=severity, locale=locale, key=key,
                   summary=summary, detail=detail)


def test_severity_is_ordered():
    assert Severity.ERROR > Severity.WARNING > Severity.INFO
    assert max([Severity.INFO, Severity.ERROR, Severity.WARNING]) is Severity.ERROR


def test_severity_prints_lowercase():
    assert str(Severity.WARNING) == "warning"


def test_severity_parse():
    assert Severity.parse("error") is Severity.ERROR
    assert Severity.parse("  WARNING ") is Severity.WARNING


def test_severity_parse_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown severity"):
        Severity.parse("catastrophic")


def test_finding_format_without_detail():
    assert make().format() == "error: fitting: overflows by 12 pixels"


def test_finding_format_with_detail():
    text = make(detail="102px available, 114px needed").format()
    assert text.splitlines()[1].strip() == "102px available, 114px needed"


def test_finding_format_can_suppress_detail():
    assert "\n" not in make(detail="x").format(with_detail=False)


def test_an_empty_report_is_falsey():
    report = Report()
    assert not report
    assert len(report) == 0
    assert report.worst is None


def test_a_report_with_findings_is_truthy():
    report = Report()
    report.add(make())
    assert report
    assert report.worst is Severity.ERROR


def test_errors_and_warnings_are_separated():
    report = Report()
    report.add(make(severity=Severity.ERROR))
    report.add(make(severity=Severity.WARNING))
    report.add(make(severity=Severity.INFO))
    assert len(report.errors) == 1
    assert len(report.warnings) == 1
    assert len(report.at_or_above(Severity.WARNING)) == 2


def test_sorted_puts_errors_first_then_groups_by_rule():
    report = Report()
    report.add(make(rule="glyphs", severity=Severity.WARNING, key="b.2"))
    report.add(make(rule="placeholders", severity=Severity.ERROR, key="c.3"))
    report.add(make(rule="fitting", severity=Severity.ERROR, key="a.1"))
    assert [f.rule for f in report.sorted()] == ["fitting", "placeholders", "glyphs"]


def test_sorted_is_stable_across_locales_for_one_rule():
    report = Report()
    report.add(make(locale="zh-TW", key="b.2"))
    report.add(make(locale="de-DE", key="a.1"))
    assert [f.locale for f in report.sorted()] == ["de-DE", "zh-TW"]


def test_by_rule_groups_and_keeps_the_sort():
    report = Report()
    report.add(make(rule="fitting", key="b.2"))
    report.add(make(rule="glyphs", severity=Severity.WARNING))
    report.add(make(rule="fitting", key="a.1"))
    grouped = report.by_rule()
    assert list(grouped) == ["fitting", "glyphs"]
    assert [f.key for f in grouped["fitting"]] == ["a.1", "b.2"]


def test_by_locale_groups():
    report = Report()
    report.add(make(locale="de-DE"))
    report.add(make(locale="zh-TW"))
    report.add(make(locale="de-DE", key="b.2"))
    assert {k: len(v) for k, v in report.by_locale().items()} == {"de-DE": 2, "zh-TW": 1}


def test_rule_counts_are_ordered_by_frequency():
    report = Report()
    report.add(make(rule="glyphs"))
    report.add(make(rule="fitting"))
    report.add(make(rule="fitting"))
    assert list(report.rule_counts()) == ["fitting", "glyphs"]


def test_summary_of_a_clean_run():
    report = Report(checked=412)
    assert report.summary() == "412 messages checked, nothing found"


def test_summary_counts_both_levels():
    report = Report(checked=412)
    report.add(make(severity=Severity.ERROR))
    report.add(make(severity=Severity.WARNING))
    report.add(make(severity=Severity.WARNING))
    assert report.summary() == "412 messages checked, 1 errors, 2 warnings"


def test_extend_adds_several():
    report = Report()
    report.extend([make(), make(key="b.2")])
    assert len(report) == 2


@pytest.mark.parametrize(
    ("fail_on", "severity", "expected"),
    [
        ("error", Severity.ERROR, True),
        ("error", Severity.WARNING, False),
        ("error", Severity.INFO, False),
        ("warning", Severity.ERROR, True),
        ("warning", Severity.WARNING, True),
        ("warning", Severity.INFO, False),
        ("never", Severity.ERROR, False),
    ],
)
def test_should_fail(fail_on, severity, expected):
    report = Report()
    report.add(make(severity=severity))
    assert report.should_fail(fail_on) is expected


def test_a_clean_report_never_fails():
    for fail_on in ("error", "warning", "never"):
        assert not Report().should_fail(fail_on)
