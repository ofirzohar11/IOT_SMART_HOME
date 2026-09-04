"""Compressor current sensor (a clamp meter on the supply line).

Every other part of this system trusts the relay's own report. The relay says
ON because it was told ON - it cannot know whether the motor actually turned.
This sensor is the independent witness: it measures the current the compressor
draws, so the data manager can compare *what it commanded* against *what the
hardware did*.

Two failures become visible that nothing else in the system can see:

* **Open circuit** - commanded on, drawing nothing. Burnt-out relay contact,
  tripped overload, or a seized motor.
* **Welded relay** - commanded off, still drawing current. Contacts fused
  closed, and the cabinet will freeze its contents solid.
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
INRUSH_A = 11.5   # a motor draws several times its running current on start-up
RAMP = 0.55       # how fast the reading settles toward its target
NOISE = 0.08

GEOMETRY = (840, 400, 340, 320)


class CurrentSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='current',
            title='⚡  Compressor Current Sensor',
            subtitle='Clamp meter - measures what the motor really draws',
            topic_note='pub: %s\nsub: %s'
                       % (cfg.TOPIC_CURRENT, cfg.TOPIC_COMPRESSOR_STS),
        )
        self.setMinimumWidth(280)

        self.commanded_on = False
        self.value = 0.0
        self._starting = False

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.TEXT_DIM)

        self.stateLabel = ui.label('waiting for the compressor', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)

        self.openCircuitCheck = QCheckBox('Inject open circuit (no current)')
        self.weldedCheck = QCheckBox('Inject welded relay (current while off)')
        self.overloadCheck = QCheckBox('Inject overload (excess current)')
        for check in (self.openCircuitCheck, self.weldedCheck, self.overloadCheck):
            check.setStyleSheet(
                'QCheckBox { color: %s; font-family: %s; font-size: 12px; '
                'background: transparent; border: none; }'
                'QCheckBox::indicator { width: 15px; height: 15px; }'
                % (ui.TEXT, ui.FONT))

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.stateLabel)
        layout.addWidget(self.openCircuitCheck)
        layout.addWidget(self.weldedCheck)
        layout.addWidget(self.overloadCheck)

        self.body.addWidget(panel)

        self.mqtt.subscribe(cfg.TOPIC_COMPRESSOR_STS)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 32px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def on_mqtt_message(self, topic, payload):
        if topic != cfg.TOPIC_COMPRESSOR_STS:
            return
        now_on = payload.strip().upper() == 'ON'
        if now_on and not self.commanded_on:
            self._starting = True  # next sample shows the start-up inrush
        self.commanded_on = now_on

    def _target_current(self):
        if self.commanded_on:
            if self.openCircuitCheck.isChecked():
                return 0.0
            if self.overloadCheck.isChecked():
                return cfg.CURRENT_OVERLOAD_A + 1.6
            return cfg.CURRENT_NOMINAL_A
        return cfg.CURRENT_NOMINAL_A if self.weldedCheck.isChecked() else 0.0

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
        self.mqtt.publish_json(cfg.TOPIC_CURRENT, {'current': self.value,
                                                   'unit': 'A'})

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
