"""Scheduler gRPC surface for admission and Tower run control."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from concurrent import futures
from typing import Any, cast

import grpc

from proto_gen import lifecycle_pb2, run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator


class SchedulerService(scheduler_pb2_grpc.SchedulerServicer):
    def __init__(
        self, validator: AdmissionValidator, orchestrator: Orchestrator
    ) -> None:
        self.validator = validator
        self.orchestrator = orchestrator

    def Enqueue(
        self, request: run_model_pb2.RunRequest, context: Any
    ) -> run_model_pb2.EnqueueResponse:
        raw_parameters = json.loads(request.parameters_json or "{}")
        parameters = cast(
            dict[str, object],
            raw_parameters if isinstance(raw_parameters, dict) else {},
        )
        requested_descriptor_id = (
            request.requested_descriptor_id
            if request.HasField("requested_descriptor_id")
            else None
        )
        result = self.validator.enqueue(
            user=request.user,
            template_name=request.template_name,
            parameters=parameters,
            idempotency_key=request.idempotency_key,
            requested_descriptor_id=requested_descriptor_id,
        )
        if not result.accepted:
            return run_model_pb2.EnqueueResponse(
                rejected=run_model_pb2.Rejection(
                    code=result.rejection_code or "rejected",
                    reason=result.rejection_reason or "",
                )
            )

        return run_model_pb2.EnqueueResponse(
            accepted=run_model_pb2.AcceptedJob(
                job_uuid=str(result.job_uuid),
                request=request,
                descriptor_id=result.descriptor_id or 0,
                snapshot_id=result.snapshot_id or 0,
                request_hash=result.request_hash or b"",
            )
        )

    def Cancel(
        self, request: run_model_pb2.CancelRequest, context: Any
    ) -> run_model_pb2.CancelResponse:
        target = uuid.UUID(request.target)
        if request.target_kind == "job":
            ok = self.validator.cancel_pending(
                target, requested_by=request.requested_by
            )
            return run_model_pb2.CancelResponse(
                ok=ok,
                state="cancelled" if ok else "",
                error="" if ok else "not pending",
            )

        ok = self.orchestrator.cancel_run(target, requested_by=request.requested_by)
        state = self.orchestrator.run_state(target).value if ok else ""
        return run_model_pb2.CancelResponse(
            ok=ok,
            state=state,
            error="" if ok else "not cancellable",
        )

    def ListRuns(
        self, request: scheduler_pb2.ListRunsRequest, context: Any
    ) -> scheduler_pb2.ListRunsResponse:
        rows = self.orchestrator.list_runs(limit=request.limit or 20)
        return scheduler_pb2.ListRunsResponse(
            runs=[
                scheduler_pb2.RunRow(
                    run_uuid=str(run_uuid),
                    state=state,
                    template_name=template_name,
                    user=user,
                )
                for run_uuid, state, template_name, user in rows
            ]
        )

    def Status(
        self, request: lifecycle_pb2.StatusRequest, context: Any
    ) -> Iterator[lifecycle_pb2.StatusEvent]:
        while context is None or context.is_active():
            yield lifecycle_pb2.StatusEvent(
                service_id="scheduler",
                state="RUNNING",
                kind="heartbeat",
                wall_ns=time.time_ns(),
            )
            time.sleep(1.0)


def serve_scheduler(
    validator: AdmissionValidator, orchestrator: Orchestrator, port: int
) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    scheduler_pb2_grpc.add_SchedulerServicer_to_server(  # type: ignore[no-untyped-call]
        SchedulerService(validator, orchestrator), server
    )
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    return server
