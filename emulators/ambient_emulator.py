"""Ambient (room) temperature sensor.

Mounted outside the cabinet, on the storeroom wall. It is what lets the data
manager tell a *facility* problem from a *unit* problem: if the cabinet is
warming while the room sits at 22 C the refrigerator is at fault, but if the
room is at 34 C because the building air conditioning failed then the
refrigerator may be working perfectly and still losing the battle.

The cabinet probe subscribes to this topic and uses it as the ambient term in
its thermal model, so a hot storeroom genuinely makes cooling harder.
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

PUBLISH_MS = 3000
NOISE = 0.15
SETTLE = 0.25
HOT_ROOM_C = 34.0

GEOMETRY = (840, 60, 340, 280)


class AmbientSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('ambient')
        self.setMinimumWidth(280)
        self.value = cfg.AMBIENT_NOMINAL_C

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.valueLabel = QLabel('--')
        self.valueLabel.setAlignment(Qt.AlignCenter)
        self._style_value(ui.OK)
        self.stateLabel = ui.label('', size=11, color=ui.TEXT_DIM,
                                   align=Qt.AlignCenter)

        layout.addWidget(self.valueLabel)
        layout.addWidget(self.stateLabel)
        self.body.addWidget(panel)

        self.start_mqtt()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(PUBLISH_MS)

    def _style_value(self, color):
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 28px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    def on_connected(self):
        self._publish()

    def tick(self):
        target = HOT_ROOM_C if self.has_fault('room_hot') else cfg.AMBIENT_NOMINAL_C
        self.value += (target - self.value) * SETTLE
        self.value += random.uniform(-NOISE, NOISE)
        self.value = round(self.value, 1)

        hot = self.value >= cfg.AMBIENT_WARNING_C
        self.valueLabel.setText('%.1f °C' % self.value)
        self._style_value(ui.WARN if hot else ui.OK)
        self.stateLabel.setText('room too warm - cooling load is high' if hot
                                else 'room within normal range')
        self._publish()

    def _publish(self):
        if not self.telemetry_allowed():
            return
        self.mqtt.publish_json(cfg.TOPIC_AMBIENT,
                               {'ambient': self.value, 'unit': 'C'}, retain=True)


if __name__ == '__main__':
    run_panel(AmbientSensorPanel, GEOMETRY)
