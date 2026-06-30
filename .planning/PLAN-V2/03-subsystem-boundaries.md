# 03 — Subsystem Boundaries

## Why boundaries are the deliverable

Per `amo-control-system-design.md` §3.10, the *seams* are the durable 5+ year contracts. Implementations inside a layer can be rewritten every 2–3 years; the boundary between layers cannot, because every analysis script, dashboard, and adapter built across the lifetime of the lab will read them.

This document defines, for each pair of adjacent layers, **who owns what**, **what flows across**, and **what is explicitly out of scope**.

## L0 ↔ L1 — Physics ↔ RT

| Owner | Responsibility |
|---|---|
| L0 | Atoms, lasers, optics, vacuum, AOD physical assembly, RF amplifiers |
| L1 | All electrical signals that interact with L0 on a *timed* basis |

Crossings:
- L1 → L0: analog out (AOD chirps), digital gates (shutters, gate pulses), DC bias outputs.
- L0 → L1: EMCCD trigger acks, photodiode signals into OPX analog inputs.

Out of scope at this boundary:
- No L0 hardware change can require a Python redeploy. Cabling and physical configuration are documented separately in `network/hardware_inventory.md` (to be created in Phase 0).

## L1 ↔ L2 — RT ↔ Device-Server

Owner of timed execution: **OPX+ PPU**. Owner of non-timed device control: **L2 device services**.

Contract direction is **L2 → L1**: device services submit compiled jobs and consume results. The OPX is never "called into" mid-execution from outside the input-stream channel.

```python
# L2 → L1 submission contract
@dataclass(frozen=True)
class RtJobSubmission:
    qua_program_blob: bytes        # protobuf-serialized compiled QUA
    qm_config_hash: str            # SHA-256 of the QmConfig used
    snapshot_id: int               # FK to calibration_snapshots
    descriptor_id: int             # FK to device_descriptors
    execution_bundle_id: int       # FK to execution_bundle
    input_stream_seed: Mapping[str, bytes]  # initial payloads if any
    expected_outputs: list[str]    # which stream_processing outputs to surface
    deadline_ticks: int            # PPU-clock deadline; missed → rt_timeout
    safety_token: SafetyToken      # signed by Layer 4 after descriptor validation
    run_uuid: UUID

# L1 → L2 result contract
@dataclass(frozen=True)
class RtJobResult:
    run_uuid: UUID
    shot_index: int
    outputs: Mapping[str, np.ndarray]
    timing: Mapping[str, int]      # PPU ticks: arm, first-output, total
    status: Literal["ok", "rt_error", "rt_timeout", "safety_trip"]
    safety_state_on_exit: SafetyState
```

The `safety_token` is the gate. The compiler at L4 attaches it only after the run passes descriptor validation, parameter bounds, and rate limits. The broker refuses any `RtJobSubmission` whose `safety_token` is missing or expired. Safety plane behavior is in §09.

In-shot rearrangement messages are a special case of this seam — see §07 for the `RearrangementBatchV1` wire format.

Out of scope at this boundary:
- The PPU is never reached except through `RtJobSubmission` + input streams. No `qua_machine.set_dc_offset(...)` calls from device services during armed/executing runs.
- Device services never read the PPU clock directly. The OPX is the timing root; clients consume timing metadata via `RtJobResult.timing`.

## L2 ↔ L3 — Device-Server ↔ Persistence

L2 produces:
- Per-shot rows for `shots` table (DB).
- HDF5 raw blobs into the local spool, then into the data lake.
- Heartbeat + health events.

L3 owns:
- Postgres schema (single source of truth for metadata).
- Raw data lake on Tower 12 TB HDD + off-host replica.
- Append-only `parameter_versions`; never-mutated `calibration_snapshots`.
- WAL replication to off-host backup.

Crossings:
- **Durable shot commit** (the protocol that protects against critique F-05):
  1. Broker writes raw payload + manifest + checksum to local durable spool. `fsync`.
  2. Broker pushes shot record (with manifest hash) to scheduler via gRPC.
  3. Scheduler writes shots row inside a transaction that also inserts the raw-manifest pointer.
  4. Data-lake writer drains the spool to the data lake; updates `shots.raw_state` from `pending` → `lake` once the off-host replica acknowledges.
  5. Replica-acknowledged shots become eligible for spool eviction; un-acknowledged shots are retained.
