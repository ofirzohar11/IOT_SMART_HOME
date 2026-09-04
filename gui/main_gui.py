"""Cold Chain Monitor - main operator GUI.

Two tabs:

* **Dashboard** - live state of the unit: temperature and humidity gauges with
  the storage band drawn on them, the door and power panels, the three
  actuators, a rolling temperature trend and the Info/Warning/Alarm log.
* **History** - the audit trail read back out of SQLite, with a summary of the
  last 24 hours and a CSV export.

The dashboard is driven by the consolidated status message the data manager
publishes once per second, plus the actuator status topics, so what is on screen
is what the devices actually reported - not what the GUI assumed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import math
from collections import deque
from datetime import datetime

from PyQt5.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame,
                             QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QMainWindow, QMessageBox, QPushButton, QScrollArea,
                             QSizePolicy, QTableWidget, QTableWidgetItem,
                             QTabWidget, QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from config.mqtt_client import MqttClient, parse_json
from database import db
from ui import theme as t

TREND_POINTS = 120
MAX_LOG_CARDS = 200


# ===========================================================================
#  Painted widgets
# ===========================================================================
class ArcGauge(QFrame):
    """Speedometer style gauge with the acceptable storage band drawn on the arc."""

    START = 210      # degrees, Qt convention (counter clockwise from 3 o'clock)
    SPAN = -240      # sweep clockwise over the top

    def __init__(self, title, unit, vmin, vmax, target_min, target_max,
                 alarm_min, alarm_max):
        super().__init__()
        self.title = title
        self.unit = unit
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.target_min = float(target_min)
        self.target_max = float(target_max)
        self.alarm_min = float(alarm_min)
        self.alarm_max = float(alarm_max)
        self.value = None
        self.setMinimumSize(270, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_value(self, value):
        self.value = value
        self.update()

    # -- helpers -----------------------------------------------------------
    def _fraction(self, value):
        span = self.vmax - self.vmin
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (value - self.vmin) / span))

    def _angle(self, value):
        return self.START + self.SPAN * self._fraction(value)

    def _status(self):
        if self.value is None:
            return 'NO DATA', t.OFF
        if self.value < self.alarm_min or self.value > self.alarm_max:
            return 'ALARM', t.ALARM
        if self.value < self.target_min or self.value > self.target_max:
            return 'WARNING', t.WARN
        return 'IN RANGE', t.OK

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), 12, 12)

        arc_w = 16
        title_h = 32
        avail_h = h - title_h - 18
        radius = int(min((w - 40 - arc_w) / 2.0, (avail_h - arc_w) / 1.5))
        radius = max(radius, 40)
        cx = w // 2
        cy = title_h + radius + arc_w // 2
        box = QRect(cx - radius, cy - radius, radius * 2, radius * 2)

        # Track
        painter.setPen(QPen(QColor('#0B1220'), arc_w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(box, self.START * 16, self.SPAN * 16)

        # Acceptable storage band
        band_start = self._angle(self.target_min)
        band_span = self._angle(self.target_max) - band_start
        band_color = QColor(t.OK)
        band_color.setAlpha(90)
        painter.setPen(QPen(band_color, arc_w, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(box, int(band_start * 16), int(band_span * 16))

        status_text, status_color = self._status()

        # Value arc
        if self.value is not None:
            span = self._angle(self.value) - self.START
            painter.setPen(QPen(QColor(status_color), arc_w, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(box, self.START * 16, int(span * 16))

        # Title
        painter.setPen(QColor(t.TEXT_DIM))
        painter.setFont(QFont('Arial', 10, QFont.Bold))
        painter.drawText(QRect(0, 8, w, 20), Qt.AlignCenter, self.title.upper())

        # Value
        text = '--' if self.value is None else ('%.1f%s' % (self.value, self.unit))
        painter.setPen(QColor(status_color if self.value is not None else t.TEXT_DIM))
        painter.setFont(QFont('Arial', 30, QFont.Bold))
        painter.drawText(QRect(cx - 110, cy - 34, 220, 48), Qt.AlignCenter, text)

        # Status word
        painter.setFont(QFont('Arial', 9, QFont.Bold))
        painter.drawText(QRect(cx - 80, cy + 14, 160, 18), Qt.AlignCenter, status_text)

        # Scale end labels
        painter.setPen(QColor(t.TEXT_DIM))
        painter.setFont(QFont('Arial', 8))
        for value in (self.vmin, self.vmax):
            deg = math.radians(self._angle(value))
            lx = cx + int((radius + 15) * math.cos(deg))
            ly = cy - int((radius + 15) * math.sin(deg))
            painter.drawText(QRect(lx - 20, ly - 8, 40, 16), Qt.AlignCenter,
                             '%g' % value)

        painter.end()


class TrendChart(QFrame):
    """Rolling temperature trend with the storage band and hard limits drawn in."""

    def __init__(self, title='Temperature trend'):
        super().__init__()
        self.title = title
        self.values = deque(maxlen=TREND_POINTS)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add(self, value):
        if value is None:
            return
        self.values.append(float(value))
        self.update()

    def _y(self, value, top, bottom):
        span = cfg.TEMP_GAUGE_MAX - cfg.TEMP_GAUGE_MIN
        frac = (value - cfg.TEMP_GAUGE_MIN) / span
        frac = max(0.0, min(1.0, frac))
        return bottom - frac * (bottom - top)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), 12, 12)

        left, right, top, bottom = 42, w - 14, 34, h - 22

        painter.setPen(QColor(t.TEXT_DIM))
        painter.setFont(QFont('Arial', 10, QFont.Bold))
        painter.drawText(QRect(14, 9, w - 28, 18), Qt.AlignLeft,
                         self.title.upper() + '   (last %d samples)' % TREND_POINTS)

        if right <= left or bottom <= top:
            painter.end()
            return

        # Acceptable band
        band_top = self._y(cfg.TEMP_TARGET_MAX, top, bottom)
        band_bottom = self._y(cfg.TEMP_TARGET_MIN, top, bottom)
        band_color = QColor(t.OK)
        band_color.setAlpha(38)
        painter.setPen(Qt.NoPen)
        painter.setBrush(band_color)
        painter.drawRect(QRect(left, int(band_top), right - left,
                               int(band_bottom - band_top)))

        # Grid and axis labels
        painter.setFont(QFont('Arial', 8))
        for value in (cfg.TEMP_GAUGE_MAX, cfg.TEMP_ALARM_MAX, cfg.TEMP_TARGET_MAX,
                      cfg.TEMP_TARGET_MIN, cfg.TEMP_ALARM_MIN, cfg.TEMP_GAUGE_MIN):
            y = int(self._y(value, top, bottom))
            is_limit = value in (cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX)
            pen = QPen(QColor(t.ALARM if is_limit else t.BORDER), 1,
                       Qt.DashLine if is_limit else Qt.SolidLine)
            painter.setPen(pen)
            painter.drawLine(left, y, right, y)
            painter.setPen(QColor(t.TEXT_DIM))
            painter.drawText(QRect(4, y - 8, 34, 16),
                             Qt.AlignRight | Qt.AlignVCenter, '%g' % value)

        if len(self.values) < 2:
            painter.setPen(QColor(t.TEXT_DIM))
            painter.setFont(QFont('Arial', 10))
            painter.drawText(QRect(left, top, right - left, bottom - top),
                             Qt.AlignCenter, 'waiting for samples...')
            painter.end()
            return

        # Trend line
        step = (right - left) / float(TREND_POINTS - 1)
        offset = TREND_POINTS - len(self.values)
        points = QPolygonF()
        for index, value in enumerate(self.values):
            x = left + (offset + index) * step
            points.append(QPointF(x, self._y(value, top, bottom)))

        latest = self.values[-1]
        in_band = cfg.TEMP_TARGET_MIN <= latest <= cfg.TEMP_TARGET_MAX
        in_limits = cfg.TEMP_ALARM_MIN <= latest <= cfg.TEMP_ALARM_MAX
        line_color = QColor(t.OK if in_band else (t.WARN if in_limits else t.ALARM))

        # Soft fill under the line
        fill = QPainterPath()
        fill.moveTo(points[0].x(), bottom)
        for point in points:
            fill.lineTo(point)
        fill.lineTo(points[-1].x(), bottom)
        fill.closeSubpath()
        fill_color = QColor(line_color)
        fill_color.setAlpha(45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_color)
        painter.drawPath(fill)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(line_color, 2))
        painter.drawPolyline(points)

        # Current sample marker
        last = points[-1]
        painter.setBrush(line_color)
        painter.setPen(QPen(QColor(t.BG), 2))
        painter.drawEllipse(last, 4.5, 4.5)

        painter.setPen(QColor(line_color))
        painter.setFont(QFont('Arial', 10, QFont.Bold))
        painter.drawText(QRect(right - 90, int(last.y()) - 22, 84, 16),
                         Qt.AlignRight, '%.1f °C' % latest)

        painter.end()


# ===========================================================================
#  Composed panels
# ===========================================================================
class DeviceCard(QFrame):
    """One actuator: the state it reported, and what its sensor measured.

    The pill is the *command* echoed back by the relay; the line underneath is
    an independent measurement of what the hardware actually did. When those two
    disagree, the card says so - which is the entire point of adding the current
    clamp and the tachometer.
    """

    def __init__(self, name, icon, on_color, measured=True):
        super().__init__()
        self.on_color = on_color
        self.setObjectName('panel')
        self.setMinimumHeight(126)
        self._apply_border(t.BORDER)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.iconLabel = t.label(icon, size=22, align=Qt.AlignCenter)
        self.nameLabel = t.label(name.upper(), size=11, color=t.TEXT_DIM, bold=True,
                                 align=Qt.AlignCenter)
        self.stateLabel = QLabel('OFF')
        self.stateLabel.setAlignment(Qt.AlignCenter)
        self.stateLabel.setFixedHeight(22)
        self._paint_pill(False)

        layout.addWidget(self.iconLabel)
        layout.addWidget(self.nameLabel)
        layout.addWidget(self.stateLabel)

        self.measuredLabel = None
        if measured:
            self.measuredLabel = t.label('-- ', size=12, color=t.TEXT_DIM, bold=True,
                                         align=Qt.AlignCenter)
            layout.addWidget(self.measuredLabel)

    def _apply_border(self, color):
        self.setStyleSheet('QFrame#panel { background-color: %s; border: 1px solid %s; '
                           'border-radius: 12px; }' % (t.PANEL, color))

    def _paint_pill(self, is_on):
        color = self.on_color if is_on else t.OFF
        self.stateLabel.setText('ON' if is_on else 'OFF')
        self.stateLabel.setStyleSheet(
            'color: %s; background-color: %s; border: none; border-radius: 7px; '
            'font-family: %s; font-size: 11px; font-weight: bold;'
            % ('#0B1220' if is_on else t.TEXT_DIM, color, t.FONT))

    def set_state(self, is_on):
        self._paint_pill(is_on)
        self._apply_border(self.on_color if is_on else t.BORDER)

    def set_measurement(self, text, color=t.TEXT_DIM):
        """Show the independent reading, coloured red when it contradicts the command."""
        if self.measuredLabel is None:
            return
        self.measuredLabel.setText(text)
        self.measuredLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 12px; font-weight: bold; '
            'background: transparent; border: none;' % (color, t.FONT))


class DoorCard(QFrame):

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        layout.addWidget(t.label('DOOR', size=10, color=t.TEXT_DIM, bold=True))
        self.stateLabel = t.label('--', size=22, bold=True)
        self.timerLabel = t.label('', size=11, color=t.TEXT_DIM)
        self.bar = QFrame()
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet('background-color: %s; border-radius: 3px; border: none;'
                               % t.BORDER)

        layout.addWidget(self.stateLabel)
        layout.addWidget(self.timerLabel)
        layout.addWidget(self.bar)

    def update_state(self, state, seconds):
        is_open = state == 'OPEN'
        if not is_open:
            self.stateLabel.setText('CLOSED')
            self.stateLabel.setStyleSheet(
                'color: %s; font-family: %s; font-size: 22px; font-weight: bold; '
                'background: transparent; border: none;' % (t.OK, t.FONT))
            self.timerLabel.setText('sealed')
            self._set_bar(0.0, t.OK)
            return

        if seconds >= cfg.DOOR_ALARM_SECONDS:
            color = t.ALARM
        elif seconds >= cfg.DOOR_WARNING_SECONDS:
            color = t.WARN
        else:
            color = t.ACCENT
        self.stateLabel.setText('OPEN')
        self.stateLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 22px; font-weight: bold; '
            'background: transparent; border: none;' % (color, t.FONT))
        self.timerLabel.setText('open %d s  (alarm at %d s)'
                                % (seconds, cfg.DOOR_ALARM_SECONDS))
        self._set_bar(min(1.0, seconds / float(cfg.DOOR_ALARM_SECONDS)), color)

    def _set_bar(self, fraction, color):
        stop = max(0.001, min(0.999, fraction))
        self.bar.setStyleSheet(
            'border: none; border-radius: 3px; background: qlineargradient('
            'x1:0, y1:0, x2:1, y2:0, stop:0 %s, stop:%.3f %s, stop:%.3f %s, stop:1 %s);'
            % (color, stop, color, stop, t.BORDER, t.BORDER))


class PowerCard(QFrame):

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        layout.addWidget(t.label('POWER', size=10, color=t.TEXT_DIM, bold=True))
        self.sourceLabel = t.label('--', size=22, bold=True)
        self.batteryLabel = t.label('', size=11, color=t.TEXT_DIM)
        self.bar = QFrame()
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet('background-color: %s; border-radius: 3px; border: none;'
                               % t.BORDER)

        layout.addWidget(self.sourceLabel)
        layout.addWidget(self.batteryLabel)
        layout.addWidget(self.bar)

    def update_state(self, source, battery):
        on_mains = source == 'MAINS'
        if battery <= cfg.BATTERY_ALARM_PERCENT:
            color = t.ALARM
        elif on_mains:
            color = t.OK
        else:
            color = t.WARN
        self.sourceLabel.setText(source)
        self.sourceLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 22px; font-weight: bold; '
            'background: transparent; border: none;' % (color, t.FONT))
        self.batteryLabel.setText('backup battery %.0f %%' % battery)
        stop = max(0.001, min(0.999, battery / 100.0))
        self.bar.setStyleSheet(
            'border: none; border-radius: 3px; background: qlineargradient('
            'x1:0, y1:0, x2:1, y2:0, stop:0 %s, stop:%.3f %s, stop:%.3f %s, stop:1 %s);'
            % (color, stop, color, stop, t.BORDER, t.BORDER))


class EventLog(QFrame):
    """Info / Warning / Alarm status window."""

    def __init__(self):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())
        self.count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(t.label('EVENT LOG', size=10, color=t.TEXT_DIM, bold=True))
        header.addStretch()
        self.counterLabel = t.label('0 events', size=10, color=t.TEXT_DIM)
        clearBtn = QPushButton('Clear')
        clearBtn.setStyleSheet(t.outline_button_style(t.TEXT_DIM))
        clearBtn.clicked.connect(self.clear)
        header.addWidget(self.counterLabel)
        header.addWidget(clearBtn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }'
                                  + SCROLLBAR_STYLE)

        self.container = QWidget()
        self.container.setStyleSheet('background: transparent;')
        self.cards = QVBoxLayout(self.container)
        self.cards.setContentsMargins(0, 0, 6, 0)
        self.cards.setSpacing(5)
        self.cards.addStretch()
        self.scroll.setWidget(self.container)

        outer.addLayout(header)
        outer.addWidget(self.scroll)

    def add_event(self, level, code, message, ts=None):
        color = t.level_color(level)
        stamp = ts or datetime.now().strftime('%H:%M:%S')
        if len(stamp) > 8:
            stamp = stamp[-8:]

        card = QFrame()
        card.setObjectName('eventCard')
        card.setStyleSheet('QFrame#eventCard { background-color: %s; border: none; '
                           'border-left: 4px solid %s; border-radius: 7px; }'
                           % (t.PANEL_ALT, color))
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(10)

        timeLabel = t.label(stamp, size=11, color=t.TEXT_DIM)
        timeLabel.setFixedWidth(58)

        levelLabel = QLabel(level)
        levelLabel.setFixedWidth(66)
        levelLabel.setAlignment(Qt.AlignCenter)
        levelLabel.setStyleSheet(
            'color: #0B1220; background-color: %s; border: none; border-radius: 4px; '
            'font-family: %s; font-size: 10px; font-weight: bold; padding: 2px 0;'
            % (color, t.FONT))

        messageLabel = t.label(message, size=12)
        messageLabel.setWordWrap(True)

        row.addWidget(timeLabel)
        row.addWidget(levelLabel)
        row.addWidget(messageLabel, stretch=1)

        self.cards.insertWidget(self.cards.count() - 1, card)
        self.count += 1
        self.counterLabel.setText('%d events' % self.count)

        while self.cards.count() - 1 > MAX_LOG_CARDS:
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def clear(self):
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.count = 0
        self.counterLabel.setText('0 events')


class StatTile(QFrame):
    """A caption with one number or short phrase above it."""

    def __init__(self, caption, value_size=20, wrap=False):
        super().__init__()
        self.value_size = value_size
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style(background=t.PANEL_ALT))
        self.setMinimumWidth(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self.valueLabel = t.label('--', size=value_size, bold=True)
        self.valueLabel.setWordWrap(wrap)
        layout.addWidget(self.valueLabel)
        layout.addWidget(t.label(caption, size=10, color=t.TEXT_DIM))

    def set_value(self, text, color=t.TEXT):
        self.valueLabel.setText(text)
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: %dpx; font-weight: bold; '
            'background: transparent; border: none;'
            % (color, t.FONT, self.value_size))


SCROLLBAR_STYLE = '''
    QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
    QScrollBar::handle:vertical { background: #3F4E64; border-radius: 4px; min-height: 30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
'''

TABLE_STYLE = '''
    QTableWidget {
        background-color: %s;
        alternate-background-color: %s;
        color: %s;
        gridline-color: %s;
        border: 1px solid %s;
        border-radius: 10px;
        font-size: 12px;
    }
    QTableWidget::item { padding: 4px; }
    QTableWidget::item:selected { background-color: #1D4ED8; color: white; }
    QHeaderView::section {
        background-color: %s;
        color: %s;
        padding: 6px;
        border: none;
        font-weight: bold;
        font-size: 11px;
    }
    QTableCornerButton::section { background-color: %s; border: none; }
''' % (t.PANEL, t.PANEL_ALT, t.TEXT, t.BORDER, t.BORDER, t.PANEL_ALT, t.TEXT_DIM,
       t.PANEL_ALT)


# ===========================================================================
#  History tab
# ===========================================================================
class HistoryTab(QWidget):

    # Mirrors db.READING_FIELDS, with shorter headers for the table.
    READING_COLUMNS = ['Time', 'A °C', 'B °C', 'Room °C', 'Hum %', 'Door',
                       'Operator', 'Power', 'Batt %', 'Comp', 'Amps', 'Fan',
                       'RPM', 'Siren', 'Level']
    EVENT_COLUMNS = ['Time', 'Level', 'Code', 'Message', 'Operator']

    def __init__(self):
        super().__init__()
        self.setObjectName('page')
        self.setStyleSheet('QWidget#page { background-color: %s; }' % t.BG)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Summary tiles
        self.tiles = {}
        tileRow = QHBoxLayout()
        tileRow.setSpacing(10)
        for key, caption in (('samples', 'readings stored'),
                             ('temp_min', 'min temperature'),
                             ('temp_max', 'max temperature'),
                             ('temp_avg', 'average temperature'),
                             ('excursion', 'minutes out of band'),
                             ('door_events', 'door openings'),
                             ('warnings', 'warnings'),
                             ('alarms', 'alarms')):
            tile = StatTile(caption)
            self.tiles[key] = tile
            tileRow.addWidget(tile)

        # Controls
        controls = QHBoxLayout()
        controls.addWidget(t.label('Last 24 hours, newest first', size=12,
                                   color=t.TEXT_DIM))
        controls.addStretch()
        refreshBtn = QPushButton('Refresh')
        refreshBtn.setStyleSheet(t.outline_button_style(t.ACCENT))
        refreshBtn.clicked.connect(self.refresh)
        exportBtn = QPushButton('Export CSV')
        exportBtn.setStyleSheet(t.button_style(t.ACCENT))
        exportBtn.clicked.connect(self.export_csv)
        controls.addWidget(refreshBtn)
        controls.addWidget(exportBtn)

        # Readings share the width evenly; the events table gives the leftover
        # space to the message column.
        self.readingsTable = self._make_table(self.READING_COLUMNS, even_columns=True)
        self.eventsTable = self._make_table(self.EVENT_COLUMNS)

        layout.addLayout(tileRow)
        layout.addLayout(controls)
        layout.addWidget(t.label('READINGS', size=10, color=t.TEXT_DIM, bold=True))
        layout.addWidget(self.readingsTable, stretch=3)
        layout.addWidget(t.label('ALERT EVENTS', size=10, color=t.TEXT_DIM, bold=True))
        layout.addWidget(self.eventsTable, stretch=2)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(10000)
        self.refresh()

    def _make_table(self, columns, even_columns=False):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet(TABLE_STYLE + SCROLLBAR_STYLE)
        header = table.horizontalHeader()
        if even_columns:
            header.setSectionResizeMode(QHeaderView.Stretch)
        else:
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)
        return table

    # -- data --------------------------------------------------------------
    def refresh(self):
        try:
            stats = db.stats_since(24, cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX,
                                   cfg.DB_WRITE_INTERVAL_S)
            readings = db.recent_readings(300)
            events = db.recent_events(150)
        except Exception as error:  # database busy or not created yet
            print('history refresh failed:', error)
            return

        self._fill_tiles(stats)
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
        self.tiles['excursion'].set_value(
            '%.1f' % excursion, t.WARN if excursion > 0 else t.OK)
        self.tiles['door_events'].set_value(str(stats['door_events']))
        self.tiles['warnings'].set_value(
            str(stats['warnings']), t.WARN if stats['warnings'] else t.TEXT)
        self.tiles['alarms'].set_value(
            str(stats['alarms']), t.ALARM if stats['alarms'] else t.OK)

    def _fill_readings(self, rows):
        self.readingsTable.setRowCount(len(rows))
        for r, row in enumerate(rows):
            (ts, temp, temp_b, ambient, hum, door, operator, power, battery,
             compressor, current, fan, rpm, siren, level) = row

            def number(value, fmt):
                return '--' if value is None else fmt % value

            values = [
                ts[11:] if len(ts) > 11 else ts,  # only the last 24 h is shown
                number(temp, '%.2f'),
                number(temp_b, '%.2f'),
                number(ambient, '%.1f'),
                number(hum, '%.0f'),
                door or '--',
                operator or '--',
                power or '--',
                number(battery, '%.0f'),
                compressor or '--',
                number(current, '%.2f'),
                fan or '--',
                number(rpm, '%.0f'),
                siren or '--',
                level or '--',
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
        for r, (ts, level, code, message, operator) in enumerate(rows):
            for c, value in enumerate((ts, level, code, message, operator or '')):
                item = QTableWidgetItem(str(value))
                if c == 1:
                    item.setForeground(QColor(t.level_color(level)))
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
        QMessageBox.information(self, 'Export complete',
                                'Wrote %d readings to:\n%s' % (written, path))


# ===========================================================================
#  Main window
# ===========================================================================
class MainWindow(QMainWindow):

    status_received = pyqtSignal(object)
    alert_received = pyqtSignal(object)
    device_status = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cold Chain Monitor - Pharmaceutical Storage Unit 1')
        self.setMinimumSize(1280, 920)
        self.setStyleSheet('QMainWindow { background-color: %s; }' % t.BG)

        self.mode = 'MONITORING'

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        root.addWidget(self._build_header())

        tabs = QTabWidget()
        tabs.setStyleSheet('''
            QTabWidget::pane { border: 1px solid %s; border-radius: 12px; top: -1px; }
            QTabBar::tab {
                background: %s; color: %s; padding: 9px 22px; margin-right: 4px;
                border-top-left-radius: 9px; border-top-right-radius: 9px;
                font-family: %s; font-size: 12px; font-weight: bold;
            }
            QTabBar::tab:selected { background: %s; color: %s; }
        ''' % (t.BORDER, t.PANEL, t.TEXT_DIM, t.FONT, t.PANEL_ALT, t.TEXT))
        tabs.addTab(self._build_dashboard(), 'Dashboard')
        self.historyTab = HistoryTab()
        tabs.addTab(self.historyTab, 'History && Reports')  # && escapes the mnemonic
        self.tabs = tabs
        root.addWidget(tabs, stretch=1)

        # Signals first, so nothing from the network thread touches a widget directly
        self.status_received.connect(self.apply_status)
        self.alert_received.connect(self.apply_alert)
        self.device_status.connect(self.apply_device_status)
        self.connection_changed.connect(self.apply_connection)

        self.mqtt = MqttClient(
            'gui',
            on_connect=lambda: self.connection_changed.emit(True),
            on_disconnect=lambda: self.connection_changed.emit(False),
            on_message=self._on_message,
        )
        self.mqtt.subscribe(cfg.TOPIC_STATUS, cfg.TOPIC_ALERT,
                            cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_FAN_STS,
                            cfg.TOPIC_SIREN_STS)
        QTimer.singleShot(200, self.mqtt.start)

    # -- construction ------------------------------------------------------
    def _build_header(self):
        header = QFrame()
        header.setObjectName('panel')
        header.setStyleSheet(t.panel_style())
        header.setFixedHeight(72)

        row = QHBoxLayout(header)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(16)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(t.label('❄  COLD CHAIN MONITOR', size=17, bold=True))
        titles.addWidget(t.label('Pharmaceutical storage - target band %.0f to %.0f °C'
                                 % (cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX),
                                 size=11, color=t.TEXT_DIM))
        row.addLayout(titles)
        row.addStretch()

        self.statusPill = QLabel('WAITING FOR DATA')
        self.statusPill.setAlignment(Qt.AlignCenter)
        self.statusPill.setFixedSize(190, 40)
        self._paint_pill(t.OFF, 'WAITING FOR DATA')

        broker = QVBoxLayout()
        broker.setSpacing(1)
        broker.addWidget(t.label('broker: %s:%s' % (cfg.BROKER_HOST, cfg.BROKER_PORT),
                                 size=10, color=t.TEXT_DIM))
        self.connectionLabel = t.label('● offline', size=10, color=t.ALARM)
        broker.addWidget(self.connectionLabel)

        self.modeBtn = QPushButton('Maintenance mode')
        self.modeBtn.setStyleSheet(t.outline_button_style(t.TEXT_DIM))
        self.modeBtn.clicked.connect(self.toggle_mode)

        row.addWidget(self.statusPill)
        row.addLayout(broker)
        row.addWidget(self.modeBtn)
        return header

    def _build_dashboard(self):
        page = QWidget()
        page.setObjectName('page')
        page.setStyleSheet('QWidget#page { background-color: %s; }' % t.BG)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        topRow = QHBoxLayout()
        topRow.setSpacing(12)
        self.tempGauge = ArcGauge('Temperature', ' °C',
                                  cfg.TEMP_GAUGE_MIN, cfg.TEMP_GAUGE_MAX,
                                  cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX,
                                  cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX)
        self.humGauge = ArcGauge('Humidity', ' %',
                                 cfg.HUM_GAUGE_MIN, cfg.HUM_GAUGE_MAX,
                                 cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX,
                                 0.0, cfg.HUM_ALARM_MAX)

        sideColumn = QVBoxLayout()
        sideColumn.setSpacing(12)
        self.doorCard = DoorCard()
        self.powerCard = PowerCard()
        sideColumn.addWidget(self.doorCard)
        sideColumn.addWidget(self.powerCard)

        topRow.addWidget(self.tempGauge, stretch=3)
        topRow.addWidget(self.humGauge, stretch=3)
        topRow.addLayout(sideColumn, stretch=2)

        # Diagnostic readings that do not warrant a full gauge
        telemetryRow = QHBoxLayout()
        telemetryRow.setSpacing(12)
        self.probeTile = StatTile('probe B  (redundant)')
        self.ambientTile = StatTile('storeroom temperature')
        self.operatorTile = StatTile('last door opened by', value_size=15)
        self.diagnosisTile = StatTile('assessment', value_size=12, wrap=True)
        for tile in (self.probeTile, self.ambientTile, self.operatorTile,
                     self.diagnosisTile):
            tile.setMinimumHeight(66)
            telemetryRow.addWidget(tile)
        telemetryRow.setStretch(3, 2)  # the assessment text needs more room

        deviceRow = QHBoxLayout()
        deviceRow.setSpacing(12)
        self.compressorCard = DeviceCard('Compressor', '❄', t.ACCENT)
        self.fanCard = DeviceCard('Fan', '🌀', t.OK)
        self.sirenCard = DeviceCard('Siren', '🚨', t.ALARM, measured=False)
        for card in (self.compressorCard, self.fanCard, self.sirenCard):
            deviceRow.addWidget(card)

        bottomRow = QHBoxLayout()
        bottomRow.setSpacing(12)
        self.trend = TrendChart()
        self.eventLog = EventLog()
        bottomRow.addWidget(self.trend, stretch=3)
        bottomRow.addWidget(self.eventLog, stretch=2)

        layout.addLayout(topRow)
        layout.addLayout(telemetryRow)
        layout.addLayout(deviceRow)
        layout.addLayout(bottomRow, stretch=1)
        return page

    # -- MQTT --------------------------------------------------------------
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

    # -- Qt thread updates -------------------------------------------------
    def apply_status(self, data):
        temperature = data.get('temperature')
        humidity = data.get('humidity')

        self.tempGauge.set_value(temperature)
        self.humGauge.set_value(humidity)
        self.trend.add(temperature)

        self.doorCard.update_state(data.get('door', '--'),
                                   int(data.get('door_seconds', 0) or 0))
        self.powerCard.update_state(data.get('power', '--'),
                                    float(data.get('battery', 0) or 0))

        self._update_telemetry(data)
        self._update_measurements(data)

        level = data.get('level', cfg.LEVEL_INFO)
        sensor_state = data.get('sensor_state', 'ONLINE')
        if data.get('mode') == 'MAINTENANCE':
            self._paint_pill(t.ACCENT, 'MAINTENANCE MODE')
        elif sensor_state == 'OFFLINE':
            self._paint_pill(t.ALARM, 'SENSOR OFFLINE')
        elif sensor_state == 'WAITING':
            self._paint_pill(t.OFF, 'WAITING FOR DATA')
        else:
            captions = {cfg.LEVEL_INFO: 'ALL NORMAL',
                        cfg.LEVEL_WARNING: 'WARNING',
                        cfg.LEVEL_ALARM: 'ALARM'}
            self._paint_pill(t.level_color(level), captions.get(level, level))

    def _update_telemetry(self, data):
        probe_b = data.get('temperature_b')
        delta = data.get('probe_delta')
        if probe_b is None:
            self.probeTile.set_value('--', t.TEXT_DIM)
        else:
            disagrees = delta is not None and delta > cfg.PROBE_DISAGREE_C
            suffix = ('  Δ%.1f' % delta) if delta is not None else ''
            self.probeTile.set_value('%.1f °C%s' % (probe_b, suffix),
                                     t.ALARM if disagrees else t.OK)

        ambient = data.get('ambient')
        if ambient is None:
            self.ambientTile.set_value('--', t.TEXT_DIM)
        else:
            self.ambientTile.set_value(
                '%.1f °C' % ambient,
                t.WARN if ambient >= cfg.AMBIENT_WARNING_C else t.TEXT)

        operator = data.get('operator')
        if not operator:
            self.operatorTile.set_value('—', t.TEXT_DIM)
        elif operator == cfg.UNKNOWN_OPERATOR:
            self.operatorTile.set_value('no badge', t.WARN)
        else:
            self.operatorTile.set_value(operator, t.TEXT)

        diagnosis = data.get('diagnosis') or ''
        level = data.get('level', cfg.LEVEL_INFO)
        if diagnosis:
            self.diagnosisTile.set_value(diagnosis, t.level_color(level))
        else:
            self.diagnosisTile.set_value('operating normally', t.TEXT_DIM)

    def _update_measurements(self, data):
        """Show each actuator's independent reading, flagged when it contradicts."""
        current = data.get('compressor_current')
        if current is None:
            self.compressorCard.set_measurement('-- A')
        else:
            commanded_on = data.get('compressor') == 'ON'
            drawing = current >= cfg.CURRENT_RUNNING_MIN_A
            mismatch = commanded_on != drawing
            overload = current > cfg.CURRENT_OVERLOAD_A
            color = t.ALARM if (mismatch or overload) else (
                t.OK if drawing else t.TEXT_DIM)
            self.compressorCard.set_measurement('%.2f A' % current, color)

        rpm = data.get('fan_rpm')
        if rpm is None:
            self.fanCard.set_measurement('-- rpm')
        else:
            commanded_on = data.get('fan') == 'ON'
            turning = rpm >= cfg.FAN_RPM_MIN
            if commanded_on != turning:
                color = t.ALARM
            elif turning and rpm < cfg.FAN_RPM_DEGRADED:
                color = t.WARN
            elif turning:
                color = t.OK
            else:
                color = t.TEXT_DIM
            self.fanCard.set_measurement('%d rpm' % int(rpm), color)

    def apply_alert(self, data):
        message = data.get('message', '')
        operator = data.get('operator')
        if operator:
            message += '  ·  %s' % operator
        self.eventLog.add_event(data.get('level', cfg.LEVEL_INFO),
                                data.get('code', ''),
                                message,
                                data.get('ts'))

    def apply_device_status(self, device, state):
        is_on = state == 'ON'
        card = {'compressor': self.compressorCard,
                'fan': self.fanCard,
                'siren': self.sirenCard}.get(device)
        if card:
            card.set_state(is_on)

    def apply_connection(self, connected):
        self.connectionLabel.setText('● connected' if connected else '● offline')
        self.connectionLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 10px; background: transparent; '
            'border: none;' % (t.OK if connected else t.ALARM, t.FONT))
        if not connected:
            self._paint_pill(t.OFF, 'BROKER OFFLINE')

    def toggle_mode(self):
        self.mode = 'MONITORING' if self.mode == 'MAINTENANCE' else 'MAINTENANCE'
        self.mqtt.publish(cfg.TOPIC_MODE_CMD, self.mode, retain=True)
        in_maintenance = self.mode == 'MAINTENANCE'
        self.modeBtn.setText('Leave maintenance' if in_maintenance
                             else 'Maintenance mode')
        self.modeBtn.setStyleSheet(t.outline_button_style(
            t.ACCENT if in_maintenance else t.TEXT_DIM))

    def _paint_pill(self, color, text):
        self.statusPill.setText(text)
        self.statusPill.setStyleSheet(
            'color: #0B1220; background-color: %s; border: none; border-radius: 10px; '
            'font-family: %s; font-size: 14px; font-weight: bold;' % (color, t.FONT))

    def closeEvent(self, event):
        self.mqtt.stop()
        super().closeEvent(event)


if __name__ == '__main__':
    db.init_db()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
