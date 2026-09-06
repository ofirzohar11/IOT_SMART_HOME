"""Operator-editable thresholds: the catalogue, the file, and the validation.

Every alarm limit in this system used to be a literal in ``mqtt_init``. They
still are - that module remains the place a threshold is *declared*, and its
literal is the recommended default. What this module adds is a way to override
those declarations at runtime and have the override survive a restart.

How it fits together
--------------------

``mqtt_init`` defines each threshold, then, at the very bottom of the module,
hands itself to :func:`capture_defaults` (which records the literals as the
recommended values) and to :func:`apply_saved` (which overwrites them with
whatever the operator saved). Every process in the system reads its thresholds
as ``cfg.SOMETHING`` at the moment it needs them, never binding them at import,
so a value written back onto the module is picked up by the next rule
evaluation, the next emulator tick and the next repaint - in this process.

Other processes are reached over MQTT. The console publishes the full effective
set, retained, on ``TOPIC_SETTINGS``; the data manager and every emulator
subscribe and apply it. The retained message and the file agree because the
console writes both in the same operation, and the file is what a cold start
reads.

Where the numbers come from
---------------------------

Some defaults are taken from published cold-chain guidance and some are choices
made for this project, and the two must not be confused, so every entry says
which it is and cites its source. The distinction matters most for the timings:
real vaccine monitors judge an excursion over hours, which no ten-minute
demonstration could ever show, so the durations here are deliberately
compressed. That is a project decision, and it is labelled as one.
"""

import json
import os
import sys
import tempfile

# The file lives beside the database rather than in the source tree proper: it
# is operator state, not code, and it is regenerated the moment it is deleted.
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'thresholds.json')

FILE_VERSION = 1

# Basis - is this number from published guidance, or a project decision?
BASIS_RESEARCH = 'research'
BASIS_PROJECT = 'project'

# What crossing the threshold does. Used for the colour and the chip.
EFFECT_WARNING = 'WARNING'      # raises a warning
EFFECT_CRITICAL = 'CRITICAL'    # raises a critical alert
EFFECT_CONTROL = 'CONTROL'      # drives an actuator, no alert of its own
EFFECT_BASELINE = 'BASELINE'    # the healthy reference the rules compare against


class Setting(object):
    """One editable threshold: what it is, what it may be, and what it does."""

    def __init__(self, key, label, unit, group, kind='float',
                 minimum=0.0, maximum=100.0, decimals=1, raises=EFFECT_WARNING,
                 what='', effect='', basis=BASIS_PROJECT, source=''):
        self.key = key                  # attribute name on mqtt_init
        self.label = label
        self.unit = unit
        self.group = group
        self.kind = kind                # 'float' or 'int'
        self.minimum = minimum
        self.maximum = maximum
        self.decimals = 0 if kind == 'int' else decimals
        self.raises = raises
        self.what = what                # short explanation
        self.effect = effect            # what happens when it is exceeded
        self.basis = basis
        self.source = source

    # -- value handling ---------------------------------------------------
    def coerce(self, value):
        """Turn text or a number into this setting's type, or raise ValueError."""
        if isinstance(value, bool):     # bool is an int subclass; never wanted
            raise ValueError('not a number')
        number = float(value)
        if number != number or number in (float('inf'), float('-inf')):
            raise ValueError('not a finite number')
        if self.kind == 'int':
            if abs(number - round(number)) > 1e-9:
                raise ValueError('whole numbers only')
            return int(round(number))
        return round(number, self.decimals)

    def format(self, value, with_unit=True):
        if value is None:
            return '--'
        text = ('%%.%df' % self.decimals) % float(value)
        return '%s %s' % (text, self.unit) if with_unit and self.unit else text

    def range_text(self):
        return '%s to %s' % (self.format(self.minimum, with_unit=False),
                             self.format(self.maximum))

    @property
    def recommended(self):
        ensure_ready()
        return RECOMMENDED.get(self.key)


