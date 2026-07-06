"""schema v1

Revision ID: 0001_schema_v1
Revises:
Create Date: 2026-07-06
"""

from alembic import op

revision = "0001_schema_v1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE device_descriptors (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    content         JSONB NOT NULL,
    content_hash    BYTEA NOT NULL UNIQUE,
    inserted_by     TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE descriptor_activations (
    id              BIGSERIAL PRIMARY KEY,
    lineage         TEXT NOT NULL DEFAULT 'default',
    descriptor_id   BIGINT NOT NULL REFERENCES device_descriptors(id),
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL
);

CREATE TABLE calibration_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    parent_id       BIGINT REFERENCES calibration_snapshots(id),
    parameter_set   JSONB NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,
    published_by    TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (parent_id, parameter_set)
);

CREATE TABLE snapshot_activations (
    id              BIGSERIAL PRIMARY KEY,
    lineage         TEXT NOT NULL DEFAULT 'default',
    snapshot_id     BIGINT NOT NULL REFERENCES calibration_snapshots(id),
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL
);

CREATE TABLE accepted_jobs (
    job_uuid        UUID PRIMARY KEY,
    user_id         TEXT NOT NULL,
    template_name   TEXT NOT NULL,
    parameters      JSONB NOT NULL,
    descriptor_id   BIGINT NOT NULL REFERENCES device_descriptors(id),
    snapshot_id     BIGINT NOT NULL REFERENCES calibration_snapshots(id),
    state           TEXT NOT NULL CHECK (state IN ('pending','dequeued','rejected','cancelled','blocked_calibration')),
    submitted_at    TIMESTAMPTZ NOT NULL,
    cancel_requested_at TIMESTAMPTZ,
    cancel_requested_by TEXT,
    cancel_effective_at TIMESTAMPTZ,
    idempotency_key TEXT NOT NULL,
    request_hash    BYTEA NOT NULL,
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE runs (
    run_uuid        UUID PRIMARY KEY,
    job_uuid        UUID NOT NULL REFERENCES accepted_jobs(job_uuid),
    user_id         TEXT NOT NULL,
    template_name   TEXT NOT NULL,
    parameters      JSONB NOT NULL,
    snapshot_id     BIGINT NOT NULL REFERENCES calibration_snapshots(id),
    descriptor_id   BIGINT NOT NULL REFERENCES device_descriptors(id),
    state           TEXT NOT NULL CHECK (state IN ('submitted','validated','planned','armed','executing','committing','completed','failed','unsafe','aborted','disarmed','rejected')),
    submitted_at    TIMESTAMPTZ NOT NULL,
    execution_started_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    cancel_requested_by TEXT,
    cancel_effective_at TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    durability_tier TEXT NOT NULL CHECK (durability_tier IN ('v1-dev_non_durable','v1-lab_durable')),
    idempotency_key TEXT NOT NULL
);

CREATE TABLE shots (
    shot_uuid       UUID PRIMARY KEY,
    run_uuid        UUID NOT NULL REFERENCES runs(run_uuid),
    shot_index      INT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('prepared','armed','executing','raw_spooled','metadata_mirrored','replicated','committed','commit_pending','failed','raw_lost','safety_trip','unsafe')),
    raw_state       TEXT NOT NULL CHECK (raw_state IN ('raw_spooled','metadata_mirrored','replicated','lost')),
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    timing          JSONB,
    analysis        JSONB,
    safety_state    JSONB,
    durability_tier TEXT NOT NULL CHECK (durability_tier IN ('v1-dev_non_durable','v1-lab_durable')),
    UNIQUE (run_uuid, shot_index)
);

CREATE TABLE raw_manifests (
    shot_uuid       UUID PRIMARY KEY REFERENCES shots(shot_uuid),
    file_path       TEXT NOT NULL,
    sha256          BYTEA NOT NULL,
    byte_count      BIGINT NOT NULL,
    replicas_ack    JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX shots_run_idx   ON shots (run_uuid, shot_index);
CREATE INDEX shots_state_idx ON shots (state) WHERE state <> 'committed';
CREATE INDEX descact_lineage_idx ON descriptor_activations (lineage, activated_at DESC);
CREATE INDEX snapact_lineage_idx ON snapshot_activations (lineage, activated_at DESC);

INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by, notes)
VALUES (NOW(), '{}', '\\x00', 'bootstrap', 'v1-dev placeholder descriptor');
INSERT INTO descriptor_activations (descriptor_id, activated_by) VALUES (1, 'bootstrap');
INSERT INTO calibration_snapshots (parent_id, parameter_set, published_at, published_by, notes)
VALUES (NULL, '{}', NOW(), 'bootstrap', 'v1-dev empty snapshot');
INSERT INTO snapshot_activations (snapshot_id, activated_by) VALUES (1, 'bootstrap');
"""
    )


def downgrade() -> None:
    op.execute(
        """
DROP INDEX IF EXISTS snapact_lineage_idx;
DROP INDEX IF EXISTS descact_lineage_idx;
DROP INDEX IF EXISTS shots_state_idx;
DROP INDEX IF EXISTS shots_run_idx;
DROP TABLE IF EXISTS raw_manifests;
DROP TABLE IF EXISTS shots;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS accepted_jobs;
DROP TABLE IF EXISTS snapshot_activations;
DROP TABLE IF EXISTS calibration_snapshots;
DROP TABLE IF EXISTS descriptor_activations;
DROP TABLE IF EXISTS device_descriptors;
"""
    )
