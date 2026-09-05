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

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

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
class InfoDot(QLabel):
    """A small ⓘ beside a heading that reveals the full explanation on hover.

    Clicking it shows the same text, so the explanation is still reachable on a
    touch screen or for anyone who never discovers hovering.
    """

    def __init__(self, tooltip, size=13):
        super().__init__('ⓘ')
        self._size = size
        self.setToolTip(tooltip)
        self.setCursor(Qt.WhatsThisCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(size + 5, size + 5)
        self._paint(t.TEXT_MUTED)

    def _paint(self, color):
        self.setStyleSheet('color: %s; background: transparent; border: none; '
                           'font-family: %s; font-size: %dpx;'
                           % (color, t.FONT, self._size))

    def enterEvent(self, event):
        self._paint(t.ACCENT)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._paint(t.TEXT_MUTED)
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

    def __init__(self, text, color=None, glyph='ⓘ'):
        super().__init__()
        color = color or t.ACCENT
        self.setObjectName('note')
        self.setStyleSheet(
            'QFrame#note { background-color: %s; border: none; '
            'border-left: 2px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, color, t.RADIUS_SM))
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 8, 12, 8)
        row.setSpacing(9)
        row.addWidget(t.label(glyph, size=12, color=color), alignment=Qt.AlignTop)
        self.textLabel = t.label(text, size=11, color=t.TEXT_DIM)
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

        self._label = label
        self.button = QPushButton('')
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
        self.button.setText(('▾  %s' if self._expanded else '▸  %s') % self._label)

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
