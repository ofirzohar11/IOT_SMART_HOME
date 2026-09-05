"""Device registry and fault catalogue.

One declarative description of every physical device in the unit, shared by:

* the **emulators**, which look up the faults they are expected to honour,
* the **data manager**, which uses the expected telemetry period to decide when
  a device has gone stale,
* the **GUI**, which builds the device page and the fault-injection console from
  this list rather than hard-coding either.

Adding a device means adding one entry here.

``icon`` names a line-art drawing in ``ui.icons`` rather than holding a
character. These used to be emoji, which the operating system renders in its
own colour font: a monitoring console for pharmaceutical storage picked up a
brown door and a flashing red beacon, at whatever weight the platform chose,
in colours that collided with a palette where green, amber and red mean
something.
"""

from config import mqtt_init as cfg

# Device kinds
SENSOR = 'SENSOR'
ACTUATOR = 'ACTUATOR'

# Health states, ordered from best to worst.
CONNECTED = 'CONNECTED'
DEGRADED = 'DEGRADED'
MAINTENANCE = 'MAINTENANCE'
FAULT = 'FAULT'
OFFLINE = 'OFFLINE'
HEALTH_ORDER = {CONNECTED: 0, MAINTENANCE: 1, DEGRADED: 2, FAULT: 3, OFFLINE: 4}


class Fault(object):
    """One injectable failure mode."""

    def __init__(self, fault_id, label, description, confirm=False):
        self.id = fault_id
        self.label = label
        self.description = description
        self.confirm = confirm          # ask before arming this one

    def as_dict(self):
        return {'id': self.id, 'label': self.label,
                'description': self.description, 'confirm': self.confirm}


class Device(object):

    def __init__(self, device_id, label, kind, group, icon, period_s,
                 telemetry_topic=None, cmd_topic=None, sts_topic=None,
                 unit='', faults=(), describes=''):
        self.id = device_id
        self.label = label
        self.kind = kind
        self.group = group
        self.icon = icon                # a name in ui.icons, not a character
        self.period_s = period_s        # expected seconds between messages
        self.telemetry_topic = telemetry_topic
        self.cmd_topic = cmd_topic
        self.sts_topic = sts_topic
        self.unit = unit
        self.describes = describes
        self.faults = list(BASE_FAULTS) + list(faults)

    @property
    def stale_after(self):
        """A device is late once it has missed roughly three of its slots."""
        return max(10.0, self.period_s * 3.0 + 4.0)

    def fault(self, fault_id):
        for item in self.faults:
            if item.id == fault_id:
                return item
        return None


# --------------------------------------------------------------------------
# Faults every device supports. Implemented once in the emulator base class,
# so each device inherits realistic connectivity failures for free.
# --------------------------------------------------------------------------
BASE_FAULTS = (
    Fault('mqtt_disconnect', 'MQTT disconnect',
          'Drop this device\'s broker connection entirely.', confirm=True),
    Fault('telemetry_stop', 'Missing telemetry',
          'Device stays powered but stops publishing.'),
    Fault('telemetry_delay', 'Delayed telemetry',
          'Publish at a quarter of the normal rate.'),
)

