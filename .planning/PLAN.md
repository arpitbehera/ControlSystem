# Control System v1 — Starting-Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand the repository up from empty to a **Pre-Phase-1 software-readiness gate**: the control-plane implementation can satisfy the software-side Phase 1 evidence (contracts, lifecycle FSM, contract tests, fake camera, fake OPX lifecycle shell, Postgres schema v1, admission validator, orchestrator skeleton, operator CLI) and the Phase 0A hardware-measurement harness code exists. This does **not** satisfy PLAN-V2 Phase 1 until Phase 0A's hardware gates have passed.

**Architecture:** Modular monolith, `src/` layout per PLAN-V2 §10. Tower is run-execution authority; EliteDesk admission is a separate gRPC seam from day one even though `v1-dev` co-locates everything. Fake-first: every service implements the eight-verb lifecycle contract and passes one shared contract-test suite before any real hardware code exists. Phase 0A harness scripts are written now, executed later in the lab.

**Tech Stack:** Python 3.14 (`>=3.14,<3.15`), gRPC + proto3 (`grpcio`, `grpcio-tools`), PostgreSQL 16 + SQLAlchemy 2.x + Alembic + psycopg3, pytest + pytest-cov, ruff + black + mypy --strict, typer CLI, uv for lockfile.

**Spec:** `.planning/architecture/` (authoritative) and `.planning/PRD.md` (distillation). Where this plan simplifies, PLAN-V2 wins.

**Phase naming reconciliation:** PLAN-V2 §00 marks the long-lived control contracts as the things to preserve, while PLAN-V2 §12 makes Phase 0A a safety- and measurement-motivated prerequisite before entering Phase 1. This plan resolves that tension by producing software readiness only: control-plane contracts can be reviewed and exercised, but RT contract freezing, `N_MAX_MOVES`, the latency budget, process discipline, and safety-plane independence remain blocked on W0A-1...W0A-5. No PLAN-V2 gate is weakened.

## Global Constraints

- Python `>=3.14,<3.15`; choose the latest supported CPython series allowed by `qm-qua` (`>=3.10,<3.15`) for the longest available support horizon. All runtime code must work on Windows (no POSIX-only APIs on runtime paths; `pathlib` everywhere; dev on WSL/Linux is fine).
- Python is **never** in the hard-timing loop; all timed actions are QUA on the OPX+ PPU (PLAN-V2 §06).
- Lifecycle verbs are exactly `health, capabilities, configure, arm, start, stop, status, disarm` — additive evolution only, never renamed (PLAN-V2 §00 freeze list).
- Run model type names are exactly `RunRequest`, `AcceptedJob`, `RunPlan`, `ShotResult`, `RunSummary` (PLAN-V2 §04).
- DB column names and HDF5 attribute names are frozen at v1 — additive only, renaming forbidden (risk B14).
- `durability_tier` values are exactly `v1-dev_non_durable` and `v1-lab_durable` (PLAN-V2 §04/§05).
- Immutable tables (`device_descriptors`, `calibration_snapshots`) never get `valid_until` or UPDATEs; currency lives only in append-only `*_activations` logs (ADR-0003).
- `mypy --strict`, `ruff`, `black` on `src/orchestrator/`, `src/compiler/`, `src/device_servers/`, `src/broker/`, contracts; coverage gate 80% on those packages (PLAN-V2 §10).
- Every mutating verb takes an `idempotency_key`; payload-bearing lifecycle verbs dedup device-locally by `(verb, key, request_hash)`, while scheduler/admission mutations dedup by `(user, key, request_hash)`. Key reuse in the same scope with a different canonical request hash is a typed rejection (`idempotency_key_reused`), never silent reuse. `Stop` and `Disarm` are state-idempotent only; stale keys must never suppress `on_disarm`.
- Commit after every green test cycle; Conventional Commits format.

**Deviation resolved in ADR-0017:** PLAN-V2 §04's FSM diagram showed `STOPPED → disarm → CONFIGURED`, while the §04 prose and risk B13 say `Disarm` returns the service to `UNINIT` and forces re-`Configure` before the next `Arm`. This plan implements the canonical semantics: `disarm` from any of `CONFIGURED / ARMED / RUNNING / STOPPED / FAULT` → `UNINIT`; idempotent no-op at `UNINIT`. Direct `RUNNING → disarm` is emergency abort / E-stop / watchdog only; graceful cancel uses shot-boundary `stop → STOPPED → disarm`. The adapter's `on_disarm` hook, not the FSM, enforces descriptor-defined `safe_default` from every entry state. No driver-cached state survives a disarm.

**Prerequisite note (Task 7+):** integration tests need Docker with `postgres:16`. Start it with the exact command given in Task 7.

---

### Task 1: Repository bootstrap

**Files:**
- Create: `pyproject.toml`, `.gitignore` (extend), `README.md`
- Create: `src/orchestrator/__init__.py`, `src/compiler/__init__.py`, `src/descriptor/__init__.py`, `src/calibration/__init__.py`, `src/broker/__init__.py`, `src/device_servers/__init__.py`, `src/device_servers/_base/__init__.py`, `src/safety/__init__.py`, `src/dashboards/__init__.py`, `src/proto_gen/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/contract/__init__.py`, `tests/integration/__init__.py`, `tests/fault_injection/__init__.py`, `tests/hardware/README.md`
- Create: `proto/.gitkeep`, `schema/.gitkeep`, `network/.gitkeep`, `ops/runbooks/.gitkeep`, `.planning/adr/.gitkeep`
- Create: `.planning/adr/0001-execution-authority-and-broker-placement.md`, `.planning/adr/0016-gpu-mutex-locality.md`, `.planning/adr/0017-lifecycle-disarm-returns-uninit.md`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing (greenfield).
- Produces: installable package set (`uv sync` works); `pytest` collects; `ruff`/`black`/`mypy` run clean on empty packages. All later tasks assume this layout.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "controlsystem"
version = "0.1.0"
description = "AMO neutral-atom lab control system (PLAN-V2 v1)"
requires-python = ">=3.14,<3.15"
dependencies = [
    "grpcio>=1.62",
    "protobuf>=4.25",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.1",
    "typer>=0.12",
    "numpy>=1.26",
]

