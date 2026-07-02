# Roadmap: Neutral Atom Lab Control System

**Created:** 2026-04-08
**Granularity:** Standard
**Mode:** Interactive

## Summary

**6 phases** | **17 v1 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Control-Plane Skeleton | Establish `PC1` orchestration, service discovery, lifecycle contracts, and run-state foundations | PLAT-01, PLAT-02, PLAT-03, RUN-01, RUN-02, RUN-03, SAFE-01 | 5 |
| 2 | Fake Execution Slice | Prove the architecture end to end with a fake `OPX/camera` path, observer client, and automated contract tests | PLAT-04, RUN-04, TEST-01, TEST-02, UI-01 | 5 |
| 3 | Snapshot And Recovery Policy | Freeze execution inputs into typed snapshots and enforce shot-boundary recovery behavior | SAFE-02, CFG-01 | 4 |
| 4 | Modeled Device Foundation | Represent OPX-driven analog elements as calibration-aware modeled devices in the run model | MODEL-01 | 4 |
| 5 | First Local Hardware Adapter | Integrate at least one real `PC1` device through the platform contract | HW-01 | 4 |
| 6 | First Remote Hardware Adapter | Integrate at least one real remote device on `PC2` or `PC3` through the same platform contract | HW-02 | 4 |

## Phase Details

### Phase 1: Control-Plane Skeleton

**Goal:** Establish the centralized control-plane foundation on `PC1`, including service discovery, shared managed-device lifecycle contracts, typed run entry points, and baseline liveness monitoring.

**Requirements:** PLAT-01, PLAT-02, PLAT-03, RUN-01, RUN-02, RUN-03, SAFE-01

**UI hint:** no

**Success criteria:**
1. The orchestrator starts on `PC1` and exposes a stable control-plane entry point for clients and device services.
2. Device services can register or be discovered and return typed `health` and `capabilities` responses.
3. A submitted `RunRequest` is validated into a typed `RunPlan` before device coordination begins.
4. The orchestrator advances and publishes an explicit run state machine during a control-flow test.
5. Service heartbeat or timeout failures are detected and surfaced as typed orchestration errors.

### Phase 2: Fake Execution Slice

**Goal:** Validate the platform end to end with fake services, fake shot production, reusable contract tests, and a minimal observer client.

**Requirements:** PLAT-04, RUN-04, TEST-01, TEST-02, UI-01

**UI hint:** yes

**Success criteria:**
1. A fake device host can participate in orchestration using the shared lifecycle contract.
2. A fake `OPX/camera` path produces a `ShotResult` that the orchestrator consumes into a `RunSummary`.
3. The observer client can view service health, run-state changes, and run results without entering the execution path.
4. Shared lifecycle contract tests pass against the fake device implementations.
5. The fake environment supports at least one successful run and scripted failure scenarios in automated tests.

### Phase 3: Snapshot And Recovery Policy

**Goal:** Make runs reproducible and failure handling explicit by freezing execution inputs and enforcing retry/resume only at shot boundaries.

**Requirements:** SAFE-02, CFG-01

**UI hint:** no

**Success criteria:**
1. A run starts from a typed snapshot of hardware registry, calibrations, session parameters, and per-run overrides.
2. The active run does not depend on mutable live session state after planning is complete.
3. Shot-boundary retry policy is explicit, testable, and enforced by the orchestrator.
4. Mid-shot failure of a required device marks the shot failed rather than attempting unsafe in-place resume.

### Phase 4: Modeled Device Foundation

**Goal:** Add first-class modeled-device support so OPX-driven analog elements carry lab semantics and calibration instead of leaking into experiment code.

**Requirements:** MODEL-01

**UI hint:** no

**Success criteria:**
1. The run model can include modeled devices that are not independent network services.
2. A modeled device can translate physical intent into controller-facing values using calibration-aware logic.
3. Safe operating ranges and validation rules are enforced before execution.
4. At least one representative OPX-driven element, such as an `AOM`, is expressed through the modeled-device abstraction.

### Phase 5: First Local Hardware Adapter

**Goal:** Prove that the platform contract survives contact with one real hardware integration attached to `PC1`.

**Requirements:** HW-01

**UI hint:** no

**Success criteria:**
1. One real `PC1` device integrates through the same lifecycle contract used by fake services.
2. The orchestrator can discover, configure, and observe the real device without bypassing the platform contract.
3. Smoke tests cover readiness, orchestration, and failure reporting for that device.
4. The real adapter preserves fake-first and contract-test discipline instead of introducing one-off orchestration logic.

### Phase 6: First Remote Hardware Adapter

**Goal:** Prove that the same contract works across the lab network with at least one remote device host on `PC2` or `PC3`.

**Requirements:** HW-02

**UI hint:** no

**Success criteria:**
1. A remote device service hosted on `PC2` or `PC3` can be discovered and orchestrated from `PC1`.
2. Networked orchestration uses the same typed control-plane contract as local services.
3. Smoke tests cover service availability, orchestration, and failure reporting across the network boundary.
4. The remote integration does not require redesigning the orchestrator or splitting the control model by host.

## Notes

- This roadmap intentionally proves the contract before broad hardware coverage.
- Rich operator UX, remote office submission, and broad device-family onboarding remain out of scope for the first milestone.
- Phase 2 is the first point where a UI/client is useful; it remains observational rather than operational.

---
*Last updated: 2026-04-08 after roadmap creation*
