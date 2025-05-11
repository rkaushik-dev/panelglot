"""The documentation is checked against the code that it describes.

Docs go stale silently. A rule gets added and nobody writes it up, a format
field moves and the table in docs/ still shows the old offset, and the person
who finds out is the firmware engineer implementing against it.

So the things that can be checked mechanically are: every rule has a section,
every state and every flag is named, and the numbers in the binary layout
table match the struct the writer actually uses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from v4t_translate.catalog.store import FORMAT_VERSION
from v4t_translate.catalog.translations import TranslationState
from v4t_translate.emit.v4l import (
    FLAG_RTL,
    FLAG_UTF16,
    HEADER_SIZE,
    MAGIC,
    MAX_PACK_BYTES,
)
from v4t_translate.emit.v4l import (
    FORMAT_VERSION as V4L_VERSION,
)
from v4t_translate.layout.panels import panel_names
from v4t_translate.rules.registry import ANALYSIS_RULES, rule_names

DOCS = Path(__file__).resolve().parents[1] / "docs"


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def headings(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


@pytest.fixture(scope="module")
def rules_doc():
    return read("rules.md")


@pytest.fixture(scope="module")
def v4l_doc():
    return read("v4l-container.md")


@pytest.fixture(scope="module")
def catalog_doc():
    return read("catalog-format.md")


def test_the_docs_directory_is_there():
    assert DOCS.is_dir()
    assert {p.name for p in DOCS.glob("*.md")} >= {
        "rules.md", "v4l-container.md", "catalog-format.md",
    }


def test_every_rule_has_a_section(rules_doc):
    documented = set(headings(rules_doc))
    for name in rule_names():
        assert name in documented, f"{name} is not written up"


def test_the_analyses_have_a_section_too(rules_doc):
    documented = set(headings(rules_doc))
    for name in ANALYSIS_RULES:
        assert name in documented


def test_nothing_is_documented_that_does_not_exist(rules_doc):
    known = set(rule_names()) | set(ANALYSIS_RULES)
    assert set(headings(rules_doc)) <= known


def test_the_rules_are_documented_in_report_order(rules_doc):
    documented = [h for h in headings(rules_doc) if h in set(rule_names())]
    assert documented == rule_names()


def test_the_config_example_uses_real_rule_names(rules_doc):
    block = rules_doc.split("```toml", 1)[1].split("```", 1)[0]
    known = set(rule_names()) | set(ANALYSIS_RULES)

    # Only the bracketed lists hold rule names. fail_on takes a severity.
    named = [
        quoted
        for group in re.findall(r"=\s*\[([^\]]*)\]", block)
        for quoted in re.findall(r'"([a-z-]+)"', group)
    ]
    assert named, "the example does not name any rules"

    for quoted in named:
        assert quoted in known, f"{quoted} is not a rule"


def test_the_config_example_fail_on_is_a_real_severity(rules_doc):
    block = rules_doc.split("```toml", 1)[1].split("```", 1)[0]
    match = re.search(r'fail_on\s*=\s*"([a-z]+)"', block)
    assert match and match.group(1) in ("error", "warning", "never")


def test_the_v4l_magic_matches(v4l_doc):
    assert f"`{MAGIC.decode()}`" in v4l_doc


def test_the_v4l_version_matches(v4l_doc):
    assert f"currently {V4L_VERSION}" in v4l_doc


def test_the_v4l_header_size_matches(v4l_doc):
    # The offset table starts where the header ends, and it is the first row
    # whose size is not a fixed number of bytes.
    rows = _layout_rows(v4l_doc)
    variable = [offset for offset, size in rows if size == 0]
    assert variable and variable[0] == HEADER_SIZE


def test_the_v4l_layout_has_no_gaps_or_overlaps(v4l_doc):
    position = 0
    for offset, size in _layout_rows(v4l_doc):
        assert offset == position, f"offset {offset} does not follow {position}"
        if size == 0:
            break
        position += size


def test_the_v4l_flag_bits_match(v4l_doc):
    table = v4l_doc.split("| bit |", 1)[1]
    assert re.search(r"\|\s*0\s*\|.*UTF-16", table)
    assert re.search(r"\|\s*1\s*\|.*right to left", table, re.IGNORECASE)
    assert FLAG_UTF16 == 1 << 0
    assert FLAG_RTL == 1 << 1


def test_the_v4l_size_limit_matches(v4l_doc):
    assert f"{MAX_PACK_BYTES // 1024} KB" in v4l_doc


def test_every_state_is_documented(catalog_doc):
    for state in TranslationState:
        assert f"`{state.value}`" in catalog_doc


def test_the_catalog_format_version_matches(catalog_doc):
    assert f'"format": {FORMAT_VERSION}' in catalog_doc


def test_the_catalog_example_parses_as_json(catalog_doc):
    import json

    for block in re.findall(r"```json\n(.*?)```", catalog_doc, re.DOTALL):
        json.loads(block)


def test_the_readme_mentions_every_source_kind():
    from v4t_translate.sources.registry import available_kinds

    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")
    for kind in available_kinds():
        assert f"`{kind}`" in readme


def test_the_panels_named_in_the_docs_exist():
    known = set(panel_names())
    for name in DOCS.glob("*.md"):
        for candidate in re.findall(r"`(mini-[a-z0-9-]+|tij[a-z0-9-]*)`",
                                    name.read_text(encoding="utf-8")):
            assert candidate in known, f"{candidate} in {name.name} is not a panel"


def _layout_rows(text: str) -> list[tuple[int, int]]:
    """The offset and size columns of the binary layout table."""
    rows: list[tuple[int, int]] = []
    for line in text.splitlines():
        match = re.match(r"\|\s*(\d+)\s*\|\s*([\d×n+ ]+)\s*\|", line)
        if match is None:
            continue
        size = match.group(2).strip()
        if "×" in size or "n" in size:
            rows.append((int(match.group(1)), 0))
            continue
        rows.append((int(match.group(1)), int(size)))
    return rows
