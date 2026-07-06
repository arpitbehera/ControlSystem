import os
import uuid
from collections.abc import Iterator

import grpc
import pytest
from typer.testing import CliRunner

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator
from orchestrator.db import make_engine
from orchestrator.grpc_server import serve_scheduler

pytestmark = pytest.mark.integration

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:test@localhost:5432/controlsystem",
)
runner = CliRunner()


@pytest.fixture()
def server() -> Iterator[grpc.Server]:
    engine = make_engine(URL)
    srv = serve_scheduler(
        AdmissionValidator(engine, frozenset({"noop_template"})),
        Orchestrator(engine),
        port=50072,
    )
    try:
        yield srv
    finally:
        srv.stop(grace=None).wait(timeout=5)


def test_submit_run_prints_job_uuid(server: grpc.Server) -> None:
    from dashboards.operator_cli.main import app

    result = runner.invoke(
        app,
        [
            "submit-run",
            "--user",
            "op",
            "--template",
            "noop_template",
            "--params",
            "{}",
            "--key",
            uuid.uuid4().hex,
            "--port",
            "50072",
        ],
    )
    assert result.exit_code == 0
    assert "accepted job_uuid=" in result.output


def test_submit_bad_template_exits_nonzero(server: grpc.Server) -> None:
    from dashboards.operator_cli.main import app

    result = runner.invoke(
        app,
        [
            "submit-run",
            "--user",
            "op",
            "--template",
            "nope",
            "--params",
            "{}",
            "--key",
            uuid.uuid4().hex,
            "--port",
            "50072",
        ],
    )
    assert result.exit_code == 1
    assert "template_not_allowed" in result.output
