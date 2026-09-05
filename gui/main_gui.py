"""Cold Chain Monitor - operator console.

The shell: a navigation rail, a status bar, and five pages that receive live
state pushed in from MQTT. Everything the console sends - a mode change, a fault
injection, an incident acknowledgement - goes out as a message and comes back as
observed state, so the screen always shows what the system actually did rather
than what the button assumed.

Threading: paho delivers on its own network thread and Qt widgets may only be
touched from the main thread, so every inbound message is converted to a Qt
signal before anything is drawn.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import time
import traceback

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from config.mqtt_client import QOS_COMMAND, MqttClient, parse_json
from database import db
from gui.pages.dashboard import DashboardPage
from gui.pages.devices import DevicesPage
from gui.pages.history import HistoryPage
from gui.pages.incidents import IncidentsPage
from gui.pages.simulations import SimulationsPage
from ui import theme as t
from ui import widgets as w

# If the manager stops publishing, the console must say so rather than leaving
# the last snapshot on screen looking current.
STATUS_STALE_SECONDS = 8

# A cascading failure raises several alerts within the same second. Popping a
# toast for each one buries the screen in exactly the moment the operator needs
# to read it, so they are throttled and the rest are summarised.
ALERT_TOAST_INTERVAL_S = 3.5

NAV_ITEMS = [
    ('Dashboard', '◈', DashboardPage),
    ('Devices', '◉', DevicesPage),
    ('Incidents', '⚑', IncidentsPage),
    ('Simulations', '⚗', SimulationsPage),
    ('History', '▤', HistoryPage),
]


class NavButton(QPushButton):

    def __init__(self, text, glyph):
        super().__init__('   %s    %s' % (glyph, text))
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setStyleSheet('''
            QPushButton {
                background-color: transparent; color: %s; border: none;
                border-radius: %dpx; font-family: %s; font-size: 13px;
                font-weight: 600; text-align: left; padding-left: 6px;
            }
            QPushButton:hover { background-color: %s; color: %s; }
            QPushButton:checked { background-color: %s; color: %s; }
        ''' % (t.TEXT_DIM, t.RADIUS, t.FONT, t.PANEL_HOVER, t.TEXT,
               t.PANEL_ALT, t.ACCENT))


class MainWindow(QWidget):
    """Kept as a plain widget so the toast overlay can sit on top of it."""

    status_received = pyqtSignal(object)
    alert_received = pyqtSignal(object)
    device_status = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cold Chain Monitor - Pharmaceutical Storage Unit 1')
        self.setMinimumSize(1180, 760)
        self.resize(1520, 940)
        self.setStyleSheet('background-color: %s;' % t.BG)

        self.operator = cfg.DEFAULT_OPERATOR
        self.mode = 'MONITORING'
        self._last_status = 0.0
        self._last_snapshot = {}
        self._last_alert_toast = 0.0
        self._suppressed_alerts = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_nav())

        right = QWidget()
        right.setStyleSheet('background: transparent;')
        rightLayout = QVBoxLayout(right)
        rightLayout.setContentsMargins(16, 14, 16, 14)
        rightLayout.setSpacing(12)
        rightLayout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.pages = []
        for index, (title, glyph, page_class) in enumerate(NAV_ITEMS):
            page = page_class(self)
            self.pages.append(page)
            self.stack.addWidget(page)
        rightLayout.addWidget(self.stack, stretch=1)
        root.addWidget(right, stretch=1)

        self.toasts = w.ToastHost(self)

        # Signals are connected before MQTT starts so no early message is lost.
        self.status_received.connect(self._apply_status)
        self.alert_received.connect(self._apply_alert)
        self.device_status.connect(self._apply_device_status)
        self.connection_changed.connect(self._apply_connection)

        self.mqtt = MqttClient(
            'gui',
            on_connect=lambda: self.connection_changed.emit(True),
            on_disconnect=lambda: self.connection_changed.emit(False),
            on_message=self._on_message)
        self.mqtt.subscribe(cfg.TOPIC_STATUS, cfg.TOPIC_ALERT,
                            cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_FAN_STS,
                            cfg.TOPIC_SIREN_STS)
        QTimer.singleShot(200, self.mqtt.start)

        self.heartbeat = QTimer(self)
        self.heartbeat.timeout.connect(self._tick)
        self.heartbeat.start(1000)

        self._select(0)

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------
    def _build_nav(self):
        rail = QFrame()
        rail.setFixedWidth(210)
        rail.setStyleSheet('QFrame { background-color: %s; border: none; '
                           'border-right: 1px solid %s; }' % (t.SURFACE, t.BORDER))

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        brand = QVBoxLayout()
        brand.setSpacing(1)
        brand.addWidget(t.label('❄  COLD CHAIN', size=15, bold=True, spacing=0.6))
        brand.addWidget(t.label('Storage Unit 1', size=11, color=t.TEXT_MUTED))
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.navGroup = QButtonGroup(self)
        self.navGroup.setExclusive(True)
        for index, (title, glyph, _cls) in enumerate(NAV_ITEMS):
            button = NavButton(title, glyph)
            button.clicked.connect(lambda _c, i=index: self._select(i))
            self.navGroup.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch()
        self.navAlertLabel = t.label('', size=10, color=t.TEXT_MUTED)
        self.navAlertLabel.setWordWrap(True)
        layout.addWidget(self.navAlertLabel)
        layout.addWidget(t.label('broker\n%s:%s' % (cfg.BROKER_HOST, cfg.BROKER_PORT),
                                 size=9, color=t.TEXT_MUTED))
        return rail

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName('panel')
        bar.setStyleSheet(t.panel_style())
        bar.setFixedHeight(62)

        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 10, 16, 10)
        row.setSpacing(14)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.pageTitle = t.label('Dashboard', size=15, bold=True)
        self.pageSubtitle = t.label('', size=11, color=t.TEXT_MUTED)
        titles.addWidget(self.pageTitle)
        titles.addWidget(self.pageSubtitle)
        row.addLayout(titles)
        row.addStretch()

        self.simPill = w.Pill('', t.SIM, filled=False, size=11)
        self.simPill.hide()
        row.addWidget(self.simPill)

        self.linkPill = w.Pill('CONNECTING', t.OFF, filled=False, size=11)
        row.addWidget(self.linkPill)

        self.modeButton = QPushButton('Enter maintenance')
        self.modeButton.setStyleSheet(t.outline_button_style(t.TEXT_DIM))
        self.modeButton.clicked.connect(self._toggle_mode)
        row.addWidget(self.modeButton)
        return bar

    def _select(self, index):
        self.stack.setCurrentIndex(index)
        button = self.navGroup.button(index)
        if button:
            button.setChecked(True)
        page = self.pages[index]
        self.pageTitle.setText(page.title)
        self.pageSubtitle.setText(page.subtitle)
        try:
            page.on_shown()
        except Exception:
            print('page %s failed to refresh:\n%s' % (page.title,
                                                      traceback.format_exc()))
        if self._last_snapshot:
            self._push_status(page, self._last_snapshot)

    # ------------------------------------------------------------------
    # Console API used by the pages
    # ------------------------------------------------------------------
    def toast(self, text, color=t.ACCENT, glyph='✓'):
        self.toasts.show_toast(text, color, glyph)

    def set_fault(self, device_id, fault_id, active):
        self.mqtt.publish_json(cfg.TOPIC_SIM_CMD, {
            'action': 'set', 'device': device_id, 'fault': fault_id,
            'active': bool(active), 'operator': self.operator,
        }, qos=QOS_COMMAND)

    def clear_all_faults(self):
        self.mqtt.publish_json(cfg.TOPIC_SIM_CMD,
                               {'action': 'clear_all', 'device': '*'},
                               qos=QOS_COMMAND)

    def acknowledge_incident(self, incident_id):
        self._incident_command('acknowledge', incident_id)
        self.toast('Incident %d acknowledged' % incident_id)

    def resolve_incident(self, incident_id):
        if not w.confirm(self, 'Resolve incident %d?' % incident_id,
                         'Mark this incident as resolved.',
                         'If the underlying condition is still true the system '
                         'will raise it again within a second.',
                         confirm_text='Resolve'):
            return
        self._incident_command('resolve', incident_id)
        self.toast('Incident %d resolved' % incident_id)

    def _incident_command(self, action, incident_id):
        self.mqtt.publish_json(cfg.TOPIC_INCIDENT_CMD, {
            'action': action, 'id': int(incident_id), 'operator': self.operator,
        }, qos=QOS_COMMAND)
        QTimer.singleShot(400, self._refresh_incident_views)

    def _refresh_incident_views(self):
        for page in self.pages:
            if hasattr(page, 'refresh_incidents'):
                page.refresh_incidents()
            elif isinstance(page, IncidentsPage) and page.isVisible():
                page.refresh()

    def _toggle_mode(self):
        entering = self.mode != 'MAINTENANCE'
        if entering and not w.confirm(
                self, 'Enter maintenance mode?',
                'Conditions will still be evaluated and logged, but the unit '
                'will not escalate to an alarm and the actuators are parked off.',
                'Critical information stays visible. Leave maintenance mode as '
                'soon as servicing is finished.',
                confirm_text='Enter maintenance'):
            return
        mode = 'MAINTENANCE' if entering else 'MONITORING'
        self.mqtt.publish_json(cfg.TOPIC_MODE_CMD,
                               {'mode': mode, 'operator': self.operator},
                               retain=True, qos=QOS_COMMAND)
        self.toast('Maintenance mode %s' % ('requested' if entering else 'ending'),
                   t.ACCENT if entering else t.OK)

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    def _on_message(self, topic, payload):
        """Network thread: forward to the Qt thread, never touch widgets here."""
        if topic == cfg.TOPIC_STATUS:
            data = parse_json(payload)
            if data:
                self.status_received.emit(data)
        elif topic == cfg.TOPIC_ALERT:
            data = parse_json(payload)
            if data:
                self.alert_received.emit(data)
        elif topic == cfg.TOPIC_COMPRESSOR_STS:
            self.device_status.emit('compressor', payload.strip().upper())
        elif topic == cfg.TOPIC_FAN_STS:
            self.device_status.emit('fan', payload.strip().upper())
        elif topic == cfg.TOPIC_SIREN_STS:
            self.device_status.emit('siren', payload.strip().upper())

    # ------------------------------------------------------------------
    # Qt-thread updates
    # ------------------------------------------------------------------
    def _apply_status(self, data):
        self._last_status = time.time()
        self._last_snapshot = data

        mode = data.get('mode', 'MONITORING')
        if mode != self.mode:
            self.mode = mode
            in_maintenance = mode == 'MAINTENANCE'
            self.modeButton.setText('Leave maintenance' if in_maintenance
                                    else 'Enter maintenance')
            self.modeButton.setStyleSheet(t.outline_button_style(
                t.ACCENT if in_maintenance else t.TEXT_DIM))

        faults = data.get('simulated_faults') or {}
        armed = sum(len(v) for v in faults.values())
        if armed:
            self.simPill.set('%d simulated faults' % armed, t.SIM, '⚠')
            self.simPill.show()
        else:
            self.simPill.hide()

        counts = data.get('alert_counts') or {}
        criticals = counts.get(cfg.LEVEL_CRITICAL, 0)
        warnings = counts.get(cfg.LEVEL_WARNING, 0)
        if criticals or warnings:
            self.navAlertLabel.setText('%d critical · %d warnings active'
                                       % (criticals, warnings))
        else:
            self.navAlertLabel.setText('No active alerts')

        for page in self.pages:
            self._push_status(page, data)

    @staticmethod
    def _push_status(page, data):
        try:
            page.apply_status(data)
        except Exception:
            print('page %s failed on status:\n%s'
                  % (page.title, traceback.format_exc()))

    def _apply_alert(self, record):
        level = cfg.normalise_level(record.get('level'))
        for page in self.pages:
            try:
                page.apply_alert(record)
            except Exception:
                print('page %s failed on alert:\n%s'
                      % (page.title, traceback.format_exc()))
        if level not in (cfg.LEVEL_CRITICAL, cfg.LEVEL_WARNING):
            return

        now = time.time()
        if now - self._last_alert_toast < ALERT_TOAST_INTERVAL_S:
            self._suppressed_alerts += 1
            return

        message = record.get('message') or level.title()
        if self._suppressed_alerts:
            message += '   (+%d more)' % self._suppressed_alerts
        self._suppressed_alerts = 0
        self._last_alert_toast = now
        if level == cfg.LEVEL_CRITICAL:
            self.toast(message, t.CRITICAL, '■')
        else:
            self.toast(message, t.WARN, '▲')

    def _apply_device_status(self, device_id, state):
        for page in self.pages:
            try:
                page.apply_device_status(device_id, state)
            except Exception:
                pass

    def _apply_connection(self, connected):
        self.linkPill.set('CONNECTED' if connected else 'DISCONNECTED',
                          t.OK if connected else t.CRITICAL,
                          '●' if connected else '■')
        if not connected:
            self.toast('Lost connection to the broker', t.CRITICAL, '■')

    def _tick(self):
        # The console must not present a stale snapshot as if it were current.
        if self._last_status and time.time() - self._last_status > STATUS_STALE_SECONDS:
            self.linkPill.set('NO DATA', t.WARN, '▲')
        for page in self.pages:
            try:
                page.tick()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toasts.setGeometry(self.rect())
        self.toasts._reflow()

    def closeEvent(self, event):
        self.heartbeat.stop()
        self.mqtt.stop()
        super().closeEvent(event)


def main():
    db.init_db()
    app = QApplication(sys.argv)
    app.setApplicationName('Cold Chain Monitor')

    def handle_exception(kind, value, tb):
        """Never let one widget bug close the console silently."""
        print(''.join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = handle_exception

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
