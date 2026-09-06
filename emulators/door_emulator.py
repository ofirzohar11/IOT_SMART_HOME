"""Door reed-switch emulator (the operator input device).

A magnetic reed switch on a refrigerator door only ever reports two states. The
button below toggles between them and publishes the result as a retained
message, so a data manager that starts later immediately learns whether the door
is currently open.

Its faults cover the three ways this goes wrong in practice: somebody opening
the door without badging in, a door that will not close, and a switch that
insists the door is shut while it stands wide open.
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

GEOMETRY = (440, 380, 340, 300)


class DoorSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('door')
        self.setMinimumWidth(280)

        self.is_open = False          # the physical door
        self.opened_at = None

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.stateLabel = QLabel()
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self.toggleBtn = QPushButton()
        self.toggleBtn.setFixedHeight(42)
        self.toggleBtn.clicked.connect(self.toggle)
        self.timerLabel = ui.label('closed', size=ui.SIZE_XS,
                                   color=ui.TEXT_MUTED,
                                   align=Qt.AlignCenter)

        layout.addWidget(self.stateLabel)
        layout.addWidget(self.toggleBtn)
        layout.addWidget(self.timerLabel)
        self.body.addWidget(panel)

        self._paint()
        self.start_mqtt()

    # -- behaviour ---------------------------------------------------------
    def toggle(self):
        if self.is_open and self.has_fault('door_stuck'):
            self.timerLabel.setText('door is jammed open - clear the fault first')
            return
        self._set_open(not self.is_open)

    def _set_open(self, is_open):
        self.is_open = is_open
        self.opened_at = time.time() if is_open else None
        self._paint()
        self._publish()

    def on_fault_changed(self, fault_id, active):
        if fault_id in ('door_forced', 'door_stuck') and active:
            self._set_open(True)
        elif fault_id == 'door_stuck' and not active:
            self._set_open(False)
        elif fault_id == 'door_sensor_fail':
            # The switch lies about the door; publish what it now claims.
            self._publish()

    def on_connected(self):
        self._publish()

    def _reported_state(self):
        """A failed switch reports CLOSED whatever the door is really doing."""
        if self.has_fault('door_sensor_fail'):
            return 'CLOSED'
        return 'OPEN' if self.is_open else 'CLOSED'

    def _publish(self):
        if self.mqtt.suspended or self.has_fault('telemetry_stop'):
            return
        self.mqtt.publish_json(cfg.TOPIC_DOOR, {'state': self._reported_state()},
                               retain=True, qos=1)

    def housekeeping(self):
        if not self.is_open or self.opened_at is None:
            return
        elapsed = int(time.time() - self.opened_at)
        note = 'open for %d s' % elapsed
        if self.has_fault('door_sensor_fail'):
            note += '  (switch is reporting CLOSED)'
        self.timerLabel.setText(note)
        color = ui.ALARM if elapsed >= cfg.DOOR_ALARM_SECONDS else (
            ui.WARN if elapsed >= cfg.DOOR_WARNING_SECONDS else ui.TEXT_DIM)
        self.timerLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'background: transparent; border: none;'
            % (color, ui.FONT, ui.SIZE_XS, ui.W_MEDIUM))

    def _paint(self):
        # The plate carries the state; the button carries the action. They used
        # to swap roles - an open door was drawn amber and the button that
        # opened it was drawn amber too, so the loudest thing on the window was
        # a control rather than the condition it produced.
        if self.is_open:
            self.stateLabel.setText('Door open')
            self.stateLabel.setStyleSheet(
                ui.state_plate_style(ui.WARN, loud=True))
            self.toggleBtn.setText('Close door')
            self.toggleBtn.setStyleSheet(ui.outline_button_style(ui.ACCENT))
            self.timerLabel.setText('open for 0 s')
        else:
            self.stateLabel.setText('Door closed')
            self.stateLabel.setStyleSheet(ui.state_plate_style(ui.OK))
            self.toggleBtn.setText('Open door')
            self.toggleBtn.setStyleSheet(ui.outline_button_style(ui.ACCENT))
            self.timerLabel.setText('closed')
        self.timerLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; '
            'background: transparent; border: none;'
            % (ui.TEXT_MUTED, ui.FONT, ui.SIZE_XS))


if __name__ == '__main__':
    run_panel(DoorSensorPanel, GEOMETRY)
