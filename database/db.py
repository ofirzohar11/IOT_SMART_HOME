"""SQLite storage for the Cold Chain Monitor.

Three tables:

* ``readings``  - a full state snapshot every few seconds. The audit trail a
  regulator would ask for, and the source for every chart.
* ``events``    - one row per alert transition, for the live log.
* ``incidents`` - the lifecycle of a condition: when it started, when it ended,
  who acknowledged it and what the system believed the cause was. An event says
  *something happened*; an incident says *something is wrong and here is its
  history*.

The data manager writes while the GUI reads, so the database runs in WAL mode,
every call uses its own short-lived connection, and writes retry briefly when
SQLite reports the file as busy.

Reading columns are declared once in ``READING_FIELDS`` and the INSERT is built
from that list, so adding a sensor means adding one entry. Databases written by
an earlier version are upgraded in place rather than having to be deleted.
"""

import csv
import os
import sqlite3
import time
from datetime import datetime, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coldchain.db')

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# Incident lifecycle
STATUS_ACTIVE = 'ACTIVE'
STATUS_ACKNOWLEDGED = 'ACKNOWLEDGED'
STATUS_RESOLVED = 'RESOLVED'

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
    ('device', 'TEXT'),
    ('simulated', 'INTEGER'),
]

INCIDENT_FIELDS = [
    ('code', 'TEXT'),
    ('severity', 'TEXT'),
    ('device', 'TEXT'),
    ('message', 'TEXT'),
    ('root_cause', 'TEXT'),
    ('started_at', 'TEXT'),
    ('ended_at', 'TEXT'),
    ('acknowledged_at', 'TEXT'),
    ('acknowledged_by', 'TEXT'),
    ('status', 'TEXT'),
    ('simulated', 'INTEGER'),
]

_BUSY_RETRIES = 4


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def _write(sql, params=(), returning_id=False):
    """Run a write, retrying briefly if another process holds the file."""
    last_error = None
    for attempt in range(_BUSY_RETRIES):
        try:
            conn = _connect()
            try:
                cursor = conn.execute(sql, params)
                conn.commit()
                return cursor.lastrowid if returning_id else cursor.rowcount
            finally:
                conn.close()
        except sqlite3.OperationalError as error:
            last_error = error
            if 'locked' not in str(error) and 'busy' not in str(error):
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last_error


def _read(sql, params=()):
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def now_string():
    return datetime.now().strftime(TIME_FORMAT)


def _since(hours):
    return (datetime.now() - timedelta(hours=hours)).strftime(TIME_FORMAT)


def _ensure_columns(conn, table, fields):
    """Add any column the table is missing, so older databases keep working."""
    existing = {row[1] for row in conn.execute('PRAGMA table_info(%s)' % table)}
    for name, sql_type in fields:
        if name not in existing:
            conn.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, name, sql_type))


def init_db():
    """Create or upgrade the schema. Safe to call on every start-up."""
    conn = _connect()
    try:
        for table in ('readings', 'events', 'incidents'):
            conn.execute('CREATE TABLE IF NOT EXISTS %s ('
                         'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                         'ts TEXT NOT NULL)' % table)
        _ensure_columns(conn, 'readings', READING_FIELDS)
        _ensure_columns(conn, 'events', EVENT_FIELDS)
        _ensure_columns(conn, 'incidents', INCIDENT_FIELDS)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_incidents_status '
                     'ON incidents(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(ts)')
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Readings
# --------------------------------------------------------------------------
def insert_reading(**values):
    """Store one snapshot. Unknown keys are ignored, missing ones become NULL."""
    columns = ['ts'] + READING_NAMES
    row = [now_string()] + [values.get(name) for name in READING_NAMES]
    _write('INSERT INTO readings (%s) VALUES (%s)'
           % (', '.join(columns), ', '.join('?' * len(columns))), row)