# ===========================================================================
#  Groups
# ===========================================================================
GROUPS = [
    ('fridge', 'Refrigerator temperature',
     'The storage band itself, the hard limits either side of it, and how long '
     'a reading may stay outside the band before the stock is called at risk.'),
    ('cooling', 'Cooling control',
     'The two temperatures the compressor switches on and off at. These do not '
     'raise an alert; they decide when the unit actually cools.'),
    ('humidity', 'Humidity',
     'Moisture inside the cabinet. Labels and cartons suffer long before the '
     'contents do, and condensation on a cold surface is what starts it.'),
    ('door', 'Door and access',
     'How long the door may stand open before it is a problem, and how long a '
     'badge scan counts as authorising the opening that follows it.'),
    ('probes', 'Sensor agreement',
     'The unit carries two thermometers so that a wrong reading can be caught. '
     'These decide when they have disagreed badly enough, and for long enough, '
     'to distrust both.'),
    ('room', 'Ambient (storeroom)',
     'The room the unit stands in. A fridge in a hot room fails differently '
     'from a broken fridge, and this is what tells the two apart.'),
    ('power', 'Power and battery',
     'Mains loss and the state of the backup battery.'),
    ('plant', 'Compressor and fan',
     'What the machinery actually did, measured rather than assumed: current '
     'drawn by the compressor, revolutions counted at the fan.'),
    ('liveness', 'Silence and connectivity',
     'How long a device may say nothing before silence is treated as a fault '
     'rather than a gap.'),
]

GROUP_TITLES = dict((key, title) for key, title, _blurb in GROUPS)


# ===========================================================================
#  The catalogue
# ===========================================================================
# Sources, cited in short form on each entry:
#
#   CDC   - Vaccine Storage and Handling Toolkit (refrigerated vaccines are
#           stored at 2-8 C, with 5 C / 40 F as the target; a digital data
#           logger records at least every 30 minutes).
#   WHO   - PQS performance specification E003 (the vaccine compartment holds
#           +2 to +8 C, and units are rated to operate in ambients up to +43 C)
#           and PQS E006 temperature monitoring devices, whose alarm rule is a
#           continuous 10 hours above +8 C or 1 hour below -0.5 C.
#   USP   - <659> Packaging and Storage: controlled cold temperature is 2-8 C,
#           tolerating excursions of 2-15 C for not more than 24 h; controlled
#           room temperature is 20-25 C. <797> holds classified compounding
#           areas below 60 % RH.
#
# Anything not carrying one of those is a decision made for this project, and
# says so.

