"""Siren relay - audible alarm, switched on for any active ALARM condition."""

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
        role='siren',
        name='Siren',
        icon='🚨',
        cmd_topic=cfg.TOPIC_SIREN_CMD,
        sts_topic=cfg.TOPIC_SIREN_STS,
        on_color='#EF4444',
        geometry=(400, 760, 330, 250),
    )
