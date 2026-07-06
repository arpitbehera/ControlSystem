"""Run + shot state machines from PLAN-V2 section 04."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    PLANNED = "planned"
    ARMED = "armed"
    EXECUTING = "executing"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNSAFE = "unsafe"
    ABORTED = "aborted"
    DISARMED = "disarmed"
    REJECTED = "rejected"


_RUN_EDGES: set[tuple[RunState, RunState]] = {
    (RunState.SUBMITTED, RunState.VALIDATED),
    (RunState.SUBMITTED, RunState.REJECTED),
    (RunState.VALIDATED, RunState.PLANNED),
    (RunState.VALIDATED, RunState.REJECTED),
    (RunState.PLANNED, RunState.ARMED),
    (RunState.PLANNED, RunState.REJECTED),
    (RunState.ARMED, RunState.EXECUTING),
    (RunState.ARMED, RunState.DISARMED),
    (RunState.EXECUTING, RunState.COMMITTING),
    (RunState.EXECUTING, RunState.ABORTED),
    (RunState.COMMITTING, RunState.COMPLETED),
    (RunState.COMMITTING, RunState.FAILED),
    (RunState.COMMITTING, RunState.UNSAFE),
}


class ShotState(StrEnum):
    PREPARED = "prepared"
    ARMED = "armed"
    EXECUTING = "executing"
    RAW_SPOOLED = "raw_spooled"
    METADATA_MIRRORED = "metadata_mirrored"
    REPLICATED = "replicated"
    COMMITTED = "committed"
    COMMIT_PENDING = "commit_pending"
    FAILED = "failed"
    RAW_LOST = "raw_lost"
    SAFETY_TRIP = "safety_trip"
    UNSAFE = "unsafe"


_SHOT_EDGES: set[tuple[ShotState, ShotState]] = {
    (ShotState.PREPARED, ShotState.ARMED),
    (ShotState.ARMED, ShotState.EXECUTING),
    (ShotState.ARMED, ShotState.SAFETY_TRIP),
    (ShotState.EXECUTING, ShotState.RAW_SPOOLED),
    (ShotState.EXECUTING, ShotState.FAILED),
    (ShotState.EXECUTING, ShotState.RAW_LOST),
    (ShotState.EXECUTING, ShotState.SAFETY_TRIP),
    (ShotState.RAW_SPOOLED, ShotState.METADATA_MIRRORED),
    (ShotState.RAW_SPOOLED, ShotState.COMMIT_PENDING),
    (ShotState.RAW_SPOOLED, ShotState.RAW_LOST),
    (ShotState.METADATA_MIRRORED, ShotState.REPLICATED),
    (ShotState.METADATA_MIRRORED, ShotState.COMMIT_PENDING),
    (ShotState.METADATA_MIRRORED, ShotState.RAW_LOST),
    (ShotState.REPLICATED, ShotState.COMMITTED),
    (ShotState.COMMIT_PENDING, ShotState.METADATA_MIRRORED),
    (ShotState.COMMIT_PENDING, ShotState.REPLICATED),
    (ShotState.COMMIT_PENDING, ShotState.COMMITTED),
    (ShotState.SAFETY_TRIP, ShotState.UNSAFE),
}


def run_can_transition(a: RunState, b: RunState) -> bool:
    return (a, b) in _RUN_EDGES


def shot_can_transition(a: ShotState, b: ShotState) -> bool:
    return (a, b) in _SHOT_EDGES
