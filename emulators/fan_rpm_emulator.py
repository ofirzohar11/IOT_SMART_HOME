"""Fan tachometer (a Hall-effect sensor on the circulation fan).

The same idea as the compressor current clamp, applied to the fan: the relay
reports the command, the tachometer reports the truth.

A stalled circulation fan is a quiet failure. The cabinet as a whole may still
average 5 C, so the temperature probes stay happy, while the air stops moving
and the top shelf drifts far warmer than the bottom one. Nothing else in this
system would notice.

The three fault switches cover the ways a fan really fails:

* **Stalled** - blocked or seized, no rotation at all.
* **Worn bearing** - still turning, but too slowly to circulate properly. This
  is the interesting one: it is a warning long before it becomes a failure.
* **Free-running** - the relay is off but the fan keeps spinning, a welded
  contact just like the compressor's.
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
from emulators import ui_common as ui
from emulators.ui_common import EmulatorPanel, run_panel

PUBLISH_MS = 2000
SPIN_UP = 0.6     # the fan reaches speed quickly
SPIN_DOWN = 0.35  # and coasts down more slowly
NOISE = 25.0      # rpm

GEOMETRY = (1240, 400, 340, 340)


class FanRpmSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='fan_rpm',
            title='🌀  Fan Tachometer',
            subtitle='Hall sensor - measures whether the fan really turns',
            topic_note='pub: %s\nsub: %s' % (cfg.TOPIC_FAN_RPM, cfg.TOPIC_FAN_STS),
        )
        self.setMinimumWidth(280)

        self.commanded_on = False
        self.value = 0.0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.TEXT_DIM)

        self.stateLabel = ui.label('waiting for the fan', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)

        self.stalledCheck = QCheckBox('Inject stall (blocked fan)')
        self.wornCheck = QCheckBox('Inject worn bearing (slow)')
        self.freeRunCheck = QCheckBox('Inject free-running (spins while off)')
        for check in (self.stalledCheck, self.wornCheck, self.freeRunCheck):
            check.setStyleSheet(
                'QCheckBox { color: %s; font-family: %s; font-size: 12px; '
                'background: transparent; border: none; }'
                'QCheckBox::indicator { width: 15px; height: 15px; }'
                % (ui.TEXT, ui.FONT))

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.stateLabel)
        layout.addWidget(self.stalledCheck)
        layout.addWidget(self.wornCheck)
        layout.addWidget(self.freeRunCheck)

        self.body.addWidget(panel)

        self.mqtt.subscribe(cfg.TOPIC_FAN_STS)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 32px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def on_mqtt_message(self, topic, payload):
        if topic == cfg.TOPIC_FAN_STS:
            self.commanded_on = payload.strip().upper() == 'ON'

    def _target_rpm(self):
        if self.commanded_on:
            if self.stalledCheck.isChecked():
                return 0.0
            if self.wornCheck.isChecked():
                return cfg.FAN_RPM_DEGRADED - 250
            return float(cfg.FAN_RPM_NOMINAL)
        return float(cfg.FAN_RPM_NOMINAL) if self.freeRunCheck.isChecked() else 0.0

    def tick(self):
        target = self._target_rpm()
        rate = SPIN_UP if target > self.value else SPIN_DOWN
        self.value += (target - self.value) * rate
        if target > 0:
            self.value += random.uniform(-NOISE, NOISE)
        self.value = round(max(0.0, self.value))

        self._update_labels()
        self.mqtt.publish_json(cfg.TOPIC_FAN_RPM, {'rpm': self.value,
                                                   'unit': 'rpm'})

    def _update_labels(self):
        self.valueLabel.setText('%d rpm' % int(self.value))
        turning = self.value >= cfg.FAN_RPM_MIN

        if self.commanded_on and not turning:
            color, state = ui.ALARM, 'commanded ON but the fan is not turning'
        elif not self.commanded_on and turning:
            color, state = ui.ALARM, 'commanded OFF but still spinning'
        elif self.commanded_on and self.value < cfg.FAN_RPM_DEGRADED:
            color, state = ui.WARN, 'turning slowly - bearing wear'
        elif turning:
            color, state = ui.OK, 'circulating normally'
        else:
            color, state = ui.TEXT_DIM, 'stopped'

        self._style_value(color)
        self.stateLabel.setText(state)


if __name__ == '__main__':
    run_panel(FanRpmSensorPanel, GEOMETRY)
