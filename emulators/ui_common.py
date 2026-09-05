"""Shared structure for the emulated devices.

Each device is written once as an **EmulatorPanel** - a self-contained card that
owns its own MQTT connection. A panel can then be shown two ways: wrapped in its
own window, one process per device, or side by side in ``device_panel.py``.
Both modes run identical code and open identical connections.

Fault injection lives here rather than in each device. Every panel listens on
the simulation command topic, keeps the set of faults it currently has armed,
reports that set back to the broker, and shows a banner so nobody mistakes an
injected failure for a real one. Three faults are implemented for every device
in this base class - a dropped link, silence, and delayed publishing - and each
subclass adds the failures peculiar to its own hardware by overriding
``on_fault_changed``.

MQTT callbacks arrive on the paho network thread, so a panel forwards them
through Qt signals before touching any widget.
"""

import sys
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from config.mqtt_client import MqttClient, parse_json
from ui import help as h
from ui.theme import (ALARM, BG, BORDER, FONT, OK, PANEL, TEXT_DIM, WARN,
                      apply_tooltip_style, label)

TELEMETRY_DELAY_FACTOR = 4     # publish one sample in four when delayed


class ConnectionLed(QLabel):
    """Small coloured dot plus text showing the MQTT connection state."""

    def __init__(self):
        super().__init__()
        self.set_state(False)

    def set_state(self, connected):
        color = OK if connected else ALARM
        text = 'CONNECTED' if connected else 'OFFLINE'
        self.setText('●  ' + text)
        self.setStyleSheet('color: %s; font-family: %s; font-size: 11px; '
                           'font-weight: bold; background: transparent; border: none;'
                           % (color, FONT))