SETTINGS = [

    # -- refrigerator ---------------------------------------------------
    Setting(
        'TEMP_TARGET_MIN', 'Storage band, low edge', '°C', 'fridge',
        minimum=-10.0, maximum=20.0, decimals=1, raises=EFFECT_WARNING,
        what='The coldest the cabinet may be and still count as in range. '
             'Below it the contents are at risk of freezing.',
        effect='A reading under this raises a temperature WARNING, and starts '
               'the excursion timer that escalates to CRITICAL.',
        basis=BASIS_RESEARCH,
        source='CDC Vaccine Storage and Handling Toolkit, WHO PQS E003 and '
               'USP <659> all give 2-8 °C for refrigerated vaccine storage. '
               'Freezing is not a mild excursion: most vaccines are discarded '
               'after it.'),
    Setting(
        'TEMP_TARGET_MAX', 'Storage band, high edge', '°C', 'fridge',
        minimum=-10.0, maximum=25.0, decimals=1, raises=EFFECT_WARNING,
        what='The warmest the cabinet may be and still count as in range.',
        effect='A reading over this raises a temperature WARNING and starts '
               'the excursion timer.',
        basis=BASIS_RESEARCH,
        source='CDC / WHO PQS E003 / USP <659>: 2-8 °C. CDC names 5 °C (40 °F) '
               'as the temperature to aim for inside that band.'),
    Setting(
        'TEMP_APPROACH_MARGIN', 'Early-warning margin', '°C', 'fridge',
        minimum=0.0, maximum=5.0, decimals=1, raises=EFFECT_WARNING,
        what='How close to either edge of the band counts as "approaching". '
             'Set it to 0 to switch the early warning off.',
        effect='Inside the band but within this margin of an edge raises the '
               'TEMP_APPROACHING warning, which is a prompt to look before '
               'anything is actually out of range.',
        basis=BASIS_PROJECT,
        source='No published standard sets an approach margin. 0.8 °C was '
               'chosen so the warning arrives while there is still time to '
               'act, without firing on ordinary compressor cycling.'),
    Setting(
        'TEMP_ALARM_MIN', 'Hard limit, low', '°C', 'fridge',
        minimum=-30.0, maximum=15.0, decimals=1, raises=EFFECT_CRITICAL,
        what='Below this the stock is treated as compromised immediately, '
             'without waiting for the excursion timer.',
        effect='Raises a CRITICAL temperature alert on the very first reading '
               'past it.',
        basis=BASIS_PROJECT,
        source='WHO PQS E006 monitors alarm below -0.5 °C after one hour. This '
               'project alarms at 0 °C and instantly, because a freeze that is '
               'noticed an hour later is a freeze that already happened.'),
    Setting(
        'TEMP_ALARM_MAX', 'Hard limit, high', '°C', 'fridge',
        minimum=-5.0, maximum=40.0, decimals=1, raises=EFFECT_CRITICAL,
        what='Above this the stock is treated as compromised immediately.',
        effect='Raises a CRITICAL temperature alert on the first reading past '
               'it, whatever the excursion timer says.',
        basis=BASIS_PROJECT,
        source='USP <659> tolerates 2-15 °C excursions for up to 24 h. 10 °C '
               'here is deliberately tighter: this unit is monitored '
               'continuously, so there is no reason to wait for 15 °C.'),
    Setting(
        'EXCURSION_ALARM_SECONDS', 'Excursion before critical', 's', 'fridge',
        kind='int', minimum=5, maximum=86400, raises=EFFECT_CRITICAL,
        what='How long the temperature may stay outside the storage band - '
             'without reaching a hard limit - before the excursion is called '
             'critical.',
        effect='Once the temperature has been continuously out of band this '
               'long, TEMP_EXCURSION goes CRITICAL and the diagnosis of the '
               'likely cause is attached to it.',
        basis=BASIS_PROJECT,
        source='WHO PQS E006 devices alarm after 10 continuous hours above '
               '8 °C. 90 s is a demonstration figure: the same rule, on a '
               'timescale a person watching the console can see.'),

    # -- cooling control ------------------------------------------------
    Setting(
        'COMPRESSOR_ON_ABOVE', 'Compressor starts above', '°C', 'cooling',
        minimum=-10.0, maximum=25.0, decimals=1, raises=EFFECT_CONTROL,
        what='The cabinet temperature at which the compressor is commanded on.',
        effect='No alert. Raise it and the unit runs less often and drifts '
               'warmer; the gap to the switch-off point is the hysteresis that '
               'stops the relay chattering.',
        basis=BASIS_PROJECT,
        source='A control setpoint, not a safety limit. 6.5 °C sits inside the '
               '2-8 °C band so the unit corrects itself before the band is '
               'breached rather than after.'),
    Setting(
        'COMPRESSOR_OFF_BELOW', 'Compressor stops below', '°C', 'cooling',
        minimum=-10.0, maximum=25.0, decimals=1, raises=EFFECT_CONTROL,
        what='The cabinet temperature at which the compressor is commanded off.',
        effect='No alert. Lower it and the unit overshoots colder, towards the '
               'freezing limit, on every cycle.',
        basis=BASIS_PROJECT,
        source='Chosen with the switch-on point so the whole duty cycle stays '
               'inside 2-8 °C.'),

    # -- humidity --------------------------------------------------------
    Setting(
        'HUM_TARGET_MIN', 'Humidity band, low edge', '%', 'humidity',
        minimum=0.0, maximum=100.0, decimals=0, raises=EFFECT_WARNING,
        what='Below this the air in the cabinet is dry enough to be worth '
             'noting.',
        effect='Raises a humidity WARNING.',
        basis=BASIS_PROJECT,
        source='No cold-chain standard sets a humidity band for the inside of '
               'a vaccine refrigerator. USP <797> holds classified compounding '
               'areas in the 30-60 % region, and 30 % is borrowed from it.'),
    Setting(
        'HUM_TARGET_MAX', 'Humidity band, high edge', '%', 'humidity',
        minimum=0.0, maximum=100.0, decimals=0, raises=EFFECT_WARNING,
        what='Above this the cabinet is damp enough that labels and cartons '
             'start to suffer.',
        effect='Raises a humidity WARNING.',
        basis=BASIS_PROJECT,
        source='Project figure. USP <797> caps classified areas at 60 % RH; '
               '70 % is a little looser because a cold cabinet is naturally '
               'damper than the room around it.'),
    Setting(
        'HUM_ALARM_MAX', 'Condensation limit', '%', 'humidity',
        minimum=0.0, maximum=100.0, decimals=0, raises=EFFECT_CRITICAL,
        what='The humidity at which water will condense on cold surfaces '
             'inside the cabinet.',
        effect='Raises a CRITICAL humidity alert. Condensation lifts labels, '
               'and an unreadable label is an unusable vial.',
        basis=BASIS_PROJECT,
        source='Project figure; no published cold-chain limit. 85 % is the '
               'point at which condensation on a 5 °C surface stops being '
               'hypothetical.'),

    # -- door -------------------------------------------------------------
    Setting(
        'DOOR_WARNING_SECONDS', 'Door open, warning after', 's', 'door',
        kind='int', minimum=1, maximum=3600, raises=EFFECT_WARNING,
        what='How long the door may stand open before the console says so.',
        effect='Raises the DOOR_OPEN warning. The temperature has usually not '
               'moved yet; this is the point where somebody should be told.',
        basis=BASIS_PROJECT,
        source='CDC asks that door openings be minimised but sets no time. '
               'Commercial pharmacy refrigerators typically alarm on a door '
               'left ajar around 4 minutes; 20 s here is compressed so the '
               'rule can be demonstrated.'),
    Setting(
        'DOOR_ALARM_SECONDS', 'Door open, critical after', 's', 'door',
        kind='int', minimum=2, maximum=7200, raises=EFFECT_CRITICAL,
        what='How long the door may stand open before it is an emergency.',
        effect='Escalates DOOR_OPEN to CRITICAL and, through it, the unit.',
        basis=BASIS_PROJECT,
        source='Same reasoning as the warning: compressed from the ~4 minute '
               'default of commercial units so a drill fits in a demo.'),
    Setting(
        'BADGE_VALID_SECONDS', 'Badge scan stays valid', 's', 'door',
        kind='int', minimum=5, maximum=3600, raises=EFFECT_WARNING,
        what='How long after a badge scan an opening still counts as '
             'authorised.',
        effect='A door opened with no scan inside this window raises '
               'UNAUTHORISED_ACCESS. Shorten it and more openings are '
               'flagged; lengthen it and one scan covers a longer visit.',
        basis=BASIS_PROJECT,
        source='An access-control choice, not a cold-chain one. It exists so '
               'the record can answer "who opened it", which is the question '
               'an auditor asks after an excursion.'),

    # -- probes ------------------------------------------------------------
    Setting(
        'PROBE_DISAGREE_C', 'Probes may differ by', '°C', 'probes',
        minimum=0.1, maximum=20.0, decimals=1, raises=EFFECT_CRITICAL,
        what='How far the backup thermometer may read from the main one '
             'before they are considered to disagree.',
        effect='A larger gap, held for the time below, raises a CRITICAL '
               'PROBE_MISMATCH: one of the two is lying and the system cannot '
               'tell which, so neither reading can be trusted.',
        basis=BASIS_RESEARCH,
        source='CDC requires a monitoring device with a valid, NIST-traceable '
               'calibration certificate; loggers in that class are typically '
               'specified to ±0.5 °C. Two probes 2 °C apart cannot both be '
               'within that tolerance.'),
    Setting(
        'PROBE_DISAGREE_SECONDS', 'Disagreement tolerated for', 's', 'probes',
        kind='int', minimum=1, maximum=3600, raises=EFFECT_CRITICAL,
        what='How long the two thermometers may disagree before the alert is '
             'raised.',
        effect='Stops a single odd sample, or the moment after the door '
               'closes when one probe is still catching up, from raising an '
               'alert on its own.',
        basis=BASIS_PROJECT,
        source='Project figure, chosen to be a few sample intervals: long '
               'enough to ignore a transient, short enough to catch a probe '
               'that has genuinely drifted.'),
    Setting(
        'PROBE_B_TIMEOUT_SECONDS', 'Backup probe silent for', 's', 'probes',
        kind='int', minimum=5, maximum=3600, raises=EFFECT_WARNING,
        what='How long the backup thermometer may say nothing before its '
             'silence is reported.',
        effect='Raises PROBE_B_OFFLINE as a warning. Nothing is wrong with the '
               'stock, but the unit is now running on a single unverified '
               'reading and that has to be visible.',
        basis=BASIS_PROJECT,
        source='Project figure, set to a small multiple of the publish '
               'interval so one dropped message is not mistaken for a dead '
               'probe.'),

    # -- ambient -----------------------------------------------------------
    Setting(
        'AMBIENT_WARNING_C', 'Storeroom too warm above', '°C', 'room',
        minimum=0.0, maximum=60.0, decimals=1, raises=EFFECT_WARNING,
        what='The room temperature at which the building, rather than the '
             'fridge, is the problem.',
        effect='Raises ROOM_HOT, and - more usefully - lets the diagnosis say '
               '"the storeroom is at 34 °C, this is a building cooling '
               'problem" instead of blaming the unit.',
        basis=BASIS_RESEARCH,
        source='USP <659> puts controlled room temperature at 20-25 °C. WHO '
               'PQS E003 rates refrigerators to keep 2-8 °C in ambients up to '
               '+43 °C, so 30 °C is not yet a failure - it is the point where '
               'the room has clearly left its own band.'),
    Setting(
        'AMBIENT_NOMINAL_C', 'Storeroom normal temperature', '°C', 'room',
        minimum=-20.0, maximum=50.0, decimals=1, raises=EFFECT_BASELINE,
        what='The temperature the simulated storeroom settles at, and the '
             'baseline the cabinet leaks heat from.',
        effect='No alert. It sets the thermal load on the cabinet in the '
               'simulation, so raising it makes the compressor work harder.',
        basis=BASIS_RESEARCH,
        source='The midpoint of USP <659> controlled room temperature, '
               '20-25 °C.'),
    Setting(
        'AMBIENT_TIMEOUT_SECONDS', 'Room sensor silent for', 's', 'room',
        kind='int', minimum=5, maximum=3600, raises=EFFECT_BASELINE,
        what='How long the room sensor may say nothing before its last reading '
             'is discarded.',
        effect='No alert of its own. A stale room reading is dropped rather '
               'than used, so the diagnosis never blames a room temperature '
               'nobody has measured recently.',
        basis=BASIS_PROJECT,
        source='Project figure, matched to the room sensor publish rate.'),

    # -- power -------------------------------------------------------------
    Setting(
        'BATTERY_ALARM_PERCENT', 'Battery critical below', '%', 'power',
        minimum=0.0, maximum=100.0, decimals=0, raises=EFFECT_CRITICAL,
        what='The backup battery charge at which running out stops being a '
             'possibility and becomes a schedule.',
        effect='Raises BATTERY_LOW as CRITICAL while the unit is on battery.',
        basis=BASIS_PROJECT,
        source='Project figure. WHO PQS rates refrigerators by holdover time - '
               'how long the compartment stays in band with the power off - '
               'rather than by battery percentage; 20 % is the conventional '
               '"act now" point for a backup supply.'),
    Setting(
        'BATTERY_WARNING_SECONDS', 'On battery, warn after', 's', 'power',
        kind='int', minimum=5, maximum=86400, raises=EFFECT_WARNING,
        what='How long the unit may run on backup power before it is worth '
             'reporting, however healthy the battery is.',
        effect='Raises POWER_BATTERY as a warning. A brief mains flicker is '
               'not news; an outage that is still going is.',
        basis=BASIS_PROJECT,
        source='Project figure, compressed for demonstration. Real holdover '
               'is measured in hours or days (WHO PQS E003).'),

    # -- plant -------------------------------------------------------------
    Setting(
        'CURRENT_RUNNING_MIN_A', 'Compressor is running above', 'A', 'plant',
        minimum=0.0, maximum=60.0, decimals=2, raises=EFFECT_CRITICAL,
        what='The current draw above which the compressor is judged to be '
             'actually turning.',
        effect='Commanded ON but drawing less than this raises '
               'COMPRESSOR_NO_CURRENT as CRITICAL - the relay or the motor has '
               'failed. Commanded OFF but drawing more raises '
               'COMPRESSOR_STUCK_ON: the contacts have welded closed.',
        basis=BASIS_PROJECT,
        source='An engineering figure for this simulated motor, well above '
               'sensor noise and well below its running current.'),
    Setting(
        'CURRENT_NOMINAL_A', 'Compressor normal draw', 'A', 'plant',
        minimum=0.1, maximum=60.0, decimals=1, raises=EFFECT_BASELINE,
        what='What this compressor draws when it is running properly.',
        effect='No alert. It is the reference the console shows a reading '
               'against, and what the simulated motor draws.',
        basis=BASIS_PROJECT,
        source='Nameplate figure for the simulated hardware.'),
    Setting(
        'CURRENT_OVERLOAD_A', 'Compressor overload above', 'A', 'plant',
        minimum=0.2, maximum=60.0, decimals=1, raises=EFFECT_CRITICAL,
        what='The draw at which the motor is being damaged rather than just '
             'working hard.',
        effect='Raises COMPRESSOR_OVERLOAD as CRITICAL - a seizing bearing or '
               'a stalled rotor, and the unit is about to lose its cooling '
               'altogether.',
        basis=BASIS_PROJECT,
        source='Set near twice the normal draw, the usual margin before a '
               'motor overload trips.'),
    Setting(
        'ACTUATOR_FAULT_SECONDS', 'Settling time after a command', 's', 'plant',
        kind='int', minimum=1, maximum=600, raises=EFFECT_CRITICAL,
        what='How long after a compressor or fan command the system waits '
             'before judging whether the hardware obeyed.',
        effect='Nothing is judged inside this window. A motor draws several '
               'times its running current for a second or two on start-up and '
               'coasts down slowly afterwards; without this, every cycle would '
               'report a fault.',
        basis=BASIS_PROJECT,
        source='An engineering allowance for start-up inrush and run-down, '
               'not a cold-chain figure.'),
    Setting(
        'FAN_RPM_MIN', 'Fan is turning above', 'rpm', 'plant',
        kind='int', minimum=0, maximum=10000, raises=EFFECT_CRITICAL,
        what='The speed above which the circulation fan counts as turning at '
             'all.',
        effect='Commanded ON but slower than this raises FAN_STALLED as '
               'CRITICAL: blocked or seized, and the cabinet is now stratified '
               'even though the average temperature still looks fine.',
        basis=BASIS_PROJECT,
        source='Project figure, set above the noise floor of the tachometer.'),
    Setting(
        'FAN_RPM_DEGRADED', 'Fan degraded below', 'rpm', 'plant',
        kind='int', minimum=0, maximum=10000, raises=EFFECT_WARNING,
        what='The speed below which the fan is still turning but no longer '
             'circulating properly.',
        effect='Raises FAN_DEGRADED as a warning - bearing wear. It is a '
               'request for maintenance before the failure, not after it.',
        basis=BASIS_PROJECT,
        source='Project figure, about 60 % of the fan\'s rated speed.'),
    Setting(
        'FAN_RPM_NOMINAL', 'Fan rated speed', 'rpm', 'plant',
        kind='int', minimum=1, maximum=10000, raises=EFFECT_BASELINE,
        what='The speed this fan runs at when it is healthy.',
        effect='No alert. It is the reference a reading is shown against, and '
               'the speed the simulated fan reports.',
        basis=BASIS_PROJECT,
        source='Nameplate figure for the simulated hardware.'),

    # -- liveness ----------------------------------------------------------
    Setting(
        'SENSOR_TIMEOUT_SECONDS', 'Main sensor silent for', 's', 'liveness',
        kind='int', minimum=5, maximum=3600, raises=EFFECT_CRITICAL,
        what='How long the main thermometer may say nothing before silence is '
             'treated as a failure.',
        effect='Raises SENSOR_OFFLINE as CRITICAL and stops the temperature '
               'rules running on a reading nobody is confirming. A monitor '
               'that goes quiet is not the same as a fridge that is fine.',
        basis=BASIS_PROJECT,
        source='Must be several publish intervals so one lost message is not '
               'read as a dead sensor. For reference, CDC asks only that a '
               'logger record at least every 30 minutes - a continuous system '
               'like this one can be far stricter.'),
    Setting(
        'MQTT_DOWN_SECONDS', 'Broker unreachable for', 's', 'liveness',
        kind='int', minimum=2, maximum=3600, raises=EFFECT_CRITICAL,
        what='How long the manager may be disconnected from the broker before '
             'it calls it a communications failure rather than a blip.',
        effect='Raises MQTT_DOWN as CRITICAL. Nothing about the fridge has '
               'changed - what has been lost is the ability to know, which is '
               'the same thing to an operator.',
        basis=BASIS_PROJECT,
        source='Project figure, a little longer than the client\'s reconnect '
               'backoff so an ordinary reconnect does not raise an alert.'),
]

