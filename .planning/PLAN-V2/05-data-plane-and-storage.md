# 05 — Data Plane and Storage

The data plane carries bulk payloads — raw EMCCD frames, raw GigE camera images, SLM phase patterns, HDF5 records. Default rule: **bulk stays on the host that owns it**. Movement happens only on a separate, asynchronous schedule from the run.

This document defines the *durable shot-commit protocol* that prevents the failure modes flagged by critique F-05 (raw without metadata, metadata without raw, or both lost in a single failure).

## Data path summary

| Producer | Path on the wire | Destination |
|---|---|---|
| Andor iXon (CameraLink) | BitFlow Axion 1xB → GPUDirect → RTX 4000 Ada VRAM | Stays on Tower; never network-traverses |
| GigE cameras (ProEM, DMK ×4) | VLAN 20 → ThinkCentre | Stays on ThinkCentre; HDF5 written locally |
| USB cameras (CS165MU1, PCO Pixelfly) | USB → ThinkCentre | Same |
| SLM | HDMI on Mini | Never leaves Mini |
| OPX `stream_processing` outputs (small) | TCP via QM router → Tower broker | Small per-shot arrays; written into shot HDF5 |

## Per-shot storage shape

Each shot produces:

1. **One raw HDF5 file** under `<lake>/YYYY/MM/DD/<run_uuid>/shot_<index>.h5` with datasets:
   - `image_andor_initial`, `image_andor_final` (uint16) — EMCCD frames before the first and after the last rearrangement loop. A shot runs **≤ 2 rearrangement loops**; only these two endpoints are persisted (no per-loop series).
   - `image_<aux>` (per GigE / USB camera that participated)
   - `occupation_matrix_initial`, `occupation_matrix_final` (uint8, from in-shot classifier) — matched to the initial/final frames.
   - `qua_outputs/<stream_name>` (small QUA `stream_processing` arrays)
   - HDF5 attributes: `shot_uuid`, `run_uuid`, `shot_index`, `snapshot_id`, `descriptor_id`, `execution_bundle_id`, `qm_config_hash`, `code_commit_sha`, `safety_state_on_exit`, `producer_versions` (jsonb)
2. **One row in `shots`** with the same IDs, indexed.
3. **One row in `raw_manifests`** with `(shot_uuid, file_path, sha256, byte_count, replicas_acknowledged)`.

Storage container choice (HDF5-per-shot vs chunked HDF5 vs Zarr) is **not frozen** in this plan. Per critique F-13, an empirical benchmark in Phase 5 selects the container behind a stable schema-versioned manifest. The IDs, attribute names, and `raw_manifest` shape are the contract; the container is implementation.

## Durable shot-commit protocol

This is the protocol the broker and data-lake writer run for every shot. It addresses critique F-05.

```
Time ────────────────────────────────────────────────────────────────►

[Broker]      capture → classify → submit RT
                  │
                  ├── on RtJobResult ──┐
                  │                    ▼
                  │           encode raw payload + manifest
                  │                    │ fsync()
                  │           [local durable spool on Tower NVMe]
                  │                    │
                  ├─ ShotResult{raw_manifest, …} ─► [Orchestrator on Tower] ─► [Postgres on EliteDesk]
                  │     (local IPC, same host)            │                          │
                  │                                       │ (after local-durable     │ BEGIN TX
                  │                                       │  spool fsync above, the  │   INSERT shots
                  │                                       │  shot is already         │   INSERT raw_manifests
                  │                                       │  recoverable: state      │   raw_state='pending'
                  │                                       │  raw_spooled)            │ COMMIT
                  │                                       │                          │
                  │                                       └─ mirrors to DB ──────────┘
                  │                                            shot now also durable in DB mirror
                  │                                            (raw on Tower spool only)
                  │
[Data-lake writer]         consume spool → write into lake dir
                                    │ fsync() + sha256 verify
                                    │
                                    ├── replicate to off-host target ──► [Off-host backup]
                                    │                                            │
                                    │                                            │ ack
                                    │ ◄──────────────────────────────────────────┘
                                    │
                                    ├── gRPC: ConfirmReplicated(shot_uuid)
                                    ▼
                                                 UPDATE shots SET raw_state='lake'
                                                 (only after off-host ack received)
```

