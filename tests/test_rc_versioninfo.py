import pytest

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.base import EmitOptions
from v4t_translate.emit.rcpack import RcEmitter
from v4t_translate.errors import ParseError
from v4t_translate.locales import resolve
from v4t_translate.sources.base import SourceOptions
from v4t_translate.sources.rc.extract import TRANSLATABLE_VERSION_FIELDS, RcSource
from v4t_translate.sources.rc.parser import parse_resource_script


@pytest.fixture(scope="module")
def script(sample_rc_text):
    return parse_resource_script(sample_rc_text, path="V4T.rc")


@pytest.fixture(scope="module")
def messages(sample_rc_path):
    extraction = RcSource().extract(
        SourceOptions(path=sample_rc_path, root=sample_rc_path.parent)
    )
    return {m.source_text: m for m in extraction.by_key().values()}


def test_the_version_block_is_parsed(script):
    assert len(script.versions) == 1
    assert script.versions[0].symbol == "VS_VERSION_INFO"


def test_it_is_no_longer_a_raw_block(script):
    assert "VERSIONINFO" not in {b.statement.upper() for b in script.raw_blocks}


def test_string_values_are_read(script):
    values = {v.name: v.text for v in script.version_values()}
    assert values["CompanyName"] == "Sellenis"
    assert values["FileDescription"] == "Thermal inkjet coder control"
    assert values["ProductName"] == "V4T Coder"


def test_a_numeric_value_is_not_a_string_value(script):
    assert script.versions[0].value("Translation") is None


def test_value_lookup_is_case_insensitive(script):
    assert script.versions[0].value("filedescription").text == (
        "Thermal inkjet coder control"
    )


def test_a_value_that_is_not_there(script):
    assert script.versions[0].value("PrivateBuild") is None


def test_values_carry_their_span(script):
    value = script.versions[0].value("FileDescription")
    assert script.text[value.span[0]:value.span[1]] == '"Thermal inkjet coder control"'


def test_values_carry_their_line(script):
    assert script.versions[0].value("CompanyName").line > 100


def test_counts_include_the_version_values(script):
    assert script.counts()["version_values"] == 6


def test_only_the_fields_people_read_are_extracted(messages):
    assert "Thermal inkjet coder control" in messages
    assert "V4T Coder" in messages


def test_legal_text_is_left_alone(messages):
    assert "Sellenis" not in messages
    assert "Copyright (C) 2024 Sellenis" not in messages


def test_a_file_name_is_not_a_message(messages):
    assert "V4T.exe" not in messages
    assert "4.1.0.0" not in messages


def test_the_translatable_field_list_is_what_it_says():
    assert TRANSLATABLE_VERSION_FIELDS == {"filedescription", "productname", "comments"}


def test_the_origin_names_the_field(messages):
    origin = messages["Thermal inkjet coder control"].origins[0]
    assert origin.kind is OriginKind.VERSION_INFO
    assert origin.symbol == "FileDescription"
    assert origin.container == "VS_VERSION_INFO"


def test_the_note_says_where_it_shows(messages):
    note = messages["V4T Coder"].developer_note
    assert "Explorer" in note


def test_the_version_block_survives_a_localised_write(tmp_path, sample_rc_path,
                                                      messages):
    catalog = Catalog(project="V4T-TIJ")
    for message in messages.values():
        catalog.add(message)

    entries = TranslationSet(locale="de-DE")
    entries.set(message_key("Thermal inkjet coder control"),
                Translation(text="Thermotintenstrahl-Codierersteuerung",
                            state=TranslationState.APPROVED))

    path = tmp_path / "V4T.de-DE.rc"
    RcEmitter().emit(
        catalog, entries,
        EmitOptions(path=path, locale=resolve("de-DE"), source_path=sample_rc_path),
    )
    text = path.read_text(encoding="cp1252")

    assert 'VALUE "FileDescription", "Thermotintenstrahl-Codierersteuerung"' in text
    assert 'VALUE "CompanyName", "Sellenis"' in text
    assert 'VALUE "Translation", 0x409, 1200' in text


def test_an_unterminated_version_block_is_reported():
    with pytest.raises(ParseError, match="unterminated VERSIONINFO"):
        parse_resource_script(
            'VS_VERSION_INFO VERSIONINFO\nBEGIN\n  VALUE "a", "b"\n'
        )


def test_a_version_block_with_no_body_does_not_hang():
    script = parse_resource_script(
        "VS_VERSION_INFO VERSIONINFO\n FILEVERSION 1,0,0,0\n"
        'IDD_X DIALOGEX 0,0,10,10\nBEGIN\n  LTEXT "a",IDC_STATIC,1,1,1,1\nEND\n'
    )
    assert script.versions[0].values == []
    assert script.dialog("IDD_X") is not None


def test_nested_blocks_are_walked():
    script = parse_resource_script(
        'X VERSIONINFO\nBEGIN\n'
        '  BLOCK "StringFileInfo"\n  BEGIN\n'
        '    BLOCK "040904b0"\n    BEGIN\n'
        '      VALUE "FileDescription", "deep"\n'
        "    END\n  END\nEND\n"
    )
    assert script.versions[0].value("FileDescription").text == "deep"
