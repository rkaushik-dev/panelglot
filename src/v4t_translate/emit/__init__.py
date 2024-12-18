"""Writing the catalog back out in whatever shape each target needs.

An emitter takes a catalog, one language's translations and a destination, and
produces a file. It never decides whether a translation is good enough to
ship; that is what ``check`` is for, and mixing the two would mean a build
that quietly dropped strings it did not like.
"""

from .base import EmitResult, Emitter

__all__ = ["EmitResult", "Emitter"]
