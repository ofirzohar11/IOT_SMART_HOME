"""Reusable interface pieces built on the design tokens.

Everything here is deliberately small and stateless-ish: a card, a tile, a
status pill, a toast, a confirmation dialog. The pages compose them rather than
each inventing its own styled QLabel, which is what keeps five very different
screens looking like one product.
"""

from PyQt5.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                          pyqtSignal)
from PyQt5.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect,
                             QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from ui import help as h
from ui import icons
from ui import status as stat
from ui import theme as t


def discard(widget):
    """Remove a widget from its parent *now*, then schedule its deletion.

    deleteLater only runs when the event loop next spins. Until then the widget
    is still a child of its old parent and Qt paints it at the parent's origin,
    which shows up as stray controls stacked in the corner of a card that is
    being rebuilt. Detaching first makes the removal immediate.
    """
    if widget is None:
        return
    widget.setParent(None)
    widget.deleteLater()


def clear_layout(layout, keep=()):
    """Empty a layout, leaving any widget in ``keep`` in place."""
    kept = []
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is None:
            child = item.layout()
            if child is not None:
                clear_layout(child)
            continue
        if widget in keep:
            kept.append(widget)
        else:
            discard(widget)
    for widget in kept:
        layout.addWidget(widget)


# ===========================================================================
#  Containers
# ===========================================================================
class Card(QFrame):
    """A titled panel. ``body`` is the layout subclasses and pages fill."""

    def __init__(self, title=None, subtitle=None, actions=None, padding=16,
                 help=None, icon=None, icon_color=None):
        super().__init__()
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style())

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(padding, padding - 3, padding, padding - 3)
        self._root.setSpacing(11)

        self.headerRow = None
        if title:
            self.headerRow = QHBoxLayout()
            self.headerRow.setSpacing(10)
            titles = QVBoxLayout()
            titles.setSpacing(2)
            # The heading lives in its own widget so the info dot stays beside
            # the words rather than being pushed to the far side of the card.
            heading = QWidget()
            heading.setStyleSheet('background: transparent;')
            # Fixed vertically: a heading that can grow steals the slack in a
            # stretched card and pushes the subtitle to the bottom of it.
            heading.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            headingRow = QHBoxLayout(heading)
            headingRow.setContentsMargins(0, 0, 0, 0)
            headingRow.setSpacing(6)
            if icon:
                headingRow.addWidget(
                    icons.Icon(icon, 15, icon_color or t.TEXT_DIM, width=1.6),
                    alignment=Qt.AlignVCenter)
            headingRow.addWidget(t.caption(title))
            if help is not None:
                headingRow.addWidget(help.dot(size=12) if hasattr(help, 'dot')
                                     else h.InfoDot(help, size=12))
            titles.addWidget(heading)
            if subtitle:
                # Deliberately not wrapped: a wrapped label reports a narrow
                # size hint, which squeezes the whole heading into a column.
                # Fixed height, or a card with a short body hands its slack to
                # the subtitle and leaves it floating in mid-air.
                note = t.label(subtitle, size=11, color=t.TEXT_MUTED)
                note.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                titles.addWidget(note)
            self.headerRow.addLayout(titles)
            self.headerRow.addStretch()
            for widget in (actions or []):
                self.headerRow.addWidget(widget)
            self._root.addLayout(self.headerRow)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self._root.addLayout(self.body)

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch=0):
        self.body.addLayout(layout, stretch)
        return layout


class SectionTitle(QWidget):
    """A heading with an optional count badge, used between blocks on a page."""

    def __init__(self, text, note=None, help=None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 4, 2, 0)
        row.setSpacing(7)
        row.addWidget(t.caption(text))
        if help is not None:
            row.addWidget(help.dot(size=12) if hasattr(help, 'dot')
                          else h.InfoDot(help, size=12))
        self.noteLabel = t.label(note or '', size=11, color=t.TEXT_MUTED)
        row.addWidget(self.noteLabel)
        row.addStretch()

    def set_note(self, text):
        self.noteLabel.setText(text)


