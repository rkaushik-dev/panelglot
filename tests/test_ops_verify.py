import pytest
from click.testing import CliRunner

from v4t_translate.cli import main
from v4t_translate.emit.v4l import FLAG_RTL, build_pack, table_signature
from v4t_translate.errors import EmitError
from v4t_translate.ops.verify import signature_of_header, verify_pack

SYMBOLS = [
    "LNG_PRINT_STARTED", "LNG_PRINT_STOPPED", "LNG_PURGE_SETTINGS",
    "LNG_FIRING_VOLTAGE", "LNG_PEN", "LNG_SPACING", "LNG_UNITS_MM",
    "LNG_LOW_INK", "LNG_CONFIRM_PURGE",
]

GERMAN = [
    "Druck gestartet", "Druck gestoppt", "Bereinigung", "Zündspannung",
    "Stift", "Abstand", "mm", "Wenig Tinte in Stift %d", "Alle spülen?",
]


@pytest.fixture
def header(fixtures_dir):
    return fixtures_dir / "v4t_lang.h"


def write_pack(tmp_path, *, symbols=None, tag="de-DE", lcid=0x0407,
               codepage=1252, rtl=False, strings=None, name="de-DE.v4l"):
    data = build_pack(
        strings if strings is not None else GERMAN,
        symbols if symbols is not None else SYMBOLS,
        tag=tag, lcid=lcid, codepage=codepage, rtl=rtl,
    )
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_the_signature_comes_out_of_the_enum(header):
    assert signature_of_header(header) == table_signature(SYMBOLS)


def test_the_count_sentinel_is_not_part_of_it(header):
    assert signature_of_header(header) != table_signature([*SYMBOLS, "LNG_COUNT"])


def test_a_header_with_no_enum(tmp_path):
    path = tmp_path / "empty.h"
    path.write_text("#define X 1\n", encoding="utf-8")
    with pytest.raises(EmitError, match="no enum"):
        signature_of_header(path)


def test_a_header_that_is_not_there(tmp_path):
    with pytest.raises(EmitError, match="does not exist"):
        signature_of_header(tmp_path / "nope.h")


def test_a_matching_pack_is_accepted(tmp_path, header):
    result = verify_pack(write_pack(tmp_path), header=header)
    assert result.accepted
    assert result.problems == []
    assert "would be accepted" in result.summary()


def test_the_description_reads(tmp_path, header):
    result = verify_pack(write_pack(tmp_path), header=header)
    text = result.describe()
    assert "de-DE" in text
    assert "9 strings" in text
    assert "codepage 1252" in text


def test_an_inserted_enum_id_is_caught(tmp_path, header):
    shifted = [SYMBOLS[0], "LNG_NEW_THING", *SYMBOLS[1:]]
    path = write_pack(tmp_path, symbols=shifted, strings=[*GERMAN, "Neu"])

    result = verify_pack(path, header=header)
    assert not result.accepted
    assert "does not match the firmware" in result.problems[0]
    assert "shifted" in result.problems[0]


def test_a_renamed_enum_id_is_caught(tmp_path, header):
    renamed = ["LNG_PRINT_BEGAN", *SYMBOLS[1:]]
    result = verify_pack(write_pack(tmp_path, symbols=renamed), header=header)
    assert not result.accepted


def test_no_header_means_no_signature_check(tmp_path):
    renamed = ["LNG_PRINT_BEGAN", *SYMBOLS[1:]]
    result = verify_pack(write_pack(tmp_path, symbols=renamed))
    assert result.accepted
    assert result.expected_signature is None


def test_the_expected_locale_can_be_insisted_on(tmp_path, header):
    result = verify_pack(write_pack(tmp_path), header=header, expect_locale="de-DE")
    assert result.accepted


def test_the_wrong_locale_is_caught(tmp_path, header):
    result = verify_pack(write_pack(tmp_path), header=header, expect_locale="zh-TW")
    assert not result.accepted
    assert "zh-TW was expected" in result.problems[0]