[dependency-groups]
dev = [
    "grpcio-tools>=1.62",
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.4",
    "black>=24",
    "mypy>=1.10",
    "types-protobuf",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = [
    "src/orchestrator", "src/compiler", "src/descriptor", "src/calibration",
    "src/broker", "src/device_servers", "src/safety", "src/dashboards",
    "src/proto_gen",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
markers = ["integration: needs dockerized Postgres"]

[tool.mypy]
strict = true
mypy_path = "src"
packages = ["orchestrator", "compiler", "descriptor", "broker", "device_servers", "safety"]

[[tool.mypy.overrides]]
module = "proto_gen.*"
ignore_errors = true

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.coverage.run]
source = ["src/orchestrator", "src/compiler", "src/device_servers", "src/broker"]
```

- [ ] **Step 2: Create the directory skeleton**

```bash
mkdir -p src/{orchestrator,compiler,descriptor,calibration,broker,safety,dashboards,proto_gen} \
         src/device_servers/_base tests/{unit,contract,integration,fault_injection,hardware} \
         proto schema network ops/runbooks docs/adr .github/workflows
for p in src/orchestrator src/compiler src/descriptor src/calibration src/broker \
         src/safety src/dashboards src/proto_gen src/device_servers src/device_servers/_base \
         tests tests/unit tests/contract tests/integration tests/fault_injection; do
  touch "$p/__init__.py"
done
```

`tests/hardware/README.md`:

```markdown
# Hardware tests — excluded from CI

Manual bring-up + Phase 0A measurement harness. Run only in the lab, on the Tower.
Each script is re-runnable and writes JSON results next to itself.
```

- [ ] **Step 3: Write the three ADRs**

Copy the full **ADR-0001** and **ADR-0016** entries verbatim from `.planning/architecture/13-architectural-decisions.md` into `.planning/adr/0001-execution-authority-and-broker-placement.md` and `.planning/adr/0016-gpu-mutex-locality.md`, using the ADR template header from the same file (`Status: Accepted`).

Create `.planning/adr/0017-lifecycle-disarm-returns-uninit.md` from the lifecycle decision resolved during planning:

```markdown
# ADR-0017: Lifecycle Disarm Returns to UNINIT
Status: Accepted

Managed device `Disarm` always tears down to `UNINIT`, including from `CONFIGURED`, `ARMED`, `RUNNING`, `STOPPED`, and `FAULT`; re-issuing `Disarm` at `UNINIT` is an idempotent no-op. `CONFIGURED` after disarm would preserve driver-cached configuration and violate the hidden-global-state mitigation in B13. Direct `Disarm` from `RUNNING` exists only for emergency abort / E-stop / watchdog paths; graceful cancel still uses shot-boundary `Stop` before `Disarm`. Reversal condition: revisit only if measured device throughput requires a warm reconfigure path, with explicit proof that no driver-cached last-set values can leak across runs.
```

- [ ] **Step 4: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: test, POSTGRES_DB: controlsystem }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+psycopg://postgres:test@localhost:5432/controlsystem
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-groups
      - run: uv run python -m grpc_tools.protoc -Iproto --python_out=src/proto_gen --grpc_python_out=src/proto_gen --pyi_out=src/proto_gen proto/*.proto
        if: hashFiles('proto/*.proto') != ''
      - run: uv run ruff check src tests
      - run: uv run black --check src tests
      - run: uv run mypy
      - run: uv run alembic upgrade head
        if: hashFiles('schema/alembic.ini') != ''
        working-directory: schema
      - run: uv run pytest --cov --cov-fail-under=80 --ignore=tests/hardware
```

- [ ] **Step 5: Verify toolchain**

Run: `uv sync --all-groups && uv run pytest && uv run mypy && uv run ruff check src tests`
Expected: pytest reports `no tests ran` (exit 5 is acceptable at this step only); mypy and ruff pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: bootstrap repo layout, toolchain, CI, accepted ADRs"
```

---

### Task 2: Proto3 wire contracts + codegen (W1-1)

**Files:**
- Create: `proto/lifecycle.proto`, `proto/run_model.proto`, `proto/scheduler.proto`, `proto/safety.proto`
- Create: `Makefile` (codegen target)
- Test: `tests/unit/test_proto_gen.py`

**Interfaces:**
- Consumes: Task 1 layout.
- Produces: `proto_gen.lifecycle_pb2`, `proto_gen.lifecycle_pb2_grpc` (service `ManagedDevice`, stub `ManagedDeviceStub`, servicer `ManagedDeviceServicer`), `proto_gen.scheduler_pb2_grpc.SchedulerServicer`. Message names used by all later tasks are defined here exactly.

- [ ] **Step 1: Write `proto/lifecycle.proto`**

```proto
syntax = "proto3";
package controlsystem.lifecycle;

message Empty {}

message HealthRequest {}
message HealthResponse {
  string service_id = 1;
  string state = 2;          // UNINIT|CONFIGURED|ARMED|RUNNING|STOPPED|FAULT
  bool healthy = 3;
  string detail = 4;
}

message TimingHint { string name = 1; string value = 2; }

message CameraCapabilities {
  uint32 sensor_width = 1;
  uint32 sensor_height = 2;
  repeated string trigger_modes = 3;
}
message SlmCapabilities { uint32 width = 1; uint32 height = 2; double refresh_ms = 3; }
message OpxCapabilities {
  string qop_version = 1;
  repeated string analog_outputs = 2;
  repeated string digital_outputs = 3;
}

message Capabilities {
  string service_id = 1;
  string firmware = 2;
  string driver_version = 3;
  repeated TimingHint timing = 4;
  oneof specific {
    CameraCapabilities camera = 10;
    SlmCapabilities slm = 11;
    OpxCapabilities opx = 12;
  }
}

message ConfigureRequest { string config_yaml = 1; string idempotency_key = 2; }
message ConfigureResponse { bool ok = 1; string error = 2; }
message ArmRequest { string run_uuid = 1; string idempotency_key = 2; }
message ArmResponse { bool ok = 1; string error = 2; }
message StartRequest { string run_uuid = 1; string idempotency_key = 2; }
message StartResponse { bool ok = 1; string error = 2; }
message StopRequest { string idempotency_key = 1; }
message StopResponse { bool ok = 1; string error = 2; }
message DisarmRequest { string idempotency_key = 1; }
message DisarmResponse { bool ok = 1; string error = 2; }

message StatusRequest {}
message StatusEvent {
  string service_id = 1;
  string state = 2;
  string kind = 3;           // "transition" | "heartbeat" | "fault"
  string detail = 4;
  int64 wall_ns = 5;
}

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

- [ ] **Step 2: Write `proto/run_model.proto`**

```proto
syntax = "proto3";
package controlsystem.run;

message RunRequest {
  string user = 1;
  string template_name = 2;
  string parameters_json = 3;             // JSON object: scanned + fixed params
  repeated string required_calibration = 4;
  optional int64 requested_descriptor_id = 5;  // replay/debug/admin only
  string idempotency_key = 6;
}

message AcceptedJob {
  string job_uuid = 1;
  RunRequest request = 2;
  int64 descriptor_id = 3;                // pinned at admission
  int64 snapshot_id = 4;                  // pinned at admission
  string submitted_at = 5;                // RFC3339
  bytes request_hash = 6;                 // sha256 over canonical request payload
}

message Rejection { string code = 1; string reason = 2; }

message EnqueueResponse {
  oneof outcome { AcceptedJob accepted = 1; Rejection rejected = 2; }
}

message CancelRequest {
  string target = 1;                      // job_uuid or run_uuid
  string target_kind = 2;                 // "job" | "run"
  string requested_by = 3;
  string reason = 4;
  string idempotency_key = 5;
}
message CancelResponse { bool ok = 1; string state = 2; string error = 3; }

message RunSummary {
  string run_uuid = 1;
  string status = 2;                      // completed|failed|aborted|unsafe
  uint32 shot_count = 3;
  uint32 shots_ok = 4;
  double duration_s = 5;
  int64 snapshot_id = 6;
  int64 descriptor_id = 7;
  int64 execution_bundle_id = 8;
  string durability_tier = 9;             // v1-dev_non_durable | v1-lab_durable
  repeated string notes = 10;
}
```

- [ ] **Step 3: Write `proto/scheduler.proto` and `proto/safety.proto`**

`proto/scheduler.proto`:

```proto
syntax = "proto3";
package controlsystem.scheduler;
import "run_model.proto";
import "lifecycle.proto";

message ListRunsRequest { uint32 limit = 1; }
message RunRow { string run_uuid = 1; string state = 2; string template_name = 3; string user = 4; }
message ListRunsResponse { repeated RunRow runs = 1; }

service Scheduler {
  rpc Enqueue(controlsystem.run.RunRequest) returns (controlsystem.run.EnqueueResponse);
  rpc Cancel(controlsystem.run.CancelRequest) returns (controlsystem.run.CancelResponse);
  rpc Status(controlsystem.lifecycle.StatusRequest) returns (stream controlsystem.lifecycle.StatusEvent);
  rpc ListRuns(ListRunsRequest) returns (ListRunsResponse);
}
```

`proto/safety.proto`:

```proto
syntax = "proto3";
package controlsystem.safety;

message SafetyState {
  bool safe = 1;
  repeated string tripped = 2;   // names of tripped interlocks/watchdogs
  string detail = 3;
}
```

- [ ] **Step 4: Write `Makefile` codegen target**

```makefile
.PHONY: proto
proto:
	uv run python -m grpc_tools.protoc -Iproto \
	  --python_out=src/proto_gen --grpc_python_out=src/proto_gen --pyi_out=src/proto_gen \
	  proto/lifecycle.proto proto/run_model.proto proto/scheduler.proto proto/safety.proto
	uv run python -c "import pathlib,re; \
	  [p.write_text(re.sub(r'^import (\w+_pb2)', r'from proto_gen import \\1', p.read_text(), flags=re.M)) \
	   for p in pathlib.Path('src/proto_gen').glob('*_pb2*.py')]"
```

(The second command rewrites absolute generated imports to package-relative so `proto_gen` imports cleanly from `src/` layout.)

- [ ] **Step 5: Write the failing test**

`tests/unit/test_proto_gen.py`:

```python
def test_lifecycle_service_generated() -> None:
    from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

    assert hasattr(lifecycle_pb2_grpc, "ManagedDeviceStub")
    assert hasattr(lifecycle_pb2_grpc, "ManagedDeviceServicer")
    ev = lifecycle_pb2.StatusEvent(service_id="x", state="UNINIT", kind="heartbeat")
    assert ev.service_id == "x"


def test_run_model_generated() -> None:
    from proto_gen import run_model_pb2

    req = run_model_pb2.RunRequest(user="op", template_name="t", idempotency_key="k1")
    assert req.template_name == "t"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_proto_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'proto_gen.lifecycle_pb2'`

- [ ] **Step 7: Generate and re-run**

Run: `make proto && uv run pytest tests/unit/test_proto_gen.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add proto Makefile src/proto_gen tests/unit/test_proto_gen.py
git commit -m "feat: proto3 wire contracts (lifecycle, run model, scheduler, safety) + codegen"
```

---

### Task 3: Device lifecycle FSM (pure logic)

**Files:**
- Create: `src/device_servers/_base/fsm.py`
- Test: `tests/unit/test_lifecycle_fsm.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DeviceState` (StrEnum: `UNINIT, CONFIGURED, ARMED, RUNNING, STOPPED, FAULT`), `Verb` (StrEnum: `configure, arm, start, stop, disarm`), `LifecycleFsm` with `state: DeviceState`, `apply(verb: Verb) -> TransitionResult`, `fault(detail: str) -> None`. `TransitionResult` = frozen dataclass `(ok: bool, state: DeviceState, noop: bool, error: str | None)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_lifecycle_fsm.py`:

```python
import pytest

from device_servers._base.fsm import DeviceState, LifecycleFsm, Verb


def test_happy_path() -> None:
    fsm = LifecycleFsm()
    assert fsm.state is DeviceState.UNINIT
    for verb, expected in [
        (Verb.CONFIGURE, DeviceState.CONFIGURED),
        (Verb.ARM, DeviceState.ARMED),
        (Verb.START, DeviceState.RUNNING),
        (Verb.STOP, DeviceState.STOPPED),
        (Verb.DISARM, DeviceState.UNINIT),
    ]:
        result = fsm.apply(verb)
        assert result.ok and not result.noop
        assert fsm.state is expected


def test_same_verb_same_state_is_noop_success() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    result = fsm.apply(Verb.CONFIGURE)
    assert result.ok and result.noop
    assert fsm.state is DeviceState.CONFIGURED


def test_invalid_transition_rejected_without_state_change() -> None:
    fsm = LifecycleFsm()
    result = fsm.apply(Verb.START)          # start from UNINIT
    assert not result.ok and result.error is not None
    assert fsm.state is DeviceState.UNINIT


def test_disarm_forces_reconfigure_before_next_arm() -> None:
    # B13 semantics: disarm always lands in UNINIT; arm requires fresh configure.
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.DISARM)
    assert fsm.state is DeviceState.UNINIT
    assert not fsm.apply(Verb.ARM).ok


def test_direct_disarm_from_running_is_emergency_teardown() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.START)
    result = fsm.apply(Verb.DISARM)
    assert result.ok
    assert fsm.state is DeviceState.UNINIT
    assert not fsm.apply(Verb.ARM).ok


def test_fault_then_disarm_recovers_to_uninit() -> None:
    fsm = LifecycleFsm()
    fsm.apply(Verb.CONFIGURE)
    fsm.apply(Verb.ARM)
    fsm.apply(Verb.START)
    fsm.fault("driver exploded")
    assert fsm.state is DeviceState.FAULT
    assert not fsm.apply(Verb.START).ok      # only disarm leaves FAULT
    result = fsm.apply(Verb.DISARM)
    assert result.ok
    assert fsm.state is DeviceState.UNINIT


@pytest.mark.parametrize("verb", [Verb.CONFIGURE, Verb.ARM, Verb.START, Verb.STOP])
def test_only_disarm_leaves_fault(verb: Verb) -> None:
    fsm = LifecycleFsm()
    fsm.fault("x")
    assert not fsm.apply(verb).ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_lifecycle_fsm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'device_servers._base.fsm'`

- [ ] **Step 3: Implement `src/device_servers/_base/fsm.py`**

```python
"""Lifecycle FSM shared by every managed device service (PLAN-V2 §04).

Disarm semantics follow §04 prose, risk B13, and ADR-0017: disarm forces
re-Configure before the next Arm and always returns to UNINIT. Direct
RUNNING->disarm is emergency teardown only; graceful cancel uses stop first.
Safe-default enforcement belongs in adapter on_disarm hooks, not in this FSM.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeviceState(StrEnum):
    UNINIT = "UNINIT"
    CONFIGURED = "CONFIGURED"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


class Verb(StrEnum):
    CONFIGURE = "configure"
    ARM = "arm"
    START = "start"
    STOP = "stop"
    DISARM = "disarm"


@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    state: DeviceState
    noop: bool = False
    error: str | None = None


_TRANSITIONS: dict[tuple[DeviceState, Verb], DeviceState] = {
    (DeviceState.UNINIT, Verb.CONFIGURE): DeviceState.CONFIGURED,
    (DeviceState.CONFIGURED, Verb.ARM): DeviceState.ARMED,
    (DeviceState.ARMED, Verb.START): DeviceState.RUNNING,
    (DeviceState.RUNNING, Verb.STOP): DeviceState.STOPPED,
    # B13: disarm from any post-configure state -> UNINIT
    (DeviceState.CONFIGURED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.ARMED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.RUNNING, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.STOPPED, Verb.DISARM): DeviceState.UNINIT,
    (DeviceState.FAULT, Verb.DISARM): DeviceState.UNINIT,
}

# Re-issuing the verb that *produced* the current state is an idempotent no-op.
_NOOPS: dict[tuple[DeviceState, Verb], None] = {
    (DeviceState.CONFIGURED, Verb.CONFIGURE): None,
    (DeviceState.ARMED, Verb.ARM): None,
    (DeviceState.RUNNING, Verb.START): None,
    (DeviceState.STOPPED, Verb.STOP): None,
    (DeviceState.UNINIT, Verb.DISARM): None,
}


class LifecycleFsm:
    def __init__(self) -> None:
        self.state: DeviceState = DeviceState.UNINIT

    def apply(self, verb: Verb) -> TransitionResult:
        if (self.state, verb) in _NOOPS:
            return TransitionResult(ok=True, state=self.state, noop=True)
        target = _TRANSITIONS.get((self.state, verb))
        if target is None:
            return TransitionResult(
                ok=False,
                state=self.state,
                error=f"verb '{verb}' invalid in state '{self.state}'",
            )
        self.state = target
        return TransitionResult(ok=True, state=self.state)

    def fault(self, detail: str) -> None:
        self.state = DeviceState.FAULT
        self._fault_detail = detail
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_lifecycle_fsm.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/device_servers/_base/fsm.py tests/unit/test_lifecycle_fsm.py
git commit -m "feat: device lifecycle FSM with B13 disarm semantics"
```

---

### Task 4: `LifecycleService` base + gRPC servicer (W1-4, part 1)

**Files:**
- Create: `src/device_servers/_base/service.py`
- Test: `tests/unit/test_lifecycle_service.py`

**Interfaces:**
- Consumes: `LifecycleFsm`, `DeviceState`, `Verb` (Task 3); `proto_gen.lifecycle_pb2`, `lifecycle_pb2_grpc` (Task 2).
- Produces: abstract `DeviceAdapter` with hooks `on_configure(config_yaml: str) -> None`, `on_arm(run_uuid: str) -> None`, `on_start(run_uuid: str) -> None`, `on_stop() -> None`, `on_disarm() -> None`, `capabilities() -> lifecycle_pb2.Capabilities` (hooks raise `DeviceFaultError(detail)` on failure); concrete `LifecycleService(adapter: DeviceAdapter, service_id: str)` implementing `ManagedDeviceServicer`. Later tasks subclass `DeviceAdapter` only.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_lifecycle_service.py`:

```python
from proto_gen import lifecycle_pb2

from device_servers._base.fsm import DeviceState
from device_servers._base.service import DeviceAdapter, DeviceFaultError, LifecycleService


class _Recorder(DeviceAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_on: str | None = None
        self.safe_default_applied = False

    def _hook(self, name: str) -> None:
        if self.fail_on == name:
            raise DeviceFaultError(f"{name} failed")
        self.calls.append(name)

    def on_configure(self, config_yaml: str) -> None: self._hook("configure")
    def on_arm(self, run_uuid: str) -> None: self._hook("arm")
    def on_start(self, run_uuid: str) -> None: self._hook("start")
    def on_stop(self) -> None: self._hook("stop")
    def on_disarm(self) -> None:
        self.safe_default_applied = True
        self._hook("disarm")

    def capabilities(self) -> lifecycle_pb2.Capabilities:
        return lifecycle_pb2.Capabilities(service_id="rec", firmware="0", driver_version="0")


def _service() -> tuple[LifecycleService, _Recorder]:
    adapter = _Recorder()
    return LifecycleService(adapter, service_id="rec"), adapter


def test_configure_arm_start_calls_hooks_in_order() -> None:
    svc, adapter = _service()
    assert svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    assert svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok
    assert svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None).ok
    assert adapter.calls == ["configure", "arm", "start"]
    assert svc.fsm.state is DeviceState.RUNNING


def test_invalid_order_returns_error_and_skips_hook() -> None:
    svc, adapter = _service()
    resp = svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert not resp.ok and "invalid" in resp.error
    assert adapter.calls == []


def test_adapter_fault_moves_fsm_to_fault() -> None:
    svc, adapter = _service()
    adapter.fail_on = "arm"
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    resp = svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    assert not resp.ok
    assert svc.fsm.state is DeviceState.FAULT


def test_health_reports_state() -> None:
    svc, _ = _service()
    health = svc.Health(lifecycle_pb2.HealthRequest(), None)
    assert health.state == "UNINIT" and health.healthy


def test_noop_reissue_does_not_recall_hook() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert adapter.calls == ["configure"]


def test_configure_exact_replay_uses_cache_before_fsm() -> None:
    svc, adapter = _service()
    first = svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None)
    assert first.ok
    assert svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None).ok
    replay = svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None)
    assert replay.ok == first.ok and replay.error == first.error
    assert adapter.calls == ["configure", "arm"]
    assert svc.fsm.state is DeviceState.ARMED


def test_arm_key_reuse_with_different_payload_rejected() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None)
    assert svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None).ok
    resp = svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-1"), None)
    assert not resp.ok and resp.error == "idempotency_key_reused"
    assert adapter.calls == ["configure", "arm"]


def test_direct_disarm_from_running_applies_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert svc.fsm.state is DeviceState.UNINIT
    assert adapter.calls[-1] == "disarm"
    assert adapter.safe_default_applied


def test_stop_then_disarm_applies_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    svc.Stop(lifecycle_pb2.StopRequest(), None)
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert svc.fsm.state is DeviceState.UNINIT
    assert adapter.calls[-2:] == ["stop", "disarm"]
    assert adapter.safe_default_applied


def test_disarm_reused_key_still_invokes_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg1", idempotency_key="cfg-1"), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1", idempotency_key="start-1"), None)
    svc.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None)
    first_disarm_count = adapter.calls.count("disarm")
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg2", idempotency_key="cfg-2"), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-2"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r2", idempotency_key="start-2"), None)
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None).ok
    assert adapter.calls.count("disarm") == first_disarm_count + 1


def test_status_events_fan_out_to_all_subscribers() -> None:
    svc, _ = _service()
    s1 = svc.Status(lifecycle_pb2.StatusRequest(), None)
    s2 = svc.Status(lifecycle_pb2.StatusRequest(), None)
    next(s1)  # subscriber-local heartbeat
    next(s2)
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert next(s1).kind == "transition"
    assert next(s2).kind == "transition"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_lifecycle_service.py -v`
Expected: FAIL with `ModuleNotFoundError` (no `device_servers._base.service`)

- [ ] **Step 3: Implement `src/device_servers/_base/service.py`**

```python
"""Base LifecycleService: FSM + adapter hooks behind the ManagedDevice gRPC contract."""

