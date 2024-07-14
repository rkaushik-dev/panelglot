from pathlib import Path

import pytest

from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.errors import ConfigError
from v4t_translate.sources import registry
from v4t_translate.sources.base import (
    Extraction,
    Source,
    SourceOptions,
    merge_extractions,
)


def message(key, text="OK", source="V4T.rc", container="IDD_A", **kw):
    return Message(
        key=key,
        source_text=text,
        origins=[Origin(source=source, kind=OriginKind.DIALOG_CONTROL,
                        container=container, symbol="IDOK")],
        **kw,
    )


def test_relative_strips_the_root():
    options = SourceOptions(path=Path("/proj/src/V4T.rc"), root=Path("/proj"))
    assert options.relative() == "src/V4T.rc"


def test_relative_leaves_a_path_outside_the_root_alone():
    options = SourceOptions(path=Path("/elsewhere/V4T.rc"), root=Path("/proj"))
    assert options.relative() == "/elsewhere/V4T.rc"


def test_relative_without_a_root():
    options = SourceOptions(path=Path("src/V4T.rc"))
    assert options.relative() == "src/V4T.rc"


def test_relative_accepts_another_path():
    options = SourceOptions(path=Path("/proj/a.rc"), root=Path("/proj"))
    assert options.relative(Path("/proj/sub/b.rc")) == "sub/b.rc"


def test_extraction_length_and_warnings():
    extraction = Extraction(source="V4T.rc", messages=[message("a"), message("b")])
    extraction.warn("skipped a toolbar")
    assert len(extraction) == 2
    assert extraction.warnings == ["skipped a toolbar"]


def test_by_key_merges_repeats_inside_one_file():
    extraction = Extraction(
        source="V4T.rc",
        messages=[
            message("ok.1", container="IDD_A"),
            message("ok.1", container="IDD_B"),
            message("cancel.2", text="Cancel"),
        ],
    )
    merged = extraction.by_key()
    assert set(merged) == {"ok.1", "cancel.2"}
    assert [o.container for o in merged["ok.1"].origins] == ["IDD_A", "IDD_B"]


def test_by_key_keeps_the_stricter_constraint():
    extraction = Extraction(
        source="V4T.rc",
        messages=[message("ok.1", max_width_px=90), message("ok.1", max_width_px=40)],
    )
    assert extraction.by_key()["ok.1"].max_width_px == 40


def test_merge_extractions_across_files():
    first = Extraction(source="V4T.rc", messages=[message("ok.1", source="V4T.rc")])
    second = Extraction(source="Config.rc", messages=[
        message("ok.1", source="Config.rc"),
        message("pen.3", text="Pen", source="Config.rc"),
    ])
    merged = merge_extractions([first, second])
    assert set(merged) == {"ok.1", "pen.3"}
    assert merged["ok.1"].sources == ["Config.rc", "V4T.rc"]


def test_merge_extractions_of_nothing():
    assert merge_extractions([]) == {}


class FakeSource:
    kind = "fake"

    def extract(self, options: SourceOptions) -> Extraction:
        return Extraction(source=options.relative(), messages=[message("fake.1")])


def test_a_plain_class_satisfies_the_protocol():
    assert isinstance(FakeSource(), Source)


def test_registry_resolves_a_registered_factory():
    registry.register("fake", FakeSource)
    try:
        assert isinstance(registry.get_source("fake"), FakeSource)
    finally:
        registry._FACTORIES.pop("fake", None)


def test_registry_override_wins():
    instance = FakeSource()
    registry.override("rc", instance)
    try:
        assert registry.get_source("rc") is instance
    finally:
        registry.clear_overrides()


def test_registry_rejects_an_unknown_kind():
    with pytest.raises(ConfigError, match="no reader for source kind"):
        registry.get_source("cobol")


def test_available_kinds_lists_the_builtins():
    kinds = registry.available_kinds()
    assert "rc" in kinds
    assert "androidxml" in kinds