def recent_readings(limit=200):
    """Newest first. Columns are ``ts`` followed by READING_NAMES."""
    return _read('SELECT ts, %s FROM readings ORDER BY id DESC LIMIT ?'
                 % ', '.join(READING_NAMES), (limit,))


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
def insert_event(level, code, message, operator=None, device=None,
                 simulated=False):
    _write('INSERT INTO events (ts, level, code, message, operator, device, '
           'simulated) VALUES (?, ?, ?, ?, ?, ?, ?)',
           (now_string(), level, code, message, operator, device,
            1 if simulated else 0))


def recent_events(limit=100):
    """Newest first."""
    return _read('SELECT ts, level, code, message, operator, device, simulated '
                 'FROM events ORDER BY id DESC LIMIT ?', (limit,))


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------
def open_incident(code, severity, device, message, root_cause=None,
                  simulated=False):
    """Start an incident, or escalate the one already open for this code.

    Returns the incident id. Re-raising the same code at the same severity is a
    no-op, so a condition that persists for ten minutes stays one incident.
    """
    rows = _read('SELECT id, severity FROM incidents WHERE code = ? AND status '
                 'IN (?, ?) ORDER BY id DESC LIMIT 1',
                 (code, STATUS_ACTIVE, STATUS_ACKNOWLEDGED))
    if rows:
        incident_id, current = rows[0]
        if current != severity:
            _write('UPDATE incidents SET severity = ?, message = ?, '
                   'root_cause = COALESCE(?, root_cause) WHERE id = ?',
                   (severity, message, root_cause, incident_id))
        return incident_id

    stamp = now_string()
    return _write(
        'INSERT INTO incidents (ts, code, severity, device, message, '
        'root_cause, started_at, status, simulated) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (stamp, code, severity, device, message, root_cause, stamp,
         STATUS_ACTIVE, 1 if simulated else 0), returning_id=True)


def close_incident(code):
    """Resolve whatever is open for this code. Returns how many rows changed."""
    return _write('UPDATE incidents SET status = ?, ended_at = ? '
                  'WHERE code = ? AND status IN (?, ?)',
                  (STATUS_RESOLVED, now_string(), code,
                   STATUS_ACTIVE, STATUS_ACKNOWLEDGED))


def acknowledge_incident(incident_id, operator):
    return _write('UPDATE incidents SET status = ?, acknowledged_at = ?, '
                  'acknowledged_by = ? WHERE id = ? AND status = ?',
                  (STATUS_ACKNOWLEDGED, now_string(), operator, incident_id,
                   STATUS_ACTIVE))


def resolve_incident(incident_id, operator):
    return _write('UPDATE incidents SET status = ?, ended_at = ?, '
                  'acknowledged_by = COALESCE(acknowledged_by, ?) '
                  'WHERE id = ? AND status IN (?, ?)',
                  (STATUS_RESOLVED, now_string(), operator, incident_id,
                   STATUS_ACTIVE, STATUS_ACKNOWLEDGED))


INCIDENT_COLUMNS = ('id', 'code', 'severity', 'device', 'message', 'root_cause',
                    'started_at', 'ended_at', 'acknowledged_at',
                    'acknowledged_by', 'status', 'simulated')


def _incident_rows(sql, params):
    return [dict(zip(INCIDENT_COLUMNS, row)) for row in _read(sql, params)]


def active_incidents():
    return _incident_rows(
        'SELECT %s FROM incidents WHERE status IN (?, ?) ORDER BY id DESC'
        % ', '.join(INCIDENT_COLUMNS), (STATUS_ACTIVE, STATUS_ACKNOWLEDGED))


def incidents(hours=24, limit=400):
    return _incident_rows(
        'SELECT %s FROM incidents WHERE started_at >= ? ORDER BY id DESC LIMIT ?'
        % ', '.join(INCIDENT_COLUMNS), (_since(hours), limit))


def incident_counts():
    rows = _read('SELECT severity, COUNT(*) FROM incidents '
                 'WHERE status IN (?, ?) GROUP BY severity',
                 (STATUS_ACTIVE, STATUS_ACKNOWLEDGED))
    return {severity: count for severity, count in rows}


