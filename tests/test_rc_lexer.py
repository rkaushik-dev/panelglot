import pytest

from v4t_translate.errors import ParseError
from v4t_translate.sources.rc.lexer import tokenize, unescape_rc_string
from v4t_translate.sources.rc.tokens import TokenKind


def kinds(text):
    return [t.kind for t in tokenize(text)[:-1]]


def values(text):
    return [t.value for t in tokenize(text) if t.kind is TokenKind.STRING]


def test_empty_input_is_just_eof():
    tokens = tokenize("")
    assert len(tokens) == 1
    assert tokens[0].kind is TokenKind.EOF


def test_identifier_number_and_string():
    assert kinds('IDD_ABOUT DIALOGEX 0, 0, 187, 92') == [
        TokenKind.IDENT,
        TokenKind.IDENT,
        TokenKind.NUMBER,
        TokenKind.COMMA,
        TokenKind.NUMBER,
        TokenKind.COMMA,
        TokenKind.NUMBER,
        TokenKind.COMMA,
        TokenKind.NUMBER,
    ]


def test_begin_and_end_words_become_block_tokens():
    assert kinds("BEGIN END") == [TokenKind.BEGIN, TokenKind.END]


def test_braces_are_the_same_tokens_as_begin_and_end():
    assert kinds("{ }") == [TokenKind.BEGIN, TokenKind.END]


def test_begin_is_case_insensitive():
    assert kinds("Begin end") == [TokenKind.BEGIN, TokenKind.END]


def test_line_comments_are_dropped():
    assert kinds("IDC_OK // this is the ok button\nIDC_CANCEL") == [
        TokenKind.IDENT,
        TokenKind.IDENT,
    ]


def test_block_comments_are_dropped():
    assert kinds("A /* out\nof\nline */ B") == [TokenKind.IDENT, TokenKind.IDENT]


def test_unterminated_block_comment_points_at_its_start():
    with pytest.raises(ParseError) as excinfo:
        tokenize("A\n/* never closed\nB", path="V4T.rc")
    assert excinfo.value.line == 2


def test_a_comment_marker_inside_a_string_is_text():
    assert values('"http://example.test/a"') == ["http://example.test/a"]


def test_directives_survive_whole():
    tokens = tokenize('#include "resource.h"\nIDD_X DIALOG')
    assert tokens[0].kind is TokenKind.DIRECTIVE
    assert tokens[0].text == '#include "resource.h"'


def test_a_hash_that_is_not_in_column_one_is_not_a_directive():
    with pytest.raises(ParseError):
        tokenize("IDD_X #define")


def test_continued_directive_is_one_token():
    tokens = tokenize("#define LONG_THING (A | \\\n    B)\n")
    assert tokens[0].kind is TokenKind.DIRECTIVE
    assert "A |" in tokens[0].text
    assert "B)" in tokens[0].text


def test_hex_numbers():
    tokens = tokenize("0x50000000 0X10")
    assert tokens[0].value == 0x50000000
    assert tokens[1].value == 16


def test_integer_suffix_is_swallowed():
    tokens = tokenize("40001L 12u")
    assert tokens[0].value == 40001
    assert tokens[1].value == 12


def test_wide_string_prefix_is_dropped():
    assert values('L"Firing Voltage"') == ["Firing Voltage"]


def test_doubled_quote_is_one_quote():
    assert values('"Say ""hello"" now"') == ['Say "hello" now']


def test_string_running_off_the_end_of_the_file_is_an_error():
    with pytest.raises(ParseError) as excinfo:
        tokenize('IDS_X\n"never closed', path="V4T.rc")
    assert excinfo.value.line == 2
    assert "unterminated string" in str(excinfo.value)


def test_newline_inside_a_string_is_an_error():
    with pytest.raises(ParseError, match="newline inside string"):
        tokenize('"broken\nacross lines"')


def test_unexpected_character_is_reported_with_position():
    with pytest.raises(ParseError) as excinfo:
        tokenize("IDD_X\n  @\n", path="V4T.rc")
    assert excinfo.value.line == 2
    assert excinfo.value.column == 3


def test_columns_are_one_based():
    tokens = tokenize("AB CD")
    assert (tokens[0].line, tokens[0].column) == (1, 1)
    assert (tokens[1].line, tokens[1].column) == (1, 4)


def test_token_is_ident_matches_case_insensitively():
    token = tokenize("Pushbutton")[0]
    assert token.is_ident("PUSHBUTTON")
    assert not token.is_ident("LTEXT")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        (r"line\nbreak", "line\nbreak"),
        (r"tab\there", "tab\there"),
        (r"back\\slash", "back\\slash"),
        (r"quote\"inside", 'quote"inside'),
        ('doubled""quote', 'doubled"quote'),
        (r"\x41\x42", "AB"),
        (r"\101\102", "AB"),
        (r"\q", "q"),
        ("trailing\\", "trailing\\"),
        (r"\x", "x"),
    ],
)
def test_unescape(raw, expected):
    assert unescape_rc_string(raw) == expected


def test_ampersands_are_left_alone():
    # The mnemonic rule needs to see these, so the lexer must not touch them.
    assert unescape_rc_string("Date&&Time Format") == "Date&&Time Format"
    assert unescape_rc_string("&Print") == "&Print"


def test_a_real_looking_control_line():
    text = 'LTEXT           "Bar Height",IDC_STATIC,7,26,40,8'
    tokens = tokenize(text)
    assert tokens[0].is_ident("LTEXT")
    assert tokens[1].value == "Bar Height"
    assert tokens[3].text == "IDC_STATIC"
