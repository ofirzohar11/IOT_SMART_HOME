"""Central configuration for the Cold Chain Monitor.

Every process (emulators, data manager, GUI) imports this module, so the broker,
the topic tree, the alarm thresholds and the severity vocabulary are defined
exactly once.
"""

import socket
import sys

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

KEEPALIVE = 30          # seconds; a dead link is noticed within ~1.5x this
RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 20


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

# Sensors -> manager
TOPIC_TEMP = TOPIC_ROOT + '/sensor/temp'          # primary probe
TOPIC_TEMP_B = TOPIC_ROOT + '/sensor/temp_b'      # redundant probe
TOPIC_AMBIENT = TOPIC_ROOT + '/sensor/ambient'    # room temperature
TOPIC_DOOR = TOPIC_ROOT + '/sensor/door'
TOPIC_POWER = TOPIC_ROOT + '/sensor/power'
TOPIC_BADGE = TOPIC_ROOT + '/sensor/badge'        # RFID reader at the door
TOPIC_CURRENT = TOPIC_ROOT + '/sensor/current'    # compressor current draw
TOPIC_FAN_RPM = TOPIC_ROOT + '/sensor/fan_rpm'    # fan tachometer

# Manager <-> actuators
TOPIC_COMPRESSOR_CMD = TOPIC_ROOT + '/actuator/compressor/cmd'
TOPIC_COMPRESSOR_STS = TOPIC_ROOT + '/actuator/compressor/sts'
TOPIC_FAN_CMD = TOPIC_ROOT + '/actuator/fan/cmd'
TOPIC_FAN_STS = TOPIC_ROOT + '/actuator/fan/sts'
TOPIC_SIREN_CMD = TOPIC_ROOT + '/actuator/siren/cmd'
TOPIC_SIREN_STS = TOPIC_ROOT + '/actuator/siren/sts'

# Manager -> GUI
TOPIC_ALERT = TOPIC_ROOT + '/alert'
TOPIC_STATUS = TOPIC_ROOT + '/status'
TOPIC_INCIDENTS = TOPIC_ROOT + '/incidents'

# GUI -> manager
TOPIC_MODE_CMD = TOPIC_ROOT + '/mode/cmd'
TOPIC_INCIDENT_CMD = TOPIC_ROOT + '/incident/cmd'   # acknowledge / resolve

# GUI -> everyone: the thresholds below, as edited from the Settings page.
# Published retained, so a process that starts later is configured the moment
# it connects rather than running on stale limits until the next edit.
TOPIC_SETTINGS = TOPIC_ROOT + '/settings'

# GUI -> emulators: fault injection. Every device subscribes and applies the
# faults it owns; each reports back what it currently has active.
TOPIC_SIM_CMD = TOPIC_ROOT + '/sim/cmd'
TOPIC_SIM_STS = TOPIC_ROOT + '/sim/sts'          # each device posts to sts/<id>
TOPIC_SIM_STS_WILDCARD = TOPIC_SIM_STS + '/+'


def sim_status_topic(device_id):
    return '%s/%s' % (TOPIC_SIM_STS, device_id)

# --------------------------------------------------------------------------
# Severity vocabulary
# --------------------------------------------------------------------------
LEVEL_INFO = 'INFO'
LEVEL_WARNING = 'WARNING'
LEVEL_CRITICAL = 'CRITICAL'
LEVELS = (LEVEL_INFO, LEVEL_WARNING, LEVEL_CRITICAL)
LEVEL_ORDER = {LEVEL_INFO: 0, LEVEL_WARNING: 1, LEVEL_CRITICAL: 2}

# Databases written before the rename store 'ALARM'; treat it as CRITICAL when
# reading history back so old rows still sort and colour correctly.
LEGACY_LEVELS = {'ALARM': LEVEL_CRITICAL}


def normalise_level(level):
    return LEGACY_LEVELS.get(level, level)


