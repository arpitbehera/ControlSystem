import os
import uuid

import pytest

from orchestrator.admission import AdmissionValidator
from orchestrator.core import IllegalTransition, Orchestrator
from orchestrator.db import make_engine
from orchestrator.run_fsm import RunState

pytestmark = pytest.mark.integration

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:test@localhost:5432/controlsystem",
)
ALLOW = frozenset({"noop_template"})


@pytest.fixture()
def stack() -> tuple[AdmissionValidator, Orchestrator]:
    engine = make_engine(URL)
    return AdmissionValidator(engine, ALLOW), Orchestrator(engine)


def test_dequeue_creates_run_from_oldest_pending(
    stack: tuple[AdmissionValidator, Orchestrator],
) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert run_uuid is not None
    assert orch.run_state(run_uuid) is RunState.SUBMITTED


def test_validate_advances_to_validated(
    stack: tuple[AdmissionValidator, Orchestrator],
) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert run_uuid is not None
    orch.validate(run_uuid)
    assert orch.run_state(run_uuid) is RunState.VALIDATED


def test_illegal_transition_raises_and_leaves_state(
    stack: tuple[AdmissionValidator, Orchestrator],
) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert run_uuid is not None
    with pytest.raises(IllegalTransition):
        orch.advance(run_uuid, RunState.EXECUTING)
    assert orch.run_state(run_uuid) is RunState.SUBMITTED


def test_cancel_prevalidated_run_records_timestamps(
    stack: tuple[AdmissionValidator, Orchestrator],
) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert run_uuid is not None
    assert orch.cancel_run(run_uuid, requested_by="op")
    assert orch.run_state(run_uuid) is RunState.REJECTED


def test_empty_queue_returns_none(
    stack: tuple[AdmissionValidator, Orchestrator],
) -> None:
    _, orch = stack
    while orch.dequeue_for_execution() is not None:
        pass
    assert orch.dequeue_for_execution() is None
