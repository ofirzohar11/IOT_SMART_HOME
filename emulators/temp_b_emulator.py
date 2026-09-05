"""Redundant temperature probe (probe B).

Medical refrigerators carry a second, independent probe. One thermometer can
only ever tell you what it believes; two can tell you when one of them has
stopped being trustworthy. If the probes disagree by more than a couple of
degrees there is no way to know which one is right - and that uncertainty is
itself the alarm.

Two probes in the same cabinet track each other closely, so this one follows the
primary reading with a small calibration offset and its own noise. Its two
faults are the ways a probe really fails: a slowly growing offset as it ages,
and a reading that freezes at a perfectly plausible value.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import random

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QVBoxLayout

from config import mqtt_init as cfg
from config.mqtt_client import parse_json
from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel

CALIBRATION_OFFSET = 0.15  # probes are never perfectly matched
NOISE = 0.08
DRIFT_PER_TICK = 0.25

GEOMETRY = (440, 60, 340, 300)


class TempProbeBPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('temp_b')
        self.setMinimumWidth(280)

        self.primary = None
        self.value = None
        self.drift = 0.0
        self._frozen = None

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.OK)
        self.deltaLabel = ui.label('waiting for the primary probe', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.deltaLabel)
        self.body.addWidget(panel)

        self.mqtt.subscribe(cfg.TOPIC_TEMP)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(cfg.SENSOR_PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 28px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def on_fault_changed(self, fault_id, active):
        if fault_id == 'probe_drift' and not active:
            self.drift = 0.0
        elif fault_id == 'probe_frozen':
            self._frozen = self.value if active else None

    def on_mqtt_message(self, topic, payload):
        if topic != cfg.TOPIC_TEMP:
            return
        data = parse_json(payload, {})
        try:
            self.primary = float(data['temperature'])
        except (KeyError, TypeError, ValueError):
            pass

    def tick(self):
        if self.primary is None:
            return

        if self.has_fault('probe_frozen') and self._frozen is not None:
            self.value = self._frozen
        else:
            if self.has_fault('probe_drift'):
                self.drift += DRIFT_PER_TICK
            self.value = round(self.primary + CALIBRATION_OFFSET + self.drift
                               + random.uniform(-NOISE, NOISE), 2)

        delta = abs(self.value - self.primary)
        self.valueLabel.setText('%.1f °C' % self.value)
        self._style_value(ui.ALARM if delta > cfg.PROBE_DISAGREE_C else ui.OK)
        self.deltaLabel.setText('primary %.1f °C   ·   difference %.1f °C'
                                % (self.primary, delta))

        if not self.telemetry_allowed():
            return
        self.mqtt.publish_json(cfg.TOPIC_TEMP_B,
                               {'temperature': self.value, 'unit': 'C'})


if __name__ == '__main__':
    run_panel(TempProbeBPanel, GEOMETRY)
