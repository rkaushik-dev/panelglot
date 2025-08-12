import shutil
from xml.etree import ElementTree

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.emit.registry import available_kinds, get_emitter
from v4t_translate.emit.xliff import (
    XLIFF_NAMESPACE,
    read_xliff,
    state_for,
    state_from,
)
from v4t_translate.errors import SourceError
from v4t_translate.ops.build import build_project
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.sync import import_xliff_file

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[[output]]
kind = "xliff"
path = "out/{locale}.xlf"
source = "src/V4T.rc"
"""

MINIMAL = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="V4T.rc" datatype="winres" source-language="en-US"
        target-language="de-DE">
    <body>
      <trans-unit id="bar-height.9a2f1c">
        <source>Bar Height</source>
        <target state="final">Balkenhöhe</target>
      </trans-unit>
    </body>
  </file>
</xliff>
"""


def strip(tag):
    return tag.rsplit("}", 1)[-1]


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def translate(config, pairs, state=TranslationState.APPROVED):
    path = config.translations_path("de-DE")
    translations = load_translations(path)
    for source, target in pairs.items():
        translations.set(message_key(source), Translation(text=target, state=state))
    save_translations(path, translations)


def built(config):
    build_project(config)
    return (config.root / "out" / "de-DE.xlf").read_text(encoding="utf-8")


# -- the emitter --------------------------------------------------------


def test_the_kind_is_registered():
    assert "xliff" in available_kinds()
    assert get_emitter("xliff").kind == "xliff"


def test_the_output_is_well_formed_xml(project):
    translate(project, {"Bar Height": "Balkenhöhe"})
    ElementTree.fromstring(built(project))


def test_the_root_declares_the_namespace_and_version(project):
    root = ElementTree.fromstring(built(project))
    assert root.get("version") == "1.2"
    assert XLIFF_NAMESPACE in root.tag


def test_the_file_element_names_both_languages(project):
    root = ElementTree.fromstring(built(project))
    element = next(c for c in root if strip(c.tag) == "file")
    assert element.get("source-language") == "en-US"
    assert element.get("target-language") == "de-DE"
    assert element.get("datatype") == "winres"


def test_the_original_is_the_source_file(project):
    root = ElementTree.fromstring(built(project))
    element = next(c for c in root if strip(c.tag) == "file")
    assert element.get("original") == "V4T.rc"


def test_the_unit_id_is_the_message_key(project):
    translate(project, {"Bar Height": "Balkenhöhe"})
    units = [u for u in ElementTree.fromstring(built(project)).iter()
             if strip(u.tag) == "trans-unit"]
    assert message_key("Bar Height") in {u.get("id") for u in units}


def test_a_translated_unit_carries_its_target(project):
    translate(project, {"Bar Height": "Balkenhöhe"})
    root = ElementTree.fromstring(built(project))
    unit = next(u for u in root.iter()
                if strip(u.tag) == "trans-unit"
                and u.get("id") == message_key("Bar Height"))
    target = next(c for c in unit if strip(c.tag) == "target")
    assert target.text == "Balkenhöhe"
    assert target.get("state") == "final"


def test_an_untranslated_unit_is_written_with_an_empty_target(project):
    root = ElementTree.fromstring(built(project))
    states = {next(c for c in u if strip(c.tag) == "target").get("state")
              for u in root.iter() if strip(u.tag) == "trans-unit"}
    assert "new" in states


def test_special_characters_are_escaped(project):
    translate(project, {"Bar Height": "A & B < C"})
    text = built(project)
    assert "A &amp; B &lt; C" in text
    ElementTree.fromstring(text)


def test_the_result_counts_what_was_translated(project):
    translate(project, {"Bar Height": "Balkenhöhe"})
    result = build_project(project)
    emitted = result.outputs[0][2]
    assert emitted.written == 1
    assert emitted.skipped


def test_a_resname_carries_the_origin(project):
    root = ElementTree.fromstring(built(project))
    resnames = [u.get("resname") for u in root.iter() if strip(u.tag) == "trans-unit"]
    assert any(name and "V4T.rc" in name for name in resnames)