- **Calibration publication** (the transactional path per critique F-04):
  1. Calibration node runs → produces candidate `calibration_execution` row.
  2. `fitness_check` runs → marks candidate `passed` / `marginal` / `failed`.
  3. On `passed`, a new `calibration_snapshot` row is inserted in one transaction that closes the previous snapshot's `valid_until` and references the new `parameter_versions` set.
  4. Failed candidates never become a snapshot; downstream nodes are not run on a failed upstream (critique F-16).

Out of scope:
- L2 never writes to `calibration_snapshots` or `device_descriptors`. Only the calibration DAG runner (L5) does, via a Postgres role that excludes L2 services.

## L3 ↔ L4 — Persistence ↔ Compiler

L4 reads the *current* snapshot and the *current* descriptor; it produces a compiled artifact. L3 records the artifact and the IDs it consumed.

```python
class DeviceDescriptor:
    """Pasqal-shaped immutable description of physical constraints."""
    id: int
    valid_from: datetime
    channels: Mapping[str, ChannelSpec]   # per AOD axis, per laser, per camera
    geometry: ArraySpec                   # max atoms, lattice constants
    timing: TimingSpec                    # min slice, jitter budgets, deadline floors
    bounds: list[Bound]                   # "AOD freq in [80, 120] MHz", "RF power < X dBm"
    safety: SafetyDescriptor              # interlock channels, safe-state actions

class CalibrationSnapshot:
    """Immutable published set of parameter versions."""
    id: int
    parent_id: int | None
    generated_at: datetime
    parameter_versions: Mapping[str, int]   # name → parameter_version row id
    publishing_node: str | None
    publishing_run_uuid: UUID | None

class CompiledRun:
    qua_program_blob: bytes
    qm_config_blob: bytes
    qm_config_hash: str
    non_rt_plan: Mapping[str, list[NonRtInstruction]]   # per device-server queue
    snapshot_id: int
    descriptor_id: int
    execution_bundle_id: int
    safety_token: SafetyToken
```

The compiler **rejects-at-submit** on any descriptor violation (Pulser-shaped, P7). Rejections happen *before* the device-server queue sees a submission.

Out of scope:
- L4 never executes runs. It produces artifacts; L5 dispatches them.
- L4 has no opinion on calibration freshness. Freshness is a scheduler concern (L5).

## L4 ↔ L5 — Compiler ↔ Scheduler

The scheduler talks in `Runs` and `CalibrationDAGTraversals`. Both compile to the same `CompiledRun` artifact at L4 — a calibration is a run with a node-typed template.

```python
class RunRequest:
    user: str
    template_name: str                 # e.g. "rydberg_blockade_demo"
    parameters: Mapping[str, JSON]     # scanned + fixed
    required_calibration: list[str] | None
    idempotency_key: str               # operator-provided, dedup'd by scheduler

class DagNode:
    name: str
    inputs: list[str]                  # registry params consumed
    outputs: list[str]                 # registry params updated
    template_name: str
    max_age_s: float                   # staleness threshold
    fitness_check: str                 # named callable

class DagTraversal:
    nodes: list[DagNode]
    layers: list[list[str]]            # topo-sorted
    snapshot_publication_policy: Literal["per_node", "per_traversal", "manual"]
```

Out of scope at this boundary:
- The scheduler does not know how to compile QUA. It asks L4.
- The compiler does not know what calibration is *fresh*. It receives a `snapshot_id` from L5.

## L5 ↔ L6 — Scheduler ↔ UI / Users

Two channels:

1. **Operator CLI / lab-terminal dashboard** (write-capable). Authenticates via OS user → Postgres role mapping. Available verbs constrained by role (see §04 §3.3 access matrix).
2. **Off-lab read-only browser dashboard**. Static front-end + FastAPI backend on EliteDesk. Reads Postgres replica only. No mutating verbs reachable.

Out of scope:
- No browser-based control UI in v1 (anti-pattern A19). A browser cannot be in the experiment thread.
- No WebSocket "live-control" channels in v1. Live updates are polling-based with debouncing.

## Cross-cutting concerns

### Safety plane
Independent of all layers; not subordinate to any of them. See §09. Safety can inhibit RF / AOD / shutters regardless of which layer is running.

### Provenance plane
Cuts across L1–L5. Every shot row references one `execution_bundle_id`, one `snapshot_id`, one `descriptor_id`, one `qm_config_hash`, one `code_commit_sha`. Every dashboard query and every analysis script reads through this chain.

### Observability plane
Structured logs from every service into a single sink (in v1: rotating log files on each host; in v2: OpenTelemetry exporter). Per-shot timing metrics in `shots.timing` JSON column. Per-DAG-traversal trace IDs in `calibration_executions`.
