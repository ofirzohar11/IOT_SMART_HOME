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

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from config import settings as thresholds
from config.mqtt_client import QOS_COMMAND, MqttClient, parse_json
from database import db
from gui import glossary
from gui.pages.dashboard import DashboardPage
from gui.pages.devices import DevicesPage
from gui.pages.history import HistoryPage
from gui.pages.incidents import IncidentsPage
from gui.pages.settings import SettingsPage
from gui.pages.simulations import SimulationsPage
from ui import help as h
from ui import icons
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
    ('Dashboard', 'gauge', DashboardPage,
     'Is the fridge safe right now? Live temperature, equipment and anything '
     'that needs attention.'),
    ('Devices', 'devices', DevicesPage,
     'Every sensor and switch in the unit: what it is for, and whether it is '
     'still reporting.'),
    ('Incidents', 'flag', IncidentsPage,
     'Problems the system has opened a case for, each with what to do about '
     'it.'),
    ('Simulations', 'flask', SimulationsPage,
     'Break something on purpose to prove the alarms really work. Everything '
     'it causes is labelled SIMULATED.'),
    ('History', 'table', HistoryPage,
     'The stored record: every reading and every alert, ready to export.'),
    ('Settings', 'gear', SettingsPage,
     'The limits every alarm is measured against: what each one is, what it '
     'is recommended to be, and what happens when it is crossed.'),
]


class NavButton(QPushButton):
    """One destination in the rail: a drawn icon, then the word.

    The icon is painted rather than typed. The characters previously used here
    were absent from the UI font on every platform, so each one arrived from a
    different fallback and the six of them were six different sizes.
    """

    def __init__(self, text, icon_name):
        super().__init__('    ' + text)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setIconSize(QSize(17, 17))
        # The selected destination is carried by a wash of the accent rather
        # than by tinting the word blue. Colouring the label made the current
        # page the only *link*-coloured thing in the rail, which read as the
        # one item you had not visited yet.
        self.setStyleSheet('''
            QPushButton {
                background-color: transparent; color: %s;
                border: none; border-radius: %dpx;
                font-family: "%s"; font-size: %dpx; font-weight: %d;
                text-align: left; padding-left: 11px;
            }
            QPushButton:hover { background-color: %s; color: %s; }
            QPushButton:checked { background-color: %s; color: %s;
                                  font-weight: %d; }
            QPushButton:focus { border: 2px solid %s; padding-left: 9px; }
        ''' % (t.TEXT_DIM, t.RADIUS_SM, t.FONT, t.SIZE_BASE, t.W_MEDIUM,
               t.PANEL_HOVER, t.TEXT,
               t.wash(t.ACCENT, 0.14, t.SURFACE), t.TEXT, t.W_SEMIBOLD,
               t.FOCUS_RING))
        self._repaint_icon()
        self.toggled.connect(lambda _c: self._repaint_icon())

    def _repaint_icon(self):
        self.setIcon(icons.icon(self.icon_name, 17,
                                t.ACCENT if self.isChecked() else t.TEXT_DIM))