from __future__ import annotations

import abc
import hashlib
import json
import queue
import threading
import time
from typing import Any, Iterator

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers._base.fsm import DeviceState, LifecycleFsm, Verb


class DeviceFaultError(Exception):
    """Raised by adapter hooks when the device fails; drives FSM to FAULT."""


class DeviceAdapter(abc.ABC):
    @abc.abstractmethod
    def on_configure(self, config_yaml: str) -> None: ...
    @abc.abstractmethod
    def on_arm(self, run_uuid: str) -> None: ...
    @abc.abstractmethod
    def on_start(self, run_uuid: str) -> None: ...
    @abc.abstractmethod
    def on_stop(self) -> None: ...
    @abc.abstractmethod
    def on_disarm(self) -> None: ...
    @abc.abstractmethod
    def capabilities(self) -> lifecycle_pb2.Capabilities: ...


_CACHEABLE_VERBS = {Verb.CONFIGURE, Verb.ARM, Verb.START}


def _payload_hash(*parts: str) -> bytes:
    canonical = json.dumps(parts, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()


class LifecycleService(lifecycle_pb2_grpc.ManagedDeviceServicer):
    def __init__(self, adapter: DeviceAdapter, service_id: str) -> None:
        self.adapter = adapter
        self.service_id = service_id
        self.fsm = LifecycleFsm()
        self._subscribers: set["queue.Queue[lifecycle_pb2.StatusEvent]"] = set()
        self._subscribers_lock = threading.Lock()
        # Pre-Phase-1 slice only: in-memory, unbounded cache; production adds TTL/eviction.
        self._idempotency: dict[tuple[Verb, str], tuple[bytes, bool, str]] = {}
        self._idempotency_lock = threading.Lock()

    # -- verb plumbing -------------------------------------------------
    def _event(self, kind: str, detail: str = "") -> lifecycle_pb2.StatusEvent:
        return lifecycle_pb2.StatusEvent(
            service_id=self.service_id,
            state=self.fsm.state.value,
            kind=kind,
            detail=detail,
            wall_ns=time.time_ns(),
        )

    def _emit(self, kind: str, detail: str = "") -> None:
        event = self._event(kind, detail)
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def _do(
        self,
        verb: Verb,
        idempotency_key: str,
        request_hash: bytes,
        hook: Any,
        *args: Any,
    ) -> tuple[bool, str]:
        cache_key = (verb, idempotency_key) if idempotency_key and verb in _CACHEABLE_VERBS else None
        if cache_key is not None:
            with self._idempotency_lock:
                cached = self._idempotency.get(cache_key)
            if cached is not None:
                cached_hash, cached_ok, cached_error = cached
                if cached_hash != request_hash:
                    return False, "idempotency_key_reused"
                return cached_ok, cached_error

        pre = self.fsm.apply(verb)
        if not pre.ok:
            ok, error = False, pre.error or "invalid transition"
        elif pre.noop:
            ok, error = True, ""
        else:
            try:
                hook(*args)
            except DeviceFaultError as exc:
                self.fsm.fault(str(exc))
                self._emit("fault", str(exc))
                ok, error = False, str(exc)
            else:
                self._emit("transition", verb.value)
                ok, error = True, ""

        if cache_key is not None:
            with self._idempotency_lock:
                self._idempotency[cache_key] = (request_hash, ok, error)
        return ok, error

    # -- ManagedDevice RPCs --------------------------------------------
    def Health(self, request: lifecycle_pb2.HealthRequest, context: Any) -> lifecycle_pb2.HealthResponse:
        return lifecycle_pb2.HealthResponse(
            service_id=self.service_id,
            state=self.fsm.state.value,
            healthy=self.fsm.state is not DeviceState.FAULT,
        )

    def Capabilities(self, request: lifecycle_pb2.Empty, context: Any) -> lifecycle_pb2.Capabilities:
        return self.adapter.capabilities()

    def Configure(self, request: lifecycle_pb2.ConfigureRequest, context: Any) -> lifecycle_pb2.ConfigureResponse:
        ok, err = self._do(
            Verb.CONFIGURE,
            request.idempotency_key,
            _payload_hash(request.config_yaml),
            self.adapter.on_configure,
            request.config_yaml,
        )
        return lifecycle_pb2.ConfigureResponse(ok=ok, error=err)

    def Arm(self, request: lifecycle_pb2.ArmRequest, context: Any) -> lifecycle_pb2.ArmResponse:
        ok, err = self._do(
            Verb.ARM,
            request.idempotency_key,
            _payload_hash(request.run_uuid),
            self.adapter.on_arm,
            request.run_uuid,
        )
        return lifecycle_pb2.ArmResponse(ok=ok, error=err)

    def Start(self, request: lifecycle_pb2.StartRequest, context: Any) -> lifecycle_pb2.StartResponse:
        ok, err = self._do(
            Verb.START,
            request.idempotency_key,
            _payload_hash(request.run_uuid),
            self.adapter.on_start,
            request.run_uuid,
        )
        return lifecycle_pb2.StartResponse(ok=ok, error=err)

    def Stop(self, request: lifecycle_pb2.StopRequest, context: Any) -> lifecycle_pb2.StopResponse:
        ok, err = self._do(Verb.STOP, request.idempotency_key, b"", self.adapter.on_stop)
        return lifecycle_pb2.StopResponse(ok=ok, error=err)

    def Disarm(self, request: lifecycle_pb2.DisarmRequest, context: Any) -> lifecycle_pb2.DisarmResponse:
        ok, err = self._do(Verb.DISARM, request.idempotency_key, b"", self.adapter.on_disarm)
        return lifecycle_pb2.DisarmResponse(ok=ok, error=err)

    def Status(self, request: lifecycle_pb2.StatusRequest, context: Any) -> Iterator[lifecycle_pb2.StatusEvent]:
        events: "queue.Queue[lifecycle_pb2.StatusEvent]" = queue.Queue()
        with self._subscribers_lock:
            self._subscribers.add(events)
        try:
            yield self._event("heartbeat")
            while context is None or context.is_active():
                try:
                    yield events.get(timeout=1.0)
                except queue.Empty:
                    yield self._event("heartbeat")
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_lifecycle_service.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/device_servers/_base/service.py tests/unit/test_lifecycle_service.py
git commit -m "feat: LifecycleService base with adapter hooks and fault handling"
```

---

### Task 5: Contract test suite + fake camera + fake OPX lifecycle shell (W1-4 part 2, W1-5, W1-6a)

**Files:**
- Create: `tests/contract/conftest.py`, `tests/contract/test_lifecycle_contract.py`
- Create: `src/device_servers/fake_camera/__init__.py`, `src/device_servers/fake_camera/adapter.py`, `src/device_servers/fake_camera/main.py`
- Create: `src/device_servers/fake_opx/__init__.py`, `src/device_servers/fake_opx/adapter.py`, `src/device_servers/fake_opx/main.py`

**Interfaces:**
- Consumes: `LifecycleService`, `DeviceAdapter`, `DeviceFaultError` (Task 4); `proto_gen` (Task 2).
- Produces: contract suite parametrized over a `service_factories` registry (`dict[str, Callable[[], ServiceCase]]`); each `ServiceCase` includes a `LifecycleService` plus test probes for configure/arm/disarm counts, proving cached replays skip payloaded hooks while repeated `Disarm` keys still reach the descriptor-defined safe default. Fakes expose counters; real adapters must probe observable safe-state actions for their device family. Produces `FakeCameraAdapter(DeviceAdapter)`; `FakeOpxAdapter(DeviceAdapter)`; `serve(port: int) -> grpc.Server` in both fake service `main.py` modules. The fake OPX is lifecycle-only: eight verbs and typed capabilities, no `QuantumMachinesManager`, no `RtJobResult`, no batch-push RPC. Those remain W2-1/W2-3. Every future device service adds one factory entry and inherits the whole suite — the base contract never changes (PLAN-V2 §04).

- [ ] **Step 1: Write the contract suite (failing)**

`tests/contract/conftest.py`:

```python
from dataclasses import dataclass
from typing import Callable

import pytest

from device_servers._base.service import LifecycleService


@dataclass(frozen=True)
class ServiceCase:
    service: LifecycleService
    configure_count: Callable[[], int]
    arm_count: Callable[[], int]
    safe_default_count: Callable[[], int]


def _fake_camera() -> ServiceCase:
    from device_servers.fake_camera.adapter import FakeCameraAdapter

    adapter = FakeCameraAdapter()
    return ServiceCase(
        service=LifecycleService(adapter, service_id="fake_camera"),
        configure_count=lambda: adapter.configure_count,
        arm_count=lambda: adapter.arm_count,
        safe_default_count=lambda: adapter.safe_default_count,
    )


def _fake_opx() -> ServiceCase:
    from device_servers.fake_opx.adapter import FakeOpxAdapter

    adapter = FakeOpxAdapter()
    return ServiceCase(
        service=LifecycleService(adapter, service_id="fake_opx"),
        configure_count=lambda: adapter.configure_count,
        arm_count=lambda: adapter.arm_count,
        safe_default_count=lambda: adapter.safe_default_count,
    )


# New device services register here; the whole suite runs against each.
SERVICE_FACTORIES: dict[str, Callable[[], ServiceCase]] = {
    "fake_camera": _fake_camera,
    "fake_opx": _fake_opx,
}


@pytest.fixture(params=sorted(SERVICE_FACTORIES))
def service_case(request: pytest.FixtureRequest) -> ServiceCase:
    return SERVICE_FACTORIES[request.param]()


@pytest.fixture
def service(service_case: ServiceCase) -> LifecycleService:
    return service_case.service
```

`tests/contract/test_lifecycle_contract.py`:

```python
"""Lifecycle contract: every managed device service must pass all of these
(REQUIREMENTS.md TEST-01; PLAN-V2 §04). Parametrized via conftest SERVICE_FACTORIES."""

from typing import Any

from proto_gen import lifecycle_pb2

from device_servers._base.fsm import DeviceState
from device_servers._base.service import LifecycleService


def test_initial_state_is_uninit_and_healthy(service: LifecycleService) -> None:
    health = service.Health(lifecycle_pb2.HealthRequest(), None)
    assert health.state == "UNINIT" and health.healthy


def test_capabilities_are_typed_and_identified(service: LifecycleService) -> None:
    caps = service.Capabilities(lifecycle_pb2.Empty(), None)
    assert caps.service_id != ""
    assert caps.WhichOneof("specific") is not None


def test_full_verb_cycle(service: LifecycleService) -> None:
    assert service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok
    assert service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None).ok
    assert service.Stop(lifecycle_pb2.StopRequest(), None).ok
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT


def test_verbs_are_idempotent(service: LifecycleService) -> None:
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok


def test_out_of_order_verb_is_typed_error_not_crash(service: LifecycleService) -> None:
    resp = service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert not resp.ok and resp.error != ""


def test_disarm_forces_reconfigure(service: LifecycleService) -> None:
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Disarm(lifecycle_pb2.DisarmRequest(), None)
    assert not service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2"), None).ok


def test_configure_exact_replay_uses_cache_before_fsm(service_case: Any) -> None:
    service = service_case.service
    first = service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert first.ok
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None).ok
    before = service_case.configure_count()
    replay = service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert replay.ok == first.ok and replay.error == first.error
    assert service_case.configure_count() == before
    assert service.fsm.state is DeviceState.ARMED


def test_arm_key_reuse_with_different_payload_rejected(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None)
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None).ok
    before = service_case.arm_count()
    resp = service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-1"), None)
    assert not resp.ok and resp.error == "idempotency_key_reused"
    assert service_case.arm_count() == before


def test_direct_disarm_from_running_applies_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT
    assert service_case.safe_default_count() >= 1
    assert not service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2"), None).ok


def test_stop_then_disarm_applies_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    service.Stop(lifecycle_pb2.StopRequest(), None)
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT
    assert service_case.safe_default_count() >= 1


def test_disarm_reused_key_still_invokes_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg1", idempotency_key="cfg-1"), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r1", idempotency_key="start-1"), None)
    service.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None)
    first_disarm_count = service_case.safe_default_count()
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml="cfg2", idempotency_key="cfg-2"), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-2"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r2", idempotency_key="start-2"), None)
    assert service.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None).ok
    assert service_case.safe_default_count() == first_disarm_count + 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/contract -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'device_servers.fake_camera'` (collection error in conftest fixture)

- [ ] **Step 3: Implement the fake camera**

`src/device_servers/fake_camera/adapter.py`:

```python
"""Fake EMCCD camera: contract-complete, zero hardware. First entry in the fake fleet."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from proto_gen import lifecycle_pb2

from device_servers._base.service import DeviceAdapter


class FakeCameraAdapter(DeviceAdapter):
    def __init__(self, width: int = 256, height: int = 256, seed: int = 0) -> None:
        self._width = width
        self._height = height
        self._rng = np.random.default_rng(seed)
        self._armed_run: str | None = None
        self.configure_count = 0
        self.arm_count = 0
        self.safe_default_count = 0

    def on_configure(self, config_yaml: str) -> None:
        self.configure_count += 1
        pass  # fake accepts any config

    def on_arm(self, run_uuid: str) -> None:
        self.arm_count += 1
        self._armed_run = run_uuid

    def on_start(self, run_uuid: str) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def on_disarm(self) -> None:
        self._armed_run = None
        self.safe_default_count += 1

    def capabilities(self) -> lifecycle_pb2.Capabilities:
        return lifecycle_pb2.Capabilities(
            service_id="fake_camera",
            firmware="fake-1.0",
            driver_version="fake-1.0",
            camera=lifecycle_pb2.CameraCapabilities(
                sensor_width=self._width,
                sensor_height=self._height,
                trigger_modes=["external"],
            ),
        )

    def snap(self) -> npt.NDArray[np.uint16]:
        """Synthetic frame with Poisson-ish bright sites; used by later fake-run tasks."""
        return self._rng.integers(0, 4096, (self._height, self._width), dtype=np.uint16)
```

`src/device_servers/fake_camera/main.py`:

```python
"""Standalone gRPC entry point: `python -m device_servers.fake_camera.main --port 50061`."""

from __future__ import annotations

import argparse
from concurrent import futures

import grpc

from proto_gen import lifecycle_pb2_grpc

from device_servers._base.service import LifecycleService
from device_servers.fake_camera.adapter import FakeCameraAdapter


def serve(port: int) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    service = LifecycleService(FakeCameraAdapter(), service_id="fake_camera")
    lifecycle_pb2_grpc.add_ManagedDeviceServicer_to_server(service, server)
    server.add_insecure_port(f"127.0.0.1:{port}")  # mTLS lands with the v1-lab split
    server.start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50061)
    args = parser.parse_args()
    serve(args.port).wait_for_termination()
```

- [ ] **Step 4: Implement the fake OPX lifecycle shell**

`src/device_servers/fake_opx/adapter.py`:

```python
"""Fake OPX lifecycle shell: contract-complete, zero QM SDK dependency.

