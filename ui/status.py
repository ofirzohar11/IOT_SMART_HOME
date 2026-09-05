"""The console's one status vocabulary.

Before this module the screen spoke three dialects at once. An alert had a
*level* (INFO / WARNING / CRITICAL), a device had a *health* (CONNECTED /
DEGRADED / MAINTENANCE / FAULT / OFFLINE), and a simulated fault was a fourth
thing again - each with its own colour lookup, its own glyph and its own
wording. The same condition therefore looked different depending on which card
it happened to appear on.

Everything now resolves to one of six states:

    NORMAL   WARNING   CRITICAL   OFFLINE   MAINTENANCE   SIMULATED

Each carries a word, a painted mark and a colour, in that order of importance.
The word and the mark are what actually communicate the state; the colour only
reinforces them, so the console stays readable to somebody who cannot separate
red from green, and on a printout.

The underlying data is untouched: alerts still carry a level and devices still
carry a health. This is the presentation layer that both of them map onto.
"""

from ui import theme as t

NORMAL = 'NORMAL'
WARNING = 'WARNING'
CRITICAL = 'CRITICAL'
OFFLINE = 'OFFLINE'
MAINTENANCE = 'MAINTENANCE'
SIMULATED = 'SIMULATED'

STATES = (NORMAL, WARNING, CRITICAL, OFFLINE, MAINTENANCE, SIMULATED)


class State(object):
    """One status: the word, the mark, the colour and what it means."""

    def __init__(self, key, label, mark, color, rank, what, why=''):
        self.key = key
        self.label = label      # the word shown to the operator
        self.mark = mark        # an icon name in ui.icons
        self.color = color
        self.rank = rank        # how loudly it should shout; higher wins
        self.what = what
        self.why = why

    def __repr__(self):
        return 'State(%s)' % self.key


STATE = {
    NORMAL: State(
        NORMAL, 'Normal', 'mark_normal', t.OK, 0,
        'Reporting on schedule and inside its expected range.',
        'Nothing to do.'),
    WARNING: State(
        WARNING, 'Warning', 'mark_warning', t.WARN, 2,
        'Still working, but something is outside its expected range.',
        'The early notice that lets somebody fix a problem before the stock '
        'is affected.'),
    CRITICAL: State(
        CRITICAL, 'Critical', 'mark_critical', t.CRITICAL, 4,
        'The stock is at risk right now, or a device is contradicting what '
        'the equipment was told to do.',
        'Somebody has to act immediately. A critical condition also sounds '
        'the alarm in the storeroom.'),
    OFFLINE: State(
        OFFLINE, 'Offline', 'mark_offline', t.OFFLINE_FG, 3,
        'It has stopped reporting.',
        'A device that has gone quiet is not a device that is fine - whatever '
        'it was checking is no longer being checked.'),
    MAINTENANCE: State(
        MAINTENANCE, 'Maintenance', 'mark_maintenance', t.ACCENT, 1,
        'Deliberately excused from alarming while the unit is serviced.',
        'Conditions are still measured and recorded; they just do not '
        'escalate. Leave maintenance as soon as servicing is finished.'),
    SIMULATED: State(
        SIMULATED, 'Simulated', 'mark_simulated', t.SIM, 1,
        'Caused by a fault armed on purpose from the Simulations page.',
        'A drill proves the alarms work. Everything a drill causes is '
        'labelled this way so it is never mistaken for a real failure.'),
}


# --------------------------------------------------------------------------
#  Mapping the existing vocabularies onto the six
# --------------------------------------------------------------------------
# Alert severities, including the pre-rename 'ALARM' rows still in old
# databases.
FROM_LEVEL = {
    'INFO': NORMAL,
    'WARNING': WARNING,
    'CRITICAL': CRITICAL,
    'ALARM': CRITICAL,
}

# Device health as the data manager reports it.
FROM_HEALTH = {
    'CONNECTED': NORMAL,
    'DEGRADED': WARNING,
    'FAULT': CRITICAL,
    'OFFLINE': OFFLINE,
    'MAINTENANCE': MAINTENANCE,
}

# The engineering term stays reachable in the tooltip, so a device page can
# still say precisely which of the five health states produced this status.
HEALTH_TERMS = {
    'CONNECTED': 'Connected - reporting on schedule.',
    'DEGRADED': 'Degraded - still reporting, but something is wrong.',
    'FAULT': 'Fault - its readings contradict what the equipment was told '
             'to do.',
    'OFFLINE': 'Offline - it has stopped reporting.',
    'MAINTENANCE': 'Maintenance - excused while the unit is serviced.',
}


def from_level(level):
    return FROM_LEVEL.get(level, NORMAL)


def from_health(health):
    return FROM_HEALTH.get(health, OFFLINE)


def get(state):
    return STATE.get(state, STATE[OFFLINE])


def label(state):
    return get(state).label


def mark(state):
    return get(state).mark


def color(state):
    return get(state).color


def rank(state):
    return get(state).rank


def worst(*states):
    """The state that should be shown when several apply at once."""
    candidates = [s for s in states if s]
    if not candidates:
        return NORMAL
    return max(candidates, key=rank)


def tooltip(state, title=None, extra=''):
    """The standard explanation for a status, for any chip or pill."""
    from ui import help as h
    entry = get(state)
    return h.tooltip_html(title or ('Status: %s' % entry.label), entry.what,
                          entry.why, note=extra)
