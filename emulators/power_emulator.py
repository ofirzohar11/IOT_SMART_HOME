"""Power supply sensor emulator.

A cold chain unit is only as safe as its power supply, so the unit reports
whether it runs on mains or on its backup battery, and how much charge is left.
Switching to battery starts a drain, which eventually produces a low-battery
alarm - a second time based rule for the data manager to handle.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QVBoxLayout)

from config import mqtt_init as cfg
from emulators import ui_common as ui
from emulators.ui_common import EmulatorPanel, run_panel

PUBLISH_MS = 3000
DRAIN_PER_TICK = 1.5     # percent of battery lost per publish while on battery
RECHARGE_PER_TICK = 0.8  # percent regained per publish while on mains

GEOMETRY = (440, 420, 340, 300)


class PowerSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='power',
            title='🔌  Power Supply Sensor',
            subtitle='Mains / battery source and charge level',
            topic_note='pub: %s (retained)' % cfg.TOPIC_POWER,
        )
        self.setMinimumWidth(300)

        self.source = 'MAINS'
        self.battery = 100.0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.sourceLabel = QLabel()
        self.sourceLabel.setAlignment(Qt.AlignCenter)

        self.batteryBar = QProgressBar()
        self.batteryBar.setRange(0, 100)
        self.batteryBar.setTextVisible(True)
        self.batteryBar.setFixedHeight(24)

        self.toggleBtn = QPushButton('SIMULATE POWER CUT')
        self.toggleBtn.setFixedHeight(42)
        self.toggleBtn.clicked.connect(self.toggle)

        row = QHBoxLayout()
        row.addWidget(ui.label('Backup battery', size=11, color=ui.TEXT_DIM))
        row.addStretch()
        self.batteryNote = ui.label('', size=11, color=ui.TEXT_DIM)
        row.addWidget(self.batteryNote)

        layout.addWidget(self.sourceLabel)
        layout.addLayout(row)
        layout.addWidget(self.batteryBar)
        layout.addWidget(self.toggleBtn)

        self.body.addWidget(panel)
        self._paint()

        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(PUBLISH_MS)

    def toggle(self):
        self.source = 'BATTERY' if self.source == 'MAINS' else 'MAINS'
        self._paint()
        self._publish()
        print('[power] source is now %s' % self.source)

    def on_connected(self):
        self._publish()

    def tick(self):
        if self.source == 'BATTERY':
            self.battery = max(0.0, self.battery - DRAIN_PER_TICK)
        else:
            self.battery = min(100.0, self.battery + RECHARGE_PER_TICK)
        self.battery = round(self.battery, 1)
        self._paint()
        self._publish()

    def _publish(self):
        self.mqtt.publish_json(cfg.TOPIC_POWER,
                               {'source': self.source, 'battery': self.battery},
                               retain=True)

    def _paint(self):
        on_mains = self.source == 'MAINS'
        color = ui.OK if on_mains else ui.WARN
        self.sourceLabel.setText('POWER: ' + self.source)
        self.sourceLabel.setStyleSheet(
            'color: %s; background: transparent; border: 2px solid %s; '
            'border-radius: 10px; font-family: %s; font-size: 19px; '
            'font-weight: bold; padding: 13px;' % (color, color, ui.FONT))
        self.toggleBtn.setText('RESTORE MAINS' if not on_mains else 'SIMULATE POWER CUT')
        self.toggleBtn.setStyleSheet(ui.button_style(ui.OK if not on_mains else ui.WARN))

        bar_color = ui.ALARM if self.battery <= cfg.BATTERY_ALARM_PERCENT else (
            ui.WARN if self.battery <= 50 else ui.OK)
        self.batteryBar.setValue(int(self.battery))
        self.batteryBar.setFormat('%.0f %%' % self.battery)
        self.batteryBar.setStyleSheet('''
            QProgressBar {
                background-color: %s;
                border: 1px solid %s;
                border-radius: 6px;
                color: %s;
                font-family: %s;
                font-size: 11px;
                font-weight: bold;
                text-align: center;
            }
            QProgressBar::chunk { background-color: %s; border-radius: 5px; }
        ''' % (ui.BG, ui.BORDER, ui.TEXT, ui.FONT, bar_color))
        self.batteryNote.setText('draining' if not on_mains else 'charging')


if __name__ == '__main__':
    run_panel(PowerSensorPanel, GEOMETRY)
