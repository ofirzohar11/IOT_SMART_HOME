"""Redundant temperature probe (probe B).

Medical refrigerators carry a second, independent probe. One thermometer can
only ever tell you what it believes; two can tell you when one of them has
stopped being trustworthy. If the probes disagree by more than a couple of
degrees there is no way to know which one is right - and that uncertainty is
itself the alarm.

Two probes in the same cabinet track each other closely, so this one follows
the primary reading with a small calibration offset and its own noise. The two
fault switches are what make the disagreement rule demonstrable:

* **Drift** - a slowly growing offset, how a probe really fails as it ages.
* **Stuck** - the reading freezes, the classic dead-sensor signature that a
  single-probe system cannot detect at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import random

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QCheckBox, QLabel, QVBoxLayout

from config import mqtt_init as cfg
from config.mqtt_client import parse_json
from emulators import ui_common as ui
from emulators.ui_common import EmulatorPanel, run_panel

CALIBRATION_OFFSET = 0.15  # probes are never perfectly matched
NOISE = 0.08
DRIFT_PER_TICK = 0.25      # how fast the injected drift grows

GEOMETRY = (440, 60, 340, 340)


class TempProbeBPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='temp_b',
            title='🌡  Temperature Probe B',
            subtitle='Redundant probe - cross-checks the primary',
            topic_note='pub: %s\nsub: %s' % (cfg.TOPIC_TEMP_B, cfg.TOPIC_TEMP),
        )
        self.setMinimumWidth(280)

        self.primary = None
        self.value = None
        self.drift = 0.0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.OK)

        self.deltaLabel = ui.label('waiting for the primary probe', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)

        self.driftCheck = QCheckBox('Inject probe drift')
        self.stuckCheck = QCheckBox('Freeze reading (dead probe)')
        for check in (self.driftCheck, self.stuckCheck):
            check.setStyleSheet(
                'QCheckBox { color: %s; font-family: %s; font-size: 12px; '
                'background: transparent; border: none; }'
                'QCheckBox::indicator { width: 15px; height: 15px; }'
                % (ui.TEXT, ui.FONT))
        self.driftCheck.stateChanged.connect(self._reset_drift)

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.deltaLabel)
        layout.addWidget(self.driftCheck)
        layout.addWidget(self.stuckCheck)

        self.body.addWidget(panel)

        self.mqtt.subscribe(cfg.TOPIC_TEMP)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(cfg.SENSOR_PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 32px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def _reset_drift(self):
        if not self.driftCheck.isChecked():
            self.drift = 0.0

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

        if self.stuckCheck.isChecked():
            if self.value is None:
                self.value = self.primary
            # reading frozen: publish the same number forever
        else:
            if self.driftCheck.isChecked():
                self.drift += DRIFT_PER_TICK
            self.value = round(self.primary + CALIBRATION_OFFSET + self.drift
                               + random.uniform(-NOISE, NOISE), 2)

        delta = abs(self.value - self.primary)
        disagrees = delta > cfg.PROBE_DISAGREE_C
        self.valueLabel.setText('%.1f °C' % self.value)
        self._style_value(ui.ALARM if disagrees else ui.OK)
        self.deltaLabel.setText('primary %.1f °C   ·   difference %.1f °C'
                                % (self.primary, delta))

        self.mqtt.publish_json(cfg.TOPIC_TEMP_B, {'temperature': self.value,
                                                  'unit': 'C'})
        print('[temp_b] published %.2f C (primary %.2f)' % (self.value, self.primary))


if __name__ == '__main__':
    run_panel(TempProbeBPanel, GEOMETRY)
