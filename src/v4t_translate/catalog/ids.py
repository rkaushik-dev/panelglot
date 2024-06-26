"""Deriving the key a message is filed under.

The key has to survive things that are not really changes. Somebody moves a
button three dialog units to the left, renames ``IDC_STATIC12`` to
``IDC_STATIC13``, or moves a whole property page into another file. None of
that should make the translator retype anything.

So the key is derived from what the translator actually sees: the source text,
plus a context when two identical strings need different translations. It is
deliberately not derived from the control id, the dialog id or the file, all
three of which churn constantly in a Win32 resource script.

The key is readable on purpose. A reviewer reading a diff of the catalog
should be able to tell which string moved without decoding a hash, so the
slug goes in front and the hash only settles collisions.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "SLUG_LIMIT",
    "HASH_LENGTH",
    "normalize_source",
    "slugify",
    "message_key",
    "source_fingerprint",
    "sort_key",
]

#: Longest slug prefix put in front of the hash.
SLUG_LIMIT = 32

#: Hex digits of the discriminating hash. Six is 16.7M buckets, which against
#: the ~1400 strings the whole product family carries is comfortable.
HASH_LENGTH = 6

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_MNEMONIC_RUN = re.compile(r"&&|&")


def normalize_source(text: str) -> str:
    """Put source text in the one form keys and fingerprints are taken over.

    Line endings collapse to ``\\n`` because a resource script edited on
    Windows and one edited over ssh must not produce two keys for one string.
    Unicode goes to NFC so a decomposed umlaut typed by one tool matches a
    precomposed one typed by another.
    """
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def slugify(text: str) -> str:
    """Turn source text into the readable part of a key.

    Ampersands are dropped first, so ``&Print`` and ``P&rint`` slug the same
    and only the hash tells them apart. That is the behaviour we want: the
    mnemonic position is a real difference but it should not dominate the
    readable prefix.
    """
    stripped = _MNEMONIC_RUN.sub("", normalize_source(text))
    folded = unicodedata.normalize("NFKD", stripped)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_SLUG.sub("-", ascii_only).strip("-")
    if not slug:
        # Chinese, Japanese, Korean and Arabic source strings slug to nothing.
        # They are rare as source but they do occur in the config tool, where
        # somebody hardcoded a unit already in the target script.
        return "x"
    return slug[:SLUG_LIMIT].rstrip("-")


def message_key(source_text: str, context: str | None = None) -> str:
    """The catalog key for one message.

    ``context`` is folded into the hash rather than the slug so that two
    contexts of the same English sort next to each other in the catalog file.
    """
    normalized = normalize_source(source_text)
    payload = f"{context or ''}\x00{normalized}".encode()
    digest = hashlib.sha1(payload).hexdigest()[:HASH_LENGTH]
    return f"{slugify(source_text)}.{digest}"


def source_fingerprint(source_text: str) -> str:
    """Hash of the source text alone, stored beside every translation.

    When the English is edited the key changes too, so this looks redundant.
    It is not: a translation carried forward by a fuzzy match keeps its old
    fingerprint, and that is how ``check`` knows to flag it for review rather
    than trusting it.
    """
    return hashlib.sha256(normalize_source(source_text).encode()).hexdigest()[:16]


def sort_key(key: str) -> tuple[str, str]:
    """Order keys by their readable part, then the hash.

    Sorting on the raw key would put ``ok.1a2b3c`` before ``ok-cancel.0f9e8d``
    because ``.`` sorts under ``-``, which reads as a bug in every catalog
    diff. Splitting the two parts fixes the order.
    """
    slug, _, digest = key.rpartition(".")
    if not slug:
        return (key, "")
    return (slug, digest)
