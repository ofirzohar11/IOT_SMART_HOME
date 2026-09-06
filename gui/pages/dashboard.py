"""Operator dashboard.

The screen is arranged to answer six questions in the order an operator asks
them: is the stock safe, what is the temperature, is anything wrong, are the
machines doing what they were told, is the data trustworthy, and what happened
recently. Everything above the fold is current state; history and detail live
further down and on the other pages.

The banner across the top answers the first three in words rather than in
numbers - safe or not, what is wrong, and what to do about it - because the
person who walks past this screen is usually not the person who built it.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QSizePolicy, QVBoxLayout, QWidget)

from config import devices as registry
from config import mqtt_init as cfg
from database import db
from gui import charts, glossary
from gui.components import ActuatorCard, EventFeed, IncidentCard, MetricTile
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import icons
from ui import status as stat
from ui import theme as t
from ui import widgets as w

# The plain-language verdict. The technical severity is still shown beside it,
# in the counts and on every incident, so nothing is hidden by simplifying.
HEADLINES = {
    cfg.LEVEL_INFO: 'The fridge is safe',
    cfg.LEVEL_WARNING: 'Something needs checking',
    cfg.LEVEL_CRITICAL: 'Act now - the stock is at risk',
}

STATUS_WORDS = {
    cfg.LEVEL_INFO: 'SAFE',
    cfg.LEVEL_WARNING: 'ATTENTION',
    cfg.LEVEL_CRITICAL: 'ACT NOW',
}

DEFAULT_ACTIONS = {
    cfg.LEVEL_INFO: 'Nothing to do. Storage conditions are inside the required '
                    'limits.',
    cfg.LEVEL_WARNING: 'Open the Incidents page to see what needs checking.',
    cfg.LEVEL_CRITICAL: 'Open the Incidents page - each one lists the '
                        'recommended action.',
}

STATUS_HELP = h.tooltip_html(
    'Overall verdict',
    'One word for the state of the whole unit: SAFE, ATTENTION or ACT NOW.',
    'It is the answer to the only question most people have when they walk '
    'past this screen.',
    'SAFE - the temperature is inside %s and no condition is open.'
    % glossary.TARGET,
    'These correspond to the severities used elsewhere in the console: SAFE is '
    'Info, ATTENTION is Warning, ACT NOW is Critical.')

RANGE_OPTIONS = [('1H', 1), ('6H', 6), ('24H', 24), ('7D', 168)]
RANGE_TIPS = {
    1: 'The last hour, in fine detail.',
    6: 'The last six hours.',
    24: 'The last day - the usual view for a shift handover.',
    168: 'The last seven days, for spotting a slow drift.',
}


class HeroBanner(QFrame):
    """The single most important line on the screen.

    Three rows, in the order somebody asks them: is it safe, what is wrong, and
    what should I do. The recommended action comes from the most serious open
    incident, so the banner tells the operator where to go next instead of
    leaving them to work it out from the severity colour.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setMinimumHeight(124)
        self._action = ''
        self._open_count = 0
        self._paint(t.OFF)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(18)

        # The verdict block: a drawn mark, then the word, then the colour.
        self.statusBlock = QFrame()
        self.statusBlock.setObjectName('verdict')
        self.statusBlock.setFixedWidth(168)
        self.statusBlock.setMinimumHeight(66)
        self.statusBlock.setToolTip(STATUS_HELP)
        verdict = QHBoxLayout(self.statusBlock)
        verdict.setContentsMargins(12, 10, 12, 10)
        verdict.setSpacing(10)
        verdict.addStretch()
        self.statusMark = icons.Icon('mark_offline', 20, t.OFFLINE_FG, width=2.0)
        self.statusLabel = QLabel('WAITING')
        self.statusLabel.setAlignment(Qt.AlignCenter)
        verdict.addWidget(self.statusMark, alignment=Qt.AlignVCenter)
        verdict.addWidget(self.statusLabel, alignment=Qt.AlignVCenter)
        verdict.addStretch()
        self._paint_status(t.OFF, 'WAITING', 'mark_offline', loud=False)
        row.addWidget(self.statusBlock)

        text = QVBoxLayout()
        text.setSpacing(3)
        self.headlineLabel = t.label('Connecting to the monitoring system…',
                                     size=t.SIZE_LG, weight=t.W_BOLD,
                                     spacing=-0.2)
        self.headlineLabel.setWordWrap(True)
        self.detailLabel = t.label('', size=t.SIZE_SM, color=t.TEXT_DIM)
        self.detailLabel.setWordWrap(True)
        text.addWidget(self.headlineLabel)
        text.addWidget(self.detailLabel)

        self.actionRow = QWidget()
        self.actionRow.setStyleSheet('background: transparent;')
        actionLayout = QHBoxLayout(self.actionRow)
        actionLayout.setContentsMargins(0, 2, 0, 0)
        actionLayout.setSpacing(8)
        actionLayout.addWidget(icons.Icon('arrow_right', 13, t.TEXT_DIM,
                                          width=1.6),
                               alignment=Qt.AlignTop)
        self.actionLabel = t.label('', size=t.SIZE_SM, color=t.TEXT)
        self.actionLabel.setWordWrap(True)
        actionLayout.addWidget(self.actionLabel, stretch=1)
        h.set_help(self.actionRow, 'What to do',
                   'The recommended response to the most serious problem that '
                   'is currently open.',
                   'It turns a colour into an instruction, so the screen is '
                   'useful to somebody who has never been trained on it.',
                   note='Guidance only - follow your site procedure where it '
                        'differs.')
        text.addWidget(self.actionRow)
        row.addLayout(text, stretch=1)

        counts = QVBoxLayout()
        counts.setSpacing(4)
        counts.setAlignment(Qt.AlignRight)
        self.criticalPill = w.Pill('0 critical', t.OFF, filled=False)
        h.set_help(self.criticalPill, 'Critical conditions',
                   'How many critical problems are open right now.',
                   'Critical means the stock is at risk and somebody has to '
                   'act immediately.', 'Zero.')
        self.warningPill = w.Pill('0 warnings', t.OFF, filled=False)
        h.set_help(self.warningPill, 'Warnings',
                   'How many warnings are open right now.',
                   'A warning is the early notice that lets somebody fix a '
                   'problem before the stock is affected.', 'Zero.')
        self.updatedLabel = t.label('', size=t.SIZE_XS, color=t.TEXT_MUTED,
                                    align=Qt.AlignRight)
        h.set_help(self.updatedLabel, 'Last update',
                   'When this console last heard from the unit, and how long '
                   'the monitoring has been running.',
                   'A timestamp that stops advancing means the screen is '
                   'showing you the past.',
                   'Updating every second.')
        counts.addWidget(self.criticalPill, alignment=Qt.AlignRight)
        counts.addWidget(self.warningPill, alignment=Qt.AlignRight)
        counts.addWidget(self.updatedLabel)
        row.addLayout(counts)

    def _paint(self, color):
        self.setStyleSheet(
            'QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-left: 3px solid %s; border-radius: %dpx; }'
            % (t.wash(color, 0.05, t.PANEL), t.mix(color, t.BORDER, 0.22),
               color, t.RADIUS_LG))

    def _paint_status(self, color, text, mark, loud=True):
        """The verdict block. It shouts only when there is something to shout about.

        This used to be a solid 186x76 slab of the status colour in every state,
        which meant a healthy unit put the brightest, most saturated object on
        the entire screen directly in front of the operator and held it there
        all day. A status system only works if calm is quiet: a good reading now
        gets a tinted chip, and the solid fill is kept for the warning and the
        alarm, where being impossible to ignore is the point.
        """
        self.statusMark.set_name(mark)
        self.statusMark.set_color(t.ON_ACCENT if loud else color)
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(
            'color: %s; background: transparent; border: none; '
            'font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'letter-spacing: 0.4px;'
            % (t.ON_ACCENT if loud else color, t.FONT, t.SIZE_MD,
               t.W_SEMIBOLD))
        if loud:
            self.statusBlock.setStyleSheet(
                'QFrame#verdict { background-color: %s; border: 1px solid %s; '
                'border-radius: %dpx; }' % (color, color, t.RADIUS))
        else:
            self.statusBlock.setStyleSheet(
                'QFrame#verdict { background-color: %s; border: 1px solid %s; '
                'border-radius: %dpx; }'
                % (t.wash(color, 0.14, t.PANEL),
                   t.mix(color, t.PANEL, 0.40), t.RADIUS))

    def set_action(self, text, open_count=0):
        """Called by the page with the advice from the worst open incident."""
        self._action = text or ''
        self._open_count = open_count

    def update_state(self, data):
        level = cfg.normalise_level(data.get('level', cfg.LEVEL_INFO))
        mode = data.get('mode')
        sensor_state = data.get('sensor_state', 'ONLINE')
        if level == cfg.LEVEL_INFO:
            # Saying "act now" under the word SAFE would be a contradiction, so
            # a calm verdict only ever points at the leftover paperwork.
            action = (('Conditions are normal, but %d incident%s still open on '
                       'the Incidents page.'
                       % (self._open_count, 's are' if self._open_count > 1
                          else ' is'))
                      if self._open_count else DEFAULT_ACTIONS[cfg.LEVEL_INFO])
        else:
            action = self._action or DEFAULT_ACTIONS.get(level, '')

        if not data.get('broker_connected', True):
            color, text, mark = t.CRITICAL, 'NO SIGNAL', 'mark_critical'
            headline = 'This console has lost contact with the unit'
            action = ('Check the network connection. The fridge keeps cooling, '
                      'but nobody is watching it - verify the temperature at '
                      'the unit itself.')
        elif mode == 'MAINTENANCE':
            color, text, mark = t.ACCENT, 'SERVICING', 'mark_maintenance'
            headline = 'Maintenance mode - alarms are not being raised'
            action = ('Conditions are still measured and recorded. Leave '
                      'maintenance mode as soon as servicing is finished.')
        elif sensor_state == 'OFFLINE':
            color, text, mark = t.CRITICAL, 'NO READING', 'mark_critical'
            headline = 'The main thermometer has stopped reporting'
            action = glossary.alert('SENSOR_OFFLINE').action
        elif sensor_state == 'WAITING':
            color, text, mark = t.OFF, 'WAITING', 'mark_offline'
            headline = 'Waiting for the first reading from the unit'
            action = 'Nothing to do yet - readings usually arrive within a few '\
                     'seconds of the unit starting.'
        else:
            color = t.level_color(level)
            text = STATUS_WORDS.get(level, level)
            mark = t.level_mark(level)
            headline = HEADLINES.get(level, '')

        self._paint(color)
        # Warning, critical and lost-contact are worth a solid fill. A calm
        # verdict, a maintenance window and "still waiting" are not.
        self._paint_status(color, text, mark,
                           loud=color in (t.CRITICAL, t.WARN))
        self.headlineLabel.setText(headline)

        detail = data.get('diagnosis') or ''
        if detail:
            detail = 'Assessment: ' + detail
        else:
            temperature = data.get('temperature')
            if temperature is not None:
                detail = ('Now %.1f °C inside the fridge - the safe range is %s.'
                          % (temperature, glossary.TARGET))
        if data.get('simulation_active'):
            detail += ('   ·   simulated faults are armed' if detail
                       else 'Simulated faults are armed')
        self.detailLabel.setText(detail)

        self.actionLabel.setText(action or '')
        self.actionRow.setVisible(bool(action))
        self.actionLabel.setStyleSheet(
            'color: %s; font-family: "%s"; font-size: %dpx; '
            'background: transparent; border: none;'
            % (t.TEXT if level != cfg.LEVEL_INFO else t.TEXT_DIM, t.FONT,
               t.SIZE_SM))

        counts = data.get('alert_counts') or {}
        criticals = counts.get(cfg.LEVEL_CRITICAL, 0)
        warnings = counts.get(cfg.LEVEL_WARNING, 0)
        self.criticalPill.set(
            '%d critical' % criticals,
            t.CRITICAL if criticals else t.TEXT_MUTED,
            'mark_critical' if criticals else 'mark_normal')
        self.warningPill.set(
            '%d warning%s' % (warnings, '' if warnings == 1 else 's'),
            t.WARN if warnings else t.TEXT_MUTED,
            'mark_warning' if warnings else 'mark_normal')
        self.updatedLabel.setText('updated %s   ·   up %s'
                                  % ((data.get('ts') or '')[-8:],
                                     _uptime(data.get('uptime_s'))))


