"""Composite widgets specific to this product, shared across the pages."""

from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from database import db
from gui.charts import Sparkline
from ui import theme as t
from ui import widgets as w

MAX_FEED_ITEMS = 150


def humanise_age(seconds):
    """'4 s ago' reads better than a timestamp when the question is freshness."""
    if seconds is None:
        return 'never'
    seconds = int(seconds)
    if seconds < 60:
        return '%d s ago' % seconds
    if seconds < 3600:
        return '%d min ago' % (seconds // 60)
    if seconds < 86400:
        return '%d h ago' % (seconds // 3600)
    return '%d d ago' % (seconds // 86400)


def humanise_duration(seconds):
    if seconds is None:
        return '--'
    seconds = int(seconds)
    if seconds < 60:
        return '%ds' % seconds
    if seconds < 3600:
        return '%dm %02ds' % (seconds // 60, seconds % 60)
    return '%dh %02dm' % (seconds // 3600, (seconds % 3600) // 60)


def duration_between(started, ended):
    fmt = db.TIME_FORMAT
    try:
        start = datetime.strptime(started, fmt)
    except (TypeError, ValueError):
        return None
    try:
        stop = datetime.strptime(ended, fmt) if ended else datetime.now()
    except (TypeError, ValueError):
        stop = datetime.now()
    return max(0, int((stop - start).total_seconds()))


# ===========================================================================
class MetricTile(w.StatTile):
    """A stat tile that also knows how to render a missing or stale value."""

    def __init__(self, caption_text, unit='', fmt='%.1f', **kwargs):
        super().__init__(caption_text, **kwargs)
        self.unit = unit
        self.fmt = fmt

    def set_metric(self, value, color=t.TEXT, suffix=''):
        if value is None:
            self.set_value('--', t.TEXT_MUTED)
            return
        self.set_value((self.fmt % value) + self.unit + suffix, color)


# ===========================================================================
class ActuatorCard(QFrame):
    """An actuator's commanded state beside an independent measurement of it.

    The pill is what the relay reported; the line underneath is what a separate
    sensor measured. When those disagree the card says so - which is the whole
    reason the current clamp and the tachometer exist.
    """

    def __init__(self, device_id, on_color, measured=True):
        super().__init__()
        self.device = registry.get(device_id)
        self.on_color = on_color
        self.setObjectName('panel')
        self.setMinimumHeight(126)
        self._paint_border(t.BORDER)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(t.label(self.device.icon, size=17))
        head.addWidget(t.caption(self.device.label.replace(' Relay', '')))
        head.addStretch()
        self.healthPill = w.HealthPill('OFFLINE')
        head.addWidget(self.healthPill)
        layout.addLayout(head)

        self.stateLabel = QLabel('OFF')
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self.stateLabel.setFixedHeight(30)
        self._paint_state(False)
        layout.addWidget(self.stateLabel)

        self.measuredLabel = None
        if measured:
            self.measuredLabel = t.label('--', size=13, color=t.TEXT_MUTED,
                                         bold=True, mono=True,
                                         align=Qt.AlignCenter)
            layout.addWidget(self.measuredLabel)
            self.captionLabel = t.label('', size=9, color=t.TEXT_MUTED,
                                        align=Qt.AlignCenter)
            layout.addWidget(self.captionLabel)
        layout.addStretch()

    def _paint_border(self, color):
        self.setStyleSheet('QFrame#panel { background-color: %s; border: 1px solid %s; '
                           'border-radius: %dpx; }' % (t.PANEL, color, t.RADIUS_LG))

    def _paint_state(self, is_on):
        color = self.on_color if is_on else t.OFF
        self.stateLabel.setText('ON' if is_on else 'OFF')
        self.stateLabel.setStyleSheet(
            'color: %s; background-color: %s; border: none; border-radius: %dpx; '
            'font-family: %s; font-size: 13px; font-weight: 700;'
            % ('#08111F' if is_on else t.TEXT_DIM, color, t.RADIUS_SM, t.FONT))

    def set_state(self, is_on):
        self._paint_state(is_on)
        self._paint_border(self.on_color if is_on else t.BORDER)

    def set_health(self, health):
        self.healthPill.set_health(health)

    def set_measurement(self, text, color=t.TEXT_MUTED, caption=''):
        if self.measuredLabel is None:
            return
        self.measuredLabel.setText(text)
        self.measuredLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 13px; font-weight: 600; '
            'background: transparent; border: none;' % (color, t.FONT_MONO))
        self.captionLabel.setText(caption)


# ===========================================================================
class DeviceCard(QFrame):
    """A device on the Devices page: identity, health, freshness, last value."""

    def __init__(self, device):
        super().__init__()
        self.device = device
        self.setObjectName('panel')
        self._paint_border(t.BORDER)
        self.setMinimumHeight(158)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(9)
        head.addWidget(t.label(device.icon, size=17))
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(t.label(device.label, size=12, bold=True))
        titles.addWidget(t.label('%s · %s' % (device.kind.title(), device.group),
                                 size=10, color=t.TEXT_MUTED))
        head.addLayout(titles)
        head.addStretch()
        self.healthPill = w.HealthPill('OFFLINE')
        head.addWidget(self.healthPill, alignment=Qt.AlignTop)
        layout.addLayout(head)

        self.valueLabel = t.label('--', size=19, bold=True, mono=True)
        layout.addWidget(self.valueLabel)

        self.spark = Sparkline(t.ACCENT, height=30)
        layout.addWidget(self.spark)

        self.freshnessLabel = t.label('no telemetry yet', size=10,
                                      color=t.TEXT_MUTED)
        layout.addWidget(self.freshnessLabel)

        self.faultLabel = t.label('', size=10, color=t.SIM)
        self.faultLabel.setWordWrap(True)
        self.faultLabel.hide()
        layout.addWidget(self.faultLabel)

        topic = device.telemetry_topic or device.sts_topic or ''
        note = t.label(topic.replace(cfg.TOPIC_ROOT, '…'), size=9,
                       color=t.TEXT_MUTED)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def _paint_border(self, color):
        self.setStyleSheet('QFrame#panel { background-color: %s; border: 1px solid %s; '
                           'border-radius: %dpx; }' % (t.PANEL, color, t.RADIUS_LG))

    def update_state(self, health, value_text, age_seconds, faults):
        self.healthPill.set_health(health)
        self._paint_border(t.health_color(health)
                           if health in ('FAULT', 'DEGRADED') else t.BORDER)
        self.valueLabel.setText(value_text)
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 19px; font-weight: 600; '
            'background: transparent; border: none;'
            % (t.TEXT if health != 'OFFLINE' else t.TEXT_MUTED, t.FONT_MONO))

        if health == 'OFFLINE':
            self.freshnessLabel.setText('offline · last seen %s'
                                        % humanise_age(age_seconds))
            color = t.CRITICAL
        else:
            self.freshnessLabel.setText('updated %s' % humanise_age(age_seconds))
            color = t.TEXT_MUTED
        self.freshnessLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 10px; background: transparent; '
            'border: none;' % (color, t.FONT))

        if faults:
            labels = []
            for fault_id in faults:
                fault = self.device.fault(fault_id)
                labels.append(fault.label if fault else fault_id)
            self.faultLabel.setText('SIMULATED: ' + ', '.join(labels))
            self.faultLabel.show()
        else:
            self.faultLabel.hide()


# ===========================================================================
class EventFeed(QFrame):
    """The rolling Info / Warning / Critical log."""

    def __init__(self, title='EVENT LOG', compact=False):
        super().__init__()
        self.compact = compact
        self.count = 0
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 11)
        outer.setSpacing(9)

        header = QHBoxLayout()
        header.addWidget(t.caption(title))
        header.addStretch()
        self.counterLabel = t.label('0 events', size=10, color=t.TEXT_MUTED)
        clearBtn = QPushButton('Clear')
        clearBtn.setStyleSheet(t.ghost_button_style())
        clearBtn.clicked.connect(self.clear)
        header.addWidget(self.counterLabel)
        header.addWidget(clearBtn)
        outer.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            'QScrollArea { border: none; background: transparent; }' + t.SCROLLBAR)

        self.container = QWidget()
        self.container.setStyleSheet('background: transparent;')
        self.items = QVBoxLayout(self.container)
        self.items.setContentsMargins(0, 0, 6, 0)
        self.items.setSpacing(5)
        self.items.addStretch()
        self.scroll.setWidget(self.container)

        self.empty = w.EmptyState('◔', 'No events yet',
                                  'Alerts appear here as conditions change.')
        outer.addWidget(self.empty)
        outer.addWidget(self.scroll, stretch=1)
        self.scroll.hide()

    def add_event(self, level, code, message, ts=None, operator=None,
                  simulated=False):
        level = cfg.normalise_level(level)
        color = t.level_color(level)
        stamp = (ts or '')[-8:] or datetime.now().strftime('%H:%M:%S')

        card = QFrame()
        card.setObjectName('eventCard')
        card.setStyleSheet('QFrame#eventCard { background-color: %s; border: none; '
                           'border-left: 3px solid %s; border-radius: %dpx; }'
                           % (t.PANEL_ALT, color, t.RADIUS_SM))
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(9)

        timeLabel = t.label(stamp, size=10, color=t.TEXT_MUTED, mono=True)
        timeLabel.setFixedWidth(54)
        badge = w.LevelPill(level, size=9)
        badge.setFixedWidth(76)

        text = message
        if operator:
            text += '  ·  %s' % operator
        messageLabel = t.label(text, size=11)
        messageLabel.setWordWrap(True)

        row.addWidget(timeLabel, alignment=Qt.AlignTop)
        row.addWidget(badge, alignment=Qt.AlignTop)
        row.addWidget(messageLabel, stretch=1)
        if simulated:
            sim = w.Pill('SIM', t.SIM, filled=False, size=9)
            sim.setFixedWidth(42)
            row.addWidget(sim, alignment=Qt.AlignTop)

        self.items.insertWidget(self.items.count() - 1, card)
        self.count += 1
        self.counterLabel.setText('%d events' % self.count)
        self.empty.hide()
        self.scroll.show()

        while self.items.count() - 1 > MAX_FEED_ITEMS:
            item = self.items.takeAt(0)
            w.discard(item.widget())

        bar = self.scroll.verticalScrollBar()
        if bar.value() >= bar.maximum() - 40:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(20, lambda: bar.setValue(bar.maximum()))

    def clear(self):
        while self.items.count() > 1:
            item = self.items.takeAt(0)
            w.discard(item.widget())
        self.count = 0
        self.counterLabel.setText('0 events')
        self.scroll.hide()
        self.empty.show()


