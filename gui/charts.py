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

from ui import icons
from ui import status as stat
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
        self.setMinimumSize(190 if compact else 220, 190 if compact else 230)
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
        """(word, colour, canonical state) - the same six used console-wide."""
        if self.value is None:
            return 'NO DATA', t.OFFLINE_FG, stat.OFFLINE
        if self.stale:
            return 'NOT REPORTING', t.OFFLINE_FG, stat.OFFLINE
        if self.value < self.alarm_min or self.value > self.alarm_max:
            return 'CRITICAL', t.CRITICAL, stat.CRITICAL
        if self.value < self.target_min or self.value > self.target_max:
            return 'WARNING', t.WARN, stat.WARNING
        return 'NORMAL', t.OK, stat.NORMAL

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(t.BORDER), 1))
        painter.setBrush(QColor(t.PANEL))
        painter.drawRoundedRect(QRect(0, 0, w - 1, h - 1), t.RADIUS_LG, t.RADIUS_LG)

        arc_w = 13 if self.compact else 16
        title_h = 30
        avail_h = h - title_h - 32     # room for the range caption at the foot
        radius = int(min((w - 76 - arc_w) / 2.0, (avail_h - arc_w) / 1.5))
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

        status_text, status_color, state = self.status()

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

        # The state in a word and a mark, not only in the colour of the arc.
        painter.setFont(QFont(t.FONT, 8, QFont.Bold))
        metrics = painter.fontMetrics()
        label_w = metrics.width(status_text)
        mark_size = 9
        total = mark_size + 6 + label_w
        left = cx - total / 2.0
        icons.paint(painter, stat.mark(state),
                    QRectF(left, cy + 17, mark_size, mark_size), status_color,
                    width=1.4)
        painter.setPen(QColor(status_color))
        painter.drawText(QRect(int(left + mark_size + 6), cy + 14,
                               label_w + 4, 16),
                         Qt.AlignLeft | Qt.AlignVCenter, status_text)

        # The ends of the scale, each carrying the unit so the number on the
        # dial can be judged without hunting for what it is measured in.
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        unit = self.unit.strip()
        for value in (self.vmin, self.vmax):
            deg = math.radians(self._angle(value))
            # Pushed clear of the arc: at radius + 15 the label sat on top of
            # the stroke, which at the ends of the scale is the thickest and
            # most saturated part of the whole gauge.
            lx = cx + int((radius + arc_w / 2 + 16) * math.cos(deg))
            ly = cy - int((radius + arc_w / 2 + 16) * math.sin(deg)) + 4
            painter.drawText(QRect(lx - 26, ly - 8, 52, 16), Qt.AlignCenter,
                             '%g %s' % (value, unit) if unit else '%g' % value)

        # The band the reading is judged against, said in words underneath.
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        painter.drawText(QRect(0, h - 17, w, 14), Qt.AlignCenter,
                         'Normal %g to %g %s' % (self.target_min,
                                                 self.target_max, unit))
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
    # The gutter has to hold the widest tick label plus its unit, so it is
    # measured rather than guessed - a "1800 rpm" label does not fit the 46 px
    # that "8 °C" did, and used to be clipped.
    def _gutter(self):
        return max(46, min(96, 14 + 7 * len(self._tick_text(self.vmax))))

    def _plot_rect(self):
        top = 34 if self.title else 16
        left = self._gutter()
        return QRectF(left, top, max(1.0, self.width() - left - 14),
                      max(1.0, self.height() - top - 26))

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

    def _tick_text(self, value):
        """A y-axis label, always carrying its unit."""
        unit = self.unit.strip()
        number = '%g' % round(value, 2)
        return ('%s %s' % (number, unit)) if unit else number

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
            self._paint_message(
                painter, rect,
                'Not enough history yet for this range' if self.rows else
                'No readings stored for this range')
            painter.end()
            return

        for trace in self.traces:
            self._paint_trace(painter, rect, trace)
        self._paint_time_axis(painter, rect)
        self._paint_hover(painter, rect)
        painter.end()

    def _paint_legend(self, painter, w):
        """A key for every trace, and for the shaded band behind them."""
        painter.setFont(QFont(t.FONT, 8, QFont.Bold))
        x = w - 16
        entries = [(trace.label, trace.color, 'line') for trace in self.traces]
        for band in self.bands:
            if band.label:
                entries.append((band.label, band.color, 'band'))
        for text, color, kind in reversed(entries):
            width = painter.fontMetrics().width(text) + 20
            x -= width
            if kind == 'band':
                swatch = QColor(color)
                swatch.setAlpha(110)
                painter.setPen(Qt.NoPen)
                painter.setBrush(swatch)
                painter.drawRect(QRectF(x, 14, 11, 8))
                painter.setBrush(Qt.NoBrush)
            else:
                painter.setPen(QPen(QColor(color), 2))
                painter.drawLine(int(x), 18, int(x) + 11, 18)
            painter.setPen(QColor(t.TEXT_DIM))
            painter.drawText(QRect(int(x) + 15, 10, width, 16), Qt.AlignLeft,
                             text)

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
        """Grid lines at the values that mean something, with labelled units.

        The lines are the scale ends, the edges of the acceptable band and the
        hard limits - the numbers an operator actually judges a reading
        against. Labels are suppressed where two of them would collide, which
        is what used to make the humidity chart print 100 / 85 / 70 on top of
        one another; the line is still drawn, only its label is dropped.
        """
        painter.setFont(QFont(t.FONT, 8))
        values = [self.vmin, self.vmax]
        values += [th.value for th in self.thresholds]
        for band in self.bands:
            values += [band.low, band.high]

        gutter = self._gutter()
        drawn = []
        for value in sorted(set(values)):
            y = self._y(value, rect)
            # A threshold is drawn in its own colour: the fan chart carries a
            # worn-bearing warning at 900 rpm and a stalled alarm at 300, and
            # painting both in alarm red said the wrong thing about the first.
            limit = next((th for th in self.thresholds
                          if abs(value - th.value) < 1e-9), None)
            color = limit.color if limit else t.BORDER
            painter.setPen(QPen(QColor(color), 1,
                                Qt.DashLine if limit else Qt.SolidLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

            # A label needs 13 px of clear vertical space to stay legible.
            if any(abs(y - other) < 13 for other in drawn):
                continue
            drawn.append(y)
            painter.setPen(QColor(color if limit else t.TEXT_MUTED))
            painter.drawText(QRectF(2, y - 8, gutter - 8, 16),
                             Qt.AlignRight | Qt.AlignVCenter,
                             self._tick_text(value))

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
        """Time labels along the foot, as many as the width will carry.

        Three fixed labels left a wide chart almost unreadable and a narrow one
        with its last label clipped off the right edge. The count now follows
        the width, and the first and last are aligned inwards so both stay
        inside the plot.
        """
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        count = len(self.rows)
        ticks = max(2, min(7, int(rect.width() // 110)))
        span_days = self._span_days()
        indices = sorted({int(round(i * (count - 1) / float(ticks - 1)))
                          for i in range(ticks)})
        for index in indices:
            when = _parse(self.rows[index].get('bucket_ts'))
            if not when:
                continue
            x = self._x(index, rect)
            if index == 0:
                align, box = Qt.AlignLeft, QRectF(x, rect.bottom() + 5, 80, 14)
            elif index == count - 1:
                align = Qt.AlignRight
                box = QRectF(x - 80, rect.bottom() + 5, 80, 14)
            else:
                align = Qt.AlignHCenter
                box = QRectF(x - 40, rect.bottom() + 5, 80, 14)
            # Over a multi-day range the clock alone is ambiguous.
            painter.drawText(box, align, when.strftime(
                '%d %b' if span_days >= 2 else '%H:%M'))

    def _span_days(self):
        first = _parse(self.rows[0].get('bucket_ts'))
        last = _parse(self.rows[-1].get('bucket_ts'))
        if not first or not last:
            return 0
        return (last - first).total_seconds() / 86400.0

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

    def __init__(self, rows_spec, minimum_height=126):
        super().__init__()
        self.rows_spec = list(rows_spec)   # [(field, label, color), ...]
        self.rows = []
        self._loading = True
        self.setMinimumHeight(minimum_height)
        self.setMouseTracking(True)
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
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        painter.drawText(QRect(16, 10, w - 32, 16), Qt.AlignRight,
                         'darker = more of that period spent on')

        left, right, top = 92, w - 16, 34
        lane_h = 15
        gap = 9

        if self._loading or not self.rows:
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.setFont(QFont(t.FONT, 10))
            painter.drawText(QRect(left, top, right - left, h - top - 12),
                             Qt.AlignCenter,
                             'Loading…' if self._loading
                             else 'No door openings or equipment runs recorded '
                                  'in this range')
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

        # Without a time axis the ribbon says how much but never when.
        self._paint_time_axis(painter, left, right,
                              top + len(self.rows_spec) * (lane_h + gap) - gap)
        painter.end()

    def _paint_time_axis(self, painter, left, right, top):
        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        count = len(self.rows)
        ticks = max(2, min(6, int((right - left) // 120)))
        first = _parse(self.rows[0].get('bucket_ts'))
        last = _parse(self.rows[-1].get('bucket_ts'))
        multiday = bool(first and last
                        and (last - first).total_seconds() >= 2 * 86400)
        for step in range(ticks):
            index = int(round(step * (count - 1) / float(ticks - 1)))
            when = _parse(self.rows[index].get('bucket_ts'))
            if not when:
                continue
            x = left + (index / float(max(1, count - 1))) * (right - left)
            if step == 0:
                align, box = Qt.AlignLeft, QRectF(x, top + 6, 80, 13)
            elif step == ticks - 1:
                align, box = Qt.AlignRight, QRectF(x - 80, top + 6, 80, 13)
            else:
                align, box = Qt.AlignHCenter, QRectF(x - 40, top + 6, 80, 13)
            painter.drawText(box, align,
                             when.strftime('%d %b' if multiday else '%H:%M'))


# ===========================================================================
class Sparkline(QFrame):
    """A tiny inline trend on a device card: the last few minutes of a reading.

    It sits on its own tinted strip with the range it covers printed at the
    right. Without those the line was a stray stroke across the card with no
    scale, which is worse than no chart: a flat line and a violent one looked
    identical because the strip rescales to whatever it holds.
    """

    def __init__(self, color=t.ACCENT, maxlen=48, height=34, unit=''):
        super().__init__()
        self.color = color
        self.unit = unit
        self.values = deque(maxlen=maxlen)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip('Recent history: the last %d readings from this '
                        'device.' % maxlen)

    def add(self, value):
        if value is None:
            return
        self.values.append(float(value))
        self.update()

    def clear(self):
        self.values.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.PANEL_ALT))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 4, 4)

        if len(self.values) < 2:
            painter.setPen(QColor(t.TEXT_MUTED))
            painter.setFont(QFont(t.FONT, 8))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                             'collecting history…')
            painter.end()
            return

        low, high = min(self.values), max(self.values)
        flat = (high - low) < 1e-9
        span = (high - low) or 1.0
        # Leave room on the right for the range caption.
        plot_w = max(10.0, w - 62.0)
        step = plot_w / float(len(self.values) - 1)
        points = QPolygonF()
        for index, value in enumerate(self.values):
            # A reading that has not moved is drawn down the middle of the
            # strip. Pinned to the floor it read as a value sitting at the
            # bottom of some range, which is not what it means.
            y = (h / 2.0 if flat
                 else h - 5 - ((value - low) / span) * (h - 11))
            points.append(QPointF(4 + index * step, y))
        painter.setPen(QPen(QColor(self.color), 1.6, Qt.SolidLine, Qt.RoundCap,
                            Qt.RoundJoin))
        painter.drawPolyline(points)

        painter.setPen(QColor(t.TEXT_MUTED))
        painter.setFont(QFont(t.FONT, 8))
        caption = ('flat at %g' % round(low, 2) if high - low < 1e-9
                   else '%g–%g' % (round(low, 2), round(high, 2)))
        painter.drawText(QRectF(w - 58, 0, 54, h),
                         Qt.AlignRight | Qt.AlignVCenter, caption)
        painter.end()
