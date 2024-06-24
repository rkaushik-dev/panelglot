import pytest

from v4t_translate.catalog.model import Message, Origin, OriginKind


def origin(symbol="IDC_BAR_HEIGHT", line=10, container="IDD_BARCODE", source="V4T.rc", ordinal=0):
    return Origin(
        source=source,
        kind=OriginKind.DIALOG_CONTROL,
        container=container,
        symbol=symbol,
        line=line,
        ordinal=ordinal,
    )


def test_origin_kind_values_are_the_on_disk_names():
    assert OriginKind.DIALOG_CONTROL.value == "dialog-control"
    assert str(OriginKind.STRING_TABLE) == "string-table"


def test_origin_describe_names_container_and_symbol():
    assert origin().describe() == "V4T.rc:10 (IDD_BARCODE/IDC_BAR_HEIGHT)"


def test_origin_describe_drops_symbol_when_it_repeats_the_container():
    o = origin(symbol="STRINGTABLE", container="STRINGTABLE")
    assert o.describe() == "V4T.rc:10 (STRINGTABLE)"


def test_origin_describe_without_a_line():
    assert origin(line=0).describe() == "V4T.rc (IDD_BARCODE/IDC_BAR_HEIGHT)"


def test_add_origin_is_idempotent():
    msg = Message(key="k", source_text="Bar Height")
    msg.add_origin(origin())
    msg.add_origin(origin())
    assert len(msg.origins) == 1


def test_origins_stay_sorted():
    msg = Message(key="k", source_text="OK")
    msg.add_origin(origin(line=40, container="IDD_Z"))
    msg.add_origin(origin(line=10, container="IDD_A"))
    assert [o.container for o in msg.origins] == ["IDD_A", "IDD_Z"]


def test_primary_origin_is_none_when_there_are_none():
    assert Message(key="k", source_text="OK").primary_origin is None


def test_sources_dedupes_and_keeps_order():
    msg = Message(key="k", source_text="OK")
    msg.add_origin(origin(source="Config.rc", container="IDD_B"))
    msg.add_origin(origin(source="Config.rc", container="IDD_C"))
    msg.add_origin(origin(source="V4T.rc", container="IDD_A"))
    assert msg.sources == ["Config.rc", "V4T.rc"]


def test_tighten_takes_the_smaller_budget():
    msg = Message(key="k", source_text="Print Spacing", max_chars=20)
    msg.tighten(max_chars=12)
    assert msg.max_chars == 12


def test_tighten_never_relaxes():
    msg = Message(key="k", source_text="Print Spacing", max_chars=12)
    msg.tighten(max_chars=20)
    assert msg.max_chars == 12


def test_tighten_sets_an_unset_budget():
    msg = Message(key="k", source_text="Print Spacing")
    msg.tighten(max_width_px=88)
    assert msg.max_width_px == 88


def test_merged_with_unions_origins():
    a = Message(key="k", source_text="OK", origins=[origin(container="IDD_A")])
    b = Message(key="k", source_text="OK", origins=[origin(container="IDD_B")])
    merged = a.merged_with(b)
    assert [o.container for o in merged.origins] == ["IDD_A", "IDD_B"]
    # The inputs are left alone.
    assert len(a.origins) == 1
    assert len(b.origins) == 1


def test_merged_with_keeps_the_stricter_constraints():
    a = Message(key="k", source_text="OK", max_chars=None, max_width_px=90, max_lines=2)
    b = Message(key="k", source_text="OK", max_chars=8, max_width_px=64, max_lines=1)
    merged = a.merged_with(b)
    assert merged.max_chars == 8
    assert merged.max_width_px == 64
    assert merged.max_lines == 1


def test_protected_is_sticky():
    a = Message(key="k", source_text="mm", protected=False)
    b = Message(key="k", source_text="mm", protected=True)
    assert a.merged_with(b).protected is True
    assert b.merged_with(a).protected is True


def test_merged_notes_are_joined_once():
    a = Message(key="k", source_text="OK", developer_note="Button.")
    b = Message(key="k", source_text="OK", developer_note="Also the menu.")
    assert a.merged_with(b).developer_note == "Button. Also the menu."


def test_merged_notes_do_not_duplicate_an_identical_note():
    a = Message(key="k", source_text="OK", developer_note="Button.")
    b = Message(key="k", source_text="OK", developer_note="Button.")
    assert a.merged_with(b).developer_note == "Button."


def test_merge_rejects_a_different_key():
    a = Message(key="a", source_text="OK")
    b = Message(key="b", source_text="OK")
    with pytest.raises(ValueError, match="cannot merge"):
        a.merged_with(b)


def test_merge_rejects_a_key_collision_on_different_text():
    a = Message(key="k", source_text="OK")
    b = Message(key="k", source_text="Cancel")
    with pytest.raises(ValueError, match="two different source texts"):
        a.merged_with(b)