Failure modes covered:
- **Broker dies after fsync but before gRPC**: on restart, the broker re-reads the spool and replays the `ShotResult` gRPC, using `shot_uuid` as idempotency key. The scheduler dedupes.
- **Orchestrator process dies before mirroring**: the shot is already `raw_spooled` (locally durable on Tower); on restart the orchestrator re-reads the spool and replays the DB mirror, `shot_uuid` as idempotency key.
- **Postgres / EliteDesk unreachable (cross-host partition)**: the shot stays locally durable as `raw_spooled`; the orchestrator buffers the DB mirror and replays it when Postgres returns. Run execution continues — run/shot state is Tower-local-authoritative, the DB is the mirror (see 04 run-FSM authority note). No data loss; the DB simply lags.
- **Tower disk fails after gRPC but before lake write**: shot row is in DB with `raw_state='pending'` and a manifest hash. The off-host replica is the recovery source — if not yet ack'd, the shot is marked `raw_lost` via operator workflow.
- **Off-host replica delayed**: shots stay `raw_state='pending'` until ack. Spool is retained.

RPO / RTO targets (to be hardened in Phase 3):

| Failure | RPO (worst-case data loss) | RTO (time to recovery) |
|---|---|---|
| Tower spool disk fails before lake write | 1 shot in flight | ≤ 30 min |
| EliteDesk Postgres fails | 0 (broker buffers) | ≤ 30 min |
| Off-host replica fails | 0 (local lake retained) | ≤ 24 h (delayed off-host sync) |
| Lab switch fails | 0 (all writes local) | ≤ 30 min |
| Building power loss | spool fsync = guarantee | ≤ 4 h |

## Postgres schema (load-bearing tables)

```sql
-- Hardware descriptors (versioned, never overwritten)
CREATE TABLE device_descriptors (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    content         JSONB NOT NULL,         -- channels, geometry, timing, bounds, safety
    content_hash    BYTEA NOT NULL UNIQUE,
    inserted_by     TEXT NOT NULL,
    notes           TEXT
);
-- NOTE: descriptors are immutable. "Which descriptor is active" is NOT a column on
-- this table (no valid_until — that would mutate an immutable row, per ADR-0003).
-- Currency lives in the append-only descriptor_activations pointer log below.

-- Calibration DAG definitions (recipe)
CREATE TABLE dag_nodes (
    name            TEXT PRIMARY KEY,
    inputs          JSONB NOT NULL,
    outputs         JSONB NOT NULL,
    template_name   TEXT NOT NULL,
    max_age_s       DOUBLE PRECISION NOT NULL,
    fitness_check   TEXT NOT NULL,
    version         INT NOT NULL
);

-- Each node execution = one candidate
CREATE TABLE calibration_executions (
    id              BIGSERIAL PRIMARY KEY,
    dag_node_name   TEXT NOT NULL REFERENCES dag_nodes(name),
    parent_id       BIGINT REFERENCES calibration_executions(id),
    run_uuid        UUID NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL,
    raw_result      JSONB,
    fitness         TEXT NOT NULL CHECK (fitness IN ('pass','marginal','fail','pending')),
    fitness_reason  TEXT
);

-- Immutable typed values produced by a passing execution
CREATE TABLE parameter_versions (
    id              BIGSERIAL PRIMARY KEY,
    parameter_name  TEXT NOT NULL,
    value           JSONB NOT NULL,
    produced_by     BIGINT NOT NULL REFERENCES calibration_executions(id),
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Snapshots = immutable published sets of parameter_version IDs
CREATE TABLE calibration_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    parent_id       BIGINT REFERENCES calibration_snapshots(id),
    parameter_set   JSONB NOT NULL,         -- {parameter_name: parameter_version_id}
    published_at    TIMESTAMPTZ NOT NULL,
    published_by    TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (parent_id, parameter_set)
);

-- Currency pointers (validity model, replaces valid_until intervals — ADR-0003).
-- Append-only: "active" = the latest activation row per lineage. Immutable snapshot/
-- descriptor rows are never mutated; only a new pointer row is appended. Validity
-- intervals are derivable (a row is active until the next activation in its lineage)
-- without storing or mutating any interval. Concurrent publishes serialize on the
-- append and the latest wins atomically.
CREATE TABLE snapshot_activations (
    id              BIGSERIAL PRIMARY KEY,
    lineage         TEXT NOT NULL DEFAULT 'default',   -- supports parallel lineages later
    snapshot_id     BIGINT NOT NULL REFERENCES calibration_snapshots(id),
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL
);
CREATE TABLE descriptor_activations (
    id              BIGSERIAL PRIMARY KEY,
    lineage         TEXT NOT NULL DEFAULT 'default',
    descriptor_id   BIGINT NOT NULL REFERENCES device_descriptors(id),
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by    TEXT NOT NULL
);

-- Bundle of compiled artifacts + environment (critique F-14)
CREATE TABLE execution_bundles (
    id              BIGSERIAL PRIMARY KEY,
    qua_program     BYTEA NOT NULL,
    qm_config       BYTEA NOT NULL,
    qm_config_hash  BYTEA NOT NULL UNIQUE,
    lockfile        TEXT NOT NULL,          -- Python env lock
    firmware        JSONB NOT NULL,         -- QOP version, OPX server build, etc.
    code_commit_sha BYTEA NOT NULL,
    worktree_dirty  BOOLEAN NOT NULL,
    classifier_model_hash BYTEA,            -- rearrangement classifier weights (NULL if none)
    cuda_kernel_hash      BYTEA,            -- compiled CUDA kernel build (NULL if CPU path)
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE runs (
    run_uuid        UUID PRIMARY KEY,
    user_id         TEXT NOT NULL,
    template_name   TEXT NOT NULL,
    parameters      JSONB NOT NULL,
    snapshot_id     BIGINT NOT NULL REFERENCES calibration_snapshots(id),
    descriptor_id   BIGINT NOT NULL REFERENCES device_descriptors(id),
    bundle_id       BIGINT NOT NULL REFERENCES execution_bundles(id),
    state           TEXT NOT NULL,          -- run state machine
    submitted_at    TIMESTAMPTZ NOT NULL,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    idempotency_key TEXT NOT NULL,
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE shots (
    shot_uuid       UUID PRIMARY KEY,
    run_uuid        UUID NOT NULL REFERENCES runs(run_uuid),
    shot_index      INT NOT NULL,
    state           TEXT NOT NULL,          -- shot state machine
    raw_state       TEXT NOT NULL CHECK (raw_state IN ('pending','lake','lost')),
    status          TEXT NOT NULL,          -- ok/failed/skipped/aborted/unsafe
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    timing          JSONB,                  -- PPU ticks
    analysis        JSONB,                  -- control-relevant analysis
    safety_state    JSONB,
    UNIQUE (run_uuid, shot_index)
);

CREATE TABLE raw_manifests (
    shot_uuid       UUID PRIMARY KEY REFERENCES shots(shot_uuid),
    file_path       TEXT NOT NULL,
    sha256          BYTEA NOT NULL,
    byte_count      BIGINT NOT NULL,
    replicas_ack    JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX shots_run_idx          ON shots (run_uuid, shot_index);
CREATE INDEX shots_state_idx        ON shots (state) WHERE state <> 'committed';
CREATE INDEX calexec_node_idx       ON calibration_executions (dag_node_name, generated_at DESC);
CREATE INDEX paramver_name_idx      ON parameter_versions (parameter_name, inserted_at DESC);
CREATE INDEX snapact_lineage_idx    ON snapshot_activations (lineage, activated_at DESC);
CREATE INDEX descact_lineage_idx    ON descriptor_activations (lineage, activated_at DESC);
```

