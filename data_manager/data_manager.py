"""Cold Chain data manager - the brain of the system.

Responsibilities:

1. Subscribe to every sensor topic and track when each device was last heard
   from, so silence is detected rather than mistaken for stability.
2. Evaluate the storage rules once per second. Some are instantaneous
   (temperature outside 0-10 C), most are time based - a door open too long, an
   excursion that has lasted, probes that have disagreed for a while, a relay
   whose feedback has contradicted its command. Those are the reason this
   component holds state instead of reacting message by message.
3. Drive the actuators: compressor with hysteresis, circulation fan, siren.
4. Maintain incidents. An event says something happened; an incident tracks a
   condition from the moment it starts, through acknowledgement, to the moment
   it clears.
5. Persist readings, events and incidents to SQLite, and publish a consolidated
   status snapshot for the GUI.

Threading: paho delivers messages on its own network thread. That thread only
mutates state under ``self.lock`` and appends to a journal; every database write
and every outbound publish happens on the manager's own loop, so a slow disk can
never stall message dispatch.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collections
import threading
import time
import traceback
from datetime import datetime

from config import devices as registry
from config import mqtt_init as cfg
from config.mqtt_client import MqttClient, parse_json
from database import db

MODE_MONITORING = 'MONITORING'
MODE_MAINTENANCE = 'MAINTENANCE'

SENSOR_ONLINE = 'ONLINE'
SENSOR_WAITING = 'WAITING'
SENSOR_OFFLINE = 'OFFLINE'

ACTUATOR_REFRESH_SECONDS = 15  # re-send commands so late relays catch up

# Which device each inbound topic belongs to, for liveness tracking.
TOPIC_DEVICE = {
    cfg.TOPIC_TEMP: 'temp',
    cfg.TOPIC_TEMP_B: 'temp_b',
    cfg.TOPIC_AMBIENT: 'ambient',
    cfg.TOPIC_DOOR: 'door',
    cfg.TOPIC_POWER: 'power',
    cfg.TOPIC_BADGE: 'badge',
    cfg.TOPIC_CURRENT: 'current',
    cfg.TOPIC_FAN_RPM: 'fan_rpm',
    cfg.TOPIC_COMPRESSOR_STS: 'compressor',
    cfg.TOPIC_FAN_STS: 'fan',
    cfg.TOPIC_SIREN_STS: 'siren',
}

# Which device an alert code should be attributed to on the device page.
CODE_DEVICE = {
    'TEMP_RANGE': 'temp', 'TEMP_APPROACHING': 'temp', 'TEMP_EXCURSION': 'temp',
    'HUM_RANGE': 'temp', 'SENSOR_OFFLINE': 'temp',
    'PROBE_MISMATCH': 'temp_b', 'PROBE_B_OFFLINE': 'temp_b',
    'ROOM_HOT': 'ambient',
    'DOOR_OPEN': 'door', 'UNAUTHORISED_ACCESS': 'badge',
    'POWER_BATTERY': 'power', 'BATTERY_LOW': 'power',
    'COMPRESSOR_NO_CURRENT': 'current', 'COMPRESSOR_STUCK_ON': 'current',
    'COMPRESSOR_OVERLOAD': 'current',
    'FAN_STALLED': 'fan_rpm', 'FAN_STUCK_ON': 'fan_rpm',
    'FAN_DEGRADED': 'fan_rpm',
    'DEVICE_STALE': None, 'MQTT_DOWN': None,
}


def stamp():
    return datetime.now().strftime('%H:%M:%S')


def _number(payload, key, valid_range, default=None):
    """Pull a numeric field out of a payload, rejecting anything implausible.

    A sensor that reports 1e9 degrees has malfunctioned; treating that as a real
    measurement would raise a temperature alarm instead of a sensor fault.
    """
    try:
        value = float(payload[key])
    except (KeyError, TypeError, ValueError):
        return default
    low, high = valid_range
    if value != value or not (low <= value <= high):   # NaN or out of range
        return default
    return value


class ColdChainManager:

    def __init__(self):
        self.lock = threading.Lock()

        # -- sensor state ------------------------------------------------
        self.temperature = None
        self.humidity = None
        self.last_temp_time = None
        self.temperature_b = None
        self.last_temp_b_time = None
        self.ambient = None
        self.last_ambient_time = None
        self.door_open = False
        self.door_since = None
        self.power_source = 'MAINS'
        self.battery = 100.0
        self.battery_since = None
        self.compressor_current = None
        self.fan_rpm = None

        # -- access control ----------------------------------------------
        self.last_badge = None      # (operator_id, name, scanned_at)
        self.door_operator = None   # who the current opening is attributed to

        # -- derived state -----------------------------------------------
        self.excursion_since = None
        self.probe_mismatch_since = None
        self.mode = MODE_MONITORING
        self.mode_since = None
        self.mode_operator = None
        self.overall_level = cfg.LEVEL_INFO
        self.diagnosis = ''

        # -- actuators ---------------------------------------------------
        self.compressor = 'OFF'
        self.fan = 'OFF'
        self.siren = 'OFF'
        self.compressor_since = 0.0
        self.fan_since = 0.0
        self._last_actuator_push = 0.0

        # -- liveness ----------------------------------------------------
        self.device_seen = {}        # device_id -> monotonic timestamp
        self.device_health = {}      # device_id -> health constant
        self.simulated_faults = {}   # device_id -> [fault_id, ...]

        # -- alerts ------------------------------------------------------
        self.active_alerts = {}      # code -> level, one report per transition
        self._journal = collections.deque()   # work for the manager thread

        self._last_db_write = 0.0
        self._started_at = time.time()
        self._connected_since = None
        self._disconnected_since = time.time()
        self._running = True

        self.mqtt = MqttClient('manager', on_connect=self._on_connect,
                               on_disconnect=self._on_disconnect,
                               on_message=self._on_message)

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    def _on_connect(self):
        with self.lock:
            self._connected_since = time.time()
            self._disconnected_since = None
        print('%s  manager | broker connected, subscriptions active' % stamp())

    def _on_disconnect(self):
        with self.lock:
            self._connected_since = None
            if self._disconnected_since is None:
                self._disconnected_since = time.time()
        print('%s  manager | broker connection lost' % stamp())

    def _on_message(self, topic, payload):
        """Network thread. Mutates state under the lock; never touches the disk."""
        try:
            with self.lock:
                device_id = TOPIC_DEVICE.get(topic)
                if device_id:
                    self.device_seen[device_id] = time.time()

                if topic == cfg.TOPIC_TEMP:
                    self._handle_temp(payload)
                elif topic == cfg.TOPIC_TEMP_B:
                    self._handle_temp_b(payload)
                elif topic == cfg.TOPIC_AMBIENT:
                    self._handle_ambient(payload)
                elif topic == cfg.TOPIC_DOOR:
                    self._handle_door(payload)
                elif topic == cfg.TOPIC_POWER:
                    self._handle_power(payload)
                elif topic == cfg.TOPIC_BADGE:
                    self._handle_badge(payload)
                elif topic == cfg.TOPIC_CURRENT:
                    self._handle_current(payload)
                elif topic == cfg.TOPIC_FAN_RPM:
                    self._handle_fan_rpm(payload)
                elif topic == cfg.TOPIC_MODE_CMD:
                    self._handle_mode(payload)
                elif topic.startswith(cfg.TOPIC_SIM_STS):
                    self._handle_sim_status(payload)
                elif topic == cfg.TOPIC_INCIDENT_CMD:
                    self._handle_incident_command(payload)
        except Exception:
            # One malformed message must never take the manager down.
            print('%s  manager | error handling %s:\n%s'
                  % (stamp(), topic, traceback.format_exc()))

    # ------------------------------------------------------------------
    # Inbound message handlers (all run under the lock)
    # ------------------------------------------------------------------
    def _handle_temp(self, payload):
        data = parse_json(payload)
        if not data:
            print('%s  manager | malformed temperature payload: %r' % (stamp(), payload))
            return
        temperature = _number(data, 'temperature', cfg.VALID_TEMP_RANGE)
        if temperature is None:
            print('%s  manager | implausible temperature ignored: %r' % (stamp(), payload))
            return
        self.temperature = temperature
        # Humidity is optional; keep the previous value rather than inventing 0.
        humidity = _number(data, 'humidity', cfg.VALID_HUM_RANGE)
        if humidity is not None:
            self.humidity = humidity
        self.last_temp_time = time.time()

    def _handle_temp_b(self, payload):
        data = parse_json(payload, {})
        value = _number(data, 'temperature', cfg.VALID_TEMP_RANGE)
        if value is None:
            return
        self.temperature_b = value
        self.last_temp_b_time = time.time()

    def _handle_ambient(self, payload):
        data = parse_json(payload, {})
        value = _number(data, 'ambient', cfg.VALID_TEMP_RANGE)
        if value is None:
            return
        self.ambient = value
        self.last_ambient_time = time.time()

    def _handle_current(self, payload):
        value = _number(parse_json(payload, {}), 'current', cfg.VALID_CURRENT_RANGE)
        if value is not None:
            self.compressor_current = value

    def _handle_fan_rpm(self, payload):
        value = _number(parse_json(payload, {}), 'rpm', cfg.VALID_RPM_RANGE)
        if value is not None:
            self.fan_rpm = value

    def _handle_badge(self, payload):
        data = parse_json(payload, {})
        operator_id = data.get('operator_id')
        if not operator_id:
            return
        name = data.get('name') or operator_id
        authorised = bool(data.get('authorised', True))
        self.last_badge = (operator_id, name, time.time(), authorised)
        if authorised:
            self._journal_event(cfg.LEVEL_INFO, 'BADGE_SCAN',
                                'Badge scanned by %s (%s)' % (name, operator_id),
                                operator=name, device='badge')
        else:
            self._journal_event(cfg.LEVEL_WARNING, 'BADGE_REJECTED',
                                'Unrecognised badge %s presented at the door'
                                % operator_id, device='badge')

    def _handle_door(self, payload):
        data = parse_json(payload, {})
        is_open = str(data.get('state', '')).upper() == 'OPEN'
        if is_open and not self.door_open:
            self.door_since = time.time()
            self.door_operator = self._attribute_door()
        elif not is_open:
            self.door_since = None
            self.door_operator = None
        self.door_open = is_open

    def _attribute_door(self):
        """Name whoever scanned a valid badge recently enough to own this opening."""
        if self.last_badge is None:
            return cfg.UNKNOWN_OPERATOR
        _operator_id, name, scanned_at, authorised = self.last_badge
        if not authorised:
            return cfg.UNKNOWN_OPERATOR
        if time.time() - scanned_at > cfg.BADGE_VALID_SECONDS:
            return cfg.UNKNOWN_OPERATOR
        return name

    def _handle_power(self, payload):
        data = parse_json(payload, {})
        source = str(data.get('source', 'MAINS')).upper()
        if source not in ('MAINS', 'BATTERY'):
            return
        if source == 'BATTERY' and self.power_source != 'BATTERY':
            self.battery_since = time.time()
        elif source != 'BATTERY':
            self.battery_since = None
        self.power_source = source
        battery = _number(data, 'battery', cfg.VALID_BATTERY_RANGE)
        if battery is not None:
            self.battery = battery

    def _handle_mode(self, payload):
        data = parse_json(payload)
        if data:
            mode = str(data.get('mode', '')).upper()
            operator = data.get('operator') or cfg.DEFAULT_OPERATOR
        else:
            mode = payload.strip().upper()
            operator = cfg.DEFAULT_OPERATOR
        if mode not in (MODE_MONITORING, MODE_MAINTENANCE) or mode == self.mode:
            return
        self.mode = mode
        self.mode_since = time.time() if mode == MODE_MAINTENANCE else None
        self.mode_operator = operator if mode == MODE_MAINTENANCE else None
        self._journal_event(cfg.LEVEL_INFO, 'MODE',
                            'System mode changed to %s by %s' % (mode, operator),
                            operator=operator)

    def _handle_sim_status(self, payload):
        """Devices announce which faults they currently have armed."""
        data = parse_json(payload, {})
        device_id = data.get('device')
        if not device_id:
            return
        faults = data.get('faults') or []
        if faults:
            self.simulated_faults[device_id] = list(faults)
        else:
            self.simulated_faults.pop(device_id, None)

    def _handle_incident_command(self, payload):
        data = parse_json(payload, {})
        action = str(data.get('action', '')).lower()
        incident_id = data.get('id')
        operator = data.get('operator') or cfg.DEFAULT_OPERATOR
        if action in ('acknowledge', 'resolve') and incident_id is not None:
            self._journal.append(('incident_cmd', (action, incident_id, operator)))

    # ------------------------------------------------------------------
    # Alert bookkeeping
    # ------------------------------------------------------------------
    def _is_simulated(self, device_id):
        return bool(device_id and self.simulated_faults.get(device_id))

    def _raise_alert(self, code, level, message, operator=None):
        """Report a condition. Only writes when the level for this code changes."""
        if self.active_alerts.get(code) == level:
            return
        self.active_alerts[code] = level
        device_id = CODE_DEVICE.get(code)
        self._journal_event(level, code, message, operator, device_id)
        if level != cfg.LEVEL_INFO:
            self._journal.append(('incident_open', {
                'code': code, 'severity': level, 'device': device_id,
                'message': message, 'root_cause': self.diagnosis or None,
                'simulated': self._is_simulated(device_id),
            }))

    def _clear_alert(self, code, message, operator=None):
        if code not in self.active_alerts:
            return
        del self.active_alerts[code]
        self._journal_event(cfg.LEVEL_INFO, code + '_CLEARED', message, operator,
                            CODE_DEVICE.get(code))
        self._journal.append(('incident_close', code))

    def _journal_event(self, level, code, message, operator=None, device=None):
        """Queue an event. The manager loop does the disk and network work."""
        self._journal.append(('event', {
            'level': level, 'code': code, 'message': message,
            'operator': operator, 'device': device,
            'simulated': self._is_simulated(device),
            'ts': db.now_string(),
        }))

    def _flush_journal(self):
        """Run queued database writes and publishes on the manager's own thread."""
        while True:
            with self.lock:
                if not self._journal:
                    return
                kind, payload = self._journal.popleft()
            try:
                if kind == 'event':
                    self._write_event(payload)
                elif kind == 'incident_open':
                    db.open_incident(**payload)
                elif kind == 'incident_close':
                    db.close_incident(payload)
                elif kind == 'incident_cmd':
                    action, incident_id, operator = payload
                    if action == 'acknowledge':
                        db.acknowledge_incident(incident_id, operator)
                    else:
                        db.resolve_incident(incident_id, operator)
                    print('%s  manager | incident %s %sd by %s'
                          % (stamp(), incident_id, action, operator))
            except Exception:
                print('%s  manager | journal entry failed (%s):\n%s'
                      % (stamp(), kind, traceback.format_exc()))

    def _write_event(self, record):
        suffix = ('  [%s]' % record['operator']) if record['operator'] else ''
        flag = '  (SIMULATED)' if record['simulated'] else ''
        print('%s  manager | %-8s %-24s %s%s%s'
              % (stamp(), record['level'], record['code'], record['message'],
                 suffix, flag))
        db.insert_event(record['level'], record['code'], record['message'],
                        record['operator'], record['device'], record['simulated'])
        self.mqtt.publish_json(cfg.TOPIC_ALERT, record)

    # ------------------------------------------------------------------
    # Rule evaluation
    # ------------------------------------------------------------------
    def evaluate(self):
        now = time.time()
        with self.lock:
            sensor_state = self._check_sensor(now)

            if sensor_state == SENSOR_ONLINE:
                self._check_temperature(now)
                self._check_excursion(now)
                self._check_humidity()
            # SENSOR_WAITING contributes nothing: the system has only just
            # started and has not had a chance to hear from the sensor yet, and
            # SENSOR_OFFLINE has already raised its own alert.

            self._check_probe_agreement(now)
            self._check_ambient(now)
            self._check_door(now)
            self._check_power(now)
            self._check_compressor_current(now)
            self._check_fan_rpm(now)
            self._check_connectivity(now)
            self._check_device_liveness(now)

            # The unit's severity is simply the worst condition still active.
            # Deriving it from the alert set rather than from what each check
            # happened to return this tick means a condition that cannot be
            # re-tested right now - a compressor fault while the compressor is
            # off in its duty cycle - keeps the unit escalated until it clears.
            self.overall_level = cfg.worst(cfg.LEVEL_INFO,
                                           *self.active_alerts.values())
            if self.mode == MODE_MAINTENANCE:
                # Servicing the unit is expected to break the rules. Conditions
                # are still evaluated and logged, but the unit is not escalated.
                self.overall_level = cfg.LEVEL_INFO

            self.diagnosis = self._diagnose()
            self._update_device_health(now)
            self._drive_actuators(now)
            snapshot = self._snapshot(now, sensor_state)
            due_write = now - self._last_db_write >= cfg.DB_WRITE_INTERVAL_S
            if due_write:
                self._last_db_write = now
                reading = self._reading_row()

        self._flush_journal()
        self.mqtt.publish_json(cfg.TOPIC_STATUS, snapshot)
        if due_write:
            try:
                db.insert_reading(**reading)
            except Exception:
                print('%s  manager | could not store reading:\n%s'
                      % (stamp(), traceback.format_exc()))

    # -- individual rules ------------------------------------------------
    def _check_sensor(self, now):
        """Report whether the primary probe is alive, silent, or not heard yet."""
        if self.last_temp_time is None:
            if now - self._started_at <= cfg.SENSOR_TIMEOUT_SECONDS:
                return SENSOR_WAITING   # grace period after start-up
            self._raise_alert('SENSOR_OFFLINE', cfg.LEVEL_CRITICAL,
                              'No temperature data received since start-up')
            return SENSOR_OFFLINE

        silent_for = now - self.last_temp_time
        if silent_for > cfg.SENSOR_TIMEOUT_SECONDS:
            self._raise_alert('SENSOR_OFFLINE', cfg.LEVEL_CRITICAL,
                              'Temperature sensor silent for %d s' % int(silent_for))
            return SENSOR_OFFLINE

        self._clear_alert('SENSOR_OFFLINE', 'Temperature sensor is reporting again')
        return SENSOR_ONLINE

    def _check_temperature(self, now):
        temp = self.temperature
        if temp is None:
            return cfg.LEVEL_INFO

        if temp < cfg.TEMP_ALARM_MIN or temp > cfg.TEMP_ALARM_MAX:
            self._raise_alert('TEMP_RANGE', cfg.LEVEL_CRITICAL,
                              'Temperature %.1f C is outside the hard limit %.0f-%.0f C'
                              % (temp, cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX))
            return cfg.LEVEL_CRITICAL

        if temp < cfg.TEMP_TARGET_MIN or temp > cfg.TEMP_TARGET_MAX:
            self._raise_alert('TEMP_RANGE', cfg.LEVEL_WARNING,
                              'Temperature %.1f C left the %.0f-%.0f C storage band'
                              % (temp, cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX))
            self._clear_alert('TEMP_APPROACHING', 'Superseded by a range warning')
            return cfg.LEVEL_WARNING

        self._clear_alert('TEMP_RANGE',
                          'Temperature back inside the storage band (%.1f C)' % temp)

        # Inside the band, but close enough to the edge to be worth flagging.
        margin = cfg.TEMP_APPROACH_MARGIN
        if temp <= cfg.TEMP_TARGET_MIN + margin or temp >= cfg.TEMP_TARGET_MAX - margin:
            self._raise_alert('TEMP_APPROACHING', cfg.LEVEL_WARNING,
                              'Temperature %.1f C is approaching the edge of the '
                              'storage band' % temp)
            return cfg.LEVEL_WARNING
        self._clear_alert('TEMP_APPROACHING',
                          'Temperature comfortably inside the band (%.1f C)' % temp)
        return cfg.LEVEL_INFO

    def _check_excursion(self, now):
        """A brief excursion is tolerable; a sustained one spoils the stock."""
        temp = self.temperature
        if temp is None:
            return cfg.LEVEL_INFO

        if cfg.TEMP_TARGET_MIN <= temp <= cfg.TEMP_TARGET_MAX:
            if self.excursion_since is not None:
                duration = int(now - self.excursion_since)
                self.excursion_since = None
                self._clear_alert('TEMP_EXCURSION',
                                  'Excursion ended after %d s' % duration)
            return cfg.LEVEL_INFO

        if self.excursion_since is None:
            self.excursion_since = now
            return cfg.LEVEL_INFO

        duration = now - self.excursion_since
        if duration >= cfg.EXCURSION_ALARM_SECONDS:
            cause = self._diagnose()
            message = ('Temperature outside %.0f-%.0f C for %d s - stock at risk'
                       % (cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX, int(duration)))
            if cause:
                message += '; ' + cause
            self._raise_alert('TEMP_EXCURSION', cfg.LEVEL_CRITICAL, message)
            return cfg.LEVEL_CRITICAL
        return cfg.LEVEL_INFO

    def _check_humidity(self):
        hum = self.humidity
        if hum is None:
            return cfg.LEVEL_INFO
        if hum > cfg.HUM_ALARM_MAX:
            self._raise_alert('HUM_RANGE', cfg.LEVEL_CRITICAL,
                              'Humidity %.0f %% - condensation risk' % hum)
            return cfg.LEVEL_CRITICAL
        if hum < cfg.HUM_TARGET_MIN or hum > cfg.HUM_TARGET_MAX:
            self._raise_alert('HUM_RANGE', cfg.LEVEL_WARNING,
                              'Humidity %.0f %% is outside %.0f-%.0f %%'
                              % (hum, cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX))
            return cfg.LEVEL_WARNING
        self._clear_alert('HUM_RANGE', 'Humidity back to normal (%.0f %%)' % hum)
        return cfg.LEVEL_INFO

    def _check_probe_agreement(self, now):
        """Two probes that disagree mean one is lying, and we cannot tell which."""
        if self.last_temp_b_time is None:
            return cfg.LEVEL_INFO

        silent_for = now - self.last_temp_b_time
        if silent_for > cfg.PROBE_B_TIMEOUT_SECONDS:
            # Losing redundancy is not an emergency, but the unit is now running
            # on a single unverified probe and that must be visible.
            self._raise_alert('PROBE_B_OFFLINE', cfg.LEVEL_WARNING,
                              'Probe B silent for %d s - redundancy lost'
                              % int(silent_for))
            self.probe_mismatch_since = None
            return cfg.LEVEL_WARNING
        self._clear_alert('PROBE_B_OFFLINE', 'Probe B is reporting again')

        if self.temperature is None or self.temperature_b is None:
            return cfg.LEVEL_INFO

        delta = abs(self.temperature - self.temperature_b)
        if delta <= cfg.PROBE_DISAGREE_C:
            if self.probe_mismatch_since is not None:
                self.probe_mismatch_since = None
                self._clear_alert('PROBE_MISMATCH',
                                  'Probes agree again (%.1f C apart)' % delta)
            return cfg.LEVEL_INFO

        if self.probe_mismatch_since is None:
            self.probe_mismatch_since = now
            return cfg.LEVEL_INFO

        if now - self.probe_mismatch_since >= cfg.PROBE_DISAGREE_SECONDS:
            self._raise_alert('PROBE_MISMATCH', cfg.LEVEL_CRITICAL,
                              'Probes disagree by %.1f C (A %.1f, B %.1f) - '
                              'readings cannot be trusted'
                              % (delta, self.temperature, self.temperature_b))
            return cfg.LEVEL_CRITICAL
        return cfg.LEVEL_INFO

    def _check_ambient(self, now):
        if self.last_ambient_time is None:
            return cfg.LEVEL_INFO
        if now - self.last_ambient_time > cfg.AMBIENT_TIMEOUT_SECONDS:
            self._clear_alert('ROOM_HOT', 'Ambient sensor stopped reporting')
            return cfg.LEVEL_INFO

        if self.ambient is not None and self.ambient >= cfg.AMBIENT_WARNING_C:
            self._raise_alert('ROOM_HOT', cfg.LEVEL_WARNING,
                              'Storeroom at %.1f C - check the building cooling'
                              % self.ambient)
            return cfg.LEVEL_WARNING
        self._clear_alert('ROOM_HOT', 'Storeroom temperature back to normal')
        return cfg.LEVEL_INFO

    def _check_compressor_current(self, now):
        """Compare what was commanded against what the motor actually drew."""
        if self.compressor_current is None:
            return cfg.LEVEL_INFO

        current = self.compressor_current
        settled = (now - self.compressor_since) >= cfg.ACTUATOR_FAULT_SECONDS
        drawing = current >= cfg.CURRENT_RUNNING_MIN_A

        if not settled:
            # A motor draws several times its running current for a second or
            # two on start-up and coasts down slowly afterwards; reacting to
            # either would report a fault on every compressor cycle.
            return cfg.LEVEL_INFO

        if current > cfg.CURRENT_OVERLOAD_A:
            self._raise_alert('COMPRESSOR_OVERLOAD', cfg.LEVEL_CRITICAL,
                              'Compressor drawing %.1f A - above the %.1f A limit'
                              % (current, cfg.CURRENT_OVERLOAD_A))
            return cfg.LEVEL_CRITICAL
        self._clear_alert('COMPRESSOR_OVERLOAD', 'Compressor current back to normal')

        # Each fault is only judged while the command that could disprove it is
        # in force. A dead compressor draws nothing whether it was told to run
        # or not, so clearing the fault just because the duty cycle turned it
        # off would reopen and close the same incident every few minutes.
        if self.compressor == 'ON':
            if not drawing:
                self._raise_alert('COMPRESSOR_NO_CURRENT', cfg.LEVEL_CRITICAL,
                                  'Compressor commanded ON but drawing %.2f A - '
                                  'relay or motor failure' % current)
                return cfg.LEVEL_CRITICAL
            self._clear_alert('COMPRESSOR_NO_CURRENT',
                              'Compressor is drawing current again')
        else:
            if drawing:
                self._raise_alert('COMPRESSOR_STUCK_ON', cfg.LEVEL_CRITICAL,
                                  'Compressor commanded OFF but drawing %.2f A - '
                                  'contacts welded closed' % current)
                return cfg.LEVEL_CRITICAL
            self._clear_alert('COMPRESSOR_STUCK_ON',
                              'Compressor has stopped drawing')
        return cfg.LEVEL_INFO

    def _check_fan_rpm(self, now):
        """A stalled fan is silent: the average stays fine while the air stops."""
        if self.fan_rpm is None:
            return cfg.LEVEL_INFO

        rpm = self.fan_rpm
        settled = (now - self.fan_since) >= cfg.ACTUATOR_FAULT_SECONDS
        turning = rpm >= cfg.FAN_RPM_MIN
        if not settled:
            return cfg.LEVEL_INFO

        # As with the compressor: a seized fan reads zero whether or not it was
        # asked to spin, so its faults are only judged - and only cleared -
        # while the relevant command is in force.
        if self.fan == 'ON':
            if not turning:
                self._raise_alert('FAN_STALLED', cfg.LEVEL_CRITICAL,
                                  'Fan commanded ON but reading %d rpm - '
                                  'blocked or seized' % int(rpm))
                return cfg.LEVEL_CRITICAL
            self._clear_alert('FAN_STALLED', 'Fan is turning again')

            if rpm < cfg.FAN_RPM_DEGRADED:
                # Still circulating, but not well. Service it before it fails.
                self._raise_alert('FAN_DEGRADED', cfg.LEVEL_WARNING,
                                  'Fan at %d rpm, below the %d rpm minimum - '
                                  'bearing wear' % (int(rpm), cfg.FAN_RPM_DEGRADED))
                return cfg.LEVEL_WARNING
            self._clear_alert('FAN_DEGRADED', 'Fan speed back to normal')
            return cfg.LEVEL_INFO

        if turning:
            self._raise_alert('FAN_STUCK_ON', cfg.LEVEL_WARNING,
                              'Fan commanded OFF but still turning at %d rpm'
                              % int(rpm))
            return cfg.LEVEL_WARNING
        self._clear_alert('FAN_STUCK_ON', 'Fan has stopped')
        return cfg.LEVEL_INFO

    def _check_door(self, now):
        if not self.door_open or self.door_since is None:
            self._clear_alert('DOOR_OPEN', 'Door closed')
            self._clear_alert('UNAUTHORISED_ACCESS', 'Door closed')
            return cfg.LEVEL_INFO

        operator = self.door_operator or cfg.UNKNOWN_OPERATOR
        level = cfg.LEVEL_INFO

        # A reader cannot physically stop anyone, but an unbadged opening is
        # exactly the entry an auditor looks for.
        if operator == cfg.UNKNOWN_OPERATOR:
            self._raise_alert('UNAUTHORISED_ACCESS', cfg.LEVEL_WARNING,
                              'Door opened with no valid badge scan')
            level = cfg.LEVEL_WARNING

        open_for = now - self.door_since
        if open_for >= cfg.DOOR_ALARM_SECONDS:
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_CRITICAL,
                              'Door has been open for %d s' % int(open_for),
                              operator=operator)
            return cfg.LEVEL_CRITICAL
        if open_for >= cfg.DOOR_WARNING_SECONDS:
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_WARNING,
                              'Door open for %d s' % int(open_for),
                              operator=operator)
            return cfg.worst(level, cfg.LEVEL_WARNING)
        return level

    def _check_power(self, now):
        level = cfg.LEVEL_INFO

        if self.power_source == 'BATTERY' and self.battery <= cfg.BATTERY_ALARM_PERCENT:
            self._raise_alert('BATTERY_LOW', cfg.LEVEL_CRITICAL,
                              'Backup battery at %.0f %%' % self.battery)
            level = cfg.LEVEL_CRITICAL
        else:
            self._clear_alert('BATTERY_LOW', 'Backup battery recovered')

        if self.power_source == 'BATTERY' and self.battery_since is not None:
            on_battery_for = now - self.battery_since
            if on_battery_for >= cfg.BATTERY_WARNING_SECONDS:
                self._raise_alert('POWER_BATTERY', cfg.LEVEL_WARNING,
                                  'Running on backup battery for %d s'
                                  % int(on_battery_for))
                level = cfg.worst(level, cfg.LEVEL_WARNING)
        else:
            self._clear_alert('POWER_BATTERY', 'Mains power restored')

        return level

    def _check_connectivity(self, now):
        """The manager's own link to the broker."""
        if self._disconnected_since is None:
            self._clear_alert('MQTT_DOWN', 'Broker connection restored')
            return cfg.LEVEL_INFO
        down_for = now - self._disconnected_since
        if down_for >= cfg.MQTT_DOWN_SECONDS:
            self._raise_alert('MQTT_DOWN', cfg.LEVEL_CRITICAL,
                              'No broker connection for %d s - telemetry is stale'
                              % int(down_for))
            return cfg.LEVEL_CRITICAL
        return cfg.LEVEL_INFO

    def _check_device_liveness(self, now):
        """Any scheduled publisher that has gone quiet, beyond the primary probe."""
        stale = []
        for device in registry.telemetry_devices():
            if device.id in ('temp', 'temp_b'):
                continue     # these have their own, more specific rules
            seen = self.device_seen.get(device.id)
            if seen is None:
                continue     # never heard from; start-up, not a failure
            if now - seen > device.stale_after:
                stale.append((device, now - seen))

        if not stale:
            self._clear_alert('DEVICE_STALE', 'All devices are reporting again')
            return cfg.LEVEL_INFO

        summary = ', '.join('%s (%ds)' % (d.label, int(age)) for d, age in stale)
        level = cfg.LEVEL_CRITICAL if len(stale) > 1 else cfg.LEVEL_WARNING
        self._raise_alert('DEVICE_STALE', level,
                          'No telemetry from %s' % summary)
        return level

    # ------------------------------------------------------------------
    # Device health
    # ------------------------------------------------------------------
    def _update_device_health(self, now):
        critical_devices = set()
        warning_devices = set()
        for code, level in self.active_alerts.items():
            device_id = CODE_DEVICE.get(code)
            if not device_id:
                continue
            if level == cfg.LEVEL_CRITICAL:
                critical_devices.add(device_id)
            elif level == cfg.LEVEL_WARNING:
                warning_devices.add(device_id)

        for device in registry.DEVICES:
            seen = self.device_seen.get(device.id)
            if seen is None:
                health = registry.OFFLINE
            elif device.period_s > 0 and (now - seen) > device.stale_after:
                health = registry.OFFLINE
            elif device.id in critical_devices:
                health = registry.FAULT
            elif device.id in warning_devices or self.simulated_faults.get(device.id):
                health = registry.DEGRADED
            elif self.mode == MODE_MAINTENANCE:
                health = registry.MAINTENANCE
            else:
                health = registry.CONNECTED
            self.device_health[device.id] = health

    # ------------------------------------------------------------------
    # Root cause
    # ------------------------------------------------------------------
    def _diagnose(self):
        """Explain *why* the cabinet is warm, using the diagnostic sensors.

        Knowing the temperature is out of range is only half an alert. The
        ambient probe, the current clamp and the tachometer between them
        separate a facility problem from a unit problem from a door left open -
        three situations that need three different people to respond.
        """
        if self.temperature is None or self.temperature <= cfg.TEMP_TARGET_MAX:
            return ''
        if self.door_open:
            return 'the door is open'
        if self.ambient is not None and self.ambient >= cfg.AMBIENT_WARNING_C:
            return ('the storeroom is at %.0f C - this is a building cooling '
                    'problem, not a unit fault' % self.ambient)
        if self.compressor == 'ON':
            if (self.compressor_current is not None
                    and self.compressor_current < cfg.CURRENT_RUNNING_MIN_A):
                return 'the compressor is commanded on but is not running'
            if self.fan_rpm is not None and self.fan_rpm < cfg.FAN_RPM_MIN:
                return 'the compressor is running but the fan is not circulating'
            return 'the compressor is running but cannot keep up'
        return 'the compressor is off'

    # ------------------------------------------------------------------
    # Actuator control
    # ------------------------------------------------------------------
    def _drive_actuators(self, now):
        compressor = self.compressor
        temp = self.temperature

        if self.mode == MODE_MAINTENANCE:
            compressor = 'OFF'
        elif self.door_open:
            # Real units stop cooling with the door open so the coil does not ice up.
            compressor = 'OFF'
        elif temp is not None:
            if temp >= cfg.COMPRESSOR_ON_ABOVE:
                compressor = 'ON'
            elif temp <= cfg.COMPRESSOR_OFF_BELOW:
                compressor = 'OFF'
            # between the two thresholds the previous state is kept (hysteresis)

        fan = 'OFF'
        if self.mode != MODE_MAINTENANCE:
            if compressor == 'ON':
                fan = 'ON'
            elif self.humidity is not None and self.humidity > cfg.HUM_TARGET_MAX:
                fan = 'ON'

        siren = 'ON' if self.overall_level == cfg.LEVEL_CRITICAL else 'OFF'

        refresh = (now - self._last_actuator_push) >= ACTUATOR_REFRESH_SECONDS
        if refresh:
            self._last_actuator_push = now

        for topic, new_value, attr in (
                (cfg.TOPIC_COMPRESSOR_CMD, compressor, 'compressor'),
                (cfg.TOPIC_FAN_CMD, fan, 'fan'),
                (cfg.TOPIC_SIREN_CMD, siren, 'siren')):
            changed = new_value != getattr(self, attr)
            if changed:
                setattr(self, attr, new_value)
                # Restart the grace period: the feedback sensors may only
                # contradict a command once the hardware has had time to act.
                if attr == 'compressor':
                    self.compressor_since = now
                elif attr == 'fan':
                    self.fan_since = now
            if changed or refresh:
                self.mqtt.publish(topic, new_value)

    # ------------------------------------------------------------------
    # Outbound state
    # ------------------------------------------------------------------
    def _reading_row(self):
        return {
            'temperature': self.temperature,
            'temperature_b': self.temperature_b,
            'ambient': self.ambient,
            'humidity': self.humidity,
            'door_state': 'OPEN' if self.door_open else 'CLOSED',
            'operator': self.door_operator,
            'power_source': self.power_source,
            'battery_level': self.battery,
            'compressor': self.compressor,
            'compressor_current': self.compressor_current,
            'fan': self.fan,
            'fan_rpm': self.fan_rpm,
            'siren': self.siren,
            'alert_level': self.overall_level,
        }

    def _snapshot(self, now, sensor_state):
        door_seconds = int(now - self.door_since) if self.door_since else 0
        excursion_seconds = int(now - self.excursion_since) if self.excursion_since else 0
        probe_delta = None
        if self.temperature is not None and self.temperature_b is not None:
            probe_delta = round(abs(self.temperature - self.temperature_b), 2)

        ages = {}
        for device_id, seen in self.device_seen.items():
            ages[device_id] = round(now - seen, 1)

        counts = collections.Counter(self.device_health.values())
        severities = collections.Counter(
            level for level in self.active_alerts.values()
            if level != cfg.LEVEL_INFO)

        return {
            'ts': db.now_string(),
            'uptime_s': int(now - self._started_at),
            'temperature': self.temperature,
            'temperature_b': self.temperature_b,
            'probe_delta': probe_delta,
            'ambient': self.ambient,
            'humidity': self.humidity,
            'door': 'OPEN' if self.door_open else 'CLOSED',
            'door_seconds': door_seconds,
            'operator': self.door_operator,
            'power': self.power_source,
            'battery': self.battery,
            'compressor': self.compressor,
            'compressor_current': self.compressor_current,
            'fan': self.fan,
            'fan_rpm': self.fan_rpm,
            'siren': self.siren,
            'mode': self.mode,
            'mode_since': self.mode_since and db.now_string(),
            'mode_operator': self.mode_operator,
            'level': self.overall_level,
            'diagnosis': self.diagnosis,
            'excursion_seconds': excursion_seconds,
            'sensor_state': sensor_state,
            'sensor_online': sensor_state == SENSOR_ONLINE,
            'broker_connected': self._disconnected_since is None,
            'active_alerts': sorted(self.active_alerts.keys()),
            'alert_counts': dict(severities),
            'device_health': dict(self.device_health),
            'device_age_s': ages,
            'device_counts': dict(counts),
            'simulated_faults': {k: list(v) for k, v in self.simulated_faults.items()},
            'simulation_active': bool(self.simulated_faults),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run(self):
        db.init_db()
        print('%s  manager | database ready: %s' % (stamp(), db.DB_FILE))

        # Any incident left open by a previous run is stale; the conditions will
        # re-raise themselves within a second if they are still true.
        for incident in db.active_incidents():
            db.close_incident(incident['code'])

        self.mqtt.subscribe(cfg.TOPIC_TEMP, cfg.TOPIC_TEMP_B, cfg.TOPIC_AMBIENT,
                            cfg.TOPIC_DOOR, cfg.TOPIC_POWER, cfg.TOPIC_BADGE,
                            cfg.TOPIC_CURRENT, cfg.TOPIC_FAN_RPM,
                            cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_FAN_STS,
                            cfg.TOPIC_SIREN_STS, cfg.TOPIC_MODE_CMD,
                            cfg.TOPIC_SIM_STS_WILDCARD, cfg.TOPIC_INCIDENT_CMD)
        self.mqtt.start()
        print('%s  manager | connecting to %s:%s'
              % (stamp(), cfg.BROKER_HOST, cfg.BROKER_PORT))

        last_summary = 0.0
        try:
            while self._running:
                try:
                    self.evaluate()
                except Exception:
                    # A rule bug must not kill the loop; log it and carry on.
                    print('%s  manager | evaluation failed:\n%s'
                          % (stamp(), traceback.format_exc()))
                if time.time() - last_summary >= 10:
                    last_summary = time.time()
                    self._print_summary()
                time.sleep(cfg.EVALUATE_INTERVAL_S)
        except KeyboardInterrupt:
            print('\n%s  manager | stopping' % stamp())
        finally:
            self.shutdown()

    def _print_summary(self):
        def number(value, fmt, suffix=''):
            return '--' if value is None else (fmt % value) + suffix

        offline = [k for k, v in self.device_health.items() if v == registry.OFFLINE]
        print('%s  manager | %-8s A=%-7s B=%-7s amb=%-6s door=%-6s '
              'comp=%-3s %-6s fan=%-3s %-8s siren=%-3s devices=%d/%d'
              % (stamp(), self.overall_level,
                 number(self.temperature, '%.1f', 'C'),
                 number(self.temperature_b, '%.1f', 'C'),
                 number(self.ambient, '%.1f', 'C'),
                 'OPEN' if self.door_open else 'CLOSED',
                 self.compressor, number(self.compressor_current, '%.2f', 'A'),
                 self.fan, number(self.fan_rpm, '%.0f', 'rpm'),
                 self.siren,
                 len(registry.DEVICES) - len(offline), len(registry.DEVICES)))
        if self.diagnosis:
            print('%s  manager | cause: %s' % (stamp(), self.diagnosis))

    def shutdown(self):
        self._running = False
        try:
            self._flush_journal()
        except Exception:
            pass
        # Leave the hardware in a safe, quiet state.
        self.mqtt.publish(cfg.TOPIC_SIREN_CMD, 'OFF')
        self.mqtt.publish(cfg.TOPIC_COMPRESSOR_CMD, 'OFF')
        self.mqtt.publish(cfg.TOPIC_FAN_CMD, 'OFF')
        time.sleep(0.3)
        self.mqtt.stop()
        print('%s  manager | stopped' % stamp())


if __name__ == '__main__':
    ColdChainManager().run()
