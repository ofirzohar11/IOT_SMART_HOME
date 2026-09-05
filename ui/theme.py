"""Design tokens and small style helpers shared by every window.

One palette, one type scale, one set of radii. Keeping them here is what stops
eleven emulator windows and a five-page console from drifting into eleven
different-looking programs, and it means a change of accent colour is a one-line
edit rather than a search across the codebase.

The palette is a dark, low-chroma industrial one: near-black backgrounds so the
data is what glows, a single blue accent for interactive elements, and three
status colours reserved *exclusively* for state. Nothing decorative is ever
green, amber or red, so when something does turn amber the eye is right to jump
to it.
"""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel

from config import mqtt_init as cfg

# -- surfaces ---------------------------------------------------------------
BG = '#080B14'            # window background, almost black
SURFACE = '#0E1422'       # navigation rail, chrome
PANEL = '#141C2E'         # cards
PANEL_ALT = '#1A2437'     # nested sections inside a card
PANEL_HOVER = '#202C43'
BORDER = '#243149'
BORDER_STRONG = '#324260'

# -- type -------------------------------------------------------------------
TEXT = '#E9EEF9'
TEXT_DIM = '#8B98B0'
TEXT_MUTED = '#5D6A85'

# -- meaning ----------------------------------------------------------------
# These four are reserved for state and never used decoratively.
ACCENT = '#4DA3FF'        # interactive: links, focus, selection
OK = '#2FD48F'
WARN = '#FFB020'
ALARM = '#FF5A5F'         # also exported as CRITICAL
CRITICAL = ALARM
OFF = '#3C4A63'
SIM = '#B57BFF'           # simulated data, deliberately not a status colour

# -- radii and spacing ------------------------------------------------------
RADIUS_SM = 6
RADIUS = 10
RADIUS_LG = 14
SPACE = 12

# Naming a font that does not exist makes Qt rebuild its font alias table on
# every start-up, so pick the one that is actually installed on this platform.
if sys.platform == 'darwin':
    FONT = 'Helvetica Neue'
    FONT_MONO = 'Menlo'
elif sys.platform.startswith('win'):
    FONT = 'Segoe UI'
    FONT_MONO = 'Consolas'
else:
    FONT = 'DejaVu Sans'
    FONT_MONO = 'DejaVu Sans Mono'

LEVEL_COLORS = {
    cfg.LEVEL_INFO: OK,
    cfg.LEVEL_WARNING: WARN,
    cfg.LEVEL_CRITICAL: CRITICAL,
    'ALARM': CRITICAL,          # pre-rename rows from an older database
}

HEALTH_COLORS = {
    'CONNECTED': OK,
    'DEGRADED': WARN,
    'MAINTENANCE': ACCENT,
    'FAULT': CRITICAL,
    'OFFLINE': OFF,
}

# Status is never carried by colour alone.
LEVEL_GLYPHS = {
    cfg.LEVEL_INFO: '●',
    cfg.LEVEL_WARNING: '▲',
    cfg.LEVEL_CRITICAL: '■',
    'ALARM': '■',
}

HEALTH_GLYPHS = {
    'CONNECTED': '●',
    'DEGRADED': '▲',
    'MAINTENANCE': '⚙',
    'FAULT': '■',
    'OFFLINE': '○',
}


def level_color(level):
    return LEVEL_COLORS.get(level, OFF)


def level_glyph(level):
    return LEVEL_GLYPHS.get(level, '○')


def health_color(health):
    return HEALTH_COLORS.get(health, OFF)


def health_glyph(health):
    return HEALTH_GLYPHS.get(health, '○')


# -- helpers ----------------------------------------------------------------
def panel_style(border_color=BORDER, background=PANEL, radius=RADIUS_LG):
    return ('QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; }' % (background, border_color, radius))


def make_panel(border_color=BORDER, background=PANEL):
    frame = QFrame()
    frame.setObjectName('panel')
    frame.setStyleSheet(panel_style(border_color, background))
    return frame


def make_subpanel():
    """A section inside a card. Borderless, so nested cards do not stack outlines."""
    frame = QFrame()
    frame.setObjectName('subpanel')
    frame.setStyleSheet('QFrame#subpanel { background-color: %s; border: none; '
                        'border-radius: %dpx; }' % (PANEL_ALT, RADIUS))
    return frame


def label(text, size=13, color=TEXT, bold=False, mono=False,
          align=Qt.AlignLeft | Qt.AlignVCenter, spacing=0):
    item = QLabel(text)
    item.setAlignment(align)
    item.setStyleSheet(
        'color: %s; font-family: %s; font-size: %dpx; font-weight: %s; '
        'letter-spacing: %.1fpx; background: transparent; border: none;'
        % (color, FONT_MONO if mono else FONT, size,
           '600' if bold else 'normal', spacing))
    return item


