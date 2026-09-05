"""Painted data-visualisation widgets.

All of these draw with QPainter rather than pulling in a charting library: the
shapes needed here are simple, and hand-drawing them keeps the thresholds, the
safe band and the fault shading as first-class parts of the picture instead of
annotations bolted on afterwards.

Two ideas run through the module:

* **Context beats precision.** A temperature of 8.4 C means nothing on its own.
  Every chart draws the acceptable band and the hard limits behind the data, so
  a glance answers "is this bad?" before the eye ever reaches an axis label.
* **History is bucketed upstream.** The database returns roughly one point per
  pixel column, so a seven-day view costs the same to draw as an hourly one.
"""

import math
from collections import deque
from datetime import datetime

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPolygonF)
from PyQt5.QtWidgets import QFrame, QSizePolicy, QToolTip

from config import mqtt_init as cfg
from ui import theme as t

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _parse(ts):
    try:
        return datetime.strptime(ts, TIME_FORMAT)
    except (TypeError, ValueError):
        return None


class Band(object):
    """A shaded horizontal region, such as the 2-8 C storage band."""

    def __init__(self, low, high, color, alpha=34, label=None):
        self.low = low
        self.high = high
        self.color = color
        self.alpha = alpha
        self.label = label


class Threshold(object):
    """A dashed limit line."""

    def __init__(self, value, color, label=None):
        self.value = value
        self.color = color
        self.label = label


class Trace(object):
    """One plotted field."""

    def __init__(self, field, label, color, fill=False, width=2.0, unit=''):
        self.field = field
        self.label = label
        self.color = color
        self.fill = fill
        self.width = width
        self.unit = unit


