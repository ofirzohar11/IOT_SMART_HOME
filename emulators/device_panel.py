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

from PyQt5.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                             QMainWindow, QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from emulators.ambient_emulator import AmbientSensorPanel
from emulators.badge_emulator import BadgeReaderPanel
from emulators.current_emulator import CurrentSensorPanel
from emulators.door_emulator import DoorSensorPanel
from emulators.fan_rpm_emulator import FanRpmSensorPanel
from emulators.power_emulator import PowerSensorPanel
from emulators.relay_base import RelayPanel
from emulators.temp_b_emulator import TempProbeBPanel
from emulators.temp_emulator import TempSensorPanel
from ui import theme as t

COLUMNS = 4


class DevicePanelWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cold Chain Monitor - Device Panel')
        self.setMinimumSize(1320, 940)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % t.BG)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(t.SPACE_MD, t.SPACE_MD, t.SPACE_MD, t.SPACE_MD)
        root.setSpacing(t.SPACE)

        root.addWidget(self._build_header())

        # Each panel opens its own MQTT connection, exactly as the standalone
        # emulator scripts do. Grouped by role: the cabinet sensors first, then
        # the diagnostic sensors that watch the hardware, then the actuators.
        self.panels = [
            TempSensorPanel(),
            TempProbeBPanel(),
            AmbientSensorPanel(),
            DoorSensorPanel(),

            BadgeReaderPanel(),
            PowerSensorPanel(),
            CurrentSensorPanel(),
            FanRpmSensorPanel(),

            RelayPanel('compressor', t.ACCENT),
            RelayPanel('fan', t.OK),
            RelayPanel('siren', t.ALARM),
        ]

        grid = QGridLayout()
        grid.setSpacing(t.SPACE)
        # No alignment flag: the cards stretch to fill their row, so the spare
        # height goes inside the cards rather than into a gap between the rows.
        for index, panel in enumerate(self.panels):
            grid.addWidget(panel, index // COLUMNS, index % COLUMNS)
        for column in range(COLUMNS):
            grid.setColumnStretch(column, 1)
        # The sensor rows carry more controls than the relay row, so they get a
        # larger share of the height.
        grid.setRowStretch(0, 4)
        grid.setRowStretch(1, 4)
        grid.setRowStretch(2, 3)

        root.addLayout(grid, stretch=1)

    def _build_header(self):
        header = QFrame()
        header.setObjectName('panel')
        header.setStyleSheet(t.panel_style())
        header.setFixedHeight(66)

        row = QHBoxLayout(header)
        row.setContentsMargins(t.SPACE_MD + 2, 10, t.SPACE_MD + 2, 10)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(t.label('Device panel', size=t.SIZE_LG,
                                 weight=t.W_BOLD, spacing=-0.2))
        titles.addWidget(t.label('8 sensors and 3 relay actuators - each with '
                                 'its own MQTT connection', size=t.SIZE_XS,
                                 color=t.TEXT_MUTED))
        row.addLayout(titles)
        row.addStretch()
        row.addWidget(t.label('broker: %s:%s' % (cfg.BROKER_HOST, cfg.BROKER_PORT),
                              size=t.SIZE_XS, color=t.TEXT_MUTED, mono=True))
        return header

    def closeEvent(self, event):
        for panel in self.panels:
            panel.shutdown()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    t.apply_tooltip_style(app)
    window = DevicePanelWindow()
    window.show()
    sys.exit(app.exec_())
