"""History and reports: the stored audit trail behind the live screens."""

import os
from datetime import datetime

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                             QHeaderView, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from config import mqtt_init as cfg
from database import db
from gui import charts, glossary
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import theme as t
from ui import widgets as w

RANGE_OPTIONS = [('1H', 1), ('6H', 6), ('24H', 24), ('7D', 168)]

RANGE_TIPS = {
    1: 'The last hour.',
    6: 'The last six hours.',
    24: 'The last day - the usual view for a shift handover.',
    168: 'The last seven days.',
}

# A table header has room for two words, so the rest of the sentence lives in
# the tooltip on each heading.
READING_COLUMNS = [
    ('Time', 'When this reading was stored.'),
    ('Main °C', 'Temperature from the main thermometer inside the fridge. '
                'Shown amber when outside %s.' % glossary.TARGET),
    ('Backup °C', 'Temperature from the second, independent thermometer.'),
    ('Room °C', 'Temperature of the storeroom outside the fridge.'),
    ('Hum %', 'Humidity inside the fridge.'),
    ('Door', 'Whether the door was open or closed.'),
    ('Opened by', 'The staff member whose badge was last read. UNKNOWN means '
                  'the door was opened without a badge.'),
    ('Power', 'Mains electricity or backup battery.'),
    ('Batt %', 'Charge left in the backup battery.'),
    ('Cooling', 'Whether the cooling motor was switched on.'),
    ('Motor A', 'Electricity the cooling motor was actually drawing. This is '
                'what proves it really ran.'),
    ('Fan', 'Whether the circulation fan was switched on.'),
    ('Fan rpm', 'How fast the fan was actually turning.'),
    ('Alarm', 'Whether the alarm sounder was sounding.'),
    ('Verdict', 'The overall severity at that moment.'),
]
EVENT_COLUMNS = [
    ('Time', 'When the system reported this.'),
    ('Level', 'Info, Warning or Critical.'),
    ('Code', 'The internal name of the rule that fired.'),
    ('Message', 'What the rule reported, in its own words.'),
    ('Operator', 'The staff member involved, where one is known.'),
    ('Device', 'The sensor or switch the event was attributed to.'),
    ('Source', 'Whether this came from a real condition or an armed '
               'simulation.'),
]