# --------------------------------------------------------------------------
# Aggregates for the charts
# --------------------------------------------------------------------------
SERIES_COLUMNS = ('bucket_ts', 'temp_avg', 'temp_min', 'temp_max', 'temp_b_avg',
                  'ambient_avg', 'humidity_avg', 'current_avg', 'rpm_avg',
                  'door_open', 'compressor_on', 'fan_on', 'samples')


def series(hours=24, points=360):
    """Bucketed history for every chart, in one pass.

    Averaging into roughly ``points`` buckets keeps a seven-day view as cheap to
    draw as an hourly one - the alternative is pulling 120 000 rows into the GUI
    and throwing almost all of them away.
    """
    seconds = max(1, int(hours * 3600))
    bucket = max(1, seconds // max(1, points))
    rows = _read('''
        SELECT MIN(ts),
               AVG(temperature), MIN(temperature), MAX(temperature),
               AVG(temperature_b), AVG(ambient), AVG(humidity),
               AVG(compressor_current), AVG(fan_rpm),
               AVG(CASE WHEN door_state = 'OPEN' THEN 1.0 ELSE 0.0 END),
               AVG(CASE WHEN compressor = 'ON' THEN 1.0 ELSE 0.0 END),
               AVG(CASE WHEN fan = 'ON' THEN 1.0 ELSE 0.0 END),
               COUNT(*)
        FROM readings
        WHERE ts >= ?
        GROUP BY CAST(strftime('%s', ts) / ? AS INTEGER)
        ORDER BY MIN(ts)
    ''', (_since(hours), bucket))
    return [dict(zip(SERIES_COLUMNS, row)) for row in rows]


def stats_since(hours=24, target_min=2.0, target_max=8.0, sample_seconds=5.0):
    """Headline numbers for the history page."""
    since = _since(hours)
    count, t_min, t_max, t_avg = _read(
        'SELECT COUNT(*), MIN(temperature), MAX(temperature), AVG(temperature) '
        'FROM readings WHERE ts >= ?', (since,))[0]

    outside = _read('SELECT COUNT(*) FROM readings WHERE ts >= ? AND '
                    'temperature IS NOT NULL AND (temperature < ? OR '
                    'temperature > ?)', (since, target_min, target_max))[0][0]

    # 'ALARM' is the pre-rename spelling of CRITICAL; count both.
    criticals = _read("SELECT COUNT(*) FROM events WHERE ts >= ? AND level IN "
                      "('CRITICAL', 'ALARM')", (since,))[0][0]
    warnings = _read("SELECT COUNT(*) FROM events WHERE ts >= ? AND "
                     "level = 'WARNING'", (since,))[0][0]
    door_events = _read("SELECT COUNT(*) FROM events WHERE ts >= ? AND "
                        "code = 'DOOR_OPEN'", (since,))[0][0]

    return {
        'samples': count or 0,
        'temp_min': t_min,
        'temp_max': t_max,
        'temp_avg': t_avg,
        'excursion_minutes': round(outside * sample_seconds / 60.0, 1),
        'criticals': criticals,
        'warnings': warnings,
        'door_events': door_events,
    }


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def export_readings_csv(path, limit=5000):
    """Write the newest readings to CSV; returns how many rows were written."""
    rows = recent_readings(limit)
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['timestamp'] + READING_NAMES)
        writer.writerows(reversed(rows))  # oldest first reads better in a report
    return len(rows)


def export_incidents_csv(path, hours=24 * 7):
    rows = incidents(hours=hours, limit=5000)
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(INCIDENT_COLUMNS))
        writer.writeheader()
        writer.writerows(reversed(rows))
    return len(rows)


if __name__ == '__main__':
    init_db()
    print('database ready at', DB_FILE)
    print('reading columns:', ', '.join(READING_NAMES))
