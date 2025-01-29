"""The providers that ship with the tool.

Two of them, and neither is a translation engine.

``passthrough`` returns the English. It exists for a language that genuinely
ships English, which two of the distributors want, and as the thing every test
uses so the suite never depends on a network.

``pseudo`` is the useful one. It rewrites English into something that is still
readable but is a third longer and full of accented characters, which is what
German and Turkish do to a layout. Running the whole HMI in pseudo finds every
clipped label and every hardcoded string before a translator has been paid for
anything, and it finds them in an afternoon rather than after the first
delivery.

A real engine is a plugin. Registering one is three lines and the protocol is
in :mod:`.base`; keeping the HTTP call out of this package means the tool has
no runtime dependency on anybody's API and no key to lose.
"""

from __future__ import annotations

from ..locales import Locale
from .base import ProviderResult, protect_placeholders, restore_placeholders

__all__ = ["PassthroughProvider", "PseudoProvider", "PSEUDO_MAP", "get_provider"]

#: ASCII to a lookalike that is still legible. Chosen so a person can read the
#: pseudo build and spot a string that did not get translated, which is the
#: other thing pseudo localisation is for.
PSEUDO_MAP: dict[str, str] = {
    "a": "å", "b": "ƀ", "c": "ç", "d": "đ", "e": "é",
    "f": "ƒ", "g": "ğ", "h": "ĥ", "i": "î", "j": "ĵ",
    "k": "ķ", "l": "ļ", "m": "ḿ", "n": "ñ", "o": "ö",
    "p": "þ", "q": "ǫ", "r": "ř", "s": "š", "t": "ţ",
    "u": "û", "v": "ṽ", "w": "ŵ", "x": "ẋ", "y": "ý",
    "z": "ž",
    "A": "Å", "B": "Ɓ", "C": "Ç", "D": "Ď", "E": "É",
    "F": "Ƒ", "G": "Ğ", "H": "Ĥ", "I": "Î", "J": "Ĵ",
    "K": "Ķ", "L": "Ļ", "M": "Ḿ", "N": "Ñ", "O": "Ö",
    "P": "Þ", "Q": "Ǫ", "R": "Ř", "S": "Š", "T": "Ţ",
    "U": "Û", "V": "Ṽ", "W": "Ŵ", "X": "Ẋ", "Y": "Ý",
    "Z": "Ž",
}

#: How much longer a pseudo string is than its source. German runs about a
#: third longer against English across the strings we have measured, so the
#: pseudo build should too.
PSEUDO_EXPANSION = 0.35

#: Padding character. Not a letter, so it cannot be mistaken for text, and in
#: every panel font we ship.
PSEUDO_PAD = "~"


class PassthroughProvider:
    """Returns the source unchanged."""

    name = "passthrough"

    def translate(self, texts: list[str], source: Locale,
                  target: Locale) -> ProviderResult:
        return ProviderResult(texts=list(texts), provider=self.name)


class PseudoProvider:
    """Rewrites English into a longer, accented, still readable form."""

    name = "pseudo"

    def __init__(self, expansion: float = PSEUDO_EXPANSION, *,
                 brackets: bool = True) -> None:
        self.expansion = expansion
        self.brackets = brackets

    def translate(self, texts: list[str], source: Locale,
                  target: Locale) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        for text in texts:
            result.texts.append(self.transform(text))
        return result

    def transform(self, text: str) -> str:
        """One string. Placeholders and mnemonics come through untouched."""
        if not text:
            return ""

        protected, placeholders = protect_placeholders(text)
        accented = self._accent(protected)
        padded = self._pad(accented, len(protected))
        restored = restore_placeholders(padded, placeholders)

        return f"[{restored}]" if self.brackets else restored

    @staticmethod
    def _accent(text: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(text):
            char = text[index]

            # Leave a token alone. Accenting the digits inside one would stop
            # restore_placeholders from finding it.
            if char == "[" and text[index:index + 2] == "[[":
                close = text.find("]]", index)
                if close != -1:
                    out.append(text[index:close + 2])
                    index = close + 2
                    continue

            out.append(PSEUDO_MAP.get(char, char))
            index += 1
        return "".join(out)

    def _pad(self, text: str, measured_length: int) -> str:
        extra = round(measured_length * self.expansion)
        if extra <= 0:
            return text
        return f"{text} {PSEUDO_PAD * extra}"


_PROVIDERS = {
    PassthroughProvider.name: PassthroughProvider,
    PseudoProvider.name: PseudoProvider,
}


def get_provider(name: str):
    """Build a provider by name. Raises :class:`ConfigError` for an unknown one."""
    from ..errors import ConfigError

    factory = _PROVIDERS.get(name)
    if factory is None:
        raise ConfigError(
            f"unknown provider {name!r}. Built in: {', '.join(sorted(_PROVIDERS))}"
        )
    return factory()


def register_provider(name: str, factory) -> None:
    """Add a provider. This is how a real engine gets plugged in."""
    _PROVIDERS[name] = factory
