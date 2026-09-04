"""Compressor relay - the cooling element of the refrigeration unit."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

from config import mqtt_init as cfg
from emulators.relay_base import run_relay

if __name__ == '__main__':
    run_relay(
        role='compressor',
        name='Compressor',
        icon='❄',
        cmd_topic=cfg.TOPIC_COMPRESSOR_CMD,
        sts_topic=cfg.TOPIC_COMPRESSOR_STS,
        on_color='#38BDF8',
        geometry=(40, 500, 330, 250),
    )
