# Running the Cold Chain Monitor

Installation, launch, a demo walkthrough, and fixes for the problems you are
most likely to hit.

For what the system *is* and how it works, see [README.md](README.md).

---

## 1. Requirements

* **Python 3.8 or newer**
* An internet connection — the default broker is the public HiveMQ server
* Two Python packages, installed below: `PyQt5` and `paho-mqtt`

Check your Python:

```bash
python3 --version
```

On Windows, use `py -3` instead of `python3` in every command on this page.
`py` is the launcher that every python.org installer puts on PATH. Plain
`python` is on PATH only if you ticked **Add python.exe to PATH** during the
install; when you did not, Windows answers that name with a Microsoft Store
stub that exits without running anything.

---

## 2. Installation

Work inside a virtual environment so the project's packages stay separate from
the rest of your system.

### macOS / Linux

Open a terminal in the project folder:

```bash
cd path/to/ColdChainMonitor
```

Create the environment:

```bash
python3 -m venv .venv
```

Install the dependencies into it:

```bash
.venv/bin/pip install -r requirements.txt
```

Verify:

```bash
.venv/bin/python -c "import PyQt5, paho.mqtt; print('dependencies OK')"
```

### Windows

You can skip this section. `run\windows\start_panel.bat` finds Python, offers to
build `.venv` and installs both packages the first time you run it. To do it by
hand anyway:

```
cd path\to\ColdChainMonitor
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Verify:

```
.venv\Scripts\python -c "import PyQt5, paho.mqtt; print('dependencies OK')"
```

> `.venv/` is listed in `.gitignore`, so it never reaches the repository.

---

## 3. Starting everything

There are two layouts. They run identical device code and open identical MQTT
connections — eleven clients with eleven distinct client ids either way. Only the
number of windows differs.

| Mode | Processes | Windows | Best for |
|---|---|---|---|
| Separate | 13 | 13 | Showing the architecture — one process per device, like real hardware |
| Device panel | 3 | 2 | Demonstrating and recording |

Thirteen windows is a lot to arrange. Use the device panel unless you are
specifically demonstrating that the devices are independent processes.

The launchers live in `run/`, one folder per platform:

```
run/
├── macos/
│   ├── start_all.command      one window per device
│   └── start_panel.command    all devices in one window
└── windows/
    ├── start_all.bat          one window per device
    └── start_panel.bat        all devices in one window
