import os
import uuid

import pytest
import sqlalchemy as sa

from orchestrator.db import active_descriptor_id, make_engine

pytestmark = pytest.mark.integration

URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:test@localhost:5432/controlsystem",
)


@pytest.fixture()
def engine() -> sa.Engine:
    return make_engine(URL)


def test_all_v1_tables_exist(engine: sa.Engine) -> None:
    names = sa.inspect(engine).get_table_names()
    for table in [
        "device_descriptors",
        "descriptor_activations",
        "calibration_snapshots",
        "snapshot_activations",
        "accepted_jobs",
        "runs",
        "shots",
        "raw_manifests",
    ]:
        assert table in names, f"missing table {table}"


def test_active_descriptor_is_latest_activation(engine: sa.Engine) -> None:
    h1 = uuid.uuid4().bytes
    h2 = uuid.uuid4().bytes
    with engine.begin() as conn:
        d1 = conn.execute(
            sa.text(
                "INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by)"
                " VALUES (NOW(), '{}', :h1, 'test') RETURNING id"
            ),
            {"h1": h1},
        ).scalar_one()
        d2 = conn.execute(
            sa.text(
                "INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by)"
                " VALUES (NOW(), '{}', :h2, 'test') RETURNING id"
            ),
            {"h2": h2},
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO descriptor_activations (descriptor_id, activated_by)"
                " VALUES (:d, 'test')"
            ),
            {"d": d1},
        )
        conn.execute(
            sa.text(
                "INSERT INTO descriptor_activations (descriptor_id, activated_by)"
                " VALUES (:d, 'test')"
            ),
            {"d": d2},
        )
        assert active_descriptor_id(conn) == d2


def test_runs_reject_bad_durability_tier(engine: sa.Engine) -> None:
    key = f"tier-test-{uuid.uuid4()}"
    with engine.begin() as conn:
        job_uuid = conn.execute(
            sa.text(
                "INSERT INTO accepted_jobs (job_uuid, user_id, template_name, parameters,"
                " descriptor_id, snapshot_id, state, submitted_at, idempotency_key, request_hash)"
                " VALUES (gen_random_uuid(), 'u', 't', '{}', 1, 1, 'pending',"
                " NOW(), :key, :h)"
                " RETURNING job_uuid"
            ),
            {"h": uuid.uuid4().bytes, "key": key},
        ).scalar_one()
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(
                sa.text(
                    "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                    " snapshot_id, descriptor_id, state, submitted_at, durability_tier,"
                    " idempotency_key)"
                    " VALUES (gen_random_uuid(), :j, 'u', 't', '{}', 1, 1,"
                    " 'submitted', NOW(), 'bogus_tier', 'k')"
                ),
                {"j": str(job_uuid)},
            )


def test_runs_reject_bad_state(engine: sa.Engine) -> None:
    key = f"state-test-{uuid.uuid4()}"
    with engine.begin() as conn:
        job_uuid = conn.execute(
            sa.text(
                "INSERT INTO accepted_jobs (job_uuid, user_id, template_name, parameters,"
                " descriptor_id, snapshot_id, state, submitted_at, idempotency_key, request_hash)"
                " VALUES (gen_random_uuid(), 'u', 't', '{}', 1, 1, 'pending',"
                " NOW(), :key, :h)"
                " RETURNING job_uuid"
            ),
            {"h": uuid.uuid4().bytes, "key": key},
        ).scalar_one()
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(
                sa.text(
                    "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                    " snapshot_id, descriptor_id, state, submitted_at, durability_tier,"
                    " idempotency_key)"
                    " VALUES (gen_random_uuid(), :j, 'u', 't', '{}', 1, 1,"
                    " 'teleported', NOW(), 'v1-dev_non_durable', 'k')"
                ),
                {"j": str(job_uuid)},
            )
