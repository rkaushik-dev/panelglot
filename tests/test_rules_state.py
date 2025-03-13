import pytest

from v4t_translate.catalog.ids import source_fingerprint
from v4t_translate.catalog.model import Message
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.registry import rule_names
from v4t_translate.rules.result import Severity
from v4t_translate.rules.state import StateRule

APPROVED = TranslationState.APPROVED
DRAFT = TranslationState.DRAFT
NEEDS_REVIEW = TranslationState.NEEDS_REVIEW
EMPTY = TranslationState.EMPTY
DNT = TranslationState.DO_NOT_TRANSLATE


@pytest.fixture
def context():
    return RuleContext(
        locale=resolve("de-DE"),
        panel=get_panel("tij-800x600"),
        font=monospace(6),
    )


def run(context, source, translation):
    return list(StateRule().check(Message(key="k.1", source_text=source),
                                  translation, context))


def summaries(findings):
    return [f.summary for f in findings]


def test_a_current_approved_translation_is_silent(context):
    entry = Translation(text="Druck gestartet", state=APPROVED,
                        fingerprint=source_fingerprint("Print started"))
    assert run(context, "Print started", entry) == []


def test_an_untouched_message_is_silent(context):
    assert run(context, "Print started", Translation()) == []


def test_approved_with_nothing_in_it_is_an_error(context):
    findings = run(context, "Print started", Translation(text="", state=APPROVED))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "approved with nothing in it" in findings[0].summary
    assert "cleared the cell" in findings[0].detail


def test_empty_and_marked_empty_is_fine(context):
    assert run(context, "Print started", Translation(text="", state=EMPTY)) == []


def test_a_stale_approved_translation_is_an_error(context):
    entry = Translation(text="Druck gestartet", state=APPROVED,
                        fingerprint=source_fingerprint("Print STARTED"),
                        updated="2024-11-20")
    findings = run(context, "Print started", entry)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "different English" in findings[0].summary
    assert "2024-11-20" in findings[0].detail


def test_a_stale_draft_is_only_a_warning(context):
    entry = Translation(text="Druck gestartet", state=DRAFT,
                        fingerprint=source_fingerprint("Print STARTED"))
    findings = run(context, "Print started", entry)
    stale = [f for f in findings if "different English" in f.summary]
    assert stale[0].severity is Severity.WARNING


def test_a_stale_entry_with_no_recorded_date(context):
    entry = Translation(text="Druck gestartet", state=APPROVED,
                        fingerprint=source_fingerprint("Print STARTED"))
    assert "an unrecorded date" in run(context, "Print started", entry)[0].detail


def test_a_do_not_translate_entry_can_go_stale_too(context):
    entry = Translation(text="mm", state=DNT,
                        fingerprint=source_fingerprint("mm "))
    findings = run(context, "mm", entry)
    assert findings and findings[0].severity is Severity.ERROR


def test_an_entry_with_no_fingerprint_is_not_called_stale(context):
    entry = Translation(text="Druck gestartet", state=APPROVED)
    assert run(context, "Print started", entry) == []


def test_a_draft_is_reported_at_info(context):
    entry = Translation(text="Druck gestartet", state=DRAFT, origin="pseudo",
                        fingerprint=source_fingerprint("Print started"))
    findings = run(context, "Print started", entry)
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    assert "is draft and not shippable" in findings[0].summary
    assert "from pseudo" in findings[0].detail


def test_needs_review_is_reported_at_info(context):
    entry = Translation(text="Druck gestartet", state=NEEDS_REVIEW,
                        fingerprint=source_fingerprint("Print started"))
    findings = run(context, "Print started", entry)
    assert findings[0].severity is Severity.INFO
    assert "is needs-review" in findings[0].summary


def test_an_in_progress_entry_with_no_origin(context):
    entry = Translation(text="Druck gestartet", state=DRAFT,
                        fingerprint=source_fingerprint("Print started"))
    assert "Written." in run(context, "Print started", entry)[0].detail


def test_a_stale_draft_reports_both_things(context):
    entry = Translation(text="Druck gestartet", state=DRAFT,
                        fingerprint=source_fingerprint("Print STARTED"))
    findings = run(context, "Print started", entry)
    assert len(findings) == 2
    assert any("different English" in s for s in summaries(findings))
    assert any("not shippable" in s for s in summaries(findings))


def test_the_rule_is_registered():
    assert "state" in rule_names()


def test_the_rule_runs_before_fitting():
    names = rule_names()
    assert names.index("state") < names.index("fitting")
