"""Fault injection console.

Every rule this system enforces should be demonstrable on demand, otherwise
nobody can tell a working alarm from one that has never fired. This page arms
real failures in the emulated hardware - the devices genuinely stop publishing,
genuinely draw no current, genuinely report a frozen value - so the alarm path
that runs is the same one a real fault would take. Nothing here writes fake
readings into the database or fakes an alert.

The page is deliberately separated from the operational screens, every armed
fault is labelled SIMULATED everywhere it surfaces, and anything with real
consequences asks first.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QPushButton,
                             QVBoxLayout, QWidget)

from config import devices as registry
from gui import glossary
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import theme as t
from ui import widgets as w

COLUMNS = 2


class ScenarioCard(QFrame):
    """A one-click multi-device failure, with what to expect from it."""

    def __init__(self, scenario, on_run):
        super().__init__()
        self.scenario = scenario
        self.setObjectName('panel')
        self.setStyleSheet(t.panel_style(background=t.PANEL_ALT, radius=t.RADIUS))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        layout.addWidget(t.label(scenario.label, size=13, bold=True))
        description = t.label(scenario.description, size=11, color=t.TEXT_DIM)
        description.setWordWrap(True)
        layout.addWidget(description)

        expectation = t.prose(scenario.expectation, lead='Expect')
        expectation.setWordWrap(True)
        layout.addWidget(expectation)
        layout.addStretch()

        button = QPushButton('Run scenario')
        button.setStyleSheet(t.outline_button_style(t.SIM))
        h.set_help(button, 'Run "%s"' % scenario.label, scenario.description,
                   'A drill proves the alarms work. Until one has been run, a '
                   'silent system and a broken one look identical.',
                   note='Expect: %s' % scenario.expectation)
        button.clicked.connect(lambda: on_run(scenario))
        layout.addWidget(button, alignment=Qt.AlignLeft)


class SimulationsPage(Page):

    title = 'Simulations'
    subtitle = 'Break something on purpose, and watch the alarms catch it'

    def __init__(self, console):
        super().__init__(console)
        self.rows = {}          # 'device:fault' -> ToggleRow

        outer = page_layout(self)
        outer.addWidget(self._build_banner())

        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)

        body.addWidget(self._build_scenarios())
        for group in registry.GROUPS:
            members = [d for d in registry.DEVICES if d.group == group]
            if members:
                body.addWidget(w.SectionTitle(
                    '%s faults' % group, glossary.GROUPS.get(group, ''),
                    help=h.Explain(
                        '%s faults' % group,
                        'Individual failures you can arm on each device in the '
                        '%s group.' % group.lower(),
                        'Arming one fault at a time is how you check that a '
                        'single rule fires - and, just as importantly, that '
                        'nothing else fires with it.')))
                body.addWidget(self._build_group(members))
        body.addStretch()
        outer.addWidget(scrollable(inner), stretch=1)

    # -- construction ------------------------------------------------------
    def _build_banner(self):
        frame = QFrame()
        frame.setObjectName('panel')
        frame.setStyleSheet(
            'QFrame#panel { background-color: %s; border: 1px solid %s; '
            'border-left: 4px solid %s; border-radius: %dpx; }'
            % (t.PANEL, t.BORDER, t.SIM, t.RADIUS_LG))
        row = QHBoxLayout(frame)
        row.setContentsMargins(18, 13, 18, 13)
        row.setSpacing(14)

        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(t.label('Test the alarms by breaking something on purpose',
                               size=14, bold=True))
        self.summaryLabel = t.label(
            'Arming a fault changes what an emulated device really does - it '
            'genuinely stops publishing, genuinely draws no current. The alarm '
            'that follows is raised by the same rules as a real failure, and '
            'everything it causes is labelled SIMULATED.',
            size=11, color=t.TEXT_DIM)
        self.summaryLabel.setWordWrap(True)
        text.addWidget(self.summaryLabel)
        row.addLayout(text, stretch=1)

        self.activePill = w.Pill('0 armed', t.TEXT_MUTED, filled=False, size=12)
        h.set_help(self.activePill, 'Armed faults',
                   'How many simulated faults are currently active.',
                   'Anything left armed keeps producing alarms, so this number '
                   'should be zero whenever a drill is finished.', 'Zero.')
        row.addWidget(self.activePill)

        self.resetButton = QPushButton('Reset all simulations')
        self.resetButton.setStyleSheet(t.button_style(t.SIM))
        h.set_help(self.resetButton, 'Reset everything',
                   'Clears every armed fault on every device at once.',
                   'It is the one-click way back to normal after a drill.',
                   note='Devices return to normal behaviour immediately.')
        self.resetButton.clicked.connect(self._reset_all)
        row.addWidget(self.resetButton)
        return frame

    def _build_scenarios(self):
        card = w.Card(
            'Ready-made drills', 'One click arms a realistic failure',
            help=h.Explain(
                'Ready-made drills',
                'Each one arms several faults at once to reproduce a failure '
                'the way it happens in real life.',
                'Real failures are rarely a single broken part. A power cut '
                'drains a battery; a dead compressor also warms the cabinet. '
                'These reproduce the whole chain.',
                note='Every drill is reversible with "Reset all simulations".'))
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, scenario in enumerate(registry.SCENARIOS):
            grid.addWidget(ScenarioCard(scenario, self._run_scenario),
                           index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        card.add_layout(grid)
        return card

    def _build_group(self, devices):
        container = QWidget()
        container.setStyleSheet('background: transparent;')
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        for index, device in enumerate(devices):
            entry = glossary.device(device.id)
            # Plain name in the heading, engineering name directly underneath:
            # the same pairing the Devices page uses, so a device can be found
            # by either of its names.
            card = w.Card(entry.name if entry else device.label,
                          '%s · %s' % (device.label, device.describes),
                          help=entry, icon=device.icon)
            for fault in device.faults:
                key = '%s:%s' % (device.id, fault.id)
                row = w.ToggleRow(key, fault.label, fault.description,
                                  danger=fault.confirm)
                row.toggled.connect(self._toggle)
                self.rows[key] = row
                card.add(row)
            # Top-aligned so a device with three faults keeps its natural
            # height instead of being stretched to match one with eleven.
            grid.addWidget(card, index // COLUMNS, index % COLUMNS,
                           Qt.AlignTop)
        for column in range(COLUMNS):
            grid.setColumnStretch(column, 1)
        return container

    # -- actions -----------------------------------------------------------
    def _toggle(self, key, active):
        device_id, fault_id = key.split(':', 1)
        device = registry.get(device_id)
        fault = device.fault(fault_id) if device else None
        if fault is None:
            return

        if active and fault.confirm:
            if not w.confirm(
                    self.window(), 'Arm %s?' % fault.label,
                    '%s on %s.' % (fault.description, device.label),
                    'The device will really behave this way until you clear it. '
                    'Everything it causes is recorded as SIMULATED.',
                    confirm_text='Arm fault', danger=True):
                return

        self.console.set_fault(device_id, fault_id, active)
        self.console.toast(
            '%s %s on %s' % (fault.label, 'armed' if active else 'cleared',
                             device.label),
            t.SIM if active else t.OK, 'mark_simulated' if active else 'check')

    def _run_scenario(self, scenario):
        if not w.confirm(self.window(), 'Run "%s"?' % scenario.label,
                         scenario.description,
                         'Expect: %s' % scenario.expectation,
                         confirm_text='Run scenario', danger=True):
            return
        for device_id, fault_id in scenario.faults:
            self.console.set_fault(device_id, fault_id, True)
        self.console.toast('Scenario "%s" is running' % scenario.label,
                           t.SIM, 'mark_simulated')

    def _reset_all(self):
        if not any(row.is_active() for row in self.rows.values()):
            self.console.toast('No simulations are armed', t.TEXT_DIM, 'info')
            return
        if not w.confirm(self.window(), 'Reset every simulation?',
                         'All armed faults will be cleared on every device.',
                         'Devices return to normal behaviour immediately.',
                         confirm_text='Reset all'):
            return
        self.console.clear_all_faults()
        self.console.toast('All simulations cleared', t.OK)

    # -- live state --------------------------------------------------------
    def apply_status(self, data):
        faults = data.get('simulated_faults') or {}
        armed = set()
        for device_id, fault_ids in faults.items():
            for fault_id in fault_ids:
                armed.add('%s:%s' % (device_id, fault_id))

        for key, row in self.rows.items():
            row.set_active(key in armed)

        count = len(armed)
        self.activePill.set('%d armed' % count,
                            t.SIM if count else t.TEXT_MUTED,
                            'mark_simulated' if count else 'mark_offline')
        self.resetButton.setEnabled(count > 0)
