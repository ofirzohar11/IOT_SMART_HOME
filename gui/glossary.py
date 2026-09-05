"""Plain-language glossary for the operator console.

The console is used by pharmacy and warehouse staff, so every technical term on
screen needs a non-technical twin: what the thing is, why anyone should care,
what a normal value looks like, and - when something is wrong - what to do
about it. All of that wording lives here, in one file, for two reasons:

* the same sensor is named on five screens, and the names have to agree;
* the numbers quoted in the explanations are read from ``mqtt_init``, so a
  threshold change cannot leave the help text quietly lying about it.

Nothing here is used by the emulators or the data manager. It is console copy,
and the technical labels in ``config/devices.py`` are left untouched so the
device registry stays the single source of truth for the system itself.
"""

from config import mqtt_init as cfg
from ui.help import Explain

TARGET = '%.0f-%.0f °C' % (cfg.TEMP_TARGET_MIN, cfg.TEMP_TARGET_MAX)
HARD = '%.0f-%.0f °C' % (cfg.TEMP_ALARM_MIN, cfg.TEMP_ALARM_MAX)


# ===========================================================================
#  Devices - keyed by the id in config/devices.py
# ===========================================================================
DEVICES = {
    'temp': Explain(
        'Main thermometer',
        'Measures the air temperature inside the fridge, next to the stock.',
        'This is the reading the whole system exists to protect. Every cooling '
        'decision and almost every alarm starts from it.',
        '%s. A warning is raised outside that band and a critical alarm '
        'outside %s.' % (TARGET, HARD),
        note='Device "temp" · Temperature Probe A · publishes every '
                  '%.0f s with humidity.' % (cfg.SENSOR_PUBLISH_MS / 1000.0),
    ),
    'temp_b': Explain(
        'Backup thermometer',
        'A second, independent thermometer in the same fridge.',
        'A single probe can drift for weeks without anyone noticing. If the two '
        'thermometers disagree, one of them is lying - and the system says so '
        'instead of trusting the wrong number.',
        'Within %.0f °C of the main thermometer.' % cfg.PROBE_DISAGREE_C,
        note='Device "temp_b" · Temperature Probe B · disagreement is '
                  'alarmed after %d s.' % cfg.PROBE_DISAGREE_SECONDS,
    ),
    'ambient': Explain(
        'Room temperature',
        'Measures the storeroom air outside the fridge.',
        'It answers whose problem a warm fridge is. A hot room means the '
        'building cooling has failed, which is a facilities call - not a '
        'refrigeration engineer.',
        'Below %.0f °C.' % cfg.AMBIENT_WARNING_C,
        note='Device "ambient" · Ambient Room Sensor.',
    ),
    'door': Explain(
        'Door sensor',
        'A magnetic switch that reports whether the fridge door is open or shut.',
        'A door left open is the most common cause of a temperature excursion, '
        'and the cheapest one to prevent.',
        'CLOSED. A warning after %d s open, a critical alarm after %d s.'
        % (cfg.DOOR_WARNING_SECONDS, cfg.DOOR_ALARM_SECONDS),
        note='Device "door" · retained OPEN / CLOSED state.',
    ),
    'badge': Explain(
        'Staff badge reader',
        'Reads the ID badge of whoever opens the fridge.',
        'Regulated storage has to record who touched the stock and when. An '
        'opening with no badge is logged as unauthorised access.',
        'A known staff name appears every time the door opens.',
        note='Device "badge" · a badge counts for %d s after the scan.'
                  % cfg.BADGE_VALID_SECONDS,
    ),
    'power': Explain(
        'Power and battery',
        'Reports whether the unit is running on mains electricity or its backup '
        'battery, and how much charge is left.',
        'When the battery runs out, both the cooling and the monitoring stop. '
        'The battery is the clock you are racing during a power cut.',
        'MAINS, with the battery above %.0f %%.' % cfg.BATTERY_ALARM_PERCENT,
        note='Device "power" · battery-run warning after %d s.'
                  % cfg.BATTERY_WARNING_SECONDS,
    ),
    'current': Explain(
        'Cooling motor power draw',
        'A clamp meter around the compressor cable, measuring the electricity '
        'the motor really uses.',
        'A switch can report ON while the motor is dead. Current is the proof '
        'that cooling is actually happening rather than merely commanded.',
        'About %.1f A while cooling, near 0 A when off. Above %.0f A is an '
        'overload.' % (cfg.CURRENT_NOMINAL_A, cfg.CURRENT_OVERLOAD_A),
        note='Device "current" · Compressor Current Sensor · judged %d s '
                  'after a command.' % cfg.ACTUATOR_FAULT_SECONDS,
    ),
    'fan_rpm': Explain(
        'Fan speed sensor',
        'Counts how fast the circulation fan is really turning.',
        'Without circulation the cold pools in one corner: the probe can read '
        'perfectly while the far end of the shelf spoils. Nothing else in the '
        'system would catch that.',
        'About %d rpm while running. Below %d rpm counts as stalled.'
        % (cfg.FAN_RPM_NOMINAL, cfg.FAN_RPM_MIN),
        note='Device "fan_rpm" · Fan Tachometer · degraded below %d rpm.'
                  % cfg.FAN_RPM_DEGRADED,
    ),
    'compressor': Explain(
        'Cooling switch',
        'The relay that switches the cooling motor on and off.',
        'This is the command. Whether the motor obeyed it is answered by the '
        'cooling motor power draw beside it.',
        'Switches on above %.1f °C and off below %.1f °C.'
        % (cfg.COMPRESSOR_ON_ABOVE, cfg.COMPRESSOR_OFF_BELOW),
        note='Device "compressor" · Compressor Relay.',
    ),
    'fan': Explain(
        'Fan switch',
        'The relay that switches the circulation fan on and off.',
        'The fan spreads the cold air evenly through the cabinet, so it runs '
        'whenever the cooling does.',
        'Runs alongside the cooling motor.',
        note='Device "fan" · Fan Relay.',
    ),
    'siren': Explain(
        'Alarm sounder',
        'The audible alarm in the storeroom.',
        'The console can only be seen by somebody looking at it. The sounder is '
        'what fetches a person who is not.',
        'Silent. It sounds whenever a critical condition is active.',
        note='Device "siren" · Siren Relay.',
    ),
}