class EmulatorPanel(QFrame):
    """One emulated device: header, body, fault banner, and its own MQTT client.

    Subclasses fill ``self.body``, override ``on_mqtt_message`` if they subscribe
    to anything, ``on_connected`` to publish an initial state, and
    ``on_fault_changed`` to honour their device-specific failures.
    """

    message_received = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, device_id):
        super().__init__()
        self.device = registry.get(device_id)
        if self.device is None:
            raise ValueError('unknown device id: %r' % device_id)
        self.role = device_id
        self.window_title = '%s  %s' % (self.device.icon, self.device.label)

        self.faults = set()
        self._delay_tick = 0
        self._outage_until = None

        self.setObjectName('devicePanel')
        self._paint_border(BORDER)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titleLabel = label(self.window_title, size=14, bold=True)
        # This window is the simulated hardware, not the console, so the
        # engineering name stays on it - the explanation goes in the tooltip.
        h.set_help(titleLabel, self.device.label, self.device.describes,
                   'This window stands in for one physical device. It holds its '
                   'own connection to the broker and publishes on its own '
                   'schedule, exactly as the real hardware would.',
                   note='%d faults can be armed on it, from here or from the '
                        'console.' % len(self.device.faults))
        titles.addWidget(titleLabel)
        titles.addWidget(label(self.device.describes, size=10, color=TEXT_DIM))
        header.addLayout(titles)
        header.addStretch()
        self.led = ConnectionLed()
        header.addWidget(self.led, alignment=Qt.AlignTop)

        self.faultBanner = QLabel()
        self.faultBanner.setWordWrap(True)
        self.faultBanner.hide()

        self.body = QVBoxLayout()
        self.body.setSpacing(10)

        footer = label(self._topic_note(), size=9, color=TEXT_DIM)
        footer.setWordWrap(True)

        root.addLayout(header)
        root.addWidget(self.faultBanner)
        root.addLayout(self.body)
        root.addStretch()
        root.addWidget(footer)

        self.message_received.connect(self.on_mqtt_message_safe)
        self.connection_changed.connect(self._on_connection_changed)

        self.mqtt = MqttClient(
            device_id,
            on_connect=lambda: self.connection_changed.emit(True),
            on_disconnect=lambda: self.connection_changed.emit(False),
            on_message=lambda topic, payload: self.message_received.emit(topic, payload),
        )
        self.mqtt.subscribe(cfg.TOPIC_SIM_CMD)

        # Drives the simulated-outage countdown and any subclass housekeeping.
        self._housekeeping = QTimer(self)
        self._housekeeping.timeout.connect(self._tick_housekeeping)
        self._housekeeping.start(1000)

    # -- description -------------------------------------------------------
    def _topic_note(self):
        parts = []
        if self.device.telemetry_topic:
            parts.append('pub: %s' % self.device.telemetry_topic)
        if self.device.sts_topic:
            parts.append('pub: %s' % self.device.sts_topic)
        if self.device.cmd_topic:
            parts.append('sub: %s' % self.device.cmd_topic)
        return '\n'.join(parts)

    def _paint_border(self, color):
        self.setStyleSheet('QFrame#devicePanel { background-color: %s; '
                           'border: 1px solid %s; border-radius: 12px; }'
                           % (PANEL, color))

    # -- lifecycle ---------------------------------------------------------
    def start_mqtt(self):
        self.mqtt.start()

    def shutdown(self):
        self._housekeeping.stop()
        self.mqtt.stop()

    # -- overridable hooks -------------------------------------------------
    def on_mqtt_message(self, topic, payload):
        pass

    def on_connected(self):
        """Called on the Qt thread once the broker connection is up."""
        pass

    def on_fault_changed(self, fault_id, active):
        """Apply a device-specific fault. Base faults are handled for you."""
        pass

    def housekeeping(self):
        """Called once a second on the Qt thread."""
        pass

    # -- MQTT plumbing -----------------------------------------------------
    def on_mqtt_message_safe(self, topic, payload):
        try:
            if topic == cfg.TOPIC_SIM_CMD:
                self._apply_sim_command(payload)
            else:
                self.on_mqtt_message(topic, payload)
        except Exception as error:
            print('[%s] error handling %s: %s' % (self.role, topic, error))

    def _on_connection_changed(self, connected):
        self.led.set_state(connected)
        if connected:
            self._publish_faults()
            try:
                self.on_connected()
            except Exception as error:
                print('[%s] on_connected failed: %s' % (self.role, error))

    # -- telemetry gating --------------------------------------------------
    def telemetry_allowed(self):
        """Whether this tick may publish, given the connectivity faults armed."""
        if self.mqtt.suspended or 'telemetry_stop' in self.faults:
            return False
        if 'telemetry_delay' in self.faults:
            self._delay_tick += 1
            return self._delay_tick % TELEMETRY_DELAY_FACTOR == 0
        return True

    def has_fault(self, fault_id):
        return fault_id in self.faults

    # -- simulation --------------------------------------------------------
    def _apply_sim_command(self, payload):
        data = parse_json(payload, {})
        action = str(data.get('action', 'set')).lower()
        target = data.get('device', '*')
        if target not in ('*', self.role):
            return

        if action == 'clear_all':
            for fault_id in sorted(self.faults):
                self._set_fault(fault_id, False)
            self._publish_faults()
            return

        fault_id = data.get('fault')
        if not fault_id or self.device.fault(fault_id) is None:
            return
        self._set_fault(fault_id, bool(data.get('active', True)))
        self._publish_faults()

    def _set_fault(self, fault_id, active):
        if active == (fault_id in self.faults):
            return
        if active:
            self.faults.add(fault_id)
        else:
            self.faults.discard(fault_id)
        print('[%s] simulation %s %s' % (self.role, fault_id,
                                         'ARMED' if active else 'cleared'))

        if fault_id == 'mqtt_disconnect':
            self._apply_link_outage(active)
        else:
            try:
                self.on_fault_changed(fault_id, active)
            except Exception as error:
                print('[%s] fault %s failed: %s' % (self.role, fault_id, error))
        self._paint_fault_banner()

    def _apply_link_outage(self, active):
        if active:
            # Publish the armed state before pulling the link down, otherwise
            # nobody would ever learn this device is off the air on purpose.
            self._publish_faults()
            self._outage_until = time.time() + cfg.SIM_OUTAGE_SECONDS
            self.mqtt.suspend()
        else:
            self._outage_until = None
            self.mqtt.restore()

    def _tick_housekeeping(self):
        if self._outage_until is not None and time.time() >= self._outage_until:
            # A device with its link cut cannot hear the command to restore it,
            # so a simulated outage heals itself the way a real one does.
            self._set_fault('mqtt_disconnect', False)
            self._publish_faults()
        elif self._outage_until is not None:
            self._paint_fault_banner()
        try:
            self.housekeeping()
        except Exception as error:
            print('[%s] housekeeping failed: %s' % (self.role, error))

    def _publish_faults(self):
        self.mqtt.publish_json(cfg.sim_status_topic(self.role),
                               {'device': self.role, 'faults': sorted(self.faults)},
                               retain=True, qos=1)

    def _paint_fault_banner(self):
        if not self.faults:
            self.faultBanner.hide()
            self._paint_border(BORDER)
            return

        labels = []
        for fault_id in sorted(self.faults):
            fault = self.device.fault(fault_id)
            labels.append(fault.label if fault else fault_id)
        text = 'SIMULATED FAULT  ·  ' + '  ·  '.join(labels)
        if self._outage_until is not None:
            remaining = max(0, int(self._outage_until - time.time()))
            text += '  ·  link returns in %d s' % remaining

        self.faultBanner.setText(text)
        self.faultBanner.setStyleSheet(
            'color: #0B1220; background-color: %s; border: none; '
            'border-radius: 7px; font-family: %s; font-size: 10px; '
            'font-weight: bold; padding: 5px 9px;' % (WARN, FONT))
        self.faultBanner.show()
        self._paint_border(WARN)


class EmulatorWindow(QMainWindow):
    """Standalone window holding a single device panel, one process per device."""

    def __init__(self, panel, geometry):
        super().__init__()
        self.panel = panel
        self.setWindowTitle(panel.window_title)
        self.setGeometry(*geometry)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % BG)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(panel)
        self.setCentralWidget(container)

    def closeEvent(self, event):
        self.panel.shutdown()
        super().closeEvent(event)


def run_panel(panel_factory, geometry):
    """Entry point used by every single-device emulator script."""
    app = QApplication(sys.argv)
    apply_tooltip_style(app)
    panel = panel_factory()
    window = EmulatorWindow(panel, geometry)
    window.show()
    sys.exit(app.exec_())