# ===========================================================================
#  Indicators
# ===========================================================================
class Pill(QFrame):
    """A compact status chip: a painted mark, then a word, then a colour.

    The mark is drawn rather than typed. The geometric characters this used to
    print - a filled square for critical, a gear for maintenance - are absent
    from the default UI font on macOS, Windows and Linux alike, so Qt
    substituted a different font for each one and a row of chips came out as a
    row of mismatched sizes. Painting them also means the mark scales with the
    chip instead of with whatever fallback font Qt happened to find.
    """

    def __init__(self, text='', color=t.OFF, filled=True, mark=None, size=11):
        super().__init__()
        self._filled = filled
        self._size = size
        self._color = color
        self.setObjectName('pill')
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(6)
        self.markIcon = icons.Icon(mark or 'mark_offline', size + 1, color,
                                   width=1.5)
        self.textLabel = QLabel(text)
        self.textLabel.setAlignment(Qt.AlignCenter)
        row.addWidget(self.markIcon, alignment=Qt.AlignVCenter)
        row.addWidget(self.textLabel, alignment=Qt.AlignVCenter)
        self.set(text, color, mark)

    # ``glyph`` is accepted under its old name so nothing that still passes a
    # character positionally breaks; a one-character value is simply ignored
    # now that the mark is painted.
    def set(self, text, color, mark=None):
        self._color = color
        if mark and mark in icons.ICONS:
            self.markIcon.set_name(mark)
            self.markIcon.show()
        elif mark is None:
            self.markIcon.hide()
        self.markIcon.set_color('#08111F' if self._filled else color)
        self.textLabel.setText(str(text))
        text_color = '#08111F' if self._filled else color
        self.textLabel.setStyleSheet(
            'color: %s; background: transparent; border: none; '
            'font-family: %s; font-size: %dpx; font-weight: %s; '
            'letter-spacing: 0.3px;'
            % (text_color, t.FONT, self._size, '700' if self._filled else '600'))
        if self._filled:
            self.setStyleSheet('QFrame#pill { background-color: %s; '
                               'border: 1px solid %s; border-radius: %dpx; }'
                               % (color, color, t.RADIUS_SM))
        else:
            self.setStyleSheet('QFrame#pill { background: transparent; '
                               'border: 1px solid %s; border-radius: %dpx; }'
                               % (color, t.RADIUS_SM))

    def set_state(self, state, text=None, note=''):
        """Show one of the six canonical states, with its standard wording."""
        entry = stat.get(state)
        self.set(text if text is not None else entry.label.upper(),
                 entry.color, entry.mark)
        self.setToolTip(stat.tooltip(state, extra=note))
        return self


class StatusChip(Pill):
    """A Pill that only ever shows one of the six canonical states."""

    def __init__(self, state=stat.NORMAL, filled=False, size=11, text=None):
        entry = stat.get(state)
        super().__init__(text if text is not None else entry.label.upper(),
                         entry.color, filled, entry.mark, size)
        self.setToolTip(stat.tooltip(state))


class LevelPill(Pill):
    """An alert severity, resolved through the shared status vocabulary."""

    def __init__(self, level=None, filled=True, size=11):
        super().__init__('', t.OFF, filled, size=size)
        if level:
            self.set_level(level)

    def set_level(self, level, text=None):
        state = stat.from_level(level)
        entry = stat.get(state)
        self.set(text or entry.label.upper(), entry.color, entry.mark)
        self.setToolTip(stat.tooltip(state, 'Severity: %s' % entry.label))


class HealthPill(Pill):
    """A device health, resolved through the same vocabulary.

    The engineering term (CONNECTED, DEGRADED, FAULT) is kept in the tooltip so
    nothing is lost, but the word on screen is the one used everywhere else in
    the console.
    """

    def __init__(self, health=None, size=10):
        super().__init__('', t.OFF, filled=False, size=size)
        if health:
            self.set_health(health)

    def set_health(self, health):
        state = stat.from_health(health)
        entry = stat.get(state)
        self.set(entry.label.upper(), entry.color, entry.mark)
        self.setToolTip(stat.tooltip(
            state, 'Device status: %s' % entry.label,
            extra=stat.HEALTH_TERMS.get(health, '')))


