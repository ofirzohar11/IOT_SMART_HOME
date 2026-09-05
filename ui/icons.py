"""Line-art icons drawn with QPainter.

The console previously used emoji for its device icons. Emoji are rendered by
the operating system's colour font, which means a pharmaceutical monitoring
console picked up a brown door, a red-and-white thermometer and a flashing
police light - consumer artwork, at whatever size and weight the platform
happened to choose, in colours that clashed with a palette where green, amber
and red are reserved for state.

These are stroked paths on a 24x24 grid instead: one weight, one colour, and
they take the colour of whatever they are describing. Nothing here is
decorative - every icon names a real device or a real page, and the label
beside it always says the same thing in words.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from ui import theme as t

GRID = 24.0


# ---------------------------------------------------------------------------
#  Path builders. Each returns a list of sub-paths on the 24x24 grid; a
#  sub-path is (kind, payload) where kind is one of 'poly', 'line', 'ellipse',
#  'arc', 'dot'.
# ---------------------------------------------------------------------------
def _thermometer():
    """A stem with a bulb: the reading the whole system exists to protect."""
    return [
        ('line', (10.3, 6.4, 10.3, 14.9)),
        ('line', (13.7, 6.4, 13.7, 14.9)),
        ('arc', (10.3, 4.7, 3.4, 3.4, 0, 180)),
        ('ellipse', (8.5, 14.4, 7.0, 7.0)),
        ('line', (15.4, 8.2, 17.6, 8.2)),
        ('line', (15.4, 11.4, 17.6, 11.4)),
    ]


def _room():
    """A building: the sensor that watches the storeroom, not the cabinet."""
    return [
        ('poly', [(3.5, 10.5), (12, 4.0), (20.5, 10.5)]),
        ('poly', [(5.5, 9.6), (5.5, 20), (18.5, 20), (18.5, 9.6)]),
        ('poly', [(10, 20), (10, 14.5), (14, 14.5), (14, 20)]),
    ]


def _door():
    return [
        ('poly', [(6, 3.5), (18, 3.5), (18, 20.5), (6, 20.5), (6, 3.5)]),
        ('ellipse', (14.2, 11.0, 1.8, 1.8)),
        ('line', (4, 20.5, 20, 20.5)),
    ]


def _badge():
    """An ID card: the reader that names who opened the door."""
    return [
        ('poly', [(3.5, 6), (20.5, 6), (20.5, 18), (3.5, 18), (3.5, 6)]),
        ('ellipse', (7.0, 9.0, 4.0, 4.0)),
        ('poly', [(6.2, 15.6), (6.9, 14.2), (11.1, 14.2), (11.8, 15.6)]),
        ('line', (14, 10, 18, 10)),
        ('line', (14, 13.4, 18, 13.4)),
    ]


def _battery():
    """Mains vs. backup: a battery with a charge bar."""
    return [
        ('poly', [(3, 7.5), (18, 7.5), (18, 16.5), (3, 16.5), (3, 7.5)]),
        ('poly', [(20, 10.5), (20, 13.5)]),
        ('line', (5.6, 10.2, 5.6, 13.8)),
        ('line', (8.6, 10.2, 8.6, 13.8)),
        ('line', (11.6, 10.2, 11.6, 13.8)),
    ]


def _bolt():
    """Current draw: what the motor really pulls."""
    return [
        ('poly', [(13.5, 2.5), (5.5, 13.5), (11.5, 13.5), (10.5, 21.5),
                  (18.5, 10.5), (12.5, 10.5), (13.5, 2.5)]),
    ]


def _fan():
    """Three blades around a hub.

    Drawn without an enclosing ring: at the 16-18 px these are used at, a ring
    plus three blades plus a hub collapsed into an illegible disc.
    """
    return [
        ('blade', (12, 12, 90)),
        ('blade', (12, 12, 210)),
        ('blade', (12, 12, 330)),
        ('ellipse', (10.3, 10.3, 3.4, 3.4)),
    ]


def _power_switch():
    """The IEC power symbol: a device that switches something on and off.

    A snowflake was the obvious mark for a compressor relay and it was tried
    first, but six barbed arms drawn at the 16 px these cards use collapse
    into a solid six-pointed star - a decorative sparkle, which is the one
    thing a monitoring console must not look like. A break in a ring with a
    stem through it stays legible at any size, and it is the more accurate
    label anyway: this device is a switch, and what it is switching is
    already written next to it.
    """
    return [
        ('arc', (4.4, 4.4, 15.2, 15.2, 62, 356)),
        ('line', (12, 2.6, 12, 11.4)),
    ]


def _siren():
    """A warning beacon with its light throwing off to the sides."""
    return [
        ('arc', (7.0, 7.4, 10.0, 10.0, 0, 180)),
        ('poly', [(7.0, 12.4), (7.0, 17.0), (17.0, 17.0), (17.0, 12.4)]),
        ('poly', [(5.0, 19.6), (19.0, 19.6)]),
        ('line', (12, 2.6, 12, 5.0)),
        ('line', (4.2, 6.0, 6.1, 7.4)),
        ('line', (19.8, 6.0, 17.9, 7.4)),
    ]


# -- navigation -------------------------------------------------------------
def _gauge():
    return [
        ('arc', (3.5, 5.0, 17.0, 17.0, 20, 140)),
        ('poly', [(12, 13.5), (16.4, 9.4)]),
        ('ellipse', (10.8, 12.3, 2.4, 2.4)),
        ('line', (12, 5.0, 12, 6.8)),
        ('line', (4.7, 9.4, 6.3, 10.3)),
        ('line', (19.3, 9.4, 17.7, 10.3)),
    ]


def _devices():
    """A sensor module: a chip with pins."""
    return [
        ('poly', [(7, 7), (17, 7), (17, 17), (7, 17), (7, 7)]),
        ('poly', [(10.2, 10.2), (13.8, 10.2), (13.8, 13.8), (10.2, 13.8),
                  (10.2, 10.2)]),
        ('line', (10, 3.6, 10, 7)),
        ('line', (14, 3.6, 14, 7)),
        ('line', (10, 17, 10, 20.4)),
        ('line', (14, 17, 14, 20.4)),
        ('line', (3.6, 10, 7, 10)),
        ('line', (3.6, 14, 7, 14)),
        ('line', (17, 10, 20.4, 10)),
        ('line', (17, 14, 20.4, 14)),
    ]


def _flag():
    return [
        ('poly', [(6, 3.2), (6, 21)]),
        ('poly', [(6, 4.6), (18.5, 4.6), (15.6, 9.2), (18.5, 13.8), (6, 13.8)]),
    ]


def _flask():
    """A test rig: the drill page."""
    return [
        ('poly', [(9.2, 3.2), (14.8, 3.2)]),
        ('poly', [(10.4, 3.2), (10.4, 9.6), (4.9, 18.4), (19.1, 18.4),
                  (13.6, 9.6), (13.6, 3.2)]),
        ('line', (7.6, 14.2, 16.4, 14.2)),
    ]


def _table():
    return [
        ('poly', [(3.5, 4.5), (20.5, 4.5), (20.5, 19.5), (3.5, 19.5), (3.5, 4.5)]),
        ('line', (3.5, 9.3, 20.5, 9.3)),
        ('line', (3.5, 14.4, 20.5, 14.4)),
        ('line', (9.6, 9.3, 9.6, 19.5)),
    ]


def _gear():
    return [
        ('arc', (6.4, 6.4, 11.2, 11.2, 0, 360)),
        ('arc', (9.4, 9.4, 5.2, 5.2, 0, 360)),
    ] + [('tooth', (12, 12, angle)) for angle in (0, 60, 120, 180, 240, 300)]


def _humidity():
    """A droplet, for the humidity reading."""
    return [
        ('drop', (12, 3.8, 6.6)),
    ]


def _fridge():
    """The product mark: the cabinet itself.

    A bare snowflake was tried here first and, at the 18 px the rail draws it,
    six barbed arms read as a decorative starburst rather than as ice - the
    exact ornament this console has no business wearing. A cabinet with a
    freezer compartment and a handle cannot be mistaken for anything else.
    """
    return [
        ('poly', [(5.5, 2.8), (18.5, 2.8), (18.5, 21.2), (5.5, 21.2),
                  (5.5, 2.8)]),
        ('line', (5.5, 9.4, 18.5, 9.4)),
        ('line', (8.4, 5.4, 8.4, 7.6)),
        ('line', (8.4, 11.8, 8.4, 15.2)),
    ]


def _clock():
    return [
        ('arc', (3.5, 3.5, 17.0, 17.0, 0, 360)),
        ('poly', [(12, 7.2), (12, 12), (15.6, 14.2)]),
    ]


def _download():
    return [
        ('poly', [(12, 3.5), (12, 15)]),
        ('poly', [(7.4, 10.6), (12, 15.2), (16.6, 10.6)]),
        ('poly', [(4.5, 19.5), (19.5, 19.5)]),
    ]


ICONS = {
    'thermometer': _thermometer, 'room': _room, 'door': _door, 'badge': _badge,
    'battery': _battery, 'bolt': _bolt, 'fan': _fan,
    'power_switch': _power_switch,
    'siren': _siren, 'gauge': _gauge, 'devices': _devices, 'flag': _flag,
    'flask': _flask, 'table': _table, 'gear': _gear, 'humidity': _humidity,
    'clock': _clock, 'download': _download, 'fridge': _fridge,
}


# ---------------------------------------------------------------------------
#  Status marks
#
#  These are the shapes that carry state beside every colour in the console.
#  They are painted rather than typed because the geometric-shape characters
#  they replace (a filled square, a gear, a diamond) are absent from the
#  default UI font on every platform: Qt silently substituted a different
#  font for each one, so a row of status chips was a row of mismatched
#  weights and sizes. Painting them keeps one weight and one size everywhere.
# ---------------------------------------------------------------------------
def _mark_normal():
    return [('ellipse', (5.5, 5.5, 13.0, 13.0))]


def _mark_warning():
    return [('poly', [(12, 3.6), (21.4, 20.4), (2.6, 20.4), (12, 3.6)])]


def _mark_critical():
    return [('poly', [(4.4, 4.4), (19.6, 4.4), (19.6, 19.6), (4.4, 19.6),
                      (4.4, 4.4)])]


def _mark_offline():
    return [('ellipse', (5.0, 5.0, 14.0, 14.0))]


def _mark_maintenance():
    """A cog: deliberately excused from alarming while the unit is serviced."""
    return [
        ('arc', (5.4, 5.4, 13.2, 13.2, 0, 360)),
        ('arc', (9.4, 9.4, 5.2, 5.2, 0, 360)),
    ] + [('smalltooth', (12, 12, angle))
         for angle in (0, 60, 120, 180, 240, 300)]


def _mark_simulated():
    return [('poly', [(12, 2.8), (21.2, 12), (12, 21.2), (2.8, 12), (12, 2.8)])]


def _info():
    return [
        ('arc', (3.4, 3.4, 17.2, 17.2, 0, 360)),
        ('ellipse', (11.05, 6.6, 1.9, 1.9)),
        ('line', (12, 11.0, 12, 17.4)),
    ]


def _check():
    return [('poly', [(4.8, 12.6), (9.8, 17.6), (19.2, 6.4)])]


def _chevron_right():
    return [('poly', [(9.4, 5.6), (16.2, 12), (9.4, 18.4)])]


def _chevron_down():
    return [('poly', [(5.6, 9.4), (12, 16.2), (18.4, 9.4)])]


def _arrow_right():
    return [
        ('poly', [(3.6, 12), (20.4, 12)]),
        ('poly', [(14.4, 6.0), (20.4, 12), (14.4, 18.0)]),
    ]


def _shield():
    """Nothing wrong: used by the "all clear" empty states."""
    return [
        ('poly', [(12, 3.2), (19.8, 6.4), (19.8, 12.0)]),
        ('poly', [(19.8, 12.0), (19.8, 12.6)]),
        ('poly', [(4.2, 6.4), (12, 3.2)]),
        ('poly', [(4.2, 6.4), (4.2, 12.2)]),
        ('poly', [(4.2, 12.2), (12, 20.8), (19.8, 12.2)]),
        ('poly', [(8.6, 12.0), (11.2, 14.6), (15.6, 9.4)]),
    ]


ICONS.update({
    'mark_normal': _mark_normal, 'mark_warning': _mark_warning,
    'mark_critical': _mark_critical, 'mark_offline': _mark_offline,
    'mark_maintenance': _mark_maintenance, 'mark_simulated': _mark_simulated,
    'info': _info, 'check': _check, 'chevron_right': _chevron_right,
    'chevron_down': _chevron_down, 'arrow_right': _arrow_right,
    'shield': _shield,
})

# Icons drawn as a solid shape rather than an outline. A filled mark reads as
# "this is the state", an outline as "this state is absent" - which is exactly
# the difference between an active alarm and an offline device.
FILLED = {'mark_normal', 'mark_warning', 'mark_critical', 'mark_simulated'}


# ---------------------------------------------------------------------------
def _blade(path, cx, cy, degrees):
    """One curved fan blade, swept out from the hub."""
    import math
    rad = math.radians(degrees)

    def point(distance, offset):
        angle = rad + offset
        return QPointF(cx + distance * math.cos(angle),
                       cy - distance * math.sin(angle))

    path.moveTo(point(2.0, 1.30))
    path.quadTo(point(9.2, 0.78), point(9.6, -0.06))
    path.quadTo(point(5.6, -0.62), point(2.0, 1.30))


def _tooth(path, cx, cy, degrees, inner=5.4, outer=8.4, spread=0.30):
    """One short cog tooth, standing off the gear body."""
    import math
    rad = math.radians(degrees)
    a1, a2 = rad - spread, rad + spread
    b1, b2 = rad - spread * 0.66, rad + spread * 0.66
    path.moveTo(QPointF(cx + inner * math.cos(a1), cy - inner * math.sin(a1)))
    path.lineTo(QPointF(cx + outer * math.cos(b1), cy - outer * math.sin(b1)))
    path.lineTo(QPointF(cx + outer * math.cos(b2), cy - outer * math.sin(b2)))
    path.lineTo(QPointF(cx + inner * math.cos(a2), cy - inner * math.sin(a2)))


def _drop(path, cx, top, size):
    path.moveTo(QPointF(cx, top))
    path.cubicTo(QPointF(cx + size, top + size * 0.95),
                 QPointF(cx + size * 0.98, top + size * 2.35),
                 QPointF(cx, top + size * 2.35))
    path.cubicTo(QPointF(cx - size * 0.98, top + size * 2.35),
                 QPointF(cx - size, top + size * 0.95),
                 QPointF(cx, top))


def build_path(name):
    """Return a QPainterPath on the 24x24 grid, or None for an unknown name."""
    factory = ICONS.get(name)
    if factory is None:
        return None
    path = QPainterPath()
    for kind, payload in factory():
        if kind == 'poly':
            points = [QPointF(x, y) for x, y in payload]
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
        elif kind == 'line':
            x1, y1, x2, y2 = payload
            path.moveTo(QPointF(x1, y1))
            path.lineTo(QPointF(x2, y2))
        elif kind == 'ellipse':
            x, y, w, h = payload
            path.addEllipse(QRectF(x, y, w, h))
        elif kind == 'arc':
            x, y, w, h, start, span = payload
            path.arcMoveTo(QRectF(x, y, w, h), start)
            path.arcTo(QRectF(x, y, w, h), start, span)
        elif kind == 'blade':
            _blade(path, *payload)
        elif kind == 'tooth':
            _tooth(path, *payload)
        elif kind == 'smalltooth':
            _tooth(path, *payload, inner=6.6, outer=9.6, spread=0.26)
        elif kind == 'drop':
            _drop(path, *payload)
    return path


def paint(painter, name, rect, color, width=1.7):
    """Stroke one icon inside ``rect`` (a QRectF) in ``color``."""
    path = build_path(name)
    if path is None:
        return False
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    scale = min(rect.width(), rect.height()) / GRID
    painter.translate(rect.center().x() - GRID * scale / 2.0,
                      rect.center().y() - GRID * scale / 2.0)
    painter.scale(scale, scale)
    # The painter is scaled, so divide the stroke back out to keep a constant
    # on-screen weight whatever size the icon is drawn at.
    pen = QPen(QColor(color))
    pen.setWidthF(width / max(scale, 0.001))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    if name in FILLED:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
    else:
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()
    return True


def pixmap(name, size=16, color=None, ratio=2):
    """A rendered icon, for anywhere a QPixmap is easier than a widget.

    Drawn at ``ratio`` times the requested size and only then told it is a
    high-density image, so it stays crisp on a Retina display. The order
    matters: setting the device pixel ratio first halves the painter's own
    coordinate space, which silently clips the drawing to one quadrant.
    """
    color = color or t.TEXT_DIM
    pixels = int(size * ratio)
    image = QPixmap(pixels, pixels)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint(painter, name, QRectF(0, 0, pixels, pixels), color,
          width=1.7 * ratio)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


class Icon(QWidget):
    """A fixed-size icon that can be recoloured in place."""

    def __init__(self, name, size=16, color=None, width=1.7):
        super().__init__()
        self.name = name
        self._color = color or t.TEXT_DIM
        self._width = width
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet('background: transparent; border: none;')

    def set_color(self, color):
        if color != self._color:
            self._color = color
            self.update()

    def set_name(self, name):
        if name != self.name:
            self.name = name
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        paint(painter, self.name, QRectF(self.rect()), self._color, self._width)
        painter.end()


def icon(name, size=16, color=None):
    """A QIcon, for the places Qt wants one (a QPushButton's icon slot)."""
    from PyQt5.QtGui import QIcon
    return QIcon(pixmap(name, size, color))
