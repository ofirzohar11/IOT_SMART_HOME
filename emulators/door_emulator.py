"""Door reed-switch emulator (the operator input device).

A magnetic reed switch on a refrigerator door only ever reports two states. The
button below toggles between them and publishes the result as a retained
message, so a data manager that starts later immediately learns whether the
door is currently open.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QLabel, QPushButton,
                             QVBoxLayout)

from config import mqtt_init as cfg
from emulators import ui_common as ui
from emulators.ui_common import EmulatorWindow

AUTO_CLOSE_SECONDS = 10


class DoorWindow(EmulatorWindow):

    def __init__(self):
        super().__init__(
            role='door',
            title='🚪  Door Sensor',
            subtitle='Reed switch - retained OPEN / CLOSED state',
            topic_note='pub: %s (retained)' % cfg.TOPIC_DOOR,
            geometry=(440, 60, 340, 330),
        )

        self.is_open = False
        self.opened_at = None

        panel = ui.make_panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.stateLabel = QLabel()
        self.stateLabel.setAlignment(Qt.AlignCenter)

        self.toggleBtn = QPushButton()
        self.toggleBtn.setFixedHeight(46)
        self.toggleBtn.clicked.connect(self.toggle)

        self.timerLabel = ui.label('closed', size=12, color=ui.TEXT_DIM,
                                   align=Qt.AlignCenter)

        self.autoCloseCheck = QCheckBox('Close automatically after %d s'
                                        % AUTO_CLOSE_SECONDS)
        self.autoCloseCheck.setStyleSheet(
            'QCheckBox { color: %s; font-family: %s; font-size: 12px; }'
            % (ui.TEXT, ui.FONT))

        layout.addWidget(self.stateLabel)
        layout.addWidget(self.toggleBtn)
        layout.addWidget(self.timerLabel)
        layout.addWidget(self.autoCloseCheck)

        self.body.addWidget(panel)
        self._paint()

        self.start_mqtt()

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(500)

    # -- behaviour ---------------------------------------------------------
    def toggle(self):
        self.is_open = not self.is_open
        self.opened_at = time.time() if self.is_open else None
        self._paint()
        self._publish()
        print('[door] %s' % ('OPEN' if self.is_open else 'CLOSED'))

    def on_connected(self):
        self._publish()

    def _publish(self):
        self.mqtt.publish_json(cfg.TOPIC_DOOR,
                               {'state': 'OPEN' if self.is_open else 'CLOSED'},
                               retain=True)

    def _tick(self):
        if not self.is_open or self.opened_at is None:
            return
        elapsed = time.time() - self.opened_at
        self.timerLabel.setText('open for %d s' % int(elapsed))
        color = ui.ALARM if elapsed >= cfg.DOOR_ALARM_SECONDS else (
            ui.WARN if elapsed >= cfg.DOOR_WARNING_SECONDS else ui.TEXT_DIM)
        self.timerLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 12px; background: transparent; '
            'border: none;' % (color, ui.FONT))
        if self.autoCloseCheck.isChecked() and elapsed >= AUTO_CLOSE_SECONDS:
            self.toggle()

    def _paint(self):
        if self.is_open:
            self.stateLabel.setText('DOOR OPEN')
            self.stateLabel.setStyleSheet(
                'color: #0B1220; background-color: %s; border-radius: 10px; '
                'font-family: %s; font-size: 22px; font-weight: bold; padding: 18px;'
                % (ui.WARN, ui.FONT))
            self.toggleBtn.setText('CLOSE DOOR')
            self.toggleBtn.setStyleSheet(ui.button_style(ui.OK))
            self.timerLabel.setText('open for 0 s')
        else:
            self.stateLabel.setText('DOOR CLOSED')
            self.stateLabel.setStyleSheet(
                'color: %s; background-color: transparent; border: 2px solid %s; '
                'border-radius: 10px; font-family: %s; font-size: 22px; '
                'font-weight: bold; padding: 16px;' % (ui.OK, ui.OK, ui.FONT))
            self.toggleBtn.setText('OPEN DOOR')
            self.toggleBtn.setStyleSheet(ui.button_style(ui.WARN))
            self.timerLabel.setText('closed')
            self.timerLabel.setStyleSheet(
                'color: %s; font-family: %s; font-size: 12px; background: transparent; '
                'border: none;' % (ui.TEXT_DIM, ui.FONT))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DoorWindow()
    window.show()
    sys.exit(app.exec_())
