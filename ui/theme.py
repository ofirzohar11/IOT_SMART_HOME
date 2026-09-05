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


# -- surfaces ---------------------------------------------------------------
BG = '#080B14'            # window background, almost black
SURFACE = '#0E1422'       # navigation rail, chrome
PANEL = '#141C2E'         # cards
PANEL_ALT = '#1A2437'     # nested sections inside a card
PANEL_HOVER = '#202C43'
BORDER = '#2A3852'
BORDER_STRONG = '#3A4A6B'
DISABLED_BG = '#1C2739'         # a control that is present but not available
DISABLED_FG = '#6E7A93'

# -- type -------------------------------------------------------------------
# Three weights of foreground, all of which clear WCAG AA (4.5:1) against
# PANEL and PANEL_ALT. The previous muted grey sat at 3.1:1, which is below
# the threshold for body text and was being used for real sentences - the
# freshness line on every device card, the meta line on every incident.
TEXT = '#E9EEF9'                # 14.6:1 on PANEL
TEXT_DIM = '#A3AFC6'            # 7.6:1  on PANEL
TEXT_MUTED = '#808DA8'          # 5.1:1  on PANEL, 4.7:1 on PANEL_ALT

# -- meaning ----------------------------------------------------------------
# These four are reserved for state and never used decoratively.
ACCENT = '#4DA3FF'        # interactive: links, focus, selection
OK = '#2FD48F'
WARN = '#FFB020'
ALARM = '#FF5A5F'         # also exported as CRITICAL
CRITICAL = ALARM
OFF = '#3C4A63'           # an inactive *fill*: a parked relay, an empty track
OFFLINE_FG = '#93A0B8'    # the readable foreground for the OFFLINE status
SIM = '#B57BFF'           # simulated data, deliberately not a status colour

# -- radii and spacing ------------------------------------------------------
RADIUS_SM = 6
RADIUS = 10
RADIUS_LG = 14

# One spacing scale, on a 4 px grid. Every gap, margin and gutter in the
# console is one of these, which is what stops six screens built at different
# times from each having their own idea of "a bit of room".
SPACE_XS = 4
SPACE_SM = 8
SPACE = 12
SPACE_MD = 16
SPACE_LG = 24

# One type scale. Sizes in between these were the main source of the drift
# between pages: a 13 px heading on one card and a 14 px heading on the next.
SIZE_DISPLAY = 30       # the number on a gauge
SIZE_XL = 21            # a stat tile value
SIZE_LG = 17            # the dashboard headline
SIZE_MD = 15            # a card or dialog title
SIZE_BASE = 13          # body copy, nav, headline of a card
SIZE_SM = 12            # secondary body, buttons, table cells
SIZE_XS = 11            # notes and descriptions
SIZE_CAPTION = 10       # upper-case captions and meta lines

CONTROL_HEIGHT = 32     # every button, combo and entry field agrees on this

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

# Colour and mark for the two vocabularies the data uses. Both resolve through
# ui.status, so an alert level and a device health that mean the same thing
# look the same wherever they land. Imported lazily: ui.status reads its
# colours from this module.
def _state(kind, key):
    from ui import status as st
    return st.get(st.from_level(key) if kind == 'level' else st.from_health(key))


def level_color(level):
    return _state('level', level).color


def level_mark(level):
    """The icon name in ui.icons for an alert severity."""
    return _state('level', level).mark


def level_word(level):
    return _state('level', level).label


def health_color(health):
    return _state('health', health).color


def health_mark(health):
    return _state('health', health).mark


def health_word(health):
    return _state('health', health).label


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


# Every button is the same height and shares one focus treatment. The focus
# ring matters: the console is stylesheet-driven, and a Qt stylesheet silently
# removes the platform focus rectangle, which leaves a keyboard user with no
# idea where they are.
_FOCUS = 'QPushButton:focus { border: 1px solid %s; outline: none; }' % ACCENT


def button_style(background, text_color='#08111F'):
    """A solid button. Reserved for the primary action in a group."""
    return '''
        QPushButton {
            background-color: %s; color: %s; border: 1px solid %s;
            border-radius: %dpx; font-family: %s; font-size: %dpx;
            font-weight: 600; padding: 0 16px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; }
        QPushButton:pressed { background-color: %s; }
        QPushButton:disabled { background-color: %s; color: %s;
                               border-color: %s; }
        QPushButton:focus { border: 1px solid %s; outline: none; }
    ''' % (background, text_color, background, RADIUS_SM, FONT, SIZE_SM,
           CONTROL_HEIGHT, background, background, DISABLED_BG, DISABLED_FG,
           BORDER, TEXT)