def worst(*levels):
    """Return the most severe level out of the ones given."""
    return max(levels, key=lambda lv: LEVEL_ORDER.get(normalise_level(lv), 0))


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
# Approaching the edge of the band is worth surfacing before it is breached.
TEMP_APPROACH_MARGIN = 0.8

HUM_TARGET_MIN = 30.0
HUM_TARGET_MAX = 70.0
HUM_ALARM_MAX = 85.0

# Gauge / chart ranges
TEMP_GAUGE_MIN = -5.0
TEMP_GAUGE_MAX = 15.0
HUM_GAUGE_MIN = 0.0
HUM_GAUGE_MAX = 100.0

# Plausibility limits: anything outside these is a malformed reading, not a
# real measurement, and is rejected rather than alarmed on.
VALID_TEMP_RANGE = (-60.0, 90.0)
VALID_HUM_RANGE = (0.0, 100.0)
VALID_CURRENT_RANGE = (0.0, 60.0)
VALID_RPM_RANGE = (0.0, 10000.0)
VALID_BATTERY_RANGE = (0.0, 100.0)

# --------------------------------------------------------------------------
# Compressor control (hysteresis keeps the relay from chattering around 8 C)
# --------------------------------------------------------------------------
COMPRESSOR_ON_ABOVE = 6.5
COMPRESSOR_OFF_BELOW = 3.5

# --------------------------------------------------------------------------
# Time based rules
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
PROBE_DISAGREE_C = 2.0
PROBE_DISAGREE_SECONDS = 30
PROBE_B_TIMEOUT_SECONDS = 30

# --------------------------------------------------------------------------
# Actuator feedback - measuring what the hardware actually did
# --------------------------------------------------------------------------
ACTUATOR_FAULT_SECONDS = 15   # grace period after a command before judging it

CURRENT_NOMINAL_A = 4.2
CURRENT_RUNNING_MIN_A = 0.5
CURRENT_OVERLOAD_A = 8.0

FAN_RPM_NOMINAL = 1450
FAN_RPM_MIN = 300
FAN_RPM_DEGRADED = 900

# --------------------------------------------------------------------------
# Ambient (room) temperature
# --------------------------------------------------------------------------
AMBIENT_NOMINAL_C = 22.0
AMBIENT_WARNING_C = 30.0
AMBIENT_TIMEOUT_SECONDS = 30

# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
BADGE_VALID_SECONDS = 60
UNKNOWN_OPERATOR = 'UNKNOWN'
DEFAULT_OPERATOR = 'Console operator'

# --------------------------------------------------------------------------
# Connectivity
# --------------------------------------------------------------------------
# How long the manager may be disconnected from the broker before it is treated
# as a communications failure rather than a blip.
MQTT_DOWN_SECONDS = 12

# A simulated link outage heals itself, both because real ones do and because a
# device with its connection cut can no longer hear the command to restore it.
SIM_OUTAGE_SECONDS = 30

# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------
SENSOR_PUBLISH_MS = 3000     # temperature sensor sample rate
EVALUATE_INTERVAL_S = 1.0    # data manager rule evaluation tick
DB_WRITE_INTERVAL_S = 5.0    # how often a reading row is persisted
STATUS_PUBLISH_INTERVAL_S = 1.0

# --------------------------------------------------------------------------
# Operator overrides
# --------------------------------------------------------------------------
# Everything above is the recommended default. The console can override any of
# the thresholds listed in ``config.settings``, and those overrides are written
# back onto this module here, at the end of the import, before any other module
# has had a chance to read a value.
#
# The order matters: the literals are captured as the recommended values first,
# so "Restore recommended defaults" restores what this file declares rather
# than whatever happens to be loaded.
from config import settings as _settings   # noqa: E402  (must come last)

RECOMMENDED = _settings.capture_defaults(sys.modules[__name__])
_settings.apply_saved(sys.modules[__name__])