# ===========================================================================
#  Readings and controls on the dashboard
# ===========================================================================
METRICS = {
    'temperature': Explain(
        'Fridge temperature',
        'The air temperature inside the fridge, from the main thermometer.',
        'Medicines and vaccines lose potency outside their storage band, and '
        'the loss cannot be seen or undone.',
        '%s. The green band on the dial is the safe range; the red marks are '
        'the hard limits at %s.' % (TARGET, HARD),
    ),
    'humidity': Explain(
        'Air humidity',
        'How much moisture is in the air inside the fridge.',
        'Damp air condenses on packaging and destroys labels and cartons; very '
        'dry air damages some preparations.',
        '%.0f-%.0f %%. A critical alarm above %.0f %%.'
        % (cfg.HUM_TARGET_MIN, cfg.HUM_TARGET_MAX, cfg.HUM_ALARM_MAX),
    ),
    'probe_delta': Explain(
        'Difference between the two thermometers',
        'How far apart the main and backup thermometers are reading.',
        'Two probes that agree can be trusted. Two that disagree mean one is '
        'faulty, and the system stops trusting either.',
        'Under %.0f °C apart.' % cfg.PROBE_DISAGREE_C,
    ),
    'operator': Explain(
        'Last opened by',
        'The staff member whose badge was read when the door was last opened.',
        'It closes the loop between a temperature excursion and the person who '
        'can explain it.',
        'A name. "No badge" means somebody opened the door without scanning.',
    ),
    'excursion': Explain(
        'Temperature excursion',
        'A spell where the temperature stayed outside the safe band '
        'continuously for more than %d seconds.' % cfg.EXCURSION_ALARM_SECONDS,
        'A door opened for a moment is normal. A sustained excursion is the '
        'event a pharmacy audit asks about, and it may condemn the stock.',
        'Zero minutes.',
    ),
}


