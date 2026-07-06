from orchestrator.run_fsm import (
    RunState,
    ShotState,
    run_can_transition,
    shot_can_transition,
)


def test_run_happy_path() -> None:
    path = [
        RunState.SUBMITTED,
        RunState.VALIDATED,
        RunState.PLANNED,
        RunState.ARMED,
        RunState.EXECUTING,
        RunState.COMMITTING,
        RunState.COMPLETED,
    ]
    for a, b in zip(path, path[1:]):
        assert run_can_transition(a, b), f"{a}->{b}"


def test_run_rejection_edges() -> None:
    for state in [RunState.SUBMITTED, RunState.VALIDATED, RunState.PLANNED]:
        assert run_can_transition(state, RunState.REJECTED)
    assert not run_can_transition(RunState.EXECUTING, RunState.REJECTED)


def test_run_terminal_states_are_terminal() -> None:
    for terminal in [
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.UNSAFE,
        RunState.ABORTED,
        RunState.REJECTED,
    ]:
        for target in RunState:
            assert not run_can_transition(terminal, target)


def test_run_abort_only_from_executing() -> None:
    assert run_can_transition(RunState.EXECUTING, RunState.ABORTED)
    assert not run_can_transition(RunState.ARMED, RunState.ABORTED)
    assert run_can_transition(RunState.ARMED, RunState.DISARMED)


def test_shot_happy_path_and_commit_pending() -> None:
    assert shot_can_transition(ShotState.EXECUTING, ShotState.RAW_SPOOLED)
    assert shot_can_transition(ShotState.RAW_SPOOLED, ShotState.METADATA_MIRRORED)
    assert shot_can_transition(ShotState.METADATA_MIRRORED, ShotState.REPLICATED)
    assert shot_can_transition(ShotState.REPLICATED, ShotState.COMMITTED)
    assert shot_can_transition(ShotState.RAW_SPOOLED, ShotState.COMMIT_PENDING)
    assert shot_can_transition(ShotState.METADATA_MIRRORED, ShotState.COMMIT_PENDING)


def test_shot_safety_trip_leads_to_unsafe_only() -> None:
    assert shot_can_transition(ShotState.EXECUTING, ShotState.SAFETY_TRIP)
    assert shot_can_transition(ShotState.SAFETY_TRIP, ShotState.UNSAFE)
    assert not shot_can_transition(ShotState.SAFETY_TRIP, ShotState.COMMITTED)
