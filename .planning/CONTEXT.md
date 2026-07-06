# CONTEXT — Glossary

Canonical domain language for the neutral-atom tweezer control system. Glossary only — no implementation detail. See `.planning/architecture/` for architecture.

## Terms

### Rearrangement cycle
One iteration of the in-shot feedback loop that drives the array toward the defect-free target geometry. Four ordered stages:

1. **Image readout** — EMCCD reads out row-by-row.
2. **Occupation matrix** — binary (0/1) per-site atom-occupancy grid derived from the image.
3. **Move computation** — sorting moves computed from occupation matrix vs target geometry.
4. **Move execution** — AOD physically sweeps atoms per the computed moves.

The cycle repeats (re-image → recompute → re-move), but a shot runs **nominally 2 rearrangement loops, with a hard maximum of 3** by design. Atom-lifetime headroom does not determine this policy. Only the **initial and final** image + occupation matrix are persisted per shot — no per-loop series.

**Deadline:** the ≤ 5 ms budget is scoped to **stage 3 (move computation) + stage 4 (move execution)**, measured from the moment the occupation matrix is ready. Image readout and occupation-matrix generation are kept in a **separate, deterministic** budget: occupation-matrix generation is pipelined inside row-by-row readout and incurs no extra wall-clock. The 5 ms is enforced as a fixed wait-slot (pseudo-real-time): all other operations wait this fixed window for compute to finish; if compute is unreasonable to fit, the budget is revisited rather than silently exceeded.

**Per-cycle wall-clock (real number):** ≈ 10 ms exposure + ≈ 7 ms readout (35 µs/row × 200 rows) + ≤ 5 ms compute+execute ≈ **22 ms/cycle**. This is tracked for shot-duration budgeting, not to derive an allowed cycle count.

**Partial-move policy:** if compute produces a valid batch before the deadline with fewer moves than ideal, the cycle plays that **best-effort partial** move-set; atoms not yet sorted are retried on the next cycle. If the batch is missing, late, malformed, or fails header validation, the PPU enters safe state and the shot is marked unsafe. Partial movement is a valid-on-time degradation, not a deadline-miss recovery path.

### Atom trap lifetime
Practical in-trap atom lifetime ≈ 2 s (vacuum/heating limited). It provides margin for the planned rearrangement policy, but does not define the number of rearrangement cycles attempted in a shot.

### Defect-free target geometry
The desired final arrangement of occupied tweezer sites that a shot's rearrangement loop converges toward.

### Orchestrator
The run-lifecycle **authority**. Owns the run state machine, lifecycle coordination over devices, active execution, and the calibration-DAG runner. **Lives on the Tower (`PC1`).** A run is *owned* and *executed* by the Tower; nothing else can advance a run's state. A Tower crash kills the in-flight shot (recovery is shot-boundary only) but not durable history.

### Broker
The Tower-resident real-time executor inside the orchestrator's host. Owns the OPX client (`QuantumMachinesManager`), BitFlow capture, the GPU rearrangement pipeline, QUA input-stream pushes, and the local raw spool. Holds **no durable authority of its own** — it is the latency-critical execution arm of the Orchestrator. One Broker process per run.

### Pending job
A submitted request that has passed EliteDesk admission and is waiting for Tower execution. It records the time it was accepted for the queue. It is not yet an executing run.

### Accepted job
A pending job that has passed admission validation. It pins the descriptor and calibration snapshot that were selected at submission time. Later changes to active descriptor or active snapshot pointers do not silently change an accepted job.

### Run
An accepted job after the Tower has taken execution authority for it. A run has Tower-owned lifecycle state and may produce one or more shots.

### Admission Validator / Submitter (EliteDesk role)
The EliteDesk owns the **pending job queue** and performs **admission validation** before adding a job to that queue: request shape, RBAC, template allow-list, active descriptor resolution, active snapshot resolution, and static semantic checks that do not require live hardware authority. Accepted jobs pin the active descriptor and snapshot at submission time. Explicit descriptor IDs are reserved for replay/debug/admin flows. The EliteDesk can reject bad jobs and order accepted jobs, but cannot make a job safe to run and cannot advance run state. Distinct from **compile-validation** (the Tower L4 `submitted → validated` step that re-validates the pinned descriptor + snapshot against current authority-side constraints and attaches the [[validation-token]]) — that stays authority-side. In the lab deployment, the EliteDesk also **hosts the durable store** (metadata DB, calibration registry, off-host raw replica), so history survives a Tower crash.

### Compile-validation
The Tower-side validation step that happens after a job is dequeued for execution and before the broker can run it. It re-validates the accepted job's pinned descriptor and calibration snapshot against current authority-side constraints, checks calibration freshness, compiles the execution bundle, and attaches a [[validation-token]].

### Submission time
The time an accepted job enters the EliteDesk pending job queue.

### Execution start time
The time the Tower begins executing a dequeued job.

### Idempotency key
A caller-provided token used to make retrying a mutating request safe. It identifies an exact request replay, not a reusable name for future work. Reusing the same key for a different request is rejected rather than silently returning an older job.

**Deployment note:** `v1-dev` may run all roles (Orchestrator, Broker, Admission Validator, Postgres, data lake) **co-located on the Tower** for bring-up and testing, but it does not provide the Tower-crash durability guarantee. `v1-lab` keeps run authority on the Tower and moves Admission Validator + Postgres + replica to the EliteDesk before routine scientific operation.

### v1-dev
The bring-up and testing deployment. Roles may be co-located on the Tower. It does not provide the Tower-crash durability guarantee. One first commissioning demo may run in this mode if its reduced durability is explicitly accepted; routine scientific operation waits for [[v1-lab]]. Its outputs are commissioning data, not durable scientific data: they may demonstrate platform function but must not support durable analysis or publication claims. For that commissioning demo, raw commissioning data may be lost if the Tower disk fails, but metadata/provenance must remain internally consistent: no orphan database rows and no committed state without verified raw.

### Commissioning data
Data produced before the [[v1-lab]] durability split. It may be used to validate that the platform and apparatus work, but not as durable scientific evidence for long-lived analysis or publication claims.

### v1-lab
The routine scientific-run deployment. Tower keeps execution authority; EliteDesk hosts admission, pending jobs, metadata, calibration registry, and replica duties.

### Pre-Phase-1 software readiness
A planning status meaning the software-side control-plane slice is ready for review and dry-run validation, but the lab has **not** passed the Phase 0A measurement and safety gates. It is not equivalent to PLAN-V2 Phase 1 completion. Phase 1 remains blocked until the hardware evidence for the rearrangement RT contract, latency budget, process discipline, safety-plane independence, and clock-drift baseline is recorded.

### Device descriptor
An immutable description of the controllable physical system: channels, geometry, timing, bounds, and safety-relevant limits. Accepted jobs pin one descriptor. Normal submissions use the active descriptor at submission time; explicit descriptor selection is reserved for replay/debug/admin flows.

### Active descriptor pointer
The mutable answer to "which immutable [[device-descriptor]] is currently active." Modeled as an append-only activation log. The active descriptor is the latest activation per lineage. Accepted jobs pin a descriptor by ID, so later activations do not silently change queued work.

### Calibration snapshot
An **immutable** published set of parameter versions. Never mutated after publication. An accepted job pins to exactly one calibration snapshot. Immutability is what makes historical shots reproducible — see [[active-snapshot-pointer]] for how "which snapshot is current" is tracked without violating immutability.

### Active snapshot pointer
The mutable answer to "which immutable [[calibration-snapshot]] is currently active." Modeled as an **append-only activation log**, not as a `valid_until` interval on the snapshot row — closing an interval would mutate an immutable row and lose concurrent-publication safety. The active row = the latest activation per *lineage*. Accepted jobs pin a snapshot by ID, so later activations do not silently change queued work.

### Validation token
A compile-time **attestation that descriptor validation + parameter bounds + rate-limit checks ran** against a run's pinned descriptor and calibration snapshot before the run reaches the broker. Signed by Layer 4 (HMAC key held only there), short expiry. It is **NOT** the safety mechanism — do not read "token present" as "safe." Distinct from the [[safety-plane]].

### Durable shot commit
The progression from Tower-local shot durability to full durable history. A shot can finish execution before it is fully committed. Canonical states: `raw_spooled` (Tower-local durable), `metadata_mirrored` (metadata copied to durable store), `replicated` (off-host raw replica acknowledged), and `committed` (metadata + replica complete).

### Safety plane
The **independent hardware** interlock system — interlocks, watchdogs, RF/AOD bounds, defined safe states. Operates correctly even when the orchestrator is dead. This, not the [[validation-token]], is what actually keeps the apparatus safe. The two share no failure domain by design.
