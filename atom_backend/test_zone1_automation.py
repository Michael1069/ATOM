import unittest


class Zone1AutomationTests(unittest.TestCase):
    def test_automatic_mode_turns_on_only_after_zone1_is_stably_occupied(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=2, off_debounce_seconds=2, stale_after_seconds=10)

        self.assertIsNone(automation.observe('automatic', 1, observed_at=0))
        self.assertEqual(automation.observe('automatic', 1, observed_at=2).desired_state, 'on')

    def test_other_zones_never_drive_the_physical_led(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=0, off_debounce_seconds=0, stale_after_seconds=10)

        self.assertEqual(automation.observe('automatic', 1, observed_at=0).desired_state, 'on')
        self.assertIsNone(automation.observe('automatic', 1, observed_at=1, other_zone_total=20))

    def test_human_override_never_generates_an_automatic_command(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=0, off_debounce_seconds=0, stale_after_seconds=10)

        self.assertIsNone(automation.observe('human_override', 2, observed_at=0))

    def test_hybrid_manual_hold_releases_on_the_next_zone1_transition(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=0, off_debounce_seconds=0, stale_after_seconds=10)
        automation.observe('automatic', 0, observed_at=0)
        automation.note_manual_command('off')

        self.assertEqual(automation.observe('hybrid', 1, observed_at=1).desired_state, 'on')

    def test_stale_feed_fails_safe_to_off_after_a_previous_on_command(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=0, off_debounce_seconds=0, stale_after_seconds=5)
        self.assertEqual(automation.observe('automatic', 1, observed_at=0).desired_state, 'on')
        self.assertEqual(automation.stale_action('automatic', now=6).desired_state, 'off')

    def test_failed_stale_off_can_be_retried(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=0, off_debounce_seconds=0, stale_after_seconds=5)
        automation.observe('automatic', 1, observed_at=0)
        self.assertEqual(automation.stale_action('automatic', now=6).desired_state, 'off')
        automation.mark_request_failed('off')

        self.assertEqual(automation.stale_action('automatic', now=7).desired_state, 'off')

    def test_fresh_feed_after_a_stale_gap_must_debounce_again(self):
        from zone1_automation import Zone1Automation

        automation = Zone1Automation(on_debounce_seconds=2, off_debounce_seconds=2, stale_after_seconds=5)
        automation.observe('automatic', 1, observed_at=0)
        automation.stale_action('automatic', now=6)

        self.assertIsNone(automation.observe('automatic', 1, observed_at=7))


class EnergyModelTests(unittest.TestCase):
    def test_energy_is_unavailable_without_user_supplied_wattage(self):
        from zone1_automation import apply_reported_switch_state

        energy = apply_reported_switch_state({}, reported_state='on', reported_at='2026-11-12T10:00:00+00:00')

        self.assertIsNone(energy['estimated_wh'])
        self.assertEqual(energy['on_since'], '2026-11-12T10:00:00+00:00')

    def test_energy_uses_reported_switch_timestamps_not_requested_commands(self):
        from zone1_automation import apply_reported_switch_state

        energy = apply_reported_switch_state(
            {'rated_watts': 5, 'on_since': '2026-11-12T10:00:00+00:00', 'cumulative_on_seconds': 0},
            reported_state='off',
            reported_at='2026-11-12T10:30:00+00:00',
        )

        self.assertEqual(energy['cumulative_on_seconds'], 1800)
        self.assertEqual(energy['estimated_wh'], 2.5)

    def test_model_energy_tracks_an_automatic_command_when_the_led_has_no_ack(self):
        from zone1_automation import apply_modeled_switch_state

        energy = apply_modeled_switch_state(
            {'rated_watts': 5}, modeled_state='on', modeled_at='2026-11-12T17:00:00+00:00'
        )
        energy = apply_modeled_switch_state(
            energy, modeled_state='off', modeled_at='2026-11-12T17:01:00+00:00'
        )

        self.assertEqual(energy['modeled_cumulative_on_seconds'], 60)
        self.assertEqual(energy['modeled_estimated_wh'], 0.083333)