# --------------------------------------------------------------------------
# The devices themselves
# --------------------------------------------------------------------------
DEVICES = [
    Device(
        'temp', 'Temperature Probe A', SENSOR, 'Cabinet', 'thermometer',
        period_s=cfg.SENSOR_PUBLISH_MS / 1000.0,
        telemetry_topic=cfg.TOPIC_TEMP, unit='°C',
        describes='Primary probe and humidity, driven by a thermal model.',
        faults=(
            Fault('cooling_fail', 'Cooling failure',
                  'The compressor is commanded on but has no cooling effect.'),
            Fault('temp_spike', 'Temperature spike',
                  'Force the reading far above the safe band.', confirm=True),
            Fault('temp_drop', 'Temperature drop',
                  'Force the reading below freezing.', confirm=True),
            Fault('temp_drift', 'Slow temperature drift',
                  'Reading creeps away from the true value.'),
            Fault('temp_frozen', 'Frozen temperature value',
                  'Reading stops changing but keeps being published.'),
            Fault('hum_spike', 'Humidity spike',
                  'Force humidity above the condensation limit.'),
            Fault('hum_drop', 'Humidity drop', 'Force humidity far too low.'),
            Fault('hum_frozen', 'Frozen humidity value',
                  'Humidity stops changing but keeps being published.'),
        ),
    ),
    Device(
        'temp_b', 'Temperature Probe B', SENSOR, 'Cabinet', 'thermometer',
        period_s=cfg.SENSOR_PUBLISH_MS / 1000.0,
        telemetry_topic=cfg.TOPIC_TEMP_B, unit='°C',
        describes='Redundant probe that cross-checks probe A.',
        faults=(
            Fault('probe_drift', 'Probe drift',
                  'Calibration slowly walks away from probe A.'),
            Fault('probe_frozen', 'Frozen reading',
                  'Probe reports the same value forever.'),
        ),
    ),
    Device(
        'ambient', 'Ambient Room Sensor', SENSOR, 'Facility', 'room',
        period_s=3.0, telemetry_topic=cfg.TOPIC_AMBIENT, unit='°C',
        describes='Storeroom temperature outside the cabinet.',
        faults=(
            Fault('room_hot', 'Building cooling failure',
                  'Storeroom climbs above the warning threshold.'),
        ),
    ),
    Device(
        'door', 'Door Sensor', SENSOR, 'Cabinet', 'door',
        period_s=0.0, telemetry_topic=cfg.TOPIC_DOOR,
        describes='Reed switch reporting a retained OPEN / CLOSED state.',
        faults=(
            Fault('door_forced', 'Door forced open',
                  'Door opens with no badge presented.'),
            Fault('door_stuck', 'Door stuck open',
                  'Door reports OPEN and refuses to close.', confirm=True),
            Fault('door_sensor_fail', 'Door sensor failure',
                  'Switch reports CLOSED no matter what the door does.'),
        ),
    ),
    Device(
        'badge', 'RFID Badge Reader', SENSOR, 'Cabinet', 'badge',
        period_s=0.0, telemetry_topic=cfg.TOPIC_BADGE,
        describes='Names the operator responsible for a door opening.',
        faults=(
            Fault('badge_invalid', 'Invalid badge',
                  'Reader emits an unreadable badge id.'),
            Fault('badge_unauthorised', 'Unauthorised badge',
                  'A badge that is not on the staff list is presented.'),
            Fault('reader_offline', 'Reader unavailable',
                  'Reader stops responding to scans.'),
        ),
    ),
    Device(
        'power', 'Power Supply Sensor', SENSOR, 'Facility', 'battery',
        period_s=3.0, telemetry_topic=cfg.TOPIC_POWER, unit='%',
        describes='Mains vs. backup battery and the charge remaining.',
        faults=(
            Fault('power_outage', 'Power outage',
                  'Mains lost, unit runs on the backup battery.', confirm=True),
            Fault('power_unstable', 'Unstable power',
                  'Supply flaps between mains and battery.'),
            Fault('battery_drain', 'Battery depletion',
                  'Backup battery drains rapidly toward empty.', confirm=True),
        ),
    ),
    Device(
        'current', 'Compressor Current Sensor', SENSOR, 'Plant', 'bolt',
        period_s=2.0, telemetry_topic=cfg.TOPIC_CURRENT, unit='A',
        describes='Clamp meter measuring what the motor really draws.',
        faults=(
            Fault('open_circuit', 'Compressor failure (open circuit)',
                  'Commanded on but drawing nothing - burnt contact or seized motor.'),
            Fault('welded_relay', 'Compressor stuck ON (welded relay)',
                  'Commanded off but still drawing current.', confirm=True),
            Fault('overload', 'Compressor overload',
                  'Motor draws far above its rated current.', confirm=True),
            Fault('erratic_current', 'Abnormal current',
                  'Current swings unpredictably around its nominal value.'),
        ),
    ),
    Device(
        'fan_rpm', 'Fan Tachometer', SENSOR, 'Plant', 'fan',
        period_s=2.0, telemetry_topic=cfg.TOPIC_FAN_RPM, unit='rpm',
        describes='Hall sensor measuring whether the fan really turns.',
        faults=(
            Fault('fan_stall', 'Fan failure (stalled)',
                  'Commanded on but not turning at all.'),
            Fault('fan_low_rpm', 'Low RPM (worn bearing)',
                  'Turning, but too slowly to circulate properly.'),
            Fault('fan_free_run', 'Fan stuck ON',
                  'Keeps spinning after being commanded off.'),
            Fault('erratic_rpm', 'Abnormal RPM',
                  'Speed swings unpredictably.'),
        ),
    ),
    Device(
        'compressor', 'Compressor Relay', ACTUATOR, 'Plant', 'power_switch',
        period_s=0.0, cmd_topic=cfg.TOPIC_COMPRESSOR_CMD,
        sts_topic=cfg.TOPIC_COMPRESSOR_STS,
        describes='Switches the cooling element.',
        faults=(
            Fault('relay_ignore', 'Relay ignores commands',
                  'Relay reports its old state whatever it is told.'),
            Fault('relay_stuck_on', 'Relay stuck ON',
                  'Relay reports ON permanently.', confirm=True),
            Fault('relay_stuck_off', 'Relay stuck OFF',
                  'Relay reports OFF permanently.', confirm=True),
        ),
    ),
    Device(
        'fan', 'Fan Relay', ACTUATOR, 'Plant', 'fan',
        period_s=0.0, cmd_topic=cfg.TOPIC_FAN_CMD, sts_topic=cfg.TOPIC_FAN_STS,
        describes='Switches the circulation fan.',
        faults=(
            Fault('relay_ignore', 'Relay ignores commands',
                  'Relay reports its old state whatever it is told.'),
            Fault('relay_stuck_on', 'Relay stuck ON',
                  'Relay reports ON permanently.', confirm=True),
            Fault('relay_stuck_off', 'Relay stuck OFF',
                  'Relay reports OFF permanently.', confirm=True),
        ),
    ),
    Device(
        'siren', 'Siren Relay', ACTUATOR, 'Plant', 'siren',
        period_s=0.0, cmd_topic=cfg.TOPIC_SIREN_CMD, sts_topic=cfg.TOPIC_SIREN_STS,
        describes='Audible alarm for any active critical condition.',
        faults=(
            Fault('relay_ignore', 'Siren failure',
                  'Siren never sounds, whatever it is told.', confirm=True),
            Fault('relay_stuck_on', 'Siren forced ON',
                  'Siren sounds permanently.', confirm=True),
        ),
    ),
]

