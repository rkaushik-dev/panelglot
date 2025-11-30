"""A plural resource with the forms the target language actually needs.

The English resources were written with one and other, because English has
two. Polish has three and Arabic has six, and a Polish plurals carrying only
one and other is not a translation with a gap in it. The platform picks other
for two, three and four, so the panel says the Polish for five pens when there
are two.

Nothing anywhere reports that. The file parses, aapt is happy, the app runs
and the string is grammatical for most counts.

It has to be an analysis rather than a rule because the question is about a
resource and a resource is several messages: pen_count[one] and
pen_count[other] are separate keys with separate English. Only something that
sees the whole language can tell that a third one is missing.

Extra forms are reported too, at a lower level. An item for a category the
language does not use is harmless, because the platform never selects it, but
it is somebody's paid work sitting in a file doing nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..catalog.model import OriginKind
from ..catalog.store import Catalog
from ..catalog.translations import TranslationSet
from ..plurals import categories_for, extra_categories, missing_categories
from ..rules.result import Finding, Severity
from .base import AnalysisContext, finding

__all__ = ["PluralAnalysis"]


class PluralAnalysis:
    """Every plural resource carries the forms this language distinguishes."""

    name = "plurals"
    default_severity = Severity.ERROR

    def run(self, catalog: Catalog, translations: TranslationSet,
            context: AnalysisContext) -> Iterable[Finding]:
        for base, entries in sorted(_resources(catalog).items()):
            answered = {
                quantity: key for quantity, key in entries.items()
                if translations.get(key).text
            }
            if not answered:
                # Nobody has started this one. That is the state rule's
                # business, and saying it twice helps nobody.
                continue

            first = entries[sorted(entries)[0]]
            yield from self._missing(base, answered, first, context)
            yield from self._extra(base, answered, first, context)

    def _missing(self, base: str, answered: dict[str, str], key: str,
                 context: AnalysisContext) -> Iterable[Finding]:
        gaps = missing_categories(context.tag, set(answered))
        if not gaps:
            return

        yield finding(
            self, context, key,
            f"{base} is missing the {', '.join(gaps)} form"
            if len(gaps) == 1 else
            f"{base} is missing the {', '.join(gaps)} forms",
            detail=f"{context.locale.english_name} distinguishes "
                   f"{', '.join(categories_for(context.tag))}. The platform "
                   f"falls back to other for a missing one, so the wrong "
                   f"wording ships and nothing reports it.",
            origin=base,
        )

    def _extra(self, base: str, answered: dict[str, str], key: str,
               context: AnalysisContext) -> Iterable[Finding]:
        spare = extra_categories(context.tag, set(answered))
        if not spare:
            return

        yield finding(
            self, context, key,
            f"{base} has a {', '.join(spare)} form that this language does "
            f"not use",
            detail=f"{context.locale.english_name} distinguishes "
                   f"{', '.join(categories_for(context.tag))}. The platform "
                   f"will never select the others, so that is paid work "
                   f"sitting in a file doing nothing.",
            origin=base,
            severity=Severity.WARNING,
        )


def _resources(catalog: Catalog) -> dict[str, dict[str, str]]:
    """Plural resources in the catalog, as ``{name: {quantity: key}}``.

    An array is not a plural resource and is excluded by the qualifier being
    a number. They share a syntax in the catalog and nothing else.
    """
    found: dict[str, dict[str, str]] = {}

    for key in catalog.sorted_keys():
        for origin in catalog.messages[key].origins:
            if origin.kind is not OriginKind.ANDROID_STRING:
                continue

            symbol = origin.symbol
            if "[" not in symbol or not symbol.endswith("]"):
                continue

            base, _, rest = symbol.partition("[")
            quantity = rest[:-1]
            if quantity.isdigit():
                continue

            found.setdefault(base, {})[quantity] = key

    return found
