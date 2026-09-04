"""Shared structure for the emulated devices.

Each device is written once as an **EmulatorPanel** - a self-contained card that
owns its own MQTT connection. A panel can then be shown two ways:

* wrapped in an ``EmulatorWindow``, one process per device, which is how
  ``start_all.sh`` runs them and how real hardware behaves;
* placed side by side in ``device_panel.py``, one window holding every device,
  which is far easier to demonstrate and record.

Both modes run identical code and open identical MQTT connections. Only the
window chrome differs.

MQTT callbacks arrive on the paho network thread, so a panel forwards them
through Qt signals before touching any widget.
"""

import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QVBoxLayout, QWidget)

from config.mqtt_client import MqttClient
# The palette and the small style helpers are shared with the main GUI.
from ui.theme import (ACCENT, ALARM, BG, BORDER, FONT, OFF, OK, PANEL,
                      PANEL_ALT, TEXT, TEXT_DIM, WARN, button_style, label,
                      make_panel, make_subpanel, outline_button_style,
                      panel_style)


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
    """One emulated device: header, body, topic footer, and its own MQTT client.

    Subclasses fill ``self.body`` and override ``on_mqtt_message`` if they
    subscribe to anything, and ``on_connected`` to publish an initial state.
    """

    message_received = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, role, title, subtitle, topic_note):
        super().__init__()
        self.role = role
        self.window_title = title

        self.setObjectName('devicePanel')
        self.setStyleSheet('QFrame#devicePanel { background-color: %s; '
                           'border: 1px solid %s; border-radius: 12px; }'
                           % (PANEL, BORDER))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label(title, size=14, bold=True))
        titles.addWidget(label(subtitle, size=10, color=TEXT_DIM))
        header.addLayout(titles)
        header.addStretch()
        self.led = ConnectionLed()
        header.addWidget(self.led, alignment=Qt.AlignTop)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)

        footer = label(topic_note, size=9, color=TEXT_DIM)
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

    # -- lifecycle ---------------------------------------------------------
    def start_mqtt(self):
        self.mqtt.start()

    def shutdown(self):
        self.mqtt.stop()

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
    panel = panel_factory()
    window = EmulatorWindow(panel, geometry)
    window.show()
    sys.exit(app.exec_())
