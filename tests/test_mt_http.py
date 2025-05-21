import io
import json
import urllib.error

import pytest

from v4t_translate.errors import ConfigError
from v4t_translate.locales import resolve
from v4t_translate.mt.base import Provider
from v4t_translate.mt.http import (
    TARGET_STYLES,
    HttpProvider,
    HttpProviderConfig,
    extract_path,
    target_code,
)

EN = resolve("en-US")
DE = resolve("de-DE")
ZH = resolve("zh-TW")


class FakeOpener:
    """Stands in for urlopen. Records what was sent, replies with what it was told."""

    def __init__(self, replies, *, error=None):
        self.replies = list(replies)
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        body = self.replies.pop(0)
        payload = body if isinstance(body, str) else json.dumps(body)
        return _Response(payload)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __init__(self, text):
        super().__init__(text.encode("utf-8"))


def config(**kw):
    defaults = {
        "name": "fake",
        "endpoint": "https://example.test/translate",
        "target_field": "target_lang",
        "target_style": "upper-language",
        "response_path": "translations[].text",
    }
    defaults.update(kw)
    return HttpProviderConfig(**defaults)


def reply(*texts):
    return {"translations": [{"text": text} for text in texts]}


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        ("tag", "zh-TW"),
        ("language", "zh"),
        ("upper-language", "ZH"),
        ("upper-tag", "ZH-TW"),
        ("underscore", "zh_TW"),
    ],
)
def test_target_code(style, expected):
    assert target_code(ZH, style) == expected


def test_every_style_is_reachable():
    for style in TARGET_STYLES:
        assert target_code(DE, style)


def test_an_unknown_style_lists_the_real_ones():
    with pytest.raises(ConfigError, match="upper-language"):
        target_code(DE, "shouty")


def test_extract_a_list_of_objects():
    assert extract_path(reply("eins", "zwei"), "translations[].text") == [
        "eins", "zwei",
    ]


def test_extract_a_plain_list():
    assert extract_path({"result": ["eins", "zwei"]}, "result") == ["eins", "zwei"]


def test_extract_a_single_string():
    assert extract_path({"data": {"text": "eins"}}, "data.text") == ["eins"]


def test_extract_a_nested_path():
    payload = {"data": {"translations": [{"translatedText": "eins"}]}}
    assert extract_path(payload, "data.translations[].translatedText") == ["eins"]


def test_extract_from_a_missing_key():
    with pytest.raises(ConfigError, match="no 'nope'"):
        extract_path(reply("eins"), "nope")


def test_extract_where_a_list_was_expected():
    with pytest.raises(ConfigError, match="no list"):
        extract_path({"translations": "eins"}, "translations[].text")


def test_extract_of_something_that_is_not_text():
    with pytest.raises(ConfigError, match="is not text"):
        extract_path({"count": 3}, "count")


def test_a_simple_call():
    opener = FakeOpener([reply("Balkenhöhe", "Breite")])
    provider = HttpProvider(config(), opener=opener)

    result = provider.translate(["Bar Height", "Width"], EN, DE)
    assert result.texts == ["Balkenhöhe", "Breite"]
    assert result.provider == "fake"
    assert result.warnings == []


def test_it_satisfies_the_protocol():
    assert isinstance(HttpProvider(config(), opener=FakeOpener([])), Provider)


def test_the_request_body():
    opener = FakeOpener([reply("Balkenhöhe")])
    HttpProvider(config(), opener=opener).translate(["Bar Height"], EN, DE)

    body = json.loads(opener.requests[0].data.decode())
    assert body["text"] == ["Bar Height"]
    assert body["target_lang"] == "DE"
    assert "source_lang" not in body


def test_the_source_language_is_sent_when_asked_for():
    opener = FakeOpener([reply("Balkenhöhe")])
    HttpProvider(config(source_field="source_lang"), opener=opener).translate(
        ["Bar Height"], EN, DE
    )
    assert json.loads(opener.requests[0].data.decode())["source_lang"] == "EN"


def test_extra_fields_are_sent():
    opener = FakeOpener([reply("Balkenhöhe")])
    HttpProvider(config(extra={"formality": "more"}), opener=opener).translate(
        ["Bar Height"], EN, DE
    )
    assert json.loads(opener.requests[0].data.decode())["formality"] == "more"


