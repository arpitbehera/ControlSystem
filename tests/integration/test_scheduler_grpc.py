import os
import uuid
from collections.abc import Iterator

import grpc
import pytest

from proto_gen import run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator
from orchestrator.db import make_engine
from orchestrator.grpc_server import serve_scheduler

pytestmark = pytest.mark.integration

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:test@localhost:5432/controlsystem",
)


@pytest.fixture()
def stub() -> Iterator[scheduler_pb2_grpc.SchedulerStub]:
    engine = make_engine(URL)
    validator = AdmissionValidator(engine, frozenset({"noop_template"}))
    orch = Orchestrator(engine)
    server = serve_scheduler(validator, orch, port=50071)
    channel = grpc.insecure_channel("127.0.0.1:50071")
    try:
        yield scheduler_pb2_grpc.SchedulerStub(channel)
    finally:
        channel.close()
        server.stop(grace=None).wait(timeout=5)


def test_enqueue_returns_accepted_job(stub: scheduler_pb2_grpc.SchedulerStub) -> None:
    resp = stub.Enqueue(
        run_model_pb2.RunRequest(
            user="op",
            template_name="noop_template",
            parameters_json="{}",
            idempotency_key=uuid.uuid4().hex,
        ),
        timeout=5,
    )
    assert resp.WhichOneof("outcome") == "accepted"
    assert resp.accepted.descriptor_id > 0 and resp.accepted.snapshot_id > 0


def test_enqueue_rejection_is_typed(stub: scheduler_pb2_grpc.SchedulerStub) -> None:
    resp = stub.Enqueue(
        run_model_pb2.RunRequest(
            user="op",
            template_name="nope",
            parameters_json="{}",
            idempotency_key=uuid.uuid4().hex,
        ),
        timeout=5,
    )
    assert resp.WhichOneof("outcome") == "rejected"
    assert resp.rejected.code == "template_not_allowed"


def test_cancel_pending_job_over_grpc(stub: scheduler_pb2_grpc.SchedulerStub) -> None:
    accepted = stub.Enqueue(
        run_model_pb2.RunRequest(
            user="op",
            template_name="noop_template",
            parameters_json="{}",
            idempotency_key=uuid.uuid4().hex,
        ),
        timeout=5,
    ).accepted
    resp = stub.Cancel(
        run_model_pb2.CancelRequest(
            target=accepted.job_uuid,
            target_kind="job",
            requested_by="op",
            idempotency_key=uuid.uuid4().hex,
        ),
        timeout=5,
    )
    assert resp.ok and resp.state == "cancelled"


def test_list_runs(stub: scheduler_pb2_grpc.SchedulerStub) -> None:
    resp = stub.ListRuns(scheduler_pb2.ListRunsRequest(limit=5), timeout=5)
    assert resp is not None
