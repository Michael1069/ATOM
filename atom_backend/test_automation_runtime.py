import asyncio
import unittest


class Reference:
    def __init__(self, value=None):
        self.value = value if value is not None else {}

    def child(self, name):
        if not isinstance(self.value, dict):
            self.value = {}
        if name not in self.value:
            self.value[name] = {}
        return ReferenceProxy(self.value, name)


class ReferenceProxy:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name

    def child(self, name):
        value = self.parent.setdefault(self.name, {})
        if not isinstance(value, dict):
            value = self.parent[self.name] = {}
        value.setdefault(name, {})
        return ReferenceProxy(value, name)

    def get(self):
        return self.parent.get(self.name)

    def set(self, value):
        self.parent[self.name] = value


class AutomationRuntimeTests(unittest.TestCase):
    def test_runtime_emits_a_zone1_command_and_persists_editable_settings(self):
        from automation_runtime import Zone1AutomationRuntime

        root = Reference({'mode': 'automatic', 'automation': {'zone1': {
            'on_debounce_seconds': 0,
            'off_debounce_seconds': 0,
            'stale_after_seconds': 10,
        }}})
        emitted = []

        async def emit(state, reason):
            emitted.append((state, reason))

        runtime = Zone1AutomationRuntime(root, emit)
        asyncio.run(runtime.load())
        asyncio.run(runtime.observe({'zone1': 1, 'zone2': 99}, '2026-11-12T10:00:00+00:00'))

        self.assertEqual(emitted, [('on', 'zone1_on_after_debounce')])
        self.assertEqual(root.value['automation']['zone1']['stale_after_seconds'], 10)

    def test_restart_restores_a_stale_on_state_and_requests_safe_off(self):
        from automation_runtime import Zone1AutomationRuntime

        root = Reference({
            'mode': 'automatic',
            'occupancy_status': {'detected_at': '2020-01-01T00:00:00+00:00'},
            'appliances': {'led1': {'state': 'on'}},
        })
        emitted = []

        async def emit(state, reason):
            emitted.append((state, reason))

        runtime = Zone1AutomationRuntime(root, emit)
        asyncio.run(runtime.load())
        asyncio.run(runtime.check_stale())

        self.assertEqual(emitted, [('off', 'zone1_feed_stale_fail_safe')])
    def test_editing_settings_keeps_the_stale_feed_protection_active(self):
        from automation_runtime import Zone1AutomationRuntime

        root = Reference({
            'mode': 'automatic',
            'occupancy_status': {'detected_at': '2020-01-01T00:00:00+00:00'},
            'appliances': {'led1': {'state': 'on'}},
        })
        emitted = []

        async def emit(state, reason):
            emitted.append((state, reason))

        runtime = Zone1AutomationRuntime(root, emit)
        asyncio.run(runtime.load())
        asyncio.run(runtime.configure({'on_debounce_seconds': 3, 'off_debounce_seconds': 3, 'stale_after_seconds': 15}))
        asyncio.run(runtime.check_stale())

        self.assertEqual(emitted, [('off', 'zone1_feed_stale_fail_safe')])
