# 12 — Phased Implementation

This plan **extends** the six phases in `.planning/ROADMAP.md` with one critical addition required by critique F-08: a **Phase 0A measurement spike** before any long-lived contract is frozen.

| Phase | Goal | Duration (rough) | Exit gate |
|---|---|---|---|
| **0A** | Hardware spike: prove the rearrangement-loop assumptions on the actual gear | 4–8 weeks | Latency budget + GPU-buffer ownership demonstrated; safety plane independent-trip test passed |
| **1** | Control-Plane Skeleton (was `ROADMAP.md` Phase 1) | 2–3 months | Orchestrator + service discovery + lifecycle contract + heartbeats functional |
| **2** | Fake Execution Slice (was Phase 2) | 2 months | One end-to-end fake `OPX/camera` run → `ShotResult` → `RunSummary`; contract tests pass against all fakes; observer UI reads state |
| **3** | Snapshot & Recovery Policy (was Phase 3) | 2 months | Immutable `calibration_snapshot` model live; durable shot-commit protocol enforced; off-host replica ack-loop closed |
| **4** | Modeled Device Foundation (was Phase 4) | 2 months | At least one OPX-driven element (e.g. AOM) expressed as a modeled device; bounds enforced at compile |
| **5** | First Local Hardware Adapter (was Phase 5) | 2 months | One real `PC1` device (Andor or AOM) runs through the platform contract; rearrangement loop hardened on real hardware |
| **6** | First Remote Hardware Adapter (was Phase 6) | 2 months | One real `PC2`/`PC3` device runs through the same contract; cross-host orchestration validated |

Total: ~12–18 months for v1; v2 features (REMOTE-01, UI-02, DATA-01, DEV-01) follow.

## Phase 0A — Hardware spike

**Why this phase exists:** the rearrangement-loop contract (`RearrangementBatchV1` shape, broker placement, GPU buffer ownership, safety-plane behavior, NTP guarantees) all depend on numbers that QM does not publish and that have not been measured on this lab's exact hardware. Per critique F-08, freezing the contracts before measuring would lock in possibly-wrong assumptions for the next 5+ years.

**Workstreams (parallel):**

1. **W0A-1: `push_to_input_stream` latency measurement.** First derive `N_MAX_MOVES` from descriptor geometry + assignment/collision policy for current ~100-atom operation and projected 1000-atom operation; treat the current-operation bound as the Phase 0A target unless the 1000-atom target is explicitly in scope. Then write minimal QUA test programs that loop `advance_input_stream → get_timestamp → output_stream`, one declared input-stream vector size per test. Python side feeds homogeneous `int` vectors of `{4, 64, 256, 2048, BATCH_WORDS}` words, corresponding to `{16 B, 256 B, 1 KB, 8 KB, target}` byte-equivalents for 32-bit words. Collect ≥ 10⁵ samples per size. Report p50/p95/p99/p99.9/max. Report this as the `t_insert` span (§07 canonical spans) so it composes with W0A-2's `t_compute` and the measured `t_readout`/`t_execute` into the §00 ≤ 5 ms compute+execute budget.
2. **W0A-2: GPUDirect for Video bring-up + CPU baseline.** Confirm BitFlow Axion 1xB + RTX 4000 Ada GPUDirect path works in a single in-process Python broker. Measure each canonical span (§07): DMA-to-VRAM, `t_compute` (classifier + assignment), encoder, host pickup. **Also measure a CPU-only `t_compute` baseline** (BitFlow → CPU RAM, SIMD threshold + greedy/auction assignment) at current array size and projected 1000-atom ROI. GPU stays the committed path (ADR-0002 / §07); the CPU baseline quantifies the GPU's margin and provides a fallback datapoint. Document Andor SDK ↔ BitFlow handoff (critique F-09).
3. **W0A-3: Process-discipline study.** Compare broker priorities (`NORMAL`, `HIGH`, `REALTIME`) and CPU pinning configurations against p99/p99.9 latency and dropped frames. Pick the lowest-priority config that meets the latency target without instability.
4. **W0A-4: Safety-plane independence test.** Wire a temporary hardware E-stop into shutter + RF amp enable lines. Verify that pressing it brings shutters closed and RF off within sub-ms, with no software in the path. Confirm that killing the broker also brings PPU into safe state within one shot via the QUA watchdog.
5. **W0A-5: NTP drift baseline.** Run a 24 h cold-start drift measurement across all four lab hosts.