class StatTile(QFrame):
    """A caption with one number or short phrase above it."""

    # Wide enough that the value itself never loses a character: the backup
    # thermometer tile reads "6.1 °C  Δ5.3" in a monospaced face, and a
    # narrower floor clipped it to "6.1 °C  Δ5." - a stat tile that drops a
    # digit is worse than one that forces the window a little wider.
    def __init__(self, caption_text, value_size=21, wrap=False, mono=True,
                 minimum_width=116, help=None):
        super().__init__()
        self.value_size = value_size
        self.mono = mono
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style(background=t.PANEL_ALT, radius=t.RADIUS))
        self.setMinimumWidth(minimum_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(3)
        self.valueLabel = t.label('--', size=value_size, bold=True, mono=mono)
        self.valueLabel.setWordWrap(wrap)
        self.captionLabel = t.caption(caption_text, color=t.TEXT_MUTED)
        # Wrapped, not clipped: eight of these share one row on the History
        # page, and a caption like "MINUTES OUT OF RANGE" has no chance of
        # fitting on one line at the console's minimum window width.
        self.captionLabel.setWordWrap(True)
        layout.addWidget(self.valueLabel)
        layout.addWidget(self.captionLabel)
        if help is not None:
            # A tile is a number with a two-word caption: the tooltip is where
            # the rest of the sentence lives.
            self.setToolTip(help.tooltip() if hasattr(help, 'tooltip') else help)

    def set_value(self, text, color=t.TEXT):
        self.valueLabel.setText(str(text))
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: %dpx; font-weight: 600; '
            'background: transparent; border: none;'
            % (color, t.FONT_MONO if self.mono else t.FONT, self.value_size))

    def set_caption(self, text):
        self.captionLabel.setText(text.upper())


class KeyValue(QWidget):
    """One aligned label/value row, for detail panes."""

    def __init__(self, key, value='--', value_color=t.TEXT, key_width=124):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        keyLabel = t.label(key, size=11, color=t.TEXT_MUTED)
        keyLabel.setFixedWidth(key_width)
        self.valueLabel = t.label(value, size=12, color=value_color)
        self.valueLabel.setWordWrap(True)
        row.addWidget(keyLabel, alignment=Qt.AlignTop)
        row.addWidget(self.valueLabel, stretch=1)

    def set_value(self, text, color=t.TEXT):
        self.valueLabel.setText(str(text))
        self.valueLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 12px; background: transparent; '
            'border: none;' % (color, t.FONT))


class EmptyState(QWidget):
    """Shown instead of a blank area when a list has nothing in it.

    An empty list is ambiguous - it can mean "nothing has happened" or "this is
    still loading" or "your filter excluded everything". Each one says which,
    and what would put something here.
    """

    def __init__(self, icon, title, detail='', color=None):
        super().__init__()
        color = color or t.TEXT_MUTED
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(t.SPACE_SM)

        holder = QWidget()
        holder.setStyleSheet('background: transparent;')
        holderRow = QHBoxLayout(holder)
        holderRow.setContentsMargins(0, 0, 0, 0)
        holderRow.addStretch()
        holderRow.addWidget(icons.Icon(icon if icon in icons.ICONS else 'info',
                                       30, color, width=1.5))
        holderRow.addStretch()
        layout.addWidget(holder)

        layout.addWidget(t.label(title, size=t.SIZE_BASE, color=t.TEXT_DIM,
                                 bold=True, align=Qt.AlignCenter))
        if detail:
            note = t.label(detail, size=t.SIZE_XS, color=t.TEXT_MUTED,
                           align=Qt.AlignCenter)
            note.setWordWrap(True)
            layout.addWidget(note)


class LoadingState(QWidget):
    """Shown while a database-backed panel is still being read."""

    def __init__(self, text='Loading…'):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(t.SPACE_SM)
        layout.addWidget(t.label(text, size=t.SIZE_SM, color=t.TEXT_MUTED,
                                 align=Qt.AlignCenter))


class ErrorState(QWidget):
    """Shown when a panel could not load, with what to do about it."""

    def __init__(self, title='Could not load this', detail=''):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(t.SPACE_SM)

        holder = QWidget()
        holder.setStyleSheet('background: transparent;')
        holderRow = QHBoxLayout(holder)
        holderRow.setContentsMargins(0, 0, 0, 0)
        holderRow.addStretch()
        holderRow.addWidget(icons.Icon('mark_warning', 26, t.WARN, width=1.5))
        holderRow.addStretch()
        layout.addWidget(holder)
        layout.addWidget(t.label(title, size=t.SIZE_BASE, color=t.WARN,
                                 bold=True, align=Qt.AlignCenter))
        note = t.label(detail or 'The stored record could not be read. The '
                                 'live readings above are unaffected.',
                       size=t.SIZE_XS, color=t.TEXT_MUTED,
                       align=Qt.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)


