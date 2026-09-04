"""Temperature and humidity sensor emulator (the data producer).

Instead of publishing random numbers, this emulator runs a small thermal model
of the cabinet, so the readings react to what the rest of the system does:

* the compressor pulls the temperature down while it is running,
* an open door lets warm room air in much faster than the closed cabinet leaks,
* a cooling failure can be injected to produce a real temperature excursion.

That makes the whole system a closed control loop: sensor -> data manager ->
compressor relay -> sensor.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qt must be able to find its platform plugin before the first widget exists.
from ui.qt_env import ensure_qt_plugin_path
ensure_qt_plugin_path()

import random

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel,
                             QSlider, QVBoxLayout)

from config import mqtt_init as cfg
from config.mqtt_client import parse_json
from emulators import ui_common as ui
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

GEOMETRY = (40, 60, 380, 400)


class TempSensorPanel(EmulatorPanel):

    def __init__(self):
        super().__init__(
            role='temp',
            title='🌡  Temperature / Humidity Sensor',
            subtitle='Data producer - publishes a JSON sample every %.1f s'
                     % (cfg.SENSOR_PUBLISH_MS / 1000.0),
            topic_note='pub: %s\nsub: %s , %s'
                       % (cfg.TOPIC_TEMP, cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_DOOR),
        )
        self.setMinimumWidth(340)

        self.temperature = START_TEMP
        self.humidity = HUM_BASE
        self.compressor_on = False
        self.door_open = False

        self._build_ui()

        self.mqtt.subscribe(cfg.TOPIC_COMPRESSOR_STS, cfg.TOPIC_DOOR)
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
        self._style_value(self.tempValue, ui.ACCENT)
        self._style_value(self.humValue, ui.TEXT)

        grid.addWidget(ui.label('Temperature', size=11, color=ui.TEXT_DIM,
                                align=Qt.AlignCenter), 0, 0)
        grid.addWidget(ui.label('Humidity', size=11, color=ui.TEXT_DIM,
                                align=Qt.AlignCenter), 0, 1)
        grid.addWidget(self.tempValue, 1, 0)
        grid.addWidget(self.humValue, 1, 1)

        self.modelLabel = ui.label('waiting for first sample', size=11,
                                   color=ui.TEXT_DIM, align=Qt.AlignCenter)
        grid.addWidget(self.modelLabel, 2, 0, 1, 2)

        controls = ui.make_subpanel()
        box = QVBoxLayout(controls)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)
        box.addWidget(ui.label('Simulation controls', size=12, bold=True))

        ambient_row = QHBoxLayout()
        self.ambientLabel = ui.label('Room: 22 °C', size=11, color=ui.TEXT_DIM)
        self.ambientSlider = QSlider(Qt.Horizontal)
        self.ambientSlider.setMinimum(15)
        self.ambientSlider.setMaximum(40)
        self.ambientSlider.setValue(22)
        self.ambientSlider.valueChanged.connect(
            lambda v: self.ambientLabel.setText('Room: %d °C' % v))
        ambient_row.addWidget(self.ambientLabel)
        ambient_row.addWidget(self.ambientSlider, stretch=1)
        box.addLayout(ambient_row)

        self.faultCheck = QCheckBox('Inject cooling failure')
        self.onlineCheck = QCheckBox('Sensor online (publishing)')
        self.onlineCheck.setChecked(True)
        for check in (self.faultCheck, self.onlineCheck):
            check.setStyleSheet(
                'QCheckBox { color: %s; font-family: %s; font-size: 12px; '
                'background: transparent; border: none; }'
                'QCheckBox::indicator { width: 15px; height: 15px; }'
                % (ui.TEXT, ui.FONT))
            box.addWidget(check)

        self.body.addWidget(readouts)
        self.body.addWidget(controls)

    @staticmethod
    def _style_value(widget, color):
        widget.setStyleSheet(
            'color: %s; font-family: %s; font-size: 32px; font-weight: bold; '
            'background: transparent; border: none;' % (color, ui.FONT))

    # -- MQTT --------------------------------------------------------------
    def on_mqtt_message(self, topic, payload):
        if topic == cfg.TOPIC_COMPRESSOR_STS:
            self.compressor_on = payload.strip().upper() == 'ON'
        elif topic == cfg.TOPIC_DOOR:
            data = parse_json(payload, {})
            self.door_open = str(data.get('state', '')).upper() == 'OPEN'

    # -- simulation --------------------------------------------------------
    def tick(self):
        ambient = float(self.ambientSlider.value())
        cooling_failed = self.faultCheck.isChecked()

        leak = LEAK_OPEN if self.door_open else LEAK_CLOSED
        self.temperature += (ambient - self.temperature) * leak
        if self.compressor_on and not cooling_failed:
            self.temperature -= COOLING_PER_TICK
        self.temperature += random.uniform(-NOISE, NOISE)
        self.temperature = round(max(-10.0, min(45.0, self.temperature)), 2)

        target_hum = HUM_BASE + (HUM_DOOR_GAIN * 4 if self.door_open else 0.0)
        self.humidity += (target_hum - self.humidity) * 0.15
        self.humidity += random.uniform(-HUM_DRIFT, HUM_DRIFT)
        self.humidity = round(max(10.0, min(95.0, self.humidity)), 1)

        self._update_readouts(cooling_failed)

        if not self.onlineCheck.isChecked():
            self.modelLabel.setText('sensor offline - not publishing')
            return

        self.mqtt.publish_json(cfg.TOPIC_TEMP, {
            'temperature': self.temperature,
            'humidity': self.humidity,
            'unit': 'C',
        })
        print('[temp] published %.2f C / %.1f %%' % (self.temperature, self.humidity))

    def _update_readouts(self, cooling_failed):
        self.tempValue.setText('%.1f °C' % self.temperature)
        self.humValue.setText('%.0f %%' % self.humidity)

        in_band = cfg.TEMP_TARGET_MIN <= self.temperature <= cfg.TEMP_TARGET_MAX
        self._style_value(self.tempValue, ui.OK if in_band else ui.ALARM)

        if cooling_failed:
            state = 'cooling failure injected - temperature rising'
        elif self.door_open:
            state = 'door open - warm air entering'
        elif self.compressor_on:
            state = 'compressor running - cooling down'
        else:
            state = 'compressor off - slow warm-up'
        self.modelLabel.setText(state)


if __name__ == '__main__':
    run_panel(TempSensorPanel, GEOMETRY)