**Exit gates (must all pass to enter Phase 1):**

- W0A-1: `N_MAX_MOVES` is derived from descriptor geometry + assignment/collision policy rather than chosen as a magic constant; OPX/QOP compiler and runtime accept the resulting target `BATCH_WORDS` declaration (`6157` words / ~24.6 KB if provisional `N_MAX_MOVES=1024` survives derivation), and `t_insert` (p99) is small enough that the **composed** budget holds — `t_compute + t_insert + t_execute` p99 ≤ 5 ms from occupation-ready (§00, §07 spans), with `t_execute` (AOD chirp) and `t_compute` from W0A-2 folded in. A bare `push_to_input_stream` p99 ≤ 5 ms is **not** sufficient on its own (insert is one span of the budget, not the whole). If target `BATCH_WORDS` is rejected or the composed budget fails, a concrete escape (shrink `N_MAX_MOVES` / multi-batch / RLE / tighter chirp) is documented before ADR-0002 is accepted.
- W0A-2: 30-minute no-drop acquisition under realistic load; documented SDK ownership model.
- W0A-3: chosen priority/affinity setting produces measurable p99.9 improvement over default.
- W0A-4: independent safe-state reached in every fault-injection scenario in §09.
- W0A-5: sustained NTP offset ≤ 10 ms across all hosts.

**Deliverables** (ADR numbers match the §13 seed list):

- `.planning/adr/0001-execution-authority-and-broker-placement.md` — ratifies (or revisits) ADR-0001 (Tower = execution authority + broker; EliteDesk = validate + store) against the measured GPUDirect path.
- `.planning/adr/0002-rearrangement-batch-v1.md` — locks ADR-0002 wire-message shape based on measurement.
- `.planning/adr/0010-broker-process-discipline.md` — locks ADR-0010 priority + affinity from W0A-3.
- `.planning/adr/0016-gpu-mutex-locality.md` — confirms ADR-0016 (Tower-local mutex) under the measured run+compute contention.
- `network/MINIMAL_OPX.md` — minimal cold-bring-up procedure (per research design doc §3.12.6).
- `tests/hardware/` — every Phase 0A test reified as a re-runnable script.

## Phase 1 — Control-Plane Skeleton

Maps to `REQUIREMENTS.md`: PLAT-01, PLAT-02, PLAT-03, RUN-01, RUN-02, RUN-03, SAFE-01.

**Workstreams:**

1. **W1-1: Proto3 contracts.** Define `lifecycle.proto`, `run_model.proto`, `safety.proto`, `scheduler.proto`. Wire schema review with the team. No code generation until reviewed.
2. **W1-2: Orchestrator skeleton.** Long-running Python process on the **Tower** (run-execution authority, ADR-0001; `v1-dev` may co-locate roles on the Tower). Implements gRPC server for `DequeueForExecution`, active-run `Cancel`, `Status`, `ListRuns`. State FSM held Tower-local-authoritative and mirrored to Postgres. Heartbeat consumer. The EliteDesk Admission Validator/Submitter owns `Enqueue`, pending-job `Cancel`, and the pending job queue.
3. **W1-3: Postgres schema v1.** Tables: `device_descriptors`, `descriptor_activations`, `accepted_jobs`, `runs`, `shots`, `raw_manifests`. Alembic migrations. (Descriptors are immutable; currency is the `descriptor_activations` append-only pointer — ADR-0003, no `valid_until`.)
4. **W1-4: Lifecycle contract base.** `src/device_servers/_base/` provides a `LifecycleService` abstract class + FSM + heartbeat. Contract test suite in `tests/contract/`.
5. **W1-5: One fake device service.** `device_servers/fake_camera/` implements the contract; passes contract tests.
6. **W1-6: Broker shell.** Tower process that connects to OPX via QM SDK and exposes a `Broker` gRPC service to the scheduler. No rearrangement logic yet — just `Configure / Arm / Start / Stop / Disarm`.
7. **W1-7: Operator CLI.** Minimal `lab` CLI with `submit-run`, `status`, `cancel-job`, `cancel-run`, `list-runs`.

