import pytest

from v4t_translate.sources.rc.expressions import ExpressionError, evaluate_expression

SYMBOLS = {
    "IDC_PEN_BASE": 1200,
    "IDC_STATIC": -1,
    "WS_CHILD": 0x40000000,
    "WS_VISIBLE": 0x10000000,
    "ZERO": 0,
}


def value(text):
    return evaluate_expression(text, SYMBOLS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("42", 42),
        ("  42  ", 42),
        ("0x10", 16),
        ("0X1F", 31),
        ("40001L", 40001),
        ("12u", 12),
        ("7UL", 7),
    ],
)
def test_literals(text, expected):
    assert value(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("IDC_PEN_BASE", 1200),
        ("IDC_STATIC", -1),
        ("IDC_PEN_BASE + 1", 1201),
        ("(IDC_PEN_BASE + 3)", 1203),
        ("IDC_PEN_BASE - 200", 1000),
        ("(IDC_PEN_BASE + 3L)", 1203),
    ],
)
def test_symbols_and_arithmetic(text, expected):
    assert value(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("100 / 7", 14),
        ("100 % 7", 2),
        ("2 * 3 + 4 * 5", 26),
        ("1 << 4", 16),
        ("256 >> 4", 16),
        ("6 & 3", 2),
        ("6 | 3", 7),
        ("6 ^ 3", 5),
        ("1 | 2 & 3", 3),
        ("-5", -5),
        ("+5", 5),
        ("~0", -1),
        ("- -5", 5),
        ("((((7))))", 7),
    ],
)
def test_operators_and_precedence(text, expected):
    assert value(text) == expected


def test_style_flags_the_way_a_header_writes_them():
    assert value("WS_CHILD | WS_VISIBLE") == 0x50000000


def test_division_truncates_toward_zero_like_c():
    assert evaluate_expression("-7 / 2", {}) == -3


def test_modulo_follows_the_sign_of_the_left_operand_like_c():
    assert evaluate_expression("-7 % 2", {}) == -1
    assert evaluate_expression("7 % -2", {}) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        '"a string"',
        "MAKE_PEN(n)",
        "UNKNOWN_SYMBOL",
        "IDC_PEN_BASE +",
        "(IDC_PEN_BASE + 1",
        "IDC_PEN_BASE)",
        "1 2",
        "1 $ 2",
        "1 / 0",
        "1 % 0",
        "1 << 200",
    ],
)
def test_things_that_are_not_expressions(text):
    with pytest.raises(ExpressionError):
        value(text)


def test_the_error_is_not_a_v4t_error():
    # A header may hold defines that are not integers. The caller skips the
    # line rather than failing the extraction, so this must not be catchable
    # as a package error.
    from v4t_translate.errors import V4TError

    assert not issubclass(ExpressionError, V4TError)


def test_nothing_in_here_can_call_anything():
    # The version this replaced used eval with an empty builtins dict.
    with pytest.raises(ExpressionError):
        evaluate_expression("__import__('os').getcwd()", {})


def test_an_attribute_access_is_not_an_expression():
    with pytest.raises(ExpressionError):
        evaluate_expression("().__class__", {})


def test_a_symbol_that_looks_like_a_builtin_is_still_just_a_symbol():
    assert evaluate_expression("len", {"len": 7}) == 7


def test_a_symbol_that_looks_like_a_builtin_and_is_not_defined():
    with pytest.raises(ExpressionError, match="unknown symbol"):
        evaluate_expression("len", {})


def test_a_very_deep_expression_does_not_explode():
    text = "(" * 40 + "1" + ")" * 40
    assert evaluate_expression(text, {}) == 1
