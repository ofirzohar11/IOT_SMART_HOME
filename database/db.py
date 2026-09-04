"""SQLite storage for the Cold Chain Monitor.

Two tables are kept:

* ``readings`` - one row every few seconds, the full state of the unit. This is
  the audit trail a regulator would ask for.
* ``events``   - one row per state change of an alert. The data manager only
  writes here when a condition starts or clears, so the table stays readable
  instead of repeating the same warning hundreds of times.

The data manager writes while the GUI reads, so the database runs in WAL mode
and every call uses its own short lived connection.
"""

import csv
import os
import sqlite3
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coldchain.db')

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def now_string():
    return datetime.now().strftime(TIME_FORMAT)


def init_db():
    """Create the schema. Safe to call on every start-up."""
    conn = _connect()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT NOT NULL,
            temperature   REAL,
            humidity      REAL,
            door_state    TEXT,
            power_source  TEXT,
            battery_level REAL,
            compressor    TEXT,
            fan           TEXT,
            siren         TEXT,
            alert_level   TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            level   TEXT NOT NULL,
            code    TEXT NOT NULL,
            message TEXT NOT NULL
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)')
    conn.commit()
    conn.close()


def insert_reading(temperature, humidity, door_state, power_source, battery_level,
                   compressor, fan, siren, alert_level):
    conn = _connect()
    conn.execute('''
        INSERT INTO readings (ts, temperature, humidity, door_state, power_source,
                              battery_level, compressor, fan, siren, alert_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (now_string(), temperature, humidity, door_state, power_source,
          battery_level, compressor, fan, siren, alert_level))
    conn.commit()
    conn.close()


def insert_event(level, code, message):
    conn = _connect()
    conn.execute('INSERT INTO events (ts, level, code, message) VALUES (?, ?, ?, ?)',
                 (now_string(), level, code, message))
    conn.commit()
    conn.close()


def recent_readings(limit=200):
    """Newest first."""
    conn = _connect()
    rows = conn.execute('''
        SELECT ts, temperature, humidity, door_state, power_source, battery_level,
               compressor, fan, siren, alert_level
        FROM readings ORDER BY id DESC LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return rows


def recent_events(limit=100):
    """Newest first."""
    conn = _connect()
    rows = conn.execute(
        'SELECT ts, level, code, message FROM events ORDER BY id DESC LIMIT ?',
        (limit,)).fetchall()
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
    }


def export_readings_csv(path, limit=5000):
    """Write the newest readings to a CSV file and return how many rows were written."""
    rows = recent_readings(limit)
    header = ['timestamp', 'temperature_c', 'humidity_pct', 'door', 'power',
              'battery_pct', 'compressor', 'fan', 'siren', 'alert_level']
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(reversed(rows))  # oldest first reads better in a report
    return len(rows)


if __name__ == '__main__':
    init_db()
    print('database ready at', DB_FILE)