**Exit gate:**
1. Orchestrator starts on the Tower (`v1-dev` may be co-located); exposes gRPC. EliteDesk admission gateway enqueues an `AcceptedJob`.
2. Fake camera service registers, returns typed `Capabilities` + `Health`.
3. `Enqueue(RunRequest)` persists an `AcceptedJob`; Tower dequeue compile-validates it into a `RunPlan`.
4. State machine transitions visible via `Status` stream.
5. Pending-job cancel records request/effective timestamps on `accepted_jobs`; active-run cancel records request/effective timestamps on `runs`.
6. Heartbeat miss surfaces a typed error within 5 s.

## Phase 2 — Fake Execution Slice

Maps to `REQUIREMENTS.md`: PLAT-04, RUN-04, TEST-01, TEST-02, UI-01.

**Workstreams:**

1. **W2-1: Fake OPX.** A test double that exposes the same gRPC interface as the real broker; produces synthetic `RtJobResult`s. Used by all integration tests.
2. **W2-2: Layer-4 compiler (v0).** Takes `(Template, parameters, fake DeviceDescriptor)` → `CompiledRun`. Rejects on bounds violations.
3. **W2-3: ShotResult / RunSummary path.** Broker → scheduler → DB → operator CLI displays summary.
4. **W2-4: All-fakes contract test suite.** Every fake device service passes contract tests in CI.
5. **W2-5: Read-only observer dashboard (v0).** FastAPI + static HTML. Tiles for service health, run state, last `RunSummary`. No mutating verbs.

**Exit gate:**
1. End-to-end fake run produces a `RunSummary` row in Postgres.
2. Observer UI shows current state of all services + the running run.
3. Contract tests pass against every fake device service in CI.
4. One scripted failure scenario (heartbeat miss, fake-OPX `rt_error`, bounds-violating request) produces the documented failure outcome.

## Phase 3 — Snapshot & Recovery Policy

Maps to `REQUIREMENTS.md`: SAFE-02, CFG-01.

**Workstreams:**

1. **W3-1: Calibration snapshot model.** Tables: `dag_nodes`, `calibration_executions`, `parameter_versions`, `calibration_snapshots`, `snapshot_activations`, `execution_bundles`. Per §05 and §08. (Snapshots immutable; currency is the `snapshot_activations` append-only pointer — no parent-chain "head", no `valid_until`.)
2. **W3-2: Snapshot publication transaction.** API + permissions per §08.
3. **W3-3: Execution bundle generator.** Compiler attaches a bundle to every run.
4. **W3-4: Durable shot-commit protocol.** Broker local spool, fsync semantics, gRPC idempotency, off-host replica ack loop. Per §05.
5. **W3-5: Recovery tests.** Power-loss simulation, kill broker mid-shot, kill scheduler mid-run, disk-fill simulation. Recovery within documented RTO.
6. **W3-6: Off-host replica.** Configure the chosen target (institutional NAS / USB rotation / standby host).

**Exit gate:**
1. A run pinned to snapshot S survives concurrent publication of snapshot S+1.
2. Every shot row has a non-null `(snapshot_id, descriptor_id, bundle_id)`.
3. Killing the broker mid-shot results in `shots.state IN ('raw_spooled', 'commit_pending', 'committed', 'unsafe')` — never an orphaned DB row or orphaned raw file.
4. Restore from off-host replica into a fresh EliteDesk produces an identical Postgres state, with bounded data loss matching RPO.

## Phase 4 — Modeled Device Foundation

Maps to `REQUIREMENTS.md`: MODEL-01.

**Workstreams:**

1. **W4-1: Modeled-device model.** `src/descriptor/modeled_device.py` defines the shape (identity, controller, bounds, translation rules).
2. **W4-2: One representative modeled device.** AOM_Y (y-axis repump AOM) expressed as a modeled device with calibration-aware power → voltage translation.
3. **W4-3: Compiler integration.** Layer 4 resolves modeled-device actions into OPX `play()` calls using the snapshot's parameter versions.
4. **W4-4: Bounds enforcement.** Compiler rejects requests outside descriptor bounds.

**Exit gate:**
1. One run template that uses AOM_Y compiles end-to-end via the modeled-device path.
2. A request asking for power outside AOM_Y's bounds is rejected at submit.
3. Changing the AOM_Y calibration via a snapshot change produces compiled voltages that differ in the expected direction.

## Phase 5 — First Local Hardware Adapter

Maps to `REQUIREMENTS.md`: HW-01.

**Workstreams:**

