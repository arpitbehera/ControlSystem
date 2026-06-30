# 13 — Architectural Decision Records

Each ADR captures one load-bearing decision with its alternatives, evidence, and reversal condition. ADRs are the durable record per critique F-19. Final per-decision ADR files live under `docs/adr/NNNN-name.md` once Phase 0A starts; this document is the seed list.

ADR template:

```markdown
# ADR-NNNN: <Title>
## Status
<Proposed | Accepted | Superseded by ADR-MMMM>

## Context
<What problem; what constraints>

## Decision
<What we are doing>

## Alternatives considered
<Each alternative + why rejected>

## Evidence / measurement
<What confirmed the decision>

## Consequences
<Forces, costs, follow-ups>

## Reversal condition
<What new evidence would invalidate this decision>
```

## Seed ADRs

### ADR-0001 — Orchestrator host is EliteDesk; broker host is Tower
**Status:** Proposed
**Context:** `PROJECT.md` fixes `PC1` (= HP Z2 Tower) as orchestrator host. Research design doc places broker on Tower for latency. These can coexist if "orchestrator" is split into a *control-plane* part (scheduler / compiler / DAG runner / DB) and a *latency-critical* part (broker / framegrabber / GPU pipeline / spool).
**Decision:** Scheduler, compiler, DAG runner, Postgres on EliteDesk. Broker process, framegrabber driver, GPU pipeline, data-lake writer, durable spool on Tower. The Tower's role in run ownership is delegated *broker only*; "run lifecycle ownership" in the `PROJECT.md` sense lives at the scheduler on EliteDesk.
**Alternatives:**
- Pure-Tower orchestrator (`PROJECT.md` literal reading): risks A8.
- Pure-EliteDesk orchestrator including broker: adds a cross-host hop on the rearrangement loop.
**Evidence:** GPUDirect for Video requires PCIe co-location (BitFlow + RTX 4000 Ada). Tower has the framegrabber. Phase 0A W0A-2 measures the actual GPUDirect path.
**Consequences:** Two hosts must agree on run state via Postgres-backed FSM. Tower failure halts in-flight shot but does not corrupt history.
**Reversal condition:** Phase 0A reveals an unsolvable bottleneck on Tower → consider relocating the GPU pipeline and broker to a new host that retains PCIe co-location.

### ADR-0002 — Rearrangement wire message: `RearrangementBatchV1`
**Status:** Proposed
**Context:** Critique F-02 and F-07 identified that a flat float array + separate IO variable is not a correct atomic message.
**Decision:** Fixed-width versioned `RearrangementBatchV1` struct with `protocol_version`, `sequence_no`, `n_moves`, `deadline_ppu_ticks`, `snapshot_hash32`, and padded `moves[N_MAX_MOVES]`. PPU validates every field before playing.
**Alternatives:**
- Variable-length input stream: QM input streams are fixed-size by spec; not supported.
- Per-move push: Phase 0A latency curve will reveal whether this is viable; current expectation is overhead dominates.
**Evidence:** QM input-stream docs; QUA `declare_input_stream` API. Phase 0A W0A-1 will measure the chosen layout.
**Consequences:** N_MAX_MOVES is part of the contract; raising it requires a new ADR.
**Reversal condition:** Phase 0A shows that a flat float array's payload-scaling is so flat that variable-length is unnecessary. The header + safety validation still apply.

### ADR-0003 — Calibration model: immutable `calibration_snapshots`
**Status:** Proposed
**Context:** Critique F-04 — original "calibration_id" was ambiguous between a node execution, a parameter version, and a published set.
**Decision:** Separate tables: `calibration_executions` (candidates), `parameter_versions` (immutable typed values), `calibration_snapshots` (immutable published sets). Runs pin to one `snapshot_id`.
**Alternatives:**
- "Registry with valid_until": closing an interval is a mutation; loses concurrent-publication safety.
- Per-shot snapshot row: would multiply rows by O(snapshots × parameters); rejected for size.
**Evidence:** Critique F-04 reasoning; Google Optimus / Kelly 2018 pattern; QUAlibrate design (translated to in-house schema).
**Consequences:** All historical shots are queryable by ID; concurrent calibration publishes are safe; UI shows snapshot lineage.
**Reversal condition:** None foreseen; this is the post-critique design.

