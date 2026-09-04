"""RFID badge reader mounted beside the door.

Regulated storage has to answer more than "was the door opened?" - it has to
answer "by whom, and were they allowed to?". Scanning a badge here gives the
data manager a name to attach to the next door opening, so the audit trail
reads *"door open 38 s - R. Levi"* rather than an anonymous event.

Opening the door with no recent scan is not blocked - a reader cannot physically
stop anyone - but it is recorded as an unauthorised access, which is exactly the
entry an auditor looks for.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout

from config import mqtt_init as cfg
from emulators import ui_common as ui
from emulators.ui_common import EmulatorPanel, run_panel

# The staff whose badges this reader accepts.
STAFF = [
    ('OP-4471', 'R. Levi', 'Pharmacist'),
    ('OP-2210', 'A. Cohen', 'Storeroom technician'),
    ('OP-8834', 'M. Barak', 'Quality assurance'),
]

GEOMETRY = (1240, 60, 340, 340)


class BadgeReaderPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='badge',
            title='🪪  RFID Badge Reader',
            subtitle='Door access control - names the operator',
            topic_note='pub: %s' % cfg.TOPIC_BADGE,
        )
        self.setMinimumWidth(280)

        self.last_scan = None

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.readoutLabel = QLabel('NO BADGE')
        self.readoutLabel.setAlignment(Qt.AlignCenter)
        self._style_readout(False)

        self.validityLabel = ui.label('scan a badge before opening the door',
                                      size=11, color=ui.TEXT_DIM,
                                      align=Qt.AlignCenter)

        layout.addWidget(self.readoutLabel)
        layout.addWidget(self.validityLabel)

        for badge_id, name, role in STAFF:
            button = QPushButton('%s  ·  %s' % (name, badge_id))
            button.setToolTip(role)
            button.setFixedHeight(34)
            button.setStyleSheet(ui.outline_button_style(ui.ACCENT))
            button.clicked.connect(
                lambda _checked, b=badge_id, n=name, r=role: self.scan(b, n, r))
            layout.addWidget(button)

        self.body.addWidget(panel)

        self.start_mqtt()

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(1000)

    def _style_readout(self, valid):
        color = ui.OK if valid else ui.OFF
        self.readoutLabel.setStyleSheet(
            'color: %s; background: transparent; border: 2px solid %s; '
            'border-radius: 10px; font-family: %s; font-size: 17px; '
            'font-weight: bold; padding: 12px;' % (color, color, ui.FONT))

    def scan(self, badge_id, name, role):
        self.last_scan = (badge_id, name, time.time())
        self.readoutLabel.setText(name)
        self._style_readout(True)
        self.mqtt.publish_json(cfg.TOPIC_BADGE, {
            'operator_id': badge_id,
            'name': name,
            'role': role,
        })
        print('[badge] %s (%s) scanned' % (name, badge_id))

    def _tick(self):
        if self.last_scan is None:
            return
        _badge_id, name, scanned_at = self.last_scan
        remaining = cfg.BADGE_VALID_SECONDS - (time.time() - scanned_at)
        if remaining > 0:
            self.validityLabel.setText('valid for another %d s' % int(remaining))
        else:
            self.validityLabel.setText('scan expired - the door is unattended')
            self.readoutLabel.setText('NO BADGE')
            self._style_readout(False)
            self.last_scan = None


if __name__ == '__main__':
    run_panel(BadgeReaderPanel, GEOMETRY)
