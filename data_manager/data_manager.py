"""Cold Chain data manager - the brain of the system.

Responsibilities:

1. Subscribe to every sensor topic on the broker.
2. Evaluate the storage rules once per second. Some rules are instantaneous
   (temperature outside 0-10 C), others are time based (door open for too long,
   temperature outside the 2-8 C band for longer than the tolerated window,
   running on battery). The time based rules are the reason this component
   keeps state instead of reacting message by message.
3. Drive the actuators: compressor with hysteresis, circulation fan, siren.
4. Persist every reading and every alert transition to SQLite.
5. Publish a consolidated status snapshot and alert messages for the GUI.

Alerts are de-duplicated: an event row and an MQTT alert are produced when a
condition *starts* and when it *clears*, not on every evaluation tick.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
from datetime import datetime

from config import mqtt_init as cfg
from config.mqtt_client import MqttClient, parse_json
from database import db

MODE_MONITORING = 'MONITORING'
MODE_MAINTENANCE = 'MAINTENANCE'

SENSOR_ONLINE = 'ONLINE'
SENSOR_WAITING = 'WAITING'
SENSOR_OFFLINE = 'OFFLINE'

ACTUATOR_REFRESH_SECONDS = 15  # re-send commands so late relays catch up


def stamp():
    return datetime.now().strftime('%H:%M:%S')


class ColdChainManager:

    def __init__(self):
        self.lock = threading.Lock()

        # Sensor state
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

        # Access control
        self.last_badge = None      # (operator_id, name, scanned_at)
        self.door_operator = None   # who the current opening is attributed to

        # Derived state
        self.excursion_since = None
        self.probe_mismatch_since = None
        self.mode = MODE_MONITORING
        self.overall_level = cfg.LEVEL_INFO
        self.diagnosis = ''

        # Actuator state as commanded by this manager
        self.compressor = 'OFF'
        self.fan = 'OFF'
        self.siren = 'OFF'
        # When each actuator was last commanded, so a fault is only declared
        # after the hardware has had time to respond.
        self.compressor_since = 0.0
        self.fan_since = 0.0
        self._last_actuator_push = 0.0

        # code -> level, so a condition is reported once per transition
        self.active_alerts = {}

        self._last_db_write = 0.0
        self._started_at = time.time()
        self._running = True

        self.mqtt = MqttClient('manager', on_connect=self._on_connect,
                               on_message=self._on_message)

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    def _on_connect(self):
        print('%s  manager | subscribed to sensor topics' % stamp())

    def _on_message(self, topic, payload):
        """Runs on the paho network thread - only touches state under the lock."""
        with self.lock:
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

    def _handle_temp(self, payload):
        data = parse_json(payload)
        if not data:
            print('%s  manager | malformed temperature payload: %r' % (stamp(), payload))
            return
        try:
            self.temperature = float(data['temperature'])
            self.humidity = float(data.get('humidity', self.humidity or 0.0))
        except (KeyError, TypeError, ValueError):
            print('%s  manager | temperature payload missing fields: %r' % (stamp(), payload))
            return
        self.last_temp_time = time.time()

    def _handle_temp_b(self, payload):
        data = parse_json(payload, {})
        try:
            self.temperature_b = float(data['temperature'])
            self.last_temp_b_time = time.time()
        except (KeyError, TypeError, ValueError):
            print('%s  manager | malformed probe B payload: %r' % (stamp(), payload))

    def _handle_ambient(self, payload):
        data = parse_json(payload, {})
        try:
            self.ambient = float(data['ambient'])
            self.last_ambient_time = time.time()
        except (KeyError, TypeError, ValueError):
            print('%s  manager | malformed ambient payload: %r' % (stamp(), payload))

    def _handle_current(self, payload):
        data = parse_json(payload, {})
        try:
            self.compressor_current = float(data['current'])
        except (KeyError, TypeError, ValueError):
            pass

    def _handle_fan_rpm(self, payload):
        data = parse_json(payload, {})
        try:
            self.fan_rpm = float(data['rpm'])
        except (KeyError, TypeError, ValueError):
            pass

    def _handle_badge(self, payload):
        data = parse_json(payload, {})
        operator_id = data.get('operator_id')
        if not operator_id:
            return
        name = data.get('name') or operator_id
        self.last_badge = (operator_id, name, time.time())
        self._emit_event(cfg.LEVEL_INFO, 'BADGE_SCAN',
                         'Badge scanned by %s (%s)' % (name, operator_id),
                         operator=name)

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
        """Name whoever scanned a badge recently enough to own this opening."""
        if self.last_badge is None:
            return cfg.UNKNOWN_OPERATOR
        _operator_id, name, scanned_at = self.last_badge
        if time.time() - scanned_at > cfg.BADGE_VALID_SECONDS:
            return cfg.UNKNOWN_OPERATOR
        return name

    def _handle_power(self, payload):
        data = parse_json(payload, {})
        source = str(data.get('source', 'MAINS')).upper()
        if source == 'BATTERY' and self.power_source != 'BATTERY':
            self.battery_since = time.time()
        elif source != 'BATTERY':
            self.battery_since = None
        self.power_source = source
        try:
            self.battery = float(data.get('battery', self.battery))
        except (TypeError, ValueError):
            pass

    def _handle_mode(self, payload):
        mode = payload.strip().upper()
        if mode in (MODE_MONITORING, MODE_MAINTENANCE) and mode != self.mode:
            self.mode = mode
            self._emit_event(cfg.LEVEL_INFO, 'MODE',
                             'System mode changed to %s' % mode)

    # ------------------------------------------------------------------
    # Alert bookkeeping
    # ------------------------------------------------------------------
    def _raise_alert(self, code, level, message, operator=None):
        """Report a condition. Only writes when the level for this code changes."""
        if self.active_alerts.get(code) == level:
            return
        self.active_alerts[code] = level
        self._emit_event(level, code, message, operator)

    def _clear_alert(self, code, message, operator=None):
        if code not in self.active_alerts:
            return
        del self.active_alerts[code]
        self._emit_event(cfg.LEVEL_INFO, code + '_CLEARED', message, operator)

    def _emit_event(self, level, code, message, operator=None):
        suffix = ('  [%s]' % operator) if operator else ''
        print('%s  manager | %-7s %-22s %s%s'
              % (stamp(), level, code, message, suffix))
        db.insert_event(level, code, message, operator)
        self.mqtt.publish_json(cfg.TOPIC_ALERT, {
            'level': level,
            'code': code,
            'message': message,
            'operator': operator,
            'ts': db.now_string(),
        })

    # ------------------------------------------------------------------
    # Rule evaluation
    # ------------------------------------------------------------------
    def evaluate(self):
        now = time.time()
        with self.lock:
            levels = [cfg.LEVEL_INFO]
            sensor_state = self._check_sensor(now)

            if sensor_state == SENSOR_ONLINE:
                levels.append(self._check_temperature(now))
                levels.append(self._check_excursion(now))
                levels.append(self._check_humidity())
            elif sensor_state == SENSOR_OFFLINE:
                levels.append(cfg.LEVEL_ALARM)
            # SENSOR_WAITING contributes nothing: the system has only just
            # started and has not had a chance to hear from the sensor yet.

            levels.append(self._check_probe_agreement(now))
            levels.append(self._check_ambient(now))
            levels.append(self._check_door(now))
            levels.append(self._check_power(now))
            levels.append(self._check_compressor_current(now))
            levels.append(self._check_fan_rpm(now))

            self.overall_level = cfg.worst(*levels)
            if self.mode == MODE_MAINTENANCE:
                # Servicing the unit is expected to break the rules; keep logging
                # the conditions but do not escalate the unit to an alarm state.
                self.overall_level = cfg.LEVEL_INFO

            self.diagnosis = self._diagnose()
            self._drive_actuators(now)
            snapshot = self._snapshot(now, sensor_state)

        self.mqtt.publish_json(cfg.TOPIC_STATUS, snapshot)

        if now - self._last_db_write >= cfg.DB_WRITE_INTERVAL_S:
            self._last_db_write = now
            db.insert_reading(
                temperature=self.temperature,
                temperature_b=self.temperature_b,
                ambient=self.ambient,
                humidity=self.humidity,
                door_state='OPEN' if self.door_open else 'CLOSED',
                operator=self.door_operator,
                power_source=self.power_source,
                battery_level=self.battery,
                compressor=self.compressor,
                compressor_current=self.compressor_current,
                fan=self.fan,
                fan_rpm=self.fan_rpm,
                siren=self.siren,
                alert_level=self.overall_level,
            )

    def _check_sensor(self, now):
        """Report whether the sensor is alive, silent, or simply not heard from yet."""
        if self.last_temp_time is None:
            # Grace period after start-up: the emulators may not be running yet.
            if now - self._started_at <= cfg.SENSOR_TIMEOUT_SECONDS:
                return SENSOR_WAITING
            self._raise_alert('SENSOR_OFFLINE', cfg.LEVEL_ALARM,
                              'No temperature data received since start-up')
            return SENSOR_OFFLINE

        silent_for = now - self.last_temp_time
        if silent_for > cfg.SENSOR_TIMEOUT_SECONDS:
            self._raise_alert('SENSOR_OFFLINE', cfg.LEVEL_ALARM,
                              'Temperature sensor silent for %d s' % int(silent_for))
            return SENSOR_OFFLINE

        self._clear_alert('SENSOR_OFFLINE', 'Temperature sensor is reporting again')
        return SENSOR_ONLINE

    def _check_temperature(self, now):
        temp = self.temperature
        if temp is None:
            return cfg.LEVEL_INFO

        if temp < cfg.TEMP_ALARM_MIN or temp > cfg.TEMP_ALARM_MAX:
            self._raise_alert('TEMP_RANGE', cfg.LEVEL_ALARM,
                              'Temperature %.1f C is outside the hard limit %.0f-%.0f C'
                              % (temp, cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX))
            return cfg.LEVEL_ALARM

        if temp < cfg.TEMP_TARGET_MIN or temp > cfg.TEMP_TARGET_MAX:
            self._raise_alert('TEMP_RANGE', cfg.LEVEL_WARNING,
                              'Temperature %.1f C left the %.0f-%.0f C storage band'
                              % (temp, cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX))
            return cfg.LEVEL_WARNING

        self._clear_alert('TEMP_RANGE',
                          'Temperature back inside the storage band (%.1f C)' % temp)
        return cfg.LEVEL_INFO

    def _check_excursion(self, now):
        """A brief excursion is tolerable; a sustained one spoils the stock."""
        temp = self.temperature
        if temp is None:
            return cfg.LEVEL_INFO

        in_band = cfg.TEMP_TARGET_MIN <= temp <= cfg.TEMP_TARGET_MAX
        if in_band:
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
            self._raise_alert('TEMP_EXCURSION', cfg.LEVEL_ALARM, message)
            return cfg.LEVEL_ALARM
        return cfg.LEVEL_INFO

    def _check_humidity(self):
        hum = self.humidity
        if hum is None:
            return cfg.LEVEL_INFO
        if hum > cfg.HUM_ALARM_MAX:
            self._raise_alert('HUM_RANGE', cfg.LEVEL_ALARM,
                              'Humidity %.0f %% - condensation risk' % hum)
            return cfg.LEVEL_ALARM
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
            return cfg.LEVEL_INFO  # probe B has never reported; nothing to compare

        silent_for = now - self.last_temp_b_time
        if silent_for > cfg.PROBE_B_TIMEOUT_SECONDS:
            # Losing redundancy is not an emergency, but it must be visible:
            # the unit is now running on a single unverified probe.
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

        # A brief disagreement is just noise; a sustained one is a failed probe.
        if now - self.probe_mismatch_since >= cfg.PROBE_DISAGREE_SECONDS:
            self._raise_alert('PROBE_MISMATCH', cfg.LEVEL_ALARM,
                              'Probes disagree by %.1f C (A %.1f, B %.1f) - '
                              'readings cannot be trusted'
                              % (delta, self.temperature, self.temperature_b))
            return cfg.LEVEL_ALARM
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
            # Nothing is judged during the grace period. A motor draws several
            # times its running current for a second or two on start-up, and
            # coasts down slowly afterwards; reacting to either would report a
            # fault on every single compressor cycle.
            return cfg.LEVEL_INFO

        if current > cfg.CURRENT_OVERLOAD_A:
            self._raise_alert('COMPRESSOR_OVERLOAD', cfg.LEVEL_ALARM,
                              'Compressor drawing %.1f A - above the %.1f A limit'
                              % (current, cfg.CURRENT_OVERLOAD_A))
            return cfg.LEVEL_ALARM
        self._clear_alert('COMPRESSOR_OVERLOAD', 'Compressor current back to normal')

        if self.compressor == 'ON' and not drawing:
            self._raise_alert('COMPRESSOR_NO_CURRENT', cfg.LEVEL_ALARM,
                              'Compressor commanded ON but drawing %.2f A - '
                              'relay or motor failure' % current)
            return cfg.LEVEL_ALARM
        if self.compressor == 'OFF' and drawing:
            self._raise_alert('COMPRESSOR_STUCK_ON', cfg.LEVEL_ALARM,
                              'Compressor commanded OFF but drawing %.2f A - '
                              'contacts welded closed' % current)
            return cfg.LEVEL_ALARM

        self._clear_alert('COMPRESSOR_NO_CURRENT',
                          'Compressor is drawing current again')
        self._clear_alert('COMPRESSOR_STUCK_ON', 'Compressor has stopped drawing')
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

        if self.fan == 'ON' and not turning:
            self._raise_alert('FAN_STALLED', cfg.LEVEL_ALARM,
                              'Fan commanded ON but reading %d rpm - blocked or seized'
                              % int(rpm))
            return cfg.LEVEL_ALARM
        self._clear_alert('FAN_STALLED', 'Fan is turning again')

        if self.fan == 'OFF' and turning:
            self._raise_alert('FAN_STUCK_ON', cfg.LEVEL_WARNING,
                              'Fan commanded OFF but still turning at %d rpm'
                              % int(rpm))
            return cfg.LEVEL_WARNING
        self._clear_alert('FAN_STUCK_ON', 'Fan has stopped')

        if self.fan == 'ON' and rpm < cfg.FAN_RPM_DEGRADED:
            # Still circulating, but not well. Worth servicing before it fails.
            self._raise_alert('FAN_DEGRADED', cfg.LEVEL_WARNING,
                              'Fan at %d rpm, below the %d rpm minimum - '
                              'bearing wear' % (int(rpm), cfg.FAN_RPM_DEGRADED))
            return cfg.LEVEL_WARNING
        self._clear_alert('FAN_DEGRADED', 'Fan speed back to normal')
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
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_ALARM,
                              'Door has been open for %d s' % int(open_for),
                              operator=operator)
            return cfg.LEVEL_ALARM
        if open_for >= cfg.DOOR_WARNING_SECONDS:
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_WARNING,
                              'Door open for %d s' % int(open_for),
                              operator=operator)
            return cfg.worst(level, cfg.LEVEL_WARNING)
        return level

    def _check_power(self, now):
        level = cfg.LEVEL_INFO

        if self.battery <= cfg.BATTERY_ALARM_PERCENT and self.power_source == 'BATTERY':
            self._raise_alert('BATTERY_LOW', cfg.LEVEL_ALARM,
                              'Backup battery at %.0f %%' % self.battery)
            level = cfg.LEVEL_ALARM
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
        if self.temperature is None:
            return ''
        if self.temperature <= cfg.TEMP_TARGET_MAX:
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

        siren = 'ON' if self.overall_level == cfg.LEVEL_ALARM else 'OFF'

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
                # Restart the grace period: the feedback sensors are only
                # allowed to contradict a command once the hardware has had
                # time to act on it.
                if attr == 'compressor':
                    self.compressor_since = now
                elif attr == 'fan':
                    self.fan_since = now
            if changed or refresh:
                self.mqtt.publish(topic, new_value)

    def _snapshot(self, now, sensor_state):
        door_seconds = int(now - self.door_since) if self.door_since else 0
        excursion_seconds = int(now - self.excursion_since) if self.excursion_since else 0
        probe_delta = None
        if self.temperature is not None and self.temperature_b is not None:
            probe_delta = round(abs(self.temperature - self.temperature_b), 2)

        return {
            'ts': db.now_string(),
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
            'level': self.overall_level,
            'diagnosis': self.diagnosis,
            'excursion_seconds': excursion_seconds,
            'sensor_state': sensor_state,
            'sensor_online': sensor_state == SENSOR_ONLINE,
            'active_alerts': sorted(self.active_alerts.keys()),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run(self):
        db.init_db()
        print('%s  manager | database ready: %s' % (stamp(), db.DB_FILE))

        self.mqtt.subscribe(cfg.TOPIC_TEMP, cfg.TOPIC_TEMP_B, cfg.TOPIC_AMBIENT,
                            cfg.TOPIC_DOOR, cfg.TOPIC_POWER, cfg.TOPIC_BADGE,
                            cfg.TOPIC_CURRENT, cfg.TOPIC_FAN_RPM,
                            cfg.TOPIC_MODE_CMD)
        self.mqtt.start()
        print('%s  manager | connecting to %s:%s'
              % (stamp(), cfg.BROKER_HOST, cfg.BROKER_PORT))

        last_summary = 0.0
        try:
            while self._running:
                self.evaluate()
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

        print('%s  manager | %-7s A=%-7s B=%-7s amb=%-6s door=%-6s '
              'comp=%-3s %-6s fan=%-3s %-8s siren=%s'
              % (stamp(), self.overall_level,
                 number(self.temperature, '%.1f', 'C'),
                 number(self.temperature_b, '%.1f', 'C'),
                 number(self.ambient, '%.1f', 'C'),
                 'OPEN' if self.door_open else 'CLOSED',
                 self.compressor, number(self.compressor_current, '%.2f', 'A'),
                 self.fan, number(self.fan_rpm, '%.0f', 'rpm'),
                 self.siren))
        if self.diagnosis:
            print('%s  manager | cause: %s' % (stamp(), self.diagnosis))

    def shutdown(self):
        self._running = False
        # Leave the hardware in a safe, quiet state.
        self.mqtt.publish(cfg.TOPIC_SIREN_CMD, 'OFF')
        self.mqtt.publish(cfg.TOPIC_COMPRESSOR_CMD, 'OFF')
        self.mqtt.publish(cfg.TOPIC_FAN_CMD, 'OFF')
        time.sleep(0.3)
        self.mqtt.stop()
        print('%s  manager | stopped' % stamp())


if __name__ == '__main__':
    ColdChainManager().run()
