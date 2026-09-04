"""Shared look and behaviour for the emulator windows.

Every emulator is its own process with its own MQTT connection, exactly like a
real device would be. What they share is the window chrome and the connection
indicator, which live here so the individual emulators stay short.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QVBoxLayout,
                             QWidget)

from config.mqtt_client import MqttClient
# The palette and the small style helpers are shared with the main GUI.
from ui.theme import (ACCENT, ALARM, BG, BORDER, FONT, OFF, OK, PANEL, TEXT,
                      TEXT_DIM, WARN, button_style, label, make_panel,
                      outline_button_style, panel_style)


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


class EmulatorWindow(QMainWindow):
    """Base window: header with the device name, a body, and a topic footer.

    Subclasses fill ``self.body`` and implement ``on_mqtt_message`` if they
    subscribe to anything. MQTT callbacks arrive on the paho network thread, so
    they are forwarded through ``message_received`` before touching any widget.
    """

    message_received = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, role, title, subtitle, topic_note, geometry):
        super().__init__()
        self.role = role

        self.setWindowTitle(title)
        self.setGeometry(*geometry)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % BG)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label(title, size=15, bold=True))
        titles.addWidget(label(subtitle, size=11, color=TEXT_DIM))
        header.addLayout(titles)
        header.addStretch()
        self.led = ConnectionLed()
        header.addWidget(self.led, alignment=Qt.AlignTop)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)

        footer = label(topic_note, size=10, color=TEXT_DIM)
        footer.setWordWrap(True)

        root.addLayout(header)
        root.addLayout(self.body)
        root.addStretch()
        root.addWidget(footer)

        self.message_received.connect(self.on_mqtt_message)
        self.connection_changed.connect(self._on_connection_changed)

        self.mqtt = MqttClient(
            role,
            on_connect=lambda: self.connection_changed.emit(True),
            on_disconnect=lambda: self.connection_changed.emit(False),
            on_message=lambda topic, payload: self.message_received.emit(topic, payload),
        )

    def start_mqtt(self):
        self.mqtt.start()

    # -- overridable hooks -------------------------------------------------
    def on_mqtt_message(self, topic, payload):
        pass

    def on_connected(self):
        """Called on the Qt thread once the broker connection is up."""
        pass

    # -- internal ----------------------------------------------------------
    def _on_connection_changed(self, connected):
        self.led.set_state(connected)
        if connected:
            self.on_connected()

    def closeEvent(self, event):
        self.mqtt.stop()
        super().closeEvent(event)
