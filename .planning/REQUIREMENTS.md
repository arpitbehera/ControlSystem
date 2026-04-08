# Requirements: Neutral Atom Lab Control System

**Defined:** 2026-04-08
**Core Value:** Scientists can run reproducible, typed, recoverable experiments from one orchestrator without coupling hardware control, analysis, and UI into a fragile monolith.

## v1 Requirements

### Platform Topology

- [ ] **PLAT-01**: Orchestrator runs on `PC1` and coordinates device services hosted on lab PCs over Ethernet
- [ ] **PLAT-02**: Device services can register or be discovered and expose typed health and capability information
- [ ] **PLAT-03**: The control plane carries typed lifecycle commands, state events, and result messages between orchestrator and services
- [ ] **PLAT-04**: The platform keeps bulk payloads off the orchestrator by default and supports metadata or reference handoff instead

### Run Orchestration

- [ ] **RUN-01**: User can submit a `RunRequest` that validates into an immutable `RunPlan`
- [ ] **RUN-02**: Orchestrator exposes an explicit run state machine to clients during run execution
- [ ] **RUN-03**: Orchestrator coordinates required managed devices through the shared lifecycle contract
- [ ] **RUN-04**: Orchestrator consumes `ShotResult` objects and emits a `RunSummary` for successful or failed runs

### Safety And Recovery

- [ ] **SAFE-01**: Service heartbeats and timeouts detect failed or unhealthy dependencies during orchestration
- [ ] **SAFE-02**: Failed shots can be retried only at shot boundaries according to explicit run policy

### Testing

- [ ] **TEST-01**: Shared lifecycle contract is enforced by reusable contract tests against fake device implementations
- [ ] **TEST-02**: A fake lab environment can execute one successful demo run and scripted failure cases without real hardware

### Configuration And Modeling

- [ ] **CFG-01**: Run execution uses typed snapshots of hardware registry, calibrations, session parameters, and per-run overrides
- [ ] **MODEL-01**: OPX-driven analog lab elements can be represented as modeled devices with calibration and safe operating ranges

### Integration And Observation

- [ ] **HW-01**: At least one real device attached to `PC1` integrates through the platform contract
- [ ] **HW-02**: At least one real remote device attached to `PC2` or `PC3` integrates through the platform contract
- [ ] **UI-01**: A minimal client can observe service health, run state, and `ShotResult`/`RunSummary` updates without entering the execution path

## v2 Requirements

### Remote Access

- **REMOTE-01**: Authorized office clients can submit jobs to the lab orchestrator without running the orchestrator outside `PC1`

### Operator Experience

- **UI-02**: Operators can use a richer dashboard for manual controls, visualizations, alarms, and workflow management

### Data Management

- **DATA-01**: Raw bulk payloads can be archived, replayed, and traced without forcing those payloads through the control plane

### Coverage Expansion

- **DEV-01**: Additional device families can be added through stable adapters without changing the orchestrator contract

## Out of Scope

| Feature | Reason |
|---------|--------|
| Mid-shot resume after required-device failure | Scientifically unsafe and too complex for v1 |
| Routing raw image streams through the orchestrator | Increases latency and couples control and data paths |
| Full real-hardware coverage in the first roadmap | The platform contract must be validated before broad adapter work |
| Rich production dashboard workflows in the first milestone | A minimal observer client is sufficient to validate the architecture |
| Remote office submission in the first milestone | Lab-local orchestration must work first |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLAT-01 | Phase 1 | Pending |
| PLAT-02 | Phase 1 | Pending |
| PLAT-03 | Phase 1 | Pending |
| RUN-01 | Phase 1 | Pending |
| RUN-02 | Phase 1 | Pending |
| RUN-03 | Phase 1 | Pending |
| SAFE-01 | Phase 1 | Pending |
| PLAT-04 | Phase 2 | Pending |
| RUN-04 | Phase 2 | Pending |
| TEST-01 | Phase 2 | Pending |
| TEST-02 | Phase 2 | Pending |
| UI-01 | Phase 2 | Pending |
| SAFE-02 | Phase 3 | Pending |
| CFG-01 | Phase 3 | Pending |
| MODEL-01 | Phase 4 | Pending |
| HW-01 | Phase 5 | Pending |
| HW-02 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-08*
*Last updated: 2026-04-08 after initial definition*
