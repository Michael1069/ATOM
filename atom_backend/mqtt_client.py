import asyncio
import json
import threading
import os
from collections.abc import Callable
from typing import Any
import paho.mqtt.client as mqtt

class MQTTClient:
    def __init__(self, broker, port, *, client_factory=None, connect_timeout_seconds=3):
        self.broker = broker
        self.port = port
        self.client = (client_factory or mqtt.Client)()
        self.connect_timeout_seconds = connect_timeout_seconds

        # MQTT authentication
        mqtt_user = os.getenv("MQTT_USER", "")
        mqtt_password = os.getenv("MQTT_PASSWORD", "")

        if mqtt_user:
            self.client.username_pw_set(mqtt_user, mqtt_password)

        self.connected = False
        self._connect_started = False
        self._connected_event = threading.Event()
        self._lock = threading.Lock()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._state_handler = None
        if hasattr(self.client, 'reconnect_delay_set'):
            self.client.reconnect_delay_set(min_delay=1, max_delay=15)

    def set_state_handler(self, handler):
        self._state_handler = handler

    def _on_connect(self, client, userdata, flags, rc, *_extra):
        if rc == 0:
            client.subscribe('atom/appliance/+/state')
            self.connected = True
            self._connected_event.set()
        else:
            self.connected = False
            self._connected_event.clear()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            appliance_id = msg.topic.split('/')[-2]
            if payload.get('state') in {'on', 'off'} and self._state_handler:
                self._state_handler(appliance_id, payload)
        except (UnicodeDecodeError, json.JSONDecodeError, IndexError, AttributeError):
            return

    def _on_disconnect(self, _client, _userdata, _rc, *_extra):
        self.connected = False
        self._connected_event.clear()

    async def connect(self):
        if self.connected:
            return
        with self._lock:
            if not self._connect_started:
                self._connect_started = True
                try:
                    self.client.connect_async(self.broker, self.port, 60)
                    self.client.loop_start()
                except Exception as exc:
                    self._connect_started = False
                    raise RuntimeError(f'Cannot start MQTT connection: {exc}') from exc
        connected = await asyncio.to_thread(
            self._connected_event.wait, self.connect_timeout_seconds
        )
        if not connected:
            raise RuntimeError('MQTT broker did not become available before the command timeout')

    async def publish(self, topic, payload):
        await self.connect()
        # QoS 0 avoids a queued stale command being replayed after reconnect.
        # Device-state acknowledgement, not this call, remains the proof of actuation.
        result = self.client.publish(topic, payload, qos=0)
        if getattr(result, 'rc', mqtt.MQTT_ERR_SUCCESS) != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError('MQTT broker rejected the command')
        return 'pending_ack'

# Global instance (will be imported by backend modules)
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

mqtt_client = MQTTClient(MQTT_BROKER, MQTT_PORT)
