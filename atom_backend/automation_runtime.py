"""Firebase-backed runtime for the single physical Zone 1 LED."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from zone1_automation import Zone1Automation


DEFAULT_SETTINGS = {
    'on_debounce_seconds': 2,
    'off_debounce_seconds': 2,
    'stale_after_seconds': 15,
}


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()


class Zone1AutomationRuntime:
    def __init__(
        self,
        root_ref: Any,
        emit_command: Callable[[str, str], Awaitable[None]],
    ) -> None:
        self._root = root_ref
        self._emit_command = emit_command
        self.settings = dict(DEFAULT_SETTINGS)
        self._policy = self._new_policy()

    def _new_policy(self) -> Zone1Automation:
        return Zone1Automation(**self.settings)

    async def load(self) -> dict[str, float]:
        stored = self._root.child('automation').child('zone1').get() or {}
        settings = await self.configure(stored, persist_missing=False)
        status = self._root.child('occupancy_status').get() or {}
        appliance = self._root.child('appliances').child('led1').get() or {}
        detected_at = status.get('detected_at') if isinstance(status, dict) else None
        try:
            last_observed_at = _epoch(detected_at) if isinstance(detected_at, str) else None
        except ValueError:
            last_observed_at = None
        last_requested = appliance.get('state') if isinstance(appliance, dict) else None
        self._policy.restore(last_observed_at=last_observed_at, last_requested=last_requested)
        return settings

    async def configure(self, settings: dict[str, Any], *, persist_missing: bool = True) -> dict[str, float]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update({key: settings[key] for key in DEFAULT_SETTINGS if key in settings})
        normalized = {key: float(value) for key, value in merged.items()}
        if any(value < 0 for value in normalized.values()):
            raise ValueError('automation timing values must be zero or greater')
        self.settings = normalized
        last_observed_at = self._policy.last_observed_at
        last_requested = self._policy._last_requested
        self._policy = self._new_policy()
        self._policy.restore(last_observed_at=last_observed_at, last_requested=last_requested)
        if persist_missing:
            self._root.child('automation').child('zone1').set(normalized)
        return normalized

    def current_mode(self) -> str:
        mode = str(self._root.child('mode').get() or 'automatic').strip().lower().replace(' ', '_')
        if mode not in {'automatic', 'human_override', 'hybrid'}:
            return 'automatic'
        return mode

    async def observe(self, counts: dict[str, Any], timestamp: str) -> None:
        # This demo has one real GPIO23 LED only: any person in the active
        # camera view represents occupancy for the physical Zone 1 light.
        people_detected = sum(int(value or 0) for value in counts.values())
        action = self._policy.observe(
            self.current_mode(), people_detected, observed_at=_epoch(timestamp)
        )
        if action:
            delivered = await self._emit_command(action.desired_state, action.reason)
            if delivered is False:
                self._policy.mark_request_failed(action.desired_state)

    async def check_stale(self) -> None:
        action = self._policy.stale_action(
            self.current_mode(), now=datetime.now(timezone.utc).timestamp()
        )
        if action:
            delivered = await self._emit_command(action.desired_state, action.reason)
            if delivered is False:
                self._policy.mark_request_failed(action.desired_state)

    def note_manual_command(self, state: str) -> None:
        if self.current_mode() == 'hybrid':
            self._policy.note_manual_command(state)
