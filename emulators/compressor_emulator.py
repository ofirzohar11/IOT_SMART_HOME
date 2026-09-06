"""Compressor relay - see emulators/relay_base.py for the shared behaviour."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

from emulators.relay_base import run_relay
from ui import theme as t

if __name__ == '__main__':
    run_relay('compressor', t.ACCENT, (40, 700, 330, 250))
