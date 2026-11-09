import importlib
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
