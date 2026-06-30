# CONTEXT — Glossary

Canonical domain language for the neutral-atom tweezer control system. Glossary only — no implementation detail. See `.planning/PLAN-V2/` for architecture.

## Terms

### Rearrangement cycle
One iteration of the in-shot feedback loop that drives the array toward the defect-free target geometry. Four ordered stages:

1. **Image readout** — EMCCD reads out row-by-row.
2. **Occupation matrix** — binary (0/1) per-site atom-occupancy grid derived from the image.
3. **Move computation** — sorting moves computed from occupation matrix vs target geometry.
4. **Move execution** — AOD physically sweeps atoms per the computed moves.

The cycle repeats (re-image → recompute → re-move), but a shot runs **at most 2 rearrangement loops** by design. (The ~90-cycle figure below is the *physical capacity* set by atom lifetime, not the per-shot usage.) Only the **initial and final** image + occupation matrix are persisted per shot — no per-loop series.

**Deadline:** the ≤ 5 ms budget is scoped to **stage 3 (move computation) + stage 4 (move execution)**, measured from the moment the occupation matrix is ready. Image readout and occupation-matrix generation are kept in a **separate, deterministic** budget: occupation-matrix generation is pipelined inside row-by-row readout and incurs no extra wall-clock. The 5 ms is enforced as a fixed wait-slot (pseudo-real-time): all other operations wait this fixed window for compute to finish; if compute is unreasonable to fit, the budget is revisited rather than silently exceeded.

**Per-cycle wall-clock (real number):** ≈ 10 ms exposure + ≈ 7 ms readout (35 µs/row × 200 rows) + ≤ 5 ms compute+execute ≈ **22 ms/cycle**. Loss headroom = 2 s / 22 ms ≈ **90 cycles** (not 400). Sorting must converge well inside 90 cycles.

**Overrun policy:** if compute misses the 5 ms slot, the cycle plays a **best-effort partial** move-set; atoms not yet sorted are retried on the next cycle. An overrun costs a cycle, not the shot.

### Atom trap lifetime
Practical in-trap atom lifetime ≈ 2 s (vacuum/heating limited). Sets the upper bound on total in-shot rearrangement time: ≈ 2 s / 5 ms ≈ 400 cycles of headroom before atom loss dominates. Convergence is therefore cycle-count limited by the sorting algorithm, not by the loss budget.

### Defect-free target geometry
The desired final arrangement of occupied tweezer sites that a shot's rearrangement loop converges toward.

### Orchestrator
The run-lifecycle **authority**. Owns the run state machine, lifecycle coordination over devices, the queue, and the calibration-DAG runner. **Lives on the Tower (`PC1`).** A run is *owned* and *executed* by the Tower; nothing else can advance a run's state. A Tower crash kills the in-flight shot (recovery is shot-boundary only) but not durable history.

### Broker
The Tower-resident real-time executor inside the orchestrator's host. Owns the OPX client (`QuantumMachinesManager`), BitFlow capture, the GPU rearrangement pipeline, `insert_input_stream`, and the local raw spool. Holds **no durable authority of its own** — it is the latency-critical execution arm of the Orchestrator. One Broker process per run.

### Job Validator / Submitter (EliteDesk role)
The EliteDesk performs **admission validation** — a pure pre-check that a `RunRequest` is well-formed, RBAC-permitted, on the template allow-list, and references an existing descriptor — then **submits** to the Tower orchestrator. It holds no run state and cannot advance it. Distinct from **compile-validation** (the Tower L4 `submitted → validated` step that evaluates bounds against the *active* descriptor + snapshot and attaches the [[validation-token]]) — that stays authority-side. The EliteDesk also **hosts the durable store** (metadata DB, calibration registry, off-host raw replica), so history survives a Tower crash.

**Deployment note:** in v1 all roles (Orchestrator, Broker, Validator, Postgres, data lake) run **co-located on the Tower** for development and testing. Physical distribution (Validator + Postgres + replica → EliteDesk) is a later step; the role boundaries are fixed now so the move is a deployment change, not a redesign.

### Calibration snapshot
An **immutable** published set of parameter versions. Never mutated after publication. A run pins to exactly one `snapshot_id`. Immutability is what makes historical shots reproducible — see [[active-snapshot-pointer]] for how "which snapshot is current" is tracked without violating immutability.

### Active snapshot pointer
The mutable answer to "which immutable [[calibration-snapshot]] is currently active." Modeled as an **append-only activation log** (`snapshot_activations` / `descriptor_activations`), not as a `valid_until` interval on the snapshot row — closing an interval would mutate an immutable row and lose concurrent-publication safety. The active row = the latest activation per *lineage*. Validity intervals are derived, never stored.

### Validation token
A compile-time **attestation that descriptor validation + parameter bounds + rate-limit checks ran** before a run reaches the broker. Signed by Layer 4 (HMAC key held only there), short expiry. It is **NOT** the safety mechanism — do not read "token present" as "safe." Distinct from the [[safety-plane]].

### Safety plane
The **independent hardware** interlock system — interlocks, watchdogs, RF/AOD bounds, defined safe states. Operates correctly even when the orchestrator is dead. This, not the [[validation-token]], is what actually keeps the apparatus safe. The two share no failure domain by design.
