"""Temperature and humidity sensor emulator (the primary data producer).

Instead of publishing random numbers, this emulator runs a small thermal model
of the cabinet, so the readings react to what the rest of the system does:

* the compressor pulls the temperature down while it is running,
* an open door lets warm room air in much faster than the closed cabinet leaks,
* the room temperature reported by the ambient sensor sets what the cabinet is
  leaking towards, so a hot storeroom really does make cooling harder,
* an injected cooling failure leaves the compressor commanded on with no effect.

That makes the whole system a closed control loop: sensor -> data manager ->
compressor relay -> sensor.

The model runs regardless of the display faults. A frozen or drifting probe
changes what is *reported*, not what the cabinet is actually doing - which is
precisely why those faults are dangerous and worth simulating.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import random

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QGridLayout, QLabel

from config import mqtt_init as cfg
from config.mqtt_client import parse_json
from ui import theme as ui
from emulators.ui_common import EmulatorPanel, run_panel

# --- thermal model constants ------------------------------------------------
LEAK_CLOSED = 0.018      # fraction of the gap to ambient recovered per tick
LEAK_OPEN = 0.030        # an open door roughly doubles the heat ingress
COOLING_PER_TICK = 0.55  # degrees removed per tick while the compressor runs
NOISE = 0.05             # sensor noise, degrees

HUM_BASE = 45.0
HUM_DRIFT = 0.4
HUM_DOOR_GAIN = 2.5

START_TEMP = 5.0
DRIFT_PER_TICK = 0.22
SPIKE_C = 16.5
DROP_C = -3.5
HUM_SPIKE = 92.0
HUM_DROP = 18.0

GEOMETRY = (40, 60, 380, 360)


class TempSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__('temp')
        self.setMinimumWidth(300)

        # The physical cabinet
        self.temperature = START_TEMP
        self.humidity = HUM_BASE
        self.compressor_on = False
        self.door_open = False
        self.ambient = cfg.AMBIENT_NOMINAL_C

        # What the probe reports, which a fault can separate from the truth
        self.reported_temp = START_TEMP
        self.reported_hum = HUM_BASE
        self.drift = 0.0
        self._frozen_temp = None
        self._frozen_hum = None

        self._build_ui()

        self.mqtt.subscribe(cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_DOOR,
                            cfg.TOPIC_AMBIENT)
        self.start_mqtt()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(cfg.SENSOR_PUBLISH_MS)

    # -- interface ---------------------------------------------------------
    def _build_ui(self):
        readouts = ui.make_subpanel()
        grid = QGridLayout(readouts)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setSpacing(6)

        self.tempValue = QLabel('--')
        self.tempValue.setAlignment(Qt.AlignCenter)
        self.humValue = QLabel('--')
        self.humValue.setAlignment(Qt.AlignCenter)
        # Neither reading is 'interactive', so neither is painted in the
        # accent. They are numbers; they get ink.
        self._style_value(self.tempValue, ui.TEXT)
        self._style_value(self.humValue, ui.TEXT)

        grid.addWidget(ui.label('Temperature', size=ui.SIZE_XS,
                                color=ui.TEXT_MUTED,
                                align=Qt.AlignCenter), 0, 0)
        grid.addWidget(ui.label('Humidity', size=ui.SIZE_XS,
                                color=ui.TEXT_MUTED,
                                align=Qt.AlignCenter), 0, 1)
        grid.addWidget(self.tempValue, 1, 0)
        grid.addWidget(self.humValue, 1, 1)

        self.modelLabel = ui.label('waiting for first sample',
                                   size=ui.SIZE_XS,
                                   color=ui.TEXT_MUTED, align=Qt.AlignCenter)
        grid.addWidget(self.modelLabel, 2, 0, 1, 2)

        self.truthLabel = ui.label('', size=ui.SIZE_XS, color=ui.WARN,
                                   align=Qt.AlignCenter)
        self.truthLabel.hide()
        grid.addWidget(self.truthLabel, 3, 0, 1, 2)

        self.body.addWidget(readouts)

    @staticmethod
    def _style_value(widget, color):
        widget.setStyleSheet(ui.reading_style(color, size=ui.SIZE_XXL))

    # -- MQTT --------------------------------------------------------------
    def on_mqtt_message(self, topic, payload):
        if topic == cfg.TOPIC_COMPRESSOR_STS:
            self.compressor_on = payload.strip().upper() == 'ON'
        elif topic == cfg.TOPIC_DOOR:
            data = parse_json(payload, {})
            self.door_open = str(data.get('state', '')).upper() == 'OPEN'
        elif topic == cfg.TOPIC_AMBIENT:
            data = parse_json(payload, {})
            try:
                self.ambient = float(data['ambient'])
            except (KeyError, TypeError, ValueError):
                pass

    # -- faults ------------------------------------------------------------
    def on_fault_changed(self, fault_id, active):
        if fault_id == 'temp_drift' and not active:
            self.drift = 0.0
        elif fault_id == 'temp_frozen':
            self._frozen_temp = self.reported_temp if active else None
        elif fault_id == 'hum_frozen':
            self._frozen_hum = self.reported_hum if active else None

    # -- simulation --------------------------------------------------------
    def tick(self):
        self._advance_physics()
        self._apply_reporting_faults()
        self._update_readouts()

        if not self.telemetry_allowed():
            self.modelLabel.setText('not publishing - telemetry fault armed')
            return

        self.mqtt.publish_json(cfg.TOPIC_TEMP, {
            'temperature': self.reported_temp,
            'humidity': self.reported_hum,
            'unit': 'C',
        })

    def _advance_physics(self):
        """What the cabinet is really doing, independent of what is reported."""
        cooling_failed = self.has_fault('cooling_fail')
        leak = LEAK_OPEN if self.door_open else LEAK_CLOSED
        self.temperature += (self.ambient - self.temperature) * leak
        if self.compressor_on and not cooling_failed:
            self.temperature -= COOLING_PER_TICK
        self.temperature += random.uniform(-NOISE, NOISE)
        self.temperature = round(max(-10.0, min(45.0, self.temperature)), 2)

        target_hum = HUM_BASE + (HUM_DOOR_GAIN * 4 if self.door_open else 0.0)
        self.humidity += (target_hum - self.humidity) * 0.15
        self.humidity += random.uniform(-HUM_DRIFT, HUM_DRIFT)
        self.humidity = round(max(10.0, min(95.0, self.humidity)), 1)

    def _apply_reporting_faults(self):
        """Separate the reported value from the true one where a fault says so."""
        if self.has_fault('temp_frozen') and self._frozen_temp is not None:
            self.reported_temp = self._frozen_temp
        elif self.has_fault('temp_spike'):
            self.reported_temp = round(SPIKE_C + random.uniform(-0.2, 0.2), 2)
        elif self.has_fault('temp_drop'):
            self.reported_temp = round(DROP_C + random.uniform(-0.2, 0.2), 2)
        else:
            if self.has_fault('temp_drift'):
                self.drift += DRIFT_PER_TICK
            self.reported_temp = round(self.temperature + self.drift, 2)

        if self.has_fault('hum_frozen') and self._frozen_hum is not None:
            self.reported_hum = self._frozen_hum
        elif self.has_fault('hum_spike'):
            self.reported_hum = round(HUM_SPIKE + random.uniform(-1, 1), 1)
        elif self.has_fault('hum_drop'):
            self.reported_hum = round(HUM_DROP + random.uniform(-1, 1), 1)
        else:
            self.reported_hum = self.humidity

    def _update_readouts(self):
        self.tempValue.setText('%.1f °C' % self.reported_temp)
        self.humValue.setText('%.0f %%' % self.reported_hum)

        in_band = cfg.TEMP_TARGET_MIN <= self.reported_temp <= cfg.TEMP_TARGET_MAX
        self._style_value(self.tempValue, ui.OK if in_band else ui.ALARM)

        if self.has_fault('cooling_fail'):
            state = 'cooling failure injected - temperature rising'
        elif self.door_open:
            state = 'door open - warm air entering'
        elif self.compressor_on:
            state = 'compressor running - cooling down'
        else:
            state = 'compressor off - slow warm-up'
        self.modelLabel.setText(state)

        # When the report and reality have been forced apart, say so on the
        # panel; the point of these faults is that the dashboard cannot tell.
        misreporting = abs(self.reported_temp - self.temperature) > 0.5
        if misreporting:
            self.truthLabel.setText('cabinet is actually %.1f °C' % self.temperature)
            self.truthLabel.show()
        else:
            self.truthLabel.hide()


if __name__ == '__main__':
    run_panel(TempSensorPanel, GEOMETRY)