INDEX = dict((setting.key, setting) for setting in SETTINGS)
KEYS = [setting.key for setting in SETTINGS]


def group_settings(group_key):
    return [setting for setting in SETTINGS if setting.group == group_key]


# ===========================================================================
#  Cross-field rules
# ===========================================================================
# Each entry says "left must be strictly less than right", with the sentence
# shown to the operator when it is not. These are the relations the rule engine
# depends on: a storage band whose edges have crossed over, or a compressor
# told to switch on below the temperature it switches off at, would not fail
# loudly - it would just behave nonsensically for ever.
ORDERINGS = [
    ('TEMP_ALARM_MIN', 'TEMP_TARGET_MIN',
     'The low hard limit must be below the low edge of the storage band.'),
    ('TEMP_TARGET_MIN', 'TEMP_TARGET_MAX',
     'The storage band must have its low edge below its high edge.'),
    ('TEMP_TARGET_MAX', 'TEMP_ALARM_MAX',
     'The high hard limit must be above the high edge of the storage band.'),
    ('COMPRESSOR_OFF_BELOW', 'COMPRESSOR_ON_ABOVE',
     'The compressor must switch off at a colder temperature than it switches '
     'on at, or the relay will chatter.'),
    ('TEMP_TARGET_MIN', 'COMPRESSOR_OFF_BELOW',
     'The compressor must stop before the cabinet reaches the cold edge of '
     'the storage band.'),
    ('COMPRESSOR_ON_ABOVE', 'TEMP_TARGET_MAX',
     'The compressor must start before the cabinet reaches the warm edge of '
     'the storage band, otherwise the unit can never hold the band.'),
    ('HUM_TARGET_MIN', 'HUM_TARGET_MAX',
     'The humidity band must have its low edge below its high edge.'),
    ('HUM_TARGET_MAX', 'HUM_ALARM_MAX',
     'The condensation limit must be above the top of the humidity band.'),
    ('DOOR_WARNING_SECONDS', 'DOOR_ALARM_SECONDS',
     'The door warning must come before the door alarm.'),
    ('CURRENT_RUNNING_MIN_A', 'CURRENT_NOMINAL_A',
     'The compressor cannot be judged to be running at more than its normal '
     'draw.'),
    ('CURRENT_NOMINAL_A', 'CURRENT_OVERLOAD_A',
     'The overload limit must be above the normal running current.'),
    ('FAN_RPM_MIN', 'FAN_RPM_DEGRADED',
     'A fan that is turning too slowly to count as turning cannot also be '
     'merely degraded.'),
    ('FAN_RPM_DEGRADED', 'FAN_RPM_NOMINAL',
     'The degraded speed must be below the fan\'s rated speed.'),
    ('AMBIENT_NOMINAL_C', 'AMBIENT_WARNING_C',
     'The storeroom warning must be above its normal temperature, or it would '
     'be raised permanently.'),
]