def test_a_protected_message_is_marked_untranslatable(project):
    root = ElementTree.fromstring(built(project))
    marked = [u for u in root.iter()
              if strip(u.tag) == "trans-unit" and u.get("translate") == "no"]
    assert marked


def test_a_note_reaches_the_file(project):
    root = ElementTree.fromstring(built(project))
    notes = [n.text for n in root.iter() if strip(n.tag) == "note"]
    assert any(notes)


def test_the_output_is_stable_across_runs(project):
    translate(project, {"Bar Height": "Balkenhöhe"})
    assert built(project) == built(project)


# -- the state table ----------------------------------------------------


@pytest.mark.parametrize("state", list(TranslationState))
def test_every_state_of_ours_has_an_xliff_name(state):
    assert state_for(state)


@pytest.mark.parametrize(
    "state",
    [TranslationState.EMPTY, TranslationState.DRAFT,
     TranslationState.NEEDS_REVIEW, TranslationState.APPROVED],
)
def test_those_states_round_trip(state):
    assert state_from(state_for(state)) is state


def test_do_not_translate_comes_back_as_approved():
    # XLIFF says that with an attribute on the unit, not with a state.
    assert state_from(state_for(TranslationState.DO_NOT_TRANSLATE)) is (
        TranslationState.APPROVED
    )


def test_an_unknown_state_never_becomes_approved():
    assert state_from("proofread") is TranslationState.NEEDS_REVIEW


def test_a_missing_state_never_becomes_approved():
    assert state_from(None) is TranslationState.NEEDS_REVIEW
    assert state_from("") is TranslationState.NEEDS_REVIEW


def test_the_state_is_read_case_insensitively():
    assert state_from(" FINAL ") is TranslationState.APPROVED


def test_signed_off_is_approved():
    assert state_from("signed-off") is TranslationState.APPROVED


def test_translated_is_not_approved():
    # A tool that marks everything translated on export has not reviewed it.
    assert state_from("translated") is TranslationState.NEEDS_REVIEW


# -- reading ------------------------------------------------------------


def test_reading_a_minimal_file():
    read = read_xliff(MINIMAL)
    assert read.locale == "de-DE"
    assert read.get("bar-height.9a2f1c").text == "Balkenhöhe"


def test_the_state_comes_back():
    assert read_xliff(MINIMAL).get("bar-height.9a2f1c").state is (
        TranslationState.APPROVED
    )


def test_a_file_without_a_namespace_still_reads():
    assert read_xliff(MINIMAL.replace(
        ' xmlns="urn:oasis:names:tc:xliff:document:1.2"', "")).entries


def test_inline_markup_is_flattened():
    text = MINIMAL.replace(
        "<target state=\"final\">Balkenhöhe</target>",
        '<target state="final">Balken<ph id="1">%d</ph>höhe</target>',
    )
    assert read_xliff(text).get("bar-height.9a2f1c").text == "Balken%dhöhe"


def test_a_unit_with_no_target_is_skipped():
    text = MINIMAL.replace('<target state="final">Balkenhöhe</target>', "")
    assert not read_xliff(text).entries


def test_broken_xml_is_refused():
    with pytest.raises(SourceError, match="not valid XML"):
        read_xliff("<xliff>")


def test_the_wrong_root_is_refused():
    with pytest.raises(SourceError, match="not xliff"):
        read_xliff("<tmx></tmx>")


def test_a_document_with_no_file_element_is_refused():
    with pytest.raises(SourceError, match="no file element"):
        read_xliff('<xliff version="1.2"></xliff>')


def test_a_unit_without_an_id_is_refused():
    with pytest.raises(SourceError, match="no id"):
        read_xliff(MINIMAL.replace(' id="bar-height.9a2f1c"', ""))


def test_a_duplicate_id_is_refused():
    doubled = MINIMAL.replace(
        "</body>",
        '<trans-unit id="bar-height.9a2f1c"><source>x</source>'
        '<target state="final">y</target></trans-unit></body>',
    )
    with pytest.raises(SourceError, match="duplicate"):
        read_xliff(doubled)


