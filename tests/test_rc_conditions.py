import pytest

from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.rc.conditions import (
    EDITOR_SYMBOLS,
    Condition,
    collect_conditions,
)
from v4t_translate.sources.rc.extract import RcSource

NESTED = """\
line one
#ifdef V4T_8PEN
inside eight pen
#ifndef V4T_EXPORT
inside both
#endif
inside eight pen again
#endif
outside again
"""


def texts(extraction):
    return {m.source_text for m in extraction.messages}


def extract(path, root, **symbols):
    return RcSource().extract(
        SourceOptions(path=path, root=root, symbols=symbols)
    )


def test_a_line_outside_any_condition():
    assert collect_conditions(NESTED).at(1) == ()
    assert collect_conditions(NESTED).at(9) == ()


def test_a_line_inside_one():
    assert collect_conditions(NESTED).at(3) == (Condition("V4T_8PEN"),)


def test_a_line_inside_two():
    assert collect_conditions(NESTED).at(5) == (
        Condition("V4T_8PEN"), Condition("V4T_EXPORT", negated=True),
    )


def test_the_stack_unwinds():
    assert collect_conditions(NESTED).at(7) == (Condition("V4T_8PEN"),)


def test_describe_reads():
    assert collect_conditions(NESTED).describe(5) == "V4T_8PEN and !V4T_EXPORT"
    assert collect_conditions(NESTED).describe(1) == ""


def test_the_symbols_a_file_uses():
    assert collect_conditions(NESTED).symbols_used() == {"V4T_8PEN", "V4T_EXPORT"}


@pytest.mark.parametrize(
    "directive",
    [
        "#ifdef V4T_8PEN",
        "#ifndef V4T_8PEN",
        "#if defined(V4T_8PEN)",
        "#if !defined(V4T_8PEN)",
        "#if V4T_8PEN",
        "  #  ifdef V4T_8PEN",
    ],
)
def test_the_forms_a_resource_script_uses(directive):
    conditions = collect_conditions(f"{directive}\nIDS_A \"x\"\n#endif\n")
    assert conditions.at(2)[0].symbol == "V4T_8PEN"


def test_a_negated_form_is_marked_negated():
    assert collect_conditions('#ifndef X\nIDS_A "x"\n#endif\n').at(2)[0].negated
    assert collect_conditions('#if !defined(X)\nIDS_A "x"\n#endif\n').at(2)[0].negated


def test_an_expression_this_does_not_understand_is_undecidable():
    conditions = collect_conditions('#if A > 3 && B\nIDS_A "x"\n#endif\n')
    assert conditions.at(2) == (None,)
    assert conditions.is_live(2, {"A": False})


def test_an_else_branch_is_undecidable():
    text = '#ifdef X\nIDS_A "a"\n#else\nIDS_B "b"\n#endif\n'
    conditions = collect_conditions(text)
    assert conditions.at(4) == (None,)
    assert conditions.is_live(4, {"X": True})


def test_a_trailing_comment_on_an_endif_does_not_confuse_it():
    text = '#ifdef X\nIDS_A "a"\n#endif /* X */\nIDS_B "b"\n'
    assert collect_conditions(text).at(4) == ()


def test_a_comment_after_an_ifdef():
    text = '#ifdef X // the eight pen build\nIDS_A "a"\n#endif\n'
    assert collect_conditions(text).at(2)[0].symbol == "X"


def test_an_unbalanced_endif_does_not_explode():
    assert collect_conditions('#endif\nIDS_A "a"\n').at(2) == ()


def test_a_symbol_the_project_defines_is_live():
    conditions = collect_conditions(NESTED)
    assert conditions.is_live(3, {"V4T_8PEN": True})


def test_a_symbol_the_project_undefines_is_dead():
    conditions = collect_conditions(NESTED)
    assert not conditions.is_live(3, {"V4T_8PEN": False})


def test_a_symbol_the_project_never_mentions_is_kept():
    # Undecidable means live. Silently dropping a string that will ship is a
    # defect; mentioning one that will not is a nuisance.
    assert collect_conditions(NESTED).is_live(3, {})


def test_a_negated_condition_reverses():
    conditions = collect_conditions(NESTED)
    assert conditions.is_live(5, {"V4T_8PEN": True, "V4T_EXPORT": False})
    assert not conditions.is_live(5, {"V4T_8PEN": True, "V4T_EXPORT": True})


def test_every_condition_has_to_hold():
    conditions = collect_conditions(NESTED)
    assert not conditions.is_live(5, {"V4T_8PEN": False, "V4T_EXPORT": False})


def test_the_editor_bookkeeping_symbols_are_never_defined():
    for symbol in EDITOR_SYMBOLS:
        text = f'#ifdef {symbol}\nIDS_A "a"\n#endif\n'
        assert not collect_conditions(text).is_live(2, {})


def test_a_negated_editor_symbol_is_live():
    text = '#ifndef APSTUDIO_INVOKED\nIDS_A "a"\n#endif\n'
    assert collect_conditions(text).is_live(2, {})


def test_the_fixture_is_extracted_whole_by_default(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent)
    assert "Traverse Printing" in texts(extraction)


def test_defining_the_symbol_keeps_it(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent, V4T_8PEN=True)
    assert "Traverse Printing" in texts(extraction)


def test_undefining_the_symbol_drops_it(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent, V4T_8PEN=False)
    found = texts(extraction)

    assert "Traverse Printing" not in found
    assert "Group Print Offsets" not in found
    # And nothing outside the block went with it.
    assert "Bar Height" in found
    assert "Print started" in found


def test_a_kept_conditional_string_says_so(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent, V4T_8PEN=True)
    message = next(m for m in extraction.messages
                   if m.source_text == "Traverse Printing")
    assert "Only built when V4T_8PEN." in message.developer_note


def test_an_unconditional_string_says_nothing(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent)
    message = next(m for m in extraction.messages if m.source_text == "Print started")
    assert "Only built when" not in (message.developer_note or "")


def test_a_condition_note_is_added_to_a_developer_note(sample_rc_path):
    extraction = extract(sample_rc_path, sample_rc_path.parent, V4T_8PEN=True)
    message = next(m for m in extraction.messages if m.source_text == "Spacing")
    assert message.developer_note
    assert "Only built when V4T_8PEN." in message.developer_note