### ADR-0004 — Execution bundle includes compiled artifacts + environment
**Status:** Proposed
**Context:** Critique F-14 — `code_commit_sha` alone does not prove what was executed.
**Decision:** Per-run `execution_bundles` row holds compiled QUA + QM config + Python lockfile + firmware versions + driver versions + worktree-dirty flag. Every run references one bundle.
**Alternatives:**
- Reconstruct from git checkout + Python env: fragile across years; dependencies move.
- Just store `qm_config_hash`: insufficient; doesn't capture environment.
**Evidence:** IBM `BackendProperties + calibration_id` pattern; reproducible-builds literature.
**Consequences:** Postgres rows grow (bundles can be MB-scale per run); large-blob columns; mitigate with TOAST + per-bundle deduplication on hash.
**Reversal condition:** Bundle size becomes operationally infeasible → split into a content-addressable store outside Postgres.

### ADR-0005 — Durable shot-commit protocol
**Status:** Proposed
**Context:** Critique F-05 — raw can exist without metadata or vice versa.
**Decision:** Local fsync spool on broker → idempotent gRPC `ShotResult` → DB tx inserts row + manifest in one tx → async data-lake replication → off-host ack → `raw_state = 'lake'`. Per §05.
**Alternatives:**
- DB commit before fsync: race window where raw is gone but row is.
- Synchronous off-host write before DB commit: slow; couples shot rate to off-host latency.
**Evidence:** Two-phase commit literature; SQLite WAL pattern; Postgres durability guarantees.
**Consequences:** Spool can grow if off-host replica is delayed; bounded by Tower NVMe; alarming surfaces lag.
**Reversal condition:** None foreseen; design follows from durability requirement.

### ADR-0006 — NTP everywhere; no PTP on installed gear
**Status:** Proposed
**Context:** Cisco 3560G has no PTP; RB3011 cannot grandmaster. Adding PTP requires new switch + grandmaster.
**Decision:** RB3011 is stratum-2 NTP server; all hosts sync to it. OPX+ owns experimental timing internally. NTP timestamps are observational metadata only.
**Alternatives:**
- Software PTP via `PTPd` over best-effort Ethernet: unreliable; gives no real sub-µs guarantee.
- Hardware PTP upgrade: capex + lead time; out of v1 scope.
**Evidence:** Cisco product docs (3650+ for PTP); MikroTik switch-chip docs.
**Consequences:** No sub-µs cross-host coordination achievable; if a future experiment needs it, upgrade gear.
**Reversal condition:** New experiment design requires sub-µs cross-host sync → file an upgrade ADR.

### ADR-0007 — Postgres on EliteDesk; off-host replica chosen in Phase 0
**Status:** Proposed
**Context:** Critique F-05 — WAL shipping to Tower puts DB recovery copy in the same failure domain as the broker.
**Decision:** Postgres lives on EliteDesk NVMe. Off-host replica target is chosen during Phase 0 setup (institutional NAS preferred; USB rotation if no NAS).
**Alternatives:**
- WAL to Tower: same failure domain; rejected.
- Cloud DB: violates `PROJECT.md` non-goal.
**Evidence:** Failure-mode analysis in §02.
**Consequences:** Off-host target requires operational care.
**Reversal condition:** If institutional NAS becomes unavailable, switch to USB rotation; record the move in a follow-up ADR.

### ADR-0008 — VLAN 50 (`opx-rt`) is an L2-only trust enclave
**Status:** Proposed
**Context:** OPX needs vendor QM router; QM router is in 192.168.88.0/24; OPX traffic must not traverse RB3011.
**Decision:** VLAN 50 on Cisco fabric only. RB3011 has no SVI for VLAN 50. Tower is dual-homed: broker NIC on VLAN 50, control NIC on VLAN 10. Anti-routing policy on the Tower (no ICS, no bridge) prevents leakage.
**Alternatives:**
- Single flat VLAN: broadcast contention; harder to secure.
- L3 SVI on RB3011 with ACLs: extra hop on critical path; rejected.
**Evidence:** Research design doc §3.4.1; QM vendor topology.
**Consequences:** Cross-host status reads from VLAN 10 hosts go through a Tower broker proxy. (Critique F-10 fix.)
**Reversal condition:** If QM publishes a supported bypass model, revisit.

### ADR-0009 — gRPC over TCP for control plane; proto3 schema
**Status:** Proposed
**Context:** Need typed, multi-language, schema-evolving RPC over the lab subnet.
**Decision:** gRPC + proto3 + mTLS on VLAN 10.
**Alternatives:** REST/JSON (weaker typing), ZeroMQ (no schema), MQTT (pub/sub semantics).
**Evidence:** Wide adoption; mature Python + Rust + Go bindings.
**Consequences:** Schema lives in `proto/`; CI generates code; mTLS cert distribution is an ops task.
**Reversal condition:** None foreseen.

