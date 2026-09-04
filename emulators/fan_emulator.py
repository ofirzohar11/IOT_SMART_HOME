"""Circulation fan relay - evens out the air temperature inside the cabinet."""

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
        role='fan',
        name='Fan',
        icon='🌀',
        cmd_topic=cfg.TOPIC_FAN_CMD,
        sts_topic=cfg.TOPIC_FAN_STS,
        on_color='#22C55E',
        geometry=(40, 760, 330, 250),
    )
