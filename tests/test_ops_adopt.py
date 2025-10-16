import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Origin, OriginKind
from v4t_translate.catalog.store import load_translations, save_translations
from v4t_translate.catalog.translations import Translation, TranslationState
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.errors import CatalogError, SourceError
from v4t_translate.ops.adopt import adopt_locale, adopt_translations, alignment_key
from v4t_translate.ops.extract import extract_project

GERMAN = Path(__file__).resolve().parent / "fixtures" / "v4t_sample_de.rc"

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]

[locale."zh-TW"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    # The fixture is checked in as UTF-8 because everything in this repository
    # is, and a real German .rc is cp1252. Converting here means the test
    # reads what the tool would actually be pointed at.
    (tmp_path / "src" / "V4T_de.rc").write_bytes(
        GERMAN.read_text(encoding="utf-8").encode("cp1252")
    )
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def german(project):
    return project.root / "src" / "V4T_de.rc"


def answers(project, tag="de-DE"):
    return load_translations(project.translations_path(tag))


def run(config, *args, verbose=False):
    before = ["-c", str(config.root / "v4t-translate.toml")]
    if verbose:
        before.append("-v")
    return CliRunner().invoke(main, [*before, *args])


# -- the alignment key --------------------------------------------------


def test_the_key_ignores_the_file_it_came_from():
    # The whole point is that the two copies have different names.
    english = Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                     container="IDD_MAIN", symbol="IDC_STATIC", line=10, ordinal=4)
    localised = Origin(source="V4T_de.rc", kind=OriginKind.DIALOG_CONTROL,
                       container="IDD_MAIN", symbol="IDC_STATIC", line=99, ordinal=4)
    assert alignment_key(english) == alignment_key(localised)


def test_the_key_separates_two_static_labels():
    first = Origin(source="a", kind=OriginKind.DIALOG_CONTROL,
                   container="IDD_MAIN", symbol="IDC_STATIC", ordinal=1)
    second = Origin(source="a", kind=OriginKind.DIALOG_CONTROL,
                    container="IDD_MAIN", symbol="IDC_STATIC", ordinal=2)
    assert alignment_key(first) != alignment_key(second)


def test_the_key_separates_two_dialogs():
    first = Origin(source="a", kind=OriginKind.DIALOG_CONTROL,
                   container="IDD_ONE", symbol="IDC_OK", ordinal=0)
    second = Origin(source="a", kind=OriginKind.DIALOG_CONTROL,
                    container="IDD_TWO", symbol="IDC_OK", ordinal=0)
    assert alignment_key(first) != alignment_key(second)


# -- adopting -----------------------------------------------------------


def test_a_dialog_label_is_lifted(project):
    adopt_locale(project, "de-DE", german(project))
    assert answers(project).get(message_key("Bar Height")).text == "Balkenhöhe"


def test_a_string_table_row_is_lifted(project):
    adopt_locale(project, "de-DE", german(project))
    assert answers(project).get(message_key("Print started")).text == "Druck gestartet"


def test_a_dialog_caption_is_lifted(project):
    adopt_locale(project, "de-DE", german(project))
    assert answers(project).get(message_key("Barcode Properties")).text == (
        "Barcode-Eigenschaften"
    )


def test_a_wrapped_string_survives(project):
    adopt_locale(project, "de-DE", german(project))
    text = answers(project).get(
        message_key("Purge offset must be less than group offset")).text
    assert text == "Bereinigungsversatz muss kleiner als Gruppenversatz sein"


def test_nothing_lands_approved(project):
    # It was written against an English that may have moved, by somebody who
    # is not here. Approved would tell the check it is all current.
    adopt_locale(project, "de-DE", german(project))
    states = {answers(project).get(key).state
              for key in answers(project).entries}
    assert TranslationState.APPROVED not in states