BY_ID = {device.id: device for device in DEVICES}
GROUPS = ['Cabinet', 'Plant', 'Facility']


def get(device_id):
    return BY_ID.get(device_id)


def sensors():
    return [d for d in DEVICES if d.kind == SENSOR]


def actuators():
    return [d for d in DEVICES if d.kind == ACTUATOR]


def telemetry_devices():
    """Devices that publish on a schedule, so silence is meaningful."""
    return [d for d in DEVICES if d.telemetry_topic and d.period_s > 0]


# --------------------------------------------------------------------------
# One-click scenarios: realistic multi-device failures for a demo or a drill.
# --------------------------------------------------------------------------
class Scenario(object):

    def __init__(self, scenario_id, label, description, expectation, faults):
        self.id = scenario_id
        self.label = label
        self.description = description
        self.expectation = expectation      # what the operator should observe
        self.faults = faults                # [(device_id, fault_id), ...]


SCENARIOS = [
    Scenario(
        'power_failure', 'Power Failure',
        'Mains is lost and the unit falls back to its backup battery, which '
        'then drains.',
        'Power card switches to BATTERY, a warning appears after 60 s, and a '
        'critical low-battery incident once the charge passes 20 %.',
        [('power', 'power_outage'), ('power', 'battery_drain')],
    ),
    Scenario(
        'compressor_failure', 'Compressor Failure',
        'The relay still reports ON but the motor draws no current, so the '
        'cabinet stops cooling.',
        'A critical COMPRESSOR_NO_CURRENT incident, the temperature climbing, '
        'and the assessment naming the compressor as the cause.',
        [('current', 'open_circuit'), ('temp', 'cooling_fail')],
    ),
    Scenario(
        'temperature_excursion', 'Temperature Excursion',
        'Cooling is lost while the storeroom is hot, driving the cabinet out '
        'of the 2-8 °C band.',
        'Warning as the band is left, critical past the hard limit, and a '
        'separate excursion incident once it has lasted 90 s.',
        [('temp', 'cooling_fail'), ('ambient', 'room_hot')],
    ),
    Scenario(
        'door_left_open', 'Door Left Open',
        'The door is opened without a badge and jammed open.',
        'An unauthorised-access warning immediately, a door warning at 20 s '
        'and a critical door incident at 45 s.',
        [('door', 'door_stuck')],
    ),
    Scenario(
        'fan_failure', 'Fan Failure',
        'The circulation fan seizes while the compressor keeps running.',
        'A critical FAN_STALLED incident even though the temperature still '
        'reads normally - the failure nothing else would catch.',
        [('fan_rpm', 'fan_stall')],
    ),
    Scenario(
        'sensor_blackout', 'Sensor Blackout',
        'Both temperature probes stop reporting at once.',
        'Redundancy-lost warning, then a critical sensor-offline incident and '
        'a SENSOR OFFLINE banner.',
        [('temp', 'telemetry_stop'), ('temp_b', 'telemetry_stop')],
    ),
]

SCENARIOS_BY_ID = {s.id: s for s in SCENARIOS}