1. **W5-1: Choice of first real device.** Recommended: Andor iXon (already on Tower, exercised by the broker). Alternative: a power supply for the MOT coils.
2. **W5-2: Real-device adapter.** `src/device_servers/camera_andor/` implements the lifecycle contract against the Andor SDK.
3. **W5-3: Hardware smoke tests.** `tests/hardware/test_andor.py` (manual run); confirms triggered acquisition, trigger response time, frame integrity.
4. **W5-4: Rearrangement loop on real hardware.** Phase 0A's measurement spike code becomes a regression test on the actual loop. Latency budget enforced as a CI gate (against a recorded baseline).
5. **W5-5: First commissioning demo.** A run that loads atoms, images them, rearranges them, and produces a defect-free target geometry — running through the full PLAN-V2 stack while still Tower-local. This is explicitly a `v1-dev` commissioning run with accepted Tower-disk durability risk, not routine scientific operation. Its outputs are commissioning data, not durable scientific data, and must not support durable analysis or publication claims.

**Exit gate:**
1. Andor service registers, advertises typed `CameraCapabilities`, passes contract tests.
2. The Phase 0A latency baseline holds on the integrated platform.
3. One full commissioning demo run from operator CLI submit → atoms rearranged → `RunSummary` persisted, with all provenance IDs populated and `durability_tier = 'v1-dev_non_durable'` on runs/shots and visible in the dashboard/export path. Raw commissioning data loss is acceptable under Tower-disk failure in this phase; inconsistent metadata is not.

## Phase 6 — First Remote Hardware Adapter

Maps to `REQUIREMENTS.md`: HW-02.

**Workstreams:**

1. **W6-1: Choice of first remote device.** Recommended: SLM on Mini (`PC2`) — exercises the cross-host orchestration path most fully.
2. **W6-2: Remote-device adapter.** `src/device_servers/slm/` runs on Mini; exposes the same lifecycle contract over gRPC.
3. **W6-3: Cross-host smoke tests.** Validate that the Tower orchestrator drives the SLM service on Mini through the same code path as a local fake. (Phase 6 is also where the EliteDesk Validator + Postgres are first physically split off the Tower, per ADR-0001 — cross-host orchestration and the store-distribution step are validated together. This transition upgrades from commissioning-only `v1-dev` to routine `v1-lab` operation.)
4. **W6-4: SLM-integrated demo.** A run that uses an SLM-defined initial geometry alongside the rearrangement loop.

**Exit gate:**
1. SLM service on Mini is discovered and orchestrated from the Tower orchestrator; contract tests pass against the real device.
2. A run that uses both Andor (Tower) and SLM (Mini) executes end-to-end with full provenance.
3. The platform contract did not change to accommodate the remote device.

## Subsystem boundaries → workstream ownership

For each phase, every workstream lists primary + backup owner roles. Pair-coverage is required (anti-pattern A20 mitigation):

| Subsystem | Primary owner role | Backup role |
|---|---|---|
| Broker + RT seam | broker engineer | scheduler engineer |
| Scheduler + state FSM | scheduler engineer | platform engineer |
| Postgres + schema | data engineer | scheduler engineer |
| Compiler + descriptor | platform engineer | scheduler engineer |
| Calibration DAG | calibration engineer | platform engineer |
| Device services | device engineer (per family) | platform engineer |
| Network + ops | ops / lab manager | broker engineer |
| Safety plane | hardware engineer | broker engineer |
| Dashboards + CLI | platform engineer | device engineer |

If two operators with the named roles cannot independently debug a subsystem, the phase exit gate fails.

## Stop / reassess discipline

Every milestone is a *real* stop. The next phase does not begin until:

1. The prior phase's exit gate is met in writing in `.planning/MILESTONES.md`.
2. Risks raised during the phase are added to `11-risks-bottlenecks-mitigations.md` with measurement plans.
3. ADRs for any decision made during the phase are committed to `.planning/adr/`.

## Cross-phase activities

- **ADR cadence:** every load-bearing decision becomes an ADR in `.planning/adr/NNNN-name.md`. See §13.
- **Quarterly drills:** restore-from-backup, switch-config restore, broker process replacement, off-host replica failover.
- **Annual review:** bus-factor per layer; renew pair-coverage assignments.
- **Per-release:** schema-migration test, hardware-smoke re-run, dashboard regression.