# ===========================================================================
class IncidentCard(QFrame):
    """One incident with its lifecycle actions."""

    acknowledged = pyqtSignal(int)
    resolved = pyqtSignal(int)

    def __init__(self, incident, compact=False):
        super().__init__()
        self.incident = incident
        self.compact = compact
        severity = cfg.normalise_level(incident.get('severity'))
        color = t.level_color(severity)

        self.setObjectName('panel')
        self.setStyleSheet(
            'QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-left: 3px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, t.BORDER, color, t.RADIUS))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(w.LevelPill(severity, size=9))
        head.addWidget(t.label(incident.get('code', ''), size=11, bold=True,
                               mono=True))
        head.addStretch()
        if incident.get('simulated'):
            head.addWidget(w.Pill('SIMULATED', t.SIM, filled=False, size=9))
        head.addWidget(w.Pill(incident.get('status', ''),
                              t.ACCENT if incident.get('status') == 'ACKNOWLEDGED'
                              else t.TEXT_MUTED, filled=False, size=9))
        layout.addLayout(head)

        message = t.label(incident.get('message', ''), size=12)
        message.setWordWrap(True)
        layout.addWidget(message)

        if incident.get('root_cause') and not compact:
            cause = t.label('Assessment: ' + incident['root_cause'], size=10,
                            color=t.TEXT_DIM)
            cause.setWordWrap(True)
            layout.addWidget(cause)

        meta = []
        device = registry.get(incident.get('device') or '')
        if device:
            meta.append(device.label)
        meta.append('started %s' % (incident.get('started_at') or '--')[-8:])
        duration = duration_between(incident.get('started_at'),
                                    incident.get('ended_at'))
        meta.append('for %s' % humanise_duration(duration))
        if incident.get('acknowledged_by'):
            meta.append('ack %s' % incident['acknowledged_by'])
        layout.addWidget(t.label('  ·  '.join(meta), size=10, color=t.TEXT_MUTED))

        if incident.get('status') in (db.STATUS_ACTIVE, db.STATUS_ACKNOWLEDGED):
            actions = QHBoxLayout()
            actions.addStretch()
            if incident.get('status') == db.STATUS_ACTIVE:
                ack = QPushButton('Acknowledge')
                ack.setStyleSheet(t.outline_button_style(t.ACCENT))
                ack.clicked.connect(
                    lambda: self.acknowledged.emit(incident['id']))
                actions.addWidget(ack)
            resolve = QPushButton('Resolve')
            resolve.setStyleSheet(t.ghost_button_style())
            resolve.clicked.connect(lambda: self.resolved.emit(incident['id']))
            actions.addWidget(resolve)
            layout.addLayout(actions)