# ===========================================================================
#  Terms the console uses
# ===========================================================================
TERMS = {
    'commanded': Explain(
        'Commanded state',
        'What the system told this piece of equipment to do.',
        'A command is only an intention. On its own it proves nothing about '
        'what the hardware did.',
    ),
    'measured': Explain(
        'Measured state',
        'What an independent sensor says the equipment is really doing.',
        'This is the half that catches a welded relay, a seized motor or a '
        'stalled fan - failures that a command alone always reports as fine.',
        'Measured and commanded agree.',
    ),
    'health': Explain(
        'Device health',
        'How well each device is reporting: Connected (on schedule), Degraded '
        '(reporting, but something is wrong), Fault (its readings contradict '
        'what the equipment should be doing), Offline (stopped reporting), '
        'Maintenance (deliberately excused while it is serviced).',
        'An offline sensor is not a quiet sensor - it is an unmonitored fridge.',
        'All devices Connected.',
    ),
    'incident': Explain(
        'Incident',
        'A problem the system has opened a case for. It stays open until the '
        'condition goes away or somebody resolves it.',
        'Alerts scroll past; an incident is the thing somebody has to own, and '
        'it keeps a record of who acknowledged it and when.',
    ),
    'acknowledge': Explain(
        'Acknowledge',
        'Says "I have seen this and I am dealing with it". Your name is stored '
        'against the incident.',
        'It tells the next person that the problem already has an owner.',
        note='The condition itself is unaffected - the alarm stays until it is '
             'actually fixed.',
    ),
    'resolve': Explain(
        'Resolve',
        'Closes the incident.',
        'Closing a case that is not really fixed hides a live problem, so the '
        'system re-opens it within a second if the condition is still true.',
    ),
    'maintenance': Explain(
        'Maintenance mode',
        'A servicing mode. Conditions are still measured, judged and recorded, '
        'but the unit stops escalating to alarms and parks the equipment off.',
        'It stops a service visit generating a wall of alarms - without ever '
        'blinding the record, which still shows everything that happened.',
        note='Leave maintenance mode as soon as servicing is finished.',
    ),
    'simulated': Explain(
        'Simulated',
        'This condition was produced by a fault deliberately armed on the '
        'Simulations page.',
        'Drills prove the alarms work. Labelling every simulated result keeps a '
        'drill from ever being mistaken for a real failure in the record.',
    ),
    'connection': Explain(
        'Connection to the monitoring network',
        'Whether this console is receiving live messages from the unit.',
        'If the link is down the screen may be showing you the past. The unit '
        'keeps cooling, but nobody is watching it.',
        'Connected.',
    ),
}


# ===========================================================================
#  Alerts - what happened, why it matters, what to do about it
# ===========================================================================
def _alert(name, what, why, action):
    return Explain(name, what, why, action=action)