Notes:
- `parameter_versions` is append-only. The "current" view is computed via `calibration_snapshots`, never by latest timestamp.
- `calibration_snapshots` and `device_descriptors` are immutable and append-only. Currency is **not** a column on those tables; the active row is the latest entry in `snapshot_activations` / `descriptor_activations` for the lineage. No row is ever mutated or deleted (per ADR-0003 — `valid_until` interval-closing was rejected as a mutation that loses concurrent-publication safety).
- `execution_bundles` is the answer to critique F-14: every shot can be reconstructed from one bundle row + one snapshot + one descriptor.

## Backup and replication

| Target | Method | Frequency | Retention |
|---|---|---|---|
| Postgres WAL | streaming replication to off-host (NAS or USB rotation) | continuous | 30 days |
| Postgres logical | `pg_dump` to off-host | nightly | 30 days |
| Raw data lake | rsync to off-host | continuous (async per-shot) | indefinite (capacity-limited) |
| Switch config (`copy running-config tftp:`) | TFTP server on EliteDesk + git commit | nightly | 30 days |
| Router config (`/export file=`) | SCP from EliteDesk + git commit | nightly | 30 days |
| Execution bundles | inline in Postgres | per run | indefinite |

Test restore quarterly. Record elapsed time. If restore exceeds RTO target, redesign.

## Off-host target options

The off-host replica is the failure-domain boundary that makes durability real. Three viable options (pick one in Phase 0):

1. **Institutional NAS** (if available): primary recommendation; integrates with existing backup policies.
2. **USB rotation pair**: two external 12 TB drives in hot-swap dock; alternating weekly; offsite copy monthly. Cheap, works on Windows, requires operator discipline.
3. **Second always-on host on a separate UPS circuit**: gives synchronous replication; adds another machine to maintain.

Choice is recorded in §13 (ADRs).

## What this does *not* do

- No cloud storage in v1 (non-goal in `PROJECT.md`).
- No long-term tape archival in v1; raw lake on disk + off-host replica is the durability boundary.
- No real-time analytics database (InfluxDB / TimescaleDB) in v1. Postgres with JSON columns suffices for relational provenance (critique-doc §3.4 reasoning). Add timeseries if/when drift dashboards demand it.