def _uptime(seconds):
    if not seconds:
        return '--'
    hours, remainder = divmod(int(seconds), 3600)
    return '%dh %02dm' % (hours, remainder // 60) if hours else '%dm' % (remainder // 60)


class SystemHealthStrip(QFrame):
    """The five counts a first-time reader needs before anything else.

    Somebody opening this console for the first time does not know what a
    tachometer is or which of eleven cards matters. What they can read is a
    row of counts: is the storage in range, how many devices need looking at,
    how many have stopped reporting altogether, how many problems are open and
    whether any of this is a drill. Each one is a number, a word and a mark -
    never a colour on its own - and each says "none" rather than going blank
    when there is nothing to report.
    """

    HELP = h.Explain(
        'System health',
        'A count of everything that could need somebody: devices that are '
        'misbehaving, devices that have gone silent, and problems the system '
        'has opened a case for.',
        'The cards below answer "what is the temperature". This row answers '
        '"is anything wrong, and how much of it" - which is the question '
        'somebody walking up to the screen actually has.',
        'Storage in range, every device reporting, nothing open, no drill '
        'running.')

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())

        root = QVBoxLayout(self)
        root.setContentsMargins(t.SPACE_MD, 11, t.SPACE_MD, 12)
        root.setSpacing(t.SPACE_SM)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(t.title('System health'))
        head.addWidget(self.HELP.dot(size=12))
        head.addStretch()
        self.summaryLabel = t.label('', size=t.SIZE_XS, color=t.TEXT_MUTED)
        head.addWidget(self.summaryLabel)
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(t.SPACE_SM)
        self.items = {}
        for key, caption_text, tip in (
                ('storage', 'Storage conditions',
                 h.Explain('Storage conditions',
                           'Whether the temperature and humidity inside the '
                           'cabinet are within the limits set on the Settings '
                           'page.',
                           'It is the thing the whole unit exists to protect.',
                           'Normal.')),
                ('attention', 'Devices needing attention',
                 h.Explain('Devices needing attention',
                           'Devices that are still reporting but are either '
                           'outside their expected range or contradicting what '
                           'the equipment was told to do.',
                           'These are the ones a person can still fix before '
                           'the stock is affected.',
                           'None.')),
                ('offline', 'Devices offline',
                 h.Explain('Devices offline',
                           'Devices that have stopped reporting altogether.',
                           'A silent device is not a healthy one - whatever it '
                           'was checking is no longer being checked, and the '
                           'screen cannot tell you what it would have said.',
                           'None.')),
                ('incidents', 'Open incidents',
                 h.Explain('Open incidents',
                           'Problems the system has opened a case for and '
                           'nobody has closed yet.',
                           'The size of the queue waiting for a person. Each '
                           'one carries the recommended action on the '
                           'Incidents page.',
                           'None.')),
                ('drill', 'Simulation',
                 h.Explain('Simulation',
                           'Whether any fault has been armed on purpose from '
                           'the Simulations page.',
                           'Anything a drill causes is labelled SIMULATED so '
                           'it is never mistaken for a real failure - but a '
                           'drill left armed keeps raising alarms.',
                           'Not running.'))):
            item = _HealthItem(caption_text, tip)
            self.items[key] = item
            row.addWidget(item, stretch=1)
        root.addLayout(row)

    def update_state(self, data, open_incidents=0):
        level = cfg.normalise_level(data.get('level', cfg.LEVEL_INFO))
        sensor_state = data.get('sensor_state', 'ONLINE')

        if sensor_state in ('OFFLINE', 'WAITING'):
            self.items['storage'].set(
                stat.OFFLINE,
                'No reading' if sensor_state == 'OFFLINE' else 'Waiting')
        else:
            state = stat.from_level(level)
            temperature = data.get('temperature')
            self.items['storage'].set(
                state, '--' if temperature is None
                else '%.1f °C' % temperature)

        health = data.get('device_health') or {}
        attention = sum(1 for v in health.values()
                        if v in ('DEGRADED', 'FAULT'))
        offline = sum(1 for v in health.values() if v == 'OFFLINE')
        total = len(health) or len(registry.DEVICES)

        self.items['attention'].set(
            stat.NORMAL if not attention else
            (stat.CRITICAL if any(v == 'FAULT' for v in health.values())
             else stat.WARNING),
            'None' if not attention else '%d of %d' % (attention, total))
        self.items['offline'].set(
            stat.NORMAL if not offline else stat.OFFLINE,
            'None' if not offline else '%d of %d' % (offline, total))
        self.items['incidents'].set(
            stat.NORMAL if not open_incidents else stat.WARNING,
            'None' if not open_incidents else '%d open' % open_incidents)

        faults = data.get('simulated_faults') or {}
        armed = sum(len(v) for v in faults.values())
        self.items['drill'].set(
            stat.SIMULATED if armed else stat.NORMAL,
            '%d armed' % armed if armed else 'Not running')

        reporting = total - offline
        self.summaryLabel.setText('%d of %d devices reporting'
                                  % (reporting, total))


