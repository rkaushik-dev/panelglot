"""Checks that need the whole language at once.

A rule sees one message and one translation, which is what keeps rules short
and independent. Three things worth checking cannot be seen that way, and they
used to live inside the check operation as a block of code that built findings
by hand and reported all three under one name.

That name was ``collisions``, and it covered mnemonic collisions, merged
translations and untranslated strings. Turning one of them off turned all
three off, and the report said ``collisions`` above a finding about a string
that was never translated.

They are three analyses now, named separately, disabled separately, and
documented separately.
"""

from __future__ import annotations