def test_everything_lands_needing_review(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert all(answers(project).get(key).state is TranslationState.NEEDS_REVIEW
               for key in result.adopted)


def test_the_origin_names_the_file(project):
    adopt_locale(project, "de-DE", german(project))
    assert answers(project).get(message_key("Bar Height")).origin == "V4T_de.rc"


def test_the_fingerprint_is_taken_against_todays_english(project):
    from v4t_translate.catalog.ids import source_fingerprint

    adopt_locale(project, "de-DE", german(project))
    entry = answers(project).get(message_key("Bar Height"))
    assert entry.fingerprint == source_fingerprint("Bar Height")


def test_something_was_adopted(project):
    assert len(adopt_locale(project, "de-DE", german(project)).adopted) > 10


# -- what it refuses to guess -------------------------------------------


def test_an_identical_string_is_not_adopted(project):
    # OK is OK in German. Either it was never translated or it genuinely does
    # not change, and neither is this operation's business.
    result = adopt_locale(project, "de-DE", german(project))
    assert message_key("OK") in result.unchanged
    assert not answers(project).get(message_key("OK")).text


def test_an_untranslated_string_shows_up_as_unchanged(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert message_key("Auto parity") in result.unchanged


def test_a_control_only_in_the_german_file_is_an_orphan(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert any("IDC_GERMAN_ONLY" in position for position in result.orphans)


def test_a_control_only_in_the_english_is_reported_missing(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert result.missing


def test_divergence_is_counted(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert result.divergence == len(result.orphans) + len(result.missing)


def test_divergence_produces_a_warning(project):
    result = adopt_locale(project, "de-DE", german(project))
    assert any("edited apart" in w for w in result.warnings)


# -- running it twice ---------------------------------------------------


def test_an_existing_translation_is_left_alone(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Höhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    result = adopt_locale(project, "de-DE", german(project))
    assert message_key("Bar Height") in result.already_answered
    assert answers(project).get(message_key("Bar Height")).text == "Höhe"


def test_overwrite_replaces_it(project):
    path = project.translations_path("de-DE")
    translations = load_translations(path)
    translations.set(message_key("Bar Height"),
                     Translation(text="Höhe", state=TranslationState.APPROVED))
    save_translations(path, translations)

    adopt_locale(project, "de-DE", german(project), overwrite=True)
    assert answers(project).get(message_key("Bar Height")).text == "Balkenhöhe"


def test_a_second_run_changes_nothing(project):
    adopt_locale(project, "de-DE", german(project))
    first = project.translations_path("de-DE").read_bytes()
    adopt_locale(project, "de-DE", german(project))
    assert project.translations_path("de-DE").read_bytes() == first


def test_a_dry_run_writes_nothing(project):
    before = project.translations_path("de-DE").read_bytes()
    result = adopt_locale(project, "de-DE", german(project), dry_run=True)
    assert result.adopted
    assert result.written is None
    assert project.translations_path("de-DE").read_bytes() == before


# -- refusals -----------------------------------------------------------


def test_a_missing_file_is_refused(project):
    with pytest.raises(SourceError, match="does not exist"):
        adopt_locale(project, "de-DE", project.root / "nope.rc")


def test_no_catalog_is_refused(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    # The fixture is checked in as UTF-8 because everything in this repository
    # is, and a real German .rc is cp1252. Converting here means the test
    # reads what the tool would actually be pointed at.
    (tmp_path / "src" / "V4T_de.rc").write_bytes(
        GERMAN.read_text(encoding="utf-8").encode("cp1252")
    )
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")

    with pytest.raises(CatalogError) as caught:
        adopt_locale(config, "de-DE", tmp_path / "src" / "V4T_de.rc")
    assert "no catalog yet" in caught.value.remedy


def test_an_unconfigured_language_is_refused(project):
    from v4t_translate.errors import ConfigError

    with pytest.raises(ConfigError):
        adopt_locale(project, "fr-FR", german(project))


# -- several at once ----------------------------------------------------


def test_two_languages_in_one_call(project):
    results = adopt_translations(project, [("de-DE", german(project))])
    assert [r.locale for r in results] == ["de-DE"]


def test_another_language_is_untouched(project):
    adopt_locale(project, "de-DE", german(project))
    assert not answers(project, "zh-TW").entries


# -- the command --------------------------------------------------------


def test_the_command_reports_what_it_did(project):
    output = run(project, "adopt", "de-DE", str(german(project))).output
    assert "adopted" in output


def test_the_command_warns_about_divergence(project):
    assert "edited apart" in run(project, "adopt", "de-DE",
                                 str(german(project))).output


def test_the_command_names_the_orphans(project):
    output = run(project, "adopt", "de-DE", str(german(project)),
                 verbose=True).output
    assert "IDC_GERMAN_ONLY" in output


def test_the_command_says_nothing_is_current(project):
    output = run(project, "adopt", "de-DE", str(german(project)),
                 verbose=True).output
    assert "needs-review" in output


def test_the_command_dry_run_writes_nothing(project):
    before = project.translations_path("de-DE").read_bytes()
    run(project, "adopt", "de-DE", str(german(project)), "--dry-run")
    assert project.translations_path("de-DE").read_bytes() == before


def test_the_command_is_registered():
    assert "adopt" in CliRunner().invoke(main, ["--help"]).output
