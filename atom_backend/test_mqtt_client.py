import asyncio
import json
import unittest


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.published = []
        self.subscriptions = []

    def username_pw_set(self, *_args):
        pass

    def reconnect_delay_set(self, **_kwargs):
        pass

    def connect_async(self, *_args):
        self.on_connect(self, None, None, 0)

    def loop_start(self):
        pass

    def subscribe(self, topic):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return type('PublishInfo', (), {'rc': 0})()


class MqttClientTests(unittest.TestCase):
    def test_publish_returns_only_when_the_broker_accepted_a_pending_command(self):
        from mqtt_client import MQTTClient

        fake = FakeMqttClient()
        client = MQTTClient('localhost', 1883, client_factory=lambda: fake, connect_timeout_seconds=0.01)

        result = asyncio.run(client.publish('atom/appliance/led1/set', '{"state":"on"}'))

        self.assertEqual(result, 'pending_ack')
        self.assertEqual(fake.published, [('atom/appliance/led1/set', '{"state":"on"}', 0)])

    def test_reported_state_is_forwarded_without_treating_a_command_as_an_acknowledgement(self):
        from mqtt_client import MQTTClient

        client = MQTTClient('localhost', 1883, client_factory=FakeMqttClient)
        received = []
        client.set_state_handler(lambda appliance_id, payload: received.append((appliance_id, payload)))
        message = type('Message', (), {
            'topic': 'atom/appliance/led1/state',
            'payload': json.dumps({'state': 'on', 'command_id': 'abc'}).encode(),
        })()

        client._on_message(None, None, message)

        self.assertEqual(received, [('led1', {'state': 'on', 'command_id': 'abc'})])