def caption(text, color=TEXT_DIM):
    """A small upper-case label used above values and section headings."""
    return label(text.upper(), size=10, color=color, bold=True, spacing=0.8)


def button_style(background, text_color='#08111F'):
    return '''
        QPushButton {
            background-color: %s; color: %s; border: none; border-radius: %dpx;
            font-family: %s; font-size: 12px; font-weight: 600; padding: 9px 16px;
        }
        QPushButton:hover { background-color: %s; }
        QPushButton:pressed { padding-top: 10px; padding-bottom: 8px; }
        QPushButton:disabled { background-color: %s; color: %s; }
    ''' % (background, text_color, RADIUS_SM, FONT, background, OFF, TEXT_MUTED)


def outline_button_style(color=ACCENT):
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: 1px solid %s;
            border-radius: %dpx; font-family: %s; font-size: 12px;
            font-weight: 600; padding: 8px 14px;
        }
        QPushButton:hover { background-color: %s; }
        QPushButton:disabled { color: %s; border-color: %s; }
    ''' % (color, color, RADIUS_SM, FONT, PANEL_HOVER, TEXT_MUTED, BORDER)


def ghost_button_style(color=TEXT_DIM):
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: none;
            border-radius: %dpx; font-family: %s; font-size: 12px;
            font-weight: 600; padding: 7px 11px;
        }
        QPushButton:hover { background-color: %s; color: %s; }
    ''' % (color, RADIUS_SM, FONT, PANEL_HOVER, TEXT)


def pill_style(color, filled=True, size=11):
    if filled:
        return ('color: #08111F; background-color: %s; border: none; '
                'border-radius: %dpx; font-family: %s; font-size: %dpx; '
                'font-weight: 700; padding: 3px 10px;'
                % (color, RADIUS_SM, FONT, size))
    return ('color: %s; background: transparent; border: 1px solid %s; '
            'border-radius: %dpx; font-family: %s; font-size: %dpx; '
            'font-weight: 600; padding: 3px 9px;' % (color, color, RADIUS_SM, FONT, size))


SCROLLBAR = '''
    QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: %s; border-radius: 5px; min-height: 32px; }
    QScrollBar::handle:vertical:hover { background: %s; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
    QScrollBar::handle:horizontal { background: %s; border-radius: 5px; min-width: 32px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
''' % (BORDER_STRONG, OFF, BORDER_STRONG)

TABLE_STYLE = '''
    QTableWidget {
        background-color: %s; alternate-background-color: %s; color: %s;
        gridline-color: %s; border: 1px solid %s; border-radius: %dpx;
        font-family: %s; font-size: 12px;
    }
    QTableWidget::item { padding: 5px; border: none; }
    QTableWidget::item:selected { background-color: %s; color: %s; }
    QHeaderView::section {
        background-color: %s; color: %s; padding: 7px 5px; border: none;
        border-bottom: 1px solid %s; font-weight: 700; font-size: 10px;
        letter-spacing: 0.6px;
    }
    QTableCornerButton::section { background-color: %s; border: none; }
''' % (PANEL, PANEL_ALT, TEXT, BORDER, BORDER, RADIUS, FONT,
       '#1D3A63', TEXT, PANEL_ALT, TEXT_DIM, BORDER, PANEL_ALT)

COMBO_STYLE = '''
    QComboBox {
        background-color: %s; color: %s; border: 1px solid %s;
        border-radius: %dpx; padding: 6px 10px; font-family: %s; font-size: 12px;
    }
    QComboBox:hover { border-color: %s; }
    QComboBox::drop-down { border: none; width: 18px; }
    QComboBox QAbstractItemView {
        background-color: %s; color: %s; border: 1px solid %s;
        selection-background-color: %s; outline: none;
    }
''' % (PANEL_ALT, TEXT, BORDER, RADIUS_SM, FONT, BORDER_STRONG,
       PANEL_ALT, TEXT, BORDER, '#1D3A63')

CHECKBOX_STYLE = '''
    QCheckBox { color: %s; font-family: %s; font-size: 12px;
                background: transparent; border: none; spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
                           border: 1px solid %s; background: %s; }
    QCheckBox::indicator:checked { background: %s; border-color: %s; }
    QCheckBox:disabled { color: %s; }
''' % (TEXT, FONT, BORDER_STRONG, PANEL_ALT, ACCENT, ACCENT, TEXT_MUTED)


def add_shadow(widget, blur=26, alpha=110, dy=5):
    """Soft elevation. Used sparingly - only the nav rail and dialogs get one."""
    from PyQt5.QtGui import QColor
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect
