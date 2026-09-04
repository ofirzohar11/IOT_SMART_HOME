"""Shared MQTT client wrapper used by every process in the system.

paho-mqtt delivers callbacks on its own network thread. Qt widgets may only be
touched from the main thread, so the GUI processes convert the callbacks below
into Qt signals before they update anything on screen.
"""

import json
import random

import paho.mqtt.client as mqtt

from config import mqtt_init as cfg

try:  # paho-mqtt 2.x
    from paho.mqtt.client import CallbackAPIVersion
    _NEW_API = True
except ImportError:  # paho-mqtt 1.x
    _NEW_API = False


class MqttClient:
    """Connect, subscribe and publish, with automatic reconnect."""

    def __init__(self, role, on_connect=None, on_message=None, on_disconnect=None,
                 verbose=False):
        self.role = role
        self.client_id = 'ccm_%s_%d' % (role, random.randrange(1, 10000000))
        self.connected = False
        self.verbose = verbose
        self._on_connect = on_connect
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._subscriptions = []
        self._client = self._build_client()

    # -- setup ------------------------------------------------------------
    def _build_client(self):
        if _NEW_API:
            client = mqtt.Client(CallbackAPIVersion.VERSION1, self.client_id)
        else:
            client = mqtt.Client(self.client_id, clean_session=True)

        client.on_connect = self._handle_connect
        client.on_disconnect = self._handle_disconnect
        client.on_message = self._handle_message
        if self.verbose:
            client.on_log = lambda c, u, level, buf: print('mqtt log:', buf)
        if cfg.USERNAME:
            client.username_pw_set(cfg.USERNAME, cfg.PASSWORD)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client

    # -- paho callbacks ---------------------------------------------------
    def _handle_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            print('[%s] connected to %s:%s' % (self.role, cfg.BROKER_HOST, cfg.BROKER_PORT))
            # Re-apply subscriptions: after a reconnect the broker forgets them.
            for topic in self._subscriptions:
                client.subscribe(topic)
            if self._on_connect:
                self._on_connect()
        else:
            self.connected = False
            print('[%s] bad connection, return code %s' % (self.role, rc))

    def _handle_disconnect(self, client, userdata, flags, rc=0):
        self.connected = False
        print('[%s] disconnected (rc=%s)' % (self.role, rc))
        if self._on_disconnect:
            self._on_disconnect()

    def _handle_message(self, client, userdata, msg):
        payload = msg.payload.decode('utf-8', 'ignore')
        if self._on_message:
            self._on_message(msg.topic, payload)

    # -- public API -------------------------------------------------------
    def start(self):
        """Connect in the background and start the network loop."""
        self._client.connect_async(cfg.BROKER_HOST, cfg.BROKER_PORT, cfg.KEEPALIVE)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:
            pass

    def subscribe(self, *topics):
        for topic in topics:
            if topic not in self._subscriptions:
                self._subscriptions.append(topic)
            if self.connected:
                self._client.subscribe(topic)

    def publish(self, topic, payload, retain=False):
        self._client.publish(topic, payload, qos=0, retain=retain)

    def publish_json(self, topic, data, retain=False):
        self.publish(topic, json.dumps(data), retain=retain)


def parse_json(payload, default=None):
    """Decode a JSON payload, returning `default` when the message is malformed."""
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, dict) else default
