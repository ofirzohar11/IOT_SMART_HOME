"""Incidents: every condition the system has raised, with its full lifecycle."""

from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QPushButton, QVBoxLayout,
                             QWidget, QFileDialog, QMessageBox)

from config import devices as registry
from config import mqtt_init as cfg
from database import db
from gui import glossary
from gui.components import IncidentCard
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import theme as t
from ui import widgets as w

RANGE_OPTIONS = [('24H', 24), ('7D', 168), ('30D', 720)]
RANGE_TIPS = {
    24: 'Incidents from the last day.',
    168: 'Incidents from the last seven days.',
    720: 'Incidents from the last thirty days - the usual audit window.',
}
STATUS_OPTIONS = ['All statuses', db.STATUS_ACTIVE, db.STATUS_ACKNOWLEDGED,
                  db.STATUS_RESOLVED]
SEVERITY_OPTIONS = ['All severities'] + list(cfg.LEVELS)


class IncidentsPage(Page):

    title = 'Incidents'
    subtitle = 'What went wrong, why it matters and what to do about it'

    def __init__(self, console):
        super().__init__(console)
        self._hours = 24

        outer = page_layout(self)
        outer.addWidget(h.InlineNote(
            'An incident is a problem the system has opened a case for. It '
            'stays open until the condition goes away or somebody closes it. '
            'Acknowledge means "I am dealing with this" and records your name; '
            'Resolve closes the case - and if the problem is still real, the '
            'system re-opens it within a second.'))
        outer.addWidget(self._build_summary())
        outer.addWidget(self._build_filters())

        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        self.listLayout = QVBoxLayout(inner)
        self.listLayout.setContentsMargins(0, 0, 6, 6)
        self.listLayout.setSpacing(8)
        self.empty = w.EmptyState(
            '✓', 'Nothing to show',
            'No incidents match these filters. Try a wider time range, or set '
            'the filters back to "All".')
        self.listLayout.addWidget(self.empty)
        self.listLayout.addStretch()
        outer.addWidget(scrollable(inner), stretch=1)

    def _build_summary(self):
        card = w.Card('Incident summary', help=glossary.term('incident'))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.activeTile = w.StatTile('still open', help=h.Explain(
            'Still open',
            'Incidents that nobody has closed yet, whether or not they have '
            'been acknowledged.',
            'It is the size of the queue: how much is waiting for somebody.',
            'Zero.'))
        self.criticalTile = w.StatTile('critical open', help=h.Explain(
            'Critical and open',
            'Open incidents where the stock is at risk right now.',
            'These are the ones that cannot wait for the next shift.',
            'Zero.'))
        self.ackTile = w.StatTile('acknowledged', help=glossary.term('acknowledge'))
        self.resolvedTile = w.StatTile('resolved', help=h.Explain(
            'Resolved in this period',
            'Incidents that have been closed within the selected time range.',
            'A useful count for a handover or an audit: how much went wrong, '
            'and how much of it was dealt with.'))
        for tile in (self.activeTile, self.criticalTile, self.ackTile,
                     self.resolvedTile):
            row.addWidget(tile)
        card.add_layout(row)
        return card

    def _build_filters(self):
        card = w.Card('Filters', 'Narrow the list below', help=h.Explain(
            'Filters',
            'Narrow the list to one severity, one device, one status or a '
            'different stretch of time.',
            'A month of incidents is unreadable as one list. Filtering is how '
            'you answer a specific question, such as "what has this fan done '
            'in the last week?".'))
        row = QHBoxLayout()
        row.setSpacing(9)

        self.severityBox = QComboBox()
        self.severityBox.addItems(SEVERITY_OPTIONS)
        self.deviceBox = QComboBox()
        self.deviceBox.addItem('All devices', None)
        for device in registry.DEVICES:
            self.deviceBox.addItem(device.label, device.id)
        self.statusBox = QComboBox()
        self.statusBox.addItems(STATUS_OPTIONS)
        h.set_tip(self.severityBox,
                  'Show only critical problems, only warnings, or everything.')
        h.set_tip(self.deviceBox, 'Show only the incidents raised against one '
                                  'sensor or switch.')
        h.set_tip(self.statusBox, 'Show only incidents that are still open, '
                                  'already acknowledged, or closed.')
        for box in (self.severityBox, self.deviceBox, self.statusBox):
            box.setStyleSheet(t.COMBO_STYLE)
            box.currentIndexChanged.connect(lambda _i: self.refresh())
            row.addWidget(box)

        self.rangeControl = w.SegmentedControl(RANGE_OPTIONS, 24, tips=RANGE_TIPS)
        self.rangeControl.changed.connect(self._change_range)
        row.addWidget(self.rangeControl)
        row.addStretch()

        exportBtn = QPushButton('Export CSV')
        exportBtn.setStyleSheet(t.outline_button_style())
        h.set_help(exportBtn, 'Export to a spreadsheet',
                   'Saves every incident in the selected time range as a CSV '
                   'file you can open in Excel.',
                   'It is the evidence a pharmacy audit or a temperature '
                   'excursion report asks for.')
        exportBtn.clicked.connect(self.export_csv)
        row.addWidget(exportBtn)

        refreshBtn = QPushButton('Refresh')
        refreshBtn.setStyleSheet(t.ghost_button_style())
        h.set_tip(refreshBtn, 'Re-read the list from the stored record. It '
                              'also updates on its own as conditions change.')
        refreshBtn.clicked.connect(self.refresh)
        row.addWidget(refreshBtn)

        card.add_layout(row)
        return card

    def _change_range(self, hours):
        self._hours = hours
        self.refresh()

    def on_shown(self):
        self.refresh()

    def apply_alert(self, record):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        try:
            rows = db.incidents(hours=self._hours, limit=400)
        except Exception as error:
            print('incidents: could not load:', error)
            return

        severity = self.severityBox.currentText()
        device_id = self.deviceBox.currentData()
        status = self.statusBox.currentText()

        active = [r for r in rows if r['status'] != db.STATUS_RESOLVED]
        self.activeTile.set_value(str(len(active)),
                                  t.WARN if active else t.OK)
        criticals = [r for r in active
                     if cfg.normalise_level(r['severity']) == cfg.LEVEL_CRITICAL]
        self.criticalTile.set_value(str(len(criticals)),
                                    t.CRITICAL if criticals else t.OK)
        self.ackTile.set_value(
            str(len([r for r in rows if r['status'] == db.STATUS_ACKNOWLEDGED])))
        self.resolvedTile.set_value(
            str(len([r for r in rows if r['status'] == db.STATUS_RESOLVED])))

        filtered = []
        for row in rows:
            if severity in cfg.LEVELS and cfg.normalise_level(row['severity']) != severity:
                continue
            if device_id and row['device'] != device_id:
                continue
            if status in (db.STATUS_ACTIVE, db.STATUS_ACKNOWLEDGED,
                          db.STATUS_RESOLVED) and row['status'] != status:
                continue
            filtered.append(row)

        for index in reversed(range(self.listLayout.count())):
            item = self.listLayout.itemAt(index)
            widget = item.widget() if item else None
            if widget is not None and widget is not self.empty:
                self.listLayout.takeAt(index)
                w.discard(widget)

        if not filtered:
            self.empty.show()
            return
        self.empty.hide()

        for index, incident in enumerate(filtered[:200]):
            card = IncidentCard(incident)
            card.acknowledged.connect(self.console.acknowledge_incident)
            card.resolved.connect(self.console.resolve_incident)
            self.listLayout.insertWidget(index + 1, card)

    def export_csv(self):
        import os
        from datetime import datetime
        default = os.path.join(
            os.path.expanduser('~'),
            'coldchain_incidents_%s.csv' % datetime.now().strftime('%Y%m%d_%H%M'))
        path, _ = QFileDialog.getSaveFileName(self, 'Export incidents', default,
                                              'CSV files (*.csv)')
        if not path:
            return
        try:
            written = db.export_incidents_csv(path, hours=self._hours)
        except OSError as error:
            QMessageBox.warning(self, 'Export failed', str(error))
            return
        self.console.toast('Exported %d incidents' % written)