This closes the W1-6 lifecycle/gRPC half only. RtJobResult, batch-push, and
QuantumMachinesManager integration belong to Phase 2 / Phase 0A.
"""

from __future__ import annotations

from proto_gen import lifecycle_pb2

from device_servers._base.service import DeviceAdapter


class FakeOpxAdapter(DeviceAdapter):
    def __init__(self) -> None:
        self._armed_run: str | None = None
        self.configure_count = 0
        self.arm_count = 0
        self.safe_default_count = 0

    def on_configure(self, config_yaml: str) -> None:
        self.configure_count += 1

    def on_arm(self, run_uuid: str) -> None:
        self.arm_count += 1
        self._armed_run = run_uuid

    def on_start(self, run_uuid: str) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def on_disarm(self) -> None:
        self._armed_run = None
        self.safe_default_count += 1

    def capabilities(self) -> lifecycle_pb2.Capabilities:
        return lifecycle_pb2.Capabilities(
            service_id="fake_opx",
            firmware="fake-qop",
            driver_version="fake-qm-sdk",
            opx=lifecycle_pb2.OpxCapabilities(
                qop_version="fake",
                analog_outputs=["aod_x", "aod_y"],
                digital_outputs=["aod_enable", "camera_trigger"],
            ),
        )
```

`src/device_servers/fake_opx/main.py`:

```python
"""Standalone fake OPX lifecycle service: no QM SDK, no RtJobResult path."""

from __future__ import annotations

import argparse
from concurrent import futures

import grpc

from proto_gen import lifecycle_pb2_grpc

from device_servers._base.service import LifecycleService
from device_servers.fake_opx.adapter import FakeOpxAdapter


def serve(port: int) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    service = LifecycleService(FakeOpxAdapter(), service_id="fake_opx")
    lifecycle_pb2_grpc.add_ManagedDeviceServicer_to_server(service, server)
    server.add_insecure_port(f"127.0.0.1:{port}")  # mTLS lands with the v1-lab split
    server.start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50062)
    args = parser.parse_args()
    serve(args.port).wait_for_termination()
```

- [ ] **Step 5: Run contract suite to verify pass**

Run: `uv run pytest tests/contract -v`
Expected: PASS (22 tests, params `fake_camera` and `fake_opx`)

- [ ] **Step 6: Smoke the real gRPC transport**

Add `tests/integration/test_fake_camera_grpc.py`:

```python
import grpc

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers.fake_camera.main import serve


def test_fake_camera_over_real_grpc() -> None:
    server = serve(50061)
    try:
        channel = grpc.insecure_channel("127.0.0.1:50061")
        stub = lifecycle_pb2_grpc.ManagedDeviceStub(channel)
        health = stub.Health(lifecycle_pb2.HealthRequest(), timeout=5)
        assert health.state == "UNINIT"
        caps = stub.Capabilities(lifecycle_pb2.Empty(), timeout=5)
        assert caps.camera.sensor_width == 256
    finally:
        server.stop(grace=None)
```

Run: `uv run pytest tests/integration/test_fake_camera_grpc.py -v`
Expected: PASS

Add `tests/integration/test_fake_opx_grpc.py`:

```python
import grpc

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers.fake_opx.main import serve


def test_fake_opx_lifecycle_over_real_grpc() -> None:
    server = serve(50062)
    try:
        channel = grpc.insecure_channel("127.0.0.1:50062")
        stub = lifecycle_pb2_grpc.ManagedDeviceStub(channel)
        health = stub.Health(lifecycle_pb2.HealthRequest(), timeout=5)
        assert health.state == "UNINIT"
        caps = stub.Capabilities(lifecycle_pb2.Empty(), timeout=5)
        assert caps.WhichOneof("specific") == "opx"
        assert "aod_x" in caps.opx.analog_outputs
    finally:
        server.stop(grace=None)
```

Run: `uv run pytest tests/integration/test_fake_camera_grpc.py tests/integration/test_fake_opx_grpc.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/contract src/device_servers/fake_camera src/device_servers/fake_opx \
        tests/integration/test_fake_camera_grpc.py tests/integration/test_fake_opx_grpc.py
git commit -m "feat: lifecycle contract suite with fake camera and fake OPX"
```

---

### Task 6: Postgres schema v1 + Alembic (W1-3)

**Files:**
- Create: `schema/alembic.ini`, `schema/env.py`, `schema/versions/0001_schema_v1.py`
- Create: `src/orchestrator/db.py`
- Test: `tests/integration/test_schema_v1.py`

**Interfaces:**
- Consumes: Task 1 toolchain.
- Produces: tables `device_descriptors`, `descriptor_activations`, `calibration_snapshots` (minimal, needed as FK target), `snapshot_activations`, `accepted_jobs`, `runs`, `shots`, `raw_manifests`; `orchestrator.db.make_engine(url: str) -> sqlalchemy.Engine` and `active_descriptor_id(conn) -> int | None`, `active_snapshot_id(conn) -> int | None`. Full calibration tables (`dag_nodes`, `calibration_executions`, `parameter_versions`, `execution_bundles`) are Phase 3 migrations, not this task.

- [ ] **Step 1: Start local Postgres and write the failing test**

```bash
docker run -d --name cs-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=controlsystem -p 5432:5432 postgres:16
export DATABASE_URL='postgresql+psycopg://postgres:test@localhost:5432/controlsystem'
```

`tests/integration/test_schema_v1.py`:

```python
import os

import pytest
import sqlalchemy as sa

from orchestrator.db import active_descriptor_id, make_engine

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:test@localhost:5432/controlsystem")


@pytest.fixture()
def engine() -> sa.Engine:
    return make_engine(URL)


def test_all_v1_tables_exist(engine: sa.Engine) -> None:
    names = sa.inspect(engine).get_table_names()
    for t in [
        "device_descriptors", "descriptor_activations", "calibration_snapshots",
        "snapshot_activations", "accepted_jobs", "runs", "shots", "raw_manifests",
    ]:
        assert t in names, f"missing table {t}"


def test_active_descriptor_is_latest_activation(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        d1 = conn.execute(sa.text(
            "INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by)"
            " VALUES (NOW(), '{}', :h1, 'test') RETURNING id"), {"h1": b"h1"}).scalar_one()
        d2 = conn.execute(sa.text(
            "INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by)"
            " VALUES (NOW(), '{}', :h2, 'test') RETURNING id"), {"h2": b"h2"}).scalar_one()
        conn.execute(sa.text(
            "INSERT INTO descriptor_activations (descriptor_id, activated_by) VALUES (:d, 'test')"),
            {"d": d1})
        conn.execute(sa.text(
            "INSERT INTO descriptor_activations (descriptor_id, activated_by) VALUES (:d, 'test')"),
            {"d": d2})
        assert active_descriptor_id(conn) == d2


def test_runs_reject_bad_durability_tier(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        job_uuid = conn.execute(sa.text(
            "INSERT INTO accepted_jobs (job_uuid, user_id, template_name, parameters,"
            " descriptor_id, snapshot_id, state, submitted_at, idempotency_key, request_hash)"
            " VALUES (gen_random_uuid(), 'u', 't', '{}', 1, 1, 'pending', NOW(), 'tier-test', :h)"
            " RETURNING job_uuid"), {"h": b"h"}).scalar_one()
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(sa.text(
                "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                " snapshot_id, descriptor_id, state, submitted_at, durability_tier, idempotency_key)"
                " VALUES (gen_random_uuid(), :j, 'u', 't', '{}', 1, 1,"
                " 'submitted', NOW(), 'bogus_tier', 'k')"), {"j": str(job_uuid)})


def test_runs_reject_bad_state(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        job_uuid = conn.execute(sa.text(
            "INSERT INTO accepted_jobs (job_uuid, user_id, template_name, parameters,"
            " descriptor_id, snapshot_id, state, submitted_at, idempotency_key, request_hash)"
            " VALUES (gen_random_uuid(), 'u', 't', '{}', 1, 1, 'pending', NOW(), 'state-test', :h)"
            " RETURNING job_uuid"), {"h": b"h"}).scalar_one()
        with pytest.raises(sa.exc.DBAPIError):
            conn.execute(sa.text(
                "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                " snapshot_id, descriptor_id, state, submitted_at, durability_tier, idempotency_key)"
                " VALUES (gen_random_uuid(), :j, 'u', 't', '{}', 1, 1,"
                " 'teleported', NOW(), 'v1-dev_non_durable', 'k')"), {"j": str(job_uuid)})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_schema_v1.py -v`
Expected: FAIL (`No module named 'orchestrator.db'`)

- [ ] **Step 3: Write the migration**

`schema/alembic.ini` (minimal):

```ini
[alembic]
script_location = .
prepend_sys_path = ../src
sqlalchemy.url =
```

`schema/env.py`:

```python
import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ["DATABASE_URL"]


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run()
```

`schema/versions/0001_schema_v1.py` — `upgrade()` executes the DDL below verbatim (one `op.execute` block; `downgrade()` drops in reverse order). The DDL is PLAN-V2 §05 restricted to the Phase-1 table set, **column names copied exactly**:

```sql
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

-- Minimal now (FK target for accepted_jobs/runs); full calibration model is Phase 3.
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
-- NOTE: §05 also gives runs.bundle_id -> execution_bundles; that FK arrives with the
-- Phase 3 migration that creates execution_bundles. Additive change, no rename.

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

-- Seed: one empty descriptor + snapshot + activations so v1-dev admission can pin IDs.
INSERT INTO device_descriptors (created_at, content, content_hash, inserted_by, notes)
VALUES (NOW(), '{}', '\x00', 'bootstrap', 'v1-dev placeholder descriptor');
INSERT INTO descriptor_activations (descriptor_id, activated_by) VALUES (1, 'bootstrap');
INSERT INTO calibration_snapshots (parent_id, parameter_set, published_at, published_by, notes)
VALUES (NULL, '{}', NOW(), 'bootstrap', 'v1-dev empty snapshot');
INSERT INTO snapshot_activations (snapshot_id, activated_by) VALUES (1, 'bootstrap');
```

- [ ] **Step 4: Implement `src/orchestrator/db.py`**

```python
"""Engine factory + active-pointer queries (append-only activation logs, ADR-0003)."""

from __future__ import annotations

import sqlalchemy as sa


def make_engine(url: str) -> sa.Engine:
    return sa.create_engine(url, pool_pre_ping=True)


_ACTIVE_DESCRIPTOR = sa.text(
    "SELECT descriptor_id FROM descriptor_activations"
    " WHERE lineage = :lineage ORDER BY activated_at DESC, id DESC LIMIT 1"
)
_ACTIVE_SNAPSHOT = sa.text(
    "SELECT snapshot_id FROM snapshot_activations"
    " WHERE lineage = :lineage ORDER BY activated_at DESC, id DESC LIMIT 1"
)


def active_descriptor_id(conn: sa.Connection, lineage: str = "default") -> int | None:
    return conn.execute(_ACTIVE_DESCRIPTOR, {"lineage": lineage}).scalar()


def active_snapshot_id(conn: sa.Connection, lineage: str = "default") -> int | None:
    return conn.execute(_ACTIVE_SNAPSHOT, {"lineage": lineage}).scalar()
```

- [ ] **Step 5: Apply migration and run tests**

Run: `(cd schema && uv run alembic upgrade head) && uv run pytest tests/integration/test_schema_v1.py -v`
Expected: migration applies; PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add schema src/orchestrator/db.py tests/integration/test_schema_v1.py
git commit -m "feat: Postgres schema v1 with append-only activation pointers"
```

---

### Task 7: Run/shot state machines (pure logic)

**Files:**
- Create: `src/orchestrator/run_fsm.py`
- Test: `tests/unit/test_run_fsm.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunState` (StrEnum: `submitted, validated, planned, armed, executing, committing, completed, failed, unsafe, aborted, disarmed, rejected`), `ShotState` (StrEnum: `prepared, armed, executing, raw_spooled, metadata_mirrored, replicated, committed, commit_pending, failed, raw_lost, safety_trip, unsafe`), and `run_can_transition(a: RunState, b: RunState) -> bool`, `shot_can_transition(a: ShotState, b: ShotState) -> bool`. The orchestrator (Task 9) enforces every state write through these.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_run_fsm.py`:

```python
from orchestrator.run_fsm import RunState, ShotState, run_can_transition, shot_can_transition


def test_run_happy_path() -> None:
    path = [RunState.SUBMITTED, RunState.VALIDATED, RunState.PLANNED, RunState.ARMED,
            RunState.EXECUTING, RunState.COMMITTING, RunState.COMPLETED]
    for a, b in zip(path, path[1:]):
        assert run_can_transition(a, b), f"{a}->{b}"


def test_run_rejection_edges() -> None:
    for s in [RunState.SUBMITTED, RunState.VALIDATED, RunState.PLANNED]:
        assert run_can_transition(s, RunState.REJECTED)
    assert not run_can_transition(RunState.EXECUTING, RunState.REJECTED)


def test_run_terminal_states_are_terminal() -> None:
    for terminal in [RunState.COMPLETED, RunState.FAILED, RunState.UNSAFE,
                     RunState.ABORTED, RunState.REJECTED]:
        for target in RunState:
            assert not run_can_transition(terminal, target)


def test_run_abort_only_from_executing() -> None:
    assert run_can_transition(RunState.EXECUTING, RunState.ABORTED)
    assert not run_can_transition(RunState.ARMED, RunState.ABORTED)
    assert run_can_transition(RunState.ARMED, RunState.DISARMED)


def test_shot_happy_path_and_commit_pending() -> None:
    assert shot_can_transition(ShotState.EXECUTING, ShotState.RAW_SPOOLED)
    assert shot_can_transition(ShotState.RAW_SPOOLED, ShotState.METADATA_MIRRORED)
    assert shot_can_transition(ShotState.METADATA_MIRRORED, ShotState.REPLICATED)
    assert shot_can_transition(ShotState.REPLICATED, ShotState.COMMITTED)
    assert shot_can_transition(ShotState.RAW_SPOOLED, ShotState.COMMIT_PENDING)
    assert shot_can_transition(ShotState.METADATA_MIRRORED, ShotState.COMMIT_PENDING)


def test_shot_safety_trip_leads_to_unsafe_only() -> None:
    assert shot_can_transition(ShotState.EXECUTING, ShotState.SAFETY_TRIP)
    assert shot_can_transition(ShotState.SAFETY_TRIP, ShotState.UNSAFE)
    assert not shot_can_transition(ShotState.SAFETY_TRIP, ShotState.COMMITTED)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_run_fsm.py -v`
Expected: FAIL (`No module named 'orchestrator.run_fsm'`)

- [ ] **Step 3: Implement `src/orchestrator/run_fsm.py`**

```python
"""Run + shot state machines, verbatim from PLAN-V2 §04 diagrams."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    PLANNED = "planned"
    ARMED = "armed"
    EXECUTING = "executing"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNSAFE = "unsafe"
    ABORTED = "aborted"
    DISARMED = "disarmed"
    REJECTED = "rejected"


