"""Relay actuator emulator.

The three actuators in this system (compressor, fan, siren) behave identically:
they subscribe to a command topic, switch state on ON/OFF, and report back on a
status topic so the rest of the system sees what the hardware actually did.
Only the name, the topics and the colour differ, so the behaviour lives here and
each actuator file is a thin entry point.
"""

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from emulators import ui_common as ui
from emulators.ui_common import EmulatorPanel, run_panel


class RelayPanel(EmulatorPanel):

    def __init__(self, role, name, icon, cmd_topic, sts_topic, on_color):
        super().__init__(
            role=role,
            title='%s  %s' % (icon, name),
            subtitle='Relay actuator - driven by the data manager',
            topic_note='sub: %s\npub: %s' % (cmd_topic, sts_topic),
        )
        self.setMinimumWidth(280)

        self.name = name
        self.cmd_topic = cmd_topic
        self.sts_topic = sts_topic
        self.on_color = on_color
        self.state = 'OFF'
        self.switch_count = 0

        panel = ui.make_subpanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.stateLabel = QLabel()
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self._paint_state()

        self.lastCmdLabel = ui.label('waiting for first command...', size=11,
                                     color=ui.TEXT_DIM, align=Qt.AlignCenter)

        counters = QHBoxLayout()
        self.switchCountLabel = ui.label('switch cycles: 0', size=11, color=ui.TEXT_DIM)
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
            'border-radius: 10px; font-family: %s; font-size: 20px; '
            'font-weight: bold; padding: 16px 8px;'
            % ('#0B1220' if is_on else ui.TEXT_DIM,
               color if is_on else 'transparent',
               color, ui.FONT))

    def on_connected(self):
        # Report the current state so a manager that started later is in sync.
        self.mqtt.publish(self.sts_topic, self.state, retain=True)

    def on_mqtt_message(self, topic, payload):
        if topic != self.cmd_topic:
            return
        command = payload.strip().upper()
        if command not in ('ON', 'OFF'):
            print('[%s] ignoring unknown command: %r' % (self.role, payload))
            return

        self.lastCmdLabel.setText('last command: %s at %s'
                                  % (command, datetime.now().strftime('%H:%M:%S')))

        if command == self.state:
            return  # already in that state, nothing to switch

        self.state = command
        self.switch_count += 1
        self.switchCountLabel.setText('switch cycles: %d' % self.switch_count)
        self._paint_state()
        self.mqtt.publish(self.sts_topic, self.state, retain=True)
        print('[%s] %s -> %s' % (self.role, self.name, self.state))


def run_relay(role, name, icon, cmd_topic, sts_topic, on_color, geometry):
    """Entry point for the single-relay emulator scripts."""
    run_panel(lambda: RelayPanel(role, name, icon, cmd_topic, sts_topic, on_color),
              geometry)
