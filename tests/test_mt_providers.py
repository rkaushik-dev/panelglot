import pytest

from v4t_translate.errors import ConfigError
from v4t_translate.locales import resolve
from v4t_translate.mt.base import (
    Provider,
    ProviderResult,
    protect_placeholders,
    restore_placeholders,
)
from v4t_translate.mt.providers import (
    PassthroughProvider,
    PseudoProvider,
    get_provider,
    register_provider,
)
from v4t_translate.rules.placeholders import find_placeholders

EN = resolve("en-US")
DE = resolve("de-DE")


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Print started", 0),
        ("Please input from %.1fV to %.1fV.", 2),
        ("Value must be between <V1> and <V2>", 2),
        ("Printing {0} of {count}", 2),
        ("Line one\\nLine two", 1),
        ("100%% done", 1),
    ],
)
def test_protect_finds_what_matters(text, count):
    _, found = protect_placeholders(text)
    assert len(found) == count


def test_protect_replaces_with_tokens():
    protected, _ = protect_placeholders("Pen %d of %d")
    assert protected == "Pen [[0]] of [[1]]"


def test_round_trip_restores_exactly():
    text = "Please input from %.1fV to %.1fV."
    protected, placeholders = protect_placeholders(text)
    assert restore_placeholders(protected, placeholders) == text


def test_restore_after_a_reorder():
    protected, placeholders = protect_placeholders("%d of %s")
    reordered = "[[1]] von [[0]]"
    assert restore_placeholders(reordered, placeholders) == "%s von %d"


def test_an_invented_token_is_dropped():
    _, placeholders = protect_placeholders("Pen %d")
    assert restore_placeholders("Stift [[0]] [[7]]", placeholders).strip() == "Stift %d"


def test_a_number_in_the_text_is_not_a_token():
    _, placeholders = protect_placeholders("Pen 4")
    assert restore_placeholders("Stift 4", placeholders) == "Stift 4"


def test_passthrough_returns_the_source():
    result = PassthroughProvider().translate(["Bar Height", "Width"], EN, DE)
    assert result.texts == ["Bar Height", "Width"]
    assert result.provider == "passthrough"
    assert result.answered == 2


def test_passthrough_satisfies_the_protocol():
    assert isinstance(PassthroughProvider(), Provider)
    assert isinstance(PseudoProvider(), Provider)


def test_a_provider_result_counts_only_answers():
    assert ProviderResult(texts=["a", "", "b"]).answered == 2


def test_pseudo_is_readable():
    text = PseudoProvider(brackets=False).transform("Bar Height")
    assert "Ƀåř" in text or "Ɓåř" in text
    assert text.lower().startswith("ƀ") or text.startswith("Ɓ")


def test_pseudo_is_longer_than_the_source():
    source = "Print started"
    text = PseudoProvider().transform(source)
    assert len(text) > len(source) * 1.3


def test_pseudo_is_bracketed_so_truncation_is_visible():
    text = PseudoProvider().transform("Bar Height")
    assert text.startswith("[")
    assert text.endswith("]")


def test_pseudo_brackets_can_be_turned_off():
    assert not PseudoProvider(brackets=False).transform("Bar Height").startswith("[")


def test_pseudo_keeps_placeholders_intact():
    text = PseudoProvider().transform("Please input from %.1fV to %.1fV.")
    assert [p.text for p in find_placeholders(text)] == ["%.1f", "%.1f"]


def test_pseudo_keeps_named_tokens_intact():
    text = PseudoProvider().transform("Value must be between <V1> and <V2>")
    assert "<V1>" in text
    assert "<V2>" in text


def test_pseudo_keeps_a_mnemonic_marker():
    assert "&" in PseudoProvider().transform("&Print")


def test_pseudo_of_an_empty_string_is_empty():
    assert PseudoProvider().transform("") == ""


def test_pseudo_expansion_is_configurable():
    tight = PseudoProvider(expansion=0.0).transform("Print started")
    loose = PseudoProvider(expansion=1.0).transform("Print started")
    assert len(loose) > len(tight)


def test_pseudo_translates_a_batch():
    result = PseudoProvider().translate(["Pen", "Width"], EN, DE)
    assert len(result.texts) == 2
    assert result.provider == "pseudo"


def test_pseudo_does_not_touch_digits_inside_a_token():
    # Accenting them would stop the placeholder being restored.
    text = PseudoProvider().transform("Pen %d and %d and %d")
    assert text.count("%d") == 3


def test_get_provider():
    assert get_provider("pseudo").name == "pseudo"
    assert get_provider("passthrough").name == "passthrough"


def test_an_unknown_provider_lists_the_real_ones():
    with pytest.raises(ConfigError, match="Built in: passthrough, pseudo"):
        get_provider("deepl")


def test_a_provider_can_be_registered():
    class Shouty:
        name = "shouty"

        def translate(self, texts, source, target):
            return ProviderResult(texts=[t.upper() for t in texts], provider=self.name)

    register_provider("shouty", Shouty)
    try:
        assert get_provider("shouty").translate(["pen"], EN, DE).texts == ["PEN"]
    finally:
        from v4t_translate.mt import providers

        providers._PROVIDERS.pop("shouty")