def config_module():
    """The config module the thresholds live on.

    Looked up through ``sys.modules`` first because ``mqtt_init`` calls into
    this module while it is still being imported: at that point the module
    object exists and every threshold is defined on it, but the import machinery
    has not yet bound the name in the package.
    """
    module = sys.modules.get('config.mqtt_init')
    if module is None:
        from config import mqtt_init as module
    return module


def _extra_checks(values, errors):
    """Relations that are not a plain "a < b"."""
    low = values.get('TEMP_TARGET_MIN')
    high = values.get('TEMP_TARGET_MAX')
    margin = values.get('TEMP_APPROACH_MARGIN')
    if None not in (low, high, margin) and margin > 0:
        if margin * 2 >= (high - low):
            errors['TEMP_APPROACH_MARGIN'] = (
                'The margin covers the whole storage band (%.1f °C wide), so '
                'every in-band reading would be "approaching". Keep it under '
                '%.1f °C.' % (high - low, (high - low) / 2.0))

    # Silence has to be judged over several samples, or a single dropped
    # message becomes an offline sensor.
    sample = max(1.0, config_module().SENSOR_PUBLISH_MS / 1000.0)
    for key in ('SENSOR_TIMEOUT_SECONDS', 'PROBE_B_TIMEOUT_SECONDS',
                'AMBIENT_TIMEOUT_SECONDS'):
        value = values.get(key)
        if value is not None and value < sample * 2:
            errors[key] = ('Sensors publish every %.0f s, so anything under '
                           '%.0f s would report a fault every time one message '
                           'is late.' % (sample, sample * 2))


