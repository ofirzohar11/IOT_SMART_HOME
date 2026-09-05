"""Composite widgets specific to this product, shared across the pages."""

from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from database import db
from gui import glossary
from gui.charts import Sparkline
from ui import help as h
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

    The left half is what the system *told* the equipment to do; the right half
    is what a separate sensor says it is *really* doing. Labelling the two
    halves is the whole point of the card: a relay that reports ON proves
    nothing, and this is where a normal user can see the difference.
    """

    def __init__(self, device_id, on_color, measured=True):
        self.device = registry.get(device_id)
        self.help = glossary.device(device_id)
        super().__init__()
        self.on_color = on_color
        self.setObjectName('panel')
        self.setMinimumHeight(152)
        self._paint_border(t.BORDER)
        if self.help:
            self.help.apply(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(7)
        head.addWidget(t.label(self.device.icon, size=16))
        name = self.help.name if self.help else self.device.label
        head.addWidget(t.caption(name))
        if self.help:
            head.addWidget(self.help.dot(size=11))
        head.addStretch()
        self.healthPill = w.HealthPill('OFFLINE')
        h.set_help(self.healthPill, 'Device health',
                   'How well this device is reporting to the system.',
                   glossary.term('health').why,
                   'Connected.')
        head.addWidget(self.healthPill)
        layout.addLayout(head)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        commanded = QVBoxLayout()
        commanded.setSpacing(3)
        commandedCaption = t.caption('Told to', color=t.TEXT_MUTED)
        glossary.term('commanded').apply(commandedCaption, 'Told to')
        commanded.addWidget(commandedCaption)
        self.stateLabel = QLabel('OFF')
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self.stateLabel.setFixedHeight(30)
        self._paint_state(False)
        commanded.addWidget(self.stateLabel)
        commanded.addStretch()
        columns.addLayout(commanded, stretch=1)

        self.measuredLabel = None
        if measured:
            measuredColumn = QVBoxLayout()
            measuredColumn.setSpacing(3)
            measuredCaption = t.caption('Really doing', color=t.TEXT_MUTED)
            glossary.term('measured').apply(measuredCaption, 'Really doing')
            measuredColumn.addWidget(measuredCaption)
            self.measuredLabel = t.label('--', size=15, color=t.TEXT_MUTED,
                                         bold=True, mono=True,
                                         align=Qt.AlignLeft | Qt.AlignVCenter)
            self.measuredLabel.setFixedHeight(30)
            measuredColumn.addWidget(self.measuredLabel)
            self.captionLabel = t.label('', size=9, color=t.TEXT_MUTED)
            self.captionLabel.setWordWrap(True)
            measuredColumn.addWidget(self.captionLabel)
            measuredColumn.addStretch()
            columns.addLayout(measuredColumn, stretch=1)
        layout.addLayout(columns)

        if not measured:
            # Saying so out loud is honest, and it explains why the other two
            # cards carry a second number and this one does not.
            note = t.label('No separate sensor - the sounder cannot confirm '
                           'itself.', size=9, color=t.TEXT_MUTED)
            note.setWordWrap(True)
            layout.addWidget(note)
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
        entry = glossary.health(health)
        if entry:
            entry.apply(self.healthPill)

    def set_measurement(self, text, color=t.TEXT_MUTED, caption=''):
        if self.measuredLabel is None:
            return
        self.measuredLabel.setText(text)
        self.measuredLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 15px; font-weight: 600; '
            'background: transparent; border: none;' % (color, t.FONT_MONO))
        self.captionLabel.setText(caption)
        self.captionLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 9px; background: transparent; '
            'border: none;' % (color if color == t.CRITICAL else t.TEXT_MUTED,
                               t.FONT))


# ===========================================================================
class DeviceCard(QFrame):
    """A device on the Devices page: what it is for, how it is, what it says.

    The plain-language purpose is the headline and the engineering identity sits
    underneath it, so somebody who has never met the word "tachometer" can still
    tell at a glance which box has stopped talking.
    """

    def __init__(self, device):
        super().__init__()
        self.device = device
        self.help = glossary.device(device.id)
        self.setObjectName('panel')
        self._paint_border(t.BORDER)
        self.setMinimumHeight(176)

        topic = device.telemetry_topic or device.sts_topic or ''
        if self.help:
            self.help.apply(self, note='%s   ·   %s'
                            % (self.help.note, topic.replace(cfg.TOPIC_ROOT, '…')))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(9)
        head.addWidget(t.label(device.icon, size=17), alignment=Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        nameRow = QHBoxLayout()
        nameRow.setSpacing(5)
        nameRow.addWidget(t.label(self.help.name if self.help else device.label,
                                  size=12, bold=True))
        if self.help:
            nameRow.addWidget(self.help.dot(size=11))
        nameRow.addStretch()
        titles.addLayout(nameRow)
        # The technical identity is kept, one step down the hierarchy.
        identity = t.label('%s · %s · %s' % (device.label, device.kind.title(),
                                             device.group),
                           size=10, color=t.TEXT_MUTED)
        identity.setWordWrap(True)
        titles.addWidget(identity)
        head.addLayout(titles, stretch=1)
        self.healthPill = w.HealthPill('OFFLINE')
        head.addWidget(self.healthPill, alignment=Qt.AlignTop)
        layout.addLayout(head)

        self.valueLabel = t.label('--', size=19, bold=True, mono=True)
        layout.addWidget(self.valueLabel)

        # Only devices whose reading is a number get a trend line; for a door
        # or a relay the strip would be a permanently empty box.
        self.spark = Sparkline(t.ACCENT, height=30)
        h.set_tip(self.spark, 'The last few minutes of this reading.')
        self.spark.hide()
        layout.addWidget(self.spark)

        if self.help and self.help.normal:
            expected = t.label('Normal: ' + self.help.normal, size=10,
                               color=t.TEXT_DIM)
            expected.setWordWrap(True)
            layout.addWidget(expected)

        self.freshnessLabel = t.label('no telemetry yet', size=10,
                                      color=t.TEXT_MUTED)
        h.set_help(self.freshnessLabel, 'Freshness',
                   'How long ago this device last sent a reading.',
                   'A device that has gone quiet is not a device that is fine - '
                   'whatever it was checking is no longer being checked.',
                   'A few seconds ago.')
        layout.addWidget(self.freshnessLabel)

        self.faultLabel = t.label('', size=10, color=t.SIM)
        self.faultLabel.setWordWrap(True)
        h.set_help(self.faultLabel, 'Simulated fault armed',
                   glossary.term('simulated').what,
                   glossary.term('simulated').why)
        self.faultLabel.hide()
        layout.addWidget(self.faultLabel)
        layout.addStretch()

    def _paint_border(self, color):
        self.setStyleSheet('QFrame#panel { background-color: %s; border: 1px solid %s; '
                           'border-radius: %dpx; }' % (t.PANEL, color, t.RADIUS_LG))

    def update_state(self, health, value_text, age_seconds, faults):
        self.healthPill.set_health(health)
        entry = glossary.health(health)
        if entry:
            entry.apply(self.healthPill)
        self._paint_border(t.health_color(health)
                           if health in ('FAULT', 'DEGRADED') else t.BORDER)
        self.valueLabel.setText(value_text)
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 19px; font-weight: 600; '
            'background: transparent; border: none;'
            % (t.TEXT if health != 'OFFLINE' else t.TEXT_MUTED, t.FONT_MONO))

        if health == 'OFFLINE':
            self.freshnessLabel.setText('Not reporting · last seen %s'
                                        % humanise_age(age_seconds))
            color = t.CRITICAL
        else:
            self.freshnessLabel.setText('Updated %s' % humanise_age(age_seconds))
            color = t.TEXT_MUTED
        self.freshnessLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 10px; background: transparent; '
            'border: none;' % (color, t.FONT))

        if faults:
            labels = []
            for fault_id in faults:
                fault = self.device.fault(fault_id)
                labels.append(fault.label if fault else fault_id)
            self.faultLabel.setText('SIMULATED FAULT: ' + ', '.join(labels))
            self.faultLabel.show()
        else:
            self.faultLabel.hide()


# ===========================================================================
class EventFeed(QFrame):
    """The rolling Info / Warning / Critical log."""

    def __init__(self, title='Recent activity', compact=False):
        super().__init__()
        self.compact = compact
        self.count = 0
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 11)
        outer.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(t.caption(title))
        header.addWidget(h.dot(
            'Recent activity',
            'Everything the monitoring rules have reported since this window '
            'was opened, newest at the bottom.',
            'It is the running commentary behind the incidents: it shows '
            'conditions clearing as well as appearing, which a list of open '
            'incidents cannot.',
            note='Clearing the list only empties this panel. Nothing is '
                 'deleted - the full record stays on the History page.',
            size=12))
        header.addStretch()
        self.counterLabel = t.label('0 events', size=10, color=t.TEXT_MUTED)
        clearBtn = QPushButton('Clear')
        clearBtn.setStyleSheet(t.ghost_button_style())
        h.set_tip(clearBtn, 'Empty this panel. The stored record is not '
                            'affected - see the History page.')
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

        self.empty = w.EmptyState(
            '◔', 'Nothing has happened yet',
            'Warnings and alarms appear here the moment a condition changes.')
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
        explain = glossary.alert(code)
        explain.apply(card, note='Alert code %s' % code if code else None)
        h.set_tip(badge, explain.name)

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
    """One incident, answering three questions before it shows any jargon.

    *What happened* in plain words, *why it matters*, and *what to do about it*
    come first; the alert code, the raw rule message and the timings are folded
    behind a details toggle. An operator who already knows the codes loses
    nothing - they are one click away - and everybody else gets a sentence they
    can act on.
    """

    acknowledged = pyqtSignal(int)
    resolved = pyqtSignal(int)

    def __init__(self, incident, compact=False):
        super().__init__()
        self.incident = incident
        self.compact = compact
        severity = cfg.normalise_level(incident.get('severity'))
        color = t.level_color(severity)
        code = incident.get('code', '')
        explain = glossary.alert(code)

        self.setObjectName('panel')
        self.setStyleSheet(
            'QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-left: 3px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, t.BORDER, color, t.RADIUS))
        explain.apply(self, note='Alert code %s' % code if code else None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(7)

        # -- severity and lifecycle ---------------------------------------
        head = QHBoxLayout()
        head.setSpacing(7)
        severityPill = w.LevelPill(severity, size=9)
        h.set_help(severityPill, 'Severity: %s' % severity.title(),
                   'Critical means stock is at risk now. Warning means '
                   'something needs checking before it becomes critical.',
                   'A critical condition also sounds the alarm in the storeroom.')
        head.addWidget(severityPill)
        head.addStretch()
        if incident.get('simulated'):
            simPill = w.Pill('SIMULATED', t.SIM, filled=False, size=9)
            glossary.term('simulated').apply(simPill)
            head.addWidget(simPill)
        status = incident.get('status', '')
        statusPill = w.Pill(status,
                            t.ACCENT if status == 'ACKNOWLEDGED' else t.TEXT_MUTED,
                            filled=False, size=9)
        h.set_help(statusPill, 'Status: %s' % status.title(),
                   'Active means nobody has picked it up yet. Acknowledged '
                   'means somebody is dealing with it. Resolved means the case '
                   'is closed.',
                   glossary.term('incident').why)
        head.addWidget(statusPill)
        layout.addLayout(head)

        # -- what happened, in plain words --------------------------------
        headline = t.label(explain.name, size=13, bold=True)
        headline.setWordWrap(True)
        layout.addWidget(headline)

        if not compact and explain.what:
            what = t.label(explain.what, size=11, color=t.TEXT_DIM)
            what.setWordWrap(True)
            layout.addWidget(what)

        if not compact and explain.why:
            why = t.label('Why it matters: ' + explain.why, size=11,
                          color=t.TEXT_DIM)
            why.setWordWrap(True)
            layout.addWidget(why)

        # -- what to do ----------------------------------------------------
        if explain.action:
            layout.addWidget(self._action_box(explain.action, color, compact))

        # -- context line --------------------------------------------------
        meta = []
        device = registry.get(incident.get('device') or '')
        if device:
            meta.append(glossary.device_name(device.id, device.label))
        meta.append('started %s' % (incident.get('started_at') or '--')[-8:])
        duration = duration_between(incident.get('started_at'),
                                    incident.get('ended_at'))
        meta.append('open for %s' % humanise_duration(duration))
        if incident.get('acknowledged_by'):
            meta.append('acknowledged by %s' % incident['acknowledged_by'])
        metaLabel = t.label('  ·  '.join(meta), size=10, color=t.TEXT_MUTED)
        metaLabel.setWordWrap(True)
        layout.addWidget(metaLabel)

        # -- the technical half, hidden until asked for --------------------
        if not compact:
            layout.addWidget(self._details(incident, code))

        # -- actions --------------------------------------------------------
        if incident.get('status') in (db.STATUS_ACTIVE, db.STATUS_ACKNOWLEDGED):
            actions = QHBoxLayout()
            actions.addStretch()
            if incident.get('status') == db.STATUS_ACTIVE:
                ack = QPushButton('Acknowledge')
                ack.setStyleSheet(t.outline_button_style(t.ACCENT))
                glossary.term('acknowledge').apply(ack)
                ack.clicked.connect(
                    lambda: self.acknowledged.emit(incident['id']))
                actions.addWidget(ack)
            resolve = QPushButton('Resolve')
            resolve.setStyleSheet(t.ghost_button_style())
            glossary.term('resolve').apply(resolve)
            resolve.clicked.connect(lambda: self.resolved.emit(incident['id']))
            actions.addWidget(resolve)
            layout.addLayout(actions)

    # ------------------------------------------------------------------
    @staticmethod
    def _action_box(text, color, compact):
        """The recommended response, given the same weight as the problem."""
        box = QFrame()
        box.setObjectName('action')
        box.setStyleSheet(
            'QFrame#action { background-color: %s; border: none; '
            'border-left: 2px solid %s; border-radius: %dpx; }'
            % (t.PANEL, color, t.RADIUS_SM))
        row = QVBoxLayout(box)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(2)
        if not compact:
            row.addWidget(t.caption('What to do', color=color))
        body = t.label(text, size=11, color=t.TEXT)
        body.setWordWrap(True)
        row.addWidget(body)
        h.set_help(box, 'Recommended action',
                   'The step that usually clears this condition, or the person '
                   'to call if it does not.',
                   'Guidance, not a substitute for local procedure - follow '
                   'your site rules where they differ.')
        return box

    @staticmethod
    def _details(incident, code):
        """Code, raw rule message and assessment, collapsed by default."""
        container = QWidget()
        container.setStyleSheet('background: transparent;')
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(5)

        body = QFrame()
        body.setObjectName('details')
        body.setStyleSheet('QFrame#details { background-color: %s; border: none; '
                           'border-radius: %dpx; }' % (t.PANEL, t.RADIUS_SM))
        inner = QVBoxLayout(body)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(4)
        inner.addWidget(w.KeyValue('Alert code', code or '--', t.TEXT, 96))
        inner.addWidget(w.KeyValue('Rule message', incident.get('message', '--'),
                                   t.TEXT, 96))
        if incident.get('root_cause'):
            inner.addWidget(w.KeyValue('Assessment', incident['root_cause'],
                                       t.TEXT_DIM, 96))
        device = registry.get(incident.get('device') or '')
        if device:
            inner.addWidget(w.KeyValue('Device', device.label, t.TEXT_DIM, 96))
        inner.addWidget(w.KeyValue('Incident', '#%s' % incident.get('id', '--'),
                                   t.TEXT_DIM, 96))
        body.hide()

        toggle = QPushButton('▸  Technical details')
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setStyleSheet(t.ghost_button_style())
        h.set_tip(toggle, 'Show the alert code and the exact rule message.')

        def flip():
            shown = not body.isVisible()
            body.setVisible(shown)
            toggle.setText(('▾  Technical details' if shown
                            else '▸  Technical details'))

        toggle.clicked.connect(flip)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(toggle)
        row.addStretch()
        column.addLayout(row)
        column.addWidget(body)
        return container
