"""Explanation layer: tooltips, info dots and inline "what is this?" notes.

A cold-chain console is read by pharmacy staff and porters, not by the engineer
who built it. Every number on screen therefore has to be able to answer three
questions without anyone leaving the page:

* **What is this?**   - what the sensor or control actually is,
* **Why does it matter?** - what goes wrong if it is ignored,
* **What is normal?**  - so a reading can be judged, not just read.

The three live together in one tooltip so the wording cannot drift apart, and
the same content feeds the small inline notes used where a hover is not enough.
Nothing here changes behaviour: it is presentation only, and every technical
value stays exactly where it was.
"""

import textwrap

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QPushButton, QVBoxLayout,
                             QWidget)

from ui import theme as t

# Qt tooltips do not word-wrap rich text on their own, so the text is folded
# here. 62 characters is about 420 px in the console's font - wide enough to
# read in two or three lines, narrow enough not to cover the value it explains.
WRAP = 62


def _lines(text):
    return '<br>'.join(textwrap.wrap(str(text), WRAP)) if text else ''


def tooltip_html(title, what='', why='', normal='', note=''):
    """Build one tooltip out of the standard four parts.

    Only the parts that were supplied are rendered, so a control with nothing
    but a title still produces a tidy tooltip rather than empty headings.
    """
    parts = ['<div style="font-family:%s;">' % t.FONT]
    if title:
        parts.append('<b style="font-size:13px; color:%s;">%s</b>' % (t.TEXT, title))
    if what:
        parts.append('<div style="color:%s; margin-top:4px;">%s</div>'
                     % (t.TEXT, _lines(what)))
    if why:
        parts.append('<div style="color:%s; margin-top:5px;">'
                     '<b style="color:%s;">Why it matters:</b> %s</div>'
                     % (t.TEXT_DIM, t.TEXT_DIM, _lines(why)))
    if normal:
        parts.append('<div style="color:%s; margin-top:5px;">'
                     '<b style="color:%s;">Normal:</b> %s</div>'
                     % (t.OK, t.OK, _lines(normal)))
    if note:
        parts.append('<div style="color:%s; margin-top:5px;">%s</div>'
                     % (t.TEXT_MUTED, _lines(note)))
    parts.append('</div>')
    return ''.join(parts)


def set_help(widget, title, what='', why='', normal='', note=''):
    """Attach a standard explanation tooltip to any widget."""
    if widget is None:
        return widget
    widget.setToolTip(tooltip_html(title, what, why, normal, note))
    return widget


def set_tip(widget, text):
    """A one-line tooltip, for controls that only need naming."""
    if widget is not None:
        widget.setToolTip('<div style="font-family:%s; color:%s;">%s</div>'
                          % (t.FONT, t.TEXT, _lines(text)))
    return widget


# ===========================================================================
class InfoDot(QWidget):
    """A small information mark beside a heading that explains it on hover.

    Painted rather than typed: the circled-i character is missing from the
    default UI font on every platform this runs on, so Qt was substituting a
    different font for it and the dot came out a different size next to every
    heading.

    Clicking it shows the same text, so the explanation is still reachable on a
    touch screen or for anyone who never discovers hovering.
    """

    def __init__(self, tooltip, size=13):
        super().__init__()
        from ui import icons
        self._icons = icons
        self._size = size
        self._color = t.TEXT_MUTED
        self.setToolTip(tooltip)
        self.setCursor(Qt.WhatsThisCursor)
        self.setFixedSize(size + 4, size + 4)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # Named for a screen reader, which cannot see the mark at all.
        self.setAccessibleName('More information')
        self.setAccessibleDescription(tooltip)

    def paintEvent(self, event):
        painter = QPainter(self)
        self._icons.paint(painter, 'info', QRectF(self.rect()), self._color,
                          width=1.5)
        painter.end()

    def enterEvent(self, event):
        self._color = t.ACCENT
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._color = t.TEXT_MUTED
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        from PyQt5.QtWidgets import QToolTip
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()),
                          self.toolTip(), self)
        super().mousePressEvent(event)


def dot(title, what='', why='', normal='', note='', size=13):
    return InfoDot(tooltip_html(title, what, why, normal, note), size)


# ===========================================================================
class InlineNote(QFrame):
    """A short always-visible explanation inside a panel.

    Used where a tooltip would be missed: the first thing somebody reads on a
    page they have never opened before should not require them to hover.
    """

    def __init__(self, text, color=None, mark='info'):
        super().__init__()
        from ui import icons
        color = color or t.ACCENT
        self.setObjectName('note')
        self.setStyleSheet(
            'QFrame#note { background-color: %s; border: none; '
            'border-left: 2px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, color, t.RADIUS_SM))
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 8, 12, 8)
        row.setSpacing(9)
        row.addWidget(icons.Icon(mark if mark in icons.ICONS else 'info', 14,
                                 color, width=1.5),
                      alignment=Qt.AlignTop)
        self.textLabel = t.label(text, size=t.SIZE_XS, color=t.TEXT_DIM)
        self.textLabel.setWordWrap(True)
        row.addWidget(self.textLabel, stretch=1)

    def set_text(self, text):
        self.textLabel.setText(text)


class HelpNote(QWidget):
    """A "What is this?" link that expands into a paragraph in place.

    Progressive disclosure: the page stays uncluttered for somebody who already
    knows what they are looking at, and explains itself to anyone who does not.
    """

    def __init__(self, text, label='What is this?', expanded=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        from ui import icons
        self._icons = icons
        self._label = label
        self.button = QPushButton('')
        self.button.setIconSize(QSize(13, 13))
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setStyleSheet(t.ghost_button_style(t.ACCENT))
        self.button.clicked.connect(self.toggle)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.button)
        row.addStretch()
        layout.addLayout(row)

        self.body = InlineNote(text)
        layout.addWidget(self.body)

        self._expanded = not expanded
        self.toggle()

    def toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.button.setText(self._label)
        self.button.setIcon(self._icons.icon(
            'chevron_down' if self._expanded else 'chevron_right', 13, t.ACCENT))
        # State, not just decoration: a screen reader needs to hear it too.
        self.button.setAccessibleDescription(
            'Expanded' if self._expanded else 'Collapsed')

    def set_text(self, text):
        self.body.set_text(text)


# ===========================================================================
class Explain(object):
    """One entry in the glossary: a plain name plus the three answers.

    Pages ask an entry for whatever shape they need - a tooltip string, an info
    dot, an inline note - so a wording change happens in exactly one place.
    """

    def __init__(self, name, what='', why='', normal='', action='', note=''):
        self.name = name
        self.what = what
        self.why = why
        self.normal = normal
        self.action = action
        self.note = note        # the small print: a device id, a caveat

    def tooltip(self, title=None, note=None):
        return tooltip_html(title or self.name, self.what, self.why,
                            self.normal, self.note if note is None else note)

    def dot(self, size=13, title=None, note=None):
        return InfoDot(self.tooltip(title, note), size)

    def apply(self, widget, title=None, note=None):
        if widget is not None:
            widget.setToolTip(self.tooltip(title, note))
        return widget

    def inline(self):
        return InlineNote(self.what)