_RUN_EDGES: set[tuple[RunState, RunState]] = {
    (RunState.SUBMITTED, RunState.VALIDATED),
    (RunState.SUBMITTED, RunState.REJECTED),
    (RunState.VALIDATED, RunState.PLANNED),
    (RunState.VALIDATED, RunState.REJECTED),
    (RunState.PLANNED, RunState.ARMED),
    (RunState.PLANNED, RunState.REJECTED),
    (RunState.ARMED, RunState.EXECUTING),
    (RunState.ARMED, RunState.DISARMED),
    (RunState.EXECUTING, RunState.COMMITTING),
    (RunState.EXECUTING, RunState.ABORTED),
    (RunState.COMMITTING, RunState.COMPLETED),
    (RunState.COMMITTING, RunState.FAILED),
    (RunState.COMMITTING, RunState.UNSAFE),
}


class ShotState(StrEnum):
    PREPARED = "prepared"
    ARMED = "armed"
    EXECUTING = "executing"
    RAW_SPOOLED = "raw_spooled"
    METADATA_MIRRORED = "metadata_mirrored"
    REPLICATED = "replicated"
    COMMITTED = "committed"
    COMMIT_PENDING = "commit_pending"
    FAILED = "failed"
    RAW_LOST = "raw_lost"
    SAFETY_TRIP = "safety_trip"
    UNSAFE = "unsafe"


_SHOT_EDGES: set[tuple[ShotState, ShotState]] = {
    (ShotState.PREPARED, ShotState.ARMED),
    (ShotState.ARMED, ShotState.EXECUTING),
    (ShotState.ARMED, ShotState.SAFETY_TRIP),
    (ShotState.EXECUTING, ShotState.RAW_SPOOLED),
    (ShotState.EXECUTING, ShotState.FAILED),
    (ShotState.EXECUTING, ShotState.RAW_LOST),
    (ShotState.EXECUTING, ShotState.SAFETY_TRIP),
    (ShotState.RAW_SPOOLED, ShotState.METADATA_MIRRORED),
    (ShotState.RAW_SPOOLED, ShotState.COMMIT_PENDING),
    (ShotState.RAW_SPOOLED, ShotState.RAW_LOST),
    (ShotState.METADATA_MIRRORED, ShotState.REPLICATED),
    (ShotState.METADATA_MIRRORED, ShotState.COMMIT_PENDING),
    (ShotState.METADATA_MIRRORED, ShotState.RAW_LOST),
    (ShotState.REPLICATED, ShotState.COMMITTED),
    (ShotState.COMMIT_PENDING, ShotState.METADATA_MIRRORED),
    (ShotState.COMMIT_PENDING, ShotState.REPLICATED),
    (ShotState.COMMIT_PENDING, ShotState.COMMITTED),
    (ShotState.SAFETY_TRIP, ShotState.UNSAFE),
}


def run_can_transition(a: RunState, b: RunState) -> bool:
    return (a, b) in _RUN_EDGES


def shot_can_transition(a: ShotState, b: ShotState) -> bool:
    return (a, b) in _SHOT_EDGES
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_run_fsm.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/run_fsm.py tests/unit/test_run_fsm.py
git commit -m "feat: run and shot state machines per PLAN-V2 §04"
```

---

### Task 8: Admission Validator (EliteDesk role, W1-2 part 1)

**Files:**
- Create: `src/orchestrator/admission.py`
- Test: `tests/integration/test_admission.py`

**Interfaces:**
- Consumes: `make_engine`, `active_descriptor_id`, `active_snapshot_id` (Task 6).
- Produces: `AdmissionValidator(engine: sa.Engine, template_allowlist: frozenset[str])` with `enqueue(user: str, template_name: str, parameters: dict[str, object], idempotency_key: str, requested_descriptor_id: int | None = None) -> AdmissionResult` and `cancel_pending(job_uuid: UUID, requested_by: str) -> bool`. `AdmissionResult` = frozen dataclass `(accepted: bool, job_uuid: UUID | None, descriptor_id: int | None, snapshot_id: int | None, request_hash: bytes | None, rejection_code: str | None, rejection_reason: str | None)`. Deterministic — runs identically co-located (`v1-dev`) or on the EliteDesk (`v1-lab`), per ADR-0001. Idempotency stores a canonical request hash; exact replays dedup, while `(user, key)` reuse with a different payload rejects with `idempotency_key_reused`. Calibration-freshness checks are deferred to Phase 3 (no DAG tables yet) — noted in code.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_admission.py`:

```python
import os
import uuid

import pytest
import sqlalchemy as sa

from orchestrator.admission import AdmissionValidator
from orchestrator.db import make_engine

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:test@localhost:5432/controlsystem")
ALLOW = frozenset({"noop_template", "rydberg_blockade_demo"})


@pytest.fixture()
def validator() -> AdmissionValidator:
    return AdmissionValidator(make_engine(URL), template_allowlist=ALLOW)


def _key() -> str:
    return uuid.uuid4().hex


def test_accept_pins_active_descriptor_and_snapshot(validator: AdmissionValidator) -> None:
    res = validator.enqueue("op", "noop_template", {"n": 1}, _key())
    assert res.accepted
    assert res.descriptor_id is not None and res.snapshot_id is not None
    with validator.engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT state, descriptor_id, snapshot_id FROM accepted_jobs WHERE job_uuid = :j"),
            {"j": str(res.job_uuid)},
        ).one()
    assert row.state == "pending"
    assert (row.descriptor_id, row.snapshot_id) == (res.descriptor_id, res.snapshot_id)


def test_reject_unknown_template(validator: AdmissionValidator) -> None:
    res = validator.enqueue("op", "not_a_template", {}, _key())
    assert not res.accepted and res.rejection_code == "template_not_allowed"


def test_idempotency_dedup_returns_same_job(validator: AdmissionValidator) -> None:
    key = _key()
    first = validator.enqueue("op", "noop_template", {}, key)
    second = validator.enqueue("op", "noop_template", {}, key)
    assert second.accepted and second.job_uuid == first.job_uuid


def test_idempotency_key_reuse_with_different_payload_rejected(validator: AdmissionValidator) -> None:
    key = _key()
    first = validator.enqueue("op", "noop_template", {"n": 1}, key)
    second = validator.enqueue("op", "noop_template", {"n": 2}, key)
    assert first.accepted
    assert not second.accepted
    assert second.rejection_code == "idempotency_key_reused"


def test_requested_descriptor_must_exist(validator: AdmissionValidator) -> None:
    res = validator.enqueue("admin", "noop_template", {}, _key(), requested_descriptor_id=999999)
    assert not res.accepted and res.rejection_code == "descriptor_not_found"


def test_cancel_pending_records_timestamps(validator: AdmissionValidator) -> None:
    res = validator.enqueue("op", "noop_template", {}, _key())
    assert res.job_uuid is not None
    assert validator.cancel_pending(res.job_uuid, requested_by="op")
    with validator.engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT state, cancel_requested_at, cancel_effective_at, cancel_requested_by"
                    " FROM accepted_jobs WHERE job_uuid = :j"),
            {"j": str(res.job_uuid)},
        ).one()
    assert row.state == "cancelled"
    assert row.cancel_requested_at is not None and row.cancel_effective_at is not None
    assert row.cancel_requested_by == "op"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_admission.py -v`
Expected: FAIL (`No module named 'orchestrator.admission'`)

- [ ] **Step 3: Implement `src/orchestrator/admission.py`**

```python
"""Admission Validator/Submitter (EliteDesk role, ADR-0001).

Deterministic over: request shape, template allow-list, active descriptor/snapshot
resolution, and static semantic checks. Calibration-freshness checks arrive with the
Phase 3 DAG tables. RBAC arrives with the mTLS identity layer (v1-lab split).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

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
                sa.text("SELECT job_uuid, descriptor_id, snapshot_id, request_hash FROM accepted_jobs"
                        " WHERE user_id = :u AND idempotency_key = :k"),
                {"u": user, "k": idempotency_key},
            ).one_or_none()
            if existing is not None:
                if bytes(existing.request_hash) != req_hash:
                    return AdmissionResult(
                        accepted=False,
                        rejection_code="idempotency_key_reused",
                        rejection_reason="idempotency key already used for a different request payload",
                    )
                return AdmissionResult(
                    accepted=True,
                    job_uuid=uuid.UUID(str(existing.job_uuid)),
                    descriptor_id=existing.descriptor_id,
                    snapshot_id=existing.snapshot_id,
                    request_hash=req_hash,
                )

            if requested_descriptor_id is not None:
                # Replay/debug/admin flow: must reference an existing immutable descriptor.
                found = conn.execute(
                    sa.text("SELECT id FROM device_descriptors WHERE id = :d"),
                    {"d": requested_descriptor_id},
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
                    " descriptor_id, snapshot_id, state, submitted_at, idempotency_key, request_hash)"
                    " VALUES (:j, :u, :t, :p, :d, :s, 'pending', :now, :k, :h)"
                ),
                {
                    "j": str(job_uuid), "u": user, "t": template_name,
                    "p": json.dumps(parameters), "d": descriptor_id, "s": snapshot_id,
                    "now": datetime.now(timezone.utc), "k": idempotency_key, "h": req_hash,
                },
            )
        return AdmissionResult(
            accepted=True, job_uuid=job_uuid,
            descriptor_id=descriptor_id, snapshot_id=snapshot_id, request_hash=req_hash,
        )

    def cancel_pending(self, job_uuid: uuid.UUID, requested_by: str) -> bool:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            updated = conn.execute(
                sa.text(
                    "UPDATE accepted_jobs SET state = 'cancelled',"
                    " cancel_requested_at = :now, cancel_requested_by = :by,"
                    " cancel_effective_at = :now"
                    " WHERE job_uuid = :j AND state = 'pending'"
                ),
                {"j": str(job_uuid), "by": requested_by, "now": now},
            )
            return updated.rowcount == 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admission.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/admission.py tests/integration/test_admission.py
git commit -m "feat: admission validator with pinning, idempotency, pending-cancel"
```

---

### Task 9: Orchestrator skeleton — dequeue, run records, cancel, status (W1-2 part 2)

**Files:**
- Create: `src/orchestrator/core.py`
- Test: `tests/integration/test_orchestrator_core.py`

**Interfaces:**
- Consumes: `AdmissionValidator` (Task 8), `RunState`, `run_can_transition` (Task 7), `make_engine` (Task 6).
- Produces: `Orchestrator(engine: sa.Engine)` with `dequeue_for_execution() -> uuid.UUID | None` (oldest pending job → `dequeued`, inserts a `runs` row in state `submitted` with `execution_started_at` and `durability_tier='v1-dev_non_durable'`, returns `run_uuid`), `advance(run_uuid: UUID, to: RunState) -> None` (raises `IllegalTransition` on invalid edges), `cancel_run(run_uuid: UUID, requested_by: str) -> bool` (records request; effective at next shot boundary — in skeleton, effective immediately when state is pre-`executing`), `run_state(run_uuid: UUID) -> RunState`, `list_runs(limit: int) -> list[tuple[uuid.UUID, str, str, str]]`. Compile-validation is a stub `validate(run_uuid) -> None` that advances `submitted → validated` (real Layer-4 compiler is Phase 2).

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_orchestrator_core.py`:

```python
import os
import uuid

import pytest

from orchestrator.admission import AdmissionValidator
from orchestrator.core import IllegalTransition, Orchestrator
from orchestrator.db import make_engine
from orchestrator.run_fsm import RunState

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:test@localhost:5432/controlsystem")
ALLOW = frozenset({"noop_template"})


@pytest.fixture()
def stack() -> tuple[AdmissionValidator, Orchestrator]:
    engine = make_engine(URL)
    return AdmissionValidator(engine, ALLOW), Orchestrator(engine)


def test_dequeue_creates_run_from_oldest_pending(stack) -> None:
    validator, orch = stack
    res = validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert run_uuid is not None
    assert orch.run_state(run_uuid) is RunState.SUBMITTED


def test_validate_advances_to_validated(stack) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    orch.validate(run_uuid)
    assert orch.run_state(run_uuid) is RunState.VALIDATED


