# ADR-0016: Run-vs-compute GPU mutex is Tower-local; Postgres is audit only
## Status
Accepted

## Context
The Tower's single RTX 4000 Ada is shared between the latency-critical broker run-pipeline and the non-loop compute service (offline reanalysis, calibration analyses). The two must never touch the GPU concurrently. An earlier draft stored this mutex in EliteDesk Postgres, held by the scheduler. With run-execution authority now on the Tower (ADR-0001), arbitrating a Tower-local resource via a remote DB re-introduces a cross-host dependency on the critical path.

## Decision
The run-vs-compute lock is a **Tower-local named OS mutex**, owned by the orchestrator (now Tower-resident), acquired synchronously whenever a run is `armed`/`executing`. It is authoritative; no network is in the acquisition path. On holder death it releases via abandoned-mutex semantics. Run preempts compute: the orchestrator signals compute to checkpoint + release, then acquires. Postgres records mutex transitions as **append-only audit only**, never the lock itself.

## Alternatives considered
- Postgres advisory lock held by the scheduler (earlier draft): couples GPU arbitration to a remote host; partition causes split-brain (block a safe run, or proceed unconfirmed); adds a TCP+txn round-trip to arming; crash-release semantics murky across a proxied connection. Rejected.
- In-GPU/CUDA-context exclusivity only: doesn't coordinate two separate OS processes cleanly, and gives no audit trail. Rejected.

## Evidence / measurement
Both GPU contenders are Tower processes; zero EliteDesk processes touch the GPU. Failure-domain principle: a lock belongs with the resource it guards and the authority that schedules it.

## Consequences
GPU arbitration survives an EliteDesk/Postgres outage. The audit write is best-effort and off the critical path -- a lost audit row never blocks a run. Same split as ADR-0001: execution state on the Tower, durable history on the EliteDesk.

## Reversal condition
The GPU pipeline relocates to a host that is not the execution authority -> the mutex moves with the GPU, and the arbitration owner is reconsidered.
