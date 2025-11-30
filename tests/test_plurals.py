from xml.etree import ElementTree

import pytest

from v4t_translate.analyses.plurals import PluralAnalysis
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.catalog.store import Catalog
from v4t_translate.catalog.translations import (
    Translation,
    TranslationSet,
    TranslationState,
)
from v4t_translate.emit.androidxml import AndroidXmlEmitter
from v4t_translate.emit.base import EmitOptions
from v4t_translate.layout.font import monospace
from v4t_translate.layout.panels import get_panel
from v4t_translate.locales import resolve
from v4t_translate.plurals import (
    CATEGORIES,
    categories_for,
    extra_categories,
    missing_categories,
)
from v4t_translate.rules.base import RuleContext
from v4t_translate.rules.result import Severity


def context(tag="pl-PL"):
    return RuleContext(
        locale=resolve(tag),
        panel=get_panel("mobile"),
        font=monospace(6, ranges=[(0x20, 0xFFFF)]),
    )


def catalog_of(*symbols):
    """A catalog holding one Android message per symbol."""
    catalog = Catalog(project="V4T-Mobile")
    for index, symbol in enumerate(symbols):
        base = symbol.partition("[")[0]
        catalog.add(Message(
            key=f"k{index}.{index:06x}",
            source_text=f"{symbol} in English",
            origins=[Origin(source="res/values/strings.xml",
                            kind=OriginKind.ANDROID_STRING,
                            container=base, symbol=symbol)],
        ))
    return catalog


def answers(catalog, *symbols):
    """Translate exactly the messages whose symbol is listed."""
    wanted = set(symbols)
    translations = TranslationSet(locale="pl-PL")
    for key, message in catalog.messages.items():
        if any(o.symbol in wanted for o in message.origins):
            translations.set(key, Translation(text=f"[{message.source_text}]",
                                              state=TranslationState.APPROVED))
    return translations


def run(catalog, translations, tag="pl-PL"):
    return list(PluralAnalysis().run(catalog, translations, context(tag)))


# -- the table ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("en-US", ("one", "other")),
        ("de-DE", ("one", "other")),
        ("zh-TW", ("other",)),
        ("ja-JP", ("other",)),
        ("pl-PL", ("one", "few", "many", "other")),
        ("ru-RU", ("one", "few", "many", "other")),
        ("ar-SA", ("zero", "one", "two", "few", "many", "other")),
        ("ro-RO", ("one", "few", "other")),
        ("fr-FR", ("one", "many", "other")),
    ],
)
def test_the_categories_per_language(tag, expected):
    assert categories_for(tag) == expected


def test_a_language_nobody_listed_gets_two():
    # Guessing more would put empty items in front of a translator for
    # categories their language may not have.
    assert categories_for("sw-KE") == ("one", "other")


def test_the_region_does_not_matter():
    assert categories_for("pt-BR") == categories_for("pt-PT")


def test_an_underscore_tag_still_resolves():
    assert categories_for("pl_PL") == categories_for("pl-PL")


def test_every_language_needs_other():
    # The platform falls back to it, so a resource without one can fail to
    # resolve at run time.
    for tag in ("en-US", "zh-TW", "pl-PL", "ar-SA", "sw-KE"):
        assert "other" in categories_for(tag)


def test_every_category_is_one_android_knows():
    for tag in ("en-US", "zh-TW", "pl-PL", "ar-SA", "fr-FR"):
        assert set(categories_for(tag)) <= set(CATEGORIES)


def test_the_order_is_androids():
    for tag in ("pl-PL", "ar-SA"):
        found = categories_for(tag)
        assert list(found) == [c for c in CATEGORIES if c in found]


# -- what is missing and what is spare ----------------------------------


def test_a_polish_resource_with_two_forms_is_missing_two():
    assert missing_categories("pl-PL", {"one", "other"}) == ["few", "many"]


def test_a_complete_one_is_missing_nothing():
    assert missing_categories("pl-PL", set(categories_for("pl-PL"))) == []


def test_the_check_is_case_insensitive():
    assert missing_categories("de-DE", {"ONE", "Other"}) == []


def test_a_chinese_resource_with_two_forms_has_one_spare():
    assert extra_categories("zh-TW", {"one", "other"}) == ["one"]


def test_a_correct_one_has_none_spare():
    assert extra_categories("de-DE", {"one", "other"}) == []


# -- the analysis -------------------------------------------------------


def test_a_polish_plural_missing_forms_is_reported():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]"))
    assert len(found) == 1
    assert "missing the few, many forms" in found[0].summary


def test_it_is_an_error():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]"))
    assert found[0].severity is Severity.ERROR


def test_the_detail_says_what_the_platform_does():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]"))
    assert "falls back to other" in found[0].detail


def test_the_finding_names_the_resource():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]"))
    assert found[0].origin == "pen_count"