def test_illegal_transition_raises_and_leaves_state(stack) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    with pytest.raises(IllegalTransition):
        orch.advance(run_uuid, RunState.EXECUTING)   # submitted -> executing is illegal
    assert orch.run_state(run_uuid) is RunState.SUBMITTED


def test_cancel_prevalidated_run_records_timestamps(stack) -> None:
    validator, orch = stack
    validator.enqueue("op", "noop_template", {}, uuid.uuid4().hex)
    run_uuid = orch.dequeue_for_execution()
    assert orch.cancel_run(run_uuid, requested_by="op")
    assert orch.run_state(run_uuid) is RunState.REJECTED


def test_empty_queue_returns_none(stack) -> None:
    _, orch = stack
    while orch.dequeue_for_execution() is not None:
        pass
    assert orch.dequeue_for_execution() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_orchestrator_core.py -v`
Expected: FAIL (`No module named 'orchestrator.core'`)

- [ ] **Step 3: Implement `src/orchestrator/core.py`**

```python
"""Tower orchestrator skeleton: dequeue -> run record -> FSM-enforced advancement.

Run state is Tower-authoritative (ADR-0001). This skeleton writes state straight to
Postgres; the Tower-local durable WAL + eventual mirror lands in Phase 3 with the
durable shot-commit work. Compile-validation is stubbed until the Phase 2 compiler.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from orchestrator.run_fsm import RunState, run_can_transition


class IllegalTransition(Exception):
    pass


class Orchestrator:
    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def dequeue_for_execution(self) -> uuid.UUID | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            job = conn.execute(
                sa.text(
                    "UPDATE accepted_jobs SET state = 'dequeued'"
                    " WHERE job_uuid = (SELECT job_uuid FROM accepted_jobs WHERE state = 'pending'"
                    "                   ORDER BY submitted_at LIMIT 1 FOR UPDATE SKIP LOCKED)"
                    " RETURNING job_uuid, user_id, template_name, parameters,"
                    "           descriptor_id, snapshot_id, submitted_at, idempotency_key"
                ),
            ).one_or_none()
            if job is None:
                return None
            run_uuid = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO runs (run_uuid, job_uuid, user_id, template_name, parameters,"
                    " snapshot_id, descriptor_id, state, submitted_at, execution_started_at,"
                    " durability_tier, idempotency_key)"
                    " VALUES (:r, :j, :u, :t, :p, :s, :d, :st, :sub, :now, :tier, :k)"
                ),
                {
                    "r": str(run_uuid), "j": str(job.job_uuid), "u": job.user_id,
                    "t": job.template_name, "p": json.dumps(dict(job.parameters))
                        if not isinstance(job.parameters, str) else job.parameters,
                    "s": job.snapshot_id, "d": job.descriptor_id,
                    "st": RunState.SUBMITTED.value, "sub": job.submitted_at, "now": now,
                    "tier": "v1-dev_non_durable", "k": job.idempotency_key,
                },
            )
        return run_uuid

    def run_state(self, run_uuid: uuid.UUID) -> RunState:
        with self.engine.connect() as conn:
            state = conn.execute(
                sa.text("SELECT state FROM runs WHERE run_uuid = :r"), {"r": str(run_uuid)}
            ).scalar_one()
        return RunState(state)

    def advance(self, run_uuid: uuid.UUID, to: RunState) -> None:
        with self.engine.begin() as conn:
            current = RunState(
                conn.execute(
                    sa.text("SELECT state FROM runs WHERE run_uuid = :r FOR UPDATE"),
                    {"r": str(run_uuid)},
                ).scalar_one()
            )
            if not run_can_transition(current, to):
                raise IllegalTransition(f"{current} -> {to}")
            conn.execute(
                sa.text("UPDATE runs SET state = :s WHERE run_uuid = :r"),
                {"s": to.value, "r": str(run_uuid)},
            )

    def validate(self, run_uuid: uuid.UUID) -> None:
        # Phase 2 replaces this stub with Layer-4 compile-validation + validation_token.
        self.advance(run_uuid, RunState.VALIDATED)

    def cancel_run(self, run_uuid: uuid.UUID, requested_by: str) -> bool:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            current = RunState(
                conn.execute(
                    sa.text("SELECT state FROM runs WHERE run_uuid = :r FOR UPDATE"),
                    {"r": str(run_uuid)},
                ).scalar_one()
            )
            if current in (RunState.SUBMITTED, RunState.VALIDATED, RunState.PLANNED):
                target = RunState.REJECTED
            elif current is RunState.ARMED:
                target = RunState.DISARMED
            elif current is RunState.EXECUTING:
                target = RunState.ABORTED   # skeleton: shot-boundary semantics land in Phase 2
            else:
                return False
            conn.execute(
                sa.text(
                    "UPDATE runs SET state = :s, cancel_requested_at = :now,"
                    " cancel_requested_by = :by, cancel_effective_at = :now WHERE run_uuid = :r"
                ),
                {"s": target.value, "now": now, "by": requested_by, "r": str(run_uuid)},
            )
        return True

    def list_runs(self, limit: int = 20) -> list[tuple[uuid.UUID, str, str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT run_uuid, state, template_name, user_id FROM runs"
                    " ORDER BY execution_started_at DESC LIMIT :n"
                ),
                {"n": limit},
            ).all()
        return [(uuid.UUID(str(r.run_uuid)), r.state, r.template_name, r.user_id) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_orchestrator_core.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/core.py tests/integration/test_orchestrator_core.py
git commit -m "feat: orchestrator skeleton with FSM-enforced run advancement and cancel"
```

---

### Task 10: Scheduler gRPC server + heartbeat monitor (W1-2 part 3)

**Files:**
- Create: `src/orchestrator/grpc_server.py`, `src/orchestrator/heartbeat.py`
- Test: `tests/unit/test_heartbeat.py`, `tests/integration/test_scheduler_grpc.py`

**Interfaces:**
- Consumes: `AdmissionValidator` (Task 8), `Orchestrator` (Task 9), `proto_gen.scheduler_pb2_grpc.SchedulerServicer` (Task 2).
- Produces: `SchedulerService(validator, orchestrator)` implementing `Enqueue`, `Cancel` (routes `target_kind=="job"` → `validator.cancel_pending`, `"run"` → `orchestrator.cancel_run`), `ListRuns`, `Status`; `serve_scheduler(validator, orchestrator, port) -> grpc.Server`; `HeartbeatMonitor(expected_services: frozenset[str], period_s: float = 1.0, miss_threshold: int = 3)` with `register(service_id: str) -> None`, `beat(service_id: str, now_ns: int) -> None`, and `unhealthy(now_ns: int) -> set[str]`. Status streams are per-subscriber: no shared `queue.Queue` may be drained by multiple clients. If scheduler later publishes run-state events instead of heartbeat-only events, it must use the same fan-out pattern as `LifecycleService`.

- [ ] **Step 1: Write the failing heartbeat test**

`tests/unit/test_heartbeat.py`:

```python
from orchestrator.heartbeat import HeartbeatMonitor

NS = 1_000_000_000


def test_service_healthy_within_threshold() -> None:
    mon = HeartbeatMonitor(expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3)
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=2 * NS) == set()


def test_service_unhealthy_after_three_misses() -> None:
    mon = HeartbeatMonitor(expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3)
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=4 * NS) == {"cam"}


def test_beat_recovers_service() -> None:
    mon = HeartbeatMonitor(expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3)
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=4 * NS) == {"cam"}
    mon.beat("cam", now_ns=4 * NS)
    assert mon.unhealthy(now_ns=5 * NS) == set()


def test_expected_service_that_never_beats_is_unhealthy() -> None:
    mon = HeartbeatMonitor(expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3)
    assert mon.unhealthy(now_ns=0) == {"cam"}
```

- [ ] **Step 2: Run to verify failure, then implement `src/orchestrator/heartbeat.py`**

Run: `uv run pytest tests/unit/test_heartbeat.py -v` → FAIL (`ModuleNotFoundError`)

```python
"""Heartbeat policy: 1 Hz default, 3-miss timeout (PLAN-V2 §04 heartbeat table)."""

from __future__ import annotations


class HeartbeatMonitor:
    def __init__(
        self,
        expected_services: frozenset[str] = frozenset(),
        period_s: float = 1.0,
        miss_threshold: int = 3,
    ) -> None:
        self._expected = set(expected_services)
        self._window_ns = int(period_s * miss_threshold * 1_000_000_000)
        self._last: dict[str, int] = {}

    def register(self, service_id: str) -> None:
        self._expected.add(service_id)

    def beat(self, service_id: str, now_ns: int) -> None:
        self._expected.add(service_id)
        self._last[service_id] = now_ns

    def unhealthy(self, now_ns: int) -> set[str]:
        return {
            sid
            for sid in self._expected
            if sid not in self._last or now_ns - self._last[sid] > self._window_ns
        }
```

Run: `uv run pytest tests/unit/test_heartbeat.py -v` → PASS (4 tests)

- [ ] **Step 3: Write the failing gRPC test**

`tests/integration/test_scheduler_grpc.py`:

```python
import os
import uuid

import grpc
import pytest

from proto_gen import run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator
from orchestrator.db import make_engine
from orchestrator.grpc_server import serve_scheduler

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:test@localhost:5432/controlsystem")


@pytest.fixture()
def stub():
    engine = make_engine(URL)
    validator = AdmissionValidator(engine, frozenset({"noop_template"}))
    orch = Orchestrator(engine)
    server = serve_scheduler(validator, orch, port=50071)
    channel = grpc.insecure_channel("127.0.0.1:50071")
    yield scheduler_pb2_grpc.SchedulerStub(channel)
    server.stop(grace=None)


def test_enqueue_returns_accepted_job(stub) -> None:
    resp = stub.Enqueue(run_model_pb2.RunRequest(
        user="op", template_name="noop_template", parameters_json="{}",
        idempotency_key=uuid.uuid4().hex), timeout=5)
    assert resp.WhichOneof("outcome") == "accepted"
    assert resp.accepted.descriptor_id > 0 and resp.accepted.snapshot_id > 0


def test_enqueue_rejection_is_typed(stub) -> None:
    resp = stub.Enqueue(run_model_pb2.RunRequest(
        user="op", template_name="nope", parameters_json="{}",
        idempotency_key=uuid.uuid4().hex), timeout=5)
    assert resp.WhichOneof("outcome") == "rejected"
    assert resp.rejected.code == "template_not_allowed"


def test_cancel_pending_job_over_grpc(stub) -> None:
    accepted = stub.Enqueue(run_model_pb2.RunRequest(
        user="op", template_name="noop_template", parameters_json="{}",
        idempotency_key=uuid.uuid4().hex), timeout=5).accepted
    resp = stub.Cancel(run_model_pb2.CancelRequest(
        target=accepted.job_uuid, target_kind="job", requested_by="op",
        idempotency_key=uuid.uuid4().hex), timeout=5)
    assert resp.ok and resp.state == "cancelled"


def test_list_runs(stub) -> None:
    resp = stub.ListRuns(scheduler_pb2.ListRunsRequest(limit=5), timeout=5)
    assert resp is not None  # shape check; rows depend on prior tests
```

- [ ] **Step 4: Run to verify failure, then implement `src/orchestrator/grpc_server.py`**

Run: `uv run pytest tests/integration/test_scheduler_grpc.py -v` → FAIL (`ModuleNotFoundError`)

```python
"""Scheduler gRPC surface: admission Enqueue + Tower run verbs behind one endpoint.

