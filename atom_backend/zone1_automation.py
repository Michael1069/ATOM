"""Pure Zone 1 automation and acknowledged-state energy helpers.

Only this module decides whether the single low-voltage demonstration LED
should be commanded.  MQTT/Firebase I/O deliberately lives elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AutomationAction:
    desired_state: str
    reason: str


class Zone1Automation:
    """Stateful debounce policy for the one real Zone 1 LED.

    Hybrid mode honours the last manual command until Zone 1's occupied / not
    occupied state changes on a subsequent real observation.  Other zones are
    intentionally absent from this API.
    """

    def __init__(
        self,
        *,
        on_debounce_seconds: float,
        off_debounce_seconds: float,
        stale_after_seconds: float,
    ) -> None:
        self.on_debounce_seconds = max(0.0, float(on_debounce_seconds))
        self.off_debounce_seconds = max(0.0, float(off_debounce_seconds))
        self.stale_after_seconds = max(0.0, float(stale_after_seconds))
        self._candidate_state: str | None = None
        self._candidate_started_at: float | None = None
        self._last_requested: str | None = None
        self._last_observed_at: float | None = None
        self._hybrid_hold = False
        self._hybrid_baseline: str | None = None
        self._last_zone_state: str | None = None

    @property
    def last_observed_at(self) -> float | None:
        return self._last_observed_at

    def note_manual_command(self, state: str) -> None:
        if state not in {'on', 'off'}:
            raise ValueError('state must be on or off')
        self._hybrid_hold = True
        self._hybrid_baseline = self._last_zone_state
        # The next valid hybrid transition reconciles the device with its rule.
        self._last_requested = None

    def restore(self, *, last_observed_at: float | None, last_requested: str | None) -> None:
        """Restore persisted feed/device state after a backend restart."""
        self._last_observed_at = last_observed_at
        self._last_requested = last_requested if last_requested in {'on', 'off'} else None

    def mark_request_failed(self, state: str) -> None:
        if self._last_requested == state:
            self._last_requested = None

    def observe(
        self,
        mode: str,
        zone1_people: int,
        *,
        observed_at: float,
        other_zone_total: int = 0,
    ) -> AutomationAction | None:
        del other_zone_total  # Explicitly prove no other zone can influence LED1.
        if mode not in {'automatic', 'hybrid'}:
            if mode == 'human_override':
                self._last_zone_state = 'on' if int(zone1_people) > 0 else 'off'
                return None
            raise ValueError('mode must be automatic, human_override, or hybrid')

        self._last_observed_at = float(observed_at)
        target = 'on' if int(zone1_people) > 0 else 'off'

        if mode == 'hybrid' and self._hybrid_hold:
            if self._hybrid_baseline is None:
                self._hybrid_baseline = target
                self._last_zone_state = target
                return None
            if target == self._hybrid_baseline:
                self._last_zone_state = target
                return None
            self._hybrid_hold = False
            self._hybrid_baseline = None
            self._candidate_state = None
            self._candidate_started_at = None
            self._last_zone_state = target
            return self._request_if_changed(target, 'hybrid_resumed_after_zone1_transition')

        delay = self.on_debounce_seconds if target == 'on' else self.off_debounce_seconds
        if self._candidate_state != target:
            self._candidate_state = target
            self._candidate_started_at = float(observed_at)
            self._last_zone_state = target
            if delay > 0:
                return None
        if self._candidate_started_at is None:
            self._candidate_started_at = float(observed_at)
        if float(observed_at) - self._candidate_started_at < delay:
            self._last_zone_state = target
            return None
        self._last_zone_state = target
        return self._request_if_changed(target, f'zone1_{target}_after_debounce')

    def stale_action(self, mode: str, *, now: float) -> AutomationAction | None:
        if mode not in {'automatic', 'hybrid'} or self._last_observed_at is None:
            return None
        if float(now) - self._last_observed_at < self.stale_after_seconds:
            return None
        self._candidate_state = None
        self._candidate_started_at = None
        return self._request_if_changed('off', 'zone1_feed_stale_fail_safe')

    def _request_if_changed(self, desired_state: str, reason: str) -> AutomationAction | None:
        if desired_state == self._last_requested:
            return None
        self._last_requested = desired_state
        return AutomationAction(desired_state=desired_state, reason=reason)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def apply_reported_switch_state(
    energy: dict[str, Any], *, reported_state: str, reported_at: str
) -> dict[str, Any]:
    """Accumulate LED ON time only when an ESP32 state acknowledgement arrives."""
    if reported_state not in {'on', 'off'}:
        raise ValueError('reported_state must be on or off')

    result = dict(energy)
    previous_state = result.get('reported_state') or ('on' if result.get('on_since') else None)
    cumulative = float(result.get('cumulative_on_seconds', 0) or 0)
    on_since = result.get('on_since')

    if previous_state == 'on' and reported_state == 'off' and isinstance(on_since, str):
        elapsed = max(0.0, (_parse_timestamp(reported_at) - _parse_timestamp(on_since)).total_seconds())
        cumulative += elapsed
        on_since = None
    elif previous_state != 'on' and reported_state == 'on':
        on_since = reported_at

    rated_watts = result.get('rated_watts')
    watts = float(rated_watts) if isinstance(rated_watts, (int, float)) and rated_watts > 0 else None
    result.update(
        {
            'reported_state': reported_state,
            'last_changed_at': reported_at,
            'on_since': on_since,
            'cumulative_on_seconds': int(cumulative),
            'modeled_available': watts is not None,
            'estimated_wh': round(watts * cumulative / 3600, 6) if watts is not None else None,
        }
    )
    return result


def apply_modeled_switch_state(
    energy: dict[str, Any], *, modeled_state: str, modeled_at: str
) -> dict[str, Any]:
    """Track the automation run-time estimate separately from ESP32 telemetry."""
    if modeled_state not in {'on', 'off'}:
        raise ValueError('modeled_state must be on or off')

    result = dict(energy)
    previous_state = result.get('modeled_state')
    cumulative = float(result.get('modeled_cumulative_on_seconds', 0) or 0)
    on_since = result.get('modeled_on_since')
    if previous_state == 'on' and modeled_state == 'off' and isinstance(on_since, str):
        elapsed = max(0.0, (_parse_timestamp(modeled_at) - _parse_timestamp(on_since)).total_seconds())
        cumulative += elapsed
        on_since = None
    elif previous_state != 'on' and modeled_state == 'on':
        on_since = modeled_at

    watts = result.get('rated_watts')
    rated_watts = float(watts) if isinstance(watts, (int, float)) and watts > 0 else None
    result.update({
        'modeled_state': modeled_state,
        'modeled_on_since': on_since,
        'modeled_cumulative_on_seconds': int(cumulative),
        'modeled_last_changed_at': modeled_at,
        'modeled_available': rated_watts is not None,
        'modeled_estimated_wh': round(rated_watts * cumulative / 3600, 6) if rated_watts else None,
    })
    return result