# ===========================================================================
class ArcGauge(QFrame):
    """Speedometer-style gauge with the acceptable band drawn on the arc."""

    START = 210      # degrees, Qt convention (counter clockwise from 3 o'clock)
    SPAN = -240      # sweep clockwise over the top

    def __init__(self, title, unit, vmin, vmax, target_min, target_max,
                 alarm_min, alarm_max, compact=False):
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
        self.stale = False
        self.compact = compact
        self.setMinimumSize(220 if compact else 260, 190 if compact else 230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, value, stale=False):
        self.value = value
        self.stale = stale
        self.update()

    def _fraction(self, value):
        span = self.vmax - self.vmin
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (value - self.vmin) / span))

    def _angle(self, value):
        return self.START + self.SPAN * self._fraction(value)

    def status(self):
        if self.value is None:
            return 'NO DATA', t.OFF, cfg.LEVEL_INFO
        if self.stale:
            return 'STALE', t.OFF, cfg.LEVEL_WARNING
        if self.value < self.alarm_min or self.value > self.alarm_max:
            return 'CRITICAL', t.CRITICAL, cfg.LEVEL_CRITICAL
        if self.value < self.target_min or self.value > self.target_max:
            return 'WARNING', t.WARN, cfg.LEVEL_WARNING
        return 'IN RANGE', t.OK, cfg.LEVEL_INFO

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), t.RADIUS_LG, t.RADIUS_LG)

        arc_w = 13 if self.compact else 16
        title_h = 30
        avail_h = h - title_h - 16
        radius = int(min((w - 44 - arc_w) / 2.0, (avail_h - arc_w) / 1.5))
        radius = max(radius, 34)
        cx = w // 2
        cy = title_h + radius + arc_w // 2
        box = QRect(cx - radius, cy - radius, radius * 2, radius * 2)

        painter.setPen(QPen(QColor('#0B1120'), arc_w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(box, self.START * 16, self.SPAN * 16)

        band_start = self._angle(self.target_min)
        band_span = self._angle(self.target_max) - band_start
        band = QColor(t.OK)
        band.setAlpha(80)
        painter.setPen(QPen(band, arc_w, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(box, int(band_start * 16), int(band_span * 16))

        status_text, status_color, _level = self.status()

        if self.value is not None:
            span = self._angle(self.value) - self.START
            painter.setPen(QPen(QColor(status_color), arc_w, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(box, self.START * 16, int(span * 16))

        painter.setPen(QColor(t.TEXT_DIM))
        painter.setFont(QFont(t.FONT, 9, QFont.Bold))
        painter.drawText(QRect(0, 9, w, 18), Qt.AlignCenter, self.title.upper())

        text = '--' if self.value is None else ('%.1f%s' % (self.value, self.unit))
        painter.setPen(QColor(status_color if self.value is not None else t.TEXT_DIM))
        painter.setFont(QFont(t.FONT, 26 if self.compact else 30, QFont.Bold))
        painter.drawText(QRect(cx - 116, cy - 32, 232, 46), Qt.AlignCenter, text)

        painter.setFont(QFont(t.FONT, 8, QFont.Bold))
        painter.drawText(QRect(cx - 84, cy + 14, 168, 16), Qt.AlignCenter,
                         '%s  %s' % (t.level_glyph(self.status()[2]), status_text))

        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        for value in (self.vmin, self.vmax):
            deg = math.radians(self._angle(value))
            lx = cx + int((radius + 14) * math.cos(deg))
            ly = cy - int((radius + 14) * math.sin(deg))
            painter.drawText(QRect(lx - 20, ly - 8, 40, 16), Qt.AlignCenter,
                             '%g' % value)
        painter.end()


# ===========================================================================
class TimeSeriesChart(QFrame):
    """Multi-trace history with bands, limits and a hover readout."""

    def __init__(self, traces, vmin, vmax, bands=(), thresholds=(), unit='',
                 title='', minimum_height=210):
        super().__init__()
        self.traces = list(traces)
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.bands = list(bands)
        self.thresholds = list(thresholds)
        self.unit = unit
        self.title = title
        self.rows = []
        self._hover_index = None
        self._loading = True

        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    # -- data --------------------------------------------------------------
    def set_rows(self, rows):
        self.rows = rows or []
        self._loading = False
        self.update()

    def set_loading(self):
        self._loading = True
        self.update()

    # -- geometry ----------------------------------------------------------
    def _plot_rect(self):
        top = 34 if self.title else 16
        return QRectF(46, top, max(1.0, self.width() - 60),
                      max(1.0, self.height() - top - 24))

    def _y(self, value, rect):
        span = self.vmax - self.vmin
        if span <= 0:
            return rect.bottom()
        frac = max(0.0, min(1.0, (value - self.vmin) / span))
        return rect.bottom() - frac * rect.height()

    def _x(self, index, rect):
        if len(self.rows) <= 1:
            return rect.left()
        return rect.left() + (index / float(len(self.rows) - 1)) * rect.width()

    # -- interaction -------------------------------------------------------
    def mouseMoveEvent(self, event):
        rect = self._plot_rect()
        if not self.rows or not rect.contains(event.pos()):
            if self._hover_index is not None:
                self._hover_index = None
                self.update()
            return
        frac = (event.pos().x() - rect.left()) / max(1.0, rect.width())
        index = int(round(frac * (len(self.rows) - 1)))
        index = max(0, min(len(self.rows) - 1, index))
        if index != self._hover_index:
            self._hover_index = index
            self.update()
        QToolTip.showText(event.globalPos(), self._tooltip_text(index), self)

    def leaveEvent(self, event):
        self._hover_index = None
        QToolTip.hideText()
        self.update()

    def _tooltip_text(self, index):
        row = self.rows[index]
        when = _parse(row.get('bucket_ts'))
        lines = [when.strftime('%d %b  %H:%M') if when else '--']
        for trace in self.traces:
            value = row.get(trace.field)
            lines.append('%s: %s' % (
                trace.label,
                '--' if value is None else '%.2f%s' % (value, trace.unit or self.unit)))
        return '\n'.join(lines)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), t.RADIUS_LG, t.RADIUS_LG)

        if self.title:
            painter.setPen(QColor(t.TEXT_DIM))
            painter.setFont(QFont(t.FONT, 9, QFont.Bold))
            painter.drawText(QRect(16, 11, w - 32, 16), Qt.AlignLeft,
                             self.title.upper())
            self._paint_legend(painter, w)

        rect = self._plot_rect()
        self._paint_bands(painter, rect)
        self._paint_grid(painter, rect)

        if self._loading:
            self._paint_message(painter, rect, 'Loading history…')
            painter.end()
            return
        if len(self.rows) < 2:
            self._paint_message(painter, rect,
                                'Not enough history yet for this range')
            painter.end()
            return

        for trace in self.traces:
            self._paint_trace(painter, rect, trace)
        self._paint_time_axis(painter, rect)
        self._paint_hover(painter, rect)
        painter.end()

    def _paint_legend(self, painter, w):
        painter.setFont(QFont(t.FONT, 8, QFont.Bold))
        x = w - 16
        for trace in reversed(self.traces):
            text = trace.label
            width = painter.fontMetrics().width(text) + 18
            x -= width
            painter.setPen(QPen(QColor(trace.color), 2))
            painter.drawLine(int(x), 18, int(x) + 10, 18)
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.drawText(QRect(int(x) + 14, 10, width, 16), Qt.AlignLeft, text)

    def _paint_bands(self, painter, rect):
        painter.setPen(Qt.NoPen)
        for band in self.bands:
            color = QColor(band.color)
            color.setAlpha(band.alpha)
            painter.setBrush(color)
            top = self._y(band.high, rect)
            bottom = self._y(band.low, rect)
            painter.drawRect(QRectF(rect.left(), top, rect.width(), bottom - top))

    def _paint_grid(self, painter, rect):
        painter.setFont(QFont(t.FONT, 8))
        values = [self.vmin, self.vmax]
        values += [th.value for th in self.thresholds]
        for band in self.bands:
            values += [band.low, band.high]
        for value in sorted(set(values)):
            y = self._y(value, rect)
            limit = any(abs(value - th.value) < 1e-9 for th in self.thresholds)
            color = t.CRITICAL if limit else t.BORDER
            painter.setPen(QPen(QColor(color), 1,
                                Qt.DashLine if limit else Qt.SolidLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.drawText(QRectF(2, y - 8, 40, 16),
                             Qt.AlignRight | Qt.AlignVCenter, '%g' % value)

    def _paint_trace(self, painter, rect, trace):
        points = QPolygonF()
        for index, row in enumerate(self.rows):
            value = row.get(trace.field)
            if value is None:
                continue
            points.append(QPointF(self._x(index, rect), self._y(value, rect)))
        if points.count() < 2:
            return

        if trace.fill:
            path = QPainterPath()
            path.moveTo(points[0].x(), rect.bottom())
            for point in points:
                path.lineTo(point)
            path.lineTo(points[points.count() - 1].x(), rect.bottom())
            path.closeSubpath()
            gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            top_color = QColor(trace.color)
            top_color.setAlpha(70)
            bottom_color = QColor(trace.color)
            bottom_color.setAlpha(0)
            gradient.setColorAt(0.0, top_color)
            gradient.setColorAt(1.0, bottom_color)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(path)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(trace.color), trace.width, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        painter.drawPolyline(points)

        last = points[points.count() - 1]
        painter.setBrush(QColor(trace.color))
        painter.setPen(QPen(QColor(t.PANEL), 2))
        painter.drawEllipse(last, 3.6, 3.6)

    def _paint_time_axis(self, painter, rect):
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        count = len(self.rows)
        for index in (0, count // 2, count - 1):
            when = _parse(self.rows[index].get('bucket_ts'))
            if not when:
                continue
            x = self._x(index, rect)
            align = Qt.AlignHCenter
            if index == 0:
                align = Qt.AlignLeft
            elif index == count - 1:
                align = Qt.AlignRight
            painter.drawText(QRectF(x - 40, rect.bottom() + 5, 80, 14), align,
                             when.strftime('%H:%M'))

    def _paint_hover(self, painter, rect):
        if self._hover_index is None:
            return
        x = self._x(self._hover_index, rect)
        painter.setPen(QPen(QColor(t.BORDER_STRONG), 1, Qt.DashLine))
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        row = self.rows[self._hover_index]
        for trace in self.traces:
            value = row.get(trace.field)
            if value is None:
                continue
            painter.setBrush(QColor(trace.color))
            painter.setPen(QPen(QColor(t.PANEL), 2))
            painter.drawEllipse(QPointF(x, self._y(value, rect)), 4.2, 4.2)

    def _paint_message(self, painter, rect, text):
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 10))
        painter.drawText(rect, Qt.AlignCenter, text)


# ===========================================================================
class StateTimeline(QFrame):
    """A ribbon showing how much of each bucket a binary state was active.

    Door openings and compressor duty do not belong on a value axis - what
    matters is *when* and *for how long*, which reads far better as a band of
    density than as a square wave.
    """

    def __init__(self, rows_spec, minimum_height=104):
        super().__init__()
        self.rows_spec = list(rows_spec)   # [(field, label, color), ...]
        self.rows = []
        self._loading = True
        self.setMinimumHeight(minimum_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_rows(self, rows):
        self.rows = rows or []
        self._loading = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), t.RADIUS_LG, t.RADIUS_LG)

        painter.setPen(QColor(t.TEXT_DIM))
        painter.setFont(QFont(t.FONT, 9, QFont.Bold))
        painter.drawText(QRect(16, 10, w - 32, 16), Qt.AlignLeft, 'ACTIVITY')

        left, right, top = 92, w - 16, 32
        lane_h = 15
        gap = 9

        if self._loading or not self.rows:
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.setFont(QFont(t.FONT, 10))
            painter.drawText(QRect(left, top, right - left, h - top - 12),
                             Qt.AlignCenter,
                             'Loading…' if self._loading else 'No activity recorded')
            painter.end()
            return

        width = max(1.0, (right - left) / float(len(self.rows)))
        for lane, (field, text, color) in enumerate(self.rows_spec):
            y = top + lane * (lane_h + gap)
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.setFont(QFont(t.FONT, 9))
            painter.drawText(QRect(12, y, 74, lane_h),
                             Qt.AlignLeft | Qt.AlignVCenter, text)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.PANEL_ALT))
            painter.drawRoundedRect(QRectF(left, y, right - left, lane_h), 4, 4)

            for index, row in enumerate(self.rows):
                fraction = row.get(field)
                if not fraction:
                    continue
                shade = QColor(color)
                shade.setAlpha(int(60 + 195 * min(1.0, float(fraction))))
                painter.setBrush(shade)
                painter.drawRect(QRectF(left + index * width, y,
                                        max(1.0, width), lane_h))
        painter.end()


# ===========================================================================
class Sparkline(QFrame):
    """A tiny inline trend, used on device cards."""

    def __init__(self, color=t.ACCENT, maxlen=48, height=34):
        super().__init__()
        self.color = color
        self.values = deque(maxlen=maxlen)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def add(self, value):
        if value is None:
            return
        self.values.append(float(value))
        self.update()

    def clear(self):
        self.values.clear()
        self.update()

    def paintEvent(self, event):
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        low, high = min(self.values), max(self.values)
        span = (high - low) or 1.0
        step = self.width() / float(len(self.values) - 1)
        points = QPolygonF()
        for index, value in enumerate(self.values):
            y = self.height() - 4 - ((value - low) / span) * (self.height() - 9)
            points.append(QPointF(index * step, y))
        painter.setPen(QPen(QColor(self.color), 1.6, Qt.SolidLine, Qt.RoundCap,
                            Qt.RoundJoin))
        painter.drawPolyline(points)
        painter.end()
