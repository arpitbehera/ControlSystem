"""Lifecycle FSM shared by every managed device service (PLAN-V2 section 04).

Disarm semantics follow section 04 prose, risk B13, and ADR-0017: disarm forces
re-Configure before the next Arm and always returns to UNINIT. Direct
RUNNING->disarm is emergency teardown only; graceful cancel uses stop first.
Safe-default enforcement belongs in adapter on_disarm hooks, not in this FSM.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeviceState(StrEnum):
    UNINIT = "UNINIT"
    CONFIGURED = "CONFIGURED"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


class Verb(StrEnum):
    CONFIGURE = "configure"
    ARM = "arm"
    START = "start"
    STOP = "stop"
    DISARM = "disarm"


@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    state: DeviceState
    noop: bool = False
    error: str | None = None


_TRANSITIONS: dict[tuple[DeviceState, Verb], DeviceState] = {
    (DeviceState.UNINIT, Verb.CONFIGURE): DeviceState.CONFIGURED,
    (DeviceState.CONFIGURED, Verb.ARM): DeviceState.ARMED,
    (DeviceState.ARMED, Verb.START): DeviceState.RUNNING,
    (DeviceState.RUNNING, Verb.STOP): DeviceState.STOPPED,
    (DeviceState.CONFIGURED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.ARMED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.RUNNING, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.STOPPED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.FAULT, Verb.DISARM): DeviceState.UNINIT,
}

_NOOPS: set[tuple[DeviceState, Verb]] = {
    (DeviceState.CONFIGURED, Verb.CONFIGURE),
    (DeviceState.ARMED, Verb.ARM),
    (DeviceState.RUNNING, Verb.START),
    (DeviceState.STOPPED, Verb.STOP),
    (DeviceState.UNINIT, Verb.DISARM),
}


class LifecycleFsm:
    def __init__(self) -> None:
        self.state: DeviceState = DeviceState.UNINIT
        self._fault_detail: str | None = None

    def apply(self, verb: Verb) -> TransitionResult:
        if (self.state, verb) in _NOOPS:
            return TransitionResult(ok=True, state=self.state, noop=True)

        target = _TRANSITIONS.get((self.state, verb))
        if target is None:
            return TransitionResult(
                ok=False,
                state=self.state,
                error=f"verb '{verb}' invalid in state '{self.state}'",
            )

        self.state = target
        if target is DeviceState.UNINIT:
            self._fault_detail = None
        return TransitionResult(ok=True, state=self.state)

    def fault(self, detail: str) -> None:
        self.state = DeviceState.FAULT
        self._fault_detail = detail
