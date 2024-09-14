"""Checks that run over a translated catalog.

Every rule answers one question about one message in one language, and none of
them know about each other. That is what makes the set safe to grow: a new
check is a new file and a line in the registry, and it cannot break the ones
already there.
"""

from .result import Finding, Report, Severity

__all__ = ["Finding", "Report", "Severity"]
