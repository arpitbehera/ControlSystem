# ADR-0001: Tower holds run-execution authority; EliteDesk admits + stores
## Status
Accepted

## Context
`PROJECT.md` fixes `PC1` (= HP Z2 Tower) as orchestrator host and says run ownership stays on the Tower and the orchestrator is not split across hosts. The rearrangement loop is PCIe-bound to the Tower (BitFlow + RTX 4000 Ada, GPUDirect). The A8 risk is that durable history is lost if the Tower (which executes runs) also holds the only copy of the calibration registry / metadata. The resolution is **not** to move run authority off the Tower, but to separate *authority over execution* (Tower) from *pending job admission + durable storage* (EliteDesk).

## Decision
The **Tower is the run-execution authority** -- it hosts the Orchestrator (scheduler, run State FSM, lifecycle coordinator, calibration-DAG runner), the Compiler, and the Broker (OPX client, framegrabber, GPU pipeline, raw spool). Only the Tower can compile, arm, execute, or advance a run's state. The **EliteDesk is the Admission Validator/Submitter, pending job queue owner, and durable store** -- it validates requests semantically at submit time, records `submitted_at`, pins the active `descriptor_id` and `snapshot_id`, appends `AcceptedJob`s to the pending queue, and hosts Postgres (metadata DB + calibration registry) plus the off-host raw replica. Explicit descriptor IDs are reserved for replay/debug/admin flows. The Tower records `execution_started_at` when it dequeues and begins authority-side compile-validation of the pinned descriptor + snapshot. The EliteDesk cannot advance run state. **`v1-dev` may co-locate all roles on the Tower** for bring-up/testing and for one first commissioning demo with explicitly accepted Tower-disk durability risk. Data produced in that posture is commissioning data, not durable scientific data, and must not support durable analysis or publication claims. Runs and shots are labeled with `durability_tier = 'v1-dev_non_durable'`; routine `v1-lab` runs use `durability_tier = 'v1-lab_durable'`. **`v1-lab` moves Admission Validator + Postgres + replica to the EliteDesk** before routine scientific operation; that is when the Tower-crash durability guarantee applies.

## Alternatives considered
- Orchestrator (scheduler/FSM) on EliteDesk, broker on Tower (earlier draft of this ADR): contradicts `PROJECT.md` ("Tower owns run, do not split orchestrator"), and puts a cross-host hop between run-authority and the latency-critical executor. Rejected.
- Pure-Tower with Postgres also on Tower as the *only* copy: full A8 exposure -- a Tower disk loss takes history with it. Acceptable only for `v1-dev` bring-up/testing; rejected for `v1-lab`.

## Evidence / measurement
GPUDirect for Video requires PCIe co-location (BitFlow + RTX 4000 Ada); the framegrabber is on the Tower, so execution authority colocated with execution avoids a cross-host hop on the loop. Phase 0A W0A-2 measures the actual GPUDirect path.

## Consequences
Pending jobs live on the EliteDesk; active run state lives on the Tower. A Tower crash halts the in-flight shot (shot-boundary recovery only) but leaves queued jobs and durable history intact in `v1-lab`. Queued jobs are reproducible because they pin `descriptor_id` and `snapshot_id` at submission; the Tower may block/reject/requeue stale pinned IDs but never silently rebinds them. Freshness is checked at admission and again at execution start; stale-at-execution jobs become `blocked_calibration` until resubmitted or explicitly refreshed-and-rebound. Cancel follows ownership: EliteDesk cancels pending jobs, Tower cancels active runs at shot boundary, and both record request/effective timestamps. The Admission Validator must be deterministic over `RunRequest`, descriptor refs, RBAC, template allow-list, active descriptor/snapshot resolution, calibration freshness at submission, and static semantic rules so it can run on either host. `v1-dev` co-location means the A8 benefit is not realized there; the Phase 5 commissioning demo is allowed only as a commissioning run with that reduced durability posture recorded. Routine scientific operation depends on `v1-lab`.

## Reversal condition
Phase 0A reveals an unsolvable bottleneck on the Tower -> consider relocating the GPU pipeline + broker (and therefore execution authority) to a new host that retains PCIe co-location.
