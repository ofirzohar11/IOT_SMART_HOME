"""Operator dashboard.

The screen is arranged to answer six questions in the order an operator asks
them: is the stock safe, what is the temperature, is anything wrong, are the
machines doing what they were told, is the data trustworthy, and what happened
recently. Everything above the fold is current state; history and detail live
further down and on the other pages.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from database import db
from gui import charts
from gui.components import ActuatorCard, EventFeed, IncidentCard, MetricTile
from gui.pages.base import Page, page_layout, scrollable
from ui import theme as t
from ui import widgets as w

HEADLINES = {
    cfg.LEVEL_INFO: 'Storage conditions are within specification',
    cfg.LEVEL_WARNING: 'Attention required - conditions are drifting',
    cfg.LEVEL_CRITICAL: 'Immediate action required - stock is at risk',
}

RANGE_OPTIONS = [('1H', 1), ('6H', 6), ('24H', 24), ('7D', 168)]


class HeroBanner(QFrame):
    """The single most important line on the screen."""

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setFixedHeight(96)
        self._paint(t.OFF)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(18)

        self.statusLabel = QLabel('WAITING')
        self.statusLabel.setAlignment(Qt.AlignCenter)
        self.statusLabel.setFixedWidth(178)
        self._paint_status(t.OFF, 'WAITING', '○')
        row.addWidget(self.statusLabel)

        text = QVBoxLayout()
        text.setSpacing(3)
        self.headlineLabel = t.label('Connecting to the monitoring system…',
                                     size=16, bold=True)
        self.detailLabel = t.label('', size=12, color=t.TEXT_DIM)
        self.detailLabel.setWordWrap(True)
        text.addWidget(self.headlineLabel)
        text.addWidget(self.detailLabel)
        row.addLayout(text, stretch=1)

        counts = QVBoxLayout()
        counts.setSpacing(4)
        counts.setAlignment(Qt.AlignRight)
        self.criticalPill = w.Pill('0 critical', t.OFF, filled=False)
        self.warningPill = w.Pill('0 warnings', t.OFF, filled=False)
        self.updatedLabel = t.label('', size=10, color=t.TEXT_MUTED,
                                    align=Qt.AlignRight)
        counts.addWidget(self.criticalPill, alignment=Qt.AlignRight)
        counts.addWidget(self.warningPill, alignment=Qt.AlignRight)
        counts.addWidget(self.updatedLabel)
        row.addLayout(counts)

    def _paint(self, color):
        self.setStyleSheet(
            'QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-left: 4px solid %s; border-radius: %dpx; }'
            % (t.PANEL, t.BORDER, color, t.RADIUS_LG))

    def _paint_status(self, color, text, glyph):
        self.statusLabel.setText('%s  %s' % (glyph, text))
        self.statusLabel.setStyleSheet(
            'color: #08111F; background-color: %s; border: none; '
            'border-radius: %dpx; font-family: %s; font-size: 16px; '
            'font-weight: 700; padding: 15px 8px;' % (color, t.RADIUS, t.FONT))

    def update_state(self, data):
        level = cfg.normalise_level(data.get('level', cfg.LEVEL_INFO))
        mode = data.get('mode')
        sensor_state = data.get('sensor_state', 'ONLINE')

        if not data.get('broker_connected', True):
            color, text, glyph = t.CRITICAL, 'LINK DOWN', '■'
            headline = 'No connection to the message broker'
        elif mode == 'MAINTENANCE':
            color, text, glyph = t.ACCENT, 'MAINTENANCE', '⚙'
            headline = 'Maintenance mode - alarms are not escalating'
        elif sensor_state == 'OFFLINE':
            color, text, glyph = t.CRITICAL, 'SENSOR DOWN', '■'
            headline = 'The primary probe has stopped reporting'
        elif sensor_state == 'WAITING':
            color, text, glyph = t.OFF, 'WAITING', '○'
            headline = 'Waiting for the first telemetry'
        else:
            color = t.level_color(level)
            text = {'INFO': 'NORMAL', 'WARNING': 'WARNING',
                    'CRITICAL': 'CRITICAL'}.get(level, level)
            glyph = t.level_glyph(level)
            headline = HEADLINES.get(level, '')

        self._paint(color)
        self._paint_status(color, text, glyph)
        self.headlineLabel.setText(headline)

        detail = data.get('diagnosis') or ''
        if not detail:
            temperature = data.get('temperature')
            if temperature is not None:
                detail = ('Cabinet at %.1f °C, target %.0f-%.0f °C'
                          % (temperature, cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX))
        if data.get('simulation_active'):
            detail += ('   ·   simulated faults are armed' if detail
                       else 'Simulated faults are armed')
        self.detailLabel.setText(detail)

        counts = data.get('alert_counts') or {}
        criticals = counts.get(cfg.LEVEL_CRITICAL, 0)
        warnings = counts.get(cfg.LEVEL_WARNING, 0)
        self.criticalPill.set('%d critical' % criticals,
                              t.CRITICAL if criticals else t.TEXT_MUTED, '■')
        self.warningPill.set('%d warnings' % warnings,
                             t.WARN if warnings else t.TEXT_MUTED, '▲')
        self.updatedLabel.setText('updated %s   ·   up %s'
                                  % ((data.get('ts') or '')[-8:],
                                     _uptime(data.get('uptime_s'))))


def _uptime(seconds):
    if not seconds:
        return '--'
    hours, remainder = divmod(int(seconds), 3600)
    return '%dh %02dm' % (hours, remainder // 60) if hours else '%dm' % (remainder // 60)


class EnvironmentCard(w.Card):
    """Door, power and link - the three states that are not numbers."""

    def __init__(self):
        super().__init__('Environment')
        grid = QGridLayout()
        grid.setSpacing(9)

        self.doorPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.powerPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.linkPill = w.Pill('--', t.OFF, filled=False, size=12)
        self.modePill = w.Pill('--', t.OFF, filled=False, size=12)

        self.doorNote = t.label('', size=10, color=t.TEXT_MUTED)
        self.powerNote = t.label('', size=10, color=t.TEXT_MUTED)
        self.linkNote = t.label('', size=10, color=t.TEXT_MUTED)
        self.modeNote = t.label('', size=10, color=t.TEXT_MUTED)

        for row, (name, pill, note) in enumerate((
                ('Door', self.doorPill, self.doorNote),
                ('Power', self.powerPill, self.powerNote),
                ('Connectivity', self.linkPill, self.linkNote),
                ('Mode', self.modePill, self.modeNote))):
            grid.addWidget(t.label(name, size=11, color=t.TEXT_DIM), row, 0)
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
            self.doorPill.set('OPEN', color, '▲')
            self.doorNote.setText('%d s  ·  critical at %d s'
                                  % (seconds, cfg.DOOR_ALARM_SECONDS))
        else:
            self.doorPill.set('CLOSED', t.OK, '●')
            operator = data.get('operator')
            self.doorNote.setText('sealed' if not operator else 'last: %s' % operator)

        power = data.get('power', '--')
        battery = float(data.get('battery') or 0)
        if power == 'MAINS':
            self.powerPill.set('MAINS', t.OK, '●')
        else:
            self.powerPill.set('BATTERY',
                               t.CRITICAL if battery <= cfg.BATTERY_ALARM_PERCENT
                               else t.WARN, '▲')
        self.powerNote.setText('battery %.0f %%' % battery)

        connected = data.get('broker_connected', True)
        self.linkPill.set('ONLINE' if connected else 'OFFLINE',
                          t.OK if connected else t.CRITICAL,
                          '●' if connected else '■')
        counts = data.get('device_counts') or {}
        online = sum(v for k, v in counts.items() if k != 'OFFLINE')
        self.linkNote.setText('%d of %d devices reporting'
                              % (online, sum(counts.values()) or 0))

        mode = data.get('mode', '--')
        self.modePill.set(mode, t.ACCENT if mode == 'MAINTENANCE' else t.OK,
                          '⚙' if mode == 'MAINTENANCE' else '●')
        operator = data.get('mode_operator')
        self.modeNote.setText(('by %s' % operator) if operator else 'normal operation')


class DashboardPage(Page):

    title = 'Dashboard'
    subtitle = 'Live storage conditions'

    def __init__(self, console):
        super().__init__(console)
        self._range_hours = 24
        self._last_series_load = 0.0

        outer = page_layout(self)
        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)

        self.hero = HeroBanner()
        body.addWidget(self.hero)

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
            'Cabinet temperature', ' °C', cfg.TEMP_GAUGE_MIN, cfg.TEMP_GAUGE_MAX,
            cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX,
            cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX)
        self.humGauge = charts.ArcGauge(
            'Humidity', ' %', cfg.HUM_GAUGE_MIN, cfg.HUM_GAUGE_MAX,
            cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX, 0.0, cfg.HUM_ALARM_MAX)
        gauges.addWidget(self.tempGauge)
        gauges.addWidget(self.humGauge)
        column.addLayout(gauges)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.probeTile = MetricTile('probe B', ' °C')
        self.ambientTile = MetricTile('storeroom', ' °C')
        self.currentTile = MetricTile('compressor draw', ' A', fmt='%.2f')
        self.rpmTile = MetricTile('fan speed', ' rpm', fmt='%.0f')
        self.operatorTile = w.StatTile('last opened by', value_size=13, mono=False)
        for tile in (self.probeTile, self.ambientTile, self.currentTile,
                     self.rpmTile, self.operatorTile):
            tiles.addWidget(tile)
        column.addLayout(tiles)

        devices = QHBoxLayout()
        devices.setSpacing(12)
        self.compressorCard = ActuatorCard('compressor', t.ACCENT)
        self.fanCard = ActuatorCard('fan', t.OK)
        self.sirenCard = ActuatorCard('siren', t.CRITICAL, measured=False)
        for card in (self.compressorCard, self.fanCard, self.sirenCard):
            devices.addWidget(card)
        column.addLayout(devices)

        self.rangeControl = w.SegmentedControl(RANGE_OPTIONS, 24)
        self.rangeControl.changed.connect(self._change_range)
        chartCard = w.Card('Temperature history', actions=[self.rangeControl])
        self.tempChart = charts.TimeSeriesChart(
            [charts.Trace('temp_avg', 'Probe A', t.ACCENT, fill=True, unit=' °C'),
             charts.Trace('temp_b_avg', 'Probe B', t.SIM, width=1.4, unit=' °C'),
             charts.Trace('ambient_avg', 'Room', t.TEXT_MUTED, width=1.2, unit=' °C')],
            cfg.TEMP_GAUGE_MIN, cfg.TEMP_GAUGE_MAX,
            bands=[charts.Band(cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX, t.OK)],
            thresholds=[charts.Threshold(cfg.TEMP_ALARM_MIN, t.CRITICAL),
                        charts.Threshold(cfg.TEMP_ALARM_MAX, t.CRITICAL)],
            unit=' °C', minimum_height=230)
        chartCard.add(self.tempChart, stretch=1)
        column.addWidget(chartCard, stretch=1)
        return column

    def _build_side_column(self):
        column = QVBoxLayout()
        column.setSpacing(12)

        self.environment = EnvironmentCard()
        column.addWidget(self.environment)

        self.incidentsCard = w.Card('Active incidents')
        self.incidentsEmpty = w.EmptyState('✓', 'Nothing active',
                                           'Conditions are within limits.')
        self.incidentsCard.add(self.incidentsEmpty)
        self.incidentsBox = QVBoxLayout()
        self.incidentsBox.setSpacing(7)
        self.incidentsCard.add_layout(self.incidentsBox)
        column.addWidget(self.incidentsCard)

        self.feed = EventFeed()
        self.feed.setMinimumHeight(260)
        column.addWidget(self.feed, stretch=1)
        return column

    # -- live state --------------------------------------------------------
    def apply_status(self, data):
        self.hero.update_state(data)
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
                suffix='' if delta is None else '  Δ%.1f' % delta)

        ambient = data.get('ambient')
        self.ambientTile.set_metric(
            ambient, t.WARN if (ambient or 0) >= cfg.AMBIENT_WARNING_C else t.TEXT)

        self._update_actuators(data)

        operator = data.get('operator')
        if not operator:
            self.operatorTile.set_value('—', t.TEXT_MUTED)
        elif operator == cfg.UNKNOWN_OPERATOR:
            self.operatorTile.set_value('no badge', t.WARN)
        else:
            self.operatorTile.set_value(operator, t.TEXT)

    def _update_actuators(self, data):
        health = data.get('device_health') or {}
        current = data.get('compressor_current')
        commanded_on = data.get('compressor') == 'ON'
        self.compressorCard.set_state(commanded_on)
        self.compressorCard.set_health(health.get('compressor', 'OFFLINE'))
        if current is None:
            self.compressorCard.set_measurement('--', t.TEXT_MUTED, 'no current sensor')
        else:
            drawing = current >= cfg.CURRENT_RUNNING_MIN_A
            mismatch = commanded_on != drawing
            overload = current > cfg.CURRENT_OVERLOAD_A
            color = t.CRITICAL if (mismatch or overload) else (
                t.OK if drawing else t.TEXT_MUTED)
            caption = 'contradicts the command' if mismatch else 'measured draw'
            self.compressorCard.set_measurement('%.2f A' % current, color, caption)

        rpm = data.get('fan_rpm')
        fan_on = data.get('fan') == 'ON'
        self.fanCard.set_state(fan_on)
        self.fanCard.set_health(health.get('fan', 'OFFLINE'))
        if rpm is None:
            self.fanCard.set_measurement('--', t.TEXT_MUTED, 'no tachometer')
        else:
            turning = rpm >= cfg.FAN_RPM_MIN
            if fan_on != turning:
                color, caption = t.CRITICAL, 'contradicts the command'
            elif turning and rpm < cfg.FAN_RPM_DEGRADED:
                color, caption = t.WARN, 'below the minimum'
            else:
                color = t.OK if turning else t.TEXT_MUTED
                caption = 'measured speed'
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

        if not incidents:
            self.incidentsEmpty.show()
            return
        self.incidentsEmpty.hide()

        for incident in incidents[:4]:
            card = IncidentCard(incident, compact=True)
            card.acknowledged.connect(self.console.acknowledge_incident)
            card.resolved.connect(self.console.resolve_incident)
            self.incidentsBox.addWidget(card)
        if len(incidents) > 4:
            self.incidentsBox.addWidget(
                t.label('+ %d more on the Incidents page' % (len(incidents) - 4),
                        size=10, color=t.TEXT_MUTED))