def validate(raw):
    """Check a full set of proposed values.

    ``raw`` maps keys to whatever the operator typed. Returns
    ``(clean, errors)``: the coerced values, and a key -> sentence map of
    everything wrong with them. ``clean`` holds an entry for every key that
    parsed, so the cross-field rules can be checked on what is left.
    """
    clean = {}
    errors = {}
    for key, value in raw.items():
        setting = INDEX.get(key)
        if setting is None:
            continue
        text = value.strip() if isinstance(value, str) else value
        if text == '' or text is None:
            errors[key] = 'This cannot be left empty.'
            continue
        try:
            number = setting.coerce(text)
        except (TypeError, ValueError):
            errors[key] = ('Enter a number%s.'
                           % (' with no decimal point' if setting.kind == 'int'
                              else ''))
            continue
        if number < setting.minimum or number > setting.maximum:
            errors[key] = ('Out of range. This setting accepts %s.'
                           % setting.range_text())
            continue
        clean[key] = number

    _apply_orderings(clean, errors)
    _extra_checks(clean, errors)
    return clean, errors


def _apply_orderings(values, errors):
    for low_key, high_key, message in ORDERINGS:
        low = values.get(low_key)
        high = values.get(high_key)
        if low is None or high is None:
            continue
        if low >= high:
            # Reported on both ends: the operator changed one of them, and
            # either one is a legitimate place to fix it.
            errors.setdefault(low_key, message)
            errors.setdefault(high_key, message)


