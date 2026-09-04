"""SQLite storage for the Cold Chain Monitor.

Two tables are kept:

* ``readings`` - one row every few seconds, the full state of the unit. This is
  the audit trail a regulator would ask for.
* ``events``   - one row per state change of an alert. The data manager only
  writes here when a condition starts or clears, so the table stays readable
  instead of repeating the same warning hundreds of times.

The data manager writes while the GUI reads, so the database runs in WAL mode
and every call uses its own short lived connection.

The reading columns are declared once in ``READING_FIELDS`` and the INSERT is
built from that list, so adding a sensor means adding one entry here. Databases
created by an earlier version are upgraded in place by ``_ensure_columns``
rather than having to be deleted.
"""

import csv
import os
import sqlite3
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coldchain.db')

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# (column name, SQL type) in the order they are stored and displayed.
READING_FIELDS = [
    ('temperature', 'REAL'),         # primary probe
    ('temperature_b', 'REAL'),       # redundant probe
    ('ambient', 'REAL'),             # room temperature outside the unit
    ('humidity', 'REAL'),
    ('door_state', 'TEXT'),
    ('operator', 'TEXT'),            # who the door opening is attributed to
    ('power_source', 'TEXT'),
    ('battery_level', 'REAL'),
    ('compressor', 'TEXT'),          # commanded state
    ('compressor_current', 'REAL'),  # measured current draw
    ('fan', 'TEXT'),                 # commanded state
    ('fan_rpm', 'REAL'),             # measured speed
    ('siren', 'TEXT'),
    ('alert_level', 'TEXT'),
]

READING_NAMES = [name for name, _ in READING_FIELDS]

EVENT_FIELDS = [
    ('level', 'TEXT'),
    ('code', 'TEXT'),
    ('message', 'TEXT'),
    ('operator', 'TEXT'),
]


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def now_string():
    return datetime.now().strftime(TIME_FORMAT)


def _ensure_columns(conn, table, fields):
    """Add any column the table is missing, so older databases keep working."""
    existing = {row[1] for row in conn.execute('PRAGMA table_info(%s)' % table)}
    for name, sql_type in fields:
        if name not in existing:
            conn.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, name, sql_type))


def init_db():
    """Create or upgrade the schema. Safe to call on every start-up."""
    conn = _connect()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL
        )
    ''')
    _ensure_columns(conn, 'readings', READING_FIELDS)
    _ensure_columns(conn, 'events', EVENT_FIELDS)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)')
    conn.commit()
    conn.close()


def insert_reading(**values):
    """Store one snapshot. Unknown keys are ignored, missing ones become NULL."""
    columns = ['ts'] + READING_NAMES
    row = [now_string()] + [values.get(name) for name in READING_NAMES]
    placeholders = ', '.join('?' * len(columns))
    conn = _connect()
    conn.execute('INSERT INTO readings (%s) VALUES (%s)'
                 % (', '.join(columns), placeholders), row)
    conn.commit()
    conn.close()


def insert_event(level, code, message, operator=None):
    conn = _connect()
    conn.execute('INSERT INTO events (ts, level, code, message, operator) '
                 'VALUES (?, ?, ?, ?, ?)',
                 (now_string(), level, code, message, operator))
    conn.commit()
    conn.close()


def recent_readings(limit=200):
    """Newest first. Columns are ``ts`` followed by READING_NAMES."""
    conn = _connect()
    rows = conn.execute(
        'SELECT ts, %s FROM readings ORDER BY id DESC LIMIT ?'
        % ', '.join(READING_NAMES), (limit,)).fetchall()
    conn.close()
    return rows


def recent_events(limit=100):
    """Newest first."""
    conn = _connect()
    rows = conn.execute(
        'SELECT ts, level, code, message, operator FROM events '
        'ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return rows


def stats_since(hours=24, target_min=2.0, target_max=8.0, sample_seconds=5.0):
    """Summary of the last `hours` hours, used by the History tab.

    ``excursion_minutes`` is an estimate: the number of stored readings that sat
    outside the target band multiplied by the sampling interval.
    """
    since = (datetime.now() - timedelta(hours=hours)).strftime(TIME_FORMAT)
    conn = _connect()

    row = conn.execute('''
        SELECT COUNT(*), MIN(temperature), MAX(temperature), AVG(temperature)
        FROM readings WHERE ts >= ?
    ''', (since,)).fetchone()

    outside = conn.execute('''
        SELECT COUNT(*) FROM readings
        WHERE ts >= ? AND temperature IS NOT NULL
          AND (temperature < ? OR temperature > ?)
    ''', (since, target_min, target_max)).fetchone()[0]

    alarms = conn.execute(
        "SELECT COUNT(*) FROM events WHERE ts >= ? AND level = 'ALARM'",
        (since,)).fetchone()[0]

    warnings = conn.execute(
        "SELECT COUNT(*) FROM events WHERE ts >= ? AND level = 'WARNING'",
        (since,)).fetchone()[0]

    door_events = conn.execute(
        "SELECT COUNT(*) FROM events WHERE ts >= ? AND code = 'DOOR_OPEN'",
        (since,)).fetchone()[0]

    conn.close()

    count, t_min, t_max, t_avg = row
    return {
        'samples': count or 0,
        'temp_min': t_min,
        'temp_max': t_max,
        'temp_avg': t_avg,
        'excursion_minutes': round(outside * sample_seconds / 60.0, 1),
        'alarms': alarms,
        'warnings': warnings,
        'door_events': door_events,
    }


def export_readings_csv(path, limit=5000):
    """Write the newest readings to a CSV file and return how many rows were written."""
    rows = recent_readings(limit)
    header = ['timestamp'] + READING_NAMES
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(reversed(rows))  # oldest first reads better in a report
    return len(rows)


if __name__ == '__main__':
    init_db()
    print('database ready at', DB_FILE)
    print('reading columns:', ', '.join(READING_NAMES))
