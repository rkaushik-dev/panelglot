import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog, load_catalog, load_translations
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.extract import extract_project
from v4t_translate.ops.sync import export_workbooks, import_workbook, split_by_container

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


def catalog_of(*groups):
    """Build a catalog from (container, count) pairs."""
    catalog = Catalog(project="V4T-TIJ")
    for container, count in groups:
        for number in range(count):
            key = f"{container}.{number}"
            catalog.add(Message(
                key=key,
                source_text=f"{container} {number}",
                origins=[Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                                container=container, symbol="IDC_STATIC",
                                line=number)],
            ))
    return catalog


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    config = load_config(tmp_path / "v4t-translate.toml")
    extract_project(config)
    return config


def run(config, *args, verbose=False):
    before = ["-c", str(config.root / "v4t-translate.toml")]
    if verbose:
        before.append("-v")
    return CliRunner().invoke(main, [*before, "export", *args])


# -- the split ----------------------------------------------------------


def test_one_part_is_the_whole_catalog():
    catalog = catalog_of(("A", 3), ("B", 2))
    assert split_by_container(catalog, 1) == [set(catalog.messages)]


def test_zero_or_fewer_parts_is_the_whole_catalog():
    catalog = catalog_of(("A", 3))
    assert split_by_container(catalog, 0) == [set(catalog.messages)]


def test_every_key_lands_somewhere():
    catalog = catalog_of(("A", 5), ("B", 3), ("C", 4))
    buckets = split_by_container(catalog, 3)
    assert set().union(*buckets) == set(catalog.messages)


def test_no_key_lands_twice():
    catalog = catalog_of(("A", 5), ("B", 3), ("C", 4))
    buckets = split_by_container(catalog, 3)
    assert sum(len(b) for b in buckets) == len(catalog.messages)


def test_a_dialog_is_never_divided():
    catalog = catalog_of(("A", 9), ("B", 1))
    buckets = split_by_container(catalog, 2)
    for bucket in buckets:
        containers = {key.split(".")[0] for key in bucket}
        assert len(containers) <= 2
    holder = next(b for b in buckets if "A.0" in b)
    assert all(f"A.{n}" in holder for n in range(9))


def test_the_parts_are_roughly_even():
    catalog = catalog_of(*[(chr(65 + n), 4) for n in range(8)])
    sizes = [len(b) for b in split_by_container(catalog, 4)]
    assert max(sizes) - min(sizes) <= 4


def test_one_huge_dialog_makes_them_uneven_and_that_is_correct():
    catalog = catalog_of(("A", 90), ("B", 2), ("C", 2))
    sizes = sorted(len(b) for b in split_by_container(catalog, 3))
    assert sizes[-1] == 90


def test_asking_for_more_parts_than_dialogs_leaves_some_empty():
    catalog = catalog_of(("A", 3), ("B", 3))
    buckets = split_by_container(catalog, 4)
    assert len(buckets) == 4
    assert sum(1 for b in buckets if not b) == 2


def test_loose_strings_get_their_own_group():
    catalog = Catalog(project="p")
    catalog.add(Message(key="a.1", source_text="A"))
    buckets = split_by_container(catalog, 2)
    assert set().union(*buckets) == {"a.1"}


def test_the_split_is_stable_between_runs():
    catalog = catalog_of(("A", 5), ("B", 3), ("C", 4), ("D", 4))
    assert split_by_container(catalog, 2) == split_by_container(catalog, 2)


# -- exporting ----------------------------------------------------------


def test_one_part_keeps_the_old_file_name(project):
    result = export_workbooks(project)
    assert " part " not in result.written[0][1].name


def test_two_parts_are_two_files(project):
    result = export_workbooks(project, parts=2)
    assert len(result.written) == 2
    assert all(path.exists() for _, path, _ in result.written)


def test_the_part_files_are_named_for_their_part(project):
    result = export_workbooks(project, parts=2)
    names = [path.name for _, path, _ in result.written]
    assert any("part 1 of 2" in name for name in names)
    assert any("part 2 of 2" in name for name in names)


def test_the_rows_add_up_to_one_whole_export(project):
    whole = export_workbooks(project)
    split = export_workbooks(project, parts=3)
    assert sum(rows for _, _, rows in split.written) == whole.written[0][2]


def test_each_part_has_some_rows(project):
    split = export_workbooks(project, parts=2)
    assert all(rows > 0 for _, _, rows in split.written)


def test_outstanding_still_applies_to_a_part(project):
    split = export_workbooks(project, parts=2, only_outstanding=True)
    assert sum(rows for _, _, rows in split.written) > 0


# -- merging back -------------------------------------------------------


def test_both_halves_import_into_one_catalog(project):
    from openpyxl import load_workbook

    result = export_workbooks(project, parts=2)
    paths = [path for _, path, _ in result.written]

    # Fill each half in, then import them in turn.
    for index, path in enumerate(paths):
        book = load_workbook(path)
        sheet = book.worksheets[0]
        for row in range(2, sheet.max_row + 1):
            source = sheet.cell(row=row, column=2).value
            if source:
                sheet.cell(row=row, column=3, value=f"[{index}] {source}")
        book.save(path)

    for path in paths:
        import_workbook(project, path)

    catalog = load_catalog(project.catalog_path())
    translations = load_translations(project.translations_path("de-DE"))
    answered = sum(1 for key in catalog.messages if translations.get(key).text)
    assert answered == len(catalog.messages)


def test_the_order_they_are_imported_in_does_not_matter(project):
    from openpyxl import load_workbook

    def fill(paths):
        for path in paths:
            book = load_workbook(path)
            sheet = book.worksheets[0]
            for row in range(2, sheet.max_row + 1):
                source = sheet.cell(row=row, column=2).value
                if source:
                    sheet.cell(row=row, column=3, value=f"<{source}>")
            book.save(path)

    paths = [path for _, path, _ in export_workbooks(project, parts=2).written]
    fill(paths)

    for path in paths:
        import_workbook(project, path)
    forwards = project.translations_path("de-DE").read_text(encoding="utf-8")

    project.translations_path("de-DE").unlink()
    for path in reversed(paths):
        import_workbook(project, path)
    backwards = project.translations_path("de-DE").read_text(encoding="utf-8")

    assert forwards == backwards


# -- the command --------------------------------------------------------


def test_the_command_splits(project):
    output = run(project, "--parts", "2").output
    assert "part 1 of 2" in output
    assert "part 2 of 2" in output


def test_the_command_explains_why_they_are_uneven(project):
    output = run(project, "--parts", "2", verbose=True).output
    assert "one person's afternoon" in output


def test_one_part_says_nothing_about_parts(project):
    output = run(project, verbose=True).output
    assert "part 1 of" not in output
    assert "one person's afternoon" not in output


def test_zero_parts_is_refused(project):
    result = run(project, "--parts", "0")
    assert result.exit_code != 0
    assert "at least 1" in result.output
