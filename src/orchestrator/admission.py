"""Admission Validator/Submitter role from ADR-0001."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa

from orchestrator.db import active_descriptor_id, active_snapshot_id


def _request_hash(
    *,
    template_name: str,
    parameters: dict[str, object],
    requested_descriptor_id: int | None,
) -> bytes:
    payload = {
        "template_name": template_name,
        "parameters": parameters,
        "requested_descriptor_id": requested_descriptor_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    job_uuid: uuid.UUID | None = None
    descriptor_id: int | None = None
    snapshot_id: int | None = None
    request_hash: bytes | None = None
    rejection_code: str | None = None
    rejection_reason: str | None = None


class AdmissionValidator:
    def __init__(self, engine: sa.Engine, template_allowlist: frozenset[str]) -> None:
        self.engine = engine
        self.template_allowlist = template_allowlist

    def enqueue(
        self,
        user: str,
        template_name: str,
        parameters: dict[str, object],
        idempotency_key: str,
        requested_descriptor_id: int | None = None,
    ) -> AdmissionResult:
        if template_name not in self.template_allowlist:
            return AdmissionResult(
                accepted=False,
                rejection_code="template_not_allowed",
                rejection_reason=f"template '{template_name}' is not on the allow-list",
            )

        req_hash = _request_hash(
            template_name=template_name,
            parameters=parameters,
            requested_descriptor_id=requested_descriptor_id,
        )

        with self.engine.begin() as conn:
            existing = conn.execute(
                sa.text(
                    "SELECT job_uuid, descriptor_id, snapshot_id, request_hash FROM accepted_jobs"
                    " WHERE user_id = :user_id AND idempotency_key = :idempotency_key"
                ),
                {"user_id": user, "idempotency_key": idempotency_key},
            ).one_or_none()
            if existing is not None:
                if bytes(existing.request_hash) != req_hash:
                    return AdmissionResult(
                        accepted=False,
                        rejection_code="idempotency_key_reused",
                        rejection_reason="idempotency key already used for a different payload",
                    )
                return AdmissionResult(
                    accepted=True,
                    job_uuid=uuid.UUID(str(existing.job_uuid)),
                    descriptor_id=existing.descriptor_id,
                    snapshot_id=existing.snapshot_id,
                    request_hash=req_hash,
                )

            if requested_descriptor_id is not None:
                found = conn.execute(
                    sa.text(
                        "SELECT id FROM device_descriptors WHERE id = :descriptor_id"
                    ),
                    {"descriptor_id": requested_descriptor_id},
                ).scalar()
                if found is None:
                    return AdmissionResult(
                        accepted=False,
                        rejection_code="descriptor_not_found",
                        rejection_reason=f"descriptor {requested_descriptor_id} does not exist",
                    )
                descriptor_id: int | None = requested_descriptor_id
            else:
                descriptor_id = active_descriptor_id(conn)

            snapshot_id = active_snapshot_id(conn)
            if descriptor_id is None or snapshot_id is None:
                return AdmissionResult(
                    accepted=False,
                    rejection_code="no_active_pointers",
                    rejection_reason="no active descriptor or snapshot activation exists",
                )

            job_uuid = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO accepted_jobs (job_uuid, user_id, template_name, parameters,"
                    " descriptor_id, snapshot_id, state, submitted_at, idempotency_key,"
                    " request_hash)"
                    " VALUES (:job_uuid, :user_id, :template_name, CAST(:parameters AS jsonb),"
                    " :descriptor_id, :snapshot_id, 'pending', :submitted_at, :idempotency_key,"
                    " :request_hash)"
                ),
                {
                    "job_uuid": str(job_uuid),
                    "user_id": user,
                    "template_name": template_name,
                    "parameters": json.dumps(parameters, sort_keys=True),
                    "descriptor_id": descriptor_id,
                    "snapshot_id": snapshot_id,
                    "submitted_at": datetime.now(UTC),
                    "idempotency_key": idempotency_key,
                    "request_hash": req_hash,
                },
            )

        return AdmissionResult(
            accepted=True,
            job_uuid=job_uuid,
            descriptor_id=descriptor_id,
            snapshot_id=snapshot_id,
            request_hash=req_hash,
        )

    def cancel_pending(self, job_uuid: uuid.UUID, requested_by: str) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            updated = conn.execute(
                sa.text(
                    "UPDATE accepted_jobs SET state = 'cancelled',"
                    " cancel_requested_at = :now, cancel_requested_by = :requested_by,"
                    " cancel_effective_at = :now"
                    " WHERE job_uuid = :job_uuid AND state = 'pending'"
                ),
                {"job_uuid": str(job_uuid), "requested_by": requested_by, "now": now},
            )
            return updated.rowcount == 1
