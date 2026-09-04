"""Shared dark theme for every window in the system.

Keeping the palette and the small style helpers in one module means the
emulators and the main GUI look like one product rather than seven unrelated
Qt windows.
"""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel

from config import mqtt_init as cfg

# -- palette ----------------------------------------------------------------
BG = '#0F172A'
PANEL = '#1E293B'
PANEL_ALT = '#263449'
BORDER = '#334155'
TEXT = '#E2E8F0'
TEXT_DIM = '#94A3B8'
ACCENT = '#38BDF8'
OK = '#22C55E'
WARN = '#F59E0B'
ALARM = '#EF4444'
OFF = '#475569'

# Naming a font that does not exist makes Qt rebuild its font alias table on
# every start-up, so pick the one that is actually installed on this platform.
if sys.platform == 'darwin':
    FONT = 'Helvetica Neue'
elif sys.platform.startswith('win'):
    FONT = 'Segoe UI'
else:
    FONT = 'DejaVu Sans'

LEVEL_COLORS = {
    cfg.LEVEL_INFO: OK,
    cfg.LEVEL_WARNING: WARN,
    cfg.LEVEL_ALARM: ALARM,
}


def level_color(level):
    return LEVEL_COLORS.get(level, OFF)


# -- helpers ----------------------------------------------------------------
def panel_style(border_color=BORDER, background=PANEL):
    return ('QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-radius: 12px; }' % (background, border_color))


def make_panel(border_color=BORDER, background=PANEL):
    frame = QFrame()
    frame.setObjectName('panel')
    frame.setStyleSheet(panel_style(border_color, background))
    return frame


def label(text, size=13, color=TEXT, bold=False,
          align=Qt.AlignLeft | Qt.AlignVCenter):
    item = QLabel(text)
    item.setAlignment(align)
    item.setStyleSheet('color: %s; font-family: %s; font-size: %dpx; font-weight: %s; '
                       'background: transparent; border: none;'
                       % (color, FONT, size, 'bold' if bold else 'normal'))
    return item


def button_style(background, text_color='#0B1220'):
    return '''
        QPushButton {
            background-color: %s;
            color: %s;
            border: none;
            border-radius: 8px;
            font-family: %s;
            font-size: 13px;
            font-weight: bold;
            padding: 9px 16px;
        }
        QPushButton:hover { background-color: %s; }
        QPushButton:disabled { background-color: %s; color: %s; }
    ''' % (background, text_color, FONT, background, OFF, TEXT_DIM)


def outline_button_style(color):
    return '''
        QPushButton {
            background-color: transparent;
            color: %s;
            border: 1px solid %s;
            border-radius: 8px;
            font-family: %s;
            font-size: 12px;
            font-weight: bold;
            padding: 8px 14px;
        }
        QPushButton:hover { background-color: %s; }
    ''' % (color, color, FONT, PANEL_ALT)