# ===========================================================================
#  Transient feedback
# ===========================================================================
class Toast(QFrame):
    """A short-lived confirmation that fades out on its own."""

    def __init__(self, parent, text, color=t.ACCENT, mark='check',
                 duration=3200):
        super().__init__(parent)
        self.setObjectName('toast')
        self.setStyleSheet(
            'QFrame#toast { background-color: %s; border: 1px solid %s; '
            'border-left: 3px solid %s; border-radius: %dpx; }'
            % (t.PANEL_ALT, t.BORDER_STRONG, color, t.RADIUS))
        t.add_shadow(self, blur=30, alpha=150, dy=6)

        row = QHBoxLayout(self)
        row.setContentsMargins(13, 10, 15, 10)
        row.setSpacing(10)
        row.addWidget(icons.Icon(mark if mark in icons.ICONS else 'info', 15,
                                 color, width=1.6),
                      alignment=Qt.AlignTop)
        message = t.label(text, size=t.SIZE_SM)
        message.setWordWrap(True)
        row.addWidget(message, stretch=1)

        self.adjustSize()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._fade_in = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade_in.setDuration(160)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b'opacity', self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.deleteLater)

        self._fade_in.start()
        QTimer.singleShot(duration, self._fade_out.start)


class ToastHost(QWidget):
    """Stacks toasts in the corner of a window without blocking clicks."""

    MARGIN = 18
    GAP = 9

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._toasts = []
        self.setGeometry(parent.rect())

    def show_toast(self, text, color=t.ACCENT, mark='check', duration=3200):
        toast = Toast(self.parentWidget(), text, color, mark, duration)
        toast.destroyed.connect(lambda: self._forget(toast))
        self._toasts.append(toast)
        if len(self._toasts) > 4:
            oldest = self._toasts[0]
            oldest.deleteLater()
        toast.show()
        self._reflow()
        return toast

    def _forget(self, toast):
        try:
            if toast in self._toasts:
                self._toasts.remove(toast)
            self._reflow()
        except RuntimeError:
            pass    # the host itself was destroyed first, during shutdown

    def _reflow(self):
        try:
            parent = self.parentWidget()
        except RuntimeError:
            return
        if parent is None:
            return
        y = parent.height() - self.MARGIN
        for toast in reversed(self._toasts):
            try:
                toast.adjustSize()
                width = max(260, min(430, toast.width()))
                toast.setFixedWidth(width)
                y -= toast.height()
                toast.move(parent.width() - width - self.MARGIN, y)
                y -= self.GAP
            except RuntimeError:
                pass    # already deleted


class ConfirmDialog(QDialog):
    """A styled yes/no dialog for anything with real consequences."""

    def __init__(self, parent, title, message, detail='', confirm_text='Confirm',
                 danger=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet('QDialog { background-color: %s; }' % t.SURFACE)

        accent = t.CRITICAL if danger else t.ACCENT
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(11)
        heading.addWidget(icons.Icon('mark_warning' if danger else 'info', 20,
                                     accent, width=1.7),
                          alignment=Qt.AlignTop)
        headingText = QVBoxLayout()
        headingText.setSpacing(5)
        headingText.addWidget(t.label(title, size=t.SIZE_MD, bold=True))
        body = t.label(message, size=12, color=t.TEXT_DIM)
        body.setWordWrap(True)
        headingText.addWidget(body)
        if detail:
            note = t.label(detail, size=11, color=t.TEXT_MUTED)
            note.setWordWrap(True)
            headingText.addWidget(note)
        heading.addLayout(headingText, stretch=1)
        layout.addLayout(heading)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('Cancel')
        cancel.setStyleSheet(t.ghost_button_style())
        cancel.clicked.connect(self.reject)
        accept = QPushButton(confirm_text)
        accept.setStyleSheet(t.button_style(accent))
        accept.setDefault(True)
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)


def confirm(parent, title, message, detail='', confirm_text='Confirm',
            danger=False):
    dialog = ConfirmDialog(parent, title, message, detail, confirm_text, danger)
    return dialog.exec_() == QDialog.Accepted


