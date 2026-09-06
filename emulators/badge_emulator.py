"""RFID badge reader mounted beside the door.

Regulated storage has to answer more than "was the door opened?" - it has to
answer "by whom, and were they allowed to?". Scanning a badge here gives the
data manager a name to attach to the next door opening, so the audit trail reads
*"door open 38 s - R. Levi"* rather than an anonymous event.

Opening the door with no recent scan is not blocked - a reader cannot physically
stop anyone - but it is recorded as an unauthorised access, which is exactly the
entry an auditor looks for.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout

from config import mqtt_init as cfg
from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel

# The staff whose badges this reader accepts.
STAFF = [
    ('OP-4471', 'R. Levi', 'Pharmacist'),
    ('OP-2210', 'A. Cohen', 'Storeroom technician'),
    ('OP-8834', 'M. Barak', 'Quality assurance'),
]

GEOMETRY = (840, 380, 340, 320)


class BadgeReaderPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('badge')
        self.setMinimumWidth(280)
        self.last_scan = None

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        self.readoutLabel = QLabel('No badge')
        self.readoutLabel.setAlignment(Qt.AlignCenter)
        self._style_readout(False)
        self.validityLabel = ui.label('scan a badge before opening the door',
                                      size=ui.SIZE_XS, color=ui.TEXT_MUTED,
                                      align=Qt.AlignCenter)

        layout.addWidget(self.readoutLabel)
        layout.addWidget(self.validityLabel)

        for badge_id, name, role in STAFF:
            button = QPushButton('%s  ·  %s' % (name, badge_id))
            button.setToolTip(role)
            button.setFixedHeight(ui.CONTROL_HEIGHT)
            # A staff badge is not the primary action on this window - three
            # of them in the accent read as three links - but it still has to
            # look pressable, so it keeps an outline and loses only the colour.
            button.setStyleSheet(ui.outline_button_style(ui.TEXT_DIM))
            button.clicked.connect(
                lambda _checked, b=badge_id, n=name, r=role: self.scan(b, n, r))
            layout.addWidget(button)

        self.body.addWidget(panel)
        self.start_mqtt()

    def _style_readout(self, valid, color=None):
        color = color or (ui.OK if valid else ui.OFFLINE_FG)
        self.readoutLabel.setStyleSheet(ui.state_plate_style(color, loud=False))

    def on_fault_changed(self, fault_id, active):
        if fault_id == 'reader_offline' and active:
            self.last_scan = None
            self.readoutLabel.setText('Reader offline')
            self._style_readout(False, ui.ALARM)
            self.validityLabel.setText('reader is not responding to scans')

    def scan(self, badge_id, name, role):
        if self.has_fault('reader_offline'):
            self.validityLabel.setText('reader is offline - scan ignored')
            return

        # An unreadable card, or one that is simply not on the staff list.
        if self.has_fault('badge_invalid'):
            badge_id, name, authorised = '??-??????', 'UNREADABLE BADGE', False
        elif self.has_fault('badge_unauthorised'):
            badge_id, name, authorised = 'OP-0000', 'UNKNOWN HOLDER', False
        else:
            authorised = True

        self.last_scan = (badge_id, name, time.time(), authorised)
        self.readoutLabel.setText(name)
        self._style_readout(authorised, None if authorised else ui.WARN)
        if not authorised:
            self.validityLabel.setText('badge rejected - access not authorised')

        if self.mqtt.suspended or self.has_fault('telemetry_stop'):
            return
        self.mqtt.publish_json(cfg.TOPIC_BADGE, {
            'operator_id': badge_id, 'name': name, 'role': role,
            'authorised': authorised,
        }, qos=1)

    def housekeeping(self):
        if self.last_scan is None or self.has_fault('reader_offline'):
            return
        _badge_id, _name, scanned_at, authorised = self.last_scan
        if not authorised:
            return
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
