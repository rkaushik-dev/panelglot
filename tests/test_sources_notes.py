import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.notes import CONTEXT_MARKER, NOTE_MARKER, collect_notes
from v4t_translate.sources.rc.extract import RcSource


@pytest.fixture(scope="module")
def extraction(sample_rc_path):
    return RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent)
    )


@pytest.fixture(scope="module")
def messages(extraction):
    return {m.source_text: m for m in extraction.by_key().values()}


def test_the_markers_are_the_gettext_ones():
    assert NOTE_MARKER == "TRANSLATORS:"
    assert CONTEXT_MARKER == "CONTEXT:"


def test_a_line_comment_covers_the_next_line():
    index = collect_notes("// TRANSLATORS: A note.\nIDS_A \"text\"\n")
    assert index.for_line(2).text == "A note."


def test_a_block_comment_covers_the_next_line():
    index = collect_notes('/* TRANSLATORS: A note. */\nIDS_A "text"\n')
    assert index.for_line(2).text == "A note."


def test_an_xml_comment_covers_the_next_line():
    index = collect_notes('<!-- TRANSLATORS: A note. -->\n<string name="a">x</string>\n')
    assert index.for_line(2).text == "A note."


def test_a_multi_line_block_comment():
    text = (
        "/* TRANSLATORS: The first line\n"
        " * and the second one.\n"
        " */\n"
        'IDS_A "text"\n'
    )
    assert collect_notes(text).for_line(4).text == "The first line and the second one."


def test_a_context_marker():
    index = collect_notes("// CONTEXT: verb\nIDS_A \"Print\"\n")
    assert index.for_line(2).context == "verb"
    assert index.for_line(2).text == ""


def test_both_markers_in_one_comment():
    text = "/* TRANSLATORS: The button.\n   CONTEXT: verb */\nIDS_A \"Print\"\n"
    note = collect_notes(text).for_line(3)
    assert note.text == "The button."
    assert note.context == "verb"


def test_trailing_punctuation_is_trimmed_off_a_context():
    assert collect_notes("// CONTEXT: verb.\nIDS_A \"x\"\n").for_line(2).context == "verb"


def test_an_unmarked_comment_is_not_a_note():
    assert len(collect_notes("// just a comment\nIDS_A \"x\"\n")) == 0


def test_a_comment_with_nothing_after_it_covers_nothing():
    assert len(collect_notes("IDS_A \"x\"\n// TRANSLATORS: A note.\n")) == 0


def test_blank_lines_between_the_comment_and_the_string():
    text = "// TRANSLATORS: A note.\n\n\nIDS_A \"x\"\n"
    assert collect_notes(text).for_line(4).text == "A note."


def test_another_comment_between_them_is_stepped_over():
    text = "// TRANSLATORS: A note.\n// something else\nIDS_A \"x\"\n"
    assert collect_notes(text).for_line(3).text == "A note."


def test_a_line_with_no_note_gets_nothing():
    index = collect_notes("// TRANSLATORS: A note.\nIDS_A \"x\"\nIDS_B \"y\"\n")
    assert index.for_line(3) is None


def test_a_note_reaches_the_message(messages):
    note = messages["Print started"].developer_note
    assert note is not None
    assert "two seconds after the start button" in note


def test_a_message_with_no_comment_keeps_whatever_it_had(messages):
    assert "accelerator" in messages["&New\tCtrl+N"].developer_note


def test_a_note_is_added_in_front_of_the_generated_one(sample_rc_path):
    message = {
        m.source_text: m
        for m in RcSource().extract(
            SourceOptions(path=sample_rc_path, root=sample_rc_path.parent)
        ).by_key().values()
    }["Bar Height"]

    assert message.developer_note.startswith("Height of the printed bars")
    assert "Anonymous control" in message.developer_note


def test_a_context_changes_the_key(tmp_path):
    path = tmp_path / "context.rc"
    path.write_text(
        "STRINGTABLE\nBEGIN\n"
        "  // CONTEXT: barcode\n"
        '  IDS_BAR_HEIGHT "Bar Height"\n'
        "END\n",
        encoding="utf-8",
    )
    message = RcSource().extract(
        SourceOptions(path=path, root=tmp_path)
    ).messages[0]

    assert message.context == "barcode"
    assert message.key == message_key("Bar Height", "barcode")
    assert message.key != message_key("Bar Height")


def test_the_shared_fixture_carries_no_context(messages):
    # Contexts change keys, and half the suite looks messages up by the key
    # of their plain English. The fixture keeps its notes and no contexts.
    assert all(message.context is None for message in messages.values())


def test_the_same_english_in_two_contexts_is_two_messages(tmp_path):
    path = tmp_path / "two.rc"
    path.write_text(
        "STRINGTABLE\nBEGIN\n"
        "  // CONTEXT: verb\n"
        '  IDS_PRINT_VERB "Print"\n'
        "  // CONTEXT: noun\n"
        '  IDS_PRINT_NOUN "Print"\n'
        "END\n",
        encoding="utf-8",
    )
    extraction = RcSource().extract(SourceOptions(path=path, root=tmp_path))
    merged = extraction.by_key()

    assert len(merged) == 2
    assert {m.context for m in merged.values()} == {"verb", "noun"}


def test_without_a_context_they_would_be_one_message(tmp_path):
    path = tmp_path / "one.rc"
    path.write_text(
        "STRINGTABLE\nBEGIN\n"
        '  IDS_PRINT_VERB "Print"\n'
        '  IDS_PRINT_NOUN "Print"\n'
        "END\n",
        encoding="utf-8",
    )
    assert len(RcSource().extract(SourceOptions(path=path, root=tmp_path)).by_key()) == 1


def test_notes_are_counted_in_the_stats(extraction):
    assert extraction.stats["notes"] == 2


def test_a_file_with_no_notes_counts_none(tmp_path):
    path = tmp_path / "plain.rc"
    path.write_text('STRINGTABLE\nBEGIN\n  IDS_A "x"\nEND\n', encoding="utf-8")
    extraction = RcSource().extract(SourceOptions(path=path, root=tmp_path))
    assert extraction.stats["notes"] == 0
