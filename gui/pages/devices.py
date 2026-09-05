"""Device inventory: what is connected, how fresh its data is, and what it says."""

from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from config import devices as registry
from database import db
from gui import glossary
from gui.components import DeviceCard
from gui.pages.base import Page, page_layout, scrollable
from ui import help as h
from ui import status as stat
from ui import theme as t
from ui import widgets as w

# Three across rather than four: each card now carries its location, what it
# measures, why it matters and - when something is wrong - the recommended
# action, and four columns squeezed those into unreadable ribbons.
COLUMNS = 3

# How to render each device's headline value from the status snapshot.
VALUE_FIELDS = {
    'temp': ('temperature', '%.1f °C'),
    'temp_b': ('temperature_b', '%.1f °C'),
    'ambient': ('ambient', '%.1f °C'),
    'power': ('battery', '%.0f %%'),
    'current': ('compressor_current', '%.2f A'),
    'fan_rpm': ('fan_rpm', '%.0f rpm'),
    'door': ('door', '%s'),
    'compressor': ('compressor', '%s'),
    'fan': ('fan', '%s'),
    'siren': ('siren', '%s'),
}


class DevicesPage(Page):

    title = 'Devices'
    subtitle = 'Every sensor and switch, and whether it is still talking'

    def __init__(self, console):
        super().__init__(console)
        self.cards = {}
        self._incidents = {}        # device id -> open incidents

        outer = page_layout(self)
        inner = QWidget()
        inner.setStyleSheet('background: transparent;')
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 6)
        body.setSpacing(12)

        body.addWidget(self._build_summary())

        for group in registry.GROUPS:
            members = [d for d in registry.DEVICES if d.group == group]
            if not members:
                continue
            body.addWidget(w.SectionTitle(
                group, glossary.GROUPS.get(group, '%d devices' % len(members)),
                help=h.Explain(
                    group, glossary.GROUPS.get(group, ''),
                    'Grouping the devices by where they sit makes it obvious '
                    'who to call: the cabinet is stock, the plant is '
                    'refrigeration, the facility is the building.',
                    '%d devices, all connected.' % len(members))))
            grid = QGridLayout()
            grid.setSpacing(12)
            for index, device in enumerate(members):
                card = DeviceCard(device)
                self.cards[device.id] = card
                # Deliberately stretched rather than top-aligned: a row of
                # cards with ragged bottoms reads as a broken layout, and each
                # card packs its content to the top anyway.
                grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            for column in range(COLUMNS):
                grid.setColumnStretch(column, 1)
            body.addLayout(grid)

        body.addStretch()
        outer.addWidget(scrollable(inner))

    # The five health states the data manager reports, in the order an
    # operator triages them, each shown under the console-wide status word.
    SUMMARY_ORDER = ('CONNECTED', 'DEGRADED', 'FAULT', 'OFFLINE', 'MAINTENANCE')

    def _build_summary(self):
        card = w.Card(
            'Fleet status',
            'How many devices are in each state right now',
            help=glossary.term('health'))
        row = QHBoxLayout()
        row.setSpacing(t.SPACE_SM)
        self.tiles = {}
        for health in self.SUMMARY_ORDER:
            state = stat.from_health(health)
            entry = stat.get(state)
            tile = w.StatTile(entry.label, help=h.Explain(
                entry.label, entry.what, entry.why,
                note=stat.HEALTH_TERMS.get(health, '')))
            tile.set_value('0', entry.color)
            self.tiles[health] = tile
            row.addWidget(tile)
        card.add_layout(row)
        # The five words are meaningless on their own, and this is the first
        # thing somebody reads on a page they have never opened.
        card.add(h.InlineNote(
            'Normal = reporting on schedule and inside its expected range.   '
            'Warning = still reporting, but something is outside that range.   '
            'Critical = its readings contradict what the equipment was told to '
            'do.   Offline = it has stopped reporting, so whatever it was '
            'checking is no longer checked.   Maintenance = deliberately '
            'excused while the unit is serviced.'))
        return card

    # -- incidents ---------------------------------------------------------
    def _load_incidents(self):
        """Group the open incidents by device, for the cards to show."""
        grouped = {}
        try:
            for row in db.active_incidents():
                device_id = row.get('device')
                if device_id:
                    grouped.setdefault(device_id, []).append(row)
        except Exception as error:
            print('devices: could not load incidents:', error)
            return
        self._incidents = grouped

    def on_shown(self):
        self._load_incidents()

    def apply_alert(self, record):
        self._load_incidents()

    def refresh_incidents(self):
        self._load_incidents()

    def apply_status(self, data):
        health_map = data.get('device_health') or {}
        ages = data.get('device_age_s') or {}
        faults = data.get('simulated_faults') or {}

        counts = {key: 0 for key in self.tiles}
        for device_id, card in self.cards.items():
            health = health_map.get(device_id, 'OFFLINE')
            counts[health] = counts.get(health, 0) + 1
            card.update_state(health, self._value_text(device_id, data),
                              ages.get(device_id), faults.get(device_id) or [],
                              self._incidents.get(device_id) or [])
            value = self._numeric(device_id, data)
            if value is not None and health != 'OFFLINE':
                card.spark.add(value)
                card.spark.show()

        for health, tile in self.tiles.items():
            count = counts.get(health, 0)
            tile.set_value(str(count),
                           stat.color(stat.from_health(health)) if count
                           else t.TEXT_MUTED)

    def _value_text(self, device_id, data):
        spec = VALUE_FIELDS.get(device_id)
        if not spec:
            return '--'
        field, fmt = spec
        value = data.get(field)
        if value is None:
            return '--'
        try:
            return fmt % value
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _numeric(device_id, data):
        spec = VALUE_FIELDS.get(device_id)
        if not spec:
            return None
        value = data.get(spec[0])
        return value if isinstance(value, (int, float)) else None
