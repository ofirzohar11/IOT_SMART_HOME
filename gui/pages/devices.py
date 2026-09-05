"""Device inventory: what is connected, how fresh its data is, and what it says."""

from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from config import devices as registry
from gui.components import DeviceCard
from gui.pages.base import Page, page_layout, scrollable
from ui import theme as t
from ui import widgets as w

COLUMNS = 4

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
    subtitle = 'Connection, health and freshness'

    def __init__(self, console):
        super().__init__(console)
        self.cards = {}

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
            body.addWidget(w.SectionTitle(group,
                                          '%d devices' % len(members)))
            grid = QGridLayout()
            grid.setSpacing(12)
            for index, device in enumerate(members):
                card = DeviceCard(device)
                self.cards[device.id] = card
                grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            for column in range(COLUMNS):
                grid.setColumnStretch(column, 1)
            body.addLayout(grid)

        body.addStretch()
        outer.addWidget(scrollable(inner))

    def _build_summary(self):
        card = w.Card('Fleet status',
                      'A device is marked offline once it misses three of its '
                      'scheduled slots.')
        row = QHBoxLayout()
        row.setSpacing(10)
        self.tiles = {}
        for health in ('CONNECTED', 'DEGRADED', 'FAULT', 'OFFLINE', 'MAINTENANCE'):
            tile = w.StatTile(health.lower())
            tile.set_value('0', t.health_color(health))
            self.tiles[health] = tile
            row.addWidget(tile)
        card.add_layout(row)
        return card

    def apply_status(self, data):
        health_map = data.get('device_health') or {}
        ages = data.get('device_age_s') or {}
        faults = data.get('simulated_faults') or {}

        counts = {key: 0 for key in self.tiles}
        for device_id, card in self.cards.items():
            health = health_map.get(device_id, 'OFFLINE')
            counts[health] = counts.get(health, 0) + 1
            card.update_state(health, self._value_text(device_id, data),
                              ages.get(device_id), faults.get(device_id) or [])
            value = self._numeric(device_id, data)
            if value is not None and health != 'OFFLINE':
                card.spark.add(value)

        for health, tile in self.tiles.items():
            count = counts.get(health, 0)
            tile.set_value(str(count),
                           t.health_color(health) if count else t.TEXT_MUTED)

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
