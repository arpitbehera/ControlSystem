# 08 — Calibration and Provenance

## Three contracts

This document defines three contracts that *together* survive 5+ years:

1. **Calibration DAG** — Optimus/QUAlibrate-shaped recipe of nodes producing parameters.
2. **Immutable snapshots** — the unit a *shot* points to (critique F-04).
3. **Provenance chain** — `code_commit_sha` + `descriptor_id` + `snapshot_id` + `execution_bundle_id` → `run_uuid` → `shot_uuid` (critique F-14).

Together these let a future user reproduce shot N exactly.

## Calibration DAG

Per `amo-control-system-design.md` §3.6, adopt the QUAlibrate shape but persist it in Postgres so the lab is not vendor-coupled to the (now-private) QUAlibrate source.

### Node definition

```python
@dataclass(frozen=True)
class DagNode:
    name: str                       # e.g. "single_qubit_pi_pulse_amplitude"
    inputs: list[str]               # parameter names consumed
    outputs: list[str]              # parameter names produced
    template_name: str              # QUA template the compiler emits
    max_age_s: float                # staleness threshold for downstream
    fitness_check: str              # name of analysis function returning pass/marginal/fail
    version: int                    # bumped on recipe change
```

The graph is the topological closure over nodes whose outputs feed each other's inputs.

### Persistence

In `dag_nodes`, `calibration_executions`, `parameter_versions`, `calibration_snapshots` (see §05 schema).

### Re-run triggers

| Trigger | Source |
|---|---|
| **Pull (freshness)** | `RunRequest.required_calibration` lists params; scheduler chains the DAG when `max_age_s` is exceeded |
| **Push (fitness failure)** | `fitness_check == "fail"` — invalidates that node's candidate; downstream candidates are marked stale (critique F-16) |
| **Scheduled (drift)** | A cron-shape rule re-runs node X every Y hours |
| **Manual** | `senior_operator` runs a node explicitly |

### Failure semantics (critique F-16 fix)

```
Node X runs → produces candidate parameter_version P_cand → fitness_check evaluates
   │
   ├─ pass     → P_cand becomes eligible for inclusion in next snapshot publication
   ├─ marginal → P_cand eligible only with operator countersign
   └─ fail     → P_cand quarantined; downstream nodes that consume P do NOT run
                  on P_cand; previously published P version remains in current snapshot
                  until a passing replacement is produced
```

**Downstream nodes never consume failed upstream candidates.** This is the inversion of the original text and resolves critique F-16. The DAG runner only triggers downstream when all upstream produced `pass` (or operator-approved `marginal`).

## Immutable snapshots (critique F-04 fix)

A snapshot is the *immutable, published* set of parameter versions a run executes against.

### Publication transaction

```sql
BEGIN;
  -- New snapshot inherits everything from parent
  INSERT INTO calibration_snapshots (parent_id, parameter_set, published_at, published_by)
    SELECT id, parameter_set || jsonb_build_object(:name, :new_param_version_id),
           NOW(), :user
      FROM calibration_snapshots WHERE id = :parent_id;
  -- Optionally close prior snapshot
  -- (snapshots are not "closed"; they remain queryable forever)
COMMIT;
```

Properties:

- A snapshot is **append-only**: the row, once committed, is never updated. Newer snapshots inherit from older ones via `parent_id`.
- A run resolves its `snapshot_id` at submit time, atomically. The scheduler reads the *current head* (no parent for which a child exists) and pins it.
- Concurrent publications serialize at the `INSERT` — the second publisher reads the now-updated head and inherits from it.
- A wrong calibration cannot retroactively poison existing data: every shot points at the snapshot that was head at its arm time, by ID.

### Snapshot vs registry semantics

There is no "registry" table that can be read for "current value". The current value of parameter X is:

```sql
SELECT pv.value
FROM   calibration_snapshots cs
JOIN   parameter_versions pv ON (cs.parameter_set ->> 'pi_pulse_amp')::bigint = pv.id
WHERE  cs.id = :current_head_snapshot_id;
```

The "current head" is the snapshot with no child. A run pinned to a snapshot reads its parameters by ID; concurrent publication of a new snapshot does not affect runs in flight.

### Snapshot publication authority

- `admin` and `senior_operator` only (see access matrix §04).
- Automated `agent` runs cannot publish; they can produce candidate parameter versions but a human approves publication.

## Execution bundle (critique F-14 fix)

Every run carries an `execution_bundle_id` that points to an immutable record of *everything* needed to reproduce the run:

```python
@dataclass(frozen=True)
class ExecutionBundle:
    id: int
    qua_program_blob: bytes          # compiled
    qm_config_blob: bytes            # compiled
    qm_config_hash: bytes            # sha256
    lockfile: str                    # full Python env lock (poetry / uv / pip-tools)
    firmware: dict                   # QOP version, OPX server build, driver versions
    code_commit_sha: bytes
    worktree_dirty: bool             # True if uncommitted changes existed at compile
    classifier_model_hash: bytes | None
    cuda_kernel_hash: bytes | None
    created_at: datetime
```

A run with `worktree_dirty == True` is flagged in the dashboard. Optionally rejected for `agent` submissions.

## Provenance chain

Every shot carries the full chain:

```
code_commit_sha ─┐
                 ├─→ execution_bundle_id  (compiled QUA+config+env+firmware)
device_descriptor_id ──┐
                       ├─→ run.descriptor_id
calibration_snapshot_id ──┐
                          ├─→ run.snapshot_id
                          ↓
                       run_uuid
                          ↓
                       shot_uuid
                          ├─→ shot.timing (PPU ticks)
                          ├─→ shot.analysis (control-relevant)
                          ├─→ shot.raw_state ∈ {pending, lake, lost}
                          ├─→ raw_manifests.sha256 + path
                          └─→ HDF5 attrs (same IDs as DB row)
```

Properties:

- **No timestamp comparisons across hosts** for causality. Snapshot identity is resolved by ID, not by `published_at <= shot.started_at`.
- **No path inferred from data**. The HDF5 file is found via `raw_manifests.file_path`; if missing on the lake, the off-host replica is queried; if both missing, `raw_state = 'lost'` makes this explicit.
- **No silent overwriting**. Every level of the chain is append-only.

## Multi-user safety

| Scenario | Safety property |
|---|---|
| Two operators submit conflicting runs | Idempotency by `(user, idempotency_key)`; serial queue prevents reorderings |
| Senior operator publishes new snapshot mid-run | In-flight run keeps its pinned `snapshot_id`; new run picks new head |
| Admin patches `device_descriptor` mid-run | In-flight run keeps its pinned `descriptor_id`; new run sees new descriptor |
| Analyst tries to mutate calibration | Postgres role lacks `INSERT` privilege; ACL also rejects at gRPC layer |
| Automated agent submits a non-allow-listed template | Compiler refuses; never enters queue |

## What this enables

- **5-year audit**: pick any historical shot row, walk back through `run_uuid` → `(snapshot, descriptor, bundle)` → reconstruct the exact compiled code, the exact parameter values, the exact driver versions, and the exact source-tree state at compile time.
- **Reproducibility under personnel turnover**: a new operator submitting the *same* `RunRequest` against the *same* snapshot produces the *same* compiled bytes; bit-for-bit comparison is possible (modulo OPX server build).
- **Conway-resistant separation**: nobody has to remember "which calibration is current"; the DB knows. The lab spreadsheet (anti-pattern A17) never gets created.
