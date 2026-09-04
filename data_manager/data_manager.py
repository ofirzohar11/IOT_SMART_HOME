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
        self.door_open = False
        self.door_since = None
        self.power_source = 'MAINS'
        self.battery = 100.0
        self.battery_since = None

        # Derived state
        self.excursion_since = None
        self.mode = MODE_MONITORING
        self.overall_level = cfg.LEVEL_INFO

        # Actuator state as commanded by this manager
        self.compressor = 'OFF'
        self.fan = 'OFF'
        self.siren = 'OFF'
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
            elif topic == cfg.TOPIC_DOOR:
                self._handle_door(payload)
            elif topic == cfg.TOPIC_POWER:
                self._handle_power(payload)
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

    def _handle_door(self, payload):
        data = parse_json(payload, {})
        is_open = str(data.get('state', '')).upper() == 'OPEN'
        if is_open and not self.door_open:
            self.door_since = time.time()
        elif not is_open:
            self.door_since = None
        self.door_open = is_open

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
    def _raise_alert(self, code, level, message):
        """Report a condition. Only writes when the level for this code changes."""
        if self.active_alerts.get(code) == level:
            return
        self.active_alerts[code] = level
        self._emit_event(level, code, message)

    def _clear_alert(self, code, message):
        if code not in self.active_alerts:
            return
        del self.active_alerts[code]
        self._emit_event(cfg.LEVEL_INFO, code + '_CLEARED', message)

    def _emit_event(self, level, code, message):
        print('%s  manager | %-7s %-18s %s' % (stamp(), level, code, message))
        db.insert_event(level, code, message)
        self.mqtt.publish_json(cfg.TOPIC_ALERT, {
            'level': level,
            'code': code,
            'message': message,
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

            levels.append(self._check_door(now))
            levels.append(self._check_power(now))

            self.overall_level = cfg.worst(*levels)
            if self.mode == MODE_MAINTENANCE:
                # Servicing the unit is expected to break the rules; keep logging
                # the conditions but do not escalate the unit to an alarm state.
                self.overall_level = cfg.LEVEL_INFO

            self._drive_actuators(now)
            snapshot = self._snapshot(now, sensor_state)

        self.mqtt.publish_json(cfg.TOPIC_STATUS, snapshot)

        if now - self._last_db_write >= cfg.DB_WRITE_INTERVAL_S:
            self._last_db_write = now
            db.insert_reading(self.temperature, self.humidity,
                              'OPEN' if self.door_open else 'CLOSED',
                              self.power_source, self.battery,
                              self.compressor, self.fan, self.siren,
                              self.overall_level)

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
            self._raise_alert('TEMP_EXCURSION', cfg.LEVEL_ALARM,
                              'Temperature outside 2-8 C for %d s - stock at risk'
                              % int(duration))
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

    def _check_door(self, now):
        if not self.door_open or self.door_since is None:
            self._clear_alert('DOOR_OPEN', 'Door closed')
            return cfg.LEVEL_INFO

        open_for = now - self.door_since
        if open_for >= cfg.DOOR_ALARM_SECONDS:
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_ALARM,
                              'Door has been open for %d s' % int(open_for))
            return cfg.LEVEL_ALARM
        if open_for >= cfg.DOOR_WARNING_SECONDS:
            self._raise_alert('DOOR_OPEN', cfg.LEVEL_WARNING,
                              'Door open for %d s' % int(open_for))
            return cfg.LEVEL_WARNING
        return cfg.LEVEL_INFO

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
            if new_value != getattr(self, attr) or refresh:
                setattr(self, attr, new_value)
                self.mqtt.publish(topic, new_value)

    def _snapshot(self, now, sensor_state):
        door_seconds = int(now - self.door_since) if self.door_since else 0
        excursion_seconds = int(now - self.excursion_since) if self.excursion_since else 0
        return {
            'ts': db.now_string(),
            'temperature': self.temperature,
            'humidity': self.humidity,
            'door': 'OPEN' if self.door_open else 'CLOSED',
            'door_seconds': door_seconds,
            'power': self.power_source,
            'battery': self.battery,
            'compressor': self.compressor,
            'fan': self.fan,
            'siren': self.siren,
            'mode': self.mode,
            'level': self.overall_level,
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

        self.mqtt.subscribe(cfg.TOPIC_TEMP, cfg.TOPIC_DOOR, cfg.TOPIC_POWER,
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
        temp = '--' if self.temperature is None else '%.1f C' % self.temperature
        hum = '--' if self.humidity is None else '%.0f %%' % self.humidity
        print('%s  manager | %-7s temp=%-7s hum=%-5s door=%-6s power=%-7s '
              'comp=%-3s fan=%-3s siren=%-3s'
              % (stamp(), self.overall_level, temp, hum,
                 'OPEN' if self.door_open else 'CLOSED', self.power_source,
                 self.compressor, self.fan, self.siren))

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
