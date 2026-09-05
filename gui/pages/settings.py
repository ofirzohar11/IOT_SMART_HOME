"""Threshold configuration.

Every limit the rule engine enforces is editable here, and nothing on this page
is decorative: a value applied from this screen is written onto the config
module this process reads, saved to disk so it survives a restart, and
published so the data manager and the emulated devices adopt it without being
restarted. The manager echoes back the thresholds it is actually enforcing in
its status snapshot, and the footer compares them against what is on screen, so
"applied" is something the console can show rather than something it assumes.

Three things are shown for every setting, because a number on its own cannot be
judged: what it currently is, what the recommended default is, and what happens
when it is crossed. Where a default comes from published cold-chain guidance the
source is named; where it is a decision made for this project, it says so
instead. Nothing here pretends 2-8 °C is universal - it is what CDC, WHO and USP
give for refrigerated vaccine storage, which is what this unit is for.

Editing is deliberately transactional. Typing changes nothing; Apply validates
the whole form at once - including the relations between settings, such as a
storage band whose edges have crossed - and Cancel puts every field back.
"""

import importlib

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget)

from config import mqtt_init as cfg
from config import settings as thresholds
from gui import glossary
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import theme as t
from ui import widgets as w

# The colour and the wording for each kind of consequence.
EFFECT_STYLE = {
    thresholds.EFFECT_CRITICAL: (t.CRITICAL, 'CRITICAL',
                                 'Crossing this raises a critical alert.'),
    thresholds.EFFECT_WARNING: (t.WARN, 'WARNING',
                                'Crossing this raises a warning.'),
    thresholds.EFFECT_CONTROL: (t.ACCENT, 'CONTROL',
                                'This switches hardware. It raises no alert of '
                                'its own.'),
    thresholds.EFFECT_BASELINE: (t.TEXT_MUTED, 'REFERENCE',
                                 'A healthy reference value. It raises no alert '
                                 'of its own.'),
}

BASIS_STYLE = {
    thresholds.BASIS_RESEARCH: (t.OK, 'RESEARCH',
                                'This default comes from published cold-chain '
                                'guidance, named underneath.'),
    thresholds.BASIS_PROJECT: (t.TEXT_MUTED, 'PROJECT',
                               'No published standard fixes this number. It is '
                               'a decision made for this project, and the '
                               'reasoning is given underneath.'),
}


