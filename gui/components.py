"""Composite widgets specific to this product, shared across the pages."""

from datetime import datetime

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from database import db
from gui import glossary
from gui.charts import Sparkline
from ui import help as h
from ui import icons
from ui import status as stat
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
        self._caption = caption_text

    def set_metric(self, value, color=t.TEXT, suffix='', state=None):
        """Set the reading, and name its state in the caption.

        Colouring the number amber was the only signal that a supporting
        sensor had left its range, which is a state carried by colour alone.
        The caption now carries the word as well.
        """
        if value is None:
            self.set_value('--', t.TEXT_MUTED)
            self.set_caption('%s · no reading' % self._caption)
            return
        # A healthy reading is ink, not green. Painting it green said nothing
        # the caption underneath did not already say, and it spent the contrast
        # that the one tile which does go amber needs in order to stand out.
        self.set_value((self.fmt % value) + self.unit + suffix,
                       t.TEXT if color == t.OK else color)
        if state and state != stat.NORMAL:
            self.set_caption('%s · %s' % (self._caption,
                                          stat.label(state)))
        else:
            self.set_caption(self._caption)


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
        self._on = False
        self._problem = None
        self._health_state = stat.OFFLINE
        self._measured_state = stat.NORMAL
        self.setObjectName('panel')
        self.setMinimumHeight(152)
        # The header - icon, name, info dot and status chip - reports a natural
        # width of about 255 px, and three of those plus the side column put
        # the dashboard over the console's own minimum window width, which
        # showed up as a horizontal scrollbar. An explicit floor lets the row
        # share out the width it actually has instead; at 1180 px each card
        # still gets ~300, so nothing is ever clipped in practice.
        self.setMinimumWidth(206)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._paint_border(t.BORDER)
        if self.help:
            self.help.apply(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.deviceIcon = icons.Icon(self.device.icon, 16, t.TEXT_DIM,
                                     width=1.6)
        head.addWidget(self.deviceIcon, alignment=Qt.AlignVCenter)
        name = self.help.name if self.help else self.device.label
        head.addWidget(t.title(name))
        if self.help:
            head.addWidget(self.help.dot(size=11))
        head.addStretch()
        self.healthPill = w.HealthPill('OFFLINE')
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
            self.measuredLabel = t.label('--', size=t.SIZE_MD,
                                         color=t.TEXT_MUTED,
                                         weight=t.W_MEDIUM, mono=True,
                                         align=Qt.AlignLeft | Qt.AlignVCenter)
            self.measuredLabel.setFixedHeight(30)
            measuredColumn.addWidget(self.measuredLabel)
            self.captionLabel = t.label('', size=t.SIZE_XS, color=t.TEXT_MUTED)
            self.captionLabel.setWordWrap(True)
            measuredColumn.addWidget(self.captionLabel)
            measuredColumn.addStretch()
            columns.addLayout(measuredColumn, stretch=1)
        layout.addLayout(columns)

        if not measured:
            # Saying so out loud is honest, and it explains why the other two
            # cards carry a second number and this one does not.
            note = t.label('No separate sensor - the sounder cannot confirm '
                           'itself.', size=t.SIZE_XS, color=t.TEXT_MUTED)
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
            'font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'letter-spacing: 0.4px;'
            % (t.ON_ACCENT if is_on else t.TEXT_DIM,
               color if is_on else t.PANEL_ALT, t.RADIUS_SM, t.FONT,
               t.SIZE_BASE, t.W_SEMIBOLD))

    def set_state(self, is_on):
        self._on = is_on
        self._paint_state(is_on)
        self._refresh_border()

    def _refresh_border(self):
        """The outline carries the worst news on the card.

        It used to carry only "is this relay on", which meant a compressor
        commanded ON while drawing no current - the exact failure this card
        exists to expose - was outlined in a calm accent blue with the alarm
        buried in small red text beside it.
        """
        if self._problem:
            self._paint_border(self._problem)
        elif self._on:
            self._paint_border(self.on_color)
        else:
            self._paint_border(t.BORDER)

    def set_health(self, health):
        self._health_state = stat.from_health(health)
        self._health_term = stat.HEALTH_TERMS.get(health, '')
        self._refresh_status()

    def _refresh_status(self):
        """The chip shows the worst of the link and the measurement.

        A relay reporting in on schedule is CONNECTED however badly the motor
        behind it is behaving, so this card used to show a calm green NORMAL
        beside a red outline and the words "switched on but not running" -
        three signals disagreeing about the same box. The chip now reports the
        equipment, and its tooltip separates the two halves.
        """
        state = stat.worst(self._health_state, self._measured_state)
        entry = stat.get(state)
        self.healthPill.set(entry.label, entry.color, entry.mark)
        self.healthPill.setToolTip(stat.tooltip(
            state, 'Equipment status: %s' % entry.label,
            extra=getattr(self, '_health_term', '')))
        self.deviceIcon.set_color(
            entry.color if state != stat.NORMAL else t.TEXT_DIM)

    def set_measurement(self, text, color=t.TEXT_MUTED, caption=''):
        self._problem = color if color in (t.CRITICAL, t.WARN) else None
        self._measured_state = (stat.CRITICAL if color == t.CRITICAL else
                                stat.WARNING if color == t.WARN else
                                stat.NORMAL)
        self._refresh_border()
        self._refresh_status()
        if self.measuredLabel is None:
            return
        self.measuredLabel.setText(text)
        self.measuredLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'background: transparent; border: none;'
            % (color, t.FONT_MONO, t.SIZE_MD, t.W_MEDIUM))
        self.captionLabel.setText(caption)
        self.captionLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; '
            'background: transparent; border: none;'
            % (color if color == t.CRITICAL else t.TEXT_MUTED, t.FONT,
               t.SIZE_XS))


