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
from gui.pages.base import Page, page_layout, scrollable
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

        expectation = t.label('Expect: ' + scenario.expectation, size=10,
                              color=t.TEXT_MUTED)
        expectation.setWordWrap(True)
        layout.addWidget(expectation)
        layout.addStretch()

        button = QPushButton('Run scenario')
        button.setStyleSheet(t.outline_button_style(t.SIM))
        button.clicked.connect(lambda: on_run(scenario))
        layout.addWidget(button, alignment=Qt.AlignLeft)


class SimulationsPage(Page):

    title = 'Simulations'
    subtitle = 'Fault injection and drills'

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
                body.addWidget(w.SectionTitle('%s faults' % group))
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
        text.addWidget(t.label('Fault injection is live', size=14, bold=True))
        self.summaryLabel = t.label(
            'Arming a fault changes the real behaviour of an emulated device. '
            'The alarms that follow are produced by the same rules as a genuine '
            'failure.', size=11, color=t.TEXT_DIM)
        self.summaryLabel.setWordWrap(True)
        text.addWidget(self.summaryLabel)
        row.addLayout(text, stretch=1)

        self.activePill = w.Pill('0 armed', t.TEXT_MUTED, filled=False, size=12)
        row.addWidget(self.activePill)

        self.resetButton = QPushButton('Reset all simulations')
        self.resetButton.setStyleSheet(t.button_style(t.SIM))
        self.resetButton.clicked.connect(self._reset_all)
        row.addWidget(self.resetButton)
        return frame

    def _build_scenarios(self):
        card = w.Card('Scenarios',
                      'Realistic multi-device failures for a drill or a demo.')
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
            card = w.Card('%s  %s' % (device.icon, device.label),
                          device.describes)
            for fault in device.faults:
                key = '%s:%s' % (device.id, fault.id)
                row = w.ToggleRow(key, fault.label, fault.description,
                                  danger=fault.confirm)
                row.toggled.connect(self._toggle)
                self.rows[key] = row
                card.add(row)
            grid.addWidget(card, index // COLUMNS, index % COLUMNS)
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
            t.SIM if active else t.OK, '⚠' if active else '✓')

    def _run_scenario(self, scenario):
        if not w.confirm(self.window(), 'Run "%s"?' % scenario.label,
                         scenario.description,
                         'Expect: %s' % scenario.expectation,
                         confirm_text='Run scenario', danger=True):
            return
        for device_id, fault_id in scenario.faults:
            self.console.set_fault(device_id, fault_id, True)
        self.console.toast('Scenario "%s" is running' % scenario.label,
                           t.SIM, '⚠')

    def _reset_all(self):
        if not any(row.is_active() for row in self.rows.values()):
            self.console.toast('No simulations are armed', t.TEXT_DIM, 'ⓘ')
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
                            '⚠' if count else '○')
        self.resetButton.setEnabled(count > 0)