def test_the_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "secret-value")
    opener = FakeOpener([reply("Balkenhöhe")])

    HttpProvider(
        config(auth_header="Authorization", auth_prefix="Key ", auth_env="FAKE_KEY"),
        opener=opener,
    ).translate(["Bar Height"], EN, DE)

    assert opener.requests[0].headers["Authorization"] == "Key secret-value"


def test_a_missing_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("FAKE_KEY", raising=False)
    provider = HttpProvider(config(auth_env="FAKE_KEY"), opener=FakeOpener([]))

    with pytest.raises(ConfigError, match="FAKE_KEY"):
        provider.translate(["Bar Height"], EN, DE)


def test_no_auth_configured_sends_no_header():
    opener = FakeOpener([reply("Balkenhöhe")])
    HttpProvider(config(), opener=opener).translate(["Bar Height"], EN, DE)
    assert "Authorization" not in opener.requests[0].headers


def test_placeholders_are_sent_as_tokens():
    # The unit letter is not part of the specifier, so it goes out as text
    # and comes back beside the restored placeholder.
    opener = FakeOpener([reply("Bitte [[0]]V bis [[1]]V eingeben.")])
    provider = HttpProvider(config(), opener=opener)

    result = provider.translate(["Please input from %.1fV to %.1fV."], EN, DE)

    sent = json.loads(opener.requests[0].data.decode())["text"][0]
    assert "%.1f" not in sent
    assert sent == "Please input from [[0]]V to [[1]]V."
    assert result.texts[0] == "Bitte %.1fV bis %.1fV eingeben."


def test_a_reordered_token_still_restores():
    opener = FakeOpener([reply("[[1]] von [[0]]")])
    result = HttpProvider(config(), opener=opener).translate(["%d of %s"], EN, DE)
    assert result.texts[0] == "%s von %d"


def test_batching():
    opener = FakeOpener([reply("a", "b"), reply("c")])
    provider = HttpProvider(config(batch_size=2), opener=opener)

    result = provider.translate(["one", "two", "three"], EN, DE)
    assert result.texts == ["a", "b", "c"]
    assert len(opener.requests) == 2


def test_a_batch_size_of_zero_still_sends_something():
    opener = FakeOpener([reply("a"), reply("b")])
    result = HttpProvider(config(batch_size=0), opener=opener).translate(
        ["one", "two"], EN, DE
    )
    assert result.texts == ["a", "b"]


def test_nothing_to_translate():
    opener = FakeOpener([])
    assert HttpProvider(config(), opener=opener).translate([], EN, DE).texts == []
    assert opener.requests == []


def test_a_network_failure_gives_up_on_that_batch_only():
    opener = FakeOpener([], error=urllib.error.URLError("no route to host"))
    result = HttpProvider(config(), opener=opener).translate(["a", "b"], EN, DE)

    assert result.texts == ["", ""]
    assert result.answered == 0
    assert any("no route to host" in w for w in result.warnings)


def test_a_timeout_is_survivable():
    opener = FakeOpener([], error=TimeoutError("took too long"))
    result = HttpProvider(config(), opener=opener).translate(["a"], EN, DE)
    assert result.texts == [""]
    assert result.warnings


def test_a_reply_that_is_not_json():
    opener = FakeOpener(["<html>gateway timeout</html>"])
    result = HttpProvider(config(), opener=opener).translate(["a"], EN, DE)
    assert result.texts == [""]
    assert any("unreadable reply" in w for w in result.warnings)


def test_a_reply_in_the_wrong_shape():
    opener = FakeOpener([{"error": "quota exceeded"}])
    result = HttpProvider(config(), opener=opener).translate(["a"], EN, DE)
    assert result.texts == [""]
    assert any("unreadable reply" in w for w in result.warnings)


def test_a_short_reply_drops_the_batch_rather_than_misaligning_it():
    # Pairing by index is the whole contract. A short reply must not shift
    # every later translation onto the wrong string.
    opener = FakeOpener([reply("a")])
    result = HttpProvider(config(), opener=opener).translate(["one", "two"], EN, DE)

    assert result.texts == ["", ""]
    assert any("answered 1 of 2" in w for w in result.warnings)


def test_an_empty_answer_stays_empty():
    opener = FakeOpener([reply("", "b")])
    result = HttpProvider(config(), opener=opener).translate(["one", "two"], EN, DE)
    assert result.texts == ["", "b"]
    assert result.answered == 1
