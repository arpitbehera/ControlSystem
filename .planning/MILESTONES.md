# Milestones

## Pre-Phase-1 Software Readiness - Control-Plane Skeleton (v1-dev, co-located)

Date: 2026-07-06
Status: software-readiness slice complete; PLAN-V2 Phase 1 remains blocked until
Phase 0A gates pass.

Ready:
- Control-plane proto contracts, lifecycle FSM, fake-camera contract tests, schema v1,
  fake OPX lifecycle shell, admission validator, orchestrator skeleton, scheduler gRPC,
  operator CLI.
- Provisional `RearrangementBatchV1` encoder plus hardware harness code exists for
  W0A-1 representative payloads.

Evidence:
- Orchestrator starts and exposes gRPC; admission enqueues an `AcceptedJob`:
  `tests/integration/test_scheduler_grpc.py::test_enqueue_returns_accepted_job`.
- Fake camera returns typed `Capabilities` and `Health`: `tests/contract/` and
  `tests/integration/test_fake_camera_grpc.py`.
- `Enqueue(RunRequest)` persists an `AcceptedJob`; Tower dequeue creates a run and
  stub compile-validation advances it: `tests/integration/test_admission.py` and
  `tests/integration/test_orchestrator_core.py::test_validate_advances_to_validated`.
- Scheduler `Status` stream exposes heartbeat events; CLI can consume them with
  `lab status`.
- Pending-job and pre-execution run cancels record request/effective timestamps:
  `tests/integration/test_admission.py::test_cancel_pending_records_timestamps` and
  `tests/integration/test_orchestrator_core.py::test_cancel_prevalidated_run_records_timestamps`.
- Heartbeat miss policy surfaces unhealthy services within the configured window:
  `tests/unit/test_heartbeat.py`. Orchestrator-side `UNHEALTHY` enforcement is
  deferred.

Verification:
- `uv run ruff check src tests && uv run black --check src tests && uv run mypy`
  passed.
- `uv run pytest --cov --cov-fail-under=80 --ignore=tests/hardware` passed:
  83 tests, total coverage 95.32%.

Blocked on W0A-1...W0A-5:
- RT contract freeze (`RearrangementBatchV1`, `BATCH_WORDS`, `N_MAX_MOVES`);
- composed latency budget (`t_compute + t_insert + t_execute <= 5 ms`);
- GPUDirect/CPU baseline and SDK ownership model;
- broker priority/affinity decision;
- safety-plane independence and NTP drift evidence.

Not Phase 1 done:
- Heartbeat policy implemented and tested; orchestrator-side `UNHEALTHY` enforcement
  still deferred.
- Compile-validation remains stubbed; full `RunPlan` and `validation_token` path
  remain Phase 2/3 work.
- Calibration-freshness checks remain Phase 3 work.
- Fake OPX is lifecycle-only. Real QM SDK connection, fake execution results,
  `ShotResult`, and `RunSummary` remain Phase 2/Phase 0A work.

Deviations:
- Lifecycle disarm semantics are recorded in ADR-0017 (section 04 diagram vs B13
  prose reconciliation).
- No separate ADR is required for the phase-gate naming reconciliation.

Next:
- Run Phase 0A lab measurements using `tests/hardware/`.
- Phase 2 does not start as a PLAN-V2 phase until the written Phase 0A gate is
  complete.
