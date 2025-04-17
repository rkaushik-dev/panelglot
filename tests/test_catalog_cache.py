import json
import shutil

import pytest
from click.testing import CliRunner

from v4t_translate.catalog.cache import (
    CACHE_VERSION,
    ExtractionCache,
    fingerprint_file,
)
from v4t_translate.catalog.ids import message_key
from v4t_translate.catalog.model import Message, Origin, OriginKind
from v4t_translate.cli import main
from v4t_translate.config import load_config
from v4t_translate.ops.extract import cache_path, extract_project

CONFIG = """
[project]
name = "V4T-TIJ"

[[source]]
kind = "rc"
path = "src/V4T.rc"

[locale."de-DE"]
"""


@pytest.fixture
def project(tmp_path, sample_rc_path):
    (tmp_path / "src").mkdir()
    shutil.copy(sample_rc_path, tmp_path / "src" / "V4T.rc")
    (tmp_path / "v4t-translate.toml").write_text(CONFIG, encoding="utf-8")
    return load_config(tmp_path / "v4t-translate.toml")


def messages():
    return [
        Message(key=message_key("Bar Height"), source_text="Bar Height",
                max_width_px=54,
                origins=[Origin(source="V4T.rc", kind=OriginKind.DIALOG_CONTROL,
                                container="IDD_X", symbol="IDC_STATIC", line=26)]),
        Message(key=message_key("mm"), source_text="mm", protected=True),
    ]


def test_fingerprint_is_stable(tmp_path):
    path = tmp_path / "a.rc"
    path.write_text("hello", encoding="utf-8")
    assert fingerprint_file(path) == fingerprint_file(path)


def test_fingerprint_changes_with_content(tmp_path):
    path = tmp_path / "a.rc"
    path.write_text("hello", encoding="utf-8")
    before = fingerprint_file(path)
    path.write_text("hello there", encoding="utf-8")
    assert fingerprint_file(path) != before


def test_fingerprint_ignores_the_modification_time(tmp_path):
    import os
    import time

    path = tmp_path / "a.rc"
    path.write_text("hello", encoding="utf-8")
    before = fingerprint_file(path)
    later = time.time() + 500
    os.utime(path, (later, later))
    assert fingerprint_file(path) == before


def test_fingerprint_of_a_missing_file_is_empty(tmp_path):
    assert fingerprint_file(tmp_path / "nope.rc") == ""


def test_a_hit_and_a_miss():
    cache = ExtractionCache()
    cache.store("V4T.rc", "abc", messages(), ["a warning"], {"dialogs": 2})

    assert cache.lookup("V4T.rc", "abc") is not None
    assert cache.lookup("V4T.rc", "different") is None
    assert cache.lookup("Config.rc", "abc") is None
    assert cache.hits == 1
    assert cache.misses == 2
    assert cache.summary == "1 cached, 2 read"


def test_an_empty_fingerprint_never_hits():
    cache = ExtractionCache()
    cache.store("V4T.rc", "abc", messages(), [], {})
    assert cache.lookup("V4T.rc", "") is None


def test_a_source_that_cannot_be_fingerprinted_is_not_stored():
    cache = ExtractionCache()
    cache.store("V4T.rc", "", messages(), [], {})
    assert cache.entries == {}


def test_storing_over_an_entry_replaces_it():
    cache = ExtractionCache()
    cache.store("V4T.rc", "abc", messages(), [], {})
    cache.store("V4T.rc", "def", [], [], {})
    assert cache.lookup("V4T.rc", "def").messages == []


def test_restrict_to_drops_sources_that_are_gone():
    cache = ExtractionCache()
    cache.store("V4T.rc", "abc", messages(), [], {})
    cache.store("Config.rc", "def", messages(), [], {})
    cache.restrict_to(["V4T.rc"])
    assert set(cache.entries) == {"V4T.rc"}