def test_a_locale_alias_is_accepted(tmp_path, header):
    assert verify_pack(write_pack(tmp_path), expect_locale="German").accepted


def test_a_locale_nobody_knows(tmp_path):
    result = verify_pack(write_pack(tmp_path), expect_locale="Klingon")
    assert not result.accepted


def test_a_wrong_locale_id_is_caught(tmp_path):
    result = verify_pack(write_pack(tmp_path, lcid=0x0409), expect_locale="de-DE")
    assert not result.accepted
    assert "locale id" in result.problems[0]


def test_empty_slots_are_noted(tmp_path):
    strings = ["Druck gestartet", "", "", *GERMAN[3:]]
    result = verify_pack(write_pack(tmp_path, strings=strings))
    assert result.accepted
    assert any("2 of 9 slots are empty" in note for note in result.notes)


HEBREW = ["הדפסה", "עצירה", "ניקוי", "מתח", "עט", "מרווח", "mm", "דיו", "לנקות?"]


def test_a_right_to_left_language_without_the_flag_is_noted(tmp_path):
    result = verify_pack(write_pack(tmp_path, tag="he-IL", lcid=0x040D,
                                    codepage=1255, strings=HEBREW))
    assert any("right to left" in note for note in result.notes)
    assert result.accepted


def test_a_right_to_left_pack_with_the_flag_is_quiet(tmp_path):
    result = verify_pack(write_pack(tmp_path, tag="he-IL", lcid=0x040D,
                                    codepage=1255, rtl=True, strings=HEBREW))
    assert not any("right to left" in note for note in result.notes)
    assert FLAG_RTL & result.pack.flags


def test_a_double_byte_language_in_an_eight_bit_pack_is_noted(tmp_path):
    result = verify_pack(write_pack(tmp_path, tag="ja-JP", lcid=0x0411,
                                    codepage=932,
                                    strings=["a"] * 9))
    assert any("more than one byte" in note for note in result.notes)


def test_a_language_this_build_does_not_know(tmp_path):
    result = verify_pack(write_pack(tmp_path, tag="eo-XX", lcid=0))
    assert any("not a language this build knows" in note for note in result.notes)


def test_a_pack_that_is_not_there(tmp_path):
    with pytest.raises(EmitError, match="does not exist"):
        verify_pack(tmp_path / "nope.v4l")


def test_a_damaged_pack_is_refused_by_the_reader(tmp_path):
    path = write_pack(tmp_path)
    data = bytearray(path.read_bytes())
    data[-3] ^= 0xFF
    path.write_bytes(bytes(data))

    with pytest.raises(EmitError, match="checksum"):
        verify_pack(path)


def test_the_command_line_accepts_a_good_pack(tmp_path, header):
    runner = CliRunner()
    result = runner.invoke(main, [
        "verify", str(write_pack(tmp_path)), "-H", str(header),
    ])
    assert result.exit_code == 0
    assert "de-DE, 9 strings" in result.output


def test_the_command_line_refuses_a_shifted_pack(tmp_path, header):
    shifted = [SYMBOLS[0], "LNG_NEW_THING", *SYMBOLS[1:]]
    path = write_pack(tmp_path, symbols=shifted, strings=[*GERMAN, "Neu"])

    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(path), "-H", str(header)])
    assert result.exit_code != 0
    assert "does not match the firmware" in result.output


def test_the_command_line_takes_several_packs(tmp_path, header):
    first = write_pack(tmp_path, name="a.v4l")
    second = write_pack(tmp_path, name="b.v4l")

    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(first), str(second), "-H", str(header)])
    assert result.exit_code == 0
    assert result.output.count("9 strings") == 2


def test_the_command_line_shows_notes_when_verbose(tmp_path):
    path = write_pack(tmp_path, strings=["", *GERMAN[1:]])
    runner = CliRunner()
    quiet = runner.invoke(main, ["verify", str(path)]).output
    loud = runner.invoke(main, ["-v", "verify", str(path)]).output
    assert "slots are empty" not in quiet
    assert "slots are empty" in loud
