"""Relay actuator emulator.

The three actuators in this system (compressor, fan, siren) behave identically:
they subscribe to a command topic, switch state on ON/OFF, and report back on a
status topic so the rest of the system sees what the hardware actually did. Only
the name, the topics and the colour differ, so the behaviour lives here and each
actuator file is a thin entry point.

Their faults are the ways a contactor fails: ignoring commands entirely, or
welding into one position and reporting that position forever. Note that a
faulty relay still reports a *plausible* state - which is exactly why the
current clamp and the tachometer exist.
"""

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel


class RelayPanel(EmulatorPanel):

    def __init__(self, device_id, on_color):
        super().__init__(device_id)
        self.setMinimumWidth(280)

        self.on_color = on_color
        self.name = self.device.label.replace(' Relay', '')
        self.cmd_topic = self.device.cmd_topic
        self.sts_topic = self.device.sts_topic
        self.state = 'OFF'
        self.switch_count = 0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)

        self.stateLabel = QLabel()
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self._paint_state()
        self.lastCmdLabel = ui.label('waiting for first command...', size=11,
                                     color=ui.TEXT_DIM, align=Qt.AlignCenter)

        counters = QHBoxLayout()
        self.switchCountLabel = ui.label('switch cycles: 0', size=11,
                                         color=ui.TEXT_DIM)
        counters.addWidget(self.switchCountLabel)
        counters.addStretch()

        layout.addWidget(self.stateLabel)
        layout.addWidget(self.lastCmdLabel)
        layout.addLayout(counters)
        self.body.addWidget(panel)

        self.mqtt.subscribe(self.cmd_topic)
        self.start_mqtt()

    def _paint_state(self):
        is_on = self.state == 'ON'
        color = self.on_color if is_on else ui.OFF
        self.stateLabel.setText(self.name.upper() + ':  ' + self.state)
        self.stateLabel.setStyleSheet(
            'color: %s; background-color: %s; border: 2px solid %s; '
            'border-radius: 10px; font-family: %s; font-size: 19px; '
            'font-weight: bold; padding: 15px 8px;'
            % ('#0B1220' if is_on else ui.TEXT_DIM,
               color if is_on else 'transparent', color, ui.FONT))

    def on_connected(self):
        # Report the current state so a manager that started later is in sync.
        self._report()

    def on_fault_changed(self, fault_id, active):
        if not active:
            return
        if fault_id == 'relay_stuck_on':
            self._force('ON')
        elif fault_id == 'relay_stuck_off':
            self._force('OFF')

    def _force(self, state):
        self.state = state
        self._paint_state()
        self._report()

    def on_mqtt_message(self, topic, payload):
        if topic != self.cmd_topic:
            return
        command = payload.strip().upper()
        if command not in ('ON', 'OFF'):
            print('[%s] ignoring unknown command: %r' % (self.role, payload))
            return

        self.lastCmdLabel.setText('last command: %s at %s'
                                  % (command, datetime.now().strftime('%H:%M:%S')))

        # A welded or dead contactor keeps reporting its own state. It is still
        # a plausible answer, which is why an independent measurement matters.
        if self.has_fault('relay_ignore'):
            self._report()
            return
        if self.has_fault('relay_stuck_on'):
            self._force('ON')
            return
        if self.has_fault('relay_stuck_off'):
            self._force('OFF')
            return

        if command == self.state:
            return
        self.state = command
        self.switch_count += 1
        self.switchCountLabel.setText('switch cycles: %d' % self.switch_count)
        self._paint_state()
        self._report()

    def _report(self):
        if self.mqtt.suspended or self.has_fault('telemetry_stop'):
            return
        self.mqtt.publish(self.sts_topic, self.state, retain=True, qos=1)


def run_relay(device_id, on_color, geometry):
    """Entry point for the single-relay emulator scripts."""
    run_panel(lambda: RelayPanel(device_id, on_color), geometry)
