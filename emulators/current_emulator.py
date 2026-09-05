"""Compressor current sensor (a clamp meter on the supply line).

Every other part of this system trusts the relay's own report. The relay says ON
because it was told ON - it cannot know whether the motor actually turned. This
sensor is the independent witness: it measures the current the compressor draws,
so the data manager can compare *what it commanded* against *what the hardware
did*.

Two failures become visible that nothing else in the system can see: an open
circuit, where the unit is commanded on and draws nothing, and a welded relay,
where it is commanded off and keeps running until the contents freeze solid.
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
from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel

PUBLISH_MS = 2000
INRUSH_A = 11.5   # a motor draws several times its running current on start-up
RAMP = 0.55
NOISE = 0.08

GEOMETRY = (1240, 380, 340, 280)


class CurrentSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('current')
        self.setMinimumWidth(280)

        self.commanded_on = False
        self.value = 0.0
        self._starting = False

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.TEXT_DIM)
        self.stateLabel = ui.label('waiting for the compressor', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.stateLabel)
        self.body.addWidget(panel)

        self.mqtt.subscribe(cfg.TOPIC_COMPRESSOR_STS)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 28px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def on_mqtt_message(self, topic, payload):
        if topic != cfg.TOPIC_COMPRESSOR_STS:
            return
        now_on = payload.strip().upper() == 'ON'
        if now_on and not self.commanded_on:
            self._starting = True  # next sample shows the start-up inrush
        self.commanded_on = now_on

    def _target_current(self):
        if self.has_fault('erratic_current'):
            return max(0.0, cfg.CURRENT_NOMINAL_A + random.uniform(-3.5, 4.5))
        if self.commanded_on:
            if self.has_fault('open_circuit'):
                return 0.0
            if self.has_fault('overload'):
                return cfg.CURRENT_OVERLOAD_A + 1.6
            return cfg.CURRENT_NOMINAL_A
        return cfg.CURRENT_NOMINAL_A if self.has_fault('welded_relay') else 0.0

    def tick(self):
        target = self._target_current()
        if self._starting and target > 0:
            self.value = INRUSH_A
            self._starting = False
        else:
            self.value += (target - self.value) * RAMP
            if target > 0:
                self.value += random.uniform(-NOISE, NOISE)
        self.value = round(max(0.0, self.value), 2)

        self._update_labels()
        if not self.telemetry_allowed():
            return
        self.mqtt.publish_json(cfg.TOPIC_CURRENT,
                               {'current': self.value, 'unit': 'A'})

    def _update_labels(self):
        self.valueLabel.setText('%.2f A' % self.value)
        running = self.value >= cfg.CURRENT_RUNNING_MIN_A

        if self.value > cfg.CURRENT_OVERLOAD_A:
            color, state = ui.ALARM, 'overload - drawing far too much'
        elif self.commanded_on and not running:
            color, state = ui.ALARM, 'commanded ON but nothing is drawing'
        elif not self.commanded_on and running:
            color, state = ui.ALARM, 'commanded OFF but still drawing'
        elif running:
            color, state = ui.OK, 'motor running normally'
        else:
            color, state = ui.TEXT_DIM, 'idle - no current'

        self._style_value(color)
        self.stateLabel.setText(state)


if __name__ == '__main__':
    run_panel(CurrentSensorPanel, GEOMETRY)