ALERTS = {
    'TEMP_RANGE': _alert(
        'Temperature outside the safe range',
        'The fridge is no longer between %s.' % TARGET,
        'Stock held outside its storage band starts losing potency, and the '
        'damage is invisible.',
        'Check the door is properly shut. Then look at the Cooling switch on '
        'the Dashboard: if it is on but drawing no current, call a '
        'refrigeration engineer.'),
    'TEMP_APPROACHING': _alert(
        'Temperature drifting towards the limit',
        'The reading is still inside %s but is close to the edge.' % TARGET,
        'It is the early warning that lets somebody act before stock is at '
        'risk rather than afterwards.',
        'Nothing is damaged yet. Check whether the door has just been used, '
        'and watch the trend for a few minutes.'),
    'TEMP_EXCURSION': _alert(
        'Sustained temperature excursion',
        'The temperature has stayed outside the safe band continuously for '
        'more than %d seconds.' % cfg.EXCURSION_ALARM_SECONDS,
        'A brief opening is tolerable; a sustained excursion is the event that '
        'may condemn the stock, and the one an audit will ask about.',
        'Treat the stock as suspect and record the excursion. If it continues, '
        'move the product to a working unit.'),
    'HUM_RANGE': _alert(
        'Humidity outside the safe range',
        'The air inside the fridge is too damp or too dry.',
        'Condensation ruins packaging and labelling; very dry air damages some '
        'preparations.',
        'Check for a door left ajar or standing water near the unit.'),
    'SENSOR_OFFLINE': _alert(
        'Main thermometer has stopped reporting',
        'No reading has arrived from the main probe for more than %d seconds.'
        % cfg.SENSOR_TIMEOUT_SECONDS,
        'The fridge is now unmonitored. It may be perfectly cold or ruining '
        'its contents, and nothing on this screen can tell you which.',
        'Treat the unit as unmonitored. Check the probe power and network, and '
        'verify the temperature with a hand thermometer meanwhile.'),
    'PROBE_MISMATCH': _alert(
        'The two thermometers disagree',
        'The main and backup probes have differed by more than %.0f °C for '
        'over %d seconds.' % (cfg.PROBE_DISAGREE_C, cfg.PROBE_DISAGREE_SECONDS),
        'One of them is wrong, and there is no way to tell which from here. '
        'Every decision made on the displayed temperature is now unsafe.',
        'Do not trust either reading. Verify with a calibrated thermometer and '
        'book a probe calibration.'),
    'PROBE_B_OFFLINE': _alert(
        'Backup thermometer has stopped reporting',
        'The redundant probe is silent, so the cross-check is gone.',
        'Monitoring continues on one probe alone - a drift in that probe would '
        'no longer be caught by anything.',
        'Book service for the backup probe. Normal monitoring continues in the '
        'meantime.'),
    'ROOM_HOT': _alert(
        'The storeroom is too warm',
        'The room around the fridge is above %.0f °C.' % cfg.AMBIENT_WARNING_C,
        'A hot room eventually beats any fridge. This is a building cooling '
        'problem, not a fault in this unit.',
        'Report it to facilities or building maintenance and ask them to check '
        'the room air conditioning.'),
    'COMPRESSOR_NO_CURRENT': _alert(
        'Cooling motor is not running',
        'The motor was switched on but is drawing no electricity.',
        'Nothing is being cooled. The temperature will climb until somebody '
        'intervenes, however healthy the switch looks.',
        'Call a refrigeration engineer - most likely a burnt contact or a '
        'seized motor. Be ready to move the stock.'),
    'COMPRESSOR_STUCK_ON': _alert(
        'Cooling motor will not switch off',
        'The motor was commanded off but is still drawing current, which means '
        'the relay contacts have welded shut.',
        'The cooling cannot be stopped, so the stock can be frozen - which for '
        'many medicines is as damaging as being too warm.',
        'Isolate the unit at the breaker and call an engineer. Check the stock '
        'for signs of freezing.'),
    'COMPRESSOR_OVERLOAD': _alert(
        'Cooling motor is overloading',
        'The motor is drawing more than %.0f A, far above its rated draw.'
        % cfg.CURRENT_OVERLOAD_A,
        'It is a warning of imminent failure, and a risk of tripping the '
        'breaker or overheating the wiring.',
        'Call maintenance now. Do not reset the breaker repeatedly.'),
    'FAN_STALLED': _alert(
        'Circulation fan is not turning',
        'The fan was switched on but the tachometer reads a standstill.',
        'Cold air stops circulating. The probe can keep reading a perfect '
        'temperature while the far end of the shelf warms up unseen.',
        'Call maintenance and do not rely on the displayed temperature until '
        'the fan runs again.'),
    'FAN_DEGRADED': _alert(
        'Circulation fan is running slowly',
        'The fan turns, but below %d rpm - typically a worn bearing.'
        % cfg.FAN_RPM_DEGRADED,
        'Air is still moving, so nothing is at risk yet, but the bearing is on '
        'its way to a full stall.',
        'Book a service visit. No immediate action is needed.'),
    'FAN_STUCK_ON': _alert(
        'Circulation fan will not stop',
        'The fan keeps turning after being switched off.',
        'It wastes energy and adds a little heat, but the stock is not at risk.',
        'Note it for the next service visit.'),
    'DOOR_OPEN': _alert(
        'Door has been left open',
        'The fridge door has been open longer than %d seconds.'
        % cfg.DOOR_WARNING_SECONDS,
        'An open door is the fastest way to lose the safe temperature, and the '
        'easiest problem on this screen to fix.',
        'Close the door. Check nothing is caught in the seal.'),
    'UNAUTHORISED_ACCESS': _alert(
        'Door opened without a badge',
        'The door was opened but no valid staff badge was presented.',
        'Regulated storage has to be able to name whoever accessed the stock. '
        'An unattributed opening is a gap in that record.',
        'Find out who opened the unit and record it. Remind staff to badge in '
        'before opening the door.'),
    'POWER_BATTERY': _alert(
        'Running on backup battery',
        'Mains power has been lost and the unit is on its battery.',
        'Cooling and monitoring both continue only while the charge lasts.',
        'Check the plug and the breaker. If mains cannot be restored quickly, '
        'plan to move the stock.'),
    'BATTERY_LOW': _alert(
        'Backup battery is nearly empty',
        'The battery has fallen below %.0f %%.' % cfg.BATTERY_ALARM_PERCENT,
        'When it empties, the cooling stops and so does every reading on this '
        'screen.',
        'Restore mains power now, or move the stock to a powered unit.'),
    'MQTT_DOWN': _alert(
        'Lost connection to the monitoring network',
        'The unit has been unable to reach the message broker for more than '
        '%d seconds.' % cfg.MQTT_DOWN_SECONDS,
        'The unit keeps cooling, but readings are not reaching anybody. The '
        'fridge is effectively unwatched.',
        'Check the network connection. Verify the temperature locally until '
        'the link returns.'),
    'DEVICE_STALE': _alert(
        'A device has stopped reporting',
        'One or more sensors have missed several of their scheduled messages.',
        'Each silent sensor is one check the system can no longer perform.',
        'Open the Devices page to see which device is offline, then check its '
        'power and connection.'),
    'BADGE_REJECTED': _alert(
        'Badge not recognised',
        'A badge was presented that is not on the staff list.',
        'Either somebody without authorisation tried to open the unit, or a '
        'legitimate badge has not been registered.',
        'Check who was at the unit and whether their badge needs registering.'),
    'BADGE_SCAN': _alert(
        'Badge accepted',
        'A staff badge was read at the door.',
        'It is the record of who opened the fridge.',
        'No action needed.'),
    'MODE': _alert(
        'Operating mode changed',
        'The unit was switched between normal monitoring and maintenance mode.',
        'Maintenance mode stops alarms escalating, so it matters that the '
        'change is recorded and does not outlast the service visit.',
        'No action needed, but leave maintenance mode when servicing ends.'),
}