### ADR-0010 — Broker is a single Python interpreter; priority chosen via measurement
**Status:** Proposed
**Context:** Critique F-09 — `REALTIME_PRIORITY_CLASS` may starve drivers; default Python may underdeliver p99.9.
**Decision:** Default `HIGH_PRIORITY_CLASS`; pinned to a fixed CPU subset; benchmarked against `REALTIME` in Phase 0A; the best-measured config wins. CPU affinity per §07.
**Alternatives:**
- Always `REALTIME`: risks Windows scheduler starvation.
- Always default: predictable but possibly worse p99.9.
**Evidence:** Phase 0A W0A-3.
**Consequences:** The Phase 0A ADR follow-up may bump priority.
**Reversal condition:** Driver / SDK starvation observed under `REALTIME` → step down; or measured benefit found at lower priority.

### ADR-0011 — One process per device-class; lifecycle contract by proto3
**Status:** Proposed
**Context:** Need device-agnostic orchestration with strong contract enforcement.
**Decision:** Every managed device is one Windows service running a Python process with the eight lifecycle verbs over gRPC. Contract tests parametrize across every implementation.
**Alternatives:** Driver libraries imported into a single process: rejected per anti-pattern A7.
**Evidence:** labscript BLACS pattern; ARTIQ device controllers; convergent across the landscape.
**Consequences:** More processes to supervise; `nssm` handles supervision.
**Reversal condition:** None foreseen.

### ADR-0012 — Safety plane is independent of orchestrator
**Status:** Proposed
**Context:** Critique F-03.
**Decision:** Hardware E-stop + shutter + RF amp enable lines have no software in the path. PPU watchdog enforces deadlines on input streams. Broker death triggers PPU safe-state within one shot. Per §09.
**Alternatives:**
- Software-only watchdogs: insufficient; cannot survive broker death.
**Evidence:** Critique F-03; lab-safety best practice.
**Consequences:** Hardware E-stop wiring + RF amp enable lines must be specified in the lab's hardware-safety doc.
**Reversal condition:** None — safety design is foundational.

### ADR-0013 — Storage container choice deferred to Phase 5 benchmark
**Status:** Proposed
**Context:** Critique F-13.
**Decision:** v1 uses HDF5-per-shot behind a stable `raw_manifest` schema; Phase 5 benchmarks per-shot HDF5 vs chunked HDF5 vs Zarr at projected scale and selects the long-term container. Schema for IDs and metadata is frozen now; container is not.
**Alternatives:**
- Pre-commit to chunked HDF5: ignores measurement.
- Pre-commit to Zarr: same risk.
**Evidence:** Phase 5 W5-x benchmark.
**Consequences:** Some early-data migration may be needed once the long-term container is chosen.
**Reversal condition:** Benchmark may surprise; accept the result.

### ADR-0014 — Read-only off-lab dashboard; no web-based control in v1
**Status:** Proposed
**Context:** Anti-pattern A19 (premature web UI).
**Decision:** Off-lab UI is read-only. Lab-terminal CLI + dashboard is write-capable, role-gated. v2 may add a richer mutating dashboard (UI-02 in `REQUIREMENTS.md`) but only after the read-only path has stabilized.
**Alternatives:** Web UI for operators in v1: rejected — frequent UI churn destabilizes the control path.
**Evidence:** Anti-pattern A19; convergent practice across labscript / ARTIQ.
**Consequences:** Operator UX in v1 is austere; CLI-first.
**Reversal condition:** v2 explicitly addresses this in UI-02.

### ADR-0015 — In-house calibration DAG runner; not QUAlibrate library
**Status:** Proposed
**Context:** QUAlibrate source moved private (github.com/qua-platform/qualibrate).
**Decision:** Implement the DAG runner in-house using the Optimus shape (DAG of nodes updating parameter versions). Build to the *interface*, not to the library.
**Alternatives:**
- Adopt QUAlibrate as a hard dependency: vendor lock-in + closed source.
**Evidence:** Research design doc §1.3.
**Consequences:** Engineering cost upfront; long-run portability.
**Reversal condition:** QM open-sources QUAlibrate or offers stable supported API → re-evaluate.

## ADR governance

- Each ADR has a single primary author + at least one reviewer from a different role.
- Proposed → Accepted only after the gating phase / measurement is complete.
- Superseded ADRs are kept in `docs/adr/` for historical reference.
- A quarterly review walks the ADR list and flags any whose reversal conditions have started to apply.