class MainWindow(QWidget):
    """Kept as a plain widget so the toast overlay can sit on top of it."""

    status_received = pyqtSignal(object)
    alert_received = pyqtSignal(object)
    device_status = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cold Chain Monitor - Pharmaceutical Storage Unit 1')
        # 1280x780 is what the dashboard actually needs: the navigation rail,
        # five system-health tiles, two gauges beside a status column and a row
        # of five readings whose values are never allowed to lose a character.
        # It was 1180x760, which is narrower than the layout has ever fitted
        # into - the page answered by growing a horizontal scrollbar and
        # clipping the right-hand column off the screen.
        self.setMinimumSize(1280, 780)
        self.resize(1520, 940)
        self.setStyleSheet('background-color: %s;' % t.BG)

        self.operator = cfg.DEFAULT_OPERATOR
        self.mode = 'MONITORING'
        self._last_status = 0.0
        self._last_snapshot = {}
        self._last_alert_toast = 0.0
        self._suppressed_alerts = 0
        self._settings_announced = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_nav())

        right = QWidget()
        right.setStyleSheet('background: transparent;')
        rightLayout = QVBoxLayout(right)
        rightLayout.setContentsMargins(t.SPACE_LG, t.SPACE_MD, t.SPACE_LG,
                                      t.SPACE)
        rightLayout.setSpacing(t.SPACE)
        rightLayout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.pages = []
        for index, (title, _icon, page_class, _tip) in enumerate(NAV_ITEMS):
            page = page_class(self)
            self.pages.append(page)
            self.stack.addWidget(page)
        rightLayout.addWidget(self.stack, stretch=1)
        rightLayout.addWidget(self._build_footer())
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
        rail.setFixedWidth(216)
        rail.setStyleSheet('QFrame { background-color: %s; border: none; '
                           'border-right: 1px solid %s; }' % (t.SURFACE, t.BORDER))

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(t.SPACE, t.SPACE_LG, t.SPACE, t.SPACE_MD)
        layout.setSpacing(2)

        brand = QVBoxLayout()
        brand.setSpacing(2)
        brand.setContentsMargins(t.SPACE_XS, 0, 0, 0)
        markRow = QHBoxLayout()
        markRow.setContentsMargins(0, 0, 0, 0)
        markRow.setSpacing(9)
        markRow.addWidget(icons.Icon('fridge', 20, t.ACCENT, width=1.7),
                          alignment=Qt.AlignVCenter)
        # A product name is a name, not a caption: set in the interface face at
        # heading size, in sentence case. The spaced capitals it used to carry
        # made the wordmark read as a section label for the rail below it.
        markRow.addWidget(t.label('Cold Chain', size=t.SIZE_MD,
                                  weight=t.W_BOLD, spacing=-0.2))
        markRow.addStretch()
        brand.addLayout(markRow)
        brand.addWidget(t.label('Pharmaceutical Storage Unit 1',
                                size=t.SIZE_XS, color=t.TEXT_MUTED))
        layout.addLayout(brand)
        layout.addSpacing(t.SPACE_LG)

        self.navGroup = QButtonGroup(self)
        self.navGroup.setExclusive(True)
        for index, (title, icon_name, _cls, tip) in enumerate(NAV_ITEMS):
            button = NavButton(title, icon_name)
            h.set_help(button, title, tip)
            button.clicked.connect(lambda _c, i=index: self._select(i))
            self.navGroup.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch()

        # A persistent count of what is open, wherever the operator is.
        self.navAlertPill = w.Pill('No active alerts', t.OK, filled=False,
                                   mark='mark_normal', size=t.SIZE_CAPTION)
        h.set_help(self.navAlertPill, 'Open conditions',
                   'How many critical problems and warnings are active right '
                   'now, wherever you are in the console.',
                   'It follows you from page to page, so a problem raised '
                   'while you are reading the history is not missed.',
                   'No active alerts.')
        layout.addWidget(self.navAlertPill)
        layout.addSpacing(t.SPACE_SM)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet('background-color: %s; border: none;' % t.BORDER)
        layout.addWidget(divider)
        layout.addSpacing(t.SPACE_SM)

        brokerLabel = t.label('Broker\n%s:%s' % (cfg.BROKER_HOST, cfg.BROKER_PORT),
                              size=t.SIZE_XS, color=t.TEXT_MUTED)
        h.set_help(brokerLabel, 'Message broker',
                   'The server every device and this console connect to in '
                   'order to exchange messages.',
                   'Nothing on this screen updates without it. If the '
                   'connection indicator turns red, this is what it lost.')
        layout.addWidget(brokerLabel)
        return rail

    def _build_footer(self):
        """A quiet strip identifying the unit and the author of the console."""
        bar = QFrame()
        bar.setFixedHeight(26)
        bar.setStyleSheet('QFrame { background: transparent; border: none; '
                          'border-top: 1px solid %s; }' % t.BORDER)
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 5, 2, 0)
        row.setSpacing(t.SPACE_SM)
        row.addWidget(t.label('Cold Chain Monitor  ·  Pharmaceutical Storage '
                              'Unit 1', size=t.SIZE_XS, color=t.TEXT_MUTED))
        row.addStretch()
        credit = t.label('Created by Ofir Zohar', size=t.SIZE_XS,
                         color=t.TEXT_MUTED)
        row.addWidget(credit)
        return bar

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName('panel')
        bar.setStyleSheet(t.panel_style())
        bar.setFixedHeight(62)

        row = QHBoxLayout(bar)
        row.setContentsMargins(t.SPACE_MD + 2, 10, t.SPACE, 10)
        row.setSpacing(t.SPACE_MD)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.pageTitle = t.label('Dashboard', size=t.SIZE_LG, weight=t.W_BOLD,
                                 spacing=-0.2)
        self.pageSubtitle = t.label('', size=t.SIZE_XS, color=t.TEXT_MUTED)
        titles.addWidget(self.pageTitle)
        titles.addWidget(self.pageSubtitle)
        row.addLayout(titles)
        row.addStretch()

        self.simPill = w.Pill('', t.SIM, filled=False, size=11)
        glossary.term('simulated').apply(
            self.simPill, 'Simulated faults are armed',
            note='Clear them from the Simulations page when the drill is over.')
        self.simPill.hide()
        row.addWidget(self.simPill)

        self.linkPill = w.Pill('Connecting', t.OFF, filled=False, size=11)
        glossary.term('connection').apply(self.linkPill)
        row.addWidget(self.linkPill)

        self.modeButton = QPushButton('Enter maintenance')
        self.modeButton.setStyleSheet(t.outline_button_style(t.TEXT_DIM))
        glossary.term('maintenance').apply(self.modeButton)
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
    def toast(self, text, color=t.ACCENT, mark='check'):
        self.toasts.show_toast(text, color, mark)

    def set_fault(self, device_id, fault_id, active):
        self.mqtt.publish_json(cfg.TOPIC_SIM_CMD, {
            'action': 'set', 'device': device_id, 'fault': fault_id,
            'active': bool(active), 'operator': self.operator,
        }, qos=QOS_COMMAND)

    def clear_all_faults(self):
        self.mqtt.publish_json(cfg.TOPIC_SIM_CMD,
                               {'action': 'clear_all', 'device': '*'},
                               qos=QOS_COMMAND)

    def publish_settings(self, values):
        """Send the thresholds to every other process, and keep them there.

        Retained, so a data manager or a device started later is configured the
        moment it connects instead of running on the values it booted with.
        """
        self.mqtt.publish_json(cfg.TOPIC_SETTINGS, {
            'values': values, 'operator': self.operator,
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, retain=True, qos=QOS_COMMAND)

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
            self.simPill.set('%d simulated faults' % armed, t.SIM, 'mark_simulated')
            self.simPill.show()
        else:
            self.simPill.hide()

        counts = data.get('alert_counts') or {}
        criticals = counts.get(cfg.LEVEL_CRITICAL, 0)
        warnings = counts.get(cfg.LEVEL_WARNING, 0)
        if criticals:
            self.navAlertPill.set('%d critical · %d warning%s'
                                  % (criticals, warnings,
                                     '' if warnings == 1 else 's'),
                                  t.CRITICAL, 'mark_critical')
        elif warnings:
            self.navAlertPill.set('%d warning%s'
                                  % (warnings, '' if warnings == 1 else 's'),
                                  t.WARN, 'mark_warning')
        else:
            self.navAlertPill.set('No active alerts', t.OK, 'mark_normal')

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
            self.toast(message, t.CRITICAL, 'mark_critical')
        else:
            self.toast(message, t.WARN, 'mark_warning')

    def _apply_device_status(self, device_id, state):
        for page in self.pages:
            try:
                page.apply_device_status(device_id, state)
            except Exception:
                pass

    def _apply_connection(self, connected):
        self.linkPill.set('Connected' if connected else 'Disconnected',
                          t.OK if connected else t.CRITICAL,
                          'mark_normal' if connected else 'mark_critical',
                          filled=not connected)
        if not connected:
            self.toast('Lost connection to the broker', t.CRITICAL, 'mark_critical')
            return
        if not self._settings_announced:
            # The saved thresholds live in a file only this process reads, so
            # the first thing the console does on connecting is tell everybody
            # else what they are. Doing it once, on the first connect, leaves a
            # later edit as the only thing that can change them.
            self._settings_announced = True
            self.publish_settings(thresholds.effective(cfg))

    def _tick(self):
        # The console must not present a stale snapshot as if it were current.
        if self._last_status and time.time() - self._last_status > STATUS_STALE_SECONDS:
            self.linkPill.set('No data', t.WARN, 'mark_warning', filled=True)
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
    # Explanations are part of this interface, so they are styled like the rest
    # of it rather than left as the platform's yellow rectangle.
    t.apply_tooltip_style(app)

    def handle_exception(kind, value, tb):
        """Never let one widget bug close the console silently."""
        print(''.join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = handle_exception

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