class HistoryPage(Page):

    title = 'History'
    subtitle = 'The stored record - what happened, and when'

    def __init__(self, console):
        super().__init__(console)
        self._hours = 24

        outer = page_layout(self)
        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)

        body.addWidget(self._build_controls())
        body.addWidget(self._build_charts())
        body.addWidget(w.SectionTitle(
            'Every reading', 'a full snapshot stored every few seconds',
            help=h.Explain(
                'Every reading',
                'One row for every stored snapshot of the whole unit, newest '
                'first.',
                'It is the audit trail. When somebody asks what the fridge was '
                'doing at 03:40 last Tuesday, this is the answer.',
                note='Hover any column heading to see what it means.')))
        self.readingsTable = self._make_table(READING_COLUMNS, even=True)
        self.readingsTable.setMinimumHeight(260)
        body.addWidget(self.readingsTable)
        body.addWidget(w.SectionTitle(
            'Alerts raised', 'every warning and alarm, as it was reported',
            help=h.Explain(
                'Alerts raised',
                'Each time a rule changed its mind - a condition appearing, '
                'and later clearing.',
                'The readings table says what the fridge was doing; this says '
                'what the system made of it.')))
        self.eventsTable = self._make_table(EVENT_COLUMNS)
        self.eventsTable.setMinimumHeight(220)
        body.addWidget(self.eventsTable)

        outer.addWidget(scrollable(inner))

    # -- construction ------------------------------------------------------
    def _build_controls(self):
        self.rangeControl = w.SegmentedControl(RANGE_OPTIONS, 24, tips=RANGE_TIPS)
        self.rangeControl.changed.connect(self._change_range)

        exportBtn = QPushButton('Export readings')
        exportBtn.setStyleSheet(t.outline_button_style())
        h.set_help(exportBtn, 'Export to a spreadsheet',
                   'Saves the stored readings as a CSV file you can open in '
                   'Excel.',
                   'A temperature record is only useful if it can leave the '
                   'screen and go into a report.')
        exportBtn.clicked.connect(self.export_csv)
        refreshBtn = QPushButton('Refresh')
        refreshBtn.setStyleSheet(t.ghost_button_style())
        h.set_tip(refreshBtn, 'Re-read everything on this page from storage.')
        refreshBtn.clicked.connect(self.refresh)

        card = w.Card('Summary', 'The selected period at a glance',
                      actions=[self.rangeControl, exportBtn, refreshBtn],
                      help=h.Explain(
                          'Summary',
                          'The headline numbers for the period selected on the '
                          'right.',
                          'It answers the shift-handover question - was '
                          'anything wrong while I was away? - without reading '
                          'a single table row.'))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tiles = {}
        tiles = (
            ('samples', 'readings stored', h.Explain(
                'Readings stored',
                'How many complete snapshots were saved in this period.',
                'A gap in the count is a gap in the monitoring.')),
            ('temp_min', 'coldest', h.Explain(
                'Coldest reading',
                'The lowest temperature recorded in this period.',
                'Freezing damages many medicines as surely as overheating.',
                'Not below %.0f °C.' % cfg.TEMP_TARGET_MIN)),
            ('temp_max', 'warmest', h.Explain(
                'Warmest reading',
                'The highest temperature recorded in this period.',
                'This is the number an audit looks at first.',
                'Not above %.0f °C.' % cfg.TEMP_TARGET_MAX)),
            ('temp_avg', 'average', h.Explain(
                'Average temperature',
                'The mean of every reading in this period.',
                'A healthy average can still hide a short excursion, so read '
                'it beside the warmest and coldest figures.',
                glossary.TARGET)),
            ('excursion', 'minutes out of range', glossary.metric('excursion')),
            ('door_events', 'door openings', h.Explain(
                'Door openings',
                'How many times the door was opened in this period.',
                'Frequent openings are the usual explanation for a fridge that '
                'keeps drifting warm.')),
            ('warnings', 'warnings', h.Explain(
                'Warnings',
                'How many warnings were raised in this period.',
                'A warning is the early notice - something to check, not yet '
                'something at risk.', 'Zero.')),
            ('criticals', 'critical alarms', h.Explain(
                'Critical alarms',
                'How many critical conditions were raised in this period.',
                'Each one is a moment when the stock was at risk.', 'Zero.')),
        )
        for key, caption, explain in tiles:
            tile = w.StatTile(caption, help=explain)
            self.tiles[key] = tile
            row.addWidget(tile)
        card.add_layout(row)
        return card

    def _build_charts(self):
        container = QWidget()
        container.setStyleSheet('background: transparent;')
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.humidityChart = charts.TimeSeriesChart(
            [charts.Trace('humidity_avg', 'Humidity', t.ACCENT, fill=True, unit=' %')],
            0, 100,
            bands=[charts.Band(cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX, t.OK)],
            thresholds=[charts.Threshold(cfg.HUM_ALARM_MAX, t.CRITICAL)],
            unit=' %', title='Humidity', minimum_height=190)
        self.plantChart = charts.TimeSeriesChart(
            [charts.Trace('current_avg', 'Cooling motor', t.WARN, unit=' A')],
            0, 14,
            thresholds=[charts.Threshold(cfg.CURRENT_OVERLOAD_A, t.CRITICAL)],
            unit=' A', title='Cooling motor power', minimum_height=190)
        glossary.metric('humidity').apply(
            self.humidityChart,
            note='The green band is the safe range; the dashed red line is the '
                 'hard limit.')
        glossary.device('current').apply(
            self.plantChart, 'Compressor current',
            note='The dashed red line is the overload limit. Flat at zero '
                 'while the motor is commanded on means it is not running.')
        top.addWidget(self.humidityChart)
        top.addWidget(self.plantChart)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.fanChart = charts.TimeSeriesChart(
            [charts.Trace('rpm_avg', 'Fan speed', t.OK, fill=True, unit=' rpm')],
            0, 1800,
            thresholds=[charts.Threshold(cfg.FAN_RPM_MIN, t.CRITICAL),
                        charts.Threshold(cfg.FAN_RPM_DEGRADED, t.WARN)],
            unit=' rpm', title='Fan speed', minimum_height=190)
        self.activityChart = charts.StateTimeline(
            [('door_open', 'Door open', t.WARN),
             ('compressor_on', 'Cooling', t.ACCENT),
             ('fan_on', 'Fan', t.OK)], minimum_height=190)
        glossary.device('fan_rpm').apply(
            self.fanChart, 'Fan speed',
            note='The upper dashed line is the worn-bearing threshold; below '
                 'the lower one the fan counts as stalled.')
        h.set_help(self.activityChart, 'Activity timeline',
                   'When the door was open and when the cooling and the fan '
                   'were running, drawn on one shared timeline.',
                   'Laid over each other, the three bars explain the '
                   'temperature line above them: a long door bar or a gap in '
                   'the cooling bar is usually the whole story.',
                   'Short door bars, and cooling cycling on and off.')
        bottom.addWidget(self.fanChart)
        bottom.addWidget(self.activityChart)
        layout.addLayout(bottom)
        return container

    def _make_table(self, columns, even=False):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels([name for name, _tip in columns])
        for index, (_name, tip) in enumerate(columns):
            item = table.horizontalHeaderItem(index)
            if item is not None:
                item.setToolTip(h.tooltip_html('', tip))
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet(t.TABLE_STYLE + t.SCROLLBAR)
        header = table.horizontalHeader()
        if even:
            header.setSectionResizeMode(QHeaderView.Stretch)
        else:
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)
        return table

    # -- data --------------------------------------------------------------
    def _change_range(self, hours):
        self._hours = hours
        for chart in (self.humidityChart, self.plantChart, self.fanChart):
            chart.set_loading()
        self.refresh()

    def on_shown(self):
        self.refresh()

    def refresh(self):
        try:
            stats = db.stats_since(self._hours, cfg.TEMP_TARGET_MIN,
                                   cfg.TEMP_TARGET_MAX, cfg.DB_WRITE_INTERVAL_S)
            rows = db.series(hours=self._hours, points=320)
            readings = db.recent_readings(300)
            events = db.recent_events(180)
        except Exception as error:
            print('history: could not load:', error)
            return

        self._fill_tiles(stats)
        for chart in (self.humidityChart, self.plantChart, self.fanChart):
            chart.set_rows(rows)
        self.activityChart.set_rows(rows)
        self._fill_readings(readings)
        self._fill_events(events)

    def _fill_tiles(self, stats):
        def number(value, suffix=''):
            return '--' if value is None else ('%.1f%s' % (value, suffix))

        self.tiles['samples'].set_value(str(stats['samples']))
        self.tiles['temp_min'].set_value(number(stats['temp_min'], ' °C'), t.ACCENT)
        self.tiles['temp_max'].set_value(number(stats['temp_max'], ' °C'), t.ACCENT)
        self.tiles['temp_avg'].set_value(number(stats['temp_avg'], ' °C'))
        excursion = stats['excursion_minutes']
        self.tiles['excursion'].set_value('%.1f' % excursion,
                                          t.WARN if excursion > 0 else t.OK)
        self.tiles['door_events'].set_value(str(stats['door_events']))
        self.tiles['warnings'].set_value(
            str(stats['warnings']), t.WARN if stats['warnings'] else t.TEXT)
        self.tiles['criticals'].set_value(
            str(stats['criticals']), t.CRITICAL if stats['criticals'] else t.OK)

    def _fill_readings(self, rows):
        self.readingsTable.setRowCount(len(rows))
        for r, row in enumerate(rows):
            (ts, temp, temp_b, ambient, hum, door, operator, power, battery,
             compressor, current, fan, rpm, siren, level) = row

            def number(value, fmt):
                return '--' if value is None else fmt % value

            level = cfg.normalise_level(level)
            values = [
                ts[11:] if len(ts) > 11 else ts,   # only the range is shown
                number(temp, '%.2f'), number(temp_b, '%.2f'),
                number(ambient, '%.1f'), number(hum, '%.0f'),
                door or '--', operator or '--', power or '--',
                number(battery, '%.0f'), compressor or '--',
                number(current, '%.2f'), fan or '--', number(rpm, '%.0f'),
                siren or '--', level or '--',
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 14:
                    item.setForeground(QColor(t.level_color(level)))
                elif c == 1 and temp is not None and not (
                        cfg.TEMP_TARGET_MIN <= temp <= cfg.TEMP_TARGET_MAX):
                    item.setForeground(QColor(t.WARN))
                elif c == 6 and operator == cfg.UNKNOWN_OPERATOR:
                    item.setForeground(QColor(t.WARN))
                self.readingsTable.setItem(r, c, item)

    def _fill_events(self, rows):
        self.eventsTable.setRowCount(len(rows))
        for r, (ts, level, code, message, operator, device, simulated) in enumerate(rows):
            level = cfg.normalise_level(level)
            values = (ts, level, code, message, operator or '', device or '',
                      'SIMULATED' if simulated else 'live')
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 1:
                    item.setForeground(QColor(t.level_color(level)))
                elif c == 6 and simulated:
                    item.setForeground(QColor(t.SIM))
                self.eventsTable.setItem(r, c, item)

    def export_csv(self):
        default = os.path.join(
            os.path.expanduser('~'),
            'coldchain_readings_%s.csv' % datetime.now().strftime('%Y%m%d_%H%M'))
        path, _ = QFileDialog.getSaveFileName(self, 'Export readings', default,
                                              'CSV files (*.csv)')
        if not path:
            return
        try:
            written = db.export_readings_csv(path)
        except OSError as error:
            QMessageBox.warning(self, 'Export failed', str(error))
            return
        self.console.toast('Exported %d readings' % written)