In v1-dev both roles are co-located; the servicer keeps them as two injected objects
so the v1-lab split is a deployment change (ADR-0001)."""

from __future__ import annotations

import json
import uuid
from concurrent import futures
from typing import Any, Iterator

import grpc

from proto_gen import lifecycle_pb2, run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator


class SchedulerService(scheduler_pb2_grpc.SchedulerServicer):
    def __init__(self, validator: AdmissionValidator, orchestrator: Orchestrator) -> None:
        self.validator = validator
        self.orchestrator = orchestrator

    def Enqueue(self, request: run_model_pb2.RunRequest, context: Any) -> run_model_pb2.EnqueueResponse:
        res = self.validator.enqueue(
            user=request.user,
            template_name=request.template_name,
            parameters=json.loads(request.parameters_json or "{}"),
            idempotency_key=request.idempotency_key,
            requested_descriptor_id=(
                request.requested_descriptor_id
                if request.HasField("requested_descriptor_id") else None
            ),
        )
        if not res.accepted:
            return run_model_pb2.EnqueueResponse(
                rejected=run_model_pb2.Rejection(
                    code=res.rejection_code or "rejected",
                    reason=res.rejection_reason or "",
                )
            )
        return run_model_pb2.EnqueueResponse(
            accepted=run_model_pb2.AcceptedJob(
                job_uuid=str(res.job_uuid),
                request=request,
                descriptor_id=res.descriptor_id or 0,
                snapshot_id=res.snapshot_id or 0,
                request_hash=res.request_hash or b"",
            )
        )

    def Cancel(self, request: run_model_pb2.CancelRequest, context: Any) -> run_model_pb2.CancelResponse:
        target = uuid.UUID(request.target)
        if request.target_kind == "job":
            ok = self.validator.cancel_pending(target, requested_by=request.requested_by)
            return run_model_pb2.CancelResponse(ok=ok, state="cancelled" if ok else "",
                                                error="" if ok else "not pending")
        ok = self.orchestrator.cancel_run(target, requested_by=request.requested_by)
        state = self.orchestrator.run_state(target).value if ok else ""
        return run_model_pb2.CancelResponse(ok=ok, state=state, error="" if ok else "not cancellable")

    def ListRuns(self, request: scheduler_pb2.ListRunsRequest, context: Any) -> scheduler_pb2.ListRunsResponse:
        rows = self.orchestrator.list_runs(limit=request.limit or 20)
        return scheduler_pb2.ListRunsResponse(
            runs=[scheduler_pb2.RunRow(run_uuid=str(r), state=s, template_name=t, user=u)
                  for r, s, t, u in rows]
        )

    def Status(self, request: lifecycle_pb2.StatusRequest, context: Any) -> Iterator[lifecycle_pb2.StatusEvent]:
        import time
        while context is None or context.is_active():
            yield lifecycle_pb2.StatusEvent(service_id="scheduler", state="RUNNING",
                                            kind="heartbeat", wall_ns=time.time_ns())
            time.sleep(1.0)


def serve_scheduler(validator: AdmissionValidator, orchestrator: Orchestrator, port: int) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    scheduler_pb2_grpc.add_SchedulerServicer_to_server(SchedulerService(validator, orchestrator), server)
    server.add_insecure_port(f"127.0.0.1:{port}")  # mTLS lands with the v1-lab split
    server.start()
    return server
```

Run: `uv run pytest tests/integration/test_scheduler_grpc.py tests/unit/test_heartbeat.py -v` → PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/grpc_server.py src/orchestrator/heartbeat.py \
        tests/unit/test_heartbeat.py tests/integration/test_scheduler_grpc.py
git commit -m "feat: scheduler gRPC service and heartbeat monitor"
```

---

### Task 11: Operator CLI (W1-7)

**Files:**
- Create: `src/dashboards/operator_cli/__init__.py`, `src/dashboards/operator_cli/main.py`
- Test: `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: `SchedulerStub` over gRPC (Task 10).
- Produces: `lab` CLI (`[project.scripts] lab = "dashboards.operator_cli.main:app"` added to `pyproject.toml`) with commands `submit-run`, `cancel-job`, `cancel-run`, `list-runs`, `status`; `--host/--port` options defaulting to `127.0.0.1:50070`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_cli.py`:

```python
import os
import uuid

import pytest
from typer.testing import CliRunner

from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator
from orchestrator.db import make_engine
from orchestrator.grpc_server import serve_scheduler

pytestmark = pytest.mark.integration

URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:test@localhost:5432/controlsystem")
runner = CliRunner()


@pytest.fixture()
def server():
    engine = make_engine(URL)
    srv = serve_scheduler(AdmissionValidator(engine, frozenset({"noop_template"})),
                          Orchestrator(engine), port=50072)
    yield srv
    srv.stop(grace=None)


def test_submit_run_prints_job_uuid(server) -> None:
    from dashboards.operator_cli.main import app

    result = runner.invoke(app, [
        "submit-run", "--user", "op", "--template", "noop_template",
        "--params", "{}", "--key", uuid.uuid4().hex, "--port", "50072",
    ])
    assert result.exit_code == 0
    assert "accepted job_uuid=" in result.output


def test_submit_bad_template_exits_nonzero(server) -> None:
    from dashboards.operator_cli.main import app

    result = runner.invoke(app, [
        "submit-run", "--user", "op", "--template", "nope",
        "--params", "{}", "--key", uuid.uuid4().hex, "--port", "50072",
    ])
    assert result.exit_code == 1
    assert "template_not_allowed" in result.output
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_cli.py -v`
Expected: FAIL (`No module named 'dashboards.operator_cli.main'`; also `typer` CliRunner import — add `typer` already in deps)

- [ ] **Step 3: Implement `src/dashboards/operator_cli/main.py`**

```python
"""Minimal `lab` operator CLI (PLAN-V2 W1-7)."""

from __future__ import annotations

import grpc
import typer

from proto_gen import run_model_pb2, scheduler_pb2, scheduler_pb2_grpc

app = typer.Typer(no_args_is_help=True)


def _stub(host: str, port: int) -> scheduler_pb2_grpc.SchedulerStub:
    return scheduler_pb2_grpc.SchedulerStub(grpc.insecure_channel(f"{host}:{port}"))


@app.command("submit-run")
def submit_run(
    user: str = typer.Option(...),
    template: str = typer.Option(...),
    params: str = typer.Option("{}", help="JSON object of parameters"),
    key: str = typer.Option(..., help="idempotency key"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(50070),
) -> None:
    resp = _stub(host, port).Enqueue(
        run_model_pb2.RunRequest(user=user, template_name=template,
                                 parameters_json=params, idempotency_key=key),
        timeout=10,
    )
    if resp.WhichOneof("outcome") == "rejected":
        typer.echo(f"rejected: {resp.rejected.code}: {resp.rejected.reason}")
        raise typer.Exit(code=1)
    typer.echo(
        f"accepted job_uuid={resp.accepted.job_uuid}"
        f" descriptor_id={resp.accepted.descriptor_id} snapshot_id={resp.accepted.snapshot_id}"
    )


def _cancel(target: str, kind: str, by: str, host: str, port: int) -> None:
    resp = _stub(host, port).Cancel(
        run_model_pb2.CancelRequest(target=target, target_kind=kind,
                                    requested_by=by, idempotency_key=f"cancel-{target}"),
        timeout=10,
    )
    if not resp.ok:
        typer.echo(f"cancel failed: {resp.error}")
        raise typer.Exit(code=1)
    typer.echo(f"cancelled: state={resp.state}")


@app.command("cancel-job")
def cancel_job(job_uuid: str, by: str = typer.Option("operator"),
               host: str = typer.Option("127.0.0.1"), port: int = typer.Option(50070)) -> None:
    _cancel(job_uuid, "job", by, host, port)


@app.command("cancel-run")
def cancel_run(run_uuid: str, by: str = typer.Option("operator"),
               host: str = typer.Option("127.0.0.1"), port: int = typer.Option(50070)) -> None:
    _cancel(run_uuid, "run", by, host, port)


@app.command("list-runs")
def list_runs(limit: int = typer.Option(20),
              host: str = typer.Option("127.0.0.1"), port: int = typer.Option(50070)) -> None:
    resp = _stub(host, port).ListRuns(scheduler_pb2.ListRunsRequest(limit=limit), timeout=10)
    for row in resp.runs:
        typer.echo(f"{row.run_uuid}  {row.state:12s}  {row.template_name}  {row.user}")


@app.command("status")
def status(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(50070),
           events: int = typer.Option(3)) -> None:
    from proto_gen import lifecycle_pb2

    stream = _stub(host, port).Status(lifecycle_pb2.StatusRequest(), timeout=events * 2 + 5)
    for i, ev in enumerate(stream):
        typer.echo(f"{ev.service_id} {ev.state} {ev.kind}")
        if i + 1 >= events:
            break


if __name__ == "__main__":
    app()
```

Add to `pyproject.toml` under `[project.scripts]`: `lab = "dashboards.operator_cli.main:app"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/dashboards/operator_cli pyproject.toml tests/integration/test_cli.py
git commit -m "feat: lab operator CLI (submit-run, cancel, list-runs, status)"
```

---

### Task 12: provisional `RearrangementBatchV1` encoder + Phase 0A hardware harness

**Files:**
- Create: `src/broker/rearrangement_batch.py`
- Create: `tests/hardware/w0a1_input_stream_latency.py`, `tests/hardware/w0a5_ntp_drift.py`, `tests/hardware/derive_n_max_moves.py`
- Test: `tests/unit/test_rearrangement_batch.py`

**Interfaces:**
- Consumes: nothing in-repo (QUA scripts use `qm-qua`, installed lab-side only — not a project dependency yet).
- Produces: provisional constants `PROTOCOL_VERSION=1`, `N_MAX_MOVES=1024` (placeholder, ADR-0002 remains Proposed), `HEADER_WORDS=16`, `MOVE_WORDS=6`, `BATCH_WORDS`, all `OFF_*` offsets for a signed-QUA-safe candidate layout; `Move` frozen dataclass `(src_x, src_y, tgt_x, tgt_y, group_id, t_ramp_ticks, flags)` (flags folded into the 6th word alongside group_id per layout below); `encode_batch(...) -> list[int]` and `decode_header(words: Sequence[int]) -> BatchHeader`. This is Phase 0A support code for representative payload generation, not a frozen RT contract. It stays provisional until W0A-1 derives `N_MAX_MOVES`, proves OPX/QOP capacity, and composes the measured latency budget. ADR-0002's PLAN-V2 seed uses two 32-bit words for 64-bit fields, but QUA `int` is signed; this task intentionally uses 31-bit chunks so high-bit hashes do not overflow signed QUA words.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_rearrangement_batch.py`:

```python
import pytest

from broker.rearrangement_batch import (
    BATCH_WORDS, HEADER_WORDS, MOVE_WORDS, N_MAX_MOVES, PROTOCOL_VERSION,
    OFF_IDEAL_MOVES, OFF_N_MOVES, OFF_PROTOCOL_VERSION, OFF_SEQUENCE_NO,
    Move, decode_header, encode_batch,
)


def _moves(n: int) -> list[Move]:
    return [Move(src_x=i, src_y=0, tgt_x=i, tgt_y=1, group_id=0, t_ramp_ticks=100, flags=0)
            for i in range(n)]


def test_batch_words_constant() -> None:
    assert HEADER_WORDS == 16 and MOVE_WORDS == 6
    assert BATCH_WORDS == HEADER_WORDS + N_MAX_MOVES * MOVE_WORDS == 6160


def test_encode_is_fixed_width_and_padded() -> None:
    words = encode_batch(sequence_no=1, deadline_ppu_ticks=10_000,
                         snapshot_hash64=0xAABB, descriptor_hash64=0xCCDD,
                         loop_index=0, max_loops=3, ideal_moves=3, moves=_moves(3))
    assert len(words) == BATCH_WORDS
    assert words[OFF_PROTOCOL_VERSION] == PROTOCOL_VERSION
    assert words[OFF_N_MOVES] == 3
    assert words[HEADER_WORDS + 3 * MOVE_WORDS :] == [0] * ((N_MAX_MOVES - 3) * MOVE_WORDS)


def test_header_roundtrip_including_64bit_fields() -> None:
    deadline = (1 << 40) + 12345          # needs lo/hi split
    words = encode_batch(sequence_no=7, deadline_ppu_ticks=deadline,
                         snapshot_hash64=(1 << 63) | 5, descriptor_hash64=42,
                         loop_index=1, max_loops=3, ideal_moves=2, moves=_moves(2))
    header = decode_header(words)
    assert header.sequence_no == 7
    assert header.deadline_ppu_ticks == deadline
    assert header.snapshot_hash64 == (1 << 63) | 5
    assert header.loop_index == 1 and header.max_loops == 3
    assert max(words[:HEADER_WORDS]) <= 0x7FFF_FFFF


def test_truncation_signal_ideal_gt_n_moves_allowed() -> None:
    words = encode_batch(sequence_no=1, deadline_ppu_ticks=1, snapshot_hash64=0,
                         descriptor_hash64=0, loop_index=0, max_loops=3,
                         ideal_moves=N_MAX_MOVES + 50, moves=_moves(2))
    assert words[OFF_IDEAL_MOVES] == N_MAX_MOVES + 50
    assert words[OFF_N_MOVES] == 2


def test_too_many_moves_rejected() -> None:
    with pytest.raises(ValueError):
        encode_batch(sequence_no=1, deadline_ppu_ticks=1, snapshot_hash64=0,
                     descriptor_hash64=0, loop_index=0, max_loops=3,
                     ideal_moves=N_MAX_MOVES + 1, moves=_moves(N_MAX_MOVES + 1))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_rearrangement_batch.py -v`
Expected: FAIL (`No module named 'broker.rearrangement_batch'`)

- [ ] **Step 3: Implement `src/broker/rearrangement_batch.py`**

```python
"""RearrangementBatchV1 wire layout (PLAN-V2 §07, ADR-0002 — PROVISIONAL until Phase 0A).

Fixed-width homogeneous int vector for the QUA input stream. QUA ints are signed, so
all 64-bit quantities are split into three 31-bit chunks (lo, mid, hi). This avoids
the high-bit overflow bug from a naive unsigned-32 split. ADR-0002 is still Proposed;
Phase 0A owns freezing the final wire layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PROTOCOL_VERSION = 1
N_MAX_MOVES = 1024  # placeholder — Phase 0A derives the real bound (ADR-0002 gate)
HEADER_WORDS = 16
MOVE_WORDS = 6
BATCH_WORDS = HEADER_WORDS + N_MAX_MOVES * MOVE_WORDS

OFF_PROTOCOL_VERSION = 0
OFF_SEQUENCE_NO = 1
OFF_N_MOVES = 2
OFF_DEADLINE_TICKS_LO = 3
OFF_DEADLINE_TICKS_MID = 4
OFF_DEADLINE_TICKS_HI = 5
OFF_SNAPSHOT_HASH_LO = 6
OFF_SNAPSHOT_HASH_MID = 7
OFF_SNAPSHOT_HASH_HI = 8
OFF_DESCRIPTOR_HASH_LO = 9
OFF_DESCRIPTOR_HASH_MID = 10
OFF_DESCRIPTOR_HASH_HI = 11
OFF_LOOP_INDEX = 12
OFF_MAX_LOOPS = 13
OFF_IDEAL_MOVES = 14
OFF_HEADER_FLAGS = 15

_MASK31 = 0x7FFF_FFFF


@dataclass(frozen=True)
class Move:
    src_x: int
    src_y: int
    tgt_x: int
    tgt_y: int
    group_id: int
    t_ramp_ticks: int
    flags: int  # bit 0: force pause for analysis; bit 1: abort if prior in group failed


@dataclass(frozen=True)
class BatchHeader:
    protocol_version: int
    sequence_no: int
    n_moves: int
    deadline_ppu_ticks: int
    snapshot_hash64: int
    descriptor_hash64: int
    loop_index: int
    max_loops: int
    ideal_moves: int
    header_flags: int


def _split64(value: int) -> tuple[int, int, int]:
    value &= (1 << 64) - 1
    return value & _MASK31, (value >> 31) & _MASK31, (value >> 62) & _MASK31


def _join64(lo: int, mid: int, hi: int) -> int:
    return (hi << 62) | (mid << 31) | lo