# ===========================================================================
class DeviceCard(QFrame):
    """One device, answering everything somebody could ask about it in order.

    Reading top to bottom: what it is, where it sits, what it measures, what it
    says right now, how that compares with normal, how it has been moving, why
    anyone should care, when it last spoke, and - only when something is wrong
    - which incidents it is tied to and what to do about it.

    The plain-language purpose is the headline and the engineering identity
    sits underneath it, so somebody who has never met the word "tachometer"
    can still tell at a glance which box has stopped talking. The
    troubleshooting half stays hidden while the device is healthy, which keeps
    a wall of eleven cards readable when nothing is wrong.
    """

    NUMERIC_UNITS = {'temp': '°C', 'temp_b': '°C', 'ambient': '°C',
                     'power': '%', 'current': 'A', 'fan_rpm': 'rpm'}

    def __init__(self, device):
        super().__init__()
        self.device = device
        self.help = glossary.device(device.id)
        self.setObjectName('panel')
        self._paint_border(t.BORDER)
        self.setMinimumHeight(210)

        topic = device.telemetry_topic or device.sts_topic or ''
        if self.help:
            self.help.apply(self, note='%s   ·   %s'
                            % (self.help.note, topic.replace(cfg.TOPIC_ROOT, '…')))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        # -- what it is, and its status ------------------------------------
        head = QHBoxLayout()
        head.setSpacing(9)
        self.deviceIcon = icons.Icon(device.icon, 17, t.TEXT_DIM, width=1.6)
        head.addWidget(self.deviceIcon, alignment=Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        nameRow = QHBoxLayout()
        nameRow.setSpacing(5)
        nameRow.addWidget(t.title(self.help.name if self.help
                                  else device.label, size=t.SIZE_SM))
        if self.help:
            nameRow.addWidget(self.help.dot(size=11))
        nameRow.addStretch()
        titles.addLayout(nameRow)
        # The technical identity is kept, one step down the hierarchy.
        identity = t.label('%s · %s' % (device.label, device.kind.title()),
                           size=t.SIZE_XS, color=t.TEXT_MUTED)
        identity.setWordWrap(True)
        titles.addWidget(identity)
        head.addLayout(titles, stretch=1)
        self.healthPill = w.HealthPill('OFFLINE')
        head.addWidget(self.healthPill, alignment=Qt.AlignTop)
        layout.addLayout(head)

        # -- where it is, and what it measures -----------------------------
        context = QHBoxLayout()
        context.setSpacing(6)
        context.addWidget(icons.Icon('room', 11, t.TEXT_MUTED, width=1.5),
                          alignment=Qt.AlignVCenter)
        location = t.label(device.group, size=t.SIZE_XS,
                           color=t.TEXT_MUTED)
        h.set_tip(location, 'Where this device sits: %s.'
                            % glossary.GROUPS.get(device.group, device.group))
        context.addWidget(location)
        if device.describes:
            context.addWidget(t.label('·', size=t.SIZE_XS,
                                      color=t.TEXT_MUTED))
            measures = t.label(device.describes, size=t.SIZE_XS,
                               color=t.TEXT_MUTED)
            measures.setWordWrap(True)
            h.set_tip(measures, 'What this device measures or switches.')
            context.addWidget(measures, stretch=1)
        else:
            context.addStretch()
        layout.addLayout(context)

        # -- what it says now ----------------------------------------------
        self.valueLabel = t.value('--', size=t.SIZE_XL - 2)
        h.set_tip(self.valueLabel, 'The reading this device is publishing '
                                   'right now.')
        layout.addWidget(self.valueLabel)

        # Only devices whose reading is a number get a trend line; for a door
        # or a relay the strip would be a permanently empty box.
        self.spark = Sparkline(t.ACCENT, height=30,
                               unit=self.NUMERIC_UNITS.get(device.id, ''))
        h.set_tip(self.spark, 'Recent history: how this reading has moved over '
                              'the last few minutes.')
        self.spark.hide()
        layout.addWidget(self.spark)

        # -- how to judge it -------------------------------------------------
        if self.help and self.help.normal:
            expected = t.prose(self.help.normal, lead='Normal',
                               color=t.TEXT_DIM)
            h.set_tip(expected, 'The range or state this device is expected to '
                                'report when everything is working.')
            layout.addWidget(expected)

        # -- why anyone should care ------------------------------------------
        if self.help and self.help.why:
            why = t.prose(self.help.why, lead='Why it matters')
            layout.addWidget(why)

        self.freshnessLabel = t.label('no telemetry yet', size=t.SIZE_XS,
                                      color=t.TEXT_MUTED)
        h.set_help(self.freshnessLabel, 'Freshness',
                   'How long ago this device last sent a reading.',
                   'A device that has gone quiet is not a device that is fine - '
                   'whatever it was checking is no longer being checked.',
                   'A few seconds ago.')
        layout.addWidget(self.freshnessLabel)

        # -- the troubleshooting half, only when there is trouble ------------
        self.incidentLabel = t.label('', size=t.SIZE_XS, color=t.WARN)
        self.incidentLabel.setWordWrap(True)
        h.set_help(self.incidentLabel, 'Related incidents',
                   'Problems the system currently has open against this '
                   'device.',
                   'It connects a misbehaving box to the case somebody is '
                   'supposed to be working on. The full record is on the '
                   'Incidents page.')
        self.incidentLabel.hide()
        layout.addWidget(self.incidentLabel)

        self.actionBox = QFrame()
        self.actionBox.setObjectName('deviceAction')
        actionLayout = QVBoxLayout(self.actionBox)
        actionLayout.setContentsMargins(9, 7, 9, 7)
        actionLayout.setSpacing(2)
        self.actionCaption = t.caption('What to do', color=t.WARN)
        self.actionLabel = t.label('', size=t.SIZE_XS, color=t.TEXT)
        self.actionLabel.setWordWrap(True)
        actionLayout.addWidget(self.actionCaption)
        actionLayout.addWidget(self.actionLabel)
        h.set_help(self.actionBox, 'Recommended action',
                   'The step that usually clears this condition, or the person '
                   'to call if it does not.',
                   'Guidance, not a substitute for local procedure - follow '
                   'your site rules where they differ.')
        self.actionBox.hide()
        layout.addWidget(self.actionBox)

        self.faultLabel = t.label('', size=t.SIZE_XS, color=t.SIM)
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

    # ------------------------------------------------------------------
    def update_state(self, health, value_text, age_seconds, faults,
                     incidents=()):
        state = stat.from_health(health)
        entry = stat.get(state)
        self.healthPill.set_health(health)
        self.deviceIcon.set_color(
            entry.color if state != stat.NORMAL else t.TEXT_DIM)
        self._paint_border(entry.color if state in (stat.CRITICAL,
                                                    stat.WARNING)
                           else t.BORDER)

        self.valueLabel.setText(value_text)
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: 600; '
            'background: transparent; border: none;'
            % (t.TEXT if state != stat.OFFLINE else t.TEXT_MUTED,
               t.FONT_MONO, t.SIZE_XL - 2))

        if state == stat.OFFLINE:
            self.freshnessLabel.setText('Not reporting · last seen %s'
                                        % humanise_age(age_seconds))
            color = t.CRITICAL
        else:
            self.freshnessLabel.setText('Updated %s' % humanise_age(age_seconds))
            color = t.TEXT_MUTED
        self.freshnessLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; '
            'background: transparent; border: none;'
            % (color, t.FONT, t.SIZE_XS))

        self._update_incidents(incidents, state)
        self._update_faults(faults)

    def _update_incidents(self, incidents, state):
        """Tie the device to its open cases, and to what to do about them."""
        incidents = list(incidents or [])
        if incidents:
            worst = max(incidents,
                        key=lambda row: cfg.LEVEL_ORDER.get(
                            cfg.normalise_level(row.get('severity')), 0))
            explain = glossary.alert(worst.get('code'))
            severity = stat.from_level(cfg.normalise_level(
                worst.get('severity')))
            tone = stat.color(severity)
            extra = ('' if len(incidents) == 1
                     else '  ·  +%d more' % (len(incidents) - 1))
            self.incidentLabel.setText('Open incident: %s%s'
                                       % (explain.name, extra))
            self.incidentLabel.setStyleSheet(
                'color: %s; font-family: "%s"; font-size: %dpx; '
                'font-weight: %d; background: transparent; border: none;'
                % (tone, t.FONT, t.SIZE_XS, t.W_MEDIUM))
            self.incidentLabel.show()
            self._show_action(explain.action, tone)
            return

        self.incidentLabel.hide()
        # No case open, but the device itself is not healthy: say what that
        # means and what would clear it, rather than leaving a red pill alone.
        if state == stat.OFFLINE:
            self._show_action(
                'Check the device has power and is on the network. Until it '
                'reports again, nothing it was watching is being checked.',
                t.OFFLINE_FG)
        elif state == stat.CRITICAL:
            self._show_action(
                'This device is contradicting what the equipment was told to '
                'do. Treat the equipment as unproven and check it in person.',
                t.CRITICAL)
        elif state == stat.WARNING:
            self._show_action(
                'Still reporting, but outside its expected range. Check it '
                'before the condition escalates.', t.WARN)
        else:
            self.actionBox.hide()

    def _show_action(self, text, color):
        if not text:
            self.actionBox.hide()
            return
        self.actionBox.setStyleSheet(
            'QFrame#deviceAction { background-color: %s; border: none; '
            'border-left: 2px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, color, t.RADIUS_SM))
        self.actionCaption.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'background: transparent; border: none;'
            % (color, t.FONT, t.SIZE_XS, t.W_SEMIBOLD))
        self.actionLabel.setText(text)
        self.actionBox.show()

    def _update_faults(self, faults):
        if not faults:
            self.faultLabel.hide()
            return
        labels = []
        for fault_id in faults:
            fault = self.device.fault(fault_id)
            labels.append(fault.label if fault else fault_id)
        self.faultLabel.setText('%s: %s' % (stat.label(stat.SIMULATED),
                                            ', '.join(labels)))
        self.faultLabel.show()


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
        header.addWidget(t.title(title))
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
        self.counterLabel = t.label('0 events', size=t.SIZE_XS,
                                    color=t.TEXT_MUTED)
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
            'clock', 'Nothing has happened yet',
            'Warnings and alarms appear here the moment a condition changes. '
            'The full stored record is on the History page.')
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

        timeLabel = t.label(stamp, size=t.SIZE_CAPTION, color=t.TEXT_MUTED,
                            mono=True)
        timeLabel.setFixedWidth(54)
        badge = w.LevelPill(level, size=t.SIZE_CAPTION)
        badge.setMinimumWidth(86)

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
            sim = w.Pill('Sim', t.SIM, filled=False, size=t.SIZE_CAPTION,
                         mark=stat.mark(stat.SIMULATED))
            sim.setToolTip(stat.tooltip(stat.SIMULATED))
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
        severityPill = w.LevelPill(severity, size=t.SIZE_CAPTION)
        h.set_help(severityPill, 'Severity: %s' % severity.title(),
                   'Critical means stock is at risk now. Warning means '
                   'something needs checking before it becomes critical.',
                   'A critical condition also sounds the alarm in the storeroom.')
        head.addWidget(severityPill)
        head.addStretch()
        if incident.get('simulated'):
            simPill = w.Pill(stat.label(stat.SIMULATED), t.SIM,
                             filled=False, size=t.SIZE_CAPTION,
                             mark=stat.mark(stat.SIMULATED))
            glossary.term('simulated').apply(simPill)
            head.addWidget(simPill)
        status = incident.get('status', '')
        # The lifecycle chip used to be drawn in the muted grey reserved for
        # small print, which put it at 3:1 against the card - below the
        # readable threshold for the one word that says whether anybody has
        # picked this up.
        status_colors = {db.STATUS_ACTIVE: t.TEXT_DIM,
                         db.STATUS_ACKNOWLEDGED: t.ACCENT,
                         db.STATUS_RESOLVED: t.OK}
        statusPill = w.Pill(status.title(),
                            status_colors.get(status, t.TEXT_DIM),
                            filled=False, size=t.SIZE_CAPTION,
                            mark={db.STATUS_ACTIVE: 'clock',
                                  db.STATUS_ACKNOWLEDGED: 'info',
                                  db.STATUS_RESOLVED: 'check'}.get(status))
        h.set_help(statusPill, 'Status: %s' % status.title(),
                   'Active means nobody has picked it up yet. Acknowledged '
                   'means somebody is dealing with it. Resolved means the case '
                   'is closed.',
                   glossary.term('incident').why)
        head.addWidget(statusPill)
        layout.addLayout(head)

        # -- what happened, in plain words --------------------------------
        headline = t.label(explain.name, size=t.SIZE_BASE, weight=t.W_SEMIBOLD)
        headline.setWordWrap(True)
        layout.addWidget(headline)

        if not compact and explain.what:
            layout.addWidget(t.prose(explain.what, size=t.SIZE_SM,
                                     color=t.TEXT_DIM))

        if not compact and explain.why:
            layout.addWidget(t.prose(explain.why, lead='Why it matters',
                                     size=t.SIZE_SM))

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
        metaLabel = t.label('  ·  '.join(meta), size=t.SIZE_XS,
                            color=t.TEXT_MUTED)
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
        body = t.label(text, size=t.SIZE_XS, color=t.TEXT)
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

        toggle = QPushButton('Technical details')
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setStyleSheet(t.ghost_button_style())
        toggle.setIconSize(QSize(13, 13))
        toggle.setIcon(icons.icon('chevron_right', 13, t.TEXT_DIM))
        h.set_tip(toggle, 'Show the alert code and the exact rule message.')

        def flip():
            shown = not body.isVisible()
            body.setVisible(shown)
            toggle.setIcon(icons.icon(
                'chevron_down' if shown else 'chevron_right', 13, t.TEXT_DIM))
            toggle.setAccessibleDescription(
                'Expanded' if shown else 'Collapsed')

        toggle.clicked.connect(flip)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(toggle)
        row.addStretch()
        column.addLayout(row)
        column.addWidget(body)
        return container
