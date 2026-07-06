"""Tower orchestrator skeleton: dequeue -> run record -> FSM advancement."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from orchestrator.run_fsm import RunState, run_can_transition


class IllegalTransition(Exception):
    pass


class Orchestrator:
    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def dequeue_for_execution(self) -> uuid.UUID | None:
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            job = conn.execute(
                sa.text(
                    "UPDATE accepted_jobs SET state = 'dequeued'"
                    " WHERE job_uuid = ("
                    "   SELECT job_uuid FROM accepted_jobs WHERE state = 'pending'"
                    "   ORDER BY submitted_at, job_uuid LIMIT 1 FOR UPDATE SKIP LOCKED"
                    " )"
                    " RETURNING job_uuid, user_id, template_name, parameters,"
                    " descriptor_id, snapshot_id, submitted_at, idempotency_key"
                )
            ).one_or_none()
            if job is None:
                return None

            run_uuid = uuid.uuid4()
            parameters = (
                job.parameters
                if isinstance(job.parameters, str)
                else json.dumps(dict(job.parameters))
            )
            conn.execute(
                sa.text(
                    "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                    " snapshot_id, descriptor_id, state, submitted_at, execution_started_at,"
                    " durability_tier, idempotency_key)"
                    " VALUES (:run_uuid, :job_uuid, :user_id, :template_name,"
                    " CAST(:parameters AS jsonb), :snapshot_id, :descriptor_id, :state,"
                    " :submitted_at, :execution_started_at, :durability_tier, :idempotency_key)"
                ),
                {
                    "run_uuid": str(run_uuid),
                    "job_uuid": str(job.job_uuid),
                    "user_id": job.user_id,
                    "template_name": job.template_name,
                    "parameters": parameters,
                    "snapshot_id": job.snapshot_id,
                    "descriptor_id": job.descriptor_id,
                    "state": RunState.SUBMITTED.value,
                    "submitted_at": job.submitted_at,
                    "execution_started_at": now,
                    "durability_tier": "v1-dev_non_durable",
                    "idempotency_key": job.idempotency_key,
                },
            )
        return run_uuid

    def run_state(self, run_uuid: uuid.UUID) -> RunState:
        with self.engine.connect() as conn:
            state = conn.execute(
                sa.text("SELECT state FROM runs WHERE run_uuid = :run_uuid"),
                {"run_uuid": str(run_uuid)},
            ).scalar_one()
        return RunState(state)

    def advance(self, run_uuid: uuid.UUID, to: RunState) -> None:
        with self.engine.begin() as conn:
            current = RunState(
                conn.execute(
                    sa.text(
                        "SELECT state FROM runs WHERE run_uuid = :run_uuid FOR UPDATE"
                    ),
                    {"run_uuid": str(run_uuid)},
                ).scalar_one()
            )
            if not run_can_transition(current, to):
                raise IllegalTransition(f"{current} -> {to}")
            conn.execute(
                sa.text("UPDATE runs SET state = :state WHERE run_uuid = :run_uuid"),
                {"state": to.value, "run_uuid": str(run_uuid)},
            )

    def validate(self, run_uuid: uuid.UUID) -> None:
        self.advance(run_uuid, RunState.VALIDATED)

    def cancel_run(self, run_uuid: uuid.UUID, requested_by: str) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            current = RunState(
                conn.execute(
                    sa.text(
                        "SELECT state FROM runs WHERE run_uuid = :run_uuid FOR UPDATE"
                    ),
                    {"run_uuid": str(run_uuid)},
                ).scalar_one()
            )
            if current in (RunState.SUBMITTED, RunState.VALIDATED, RunState.PLANNED):
                target = RunState.REJECTED
            elif current is RunState.ARMED:
                target = RunState.DISARMED
            elif current is RunState.EXECUTING:
                target = RunState.ABORTED
            else:
                return False

            conn.execute(
                sa.text(
                    "UPDATE runs SET state = :state, cancel_requested_at = :now,"
                    " cancel_requested_by = :requested_by, cancel_effective_at = :now"
                    " WHERE run_uuid = :run_uuid"
                ),
                {
                    "state": target.value,
                    "now": now,
                    "requested_by": requested_by,
                    "run_uuid": str(run_uuid),
                },
            )
        return True

    def list_runs(self, limit: int = 20) -> list[tuple[uuid.UUID, str, str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT run_uuid, state, template_name, user_id FROM runs"
                    " ORDER BY execution_started_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).all()
        return [
            (uuid.UUID(str(r.run_uuid)), r.state, r.template_name, r.user_id)
            for r in rows
        ]
