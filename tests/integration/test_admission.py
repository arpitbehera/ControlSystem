import os
import uuid

import pytest
import sqlalchemy as sa

from orchestrator.admission import AdmissionValidator
from orchestrator.db import make_engine

pytestmark = pytest.mark.integration

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:test@localhost:5432/controlsystem",
)
ALLOW = frozenset({"noop_template", "rydberg_blockade_demo"})


@pytest.fixture()
def validator() -> AdmissionValidator:
    return AdmissionValidator(make_engine(URL), template_allowlist=ALLOW)


def _key() -> str:
    return uuid.uuid4().hex


def test_accept_pins_active_descriptor_and_snapshot(
    validator: AdmissionValidator,
) -> None:
    res = validator.enqueue("op", "noop_template", {"n": 1}, _key())
    assert res.accepted
    assert res.descriptor_id is not None and res.snapshot_id is not None
    with validator.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT state, descriptor_id, snapshot_id FROM accepted_jobs WHERE job_uuid = :j"
            ),
            {"j": str(res.job_uuid)},
        ).one()
    assert row.state == "pending"
    assert (row.descriptor_id, row.snapshot_id) == (res.descriptor_id, res.snapshot_id)


def test_reject_unknown_template(validator: AdmissionValidator) -> None:
    res = validator.enqueue("op", "not_a_template", {}, _key())
    assert not res.accepted and res.rejection_code == "template_not_allowed"


def test_idempotency_dedup_returns_same_job(validator: AdmissionValidator) -> None:
    key = _key()
    first = validator.enqueue("op", "noop_template", {}, key)
    second = validator.enqueue("op", "noop_template", {}, key)
    assert second.accepted and second.job_uuid == first.job_uuid


def test_idempotency_key_reuse_with_different_payload_rejected(
    validator: AdmissionValidator,
) -> None:
    key = _key()
    first = validator.enqueue("op", "noop_template", {"n": 1}, key)
    second = validator.enqueue("op", "noop_template", {"n": 2}, key)
    assert first.accepted
    assert not second.accepted
    assert second.rejection_code == "idempotency_key_reused"


def test_requested_descriptor_must_exist(validator: AdmissionValidator) -> None:
    res = validator.enqueue(
        "admin", "noop_template", {}, _key(), requested_descriptor_id=999999
    )
    assert not res.accepted and res.rejection_code == "descriptor_not_found"


def test_cancel_pending_records_timestamps(validator: AdmissionValidator) -> None:
    res = validator.enqueue("op", "noop_template", {}, _key())
    assert res.job_uuid is not None
    assert validator.cancel_pending(res.job_uuid, requested_by="op")
    with validator.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT state, cancel_requested_at, cancel_effective_at, cancel_requested_by"
                " FROM accepted_jobs WHERE job_uuid = :j"
            ),
            {"j": str(res.job_uuid)},
        ).one()
    assert row.state == "cancelled"
    assert row.cancel_requested_at is not None and row.cancel_effective_at is not None
    assert row.cancel_requested_by == "op"