# ===========================================================================
#  Small controls
# ===========================================================================
class SegmentedControl(QWidget):
    """A row of mutually exclusive buttons - used for chart time ranges."""

    changed = pyqtSignal(object)

    def __init__(self, options, current=None, tips=None):
        super().__init__()
        self._buttons = {}
        self._value = current if current is not None else options[0][1]

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        for text, value in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c, v=value: self.set_value(v))
            h.set_tip(button, (tips or {}).get(value, 'Show the last %s.' % text))
            self._buttons[value] = button
            row.addWidget(button)
        self._paint()

    def value(self):
        return self._value

    def set_value(self, value, emit=True):
        if value not in self._buttons:
            return
        self._value = value
        self._paint()
        if emit:
            self.changed.emit(value)

    def _paint(self):
        for value, button in self._buttons.items():
            selected = value == self._value
            button.setChecked(selected)
            button.setStyleSheet('''
                QPushButton {
                    background-color: %s; color: %s; border: 1px solid %s;
                    border-radius: %dpx; font-family: %s; font-size: 11px;
                    font-weight: 600; padding: 5px 12px;
                }
                QPushButton:hover { background-color: %s; }
            ''' % (t.PANEL_ALT if selected else 'transparent',
                   t.TEXT if selected else t.TEXT_DIM,
                   t.BORDER_STRONG if selected else t.BORDER,
                   t.RADIUS_SM, t.FONT, t.PANEL_HOVER))


class ToggleRow(QFrame):
    """A labelled switch with a description - the fault-injection control."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, key, title, description, danger=False):
        super().__init__()
        self.key = key
        self.danger = danger
        self._active = False
        self.setObjectName('toggleRow')
        # Fixed height: a card with few faults would otherwise share its spare
        # room out among its rows and leave them looking stretched next to a
        # card with many.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._paint_frame()

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(11)

        text = QVBoxLayout()
        text.setSpacing(2)
        titleRow = QHBoxLayout()
        titleRow.setContentsMargins(0, 0, 0, 0)
        titleRow.setSpacing(6)
        self.armedMark = icons.Icon(stat.mark(stat.SIMULATED), 11, t.SIM,
                                    width=1.5)
        self.armedMark.hide()
        self.titleLabel = t.label(title, size=t.SIZE_SM, bold=True)
        titleRow.addWidget(self.armedMark, alignment=Qt.AlignVCenter)
        titleRow.addWidget(self.titleLabel)
        titleRow.addStretch()
        text.addLayout(titleRow)
        note = t.label(description, size=10, color=t.TEXT_MUTED)
        note.setWordWrap(True)
        text.addWidget(note)
        h.set_help(self, title, description,
                   'Arming this changes what the emulated device really does, so '
                   'the alarm that follows travels the same path a genuine '
                   'failure would.',
                   note='Everything it causes is recorded as SIMULATED.')
        row.addLayout(text, stretch=1)

        self.button = QPushButton('Arm')
        self.button.setFixedWidth(74)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self._clicked)
        row.addWidget(self.button, alignment=Qt.AlignVCenter)
        self._paint_button()

    def _clicked(self):
        self.toggled.emit(self.key, not self._active)

    def set_active(self, active):
        if active == self._active:
            return
        self._active = active
        self._paint_frame()
        self._paint_button()

    def is_active(self):
        return self._active

    def _paint_frame(self):
        if hasattr(self, 'armedMark'):
            self.armedMark.setVisible(self._active)
            self.titleLabel.setToolTip(
                stat.tooltip(stat.SIMULATED) if self._active else '')
        color = t.SIM if self._active else t.BORDER
        self.setStyleSheet(
            'QFrame#toggleRow { background-color: %s; border: 1px solid %s; '
            'border-radius: %dpx; }'
            % (t.PANEL_ALT if self._active else t.PANEL, color, t.RADIUS))

    def _paint_button(self):
        if self._active:
            self.button.setText('Clear')
            self.button.setStyleSheet(t.button_style(t.SIM))
        else:
            self.button.setText('Arm')
            self.button.setStyleSheet(
                t.outline_button_style(t.CRITICAL if self.danger else t.TEXT_DIM))