# ===========================================================================
#  Persistence
# ===========================================================================
RECOMMENDED = {}        # key -> the literal declared in mqtt_init
_ready = False


def capture_defaults(module):
    """Record the values a module declares as the recommended defaults.

    Called by ``mqtt_init`` on itself, before any override is applied, so the
    literals in that file stay the single source of the recommended values and
    cannot drift out of step with this catalogue.
    """
    for key in KEYS:
        if hasattr(module, key):
            RECOMMENDED[key] = getattr(module, key)
    missing = [key for key in KEYS if key not in RECOMMENDED]
    if missing:
        # A typo in a key would otherwise show up as a silently dead control.
        print('settings | no such threshold in mqtt_init: %s'
              % ', '.join(missing))
    return dict(RECOMMENDED)


def ensure_ready():
    """Make sure the defaults have been captured, importing mqtt_init if not."""
    global _ready
    if not _ready:
        _ready = True
        config_module()      # importing it populates RECOMMENDED
    return RECOMMENDED


def load():
    """Read the saved overrides. A missing or damaged file means "defaults"."""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError) as error:
        print('settings | ignoring unreadable %s (%s)' % (SETTINGS_FILE, error))
        return {}

    stored = data.get('values') if isinstance(data, dict) else None
    if not isinstance(stored, dict):
        print('settings | ignoring %s: no values block' % SETTINGS_FILE)
        return {}

    # A file written by hand, or by an older version, must not be able to put
    # an impossible number into the rule engine. The saved keys are checked as
    # part of a complete set - the recommended defaults standing in for
    # anything the file does not mention - because the relations that matter
    # here run between settings, and half a set proves nothing.
    ensure_ready()
    proposed = dict(RECOMMENDED)
    saved_keys = [key for key in stored if key in INDEX]
    proposed.update(dict((key, stored[key]) for key in saved_keys))

    clean, errors = validate(proposed)
    for key in sorted(errors):
        if key in saved_keys:
            print('settings | ignoring saved %s: %s' % (key, errors[key]))
        clean.pop(key, None)
    return dict((key, clean[key]) for key in saved_keys if key in clean)


