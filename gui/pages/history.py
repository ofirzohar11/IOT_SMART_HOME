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
from gui import charts
from gui.pages.base import Page, page_layout, scrollable
from ui import theme as t
from ui import widgets as w

RANGE_OPTIONS = [('1H', 1), ('6H', 6), ('24H', 24), ('7D', 168)]

READING_COLUMNS = ['Time', 'A °C', 'B °C', 'Room °C', 'Hum %', 'Door', 'Operator',
                   'Power', 'Batt %', 'Comp', 'Amps', 'Fan', 'RPM', 'Siren', 'Level']
EVENT_COLUMNS = ['Time', 'Level', 'Code', 'Message', 'Operator', 'Device', 'Source']


class HistoryPage(Page):

    title = 'History'
    subtitle = 'Stored readings, events and reports'

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
        body.addWidget(w.SectionTitle('Readings', 'five-second audit trail'))
        self.readingsTable = self._make_table(READING_COLUMNS, even=True)
        self.readingsTable.setMinimumHeight(260)
        body.addWidget(self.readingsTable)
        body.addWidget(w.SectionTitle('Alert events'))
        self.eventsTable = self._make_table(EVENT_COLUMNS)
        self.eventsTable.setMinimumHeight(220)
        body.addWidget(self.eventsTable)

        outer.addWidget(scrollable(inner))

    # -- construction ------------------------------------------------------
    def _build_controls(self):
        self.rangeControl = w.SegmentedControl(RANGE_OPTIONS, 24)
        self.rangeControl.changed.connect(self._change_range)

        exportBtn = QPushButton('Export readings')
        exportBtn.setStyleSheet(t.outline_button_style())
        exportBtn.clicked.connect(self.export_csv)
        refreshBtn = QPushButton('Refresh')
        refreshBtn.setStyleSheet(t.ghost_button_style())
        refreshBtn.clicked.connect(self.refresh)

        card = w.Card('Summary', actions=[self.rangeControl, exportBtn, refreshBtn])
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tiles = {}
        for key, caption in (('samples', 'readings stored'),
                             ('temp_min', 'min temperature'),
                             ('temp_max', 'max temperature'),
                             ('temp_avg', 'average temperature'),
                             ('excursion', 'minutes out of band'),
                             ('door_events', 'door openings'),
                             ('warnings', 'warnings'),
                             ('criticals', 'critical events')):
            tile = w.StatTile(caption)
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
            [charts.Trace('current_avg', 'Compressor A', t.WARN, unit=' A')],
            0, 14,
            thresholds=[charts.Threshold(cfg.CURRENT_OVERLOAD_A, t.CRITICAL)],
            unit=' A', title='Compressor current', minimum_height=190)
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
             ('compressor_on', 'Compressor', t.ACCENT),
             ('fan_on', 'Fan', t.OK)], minimum_height=190)
        bottom.addWidget(self.fanChart)
        bottom.addWidget(self.activityChart)
        layout.addLayout(bottom)
        return container

    def _make_table(self, columns, even=False):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
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