def test_a_round_trip_through_disk(tmp_path):
    cache = ExtractionCache()
    cache.store("V4T.rc", "abc", messages(), ["careful"], {"dialogs": 2})
    cache.save(tmp_path / "cache.json")

    reloaded = ExtractionCache.load(tmp_path / "cache.json")
    entry = reloaded.lookup("V4T.rc", "abc")
    assert entry is not None
    assert [m.source_text for m in entry.messages] == ["Bar Height", "mm"]
    assert entry.messages[0].max_width_px == 54
    assert entry.messages[1].protected
    assert entry.warnings == ["careful"]
    assert entry.stats == {"dialogs": 2}


def test_loading_a_file_that_is_not_there(tmp_path):
    assert ExtractionCache.load(tmp_path / "nope.json").entries == {}


def test_loading_something_that_is_not_json(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{ not json", encoding="utf-8")
    assert ExtractionCache.load(path).entries == {}


def test_loading_a_cache_from_an_older_version(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"version": CACHE_VERSION - 1, "sources": {}}),
                    encoding="utf-8")
    assert ExtractionCache.load(path).entries == {}


def test_loading_a_cache_whose_entries_are_wrong(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps({"version": CACHE_VERSION,
                    "sources": {"V4T.rc": {"fingerprint": "abc",
                                           "messages": [{"no": "key"}]}}}),
        encoding="utf-8",
    )
    assert ExtractionCache.load(path).entries == {}


def test_an_entry_with_no_fingerprint_is_dropped(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps({"version": CACHE_VERSION,
                    "sources": {"V4T.rc": {"messages": []}}}),
        encoding="utf-8",
    )
    assert ExtractionCache.load(path).entries == {}


def test_a_first_run_reads_everything(project):
    result = extract_project(project)
    assert result.cache_summary == "0 cached, 1 read"
    assert cache_path(project).exists()


def test_a_second_run_uses_the_cache(project):
    extract_project(project)
    assert extract_project(project).cache_summary == "1 cached, 0 read"


def test_the_cached_run_produces_the_same_catalog(project):
    first = extract_project(project)
    before = project.catalog_path().read_bytes()

    second = extract_project(project)
    assert second.message_count == first.message_count
    assert project.catalog_path().read_bytes() == before


def test_editing_the_source_misses(project):
    extract_project(project)
    path = project.root / "src" / "V4T.rc"
    path.write_text(path.read_text(encoding="utf-8").replace("Bar Height", "Bar height"),
                    encoding="utf-8")
    assert extract_project(project).cache_summary == "0 cached, 1 read"


def test_touching_the_source_without_changing_it_still_hits(project):
    import os
    import time

    extract_project(project)
    path = project.root / "src" / "V4T.rc"
    later = time.time() + 500
    os.utime(path, (later, later))
    assert extract_project(project).cache_summary == "1 cached, 0 read"


def test_changing_the_protected_patterns_misses(project):
    extract_project(project)
    (project.root / "v4t-translate.toml").write_text(
        CONFIG + '\n[protected]\npatterns = ["SENC"]\n', encoding="utf-8"
    )
    config = load_config(project.root / "v4t-translate.toml")
    assert extract_project(config).cache_summary == "0 cached, 1 read"


def test_no_cache_reads_everything_again(project):
    extract_project(project)
    assert extract_project(project, use_cache=False).cache_summary == "0 cached, 1 read"


def test_no_cache_does_not_write_one(project, tmp_path):
    extract_project(project, use_cache=False)
    assert not cache_path(project).exists()


def test_a_dry_run_does_not_write_the_cache(project):
    extract_project(project, dry_run=True)
    assert not cache_path(project).exists()


def test_a_corrupt_cache_does_not_stop_the_run(project):
    extract_project(project)
    cache_path(project).write_text("nonsense", encoding="utf-8")
    result = extract_project(project)
    assert result.message_count > 30
    assert result.cache_summary == "0 cached, 1 read"


def test_the_command_line_flag(project):
    runner = CliRunner()
    args = ["-c", str(project.root / "v4t-translate.toml")]

    runner.invoke(main, [*args, "extract"])
    cached = runner.invoke(main, [*args, "-v", "extract"]).output
    assert "1 cached, 0 read" in cached

    fresh = runner.invoke(main, [*args, "-v", "extract", "--no-cache"]).output
    assert "0 cached, 1 read" in fresh
