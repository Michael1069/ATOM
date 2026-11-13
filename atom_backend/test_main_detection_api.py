import importlib
import asyncio
import sys
import types
import unittest


class FakeReference:
    def __init__(self):
        self.value = None

    def child(self, _name):
        return self

    def set(self, value):
        self.value = value

    def update(self, value):
        self.value = value

    def get(self):
        return self.value


class DetectionApiTests(unittest.TestCase):
    def setUp(self):
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in ("main", "firebase_admin", "mqtt_client", "decision_engine")
        }
        firebase = types.ModuleType("firebase_admin")
        firebase.credentials = types.SimpleNamespace(Certificate=lambda _path: object())
        firebase.db = types.SimpleNamespace(reference=lambda _path: FakeReference())
        firebase.initialize_app = lambda *_args, **_kwargs: None
        sys.modules["firebase_admin"] = firebase
        sys.modules["mqtt_client"] = types.SimpleNamespace(mqtt_client=object())
        sys.modules["decision_engine"] = types.SimpleNamespace(decision_engine=object())
        sys.modules.pop("main", None)
        self.main = importlib.import_module("main")

    def tearDown(self):
        sys.modules.pop("main", None)
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_detection_status_is_available_without_starting_the_camera(self):
        status = self.main.detection_service.snapshot()
        routes = {route.path for route in self.main.app.routes}

        self.assertEqual(status["status"], "stopped")
        self.assertFalse(status["running"])
        self.assertIn("/detection/status", routes)

    def test_video_demo_routes_are_available(self):
        routes = {route.path for route in self.main.app.routes}

        self.assertTrue(
            {
                "/api/camera/upload",
                "/api/camera/start",
                "/api/camera/stop",
                "/api/camera/status",
                "/api/camera/stream",
                "/api/session/{session_id}/snapshot",
            }.issubset(routes)
        )

    def test_dashboard_mode_labels_normalize_to_the_backend_contract(self):
        self.assertEqual(self.main.normalize_mode('Automatic'), 'automatic')
        self.assertEqual(self.main.normalize_mode('Human Override'), 'human_override')
        self.assertEqual(self.main.normalize_mode('hybrid'), 'hybrid')
        with self.assertRaises(ValueError):
            self.main.normalize_mode('something else')

    def test_camera_routes_include_a_single_annotated_frame_endpoint(self):
        routes = {route.path for route in self.main.app.routes}

        self.assertIn('/api/camera/frame.jpg', routes)

    def test_startup_does_not_wait_for_an_unavailable_mqtt_broker(self):
        class NeverConnectingMqtt:
            async def connect(self):
                await asyncio.Event().wait()

        scheduled = []

        def record_background_task(coro, *, name=None):
            scheduled.append(name)
            coro.close()

        self.main.schedule_optional_mqtt_connect(
            NeverConnectingMqtt(), task_creator=record_background_task
        )
        self.assertEqual(scheduled, ['atom-optional-mqtt-connect'])

    def test_request_session_activation_routes_output_to_that_session(self):
        class SessionReference:
            def __init__(self, value=None):
                self.value = value
                self.children = {}

            def child(self, name):
                return self.children.setdefault(name, SessionReference())

            def get(self):
                return self.value

        root = SessionReference()
        root.child('sessions').child('current-session').value = {'id': 'current-session'}
        previous_root = self.main.root_ref
        previous_session = self.main.active_session_id
        original_service = self.main.detection_service

        class Detector:
            def __init__(self):
                self.session_root = None

            def set_session_root(self, value):
                self.session_root = value

        detector = Detector()
        self.main.root_ref = root
        self.main.detection_service = detector
        try:
            self.main._activate_session('current-session')
            self.assertEqual(self.main.active_session_id, 'current-session')
            self.assertIs(detector.session_root, root.child('sessions').child('current-session'))
        finally:
            self.main.root_ref = previous_root
            self.main.active_session_id = previous_session
            self.main.detection_service = original_service