def test_one_missing_form_reads_singular():
    catalog = catalog_of("pen_count[one]", "pen_count[few]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[few]",
                                 "pen_count[other]"))
    assert "missing the many form" in found[0].summary


def test_a_complete_polish_plural_is_quiet():
    symbols = [f"pen_count[{c}]" for c in categories_for("pl-PL")]
    catalog = catalog_of(*symbols)
    assert run(catalog, answers(catalog, *symbols)) == []


def test_an_untouched_resource_is_left_to_the_state_rule():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    assert run(catalog, TranslationSet(locale="pl-PL")) == []


def test_a_spare_form_is_a_warning():
    catalog = catalog_of("pen_count[one]", "pen_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]"),
                tag="zh-TW")
    spare = [f for f in found if "does not use" in f.summary]
    assert spare and spare[0].severity is Severity.WARNING


def test_a_plain_string_is_not_a_plural():
    catalog = catalog_of("app_name")
    assert run(catalog, answers(catalog, "app_name")) == []


def test_an_array_is_not_a_plural():
    # They share a syntax in the catalog and nothing else.
    catalog = catalog_of("modes[0]", "modes[1]")
    assert run(catalog, answers(catalog, "modes[0]", "modes[1]")) == []


def test_two_resources_are_reported_separately():
    catalog = catalog_of("pen_count[one]", "pen_count[other]",
                         "job_count[one]", "job_count[other]")
    found = run(catalog, answers(catalog, "pen_count[one]", "pen_count[other]",
                                 "job_count[one]", "job_count[other]"))
    assert {f.origin for f in found} == {"pen_count", "job_count"}


# -- what gets written --------------------------------------------------


def emit(catalog, translations, tag, tmp_path):
    out = tmp_path / "strings.xml"
    AndroidXmlEmitter().emit(catalog, translations,
                             EmitOptions(path=out, locale=resolve(tag)))
    return out.read_text(encoding="utf-8")


def test_a_plural_comes_out_as_a_plurals_element(tmp_path):
    # It used to come out as <string name="pen_count_one">, which parses,
    # builds, installs and never resolves.
    symbols = ["pen_count[one]", "pen_count[other]"]
    catalog = catalog_of(*symbols)
    text = emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path)

    root = ElementTree.fromstring(text)
    plurals = root.findall("plurals")
    assert [p.get("name") for p in plurals] == ["pen_count"]


def test_its_items_carry_their_quantity(tmp_path):
    symbols = ["pen_count[one]", "pen_count[other]"]
    catalog = catalog_of(*symbols)
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path))

    quantities = [i.get("quantity") for i in root.find("plurals")]
    assert quantities == ["one", "other"]


def test_the_items_are_in_androids_order(tmp_path):
    symbols = [f"pen_count[{c}]" for c in ("other", "many", "one", "few")]
    catalog = catalog_of(*symbols)
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, *symbols), "pl-PL", tmp_path))

    quantities = [i.get("quantity") for i in root.find("plurals")]
    assert quantities == ["one", "few", "many", "other"]


def test_a_category_this_build_does_not_know_is_kept(tmp_path):
    symbols = ["pen_count[other]", "pen_count[quite-a-few]"]
    catalog = catalog_of(*symbols)
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path))

    quantities = [i.get("quantity") for i in root.find("plurals")]
    assert quantities == ["other", "quite-a-few"]


def test_an_array_comes_out_as_a_string_array(tmp_path):
    symbols = ["modes[0]", "modes[1]"]
    catalog = catalog_of(*symbols)
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path))

    assert [a.get("name") for a in root.findall("string-array")] == ["modes"]


def test_an_array_keeps_its_order(tmp_path):
    # Order is the whole meaning of an array: the code indexes into it. Ten
    # items is where sorting the indices as strings goes wrong.
    symbols = [f"modes[{n}]" for n in range(11)]
    catalog = catalog_of(*symbols)
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path))

    texts = [item.text for item in root.find("string-array")]
    assert texts == [f"[modes[{n}] in English]" for n in range(11)]


def test_a_plain_string_still_comes_out_as_a_string(tmp_path):
    catalog = catalog_of("app_name")
    root = ElementTree.fromstring(
        emit(catalog, answers(catalog, "app_name"), "de-DE", tmp_path))

    assert [s.get("name") for s in root.findall("string")] == ["app_name"]


def test_the_file_still_parses_with_all_three(tmp_path):
    symbols = ["app_name", "pen_count[one]", "pen_count[other]", "modes[0]"]
    catalog = catalog_of(*symbols)
    text = emit(catalog, answers(catalog, *symbols), "de-DE", tmp_path)

    root = ElementTree.fromstring(text)
    assert root.tag == "resources"
    assert len(root) == 3


def test_no_flattened_name_survives(tmp_path):
    symbols = ["pen_count[one]", "pen_count[other]"]
    catalog = catalog_of(*symbols)
    assert "pen_count_one" not in emit(catalog, answers(catalog, *symbols),
                                       "de-DE", tmp_path)
