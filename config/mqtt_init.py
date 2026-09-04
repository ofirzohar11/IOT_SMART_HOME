"""Central configuration for the Cold Chain Monitor system.

Every process (emulators, data manager, GUI) imports this module, so the broker,
the topic tree and the alarm thresholds are defined exactly once.
"""

import socket

# --------------------------------------------------------------------------
# Broker selection
# --------------------------------------------------------------------------
# 0 - HIT college broker (requires the college network / VPN)
# 1 - public HiveMQ broker (works from anywhere, used for the demo)
BROKER_INDEX = 1

_BROKER_HOSTS = ['vmm1.saaintertrade.com', 'broker.hivemq.com']
_BROKER_PORTS = [80, 1883]
_USERNAMES = ['MATZI', '']
_PASSWORDS = ['MATZI', '']

BROKER_HOST = _BROKER_HOSTS[BROKER_INDEX]
BROKER_PORT = _BROKER_PORTS[BROKER_INDEX]
USERNAME = _USERNAMES[BROKER_INDEX]
PASSWORD = _PASSWORDS[BROKER_INDEX]

KEEPALIVE = 60


def resolve_broker_ip():
    """Return the broker IP for display purposes, falling back to the hostname."""
    try:
        return socket.gethostbyname(BROKER_HOST)
    except socket.gaierror:
        return BROKER_HOST


# --------------------------------------------------------------------------
# Topic tree
# --------------------------------------------------------------------------
# The public HiveMQ broker is shared with the whole internet, so the root is
# namespaced to this project to avoid picking up somebody else's traffic.
TOPIC_ROOT = 'HIT/coldchain/ofir/unit1'

TOPIC_TEMP = TOPIC_ROOT + '/sensor/temp'          # primary probe
TOPIC_TEMP_B = TOPIC_ROOT + '/sensor/temp_b'      # redundant probe
TOPIC_AMBIENT = TOPIC_ROOT + '/sensor/ambient'    # room temperature outside the unit
TOPIC_DOOR = TOPIC_ROOT + '/sensor/door'
TOPIC_POWER = TOPIC_ROOT + '/sensor/power'
TOPIC_BADGE = TOPIC_ROOT + '/sensor/badge'        # RFID reader at the door
TOPIC_CURRENT = TOPIC_ROOT + '/sensor/current'    # compressor current draw
TOPIC_FAN_RPM = TOPIC_ROOT + '/sensor/fan_rpm'    # fan tachometer

TOPIC_COMPRESSOR_CMD = TOPIC_ROOT + '/actuator/compressor/cmd'
TOPIC_COMPRESSOR_STS = TOPIC_ROOT + '/actuator/compressor/sts'
TOPIC_FAN_CMD = TOPIC_ROOT + '/actuator/fan/cmd'
TOPIC_FAN_STS = TOPIC_ROOT + '/actuator/fan/sts'
TOPIC_SIREN_CMD = TOPIC_ROOT + '/actuator/siren/cmd'
TOPIC_SIREN_STS = TOPIC_ROOT + '/actuator/siren/sts'

TOPIC_ALERT = TOPIC_ROOT + '/alert'
TOPIC_STATUS = TOPIC_ROOT + '/status'
TOPIC_MODE_CMD = TOPIC_ROOT + '/mode/cmd'

# --------------------------------------------------------------------------
# Storage thresholds
# --------------------------------------------------------------------------
# A pharmaceutical refrigerator for vaccines must stay inside 2-8 C. Anything
# outside that band is a temperature excursion; 0-10 C is the hard limit past
# which the stock is considered compromised immediately.
TEMP_TARGET_MIN = 2.0
TEMP_TARGET_MAX = 8.0
TEMP_ALARM_MIN = 0.0
TEMP_ALARM_MAX = 10.0

HUM_TARGET_MIN = 30.0
HUM_TARGET_MAX = 70.0
HUM_ALARM_MAX = 85.0

# Gauge / chart ranges
TEMP_GAUGE_MIN = -5.0
TEMP_GAUGE_MAX = 15.0
HUM_GAUGE_MIN = 0.0
HUM_GAUGE_MAX = 100.0

# --------------------------------------------------------------------------
# Compressor control (hysteresis keeps the relay from chattering around 8 C)
# --------------------------------------------------------------------------
COMPRESSOR_ON_ABOVE = 6.5
COMPRESSOR_OFF_BELOW = 3.5

# --------------------------------------------------------------------------
# Time based rules - these are what separate a cold chain monitor from a
# plain thermometer. A short excursion is tolerable, a sustained one is not.
# --------------------------------------------------------------------------
DOOR_WARNING_SECONDS = 20
DOOR_ALARM_SECONDS = 45
EXCURSION_ALARM_SECONDS = 90
BATTERY_WARNING_SECONDS = 60
BATTERY_ALARM_PERCENT = 20.0
SENSOR_TIMEOUT_SECONDS = 25

# --------------------------------------------------------------------------
# Redundant temperature probe
# --------------------------------------------------------------------------
# Two probes in the same cabinet should read almost the same. A sustained
# disagreement means one of them is lying, and there is no way to tell which -
# which is exactly why regulators require a second probe.
PROBE_DISAGREE_C = 2.0
PROBE_DISAGREE_SECONDS = 30
PROBE_B_TIMEOUT_SECONDS = 30

# --------------------------------------------------------------------------
# Actuator feedback - measuring what the hardware actually did
# --------------------------------------------------------------------------
# A relay reports the command it received, not whether the motor turned. The
# current clamp and the tachometer are what catch a welded relay or a seized
# compressor.
ACTUATOR_FAULT_SECONDS = 15   # grace period after a command before judging it

CURRENT_NOMINAL_A = 4.2       # a healthy compressor under load
CURRENT_RUNNING_MIN_A = 0.5   # below this the motor is not turning
CURRENT_OVERLOAD_A = 8.0      # above this it is straining or shorting

FAN_RPM_NOMINAL = 1450
FAN_RPM_MIN = 300             # below this the fan is stalled
FAN_RPM_DEGRADED = 900        # turning, but not fast enough - worn bearing

# --------------------------------------------------------------------------
# Ambient (room) temperature - used to tell a facility problem from a unit one
# --------------------------------------------------------------------------
AMBIENT_NOMINAL_C = 22.0
AMBIENT_WARNING_C = 30.0
AMBIENT_TIMEOUT_SECONDS = 30

# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
# A door opening is attributed to the last badge scanned within this window.
# Opening it without a badge is an unauthorised access for the audit trail.
BADGE_VALID_SECONDS = 60
UNKNOWN_OPERATOR = 'UNKNOWN'

# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------
SENSOR_PUBLISH_MS = 3000     # temperature sensor sample rate
EVALUATE_INTERVAL_S = 1.0    # data manager rule evaluation tick
DB_WRITE_INTERVAL_S = 5.0    # how often a reading row is persisted

# --------------------------------------------------------------------------
# Alert levels, ordered by severity
# --------------------------------------------------------------------------
LEVEL_INFO = 'INFO'
LEVEL_WARNING = 'WARNING'
LEVEL_ALARM = 'ALARM'
LEVEL_ORDER = {LEVEL_INFO: 0, LEVEL_WARNING: 1, LEVEL_ALARM: 2}


def worst(*levels):
    """Return the most severe level out of the ones given."""
    return max(levels, key=lambda lv: LEVEL_ORDER.get(lv, 0))