def test_the_path_appears_in_the_error():
    with pytest.raises(SourceError, match="delivery.xlf"):
        read_xliff("<xliff>", path="delivery.xlf")


# -- the round trip -----------------------------------------------------


def test_what_goes_out_comes_back(project, tmp_path):
    translate(project, {"Bar Height": "Balkenhöhe", "Print started": "Druck gestartet"})
    build_project(project)

    delivered = tmp_path / "delivery.xlf"
    delivered.write_text((project.root / "out" / "de-DE.xlf").read_text("utf-8"),
                         encoding="utf-8")

    # Wipe the catalog side, then import the file back over it.
    save_translations(project.translations_path("de-DE"),
                      load_translations(tmp_path / "nothing.json"))

    result = import_xliff_file(project, delivered)
    after = load_translations(project.translations_path("de-DE"))
    assert after.get(message_key("Bar Height")).text == "Balkenhöhe"
    assert result.applied


def test_the_locale_comes_from_the_file(project, tmp_path):
    delivered = tmp_path / "d.xlf"
    delivered.write_text(MINIMAL, encoding="utf-8")
    assert import_xliff_file(project, delivered, dry_run=True).locale == "de-DE"


def test_a_unit_naming_nothing_is_reported(project, tmp_path):
    delivered = tmp_path / "d.xlf"
    delivered.write_text(MINIMAL.replace("bar-height.9a2f1c", "gone.000000"),
                         encoding="utf-8")
    result = import_xliff_file(project, delivered, dry_run=True)
    assert len(result.unmatched) == 1
    assert result.ambiguous == []


def test_nothing_is_ever_ambiguous(project, tmp_path):
    # The whole reason for reading XLIFF rather than a spreadsheet.
    translate(project, {"Bar Height": ""})
    build_project(project)
    delivered = tmp_path / "d.xlf"
    delivered.write_text((project.root / "out" / "de-DE.xlf").read_text("utf-8"),
                         encoding="utf-8")
    assert import_xliff_file(project, delivered, dry_run=True).ambiguous == []


def test_a_dry_run_writes_nothing(project, tmp_path):
    before = project.translations_path("de-DE").read_bytes()
    delivered = tmp_path / "d.xlf"
    delivered.write_text(MINIMAL, encoding="utf-8")
    import_xliff_file(project, delivered, dry_run=True)
    assert project.translations_path("de-DE").read_bytes() == before


def test_a_file_with_no_language_and_no_override_is_refused(project, tmp_path):
    delivered = tmp_path / "d.xlf"
    delivered.write_text(MINIMAL.replace('target-language="de-DE"', ""),
                         encoding="utf-8")
    with pytest.raises(Exception, match="target-language"):
        import_xliff_file(project, delivered, dry_run=True)


def test_the_override_wins(project, tmp_path):
    delivered = tmp_path / "d.xlf"
    delivered.write_text(MINIMAL.replace('target-language="de-DE"',
                                         'target-language="fr-FR"'),
                         encoding="utf-8")
    result = import_xliff_file(project, delivered, locale="de-DE", dry_run=True)
    assert result.locale == "de-DE"


# -- through the command line -------------------------------------------


def test_the_import_command_takes_an_xlf(project, tmp_path):
    translate(project, {"Bar Height": "Balkenhöhe"})
    build_project(project)
    delivered = tmp_path / "delivery.xlf"
    delivered.write_text((project.root / "out" / "de-DE.xlf").read_text("utf-8"),
                         encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "import", str(delivered), "--dry-run",
    ])
    assert result.exit_code == 0
    assert "rows:" in result.output


def test_sheet_is_meaningless_for_xliff(project, tmp_path):
    delivered = tmp_path / "d.xliff"
    delivered.write_text(MINIMAL, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        "-c", str(project.root / "v4t-translate.toml"),
        "import", str(delivered), "--sheet", "Sheet1", "--dry-run",
    ])
    assert "means nothing for an XLIFF delivery" in result.output
