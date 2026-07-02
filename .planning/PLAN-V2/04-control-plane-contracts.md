# 04 — Control-Plane Contracts

The control plane is the orchestrator-to-service backbone. It carries small typed messages and *never* carries bulk payloads. This document defines the on-wire types and the lifecycle protocol.

## Transport

| Property | Choice | Justification |
|---|---|---|
| Wire protocol | **gRPC over TCP** on VLAN 10 | Mature on Windows; native Python + Rust + Go bindings; streaming RPC for events |
| Schema language | **Protocol Buffers (proto3)** | Forward/backward compatible by construction; one source of truth |
| Discovery | **Static registry** in Postgres (`device_services` table) + heartbeats | Avoids a separate service-discovery daemon; v1 lab is small |
| Authentication | mTLS with per-service cert issued by an internal CA on the EliteDesk | Lab-scoped; CA cert distributed manually on Phase 1 deployment |
| Heartbeats | Server-side bidi stream; default 1 Hz; 3-miss timeout | Detects partitions even when TCP RST is delayed |

gRPC is **not** the transport for the rearrangement input-stream. That uses the QM QUA input-stream push API (`push_to_input_stream` in current SDKs; older notes may call this insert/push) directly between broker process and OPX server, on VLAN 50. The gRPC control plane never crosses VLAN 50.

## Lifecycle contract

Every managed device service implements the same eight verbs. Reusable contract tests (`tests/contract/test_lifecycle_contract.py`) drive every service through the FSM with a configurable adapter.

```proto
service ManagedDevice {
  rpc Health(HealthRequest) returns (HealthResponse);
  rpc Capabilities(Empty) returns (Capabilities);
  rpc Configure(ConfigureRequest) returns (ConfigureResponse);
  rpc Arm(ArmRequest) returns (ArmResponse);
  rpc Start(StartRequest) returns (StartResponse);
  rpc Stop(StopRequest) returns (StopResponse);
  rpc Status(StatusRequest) returns (stream StatusEvent);
  rpc Disarm(DisarmRequest) returns (DisarmResponse);
}
```

State machine each service implements:

```
            ┌──────────┐  configure ok   ┌────────────┐
            │  UNINIT  │ ──────────────► │ CONFIGURED │
            └──────────┘                  └─────┬──────┘
                  ▲                              │ arm
                  │ disarm                       ▼
                  │                       ┌────────────┐
                  │                       │   ARMED    │
                  │                       └─────┬──────┘
                  │                              │ start
                  │                              ▼
                  │                       ┌────────────┐
                  │  stop / fault         │  RUNNING   │
                  └──────────────────────┴─────┬──────┘
                                                │ stop ok
                                                ▼
                                         ┌────────────┐
                                         │  STOPPED   │ → disarm → CONFIGURED
                                         └────────────┘
```

Faults are surfaced as `StatusEvent.kind == "fault"`; the orchestrator transitions the service to `UNINIT` after a `Disarm`. Idempotent: re-issuing the same verb in the same state is a no-op success. Submitting `idempotency_key` on `Start` deduplicates retries (critique F-15).

### Capability shape

Capabilities are typed extensions of the base. Service-specific fields live under a oneof.

```proto
message Capabilities {
  string service_id = 1;
  string firmware = 2;
  string driver_version = 3;
  repeated TimingHint timing = 4;     // e.g. "trigger jitter ≤ 1 µs"

  oneof specific {
    CameraCapabilities camera = 10;
    SlmCapabilities slm = 11;
    PowerSupplyCapabilities psu = 12;
    LockCapabilities lock = 13;
    ArduinoCapabilities arduino = 14;
    // …
  }
}
```

Adding a new device family adds a new branch. The base contract does not change.

## Modeled devices (no service of their own)

AOMs, AODs, analog shutters, coils, and bias coils don't expose a network service. They appear in the run model carrying:

