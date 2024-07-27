"""The catalog: the one representation of a translatable string in this pipeline.

Sources produce it, workbooks are generated from it, rules run against it, and
emitters consume it. Nothing else in the package is allowed to invent its own
idea of what a message is.
"""

from .model import Message, Origin, OriginKind
from .translations import Translation, TranslationSet, TranslationState

__all__ = [
    "Message",
    "Origin",
    "OriginKind",
    "Translation",
    "TranslationSet",
    "TranslationState",
]