```

Each launcher finds the project root by itself, and uses `.venv` automatically
if it exists. You do not need to `cd` anywhere or activate anything.

### macOS

**Double-click** `run/macos/start_panel.command` in Finder. Terminal opens and
everything starts.

Or from a terminal:

```bash
run/macos/start_panel.command
```

```bash
run/macos/start_all.command
```

`Ctrl-C` in that terminal stops every component at once.

> **First time only.** If you downloaded this project rather than cloning it,
> macOS refuses to open the `.command` file: *"Apple could not verify
> start_panel.command is free of malware."* Clear the download flag once, from
> the project folder:
>
> ```bash
> xattr -d com.apple.quarantine run/macos/*.command run/macos/*.sh
> ```
>
> Then the double-click works. Running the file from a terminal instead needs
> nothing - Gatekeeper only guards the Finder double-click.

### Windows

**Double-click** `run\windows\start_panel.bat`, or from a command prompt:

```
run\windows\start_panel.bat
```

```
run\windows\start_all.bat
```

Each component opens in its own console window; close them to stop.

> **First time only.** If the dependencies are not installed yet, the launcher
> says so and offers to install them:
>
> ```
> Install them into .venv now? [Y/n]
> ```
>
> Press Return. It builds `.venv` and installs both packages, then starts the
> system. Later runs skip straight to the launch.

### Using a different interpreter

Both launchers respect a `PYTHON` variable if you want to override the automatic
choice:

```bash
PYTHON=/usr/local/bin/python3.11 run/macos/start_all.command
```

### Which one to record

Use `start_panel`. Two windows — the device panel and the console — fit side by
side on one screen, so every fault you arm and its effect on the dashboard are
visible in the same frame.

![Device panel](docs/screenshots/08_device_panel.png)

Show the thirteen-process mode briefly when you explain the architecture, so it
is clear the devices really are independent clients rather than one program.

### Starting one component at a time

Useful while developing, and for showing the startup order in a presentation.
Order does not matter — retained messages and the manager's periodic actuator
refresh let any component join late.

```bash
.venv/bin/python data_manager/data_manager.py
.venv/bin/python gui/main_gui.py

# cabinet sensors
.venv/bin/python emulators/temp_emulator.py
.venv/bin/python emulators/temp_b_emulator.py
.venv/bin/python emulators/door_emulator.py
.venv/bin/python emulators/badge_emulator.py

# diagnostic sensors
.venv/bin/python emulators/ambient_emulator.py
.venv/bin/python emulators/current_emulator.py
.venv/bin/python emulators/fan_rpm_emulator.py
.venv/bin/python emulators/power_emulator.py

# actuators
.venv/bin/python emulators/compressor_emulator.py
.venv/bin/python emulators/fan_emulator.py
.venv/bin/python emulators/siren_emulator.py
```

Or all eleven devices in one window:

```bash
.venv/bin/python emulators/device_panel.py
```

---

## 4. What you should see

Two windows open in panel mode: the device panel and the console.

In the device panel every card's indicator turns green and reads `● CONNECTED`.
In the console the top bar reads `● CONNECTED`, the dashboard banner is green
and says **NORMAL — Storage conditions are within specification**, and the
navigation rail footer reads *No active alerts*.

Leave it alone for about a minute. The unit should settle into its cooling
cycle:

* temperature oscillating roughly between **3.5 °C and 6.5 °C**,
* the **Compressor** and **Fan** cards switching on together, each showing a
  measured value that agrees with its commanded state,
* the temperature history drawing a wave inside the green band.

On the **Devices** page all eleven devices read `CONNECTED`.

If that happens the entire chain works: sensor → broker → manager → relay → back
to the sensor.

The data manager's terminal prints a summary line every ten seconds:

```
09:14:08  manager | INFO     A=6.3C   B=6.5C   amb=22.1C  door=CLOSED comp=ON  4.21A  fan=ON  1447rpm  siren=OFF devices=11/11
```

Every device is listed as reporting. If that count drops, the Devices page names
which one went quiet.

---

## 5. Demo walkthrough

Every fault below is armed from the console's **Simulations** page — you no
longer touch the individual emulator windows. Each one changes what the emulated
hardware really does, so the alarm that follows is produced by the same rules a
genuine failure would trigger, and everything it causes is labelled `SIMULATED`.

### Step 1 — Normal operation *(about 1 minute)*

Leave it alone. The temperature oscillates between roughly 3.5 °C and 6.5 °C,
the compressor and fan switch together, and the dashboard banner stays green
with **0 critical, 0 warnings**. Point out the hysteresis: the compressor starts
near 6.5 °C and stops near 3.5 °C rather than chattering at the 8 °C limit.

On the **Devices** page all eleven devices read `CONNECTED` with a freshness of
a few seconds.

### Step 2 — One-click scenarios *(the fastest demonstration)*

Open **Simulations**. The six scenario cards each state what they arm and what
you should expect. **Compressor Failure** is the strongest:

| Time | What happens |
|---|---|
| immediately | The compressor card still shows `ON`, but its measured line drops to `0.00 A` and turns red — *contradicts the command* |
| ~15 s | `CRITICAL · COMPRESSOR_NO_CURRENT` — relay or motor failure |
| — | The temperature starts climbing because cooling is genuinely lost |
| ~90 s outside the band | `CRITICAL · TEMP_EXCURSION`, with the assessment naming the compressor |

### Step 3 — The failure nothing else would catch

Arm **Fan Tachometer → Fan failure (stalled)**. After the 15 s grace period a
`CRITICAL · FAN_STALLED` incident appears **while the temperature still reads
perfectly normal**. Without the tachometer this failure is invisible until the
stock at the top of the cabinet has already spoiled.

Then clear it and arm **Low RPM (worn bearing)** instead: the fan still turns,
so no critical — but a `WARNING · FAN_DEGRADED` appears. That is predictive
maintenance: service it now, not after it seizes.

### Step 4 — A probe you cannot trust

Arm **Temperature Probe B → Probe drift**. Nothing is out of range and the
reading stays plausible, yet after 30 s of disagreement:

`CRITICAL · PROBE_MISMATCH — readings cannot be trusted`

The alarm never says which probe is wrong, because nothing in the system can
know. That uncertainty *is* the alarm.

### Step 5 — Whose fault is it?

Arm **Ambient Room Sensor → Building cooling failure**. The storeroom climbs
past 30 °C, and because the ambient probe feeds probe A's thermal model the
cabinet genuinely starts losing ground. Read the assessment on the dashboard:

> *the storeroom is at 34 °C — this is a building cooling problem, not a unit
> fault*

That sentence sends a building engineer instead of a refrigeration technician.
Compare it with step 2, where the same excursion was diagnosed as the
compressor's fault.

### Step 6 — Access control

Arm **Door Sensor → Door forced open**. A `WARNING · UNAUTHORISED_ACCESS`
appears immediately and the *last opened by* tile reads **no badge**. The door
warning follows at 20 s and becomes critical at 45 s.

Clear it, press a badge button on the RFID reader panel, then arm it again — the
incident now carries the operator's name.

### Step 7 — Connectivity

Every device supports three connectivity faults. Arm **Missing telemetry** on
the Power Supply Sensor: after roughly three missed slots the Devices page marks
it `OFFLINE`, and a `DEVICE_STALE` incident opens naming it.

**MQTT disconnect** drops that device's broker connection entirely. It heals
itself after 30 seconds, because a device with its link cut cannot hear the
command to restore it — the panel shows the countdown.

### Step 8 — Incident lifecycle

Open **Incidents**. Every condition raised above is there with its severity,
device, duration and assessed cause. **Acknowledge** one: its status changes and
your name is recorded against it. Filter by severity, device, status or time
range, and export the result to CSV.

### Step 9 — Maintenance mode

Press **Enter maintenance** in the top bar and confirm. Conditions are still
evaluated and logged, the actuators are parked off, but the unit no longer
escalates and the siren stays silent. The banner says so explicitly, and the
mode row names who activated it. Leave maintenance to restore escalation.

### Step 10 — Reset

Back on **Simulations**, press **Reset all simulations**. Every armed fault
clears on every device, the conditions resolve with their own events, and the
dashboard returns to green.

### Step 11 — The stored record

Open **History**. The tiles summarise the range; the charts show humidity,
compressor current, fan speed and an activity ribbon for door/compressor/fan.
The readings table is the five-second audit trail — note the pairs of columns,
`Comp` beside `Amps` and `Fan` beside `RPM`, the command next to the measurement
that verifies it. The events table marks which rows came from a simulation.

## 6. Speeding up the demo

The default timers are realistic but slow for a 10-minute recording. To make the
alarms fire sooner, edit `config/mqtt_init.py`:

```python
DOOR_WARNING_SECONDS = 10        # default 20
DOOR_ALARM_SECONDS = 20          # default 45
EXCURSION_ALARM_SECONDS = 30     # default 90
BATTERY_WARNING_SECONDS = 20     # default 60
SENSOR_TIMEOUT_SECONDS = 15      # default 25
PROBE_DISAGREE_SECONDS = 12      # default 30
ACTUATOR_FAULT_SECONDS = 6       # default 15
```

Restart the data manager afterwards — it reads these once at startup.

Arming **Ambient Room Sensor → Building cooling failure** is the other
accelerator: a hot storeroom makes the cabinet warm up far faster.

---

## 7. Stopping

**macOS:** `Ctrl-C` in the terminal the launcher opened stops everything, and so
does closing that terminal window.

If a component was started separately and is still running:

```bash
pkill -f "data_manager.py"
pkill -f "main_gui.py"
pkill -f "emulators/"
```

**Windows:** close each console window, or `Ctrl-C` in it.

On shutdown the data manager switches the siren, compressor and fan off, so the
system is left in a quiet state.

---

## 8. Troubleshooting

### `Could not find the Qt platform plugin "cocoa"` (macOS)

Some PyQt5 wheels do not export their plugin directory. `ui/qt_env.py` sets the
path automatically before the first window is created, so this should not
happen. If it still does, you likely have a stale environment variable:

```bash
unset QT_QPA_PLATFORM_PLUGIN_PATH
```

### Windows open, but the indicator stays red `● OFFLINE`

The broker is unreachable. Check your internet connection, and check whether
outbound port **1883** is blocked — some campus and corporate networks block it.
Test:

```bash
nc -vz broker.hivemq.com 1883
```

If it is blocked, switch to the college broker in `config/mqtt_init.py`:

```python
BROKER_INDEX = 0
```

That one runs on port 80, which is rarely filtered, but requires the college
network.

### A cleared fault takes a minute to stop showing as critical

This is deliberate. A compressor fault can only be *disproven* by commanding the
compressor on and watching it draw current, so after you clear the simulation
the incident stays open until the next cooling cycle proves the hardware works.
The same applies to the fan. Everything else clears within a second or two.

### Values jump around, or the log shows duplicated events

**More than one data manager is running.** Each instance writes its own rows to
the same database and sends its own actuator commands, so events appear two or
three times over and the relays fight each other.

Check:

```bash
ps aux | grep "[d]ata_manager.py"
```

There should be exactly one line. If there are more:

```bash
pkill -f "data_manager.py"
```

Then start a single one.

### Readings appear that you did not cause

Somebody else is publishing to the same topics on the public broker. Change the
namespace in `config/mqtt_init.py`:

```python
TOPIC_ROOT = 'HIT/coldchain/<your-name>/unit1'
```

Restart every component so they all agree on the new root.

### `Permission denied` when running a launcher

```bash
chmod +x run/macos/*.command run/macos/*.sh
```

### macOS: *"Apple could not verify ... is free of malware"*

Every file that arrives over the network is tagged `com.apple.quarantine`, and
Gatekeeper will not let Finder open a quarantined script that nobody has signed.
A clone is not affected; a downloaded zip is. The dialog offers only **Done** and
**Move to Trash** - there is no "Open anyway" in it, and on macOS 15 the old
right-click → **Open** route is gone too, so the file cannot be released from
the dialog itself.

Remove the tag, from the project folder:

```bash
xattr -d com.apple.quarantine run/macos/*.command run/macos/*.sh
```

Double-clicking works from then on. `xattr run/macos/*` lists what is left, and
prints nothing about quarantine once it is cleared.

Two things worth knowing:

* **A terminal does not care.** `./run/macos/start_panel.command` runs a
  quarantined file without complaint - Gatekeeper guards the Finder
  double-click, not execution.
* **`git clone` avoids the whole problem**, because the files are written by git
  rather than downloaded by a browser, so they are never tagged.

If the file is also not executable - some unzip tools drop the bit, though the
GitHub zip keeps it:

```bash
chmod +x run/macos/*.command run/macos/*.sh
```

### Windows: `ERROR: Python 3 was not found on this computer.`

The launcher tried the `py` launcher, `python` and `python3` and none of them
were a working interpreter. Install Python from
[python.org](https://www.python.org/downloads/windows/) and tick
**Add python.exe to PATH** on the first screen, then run the launcher again.

If Python *is* installed and you still see this, open a command prompt and check
what the names actually resolve to:

```
py -3 --version
python --version
```

A `python` that prints nothing, or opens the Microsoft Store, is the App
Execution Alias rather than a real interpreter. Turn it off under
**Settings → Apps → Advanced app settings → App execution aliases**, or just
use `py -3`, which the launcher prefers anyway.

### Windows: the launcher window flashes and disappears

The `.bat` files must have Windows (CRLF) line endings; `cmd.exe` seeks through
them by byte offset, so a copy saved with Unix endings can jump to the wrong
place. `.gitattributes` pins them, so a normal `git clone` is correct. If you
edited one in an editor set to LF, save it again as CRLF.

### `ModuleNotFoundError: No module named 'PyQt5'`

You are running the system Python instead of the virtual environment. Use the
full path:

```bash
.venv/bin/python gui/main_gui.py
```

Or activate the environment first:

```bash
source .venv/bin/activate
```

### The History tab is empty

The data manager writes a reading only every 5 seconds, and only while it is
running. Give it a minute, then press **Refresh**. If it stays empty, confirm
the manager's terminal is printing its summary lines.

### Starting over with a clean database

The database is recreated automatically on the next start:

```bash
rm database/coldchain.db*
```

---

## 9. Quick reference

| Task | Command (macOS) |
|---|---|
| Install | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| Start everything, 8 windows | `run/macos/start_all.command` |
| Start everything, 1 device window | `run/macos/start_panel.command` |
| Start one component | `.venv/bin/python gui/main_gui.py` |
| Stop everything | `Ctrl-C`, or `pkill -f "data_manager.py"` |
| Clear the database | `rm database/coldchain.db*` |
| Check for stray managers | `ps aux \| grep "[d]ata_manager.py"` |

On Windows the equivalents are `run\windows\start_all.bat` and
`run\windows\start_panel.bat`.