- `identity` (e.g. `aom_y_axis_repump`).
- `controller` (which OPX channel pair).
- `calibration_id` (the active snapshot's parameter version for this device).
- `bounds` (frequency / amplitude / phase ranges from the `DeviceDescriptor`).
- `translation_rules` (physical-intent → controller-facing values).

The compiler resolves a modeled-device action into OPX `play()` calls using the active calibration. The `DeviceDescriptor` enforces that no `play` outside the bounds is compilable.

## Run model

```python
@dataclass(frozen=True)
class RunRequest:
    user: str
    template_name: str
    parameters: Mapping[str, JSON]              # scanned and fixed
    required_calibration: list[str] | None      # registry params that must be fresh
    requested_descriptor_id: int | None         # replay/debug/admin only; normal submissions resolve active descriptor
    idempotency_key: str

@dataclass(frozen=True)
class AcceptedJob:
    job_uuid: UUID
    request: RunRequest
    descriptor_id: int                           # pinned at admission
    snapshot_id: int
    submitted_at: datetime                      # accepted into EliteDesk pending queue
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancel_effective_at: datetime | None = None

@dataclass(frozen=True)
class RunPlan:
    run_uuid: UUID
    job: AcceptedJob
    snapshot_id: int
    descriptor_id: int
    execution_bundle_id: int
    compiled: CompiledRun
    shot_schedule: list[ShotSpec]               # per-shot parameter resolution
    estimated_duration_s: float
    execution_started_at: datetime              # Tower begins executing dequeued job
    validation_token: ValidationToken
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancel_effective_at: datetime | None = None

@dataclass(frozen=True)
class ShotResult:
    shot_uuid: UUID
    run_uuid: UUID
    shot_index: int
    status: Literal["ok", "failed", "skipped", "aborted", "unsafe"]
    raw_manifest: RawManifest                   # hashes + paths into local spool
    rt_outputs: Mapping[str, np.ndarray]        # small QUA stream outputs only
    analysis_outputs: Mapping[str, JSON]        # control-relevant outputs only
    timing: Mapping[str, int]
    safety_state_on_exit: SafetyState

@dataclass(frozen=True)
class RunSummary:
    run_uuid: UUID
    status: Literal["completed", "failed", "aborted", "unsafe"]
    shot_count: int
    shots_ok: int
    duration_s: float
    snapshot_id: int
    descriptor_id: int
    execution_bundle_id: int
    durability_tier: Literal["v1-dev_non_durable", "v1-lab_durable"]
    notes: list[str]
```

Cancel target shape:

```python
@dataclass(frozen=True)
class CancelRequest:
    target: UUID                                # job_uuid or run_uuid
    target_kind: Literal["job", "run"]
    requested_by: str
    requested_at: datetime
    reason: str | None
```

`ShotResult` carries only the *control-relevant* analysis output — atom counts, fidelity estimates, conditional-branch readouts. Bulk images stay in the raw lake; the result references them via `raw_manifest`.

`durability_tier` is a first-class run/shot property, not a milestone-note convention. Phase 5 Tower-local commissioning runs are labeled `v1-dev_non_durable`; routine `v1-lab` runs are labeled `v1-lab_durable`. Dashboards and exports must show the tier whenever displaying run or shot data.

## Run state machine

Per critique F-15, runs and shots both carry an explicit state machine. The **Tower orchestrator is the authority**: run state is held authoritatively in-process on the Tower and written to a local durable WAL synchronously, then mirrored to Postgres (on the EliteDesk) **eventually-consistently**. A run-state transition never *blocks* on a remote Postgres commit — this is what lets an in-flight run continue when the EliteDesk is unreachable (see 02 failure table). Postgres is the durable history mirror, not the authority. The shot FSM already follows this (`raw_spooled` = locally durable before `committed`).

```
                                            (operator abort)
                                                  │
   submitted → validated → planned → armed → executing → committing → completed
       │           │           │       │          │             │
       │           │           │       │          │             ├─→ failed
       │           │           │       │          │             └─→ unsafe
       │           │           │       │          └─→ aborted
       │           │           │       └─→ disarmed
       │           │           └─→ rejected
       │           └─→ rejected
       └─→ rejected
```

Per-shot state machine (subset):

```
prepared → armed → executing → raw_spooled → metadata_mirrored → replicated → committed
                    │             │              │                 │
                    │             │              │                 ├─→ raw_lost
                    │             │              └─→ commit_pending
                    │             ├─→ failed
                    │             └─→ raw_lost
                    └─→ safety_trip → unsafe
```

`raw_spooled` is the Tower-local durable waypoint — once the broker has fsync'd the raw payload + manifest locally, the shot is recoverable on the Tower even if Postgres has not yet committed. `metadata_mirrored` means the Postgres shot row and raw manifest row exist. `replicated` means the off-host raw replica acknowledged the manifest. `committed` requires both metadata mirrored and off-host raw replication. During an EliteDesk/Postgres outage or replica lag, execution may complete while the shot remains `raw_spooled` or `commit_pending`; UI must show "execution complete, commit pending" rather than "committed."

Cancel routing follows authority ownership:

- `pending` job: EliteDesk marks `accepted_jobs.state = "cancelled"` and records `cancel_requested_at`, `cancel_requested_by`, `cancel_effective_at`.
- `dequeued`, `validated`, `planned`, `armed`, or `executing`: Tower records the cancel request on the run and makes it effective at the next shot boundary. Immediate safe-state is reserved for safety faults, not ordinary user cancel.
- `committing` or terminal states: cancel is rejected as too late or returned idempotently if already terminal.

Every cancel keeps both request time and effective time because queued-job cancellation and in-flight run abortion can be separated by a shot boundary.

## Submission path: admission gateway → authority

Submission is two named stages (ADR-0001):

1. **Admission** (EliteDesk Admission Validator/Submitter): checks the `RunRequest` is well-formed, the caller's role permits the verb (RBAC), the `template_name` is on the allow-list, the active descriptor and active snapshot can be resolved, requested calibrations are fresh at `submitted_at`, and static semantic checks pass. Normal submissions pin the active descriptor. Explicit `requested_descriptor_id` is allowed only for replay/debug/admin flows and must reference an existing immutable descriptor. On pass admission records `submitted_at`, pins `descriptor_id` + `snapshot_id`, and appends an `AcceptedJob` to the EliteDesk pending queue; on stale calibration it blocks enqueue and triggers the calibration DAG; on other fail it rejects before the job can be dequeued for execution.
2. **Compile-validation** (Tower L4, the `submitted → validated` FSM edge): dequeues an `AcceptedJob`, records `execution_started_at`, re-validates the pinned descriptor + snapshot against current authority-side constraints, re-checks requested calibration freshness at `execution_started_at`, compiles, and attaches the `validation_token`. This is authority-side because it needs live hardware state and final bound evaluation. If pinned calibration is stale at execution time, the Tower marks the job `blocked_calibration`, triggers the DAG, and requires resubmission or an explicit user/operator "refresh and rebind" action. If the pinned snapshot is otherwise no longer permitted, the job is rejected/requeued by explicit policy rather than silently rebound to a newer snapshot.

In `v1-dev` the admission queue and scheduler may be co-located on the Tower; the stage boundary is preserved so the `v1-lab` EliteDesk split is a deployment move, not a redesign.

## Run-control verbs

```proto
service Scheduler {
  rpc Enqueue(RunRequest) returns (AcceptedJob);        // called by clients through the admission gateway
  rpc DequeueForExecution(Empty) returns (RunPlan);     // called by the Tower scheduler
  rpc Cancel(CancelRequest) returns (CancelResponse);   // routed to EliteDesk for pending jobs, Tower for active runs
  rpc Status(StatusRequest) returns (stream StatusEvent);
  rpc ListRuns(ListRunsRequest) returns (ListRunsResponse);

  rpc SubmitCalibration(CalibrationDagRequest) returns (DagTraversal);
  rpc PublishSnapshot(PublishRequest) returns (SnapshotResponse);

  rpc AdminPublishDescriptor(DescriptorPublish) returns (DescriptorResponse);  // insert immutable descriptor + append activation; never patches in place
}
```

Idempotency: every mutating verb takes an `idempotency_key`. The scheduler deduplicates by `(user, key)` for 24 h.

## Access control matrix

| Role / Verb | view | read_cal | read_lake | submit_run | cancel_run | publish_snapshot | mutate_descriptor | restart_service | add_user |
|---|---|---|---|---|---|---|---|---|---|
| `analyst` (off-lab, read-only) | ✓ | ✓ | ✓ (replica) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `operator` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `senior_operator` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| `admin` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `agent` (automated) | ✓ (own runs only) | ✓ | ✗ | ✓ (scoped to allow-list) | ✗ | ✗ | ✗ | ✗ | ✗ |

Blast-radius bounds (critique F-17 partial):

1. `mutate_descriptor` inserts a new immutable descriptor row and appends a `descriptor_activations` pointer — it never patches in place. Past shots keep the descriptor they pinned; only future shots see the newly activated one.
2. `publish_snapshot` is transactional and append-only. A wrong calibration cannot retroactively poison existing data.
3. `agent` `submit_run` is restricted to a static allow-list of template names; arbitrary templates require operator countersign.
4. `agent` `view` is scoped to the runs that agent submitted (its own `run_uuid`s) — it can observe its own runs' status/outcome but not the lab-wide run list or other users' runs.

## Heartbeat + timeout policy

| Source | Period | Miss threshold | Action |
|---|---|---|---|
| Device service → orchestrator | 1 s | 3 misses | Mark service `UNHEALTHY`; refuse new arms; drain in-flight at next shot boundary |
| Broker ↔ orchestrator | (intra-Tower) | OS process-liveness | Both run on the Tower (ADR-0001) — this is local supervisor/process monitoring, **not** a network heartbeat. Broker death → orchestrator marks run `unsafe`, requires Disarm-Arm |
| Orchestrator (Tower) ↔ EliteDesk gateway/Postgres | 1 s | 3 misses | The real cross-host link. Miss → block new submissions + pause durable mirror; in-flight run continues (run state is Tower-local) |
| Safety plane → all | hardware watchdog (see §09) | hardware threshold | Independent safe-state action |

## Error taxonomy

| Class | Source | Recovery posture |
|---|---|---|
| `rt_error` | OPX job ran but returned bad outputs | Mark shot failed; continue run; surface to operator |
| `rt_timeout` | PPU deadline exceeded | Mark shot failed; broker forces safe state via `Disarm` |
| `safety_trip` | Independent safety plane fired | Mark run `unsafe`; require operator acknowledgement to clear (critique F-15) |
| `service_unhealthy` | heartbeat miss | Drain run; refuse new |
| `compile_error` | Layer-4 rejected at submit | Reject `RunRequest`; do not enter the queue |
| `validation_error` | Descriptor bound violated | Reject `RunRequest` |
| `transient_io` | Postgres temporarily unavailable, etc. | Retry with backoff, max 3 |
| `unrecoverable_io` | Disk full, OPX server gone | Mark run failed; alert operator |