def save(values):
    """Write the overrides, atomically so a crash cannot leave half a file."""
    payload = {
        'version': FILE_VERSION,
        'note': 'Thresholds set from the console. Delete this file to return '
                'to the recommended defaults.',
        'values': dict((key, values[key]) for key in KEYS if key in values),
    }
    directory = os.path.dirname(SETTINGS_FILE)
    handle, temporary = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write('\n')
        # os.replace, not os.rename: the two behave the same on POSIX, but on
        # Windows rename refuses to overwrite and raises WinError 183, so the
        # first save here would succeed and every save after it would fail.
        # replace overwrites atomically on both.
        os.replace(temporary, SETTINGS_FILE)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return SETTINGS_FILE


def clear():
    """Forget every override, so the recommended defaults apply again."""
    if os.path.exists(SETTINGS_FILE):
        os.remove(SETTINGS_FILE)


# ===========================================================================
#  Applying
# ===========================================================================
def apply_to(module, values):
    """Write values onto a config module. Returns the keys that changed.

    Nothing here validates: callers pass values that came from :func:`validate`
    or from a file that has been through it.
    """
    changed = []
    for key, value in values.items():
        setting = INDEX.get(key)
        if setting is None:
            continue
        try:
            number = setting.coerce(value)
        except (TypeError, ValueError):
            continue
        if getattr(module, key, None) != number:
            setattr(module, key, number)
            changed.append(key)
    return changed


def apply_saved(module):
    """Overlay the saved file onto a config module, at import time."""
    saved = load()
    if saved:
        apply_to(module, saved)
    return saved


def effective(module=None):
    """The value every threshold currently has."""
    ensure_ready()
    if module is None:
        module = config_module()
    return dict((key, getattr(module, key)) for key in KEYS
                if hasattr(module, key))


def overrides(module=None):
    """Only the thresholds that differ from the recommended default."""
    ensure_ready()
    current = effective(module)
    return dict((key, value) for key, value in current.items()
                if RECOMMENDED.get(key) != value)


def describe(values, previous=None):
    """One line per change, for the event log."""
    ensure_ready()
    previous = previous or {}
    lines = []
    for key in KEYS:
        if key not in values:
            continue
        setting = INDEX[key]
        new = values[key]
        old = previous.get(key)
        if old is None or old == new:
            continue
        lines.append('%s %s -> %s' % (setting.label, setting.format(old),
                                      setting.format(new)))
    return lines
