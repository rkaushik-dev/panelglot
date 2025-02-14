"""Questions that need to see more than one message at a time.

The rules deliberately cannot do this: a rule gets one message and one
translation, which is what keeps them short and independent. These three
checks need the whole language at once.

Two controls on one dialog sharing a mnemonic. Alt+D on a dialog with two
D-marked buttons presses one of them and nobody can predict which, and it is
invisible until somebody uses the keyboard. This is the single most common
thing a translator does wrong that no per-string check can see.

Two different English strings translated identically. Sometimes right, often a
lost distinction: "Print" the button and "Print" the menu heading are one word
in English and two in German, and collapsing them back is a regression.

A translation identical to its source. In German that is usually correct for
OK and Barcode and wrong for everything else, and the ratio of the two is what
tells you whether a delivery was actually done.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..catalog.model import Message, OriginKind
from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..layout.measure import mnemonic_of
from ..locales import Locale

__all__ = [
    "MnemonicCollision",
    "MergedTarget",
    "AnalysisResult",
    "analyse",
    "mnemonic_collisions",
    "merged_targets",
    "identical_to_source",
]

#: Source strings a translator is right to leave alone in most languages.
#: Reporting these as untranslated would bury the ones that matter.
_LEGITIMATELY_UNCHANGED = frozenset(
    {"ok", "barcode", "v4t", "usb", "id", "mm", "ms", "cm", "dpi", "senc", "mcr",
     "tij", "pdf", "csv", "ip", "com", "normal", "standard", "reset", "start",
     "stop", "test", "info", "modem", "monitor", "modus", "format", "service"}
)


@dataclass(frozen=True)
class MnemonicCollision:
    """Two or more controls on one dialog marking the same character."""

    container: str
    mnemonic: str
    keys: tuple[str, ...]
    texts: tuple[str, ...]

    def describe(self) -> str:
        listed = ", ".join(repr(text) for text in self.texts)
        return f"{self.container}: Alt+{self.mnemonic} is claimed by {listed}"


@dataclass(frozen=True)
class MergedTarget:
    """Several distinct English strings sharing one translation."""

    target: str
    sources: tuple[str, ...]
    keys: tuple[str, ...]

    def describe(self) -> str:
        listed = ", ".join(repr(text) for text in self.sources)
        return f"{listed} all translate to {self.target!r}"


@dataclass
class AnalysisResult:
    """Everything the whole-language checks found."""

    locale: str
    collisions: list[MnemonicCollision] = field(default_factory=list)
    merged: list[MergedTarget] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    checked: int = 0

    def __bool__(self) -> bool:
        return bool(self.collisions or self.merged or self.unchanged)

    def summary(self) -> str:
        return (
            f"{self.locale}: {self.checked} translated, "
            f"{len(self.collisions)} mnemonic collisions, "
            f"{len(self.merged)} merged translations, "
            f"{len(self.unchanged)} unchanged from English"
        )


def analyse(catalog: Catalog, translations: TranslationSet,
            locale: Locale) -> AnalysisResult:
    """Run every whole-language check."""
    result = AnalysisResult(locale=locale.tag)
    result.checked = sum(
        1 for key in catalog.messages if translations.get(key).text
    )
    result.collisions = mnemonic_collisions(catalog, translations)
    result.merged = merged_targets(catalog, translations)
    result.unchanged = identical_to_source(catalog, translations)
    return result


def mnemonic_collisions(catalog: Catalog, translations: TranslationSet
                        ) -> list[MnemonicCollision]:
    """Controls on one dialog whose translations claim the same Alt key.

    Only dialog controls and menu items are considered. A string table entry
    containing an ampersand is not bound to anything, and a dialog caption is
    not either.
    """
    claims: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for key, message in catalog.messages.items():
        translation = translations.get(key)
        if not translation.text:
            continue

        marker = mnemonic_of(translation.text)
        if marker is None:
            continue

        for container in _mnemonic_containers(message):
            claims.setdefault((container, marker), []).append((key, translation.text))

    collisions: list[MnemonicCollision] = []
    for (container, marker), holders in sorted(claims.items()):
        if len(holders) < 2:
            continue
        collisions.append(
            MnemonicCollision(
                container=container,
                mnemonic=marker,
                keys=tuple(key for key, _ in holders),
                texts=tuple(text for _, text in holders),
            )
        )
    return collisions


def merged_targets(catalog: Catalog, translations: TranslationSet) -> list[MergedTarget]:
    """Distinct English strings that came back with the same translation."""
    by_target: dict[str, list[tuple[str, str]]] = {}

    for key, message in catalog.messages.items():
        translation = translations.get(key)
        if not translation.text:
            continue
        by_target.setdefault(translation.text, []).append((key, message.source_text))

    merged: list[MergedTarget] = []
    for target, holders in sorted(by_target.items()):
        sources = {source for _, source in holders}
        if len(sources) < 2:
            continue
        merged.append(
            MergedTarget(
                target=target,
                sources=tuple(sorted(sources)),
                keys=tuple(sorted(key for key, _ in holders)),
            )
        )
    return merged


def identical_to_source(catalog: Catalog, translations: TranslationSet) -> list[str]:
    """Translations that are character for character the English.

    Protected messages are excluded because that is the whole point of them,
    and so is a short list of words that genuinely do not change.
    """
    unchanged: list[str] = []

    for key in catalog.sorted_keys():
        message = catalog.messages[key]
        translation = translations.get(key)

        if not translation.text or message.protected:
            continue
        if translation.text != message.source_text:
            continue
        if message.source_text.strip().lower() in _LEGITIMATELY_UNCHANGED:
            continue

        unchanged.append(key)

    return unchanged


def _mnemonic_containers(message: Message) -> set[str]:
    """Containers within which this message's mnemonic has to be unique."""
    containers: set[str] = set()
    for origin in message.origins:
        if origin.kind in (OriginKind.DIALOG_CONTROL, OriginKind.MENU_ITEM,
                           OriginKind.MENU_POPUP):
            containers.add(origin.container)
    return containers
