"""Shared MQTT client wrapper used by every process in the system.

paho delivers callbacks on its own network thread. Qt widgets may only be
touched from the main thread, so the GUI processes convert these callbacks into
Qt signals before they update anything on screen; the data manager guards its
state with a lock and defers all disk work to its own loop.

The wrapper adds four things paho does not give you directly:

* subscriptions are remembered and re-applied after a reconnect, because the
  broker forgets them when the session drops;
* commands and alerts publish at QoS 1 so they are not silently lost, while
  high-rate telemetry stays at QoS 0 where the newest value supersedes anything
  missed;
* payloads are validated before they reach application code;
* the link can be dropped and restored deliberately, which is what the
  connectivity fault injections use.
"""

import json
import random
import threading

import paho.mqtt.client as mqtt

from config import mqtt_init as cfg

try:  # paho-mqtt 2.x
    from paho.mqtt.client import CallbackAPIVersion
    _NEW_API = True
except ImportError:  # paho-mqtt 1.x
    _NEW_API = False

QOS_TELEMETRY = 0   # a newer reading replaces a lost one
QOS_COMMAND = 1     # must arrive: actuator commands, alerts, control messages


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
        self._lock = threading.Lock()
        self._started = False
        self._suspended = False     # deliberately taken down by a simulation
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
        client.reconnect_delay_set(min_delay=cfg.RECONNECT_MIN_S,
                                   max_delay=cfg.RECONNECT_MAX_S)
        return client

    # -- paho callbacks ---------------------------------------------------
    def _handle_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.connected = False
            print('[%s] bad connection, return code %s' % (self.role, rc))
            return
        self.connected = True
        print('[%s] connected to %s:%s' % (self.role, cfg.BROKER_HOST, cfg.BROKER_PORT))
        # The broker forgets subscriptions when a session ends, so re-apply
        # them on every connect rather than only the first.
        with self._lock:
            topics = list(self._subscriptions)
        for topic in topics:
            client.subscribe(topic, qos=QOS_COMMAND)
        if self._on_connect:
            self._on_connect()

    def _handle_disconnect(self, client, userdata, flags, rc=0):
        was_connected = self.connected
        self.connected = False
        if was_connected:
            print('[%s] disconnected (rc=%s)' % (self.role, rc))
        if self._on_disconnect and was_connected:
            self._on_disconnect()

    def _handle_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8', 'ignore')
        except Exception:
            return
        if self._on_message:
            try:
                self._on_message(msg.topic, payload)
            except Exception as error:
                # A handler bug must not kill the network thread.
                print('[%s] handler error on %s: %s' % (self.role, msg.topic, error))

    # -- public API -------------------------------------------------------
    def start(self):
        """Connect in the background and start the network loop."""
        if self._started:
            return
        self._started = True
        self._client.connect_async(cfg.BROKER_HOST, cfg.BROKER_PORT, cfg.KEEPALIVE)
        self._client.loop_start()

    def stop(self):
        if not self._started:
            return
        self._started = False
        try:
            self._client.disconnect()
        except Exception:
            pass
        try:
            self._client.loop_stop()
        except Exception:
            pass
        self.connected = False

    def subscribe(self, *topics):
        with self._lock:
            new = [t for t in topics if t not in self._subscriptions]
            self._subscriptions.extend(new)
        if self.connected:
            for topic in new:
                self._client.subscribe(topic, qos=QOS_COMMAND)

    def publish(self, topic, payload, retain=False, qos=QOS_TELEMETRY):
        if self._suspended:
            return False
        try:
            self._client.publish(topic, payload, qos=qos, retain=retain)
            return True
        except Exception as error:
            print('[%s] publish to %s failed: %s' % (self.role, topic, error))
            return False

    def publish_json(self, topic, data, retain=False, qos=QOS_TELEMETRY):
        try:
            body = json.dumps(data)
        except (TypeError, ValueError) as error:
            print('[%s] could not encode payload for %s: %s'
                  % (self.role, topic, error))
            return False
        return self.publish(topic, body, retain=retain, qos=qos)

    # -- deliberate outage (used by the connectivity fault injections) ----
    @property
    def suspended(self):
        return self._suspended

    def suspend(self):
        """Drop the link and stay down until restore() is called."""
        if self._suspended:
            return
        self._suspended = True
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self.connected = False
        print('[%s] link suspended by simulation' % self.role)

    def restore(self):
        if not self._suspended:
            return
        self._suspended = False
        try:
            self._client.connect_async(cfg.BROKER_HOST, cfg.BROKER_PORT,
                                       cfg.KEEPALIVE)
            self._client.loop_start()
        except Exception as error:
            print('[%s] could not restore link: %s' % (self.role, error))
        print('[%s] link restored' % self.role)


def parse_json(payload, default=None):
    """Decode a JSON payload, returning `default` when the message is malformed."""
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, dict) else default