def encode_batch(
    *,
    sequence_no: int,
    deadline_ppu_ticks: int,
    snapshot_hash64: int,
    descriptor_hash64: int,
    loop_index: int,
    max_loops: int,
    ideal_moves: int,
    moves: Sequence[Move],
) -> list[int]:
    if len(moves) > N_MAX_MOVES:
        raise ValueError(f"n_moves {len(moves)} exceeds N_MAX_MOVES {N_MAX_MOVES}")
    dl_lo, dl_mid, dl_hi = _split64(deadline_ppu_ticks)
    sn_lo, sn_mid, sn_hi = _split64(snapshot_hash64)
    de_lo, de_mid, de_hi = _split64(descriptor_hash64)
    words = [0] * BATCH_WORDS
    words[OFF_PROTOCOL_VERSION] = PROTOCOL_VERSION
    words[OFF_SEQUENCE_NO] = sequence_no & _MASK31
    words[OFF_N_MOVES] = len(moves)
    words[OFF_DEADLINE_TICKS_LO] = dl_lo
    words[OFF_DEADLINE_TICKS_MID] = dl_mid
    words[OFF_DEADLINE_TICKS_HI] = dl_hi
    words[OFF_SNAPSHOT_HASH_LO] = sn_lo
    words[OFF_SNAPSHOT_HASH_MID] = sn_mid
    words[OFF_SNAPSHOT_HASH_HI] = sn_hi
    words[OFF_DESCRIPTOR_HASH_LO] = de_lo
    words[OFF_DESCRIPTOR_HASH_MID] = de_mid
    words[OFF_DESCRIPTOR_HASH_HI] = de_hi
    words[OFF_LOOP_INDEX] = loop_index
    words[OFF_MAX_LOOPS] = max_loops
    words[OFF_IDEAL_MOVES] = ideal_moves
    words[OFF_HEADER_FLAGS] = 0  # reserved, must be zero in v1
    for i, m in enumerate(moves):
        base = HEADER_WORDS + i * MOVE_WORDS
        words[base + 0] = m.src_x
        words[base + 1] = m.src_y
        words[base + 2] = m.tgt_x
        words[base + 3] = m.tgt_y
        words[base + 4] = m.group_id
        words[base + 5] = ((m.flags & 0xFFFF) << 16) | (m.t_ramp_ticks & 0xFFFF)
    return words


def decode_header(words: Sequence[int]) -> BatchHeader:
    return BatchHeader(
        protocol_version=words[OFF_PROTOCOL_VERSION],
        sequence_no=words[OFF_SEQUENCE_NO],
        n_moves=words[OFF_N_MOVES],
        deadline_ppu_ticks=_join64(
            words[OFF_DEADLINE_TICKS_LO], words[OFF_DEADLINE_TICKS_MID], words[OFF_DEADLINE_TICKS_HI]
        ),
        snapshot_hash64=_join64(
            words[OFF_SNAPSHOT_HASH_LO], words[OFF_SNAPSHOT_HASH_MID], words[OFF_SNAPSHOT_HASH_HI]
        ),
        descriptor_hash64=_join64(
            words[OFF_DESCRIPTOR_HASH_LO], words[OFF_DESCRIPTOR_HASH_MID], words[OFF_DESCRIPTOR_HASH_HI]
        ),
        loop_index=words[OFF_LOOP_INDEX],
        max_loops=words[OFF_MAX_LOOPS],
        ideal_moves=words[OFF_IDEAL_MOVES],
        header_flags=words[OFF_HEADER_FLAGS],
    )
```

Run: `uv run pytest tests/unit/test_rearrangement_batch.py -v` → PASS (5 tests)

- [ ] **Step 4: Write the Phase 0A harness scripts (lab-run, not CI)**

`tests/hardware/w0a1_input_stream_latency.py`:

```python
"""W0A-1: push_to_input_stream latency vs declared vector size.

Run on the Tower against the lab OPX+. Requires `qm-qua` installed lab-side.
For each size in SIZES, compiles a QUA program that declares an input stream of that
size, loops `advance_input_stream -> get_timestamp -> output stream`, and measures
PPU-tick deltas across N_SAMPLES pushes. Writes quantiles to w0a1_results.json.
Host-side ping is deliberately NOT measured (PLAN-V2 §06 excludes it)."""

import json
import statistics
import sys
from pathlib import Path

SIZES = [4, 64, 256, 2048, 6160]  # words; 6160 = BATCH_WORDS at provisional N_MAX_MOVES=1024
N_SAMPLES = 100_000
OPX_HOST = "192.168.88.10"  # QM router enclave, VLAN 50 — adjust to lab assignment


def build_program(size: int):  # type: ignore[no-untyped-def]
    from qm.qua import (advance_input_stream, declare_input_stream, declare_stream,
                        infinite_loop_, program, save)
    from qm.qua._dsl import get_timestamp  # QOP >= 2.2

    with program() as prog:
        batch = declare_input_stream(int, name="latency_probe", size=size)
        ts_out = declare_stream()
        with infinite_loop_():
            advance_input_stream(batch)
            save(get_timestamp(), ts_out)
        # stream_processing: save_all ts_out -> "ts"
    return prog


def main() -> None:
    from qm import QuantumMachinesManager

    results = {}
    qmm = QuantumMachinesManager(host=OPX_HOST)
    for size in SIZES:
        # NOTE: capacity check first — if compile/run of size=6160 fails, record it and
        # follow the §07 escape (shrink N_MAX_MOVES / multi-batch) before ADR-0002.
        prog = build_program(size)
        # ... open qm with lab config, execute prog, then:
        # for _ in range(N_SAMPLES): job.push_to_input_stream("latency_probe", [0]*size)
        # ticks = fetch "ts" stream; deltas between consecutive timestamps (ns = ticks*4)
        deltas: list[float] = []  # filled by the loop above when run in the lab
        if deltas:
            deltas.sort()
            results[size] = {
                "p50": deltas[len(deltas) // 2],
                "p95": deltas[int(len(deltas) * 0.95)],
                "p99": deltas[int(len(deltas) * 0.99)],
                "p999": deltas[int(len(deltas) * 0.999)],
                "max": deltas[-1],
                "n": len(deltas),
            }
    Path(__file__).with_name("w0a1_results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    sys.exit(main())
```

`tests/hardware/w0a5_ntp_drift.py`:

```python
"""W0A-5: 24 h NTP drift baseline across lab hosts (Windows).

Run on each host: `python w0a5_ntp_drift.py --hours 24`. Parses `w32tm /query /status`
once per minute, appends (iso_time, offset_s) to w0a5_<hostname>.csv.
Gate: sustained |offset| <= 10 ms (PLAN-V2 §06)."""

import argparse
import csv
import datetime
import platform
import re
import subprocess
import time
from pathlib import Path


def query_offset_s() -> float | None:
    out = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, text=True).stdout
    m = re.search(r"Phase Offset:\s*([-\d.]+)s", out)
    return float(m.group(1)) if m else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()
    path = Path(__file__).with_name(f"w0a5_{platform.node()}.csv")
    deadline = time.time() + args.hours * 3600
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        while time.time() < deadline:
            offset = query_offset_s()
            writer.writerow([datetime.datetime.now().isoformat(), offset])
            f.flush()
            time.sleep(60)


if __name__ == "__main__":
    main()
```

`tests/hardware/derive_n_max_moves.py`:

```python
"""N_MAX_MOVES derivation gate (PLAN-V2 §07): compute the per-loop move bound from
descriptor geometry + assignment policy, for current (~100 atoms) and projected
(1000 atoms) geometries. Output feeds ADR-0002; the placeholder 1024 is NOT the answer.

Model: worst case = every target site needs one move, plus collision-avoidance detours.
Refine `detour_factor` and `parallel_groups` from the chosen assignment algorithm."""

import json
from pathlib import Path


def derive(max_sites: int, target_sites: int, detour_factor: float, parallel_groups: int) -> int:
    worst_case_moves = int(target_sites * detour_factor)
    return min(worst_case_moves, max_sites)


def main() -> None:
    scenarios = {
        "current_100": derive(max_sites=256, target_sites=100, detour_factor=1.5, parallel_groups=4),
        "projected_1000": derive(max_sites=2048, target_sites=1000, detour_factor=1.5, parallel_groups=8),
    }
    Path(__file__).with_name("n_max_moves_derivation.json").write_text(json.dumps(scenarios, indent=2))
    print(json.dumps(scenarios, indent=2))
    print("ADR-0002 rule: freeze the current-operation bound; record the 1000-atom scaling trigger.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify unit tests + full suite still green**

Run: `uv run pytest --ignore=tests/hardware -v`
Expected: PASS (all tasks' tests)

- [ ] **Step 6: Commit**

```bash
git add src/broker/rearrangement_batch.py tests/unit/test_rearrangement_batch.py tests/hardware
git commit -m "feat: RearrangementBatchV1 encoder + Phase 0A measurement harness"
```

---

### Task 13: Pre-Phase-1 software-readiness verification + milestone record

**Files:**
- Create: `.planning/MILESTONES.md`
- Modify: `README.md` (quickstart: docker Postgres, migrate, run scheduler, use `lab` CLI)

**Interfaces:**
- Consumes: everything above.
- Produces: written software-readiness record that explicitly keeps PLAN-V2 §12 Phase 0A/Phase 1 gates blocked where hardware evidence is missing.

- [ ] **Step 1: Run the full verification suite**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
uv run pytest --cov --cov-fail-under=80 --ignore=tests/hardware
```

Expected: all green, coverage ≥ 80% on `src/orchestrator`, `src/compiler`, `src/device_servers`, `src/broker`.

- [ ] **Step 2: Walk the software-readiness evidence manually**

Map each PLAN-V2 §12 Phase-1 software-side gate item to its evidence. This is readiness evidence only, not Phase 1 completion:

1. Orchestrator starts and exposes gRPC; admission enqueues an `AcceptedJob` → `tests/integration/test_scheduler_grpc.py::test_enqueue_returns_accepted_job`.
2. Fake camera registers, returns typed `Capabilities` + `Health` → `tests/contract/` + `tests/integration/test_fake_camera_grpc.py`.
3. `Enqueue(RunRequest)` persists an `AcceptedJob`; Tower dequeue compile-validates into a run → `test_admission.py` + `test_orchestrator_core.py::test_validate_advances_to_validated` (compile-validation stubbed; full `RunPlan` is Phase 2).
4. State machine transitions visible via `Status` stream → CLI `lab status` against a running scheduler.
5. Pending-job + active-run cancels record request/effective timestamps → `test_admission.py::test_cancel_pending_records_timestamps` + `test_orchestrator_core.py::test_cancel_prevalidated_run_records_timestamps`.
6. Heartbeat miss surfaces a typed error within 5 s → `tests/unit/test_heartbeat.py` (policy) — wire-level enforcement (orchestrator marking services `UNHEALTHY` and refusing arms) is the first Phase 2 task.

- [ ] **Step 3: Write `.planning/MILESTONES.md`**

```markdown
# Milestones

## Pre-Phase-1 Software Readiness — Control-Plane Skeleton (v1-dev, co-located)
Date: <fill on completion>
Status: software-readiness slice complete; PLAN-V2 Phase 1 remains blocked until
Phase 0A gates pass.

Ready:
- Control-plane proto contracts, lifecycle FSM, fake-camera contract tests, schema v1,
  fake OPX lifecycle shell, admission validator, orchestrator skeleton, scheduler gRPC,
  operator CLI.
- Provisional `RearrangementBatchV1` encoder + hardware harness code exists for W0A-1
  representative payloads.

Blocked on W0A-1...W0A-5:
- RT contract freeze (`RearrangementBatchV1`, `BATCH_WORDS`, `N_MAX_MOVES`);
- composed latency budget (`t_compute + t_insert + t_execute <= 5 ms`);
- GPUDirect/CPU baseline and SDK ownership model;
- broker priority/affinity decision;
- safety-plane independence and NTP drift evidence.

Not Phase 1 done:
- Heartbeat policy implemented + tested; orchestrator-side `UNHEALTHY` enforcement
  still deferred.
- Compile-validation remains stubbed; full `RunPlan`/`validation_token` path remains
  Phase 2/3 work.
- Calibration-freshness checks remain Phase 3 work.
- Fake OPX is lifecycle-only. Real QM SDK connection, fake execution results, `ShotResult`,
  and `RunSummary` remain Phase 2/Phase 0A work.

Deviations: lifecycle disarm semantics are recorded in ADR-0017 (§04 diagram vs
B13 prose reconciliation). No separate ADR is required for the phase-gate naming
reconciliation.
Next: run Phase 0A lab measurements using tests/hardware/. Phase 2 does not start
as a PLAN-V2 phase until the written Phase 0A gate is complete.
```

- [ ] **Step 4: Commit**

```bash
git add .planning/MILESTONES.md README.md
git commit -m "docs: record pre-phase-1 software readiness"
```

---

## What comes next (not in this plan)

- **Phase 0A in the lab (blocking track):** run `tests/hardware/` scripts on the Tower/OPX; complete `N_MAX_MOVES` derivation; ratify ADR-0002/0010; write `network/MINIMAL_OPX.md`; safety-plane fault-injection per PLAN-V2 §09.
- **Phase 2:** richer fake OPX broker double beyond lifecycle verbs, Layer-4 compiler v0 (+ `validation_token` issuance in `src/safety/`), `ShotResult`/`RunSummary` path, read-only observer dashboard, orchestrator `UNHEALTHY` enforcement from heartbeats. This starts only after the Phase 0A gate is written complete.
- **Phase 3:** full calibration tables + publication transaction, execution bundles, durable shot-commit protocol (spool + fsync + replay), recovery tests, off-host replica.
- **Phases 4–6:** modeled devices, Andor adapter + commissioning demo (`v1-dev_non_durable`), SLM remote adapter + `v1-lab` EliteDesk split.

## Self-review notes

- Coverage vs spec: all seven Phase-1 workstreams (W1-1...W1-7) have tasks. W1-6 is split: the hardware-free lifecycle/gRPC shell is covered by `fake_opx` in Task 5; the QM SDK connection and `RtJobResult` path are blocked on OPX access and remain Phase 2/Phase 0A work. The previous conflation of those halves is explicitly avoided.
- Type consistency: `AdmissionResult`, `Orchestrator.dequeue_for_execution`, proto message names, and FSM enums are used with identical names/signatures across Tasks 8–11.
- Known simplifications, all flagged inline: insecure gRPC ports until the v1-lab mTLS rollout; compile-validation stub; minimal `calibration_snapshots` table as FK target; `runs.bundle_id` deferred to the Phase 3 migration.