class _HealthItem(QFrame):
    """One count in the strip: a value, its state and what it is counting."""

    def __init__(self, caption_text, help_entry):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style(background=t.PANEL_ALT,
                                         radius=t.RADIUS))
        self.setMinimumWidth(124)
        help_entry.apply(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(5)

        valueRow = QHBoxLayout()
        valueRow.setContentsMargins(0, 0, 0, 0)
        valueRow.setSpacing(7)
        self.mark = icons.Icon('mark_normal', 13, t.OK, width=1.5)
        self.valueLabel = t.label('--', size=t.SIZE_MD, bold=True)
        valueRow.addWidget(self.mark, alignment=Qt.AlignVCenter)
        valueRow.addWidget(self.valueLabel, stretch=1)
        layout.addLayout(valueRow)

        self.stateLabel = t.label('', size=t.SIZE_CAPTION, color=t.TEXT_MUTED,
                                  bold=True, spacing=0.6)
        layout.addWidget(self.stateLabel)
        caption_label = t.label(caption_text, size=t.SIZE_XS,
                                color=t.TEXT_MUTED)
        caption_label.setWordWrap(True)
        layout.addWidget(caption_label)

    def set(self, state, value):
        entry = stat.get(state)
        self.mark.set_name(entry.mark)
        self.mark.set_color(entry.color)
        self.valueLabel.setText(str(value))
        self.valueLabel.setStyleSheet(
            'color: %s; background: transparent; border: none; '
            'font-family: "%s"; font-size: %dpx; font-weight: 600;'
            % (entry.color if state != stat.NORMAL else t.TEXT, t.FONT,
               t.SIZE_MD))
        self.stateLabel.setText(entry.label)
        self.stateLabel.setStyleSheet(
            'color: %s; background: transparent; border: none; '
            'font-family: "%s"; font-size: %dpx; font-weight: 700; '
            'letter-spacing: 0.6px;' % (entry.color, t.FONT, t.SIZE_CAPTION))


class EnvironmentCard(w.Card):
    """Door, power and link - the three states that are not numbers."""

    HELP = h.Explain(
        'Unit status',
        'The four things about the fridge that are a state rather than a '
        'measurement: is it shut, is it powered, is it being heard, and is it '
        'in service or being maintained.',
        'Each one can ruin the stock on its own, whatever the temperature '
        'currently reads.',
        'Door closed, on mains power, connected, and in Monitoring mode.')

    def __init__(self):
        super().__init__('Unit status', help=self.HELP)
        grid = QGridLayout()
        grid.setSpacing(9)

        self.doorPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.powerPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.linkPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.modePill = w.Pill('--', t.OFF, filled=False, size=12)

        # Wrapped: these sit in the narrow right-hand column, and left on one
        # line "9 of 11 devices reporting" set a floor for the whole page.
        # Wrapping lets the column give its width to the chips instead, which
        # cannot shrink without losing letters.
        self.doorNote = t.label('', size=t.SIZE_CAPTION, color=t.TEXT_MUTED)
        self.powerNote = t.label('', size=t.SIZE_CAPTION, color=t.TEXT_MUTED)
        self.linkNote = t.label('', size=t.SIZE_CAPTION, color=t.TEXT_MUTED)
        self.modeNote = t.label('', size=t.SIZE_CAPTION, color=t.TEXT_MUTED)
        for note in (self.doorNote, self.powerNote, self.linkNote,
                     self.modeNote):
            note.setWordWrap(True)
            note.setMinimumWidth(64)

        rows = (
            ('Door', self.doorPill, self.doorNote, glossary.device('door')),
            ('Power', self.powerPill, self.powerNote, glossary.device('power')),
            ('Connection', self.linkPill, self.linkNote,
             glossary.term('connection')),
            ('Mode', self.modePill, self.modeNote, glossary.term('maintenance')),
        )
        for row, (name, pill, note, explain) in enumerate(rows):
            label = t.label(name, size=11, color=t.TEXT_DIM)
            if explain is not None:
                explain.apply(label)
                explain.apply(pill)
            grid.addWidget(label, row, 0)
            grid.addWidget(pill, row, 1, alignment=Qt.AlignRight)
            grid.addWidget(note, row, 2)
        grid.setColumnStretch(2, 1)
        self.add_layout(grid)

    def update_state(self, data):
        door = data.get('door', '--')
        seconds = int(data.get('door_seconds') or 0)
        if door == 'OPEN':
            color = (t.CRITICAL if seconds >= cfg.DOOR_ALARM_SECONDS else
                     t.WARN if seconds >= cfg.DOOR_WARNING_SECONDS else t.ACCENT)
            self.doorPill.set('Open', color, 'mark_warning',
                              filled=color is not t.ACCENT)
            self.doorNote.setText('open %d s  ·  alarm at %d s'
                                  % (seconds, cfg.DOOR_ALARM_SECONDS))
        else:
            self.doorPill.set('Closed', t.OK, 'mark_normal', filled=False)
            operator = data.get('operator')
            self.doorNote.setText('shut' if not operator
                                  else 'last opened by %s' % operator)

        power = data.get('power', '--')
        battery = float(data.get('battery') or 0)
        if power == 'MAINS':
            self.powerPill.set('Mains', t.OK, 'mark_normal', filled=False)
        else:
            self.powerPill.set('Battery',
                               t.CRITICAL if battery <= cfg.BATTERY_ALARM_PERCENT
                               else t.WARN, 'mark_warning', filled=True)
        self.powerNote.setText('battery at %.0f %%' % battery)

        connected = data.get('broker_connected', True)
        self.linkPill.set('Online' if connected else 'Offline',
                          t.OK if connected else t.CRITICAL,
                          'mark_normal' if connected else 'mark_critical',
                          filled=not connected)
        self.linkPill.setToolTip(stat.tooltip(
            stat.NORMAL if connected else stat.CRITICAL,
            'Connection to the broker'))
        counts = data.get('device_counts') or {}
        online = sum(v for k, v in counts.items() if k != 'OFFLINE')
        self.linkNote.setText('%d of %d devices reporting'
                              % (online, sum(counts.values()) or 0))

        mode = data.get('mode', '--')
        self.modePill.set(mode.title(),
                          t.ACCENT if mode == 'MAINTENANCE' else t.OK,
                          'mark_maintenance' if mode == 'MAINTENANCE'
                          else 'mark_normal', filled=False)
        operator = data.get('mode_operator')
        self.modeNote.setText(('set by %s' % operator) if operator
                              else 'normal operation')


class DashboardPage(Page):

    title = 'Dashboard'
    subtitle = 'Live storage conditions'

    def __init__(self, console):
        super().__init__(console)
        self._range_hours = 24
        self._last_series_load = 0.0
        self._open_incidents = 0
        self._last_data = {}

        outer = page_layout(self)
        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)

        self.hero = HeroBanner()
        body.addWidget(self.hero)

        self.healthStrip = SystemHealthStrip()
        body.addWidget(self.healthStrip)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addLayout(self._build_main_column(), stretch=5)
        columns.addLayout(self._build_side_column(), stretch=2)
        body.addLayout(columns)

        outer.addWidget(scrollable(inner))

    # -- construction ------------------------------------------------------
    def _build_main_column(self):
        column = QVBoxLayout()
        column.setSpacing(12)

        gauges = QHBoxLayout()
        gauges.setSpacing(12)
        self.tempGauge = charts.ArcGauge(
            'Fridge temperature', ' °C', cfg.TEMP_GAUGE_MIN, cfg.TEMP_GAUGE_MAX,
            cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX,
            cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX)
        glossary.metric('temperature').apply(
            self.tempGauge,
            note='The green arc is the safe range; the red marks are the hard '
                 'limits. Measured by the main thermometer.')
        self.humGauge = charts.ArcGauge(
            'Air humidity', ' %', cfg.HUM_GAUGE_MIN, cfg.HUM_GAUGE_MAX,
            cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX, 0.0, cfg.HUM_ALARM_MAX)
        glossary.metric('humidity').apply(
            self.humGauge,
            note='The green arc is the safe range. Measured by the same probe '
                 'as the temperature.')
        gauges.addWidget(self.tempGauge)
        gauges.addWidget(self.humGauge)
        column.addLayout(gauges)

        column.addWidget(w.SectionTitle(
            'Supporting sensors',
            'the readings that catch a lying thermometer or a dead motor',
            help=h.Explain(
                'Supporting sensors',
                'Five extra sensors that check the system itself rather than '
                'the storage conditions.',
                'The temperature alone cannot tell you whether it can be '
                'trusted, or why it is wrong. These can: a second probe, the '
                'room, the motor current, the fan speed and the badge reader.',
                'All five reading normally.')))

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.probeTile = MetricTile('Backup thermometer', ' °C',
                                    help=glossary.device('temp_b'))
        self.ambientTile = MetricTile('Room temperature', ' °C',
                                      help=glossary.device('ambient'))
        self.currentTile = MetricTile('Cooling motor', ' A', fmt='%.2f',
                                      help=glossary.device('current'))
        self.rpmTile = MetricTile('Fan speed', ' rpm', fmt='%.0f',
                                  help=glossary.device('fan_rpm'))
        self.operatorTile = w.StatTile('Last opened by', value_size=13,
                                       mono=False,
                                       help=glossary.metric('operator'))
        for tile in (self.probeTile, self.ambientTile, self.currentTile,
                     self.rpmTile, self.operatorTile):
            tiles.addWidget(tile)
        column.addLayout(tiles)

        column.addWidget(w.SectionTitle(
            'Equipment',
            'what each part was told to do, and what it is really doing',
            help=h.Explain(
                'Equipment',
                'The three switched parts of the unit: the cooling motor, the '
                'circulation fan and the alarm sounder.',
                'A switch reporting ON only proves it was asked. Each card '
                'puts the command next to an independent measurement, which is '
                'how a welded relay or a seized motor is caught.',
                'Commanded and measured agree on every card.')))

        devices = QHBoxLayout()
        devices.setSpacing(12)
        self.compressorCard = ActuatorCard('compressor', t.ACCENT)
        self.fanCard = ActuatorCard('fan', t.OK)
        self.sirenCard = ActuatorCard('siren', t.CRITICAL, measured=False)
        for card in (self.compressorCard, self.fanCard, self.sirenCard):
            devices.addWidget(card)
        column.addLayout(devices)

        self.rangeControl = w.SegmentedControl(RANGE_OPTIONS, 24,
                                               tips=RANGE_TIPS)
        self.rangeControl.changed.connect(self._change_range)
        chartCard = w.Card(
            'Temperature history', 'Green band = the safe range',
            actions=[self.rangeControl],
            help=h.Explain(
                'Temperature history',
                'The last few hours of temperature: the main thermometer in '
                'blue, the backup in purple and the storeroom in grey.',
                'A single reading cannot tell you whether things are getting '
                'better or worse. The shape of the line can, and two probes '
                'drawn together make a drifting one obvious.',
                'A gentle saw-tooth inside the green band as the cooling '
                'cycles on and off.',
                note='Hover anywhere on the chart to read the exact values at '
                     'that moment.'))
        self.tempChart = charts.TimeSeriesChart(
            [charts.Trace('temp_avg', 'Main probe', t.ACCENT, fill=True, unit=' °C'),
             charts.Trace('temp_b_avg', 'Backup probe', t.SIM, width=1.4, unit=' °C'),
             charts.Trace('ambient_avg', 'Room', t.TEXT_MUTED, width=1.2, unit=' °C')],
            cfg.TEMP_GAUGE_MIN, cfg.TEMP_GAUGE_MAX,
            bands=[charts.Band(cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX, t.OK)],
            thresholds=[charts.Threshold(cfg.TEMP_ALARM_MIN, t.CRITICAL),
                        charts.Threshold(cfg.TEMP_ALARM_MAX, t.CRITICAL)],
            unit=' °C', minimum_height=230)
        h.set_tip(self.tempChart,
                  'Hover to read the exact values at any moment.')
        chartCard.add(self.tempChart, stretch=1)
        column.addWidget(chartCard, stretch=1)
        return column

    def _build_side_column(self):
        """The narrow right-hand column: unit state, open work, live log.

        The incident cards and the log are given an explicit floor and told to
        ignore their own natural width: a compact incident card wants about
        300 px for its headline and its two buttons, and letting three of those
        set the column width pushed the whole page past the console's minimum
        window size into a horizontal scrollbar. The unit-status card is left
        alone - it holds fixed-size status chips, and squeezing it clipped
        "BATTERY" down to "ATTER".
        """
        column = QVBoxLayout()
        column.setSpacing(12)

        self.environment = EnvironmentCard()
        column.addWidget(self.environment)

        self.incidentsCard = w.Card(
            'Needs attention', 'Most serious first',
            help=glossary.term('incident'))
        self.incidentsEmpty = w.EmptyState(
            'shield', 'Nothing needs attention',
            'Every condition the system checks is currently normal. Anything '
            'that changes appears here, most serious first.', color=t.OK)
        self.incidentsCard.add(self.incidentsEmpty)
        self.incidentsBox = QVBoxLayout()
        self.incidentsBox.setSpacing(7)
        self.incidentsCard.add_layout(self.incidentsBox)
        self._shrinkable(self.incidentsCard)
        column.addWidget(self.incidentsCard)

        self.feed = EventFeed()
        self.feed.setMinimumHeight(260)
        self._shrinkable(self.feed)
        column.addWidget(self.feed, stretch=1)
        return column

    @staticmethod
    def _shrinkable(widget, minimum=208):
        widget.setMinimumWidth(minimum)
        widget.setSizePolicy(QSizePolicy.Ignored, widget.sizePolicy().verticalPolicy())

    # -- live state --------------------------------------------------------
    def apply_status(self, data):
        self._last_data = data
        self.hero.update_state(data)
        self.healthStrip.update_state(data, self._open_incidents)
        self.environment.update_state(data)

        stale = data.get('sensor_state') == 'OFFLINE'
        self.tempGauge.set_value(data.get('temperature'), stale)
        self.humGauge.set_value(data.get('humidity'), stale)

        delta = data.get('probe_delta')
        probe_b = data.get('temperature_b')
        if probe_b is None:
            self.probeTile.set_metric(None)
        else:
            disagrees = delta is not None and delta > cfg.PROBE_DISAGREE_C
            self.probeTile.set_metric(
                probe_b, t.CRITICAL if disagrees else t.OK,
                suffix='' if delta is None else '  Δ%.1f' % delta,
                state=stat.CRITICAL if disagrees else stat.NORMAL)

        ambient = data.get('ambient')
        hot = (ambient or 0) >= cfg.AMBIENT_WARNING_C
        self.ambientTile.set_metric(ambient, t.WARN if hot else t.TEXT,
                                    state=stat.WARNING if hot else stat.NORMAL)

        self._update_actuators(data)

        operator = data.get('operator')
        if not operator:
            self.operatorTile.set_value('—', t.TEXT_MUTED)
        elif operator == cfg.UNKNOWN_OPERATOR:
            self.operatorTile.set_value('No badge', t.WARN)
        else:
            self.operatorTile.set_value(operator, t.TEXT)

    def _update_actuators(self, data):
        """Command beside measurement, with the mismatch said in plain words."""
        health = data.get('device_health') or {}
        current = data.get('compressor_current')
        commanded_on = data.get('compressor') == 'ON'
        self.compressorCard.set_state(commanded_on)
        self.compressorCard.set_health(health.get('compressor', 'OFFLINE'))
        if current is None:
            self.compressorCard.set_measurement('--', t.TEXT_MUTED,
                                                'no reading from the sensor')
        else:
            drawing = current >= cfg.CURRENT_RUNNING_MIN_A
            mismatch = commanded_on != drawing
            overload = current > cfg.CURRENT_OVERLOAD_A
            if mismatch:
                color = t.CRITICAL
                caption = ('switched on but not running' if commanded_on
                           else 'switched off but still running')
            elif overload:
                color, caption = t.CRITICAL, 'drawing far too much power'
            else:
                color = t.OK if drawing else t.TEXT_MUTED
                caption = 'motor is running' if drawing else 'motor is off'
            self.compressorCard.set_measurement('%.2f A' % current, color, caption)

        rpm = data.get('fan_rpm')
        fan_on = data.get('fan') == 'ON'
        self.fanCard.set_state(fan_on)
        self.fanCard.set_health(health.get('fan', 'OFFLINE'))
        if rpm is None:
            self.fanCard.set_measurement('--', t.TEXT_MUTED,
                                         'no reading from the sensor')
        else:
            turning = rpm >= cfg.FAN_RPM_MIN
            if fan_on != turning:
                color = t.CRITICAL
                caption = ('switched on but not turning' if fan_on
                           else 'switched off but still turning')
            elif turning and rpm < cfg.FAN_RPM_DEGRADED:
                color, caption = t.WARN, 'turning too slowly'
            else:
                color = t.OK if turning else t.TEXT_MUTED
                caption = 'fan is turning' if turning else 'fan is stopped'
            self.fanCard.set_measurement('%d rpm' % int(rpm), color, caption)

        self.sirenCard.set_state(data.get('siren') == 'ON')
        self.sirenCard.set_health(health.get('siren', 'OFFLINE'))

        self.currentTile.set_metric(current)
        self.rpmTile.set_metric(rpm)

    def apply_alert(self, record):
        self.feed.add_event(record.get('level'), record.get('code'),
                            record.get('message'), record.get('ts'),
                            record.get('operator'), record.get('simulated'))
        self.refresh_incidents()

    # -- database-backed content -------------------------------------------
    def on_shown(self):
        self.refresh_incidents()
        self.reload_series()

    def tick(self):
        pass

    def _change_range(self, hours):
        self._range_hours = hours
        self.tempChart.set_loading()
        self.reload_series()

    def reload_series(self):
        try:
            rows = db.series(hours=self._range_hours, points=340)
        except Exception as error:
            print('dashboard: could not load history:', error)
            rows = []
        self.tempChart.set_rows(rows)

    def refresh_incidents(self):
        try:
            incidents = db.active_incidents()
        except Exception as error:
            print('dashboard: could not load incidents:', error)
            return

        w.clear_layout(self.incidentsBox)
        self._open_incidents = len(incidents)
        self.hero.set_action(self._recommended_action(incidents),
                             len(incidents))
        if self._last_data:
            self.healthStrip.update_state(self._last_data, len(incidents))

        if not incidents:
            self.incidentsEmpty.show()
            return
        self.incidentsEmpty.hide()

        # Most serious first: an operator reading top-down should meet the
        # thing that matters most before anything else.
        ordered = sorted(
            incidents,
            key=lambda row: -cfg.LEVEL_ORDER.get(
                cfg.normalise_level(row.get('severity')), 0))

        for incident in ordered[:4]:
            card = IncidentCard(incident, compact=True)
            self._shrinkable(card, 190)
            card.acknowledged.connect(self.console.acknowledge_incident)
            card.resolved.connect(self.console.resolve_incident)
            self.incidentsBox.addWidget(card)
        if len(ordered) > 4:
            more = t.label('+ %d more on the Incidents page' % (len(ordered) - 4),
                           size=t.SIZE_XS, color=t.TEXT_MUTED)
            self.incidentsBox.addWidget(more)

    @staticmethod
    def _recommended_action(incidents):
        """The advice for the most serious open incident, for the banner."""
        if not incidents:
            return ''
        worst = max(incidents,
                    key=lambda row: cfg.LEVEL_ORDER.get(
                        cfg.normalise_level(row.get('severity')), 0))
        return glossary.alert(worst.get('code')).action
