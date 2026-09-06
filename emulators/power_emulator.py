"""Power supply sensor emulator.

A cold chain unit is only as safe as its power supply, so it reports whether it
runs on mains or on its backup battery, and how much charge is left. Switching
to battery starts a drain, which eventually produces a low-battery alarm - a
time-based rule for the data manager to handle.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from config import mqtt_init as cfg
from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel

PUBLISH_MS = 3000
DRAIN_PER_TICK = 1.5      # percent lost per publish while on battery
FAST_DRAIN_PER_TICK = 6.0  # the injected depletion fault
RECHARGE_PER_TICK = 0.8

GEOMETRY = (1240, 60, 340, 300)


class PowerSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('power')
        self.setMinimumWidth(280)

        self.source = 'MAINS'
        self.battery = 100.0
        self._flap = 0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.sourceLabel = QLabel()
        self.sourceLabel.setAlignment(Qt.AlignCenter)
        self.batteryBar = QProgressBar()
        self.batteryBar.setRange(0, 100)
        self.toggleBtn = QPushButton()
        self.toggleBtn.setFixedHeight(ui.CONTROL_HEIGHT + 4)
        self.toggleBtn.clicked.connect(self.toggle)

        row = QHBoxLayout()
        row.setSpacing(ui.SPACE_SM)
        row.addWidget(ui.label('Backup battery', size=ui.SIZE_XS,
                               color=ui.TEXT_MUTED))
        row.addStretch()
        self.batteryNote = ui.label('', size=ui.SIZE_XS, color=ui.TEXT_MUTED)
        row.addWidget(self.batteryNote)
        self.batteryPercent = ui.label('--', size=ui.SIZE_XS, mono=True)
        row.addWidget(self.batteryPercent)

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
        if self.has_fault('power_outage'):
            self.batteryNote.setText('outage simulated - clear the fault first')
            return
        self.source = 'BATTERY' if self.source == 'MAINS' else 'MAINS'
        self._paint()
        self._publish()

    def on_fault_changed(self, fault_id, active):
        if fault_id == 'power_outage':
            self.source = 'BATTERY' if active else 'MAINS'
            self._paint()
            self._publish()
        elif fault_id == 'power_unstable' and not active:
            self.source = 'MAINS'
            self._paint()

    def on_connected(self):
        self._publish()

    def tick(self):
        if self.has_fault('power_unstable'):
            # Supply flaps between mains and battery every few samples.
            self._flap += 1
            if self._flap % 2 == 0:
                self.source = 'BATTERY' if self.source == 'MAINS' else 'MAINS'

        if self.source == 'BATTERY':
            drain = FAST_DRAIN_PER_TICK if self.has_fault('battery_drain') else DRAIN_PER_TICK
            self.battery = max(0.0, self.battery - drain)
        else:
            self.battery = min(100.0, self.battery + RECHARGE_PER_TICK)
        self.battery = round(self.battery, 1)

        self._paint()
        self._publish()

    def _publish(self):
        if not self.telemetry_allowed():
            return
        self.mqtt.publish_json(cfg.TOPIC_POWER,
                               {'source': self.source, 'battery': self.battery},
                               retain=True)

    def _paint(self):
        on_mains = self.source == 'MAINS'
        color = ui.OK if on_mains else ui.WARN
        self.sourceLabel.setText('Power: ' + self.source.title())
        self.sourceLabel.setStyleSheet(
            ui.state_plate_style(color, loud=not on_mains))
        # Cutting the mains arms a fault, so that direction is the destructive
        # one and is drawn as such. Restoring it is ordinary.
        if on_mains:
            self.toggleBtn.setText('Simulate power cut')
            self.toggleBtn.setStyleSheet(ui.outline_button_style(ui.WARN))
        else:
            self.toggleBtn.setText('Restore mains')
            self.toggleBtn.setStyleSheet(ui.outline_button_style(ui.ACCENT))

        bar_color = ui.ALARM if self.battery <= cfg.BATTERY_ALARM_PERCENT else (
            ui.WARN if self.battery <= 50 else ui.OK)
        # The figure reads beside the bar, not on top of it. Printed inside,
        # it sat on the filled chunk at a full charge and on the empty track at
        # a flat one, so no single ink colour was legible in both - and at 20 %
        # the number was half on one and half on the other.
        self.batteryBar.setValue(int(self.battery))
        self.batteryBar.setTextVisible(False)
        self.batteryBar.setFixedHeight(8)
        self.batteryBar.setStyleSheet('''
            QProgressBar { background-color: %s; border: 1px solid %s;
                border-radius: %dpx; }
            QProgressBar::chunk { background-color: %s; border-radius: %dpx; }
        ''' % (ui.BG, ui.BORDER, ui.RADIUS_SM - 3, bar_color,
               ui.RADIUS_SM - 3))
        self.batteryPercent.setText('%.0f %%' % self.battery)
        self.batteryPercent.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'background: transparent; border: none;'
            % (bar_color if self.battery <= 50 else ui.TEXT, ui.FONT_MONO,
               ui.SIZE_XS, ui.W_MEDIUM))
        self.batteryNote.setText('draining' if not on_mains else 'charging')


if __name__ == '__main__':
    run_panel(PowerSensorPanel, GEOMETRY)
