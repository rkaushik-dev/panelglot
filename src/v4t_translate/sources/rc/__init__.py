"""Reader for Win32 resource scripts.

The ``.rc`` grammar is not small, but the part that carries translatable text
is. This package reads enough of the file to find dialogs, string tables and
menus, and deliberately treats everything else as opaque so that a bitmap
declaration or a version block cannot break an extraction run.
"""