def outline_button_style(color=ACCENT):
    """A secondary action: the same weight of word, none of the fill."""
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: 1px solid %s;
            border-radius: %dpx; font-family: %s; font-size: %dpx;
            font-weight: 600; padding: 0 14px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; }
        QPushButton:pressed { background-color: %s; }
        QPushButton:disabled { color: %s; border-color: %s;
                               background-color: %s; }
        %s
    ''' % (color, color, RADIUS_SM, FONT, SIZE_SM, CONTROL_HEIGHT,
           PANEL_HOVER, PANEL_ALT, DISABLED_FG, BORDER, DISABLED_BG, _FOCUS)


def ghost_button_style(color=TEXT_DIM):
    """A tertiary action: no chrome until it is pointed at."""
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: 1px solid transparent;
            border-radius: %dpx; font-family: %s; font-size: %dpx;
            font-weight: 600; padding: 0 12px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; color: %s; }
        QPushButton:disabled { color: %s; }
        %s
    ''' % (color, RADIUS_SM, FONT, SIZE_SM, CONTROL_HEIGHT, PANEL_HOVER,
           TEXT, DISABLED_FG, _FOCUS)


def pill_style(color, filled=True, size=11):
    if filled:
        return ('color: #08111F; background-color: %s; border: 1px solid %s; '
                'border-radius: %dpx; font-family: %s; font-size: %dpx; '
                'font-weight: 700; letter-spacing: 0.3px; padding: 3px 9px;'
                % (color, color, RADIUS_SM, FONT, size))
    return ('color: %s; background: transparent; border: 1px solid %s; '
            'border-radius: %dpx; font-family: %s; font-size: %dpx; '
            'font-weight: 600; letter-spacing: 0.3px; padding: 3px 9px;'
            % (color, color, RADIUS_SM, FONT, size))


# Explanations are a first-class part of this interface, so the tooltip they
# arrive in is styled like a small card rather than left as the platform's
# yellow rectangle. Applied once to the QApplication, it reaches every window.
TOOLTIP_STYLE = '''
    QToolTip {
        background-color: %s; color: %s; border: 1px solid %s;
        border-radius: %dpx; padding: 9px 12px;
        font-family: %s; font-size: 12px;
    }
''' % (PANEL_ALT, TEXT, BORDER_STRONG, RADIUS, FONT)


def apply_tooltip_style(app):
    """Make every tooltip in this application an opaque, readable card.

    A stylesheet alone is not enough: on macOS the native tooltip window is
    translucent at the platform level, so without a matching opaque palette
    the panel colour is drawn over whatever was on screen underneath it and
    the text becomes unreadable. Setting both keeps the tooltip solid on
    every platform.
    """
    from PyQt5.QtGui import QColor, QPalette
    app.setStyleSheet(app.styleSheet() + TOOLTIP_STYLE)
    palette = app.palette()
    palette.setColor(QPalette.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(palette)


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
        border-radius: %dpx; padding: 0 10px; min-height: %dpx;
        font-family: %s; font-size: 12px;
    }
    QComboBox:hover { border-color: %s; }
    QComboBox:focus { border-color: %s; }
    QComboBox:disabled { color: %s; background-color: %s; }
    QComboBox::drop-down { border: none; width: 18px; }
    QComboBox QAbstractItemView {
        background-color: %s; color: %s; border: 1px solid %s;
        selection-background-color: %s; outline: none;
    }
''' % (PANEL_ALT, TEXT, BORDER, RADIUS_SM, CONTROL_HEIGHT, FONT, BORDER_STRONG, ACCENT,
       DISABLED_FG, DISABLED_BG, PANEL_ALT, TEXT, BORDER, '#1D3A63')


def line_edit_style(border_color=BORDER, mono=True):
    """A numeric entry field. The border carries the validation state."""
    return '''
        QLineEdit {
            background-color: %s; color: %s; border: 1px solid %s;
            border-radius: %dpx; padding: 6px 9px; font-family: %s;
            font-size: 12px; selection-background-color: %s;
        }
        QLineEdit:focus { border-color: %s; }
        QLineEdit:disabled { color: %s; background-color: %s; }
    ''' % (PANEL_ALT, TEXT, border_color, RADIUS_SM,
           FONT_MONO if mono else FONT, '#1D3A63', ACCENT, DISABLED_FG,
           DISABLED_BG)


CHECKBOX_STYLE = '''
    QCheckBox { color: %s; font-family: %s; font-size: 12px;
                background: transparent; border: none; spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px;
                           border: 1px solid %s; background: %s; }
    QCheckBox::indicator:checked { background: %s; border-color: %s; }
    QCheckBox::indicator:focus { border-color: %s; }
    QCheckBox:disabled { color: %s; }
''' % (TEXT, FONT, BORDER_STRONG, PANEL_ALT, ACCENT, ACCENT, ACCENT,
       DISABLED_FG)


def add_shadow(widget, blur=26, alpha=110, dy=5):
    """Soft elevation. Used sparingly - only the nav rail and dialogs get one."""
    from PyQt5.QtGui import QColor
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect
