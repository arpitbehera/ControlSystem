# 11 — Risks, Bottlenecks, Mitigations

## Risk taxonomy

Risks fall into four bands by severity × likelihood. Each carries a *mitigation* (already in this plan), a *measurement* (how the team will know it has bitten), and an *escape* (what to do if mitigation fails).

## Latency / throughput bottlenecks

### B1 — `insert_input_stream` payload-scaling unknown
*Likelihood:* medium · *Severity:* high
- **Symptom:** Rearrangement-loop p99 exceeds budget.
- **Mitigation:** Phase 0A measurement (see §07 acceptance gates) freezes the budget before contracts are written.
- **Measurement:** in-QUA `get_timestamp()` quantiles across ≥ 10⁵ shots at multiple payload sizes.
- **Escape:** raise `N_MAX_MOVES` only if curve is flat; if curve scales linearly past 5 ms, change to multi-batch-per-shot or compressed encoding; ultimate escape is the LLRS-style framegrabber → FPGA path (out-of-scope for v1).

### B2 — Andor + BitFlow + GPU buffer ownership on Windows
*Likelihood:* medium · *Severity:* high
- **Symptom:** Frame drops, hung capture, GPU-buffer-not-registered errors, conflicts between Andor SDK and in-process BitFlow path.
- **Mitigation:** Phase 0A 30-minute no-drop acquisition test under realistic CPU/IO load; explicit SDK ownership document.
- **Measurement:** `Statistic_Failed_Buffer_Count` (or vendor equivalent) per camera; required: zero over 30 minutes.
- **Escape:** if in-process broker capture is infeasible, fall back to a *thin* in-process broker that calls a co-located driver service over shared-memory ring buffer — adds <100 µs but unblocks. Last resort: switch to a CameraLink card with a more permissive driver model.

### B3 — GIL contention in broker process
*Likelihood:* low · *Severity:* medium
- **Symptom:** p99.9 worse than p99 by orders of magnitude; periodic stalls correlated with garbage collection.
- **Mitigation:** broker is single Python interpreter, hot path uses `nogil` libraries where available (numpy, cupy, custom C extensions for hot path); no background threads in broker.
- **Measurement:** GC duration + count via `gc` stats per shot.
- **Escape:** rewrite hot encoder path in a small Rust/C++ extension exposing a `pyo3` / `pybind11` shim.

### B4 — Slow GigE camera bottlenecks the experiment cadence
*Likelihood:* low (OPX owns the clock) · *Severity:* medium
- **Symptom:** Shot cadence pinned to slowest device.
- **Mitigation:** OPX+ is the timing root (seam #7). Slow cameras are triggered, not free-running; they don't gate the QUA program. Phase 0A spike #4 explicitly verifies this.
- **Measurement:** dashboard tile for `shots/min` vs target; alert if cadence drops.
- **Escape:** drop the slow camera from the in-loop shot; pre-trigger and ack post-shot.

### B5 — SLM HDMI 16.7 ms floor
*Likelihood:* high (physics) · *Severity:* low
- **Symptom:** Any experiment that updates the hologram per shot cannot exceed ~60 Hz cadence.
- **Mitigation:** documented in §06; precompute holograms for scans and step through; experiments that don't update SLM aren't constrained.
- **Measurement:** SLM-update-needing templates flagged at compile.
- **Escape:** evaluate a non-HDMI SLM interface (DisplayPort, dedicated card) in v2 if this constrains target experiments.

## Reliability / failure-domain risks

### B6 — Single fast box (A8) — Tower is broker + framegrabber + GPU + data lake
*Likelihood:* certain · *Severity:* high
- **Symptom:** Tower failure halts all experiments.
- **Mitigation:** process discipline (broker isolation); calibration registry + scheduler on EliteDesk; off-host raw-data replication; durable shot-commit protocol; quarterly fire-drill restore test.
- **Measurement:** RTO drills quarterly; record elapsed times.
- **Escape:** stocked spare Tower-class workstation with pre-installed image; documented one-day swap procedure.

### B7 — Postgres / EliteDesk failure
*Likelihood:* low · *Severity:* medium
- **Symptom:** New runs blocked; broker buffers locally.
- **Mitigation:** WAL streaming + nightly `pg_dump` to off-host; broker durable spool keeps shot commits available; idempotent replay on recovery.
- **Measurement:** monthly restore-from-backup drill; record RPO.
- **Escape:** spare EliteDesk-class machine with imaged OS + DB role; restore from WAL.

### B8 — Off-host replica lag
*Likelihood:* medium · *Severity:* medium
- **Symptom:** raw_state stuck at `pending`; gap between local lake and replica.
- **Mitigation:** dashboard tile shows replica lag; alert thresholds in §05.
- **Measurement:** lag tile updated each minute; alert at ≥ 1 h sustained.
- **Escape:** rotate the USB-pair replicas more frequently; or upgrade to NAS-backed replica.

### B9 — Lab switch / router failure
*Likelihood:* low · *Severity:* medium
- **Symptom:** All inter-host comms stop; broker ↔ OPX still works if Cisco is up (OPX is on Cisco fabric only).
- **Mitigation:** switch/router configs committed to git; spare 3560G; cable spares; restore runbook (§3.12 in research design doc).
- **Measurement:** quarterly restore drill.
- **Escape:** documented spare SKU + lead time.

### B10 — QM router failure
*Likelihood:* low · *Severity:* high
- **Symptom:** OPX cluster unreachable.
- **Mitigation:** QM router replacement procedure documented; vendor support contract; do not bypass without QM confirmation.
- **Measurement:** lab is offline; reported immediately.
- **Escape:** vendor swap; experiments halt until restored.

## Schema / contract risks

### B11 — `calibration_id` ambiguity (critique F-04, addressed)
*Mitigation:* the schema in §05 is the post-critique form: `calibration_snapshots` is the immutable unit a shot points to; per-node `calibration_executions` produces candidates; `parameter_versions` are append-only.
*Status:* designed in; deliverable in Phase 2.

### B12 — Lost provenance link (critique F-14, addressed)
*Mitigation:* `execution_bundles` row captures compiled QUA + config + lockfile + firmware + driver versions + dirty-worktree flag.
*Status:* designed in; deliverable in Phase 3.

### B13 — Hidden global state in instrument drivers (A2)
*Mitigation:* `Disarm` is idempotent and forces re-`Configure` before the next `Arm`; no driver-cached "last-set" values.
*Status:* designed in; deliverable in Phase 1 contract tests.

### B14 — Schemas defined by example (A14)
*Mitigation:* proto3 schema is authoritative; HDF5 attribute names + DB column names locked at v1; renaming forbidden (additive only).
*Status:* designed in; deliverable in Phase 1.

## Vendor / supply-chain risks

### B15 — QUAlibrate source moved private
*Mitigation:* build to the *interface* (DagNode + snapshot model in §08), not to QUAlibrate the library. The DAG-shape is the durable contract.
*Status:* designed in; the plan deliberately reimplements DAG runner in-house.

### B16 — QOP API breaks (QOP 2.x → 3.x; OPX+ → OPX1000)
*Mitigation:* the `RtJobSubmission` / `RearrangementBatchV1` contract above L1 is QOP-major-version-stable; the QUA template below it is rebuildable.
*Status:* designed in; the compiler is the layer that absorbs the next QOP bump.

### B17 — Vendor-lock on framegrabber / camera SDK
*Mitigation:* BitFlow + Andor drivers are wrapped behind the lifecycle contract; replacing either family means writing one device service + contract tests pass.
*Status:* designed in; each driver is one device service in `src/device_servers/`.

## People / process risks

### B18 — Conway's-Law fragility (A20)
*Mitigation:* layered seams with named owners; pair-coverage rule — each layer must have at least two operators who can debug it; contract tests embed knowledge in code.
*Measurement:* annual review of the bus-factor per layer.
*Escape:* documented runbooks for each layer; written onboarding pack.

### B19 — Bus-factor on the broker process
*Likelihood:* high (it's the most specialized component)
*Mitigation:* runbook + fault-injection tests + simulator (fake OPX + fake framegrabber); two senior operators trained on broker internals before Phase 3 ends.
*Measurement:* table-top exercise: "broker crashes mid-run", two operators independently recover.

### B20 — "One more spreadsheet" (A17)
*Mitigation:* calibration registry is queryable from the dashboard; no spreadsheet exists; the dashboard *is* the answer to "which calibration is current".
*Measurement:* spot-check: are operators using spreadsheets? If yes, audit the missing dashboard feature.

### B21 — Premature web UI (A19)
*Mitigation:* operator UI is CLI + lab-terminal dashboard; off-lab UI is read-only. No web-based control path in v1.
*Status:* designed in.

## Scientific risk

### B22 — Calibration drift faster than DAG re-runs
*Likelihood:* high in early days · *Severity:* medium
- **Symptom:** experiments fail fitness even after fresh calibration.
- **Mitigation:** `max_age_s` per node is tunable; scheduled drift-prone nodes re-run on cron-shape rules; dashboard surfaces age of every active parameter.
- **Measurement:** parameter-drift telemetry vs node `max_age_s`.
- **Escape:** tighten `max_age_s`; add additional calibration nodes; identify root drift cause in hardware.

### B23 — Classifier accuracy on real frames vs synthetic
*Likelihood:* medium · *Severity:* medium
- **Symptom:** assignment quality drops on real data despite Phase 0A passing.
- **Mitigation:** classifier model versioned in `execution_bundles.classifier_model_hash`; A/B comparison framework on historical shots.
- **Measurement:** post-shot reanalysis on archived raw frames vs in-shot classification — disagreement rate tracked.
- **Escape:** retrain classifier on lab-specific data; expand training set; ultimate escape is a hand-tuned matched filter.

## Single matrix view

| ID | Class | Severity | Mitigation in plan? | Measurement plan? |
|---|---|---|---|---|
| B1 | Latency | high | Yes (§07) | Yes (Phase 0A) |
| B2 | Latency | high | Yes (§07) | Yes (Phase 0A) |
| B3 | Latency | medium | Yes (§07) | Yes |
| B4 | Latency | medium | Yes (§06) | Yes |
| B5 | Latency | low | Yes (§06) | Yes |
| B6 | Reliability | high | Yes (§02, §05) | Yes (quarterly) |
| B7 | Reliability | medium | Yes (§05) | Yes (monthly) |
| B8 | Reliability | medium | Yes (§05) | Yes (continuous) |
| B9 | Reliability | medium | Yes | Yes (quarterly) |
| B10 | Reliability | high | Yes | (incident-driven) |
| B11 | Contract | high | Yes (§05, §08) | Phase 2 deliverable |
| B12 | Contract | high | Yes (§08) | Phase 3 deliverable |
| B13 | Contract | medium | Yes (§04) | Phase 1 tests |
| B14 | Contract | medium | Yes (§04) | Phase 1 |
| B15 | Vendor | medium | Yes (§08) | n/a |
| B16 | Vendor | medium | Yes (§04, §07) | n/a |
| B17 | Vendor | medium | Yes (§04) | n/a |
| B18 | People | medium | Yes | Annual |
| B19 | People | medium | Yes (Phase 3 exit gate) | Table-top exercises |
| B20 | People | low | Yes (§04) | Spot-check |
| B21 | UI | low | Yes (§10) | n/a |
| B22 | Science | medium | Yes (§08) | Continuous |
| B23 | Science | medium | Yes (§08) | Continuous |
