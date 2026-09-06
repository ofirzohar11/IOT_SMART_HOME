"""Design tokens and small style helpers shared by every window.

One palette, one type scale, one set of radii. Keeping them here is what stops
eleven emulator windows and a six-page console from drifting into eleven
different-looking programs, and it means a change of accent colour is a one-line
edit rather than a search across the codebase.

The palette is a dark, low-chroma industrial one: near-black neutral surfaces so
the data is what glows, a single azure accent for interactive elements, and four
status colours reserved *exclusively* for state. Nothing decorative is ever
green, amber or red, so when something does turn amber the eye is right to jump
to it.

Surfaces are separated by luminance first and a hairline border second. The
previous palette did the opposite - every card carried a visible 1px outline -
which is what made six screens of cards read as a wireframe rather than as a
product.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel

from ui import fonts


# -- surfaces ---------------------------------------------------------------
# A five-step ladder. Each rung is a real luminance change, so a nested section
# inside a card is legible with no border at all.
BG = '#0A0D13'            # window background, almost black
SURFACE = '#0E121B'       # navigation rail, chrome
PANEL = '#141922'         # cards
PANEL_ALT = '#1A202B'     # nested sections inside a card
PANEL_HOVER = '#222937'
BORDER = '#232A37'        # a hairline, not an outline
BORDER_STRONG = '#333C4C'
DISABLED_BG = '#171C26'         # a control that is present but not available
DISABLED_FG = '#667185'

# -- type -------------------------------------------------------------------
# Three weights of foreground, all of which clear WCAG AA (4.5:1) against
# PANEL and PANEL_ALT alike - the muted tone is used for real sentences (the
# freshness line on every device card, the meta line on every incident), so it
# is held to the body-text threshold rather than the large-text one.
TEXT = '#EDF1F7'                # 15.5:1 on PANEL
TEXT_DIM = '#A9B4C6'            # 8.4:1  on PANEL
TEXT_MUTED = '#8A94A6'          # 5.8:1  on PANEL, 5.3:1 on PANEL_ALT

# -- meaning ----------------------------------------------------------------
# These are reserved for state and never used decoratively.
ACCENT = '#3EA8FF'        # interactive: links, focus, selection
ACCENT_HOVER = '#5FB6FF'
ACCENT_PRESSED = '#2B90E6'
OK = '#34D399'
WARN = '#FBBF24'
ALARM = '#FF4D4F'         # also exported as CRITICAL
CRITICAL = ALARM
OFF = '#333C4C'           # an inactive *fill*: a parked relay, an empty track
OFFLINE_FG = '#96A1B5'    # the readable foreground for the OFFLINE status
SIM = '#A78BFA'           # simulated data, deliberately not a status colour

# The ink laid over a saturated fill. Near-black rather than pure black so a
# filled pill does not punch a hole in a dark screen; every status colour
# clears AA against it.
ON_ACCENT = '#08111F'
OVERLAY = '#05070C'

# -- radii and spacing ------------------------------------------------------
RADIUS_SM = 8
RADIUS = 12
RADIUS_LG = 16

# One spacing scale, on a 4 px grid. Every gap, margin and gutter in the
# console is one of these, which is what stops six screens built at different
# times from each having their own idea of "a bit of room".
SPACE_XS = 4
SPACE_SM = 8
SPACE = 12
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32

# One type scale. Sizes in between these were the main source of the drift
# between pages: a 13 px heading on one card and a 14 px heading on the next.
SIZE_DISPLAY = 32       # the number on a gauge
SIZE_XXL = 24
SIZE_XL = 21            # a stat tile value
SIZE_LG = 17            # the dashboard headline
SIZE_MD = 15            # a card or dialog title
SIZE_BASE = 13          # body copy, nav, headline of a card
SIZE_SM = 12            # secondary body, buttons, table cells
SIZE_XS = 11            # notes and descriptions
SIZE_CAPTION = 10       # upper-case captions and meta lines

# -- weight -----------------------------------------------------------------
# Qt's stylesheet parser does *not* read CSS weights on the 100-900 scale. It
# divides the number by 8 onto QFont's own 0-99 scale, so `font-weight: 600`
# and `font-weight: 700` both land on QFont::Bold (75) and render identically.
# That is why the console had no weight hierarchy: every "semibold" label in it
# was in fact bold, and nothing could be heavier than anything else.
#
# These four are the values that actually select the four faces shipped in
# assets/fonts. Verified against QFontInfo.styleName(), not assumed.
#
#     400 -> 50 Regular      450 -> 57 Medium
#     500 -> 63 SemiBold     550 -> 75 Bold
#
# Always use the constant. A bare number here is a silent bug.
W_REGULAR = 400
W_MEDIUM = 450
W_SEMIBOLD = 500
W_BOLD = 550

CONTROL_HEIGHT = 32     # every button, combo and entry field agrees on this


# -- colour maths -----------------------------------------------------------
def _split(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, weight=0.5):
    """Blend ``a`` into ``b``. weight=0 is all b, weight=1 is all a."""
    ar, ag, ab = _split(a)
    br, bg, bb = _split(b)
    return '#%02X%02X%02X' % (
        round(ar * weight + br * (1 - weight)),
        round(ag * weight + bg * (1 - weight)),
        round(ab * weight + bb * (1 - weight)))


def tint(color, amount=0.14):
    """Lift a colour towards white - a hover state on a filled control."""
    return mix('#FFFFFF', color, amount)


def shade(color, amount=0.14):
    """Push a colour towards black - a pressed state on a filled control."""
    return mix('#000000', color, amount)


def wash(color, amount=0.14, over=None):
    """A faint field of ``color`` laid on ``over``, defaulting to a card.

    Qt stylesheets have no alpha compositing worth relying on across platforms,
    so a tinted background is computed against the surface it will actually sit
    on rather than expressed as an rgba() and hoped for.
    """
    return mix(color, PANEL if over is None else over, amount)


# Derived once so nothing has to guess at them. The selection colour used to be
# a hardcoded navy that had drifted away from the accent it was meant to echo.
SELECTION_BG = wash(ACCENT, 0.26, PANEL_ALT)
FOCUS_RING = ACCENT

SCROLLBAR = '''
    QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: %s; border-radius: 5px; min-height: 32px; }
    QScrollBar::handle:vertical:hover { background: %s; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
    QScrollBar::handle:horizontal { background: %s; border-radius: 5px; min-width: 32px; }
    QScrollBar::handle:horizontal:hover { background: %s; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
''' % (BORDER_STRONG, mix(BORDER_STRONG, TEXT_MUTED, 0.4), BORDER_STRONG,
       mix(BORDER_STRONG, TEXT_MUTED, 0.4))


# -- font resolution --------------------------------------------------------
# FONT and FONT_MONO cannot be constants: the shipped faces are registered with
# Qt only once a QApplication exists, which is long after this module is
# imported. They are resolved on each read instead - ui.fonts caches the
# answer, so this costs a dictionary lookup - and the composed stylesheet
# blocks below are built the same way, on access rather than at import.
#
# Read them as attributes (``t.FONT``). A ``from ui.theme import FONT`` freezes
# whatever the fallback was at import time and will not pick the shipped face up.


def _table_style():
    return '''
    QTableWidget {
        background-color: %s; alternate-background-color: %s; color: %s;
        gridline-color: %s; border: 1px solid %s; border-radius: %dpx;
        font-family: "%s"; font-size: %dpx;
    }
    QTableWidget::item { padding: 6px 5px; border: none; }
    QTableWidget::item:selected { background-color: %s; color: %s; }
    QHeaderView::section {
        background-color: %s; color: %s; padding: 8px 5px; border: none;
        border-bottom: 1px solid %s; font-weight: %d; font-size: %dpx;
        letter-spacing: 0.5px;
    }
    QTableCornerButton::section { background-color: %s; border: none; }
''' % (PANEL, mix(PANEL_ALT, PANEL, 0.55), TEXT, BORDER, BORDER, RADIUS,
       FONT_UI(), SIZE_SM, SELECTION_BG, TEXT, PANEL_ALT, TEXT_DIM, BORDER,
       W_SEMIBOLD, SIZE_CAPTION, PANEL_ALT)


def _combo_style():
    return '''
    QComboBox {
        background-color: %s; color: %s; border: 1px solid %s;
        border-radius: %dpx; padding: 0 10px; min-height: %dpx;
        font-family: "%s"; font-size: %dpx; font-weight: %d;
    }
    QComboBox:hover { border-color: %s; background-color: %s; }
    QComboBox:focus { border-color: %s; }
    QComboBox:disabled { color: %s; background-color: %s; }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background-color: %s; color: %s; border: 1px solid %s;
        border-radius: %dpx; padding: 4px;
        selection-background-color: %s; outline: none;
    }
''' % (PANEL_ALT, TEXT, BORDER, RADIUS_SM, CONTROL_HEIGHT, FONT_UI(), SIZE_SM,
       W_MEDIUM, BORDER_STRONG, PANEL_HOVER, ACCENT, DISABLED_FG, DISABLED_BG,
       PANEL_ALT, TEXT, BORDER_STRONG, RADIUS_SM, SELECTION_BG)


def _checkbox_style():
    return '''
    QCheckBox { color: %s; font-family: "%s"; font-size: %dpx;
                background: transparent; border: none; spacing: 8px; }
    QCheckBox::indicator { width: 15px; height: 15px; border-radius: 5px;
                           border: 1px solid %s; background: %s; }
    QCheckBox::indicator:hover { border-color: %s; }
    QCheckBox::indicator:checked { background: %s; border-color: %s; }
    QCheckBox::indicator:focus { border-color: %s; }
    QCheckBox:disabled { color: %s; }
''' % (TEXT, FONT_UI(), SIZE_SM, BORDER_STRONG, PANEL_ALT, ACCENT, ACCENT,
       ACCENT, ACCENT, DISABLED_FG)


def _tooltip_style():
    # Explanations are a first-class part of this interface, so the tooltip they
    # arrive in is styled like a small card rather than left as the platform's
    # yellow rectangle. Applied once to the QApplication, it reaches every window.
    return '''
    QToolTip {
        background-color: %s; color: %s; border: 1px solid %s;
        border-radius: %dpx; padding: 9px 12px;
        font-family: "%s"; font-size: %dpx;
    }
''' % (PANEL_ALT, TEXT, BORDER_STRONG, RADIUS, FONT_UI(), SIZE_SM)


_BUILDERS = {
    'TABLE_STYLE': _table_style,
    'COMBO_STYLE': _combo_style,
    'CHECKBOX_STYLE': _checkbox_style,
    'TOOLTIP_STYLE': _tooltip_style,
}


def FONT_UI():
    return fonts.ui_family()


def __getattr__(name):
    """Resolve the font-dependent tokens at read time (PEP 562)."""
    if name == 'FONT':
        return fonts.ui_family()
    if name == 'FONT_MONO':
        return fonts.mono_family()
    if name in _BUILDERS:
        return _BUILDERS[name]()
    raise AttributeError('module %r has no attribute %r' % (__name__, name))


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
def panel_style(border_color=None, background=None, radius=RADIUS_LG):
    return ('QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; }'
            % (PANEL if background is None else background,
               BORDER if border_color is None else border_color, radius))


def make_panel(border_color=None, background=None):
    frame = QFrame()  # colours resolved by panel_style at call time
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


def label(text, size=SIZE_BASE, color=None, bold=False, mono=False,
          align=Qt.AlignLeft | Qt.AlignVCenter, spacing=0, weight=None):
    """A styled QLabel.

    ``bold`` is kept for the call sites that predate the weight scale and means
    semibold, which is what those sites always wanted; pass ``weight`` for
    anything that needs a specific rung.
    """
    if weight is None:
        weight = W_SEMIBOLD if bold else W_REGULAR
    if color is None:
        color = TEXT
    item = QLabel(text)
    item.setAlignment(align)
    item.setStyleSheet(
        'color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
        'letter-spacing: %.2fpx; background: transparent; border: none;'
        % (color, fonts.mono_family() if mono else fonts.ui_family(), size,
           weight, spacing))
    return item


def caption(text, color=None):
    """A small quiet label sitting above a value - 'Told to', 'What to do'.

    Sentence case, not spaced capitals. Upper case is a shout, and the console
    was using it for every heading and every micro-label alike: the name of a
    card, the label above a switch state and the title of a section all arrived
    in the same 10px spaced capitals, so none of them ranked above the others.
    Capitals are now left to the one place they earn their keep - a table's
    column headers, set in TABLE_STYLE.

    Headings use ``title``; this is for the label *of* a value.
    """
    return label(text, size=SIZE_XS,
                 color=TEXT_MUTED if color is None else color,
                 weight=W_MEDIUM)


def title(text, size=SIZE_BASE, color=None):
    """A card or section heading: sentence case, semibold, full-strength ink."""
    return label(text, size=size, color=TEXT if color is None else color,
                 weight=W_SEMIBOLD)


def prose(text, lead=None, size=SIZE_XS, color=None,
          lead_color=None, line_height=150):
    """A paragraph of real sentences, set to be read rather than skimmed.

    Two things a plain QLabel cannot do, which is why this goes through rich
    text. First, leading: Qt sets a wrapped label solid, and four lines of 11px
    grey with no air between them is a block, not a paragraph. Second, the
    lead-in - 'Normal', 'Why it matters' - which is a label attached to the
    sentence after it and should not be the same weight and colour as the
    sentence itself.

    Qt's rich text honours line-height on a block element; most of the rest of
    CSS it quietly ignores, so nothing more ambitious is attempted here.
    """
    from html import escape
    color = TEXT_MUTED if color is None else color
    lead_color = TEXT_DIM if lead_color is None else lead_color
    body = ('<span style="color:%s">%s</span>' % (color, escape(str(text))))
    if lead:
        body = ('<span style="color:%s; font-weight:%d">%s</span>&nbsp;%s'
                % (lead_color, W_SEMIBOLD, escape(str(lead)), body))
    item = QLabel('<div style="line-height:%d%%">%s</div>'
                  % (line_height, body))
    item.setWordWrap(True)
    item.setTextFormat(Qt.RichText)
    item.setStyleSheet('font-family: "%s"; font-size: %dpx; '
                       'background: transparent; border: none;'
                       % (fonts.ui_family(), size))
    return item


def value(text, size=SIZE_XL, color=None):
    """A number that changes while you watch it.

    Always the tabular face: Inter's digits are proportional, so a live reading
    set in it shuffles sideways every time a 1 replaces a 0.
    """
    return label(text, size=size, color=TEXT if color is None else color,
                 mono=True, weight=W_MEDIUM)


# Every button is the same height and shares one focus treatment. The focus
# ring matters: the console is stylesheet-driven, and a Qt stylesheet silently
# removes the platform focus rectangle, which leaves a keyboard user with no
# idea where they are. A 1px ring in the accent was too easy to miss against a
# border that was already there, so the ring doubles the border weight and
# lightens the fill at the same time.
def _focus():
    return ('QPushButton:focus { border: 2px solid %s; outline: none; }'
            % FOCUS_RING)


def button_style(background, text_color=None):
    """A solid button. Reserved for the primary action in a group.

    Hover and pressed are computed from the fill rather than repeating it. They
    used to be set to the same colour as the resting state, so the primary
    action in every dialog and on every page gave no feedback at all when
    pointed at or held down.
    """
    if text_color is None:
        text_color = ON_ACCENT
    return '''
        QPushButton {
            background-color: %s; color: %s; border: 1px solid %s;
            border-radius: %dpx; font-family: "%s"; font-size: %dpx;
            font-weight: %d; letter-spacing: 0.1px;
            padding: 0 16px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; border-color: %s; }
        QPushButton:pressed { background-color: %s; border-color: %s; }
        QPushButton:disabled { background-color: %s; color: %s;
                               border-color: %s; }
        %s
    ''' % (background, text_color, background, RADIUS_SM, fonts.ui_family(),
           SIZE_SM, W_SEMIBOLD, CONTROL_HEIGHT,
           tint(background, 0.16), tint(background, 0.16),
           shade(background, 0.16), shade(background, 0.16),
           DISABLED_BG, DISABLED_FG, BORDER, _focus())


def outline_button_style(color=None):
    """A secondary action: the same weight of word, none of the fill."""
    if color is None:
        color = ACCENT
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: 1px solid %s;
            border-radius: %dpx; font-family: "%s"; font-size: %dpx;
            font-weight: %d; padding: 0 14px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; color: %s;
                            border-color: %s; }
        QPushButton:pressed { background-color: %s; }
        QPushButton:disabled { color: %s; border-color: %s;
                               background-color: %s; }
        %s
    ''' % (color, mix(color, PANEL, 0.55), RADIUS_SM, fonts.ui_family(),
           SIZE_SM, W_SEMIBOLD, CONTROL_HEIGHT,
           wash(color, 0.13), tint(color, 0.12), color,
           wash(color, 0.20), DISABLED_FG, BORDER, DISABLED_BG, _focus())


def ghost_button_style(color=None):
    """A tertiary action: no chrome until it is pointed at."""
    if color is None:
        color = TEXT_DIM
    return '''
        QPushButton {
            background-color: transparent; color: %s; border: 1px solid transparent;
            border-radius: %dpx; font-family: "%s"; font-size: %dpx;
            font-weight: %d; padding: 0 12px; min-height: %dpx;
        }
        QPushButton:hover { background-color: %s; color: %s; }
        QPushButton:pressed { background-color: %s; }
        QPushButton:disabled { color: %s; }
        %s
    ''' % (color, RADIUS_SM, fonts.ui_family(), SIZE_SM, W_SEMIBOLD,
           CONTROL_HEIGHT, PANEL_HOVER, TEXT, PANEL_ALT, DISABLED_FG, _focus())


def pill_style(color, filled=True, size=SIZE_XS):
    """A status chip. ``color`` is required: a chip always means something."""
    if filled:
        return ('color: %s; background-color: %s; border: 1px solid %s; '
                'border-radius: %dpx; font-family: "%s"; font-size: %dpx; '
                'font-weight: %d; letter-spacing: 0.2px; padding: 3px 9px;'
                % (ON_ACCENT, color, color, RADIUS_SM, fonts.ui_family(), size,
                   W_SEMIBOLD))
    return ('color: %s; background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; font-family: "%s"; font-size: %dpx; '
            'font-weight: %d; letter-spacing: 0.2px; padding: 3px 9px;'
            % (color, wash(color, 0.10), mix(color, PANEL, 0.45), RADIUS_SM,
               fonts.ui_family(), size, W_MEDIUM))


def line_edit_style(border_color=None, mono=True):
    """A numeric entry field. The border carries the validation state."""
    if border_color is None:
        border_color = BORDER
    return '''
        QLineEdit {
            background-color: %s; color: %s; border: 1px solid %s;
            border-radius: %dpx; padding: 6px 9px; font-family: "%s";
            font-size: %dpx; selection-background-color: %s;
        }
        QLineEdit:hover { border-color: %s; }
        QLineEdit:focus { border: 2px solid %s; padding: 5px 8px; }
        QLineEdit:disabled { color: %s; background-color: %s; }
    ''' % (PANEL_ALT, TEXT, border_color, RADIUS_SM,
           fonts.mono_family() if mono else fonts.ui_family(), SIZE_SM,
           SELECTION_BG, BORDER_STRONG, ACCENT, DISABLED_FG, DISABLED_BG)


def reading_style(color=None, size=None):
    """The stylesheet for the headline number in an emulator window.

    Two rules, applied in one place so eleven windows cannot drift apart.

    The face is the tabular one. These readings update once a second, and set
    in a proportional face they shuffled sideways every time a 1 replaced a 0.

    The colour is neutral while the reading is fine. Every emulator used to
    paint its value green whenever the device was healthy, so a wall of eleven
    windows was a wall of green - and a reading that then went amber had to
    compete with ten other saturated things for attention. Green here says
    nothing that the word underneath the number does not already say, so the
    ink stays quiet and WARNING and ALARM keep their colour to themselves.
    """
    if color in (None, OK):
        color = TEXT
    return ('color: %s; font-family: "%s"; font-size: %dpx; font-weight: %d; '
            'letter-spacing: -0.4px; background: transparent; border: none;'
            % (color, fonts.mono_family(), size or SIZE_DISPLAY, W_MEDIUM))


def state_plate_style(color, loud=False):
    """The big ON/OFF/OPEN/CLOSED plate an actuator window is built around.

    ``loud`` fills it; otherwise it is a tinted chip. Same rule as the console's
    verdict block: a resting state does not need to be the brightest object on
    the screen, and keeping the fill in reserve means the one window that *is*
    filled is the one worth walking over to.
    """
    if loud:
        return ('color: %s; background-color: %s; border: 1px solid %s; '
                'border-radius: %dpx; font-family: "%s"; font-size: %dpx; '
                'font-weight: %d; letter-spacing: 0.3px; padding: 13px 10px;'
                % (ON_ACCENT, color, color, RADIUS, fonts.ui_family(), SIZE_MD,
                   W_SEMIBOLD))
    return ('color: %s; background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; font-family: "%s"; font-size: %dpx; '
            'font-weight: %d; letter-spacing: 0.3px; padding: 13px 10px;'
            % (color, wash(color, 0.12, PANEL), mix(color, PANEL, 0.40),
               RADIUS, fonts.ui_family(), SIZE_MD, W_SEMIBOLD))


def add_shadow(widget, blur=26, alpha=110, dy=5):
    """Soft elevation. Used sparingly - only the nav rail and dialogs get one."""
    from PyQt5.QtGui import QColor
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect


# ---------------------------------------------------------------------------
#  Application bootstrap
# ---------------------------------------------------------------------------
def bootstrap(app):
    """Register the shipped faces and apply the chrome every window inherits.

    Call once, immediately after the QApplication is constructed and before the
    first window is built - the console and each emulator do this.
    """
    fonts.load()
    from PyQt5.QtGui import QColor, QFont, QPalette

    base = QFont(fonts.ui_family())
    base.setPixelSize(SIZE_BASE)
    app.setFont(base)

    app.setStyleSheet(app.styleSheet() + _tooltip_style() + SCROLLBAR)

    # A stylesheet alone is not enough for the tooltip: on macOS the native
    # tooltip window is translucent at the platform level, so without a matching
    # opaque palette the panel colour is drawn over whatever was on screen
    # underneath it and the text becomes unreadable.
    palette = app.palette()
    palette.setColor(QPalette.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(SELECTION_BG))
    palette.setColor(QPalette.HighlightedText, QColor(TEXT))
    app.setPalette(palette)


def apply_tooltip_style(app):
    """Kept under its old name - the emulators call it during start-up."""
    bootstrap(app)
