"""All six emulated devices in one window.

This is a convenience shell for demonstrating and recording the system: instead
of arranging eight windows on screen, the device panel plus the main GUI is two.

It changes nothing about the architecture. Each panel here is the exact same
class the standalone emulator script runs, and each one still opens its **own
MQTT connection with its own client id** - six independent clients on the broker,
just hosted by one process. Run `start_all.sh` without arguments to get the
one-process-per-device layout instead.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                             QMainWindow, QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from emulators.door_emulator import DoorSensorPanel
from emulators.power_emulator import PowerSensorPanel
from emulators.relay_base import RelayPanel
from emulators.temp_emulator import TempSensorPanel
from ui import theme as t


class DevicePanelWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cold Chain Monitor - Device Panel')
        self.setMinimumSize(1160, 800)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % t.BG)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        root.addWidget(self._build_header())

        # Each panel opens its own MQTT connection, exactly as the standalone
        # emulator scripts do.
        self.panels = [
            TempSensorPanel(),
            DoorSensorPanel(),
            PowerSensorPanel(),
            RelayPanel('compressor', 'Compressor', '❄',
                       cfg.TOPIC_COMPRESSOR_CMD, cfg.TOPIC_COMPRESSOR_STS, t.ACCENT),
            RelayPanel('fan', 'Fan', '🌀',
                       cfg.TOPIC_FAN_CMD, cfg.TOPIC_FAN_STS, t.OK),
            RelayPanel('siren', 'Siren', '🚨',
                       cfg.TOPIC_SIREN_CMD, cfg.TOPIC_SIREN_STS, t.ALARM),
        ]

        grid = QGridLayout()
        grid.setSpacing(12)
        # No alignment flag: the cards stretch to fill their row, so the spare
        # height goes inside the cards rather than into a gap between the rows.
        for index, panel in enumerate(self.panels):
            grid.addWidget(panel, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)

        root.addLayout(grid, stretch=1)

    def _build_header(self):
        header = QFrame()
        header.setObjectName('panel')
        header.setStyleSheet(t.panel_style())
        header.setFixedHeight(66)

        row = QHBoxLayout(header)
        row.setContentsMargins(18, 10, 18, 10)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(t.label('DEVICE PANEL', size=16, bold=True))
        titles.addWidget(t.label('3 sensors and 3 relay actuators - each with its own '
                                 'MQTT connection', size=11, color=t.TEXT_DIM))
        row.addLayout(titles)
        row.addStretch()
        row.addWidget(t.label('broker: %s:%s' % (cfg.BROKER_HOST, cfg.BROKER_PORT),
                              size=10, color=t.TEXT_DIM))
        return header

    def closeEvent(self, event):
        for panel in self.panels:
            panel.shutdown()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DevicePanelWindow()
    window.show()
    sys.exit(app.exec_())