class SettingRow(QFrame):
    """One editable threshold, with everything needed to judge it."""

    edited = pyqtSignal()

    def __init__(self, setting):
        super().__init__()
        self.setting = setting
        self.setObjectName('settingRow')
        self._border = None
        self._field_border = None
        self._paint(t.BORDER)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 11)
        layout.setSpacing(5)

        effect_color, effect_text, effect_help = EFFECT_STYLE[setting.raises]
        basis_color, basis_text, basis_help = BASIS_STYLE[setting.basis]

        # -- heading: name, what it does, the field itself ----------------
        head = QHBoxLayout()
        head.setSpacing(9)

        name = t.label(setting.label, size=13, bold=True)
        head.addWidget(name)
        head.addWidget(h.set_tip(w.Pill(effect_text, effect_color, filled=False,
                                        size=9), effect_help))
        head.addWidget(h.set_tip(w.Pill(basis_text, basis_color, filled=False,
                                        size=9), basis_help))
        head.addStretch()

        self.field = QLineEdit()
        self.field.setFixedWidth(96)
        self.field.setAlignment(Qt.AlignRight)
        self._paint_field(t.BORDER)
        h.set_help(self.field, setting.label, setting.what,
                   setting.effect,
                   'Recommended %s. Accepts %s.'
                   % (setting.format(setting.recommended), setting.range_text()))
        self.field.textEdited.connect(lambda _text: self.edited.emit())
        head.addWidget(self.field)

        unit = t.label(setting.unit or '', size=11, color=t.TEXT_DIM)
        unit.setFixedWidth(30)
        head.addWidget(unit)

        self.recommendedLabel = t.label('', size=10, color=t.TEXT_MUTED)
        self.recommendedLabel.setFixedWidth(126)
        h.set_help(self.recommendedLabel, 'Recommended default',
                   'The value this setting has until somebody changes it.',
                   note=setting.source)
        head.addWidget(self.recommendedLabel)

        self.resetButton = QPushButton('↺')
        self.resetButton.setFixedWidth(30)
        self.resetButton.setCursor(Qt.PointingHandCursor)
        self.resetButton.setStyleSheet(t.ghost_button_style(t.ACCENT))
        h.set_tip(self.resetButton,
                  'Put %s back to its recommended %s'
                  % (setting.label.lower(),
                     setting.format(setting.recommended)))
        self.resetButton.clicked.connect(self._restore_recommended)
        head.addWidget(self.resetButton)
        layout.addLayout(head)

        # -- what it is ----------------------------------------------------
        what = t.label(setting.what, size=11, color=t.TEXT_DIM)
        what.setWordWrap(True)
        layout.addWidget(what)

        # -- what crossing it does ----------------------------------------
        effect = t.label('→  ' + setting.effect, size=11, color=effect_color)
        effect.setWordWrap(True)
        layout.addWidget(effect)

        # -- where the number came from ------------------------------------
        prefix = ('Research basis' if setting.basis == thresholds.BASIS_RESEARCH
                  else 'Project choice')
        source = t.label('%s — %s' % (prefix, setting.source), size=10,
                         color=t.TEXT_MUTED)
        source.setWordWrap(True)
        layout.addWidget(source)

        # -- validation message, hidden until there is one ------------------
        self.errorLabel = t.label('', size=11, color=t.CRITICAL)
        self.errorLabel.setWordWrap(True)
        self.errorLabel.hide()
        layout.addWidget(self.errorLabel)

    # -- painting ---------------------------------------------------------
    def _paint(self, border_color, background=t.PANEL_ALT):
        # Every keystroke re-validates the whole form and repaints every row,
        # so the stylesheet is only rebuilt when the colour has actually moved.
        if getattr(self, '_border', None) == border_color:
            return
        self._border = border_color
        self.setStyleSheet('QFrame#settingRow { background-color: %s; '
                           'border: 1px solid %s; border-radius: %dpx; }'
                           % (background, border_color, t.RADIUS))

    def _restore_recommended(self):
        self.set_text(self.setting.format(self.setting.recommended,
                                          with_unit=False))
        self.edited.emit()

    # -- state ------------------------------------------------------------
    def set_text(self, text):
        self.field.setText(text)

    def text(self):
        return self.field.text()

    def load(self, value):
        """Show a stored value, clearing any edit in progress."""
        self.set_text(self.setting.format(value, with_unit=False))
        self.show_error(None)

    def show_error(self, message):
        if message:
            self.errorLabel.setText(message)
            self.errorLabel.show()
            self._paint_field(t.CRITICAL)
            self._paint(t.CRITICAL)
        else:
            self.errorLabel.hide()
            self._paint_field(t.BORDER)

    def _paint_field(self, border_color):
        if getattr(self, '_field_border', None) == border_color:
            return
        self._field_border = border_color
        self.field.setStyleSheet(t.line_edit_style(border_color))

    def mark(self, saved_value, has_error):
        """Colour the row by how it stands against what is saved and default."""
        recommended = self.setting.recommended
        overridden = saved_value is not None and saved_value != recommended
        self.recommendedLabel.setText('Recommended %s'
                                      % self.setting.format(recommended))
        self.recommendedLabel.setStyleSheet(
            'color: %s; font-family: %s; font-size: 10px; '
            'background: transparent; border: none;'
            % (t.WARN if overridden else t.TEXT_MUTED, t.FONT))
        # The per-row undo only means anything while the field is off default.
        self.resetButton.setVisible(
            self.text().strip() != self.setting.format(recommended,
                                                       with_unit=False))

        if has_error:
            return              # the error colour wins
        if self.is_dirty(saved_value):
            self._paint(t.ACCENT)       # edited, not yet applied
        elif overridden:
            self._paint(t.WARN)         # applied, but not the recommended value
        else:
            self._paint(t.BORDER)

    def is_dirty(self, saved_value):
        """Whether the field differs from the value currently in force."""
        if saved_value is None:
            return False
        try:
            return self.setting.coerce(self.text().strip()) != saved_value
        except (TypeError, ValueError):
            return True