GENERIC_ALERT = _alert(
    'System event',
    'A condition the monitoring rules reported.',
    'Everything the system judges is recorded, whether or not it needs action.',
    'Read the message below for the detail.')


# ===========================================================================
#  Health states and lookups
# ===========================================================================
HEALTH = {
    'CONNECTED': Explain(
        'Connected',
        'The device is reporting on schedule and its readings make sense.',
        normal='Every device should sit here.'),
    'DEGRADED': Explain(
        'Degraded',
        'Still reporting, but something is wrong: a warning is open against it, '
        'or a simulated fault is armed on it.',
        'It still works, but it is no longer fully trustworthy.'),
    'FAULT': Explain(
        'Fault',
        'The device is reporting, but a critical condition is open against it - '
        'usually its measurement contradicting what the equipment was told.',
        'This is the state that catches hardware lying about itself.'),
    'OFFLINE': Explain(
        'Offline',
        'The device has missed roughly three of its scheduled messages.',
        'A silent sensor is not a quiet one. Whatever it was checking is no '
        'longer being checked at all.'),
    'MAINTENANCE': Explain(
        'Maintenance',
        'The unit is in maintenance mode, so this device is deliberately '
        'excused from escalating alarms.',
        'It keeps a service visit from filling the log with alarms nobody '
        'needs to answer.'),
}

GROUPS = {
    'Cabinet': 'Inside the fridge - what the stock actually experiences.',
    'Plant': 'The cooling machinery, and the sensors that check it obeyed.',
    'Facility': 'The room and the power supply the fridge depends on.',
}


def device(device_id):
    return DEVICES.get(device_id)


def metric(key):
    return METRICS.get(key)


def term(key):
    return TERMS.get(key)


def health(state):
    return HEALTH.get(state)


def alert(code):
    """Explain an alert code, tolerating the ``_CLEARED`` suffix."""
    if not code:
        return GENERIC_ALERT
    if code.endswith('_CLEARED'):
        base = ALERTS.get(code[:-len('_CLEARED')])
        if base:
            return Explain('%s - now resolved' % base.name,
                           'This condition has cleared on its own.',
                           base.why, action='No action needed.')
    return ALERTS.get(code, GENERIC_ALERT)


def device_name(device_id, fallback=''):
    """The plain-language name for a device, for use in body text."""
    entry = DEVICES.get(device_id)
    return entry.name if entry else fallback
