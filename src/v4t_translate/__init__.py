"""Localisation toolchain for the V4T thermal inkjet coder family.

The V4T products ship a Win32 HMI (V4T-TIJ, V4T-TIJ8PEN), an embedded panel
firmware (V4T-Mini) and an Android companion (V4T-Mobile). Every one of them
carries its own idea of what a translatable string is, and every one of them
draws onto a display that is far too small for a careless translation.

This package pulls those strings into one catalog, hands the catalog to a
translator as a workbook, checks what comes back against the physical limits of
the panel it will be drawn on, and writes the result back out in whatever shape
each target needs.
"""

__all__ = ["__version__"]

#: The one place the version lives. hatch reads it from here at build time.
__version__ = "0.3.0"