class SettingsPage(Page):

    title = 'Settings'
    subtitle = 'The limits every alarm on this system is measured against'

    def __init__(self, console):
        super().__init__(console)
        self.rows = {}                  # key -> SettingRow
        self._manager_values = {}       # what the data manager last reported
        self._manager_seen = False

        outer = page_layout(self)
        outer.addWidget(self._build_banner())

        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)
        for group_key, group_title, blurb in thresholds.GROUPS:
            members = thresholds.group_settings(group_key)
            if members:
                body.addWidget(self._build_group(group_title, blurb, members))
        body.addStretch()
        outer.addWidget(scrollable(inner), stretch=1)

        outer.addWidget(self._build_footer())
        self.reload()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_banner(self):
        card = w.Card(padding=13)
        note = h.InlineNote(
            'These are the real limits. A value applied here is saved, sent to '
            'the data manager and the devices, and used by the very next rule '
            'evaluation — nothing on this page is a display setting. Rows '
            'outlined in blue have been edited but not applied; rows outlined '
            'in amber are applied and differ from the recommended default.')
        card.add(note)

        legend = QHBoxLayout()
        legend.setSpacing(8)
        legend.addWidget(t.label('Colour of a limit:', size=11, color=t.TEXT_DIM))
        for effect in (thresholds.EFFECT_CRITICAL, thresholds.EFFECT_WARNING,
                       thresholds.EFFECT_CONTROL, thresholds.EFFECT_BASELINE):
            color, text, tip = EFFECT_STYLE[effect]
            legend.addWidget(h.set_tip(w.Pill(text, color, filled=False, size=9),
                                       tip))
        legend.addSpacing(14)
        legend.addWidget(t.label('Where the default comes from:', size=11,
                                 color=t.TEXT_DIM))
        for basis in (thresholds.BASIS_RESEARCH, thresholds.BASIS_PROJECT):
            color, text, tip = BASIS_STYLE[basis]
            legend.addWidget(h.set_tip(w.Pill(text, color, filled=False, size=9),
                                       tip))
        legend.addStretch()
        card.add_layout(legend)

        card.add(h.HelpNote(
            'The 2–8 °C storage band is what CDC (Vaccine Storage and Handling '
            'Toolkit), WHO (PQS specification E003) and USP <659> all give for '
            'refrigerated vaccine storage, and this unit is built for that. It '
            'is not universal: other medicines have their own ranges, and a '
            'product\'s own package insert always wins. The durations in this '
            'console are deliberately shorter than the real ones — a WHO-listed '
            'monitor alarms after ten continuous hours above 8 °C, which no '
            'demonstration could ever show — and every setting says whether its '
            'default came from guidance or from this project.',
            label='Where these recommended values come from'))
        return card

    def _build_group(self, title, blurb, members):
        card = w.Card(title, blurb)
        for setting in members:
            row = SettingRow(setting)
            row.edited.connect(self._on_edited)
            self.rows[setting.key] = row
            card.add(row)
        return card

    def _build_footer(self):
        bar = QFrame()
        bar.setObjectName('panel')
        bar.setStyleSheet(t.panel_style())

        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 11, 14, 11)
        row.setSpacing(12)

        status = QVBoxLayout()
        status.setSpacing(2)
        self.statusLabel = t.label('', size=12, bold=True)
        self.appliedLabel = t.label('', size=10, color=t.TEXT_MUTED)
        status.addWidget(self.statusLabel)
        status.addWidget(self.appliedLabel)
        row.addLayout(status)
        row.addStretch()

        self.defaultsButton = QPushButton('Restore recommended defaults')
        self.defaultsButton.setStyleSheet(t.outline_button_style(t.TEXT_DIM))
        h.set_help(self.defaultsButton, 'Restore recommended defaults',
                   'Puts every threshold back to the value the system ships '
                   'with and forgets the saved overrides.',
                   'It is the way back to a known-good configuration after an '
                   'experiment, without having to remember what was changed.',
                   note='This asks for confirmation first.')
        self.defaultsButton.clicked.connect(self.restore_defaults)
        row.addWidget(self.defaultsButton)

        self.cancelButton = QPushButton('Cancel')
        self.cancelButton.setStyleSheet(t.ghost_button_style())
        h.set_tip(self.cancelButton,
                  'Discard the edits on this page and show the values that are '
                  'in force')
        self.cancelButton.clicked.connect(self.reload)
        row.addWidget(self.cancelButton)

        self.applyButton = QPushButton('Apply changes')
        self.applyButton.setStyleSheet(t.button_style(t.ACCENT))
        h.set_help(self.applyButton, 'Apply changes',
                   'Validates every field, saves the result, and sends it to '
                   'the data manager and the devices.',
                   'Until this is pressed nothing has changed: the rules are '
                   'still being evaluated against the old limits.',
                   note='Saved settings are reloaded automatically the next '
                        'time the system starts.')
        self.applyButton.clicked.connect(self.apply_changes)
        row.addWidget(self.applyButton)
        return bar

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _saved(self):
        """The values in force in this process, which is what was applied."""
        return thresholds.effective(cfg)

    def reload(self):
        """Fill every field from the values currently in force."""
        current = self._saved()
        for key, row in self.rows.items():
            if key in current:
                row.load(current[key])
        self._refresh()

    def _on_edited(self):
        self._refresh()

    def _collect(self):
        return dict((key, row.text()) for key, row in self.rows.items())

    def _refresh(self):
        """Re-validate the whole form and repaint every row and the footer."""
        current = self._saved()
        _clean, errors = thresholds.validate(self._collect())

        dirty = 0
        for key, row in self.rows.items():
            saved = current.get(key)
            row.show_error(errors.get(key))
            row.mark(saved, key in errors)
            if row.is_dirty(saved):
                dirty += 1

        self._paint_footer(dirty, len(errors))

    def _paint_footer(self, dirty, problems):
        if problems:
            self.statusLabel.setText('%d setting%s cannot be applied'
                                     % (problems, '' if problems == 1 else 's'))
            self.statusLabel.setStyleSheet(
                'color: %s; font-family: %s; font-size: 12px; font-weight: 600; '
                'background: transparent; border: none;' % (t.CRITICAL, t.FONT))
        elif dirty:
            self.statusLabel.setText('%d change%s ready to apply'
                                     % (dirty, '' if dirty == 1 else 's'))
            self.statusLabel.setStyleSheet(
                'color: %s; font-family: %s; font-size: 12px; font-weight: 600; '
                'background: transparent; border: none;' % (t.ACCENT, t.FONT))
        else:
            self.statusLabel.setText('All settings applied')
            self.statusLabel.setStyleSheet(
                'color: %s; font-family: %s; font-size: 12px; font-weight: 600; '
                'background: transparent; border: none;' % (t.OK, t.FONT))

        self.applyButton.setEnabled(bool(dirty) and not problems)
        self.cancelButton.setEnabled(bool(dirty))
        self.appliedLabel.setText(self._applied_text())

    def _applied_text(self):
        """What the data manager says it is actually enforcing."""
        current = self._saved()
        changed = [key for key in thresholds.KEYS
                   if current.get(key) != thresholds.RECOMMENDED.get(key)]
        parts = []
        if changed:
            parts.append('%d of %d differ from the recommended default'
                         % (len(changed), len(thresholds.KEYS)))
        else:
            parts.append('every threshold is at its recommended default')

        if not self._manager_seen:
            parts.append('waiting for the data manager')
        else:
            mismatched = [key for key in thresholds.KEYS
                          if key in self._manager_values
                          and self._manager_values[key] != current.get(key)]
            if mismatched:
                parts.append('data manager still enforcing %d older value%s'
                             % (len(mismatched),
                                '' if len(mismatched) == 1 else 's'))
            else:
                parts.append('data manager confirms it is enforcing these')
        return '  ·  '.join(parts)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _rebuild_wording(self):
        """Rebuild the help text, which quotes the thresholds it explains.

        The glossary reads its numbers from the config module when it is
        imported, so re-importing it after a change is what stops a tooltip
        still promising 2-8 °C on a unit that has been set to 2-6 °C. Screens
        that build their wording as they draw - incidents, the device cards,
        the history columns - pick the new text up on their next refresh.
        """
        try:
            importlib.reload(glossary)
        except Exception as error:
            print('settings | could not rebuild the glossary: %s' % error)

    def apply_changes(self):
        clean, errors = thresholds.validate(self._collect())
        if errors:
            self._refresh()
            self.console.toast(
                '%d setting%s could not be applied - see the rows outlined in '
                'red' % (len(errors), '' if len(errors) == 1 else 's'),
                t.CRITICAL, '■')
            return

        previous = self._saved()
        changed = [key for key in clean if clean[key] != previous.get(key)]
        if not changed:
            self.console.toast('Nothing to apply', t.TEXT_DIM, 'ⓘ')
            return

        # Only the differences are stored, so a later change to a recommended
        # default in the source reaches an installation that never overrode it.
        overrides = dict((key, value) for key, value in clean.items()
                         if value != thresholds.RECOMMENDED.get(key))
        try:
            thresholds.save(overrides)
        except Exception as error:
            self.console.toast('Could not save settings: %s' % error,
                               t.CRITICAL, '■')
            return

        thresholds.apply_to(cfg, clean)
        self._rebuild_wording()
        self.console.publish_settings(clean)
        self.reload()
        self.console.toast('%d threshold%s applied'
                           % (len(changed), '' if len(changed) == 1 else 's'),
                           t.OK, '✓')

    def restore_defaults(self):
        if not w.confirm(
                self, 'Restore recommended defaults?',
                'Every threshold goes back to the value the system ships with, '
                'and the saved overrides are deleted.',
                'The rules start using the restored limits immediately, and '
                'anything that is out of range against them will be raised '
                'within a second.',
                confirm_text='Restore defaults'):
            return
        try:
            thresholds.clear()
        except Exception as error:
            self.console.toast('Could not clear the saved settings: %s' % error,
                               t.CRITICAL, '■')
            return
        thresholds.apply_to(cfg, dict(thresholds.RECOMMENDED))
        self._rebuild_wording()
        self.console.publish_settings(thresholds.effective(cfg))
        self.reload()
        self.console.toast('Recommended defaults restored', t.OK, '✓')

    # ------------------------------------------------------------------
    # Console hooks
    # ------------------------------------------------------------------
    def apply_status(self, data):
        reported = data.get('thresholds')
        if isinstance(reported, dict) and reported:
            self._manager_values = reported
            self._manager_seen = True
            self.appliedLabel.setText(self._applied_text())

    def on_shown(self):
        self._refresh()
