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
                             QMainWindow, QSizePolicy, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from config import settings as thresholds
from config.mqtt_client import MqttClient, parse_json
from ui import help as h
from ui import icons
from ui import status as stat
from ui import theme as t
# Colours are read as ``t.PANEL`` and never imported by name: a from-import
# binds whichever palette happened to be loaded when this module was first
# imported, and the console can change palette after that.
from ui.theme import apply_tooltip_style, label

TELEMETRY_DELAY_FACTOR = 4     # publish one sample in four when delayed


class ConnectionLed(QFrame):
    """A painted mark plus a word, showing the MQTT connection state.

    This used to be a QLabel printing a bullet character. A bullet is not in
    every UI font, so Qt substituted a different face for that one glyph and it
    arrived at a different size and baseline on each platform - the same reason
    ui.icons exists. It is now the console's own status chip, so an emulator
    and the console say 'connected' in identical terms.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName('led')
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 9, 3)
        row.setSpacing(6)
        self.mark = icons.Icon('mark_normal', t.SIZE_SM, t.OK, width=1.6)
        self.textLabel = QLabel()
        row.addWidget(self.mark, alignment=Qt.AlignVCenter)
        row.addWidget(self.textLabel, alignment=Qt.AlignVCenter)
        self.set_state(False)

    def set_state(self, connected):
        state = stat.NORMAL if connected else stat.OFFLINE
        entry = stat.get(state)
        color = t.OK if connected else t.OFFLINE_FG
        self.mark.set_name(entry.mark)
        self.mark.set_color(color)
        self.textLabel.setText('Connected' if connected else 'Offline')
        self.textLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'background: transparent; border: none;'
            % (color, t.FONT, t.SIZE_XS, t.W_MEDIUM))
        self.setStyleSheet('QFrame#led { background-color: %s; '
                           'border: 1px solid %s; border-radius: %dpx; }'
                           % (t.wash(color, 0.11, t.PANEL),
                              t.mix(color, t.PANEL, 0.40), t.RADIUS_SM))
        self.setToolTip(stat.tooltip(state))


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
        # ``device.icon`` names a drawing rather than holding a character,
        # so the mark is painted into the header beside the title.
        self.window_title = self.device.label

        self.faults = set()
        self._delay_tick = 0
        self._outage_until = None

        self.setObjectName('devicePanel')
        self._paint_border(t.BORDER)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(icons.Icon(self.device.icon, 17, t.TEXT_DIM, width=1.6),
                         alignment=Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titleLabel = t.title(self.window_title, size=t.SIZE_BASE)
        # This window is the simulated hardware, not the console, so the
        # engineering name stays on it - the explanation goes in the tooltip.
        h.set_help(titleLabel, self.device.label, self.device.describes,
                   'This window stands in for one physical device. It holds its '
                   'own connection to the broker and publishes on its own '
                   'schedule, exactly as the real hardware would.',
                   note='%d faults can be armed on it, from here or from the '
                        'console.' % len(self.device.faults))
        titles.addWidget(titleLabel)
        # Wrapped, and given the row's spare width: unwrapped it was cut off
        # mid-word at the edge of every card in the device panel.
        describes = label(self.device.describes, size=t.SIZE_XS,
                          color=t.TEXT_MUTED)
        describes.setWordWrap(True)
        titles.addWidget(describes)
        header.addLayout(titles, stretch=1)
        self.led = ConnectionLed()
        header.addWidget(self.led, alignment=Qt.AlignTop)

        self.faultBanner = QLabel()
        self.faultBanner.setWordWrap(True)
        self.faultBanner.hide()

        self.body = QVBoxLayout()
        self.body.setSpacing(10)

        # The topics this device publishes and listens on. Set in the tabular
        # face because that is what they are - identifiers to be compared
        # character by character, not prose.
        footer = label(self._topic_note(), size=t.SIZE_CAPTION,
                       color=t.TEXT_MUTED, mono=True)
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
        self.mqtt.subscribe(cfg.TOPIC_SIM_CMD, cfg.TOPIC_SETTINGS)

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
                           'border: 1px solid %s; border-radius: %dpx; }'
                           % (t.PANEL, color, t.RADIUS_LG))

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
            elif topic == cfg.TOPIC_SETTINGS:
                self._apply_settings(payload)
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

    # -- configuration -----------------------------------------------------
    def _apply_settings(self, payload):
        """Adopt thresholds edited on the console.

        The emulated hardware uses a handful of them - what a healthy motor
        draws, what speed the fan is rated at, how warm the room settles - and
        every panel reads them at the moment it needs them, so nothing has to
        be restarted for a change to take effect.
        """
        data = parse_json(payload, {})
        proposed = data.get('values')
        if not isinstance(proposed, dict):
            return
        clean, errors = thresholds.validate(proposed)
        for key in errors:
            clean.pop(key, None)
        changed = thresholds.apply_to(cfg, clean)
        if changed:
            print('[%s] %d threshold(s) updated' % (self.role, len(changed)))

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
            self._paint_border(t.BORDER)
            return

        labels = []
        for fault_id in sorted(self.faults):
            fault = self.device.fault(fault_id)
            labels.append(fault.label if fault else fault_id)
        text = 'Simulated fault  ·  ' + '  ·  '.join(labels)
        if self._outage_until is not None:
            remaining = max(0, int(self._outage_until - time.time()))
            text += '  ·  link returns in %d s' % remaining

        # Purple, not amber. An armed drill is not a warning about the stock -
        # the console reserves SIM for exactly this, and painting it amber here
        # made a deliberate test look like a real fault on the one screen where
        # that distinction matters most.
        self.faultBanner.setText(text)
        self.faultBanner.setStyleSheet(
            'color: %s; background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; font-family: "%s"; font-size: %dpx; '
            'font-weight: %d; padding: 6px 10px;'
            % (t.SIM, t.wash(t.SIM, 0.13, t.PANEL), t.mix(t.SIM, t.PANEL, 0.40),
               t.RADIUS_SM, t.FONT, t.SIZE_XS, t.W_SEMIBOLD))
        self.faultBanner.show()
        self._paint_border(t.mix(t.SIM, t.BORDER, 0.55))


class EmulatorWindow(QMainWindow):
    """Standalone window holding a single device panel, one process per device."""

    def __init__(self, panel, geometry):
        super().__init__()
        self.panel = panel
        self.setWindowTitle(panel.window_title)
        self.setGeometry(*geometry)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % t.BG)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(t.SPACE, t.SPACE, t.SPACE, t.SPACE)
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
