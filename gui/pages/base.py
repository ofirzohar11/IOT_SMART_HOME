"""Common behaviour for the console's pages."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ui import theme as t


class Page(QWidget):
    """A screen in the console.

    The shell pushes live state in through ``apply_status`` and ``apply_alert``,
    calls ``on_shown`` when the page becomes visible so database-backed content
    is refreshed only when somebody is looking at it, and ``tick`` once a second
    for anything that has to count.
    """

    title = 'Page'
    subtitle = ''

    def __init__(self, console):
        super().__init__()
        self.console = console
        self.setObjectName('page')
        self.setStyleSheet('QWidget#page { background-color: %s; }' % t.BG)

    # -- hooks -------------------------------------------------------------
    def apply_status(self, data):
        pass

    def apply_alert(self, record):
        pass

    def apply_device_status(self, device_id, state):
        pass

    def on_shown(self):
        pass

    def tick(self):
        pass


def scrollable(inner):
    """Wrap a page body so it stays usable when the window is short."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setStyleSheet('QScrollArea { border: none; background: transparent; }'
                       + t.SCROLLBAR)
    area.setWidget(inner)
    return area


def page_layout(page, spacing=12):
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout
