"""The typeface the product ships with, and the fallbacks if it cannot load.

A console that is installed on somebody else's machine cannot rely on a font
being there. Naming one that is absent is worse than picking a different one:
Qt answers a missing family by rebuilding its entire font alias table, which
measured at 161 ms on every single start-up here, and then substitutes a face
of its own choosing anyway - so the same screen came out in Helvetica on a Mac,
Segoe on Windows and DejaVu on Linux, at three different widths.

So the two faces are shipped in ``assets/fonts`` and registered with Qt before
the first window exists:

    Inter           the interface itself - labels, headings, buttons, prose
    JetBrains Mono  every number that changes while you watch it

The split matters. Inter's digits are proportional: a 1 is narrower than a 0,
so a live temperature would shuffle sideways a few pixels every time it ticked
from 4.1 to 4.0. JetBrains Mono is tabular, so a column of readings stays a
column and a gauge value stays put. Prose gets the proportional face because
that is what prose is for; instruments get the fixed one.

Both are SIL Open Font License 1.1, which permits redistribution inside a
product - the licences travel with the files.
"""

import os
import sys

# Where the shipped faces live, resolved from this file rather than from the
# working directory: Qt's addApplicationFont silently fails on a relative path
# when the process was started from somewhere else, and a launcher script
# double-clicked in Finder starts it from ``/``.
FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'assets', 'fonts')

BUNDLED_UI = 'Inter'
BUNDLED_MONO = 'JetBrains Mono'

# Used only if the bundled files are missing - a checkout without the assets,
# or a stripped-down install. Each list is in preference order and every entry
# is a face that genuinely ships with that platform, so nothing here can
# trigger the alias-table rebuild described above.
_FALLBACK_UI = {
    'darwin': ['.AppleSystemUIFont', 'Helvetica Neue'],
    'win32': ['Segoe UI Variable Text', 'Segoe UI'],
    'linux': ['DejaVu Sans'],
}
_FALLBACK_MONO = {
    'darwin': ['Menlo', 'Monaco'],
    'win32': ['Cascadia Mono', 'Consolas'],
    'linux': ['DejaVu Sans Mono'],
}

# Filled in by load(). Until it runs, the fallbacks are what any caller gets.
_ui_family = None
_mono_family = None
_loaded = []
_missing = []


def _platform():
    if sys.platform == 'darwin':
        return 'darwin'
    if sys.platform.startswith('win'):
        return 'win32'
    return 'linux'


def _first_installed(candidates, database):
    """The first of ``candidates`` Qt actually has, or the last as a last resort."""
    installed = set(database.families())
    for name in candidates:
        if name in installed:
            return name
    return candidates[-1]


def load():
    """Register the shipped faces with Qt. Safe to call more than once.

    Must run after a QApplication exists and before any widget is styled.
    Returns ``(ui_family, mono_family)`` - the names to put in a stylesheet.
    """
    global _ui_family, _mono_family
    if _ui_family is not None:
        return _ui_family, _mono_family

    from PyQt5.QtGui import QFontDatabase

    for name in sorted(os.listdir(FONT_DIR)) if os.path.isdir(FONT_DIR) else []:
        if not name.lower().endswith(('.ttf', '.otf')):
            continue
        path = os.path.join(FONT_DIR, name)
        if QFontDatabase.addApplicationFont(path) == -1:
            _missing.append(name)
        else:
            _loaded.append(name)

    database = QFontDatabase()
    families = set(database.families())
    platform = _platform()

    _ui_family = (BUNDLED_UI if BUNDLED_UI in families
                  else _first_installed(_FALLBACK_UI[platform], database))
    _mono_family = (BUNDLED_MONO if BUNDLED_MONO in families
                    else _first_installed(_FALLBACK_MONO[platform], database))

    if _missing:
        print('[fonts] could not load: %s' % ', '.join(_missing))
    if _ui_family != BUNDLED_UI:
        print('[fonts] %s unavailable, falling back to %s'
              % (BUNDLED_UI, _ui_family))
    return _ui_family, _mono_family


def ui_family():
    """The interface face. Falls back to the platform's own if load() has not run."""
    if _ui_family is not None:
        return _ui_family
    return _FALLBACK_UI[_platform()][0]


def mono_family():
    """The tabular face used for every value that changes on screen."""
    if _mono_family is not None:
        return _mono_family
    return _FALLBACK_MONO[_platform()][0]
