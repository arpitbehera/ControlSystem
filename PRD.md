# PRD — AMO Neutral-Atom Lab Control System (v1)

**Source:** `.planning/PLAN-V2/` (15-document architecture set), `CONTEXT.md` glossary, ADR seed list (PLAN-V2 §13).
**Status:** Derived PRD for starting implementation. Where this PRD and PLAN-V2 disagree, PLAN-V2 wins.
**Companion:** `PLAN.md` — step-by-step implementation plan for the first slice (Phase 0 bootstrap → Phase 1 exit gate + Phase 0A harness code).

---

## Problem Statement

The lab runs a neutral-atom optical-tweezer experiment: load atoms into a tweezer array, image them on an EMCCD, rearrange them with an AOD into a defect-free target geometry, and execute programmable laser-pulse sequences against that array. Today there is **no control-system software** — the repository contains only architecture documents.

The people running the experiment face five problems:

1. **Scale.** The experiment operates at ~100 atoms and must reach ~1000 atoms within 3–5 years. The rearrangement feedback loop (image → classify → assign moves → play AOD chirp) has a hard latency budget (`t_compute + t_insert + t_execute ≤ 5 ms` from occupation-ready) that ad-hoc scripting cannot meet or verify.
2. **Reproducibility.** Postdocs and grad students turn over. Without immutable calibration snapshots and a full provenance chain, historical data becomes unreproducible and "which calibration is current" lives in someone's head or a spreadsheet.
3. **Durability.** Raw frames, shot metadata, and calibration history can be lost or become mutually inconsistent (raw without metadata, metadata without raw) when a machine crashes mid-shot.
4. **Safety.** Loss of a Python process must never be able to damage the apparatus or harm a person. Software checks alone are not a safety guarantee.
5. **Longevity.** The system must remain maintainable ~15 years, surviving vendor API churn (QM QOP versions, camera SDKs) and personnel turnover. The durable deliverables are the *contracts between layers*, not any particular implementation.

## Solution

Build the six-layer control platform specified in PLAN-V2:

- **Tower (`PC1`) is the run-execution authority** — orchestrator (scheduler, run FSM, calibration-DAG runner), compiler, and broker (OPX client, BitFlow capture, GPU pipeline, raw spool) all live there, keeping the rearrangement loop inside one PCIe topology. Only the Tower advances run state (ADR-0001).
- **EliteDesk is Admission Validator/Submitter + pending job queue + durable store** (Postgres metadata DB, calibration registry, off-host raw replica). It cannot advance run state. `v1-dev` co-locates all roles on the Tower for bring-up; `v1-lab` splits them before routine scientific operation.
- **Typed control plane:** gRPC + proto3 over VLAN 10. Run model `RunRequest → AcceptedJob → RunPlan → ShotResult → RunSummary`; eight-verb lifecycle contract (`health, capabilities, configure, arm, start, stop, status, disarm`) implemented identically by every device service, fake or real.
- **OPX+ owns deterministic timing.** Python is never in the timed loop. The rearrangement loop closes on the PPU via the versioned, fixed-width `RearrangementBatchV1` input-stream message; the GPU computes the plan, the PPU plays the waveform.
- **Calibration as immutable snapshots over a DAG,** with currency tracked by append-only activation logs (never `valid_until` mutation), and per-run execution bundles capturing compiled QUA + config + lockfile + firmware for bit-level reproducibility.
- **Durable shot commit:** local fsync spool → idempotent metadata mirror → off-host replica ack, with explicit shot states (`raw_spooled → metadata_mirrored → replicated → committed`) and a first-class `durability_tier` on every run/shot.
- **Independent safety plane** (hardware E-stop, PPU watchdog, RF/AOD bounds, defined safe states) that works even when every software process is dead. The `validation_token` is a compile-time attestation, not the safety mechanism.
- **Fake-first, contract-tested.** Every adapter ships after its fake; one parametrized contract-test suite drives fakes and reals through the same code path.
- **Phase 0A measurement spike** precedes contract freezing: `push_to_input_stream` latency curves, GPUDirect bring-up, `N_MAX_MOVES` derivation, process-discipline study, safety-plane independence tests, NTP drift baseline.

Implementation starts with the Phase 0/1 slice in `PLAN.md`: repository bootstrap, proto contracts, lifecycle FSM + contract tests, one fake device, Postgres schema v1, admission validator, orchestrator skeleton, operator CLI, and the Phase 0A hardware-harness code.

## User Stories

1. As an **operator**, I want to submit a run from a CLI with a template name and parameters, so that I can execute an experiment without writing QUA by hand.
2. As an **operator**, I want submission to fail fast with a typed rejection when my parameters violate descriptor bounds, so that invalid work never reaches the hardware queue.
3. As an **operator**, I want to see the live state of my run (`submitted → validated → planned → armed → executing → committing → completed`), so that I know what the system is doing.
4. As an **operator**, I want to cancel a pending job or an executing run, with the cancel taking effect at the next shot boundary, so that I can stop bad runs without tripping safety.
5. As an **operator**, I want a `RunSummary` (shot counts, status, duration, pinned snapshot/descriptor/bundle IDs) at the end of every run, so that I can immediately assess outcomes.
6. As an **operator**, I want re-submitting the same request with the same idempotency key to be deduplicated, so that a flaky terminal doesn't double-run an experiment.
7. As an **operator**, I want stale calibration to block my run and automatically trigger the calibration DAG, so that I never take data against expired parameters without knowing.
8. As an **operator**, I want the dashboard/CLI to distinguish "execution complete, commit pending" from "committed", so that I know when data is actually durable.
9. As a **senior operator**, I want to publish a calibration snapshot transactionally after fitness checks pass, so that a bad candidate can never silently poison future runs.
10. As a **senior operator**, I want in-flight runs to keep their pinned snapshot when I publish a new one, so that publication is always safe to do mid-operation.
11. As a **senior operator**, I want a safety trip to require my explicit acknowledgement before the run resumes, so that no shot replays automatically into an unknown apparatus state.
12. As an **admin**, I want descriptor changes to be new immutable rows plus an activation pointer (never in-place patches), so that past shots keep the exact descriptor they ran against.
13. As an **admin**, I want a role × verb access matrix enforced at both the gRPC layer and the Postgres role layer, so that an analyst or agent cannot mutate calibration even by accident.
14. As an **analyst (off-lab)**, I want a read-only dashboard over the Postgres replica, so that I can monitor runs and browse provenance without any ability to mutate the lab.
15. As an **analyst**, I want to pick any historical shot and walk `shot_uuid → run_uuid → (snapshot, descriptor, bundle) → code_commit_sha + lockfile + firmware`, so that I can reproduce the exact execution years later.
16. As an **automated agent**, I want to submit runs restricted to an allow-list of templates and view only my own runs, so that automation is useful but blast-radius-bounded.
17. As a **new grad student**, I want the current value of any calibration parameter to be a database query (latest activation per lineage), so that no lab spreadsheet is ever needed.
18. As a **platform engineer**, I want every device service — fake or real — to pass one shared lifecycle contract-test suite, so that the orchestrator can drive any device through identical code paths.
19. As a **platform engineer**, I want fakes for every device family before real adapters exist, so that the entire platform is testable in CI with no hardware.
20. As a **broker engineer**, I want the rearrangement wire message (`RearrangementBatchV1`) versioned, fixed-width, and validated on the PPU (protocol version, sequence continuity, snapshot/descriptor hashes, deadline, bounds), so that any malformed or stale batch lands in safe state instead of playing.
21. As a **broker engineer**, I want Phase 0A latency measurements (p50/p95/p99/p99.9/max from PPU `get_timestamp()`) for every declared input-stream size before the contract freezes, so that `N_MAX_MOVES` and `BATCH_WORDS` are derived, not guessed.
22. As a **broker engineer**, I want the broker's pure-logic paths (batch encoding, sequence/hash validation, spool fsync + replay) type-checked strict and covered against a fake OPX, so that the latency-critical component is the most tested, not the least.
23. As a **hardware engineer**, I want the hardware E-stop to close shutters and disable the RF amp with no software in the path, so that the apparatus is safe even if every process is dead.
24. As a **hardware engineer**, I want fault-injection tests (kill broker, drop payload, malformed batch, OPX power-cycle, E-stop trip) reified as re-runnable scripts, so that safety guarantees are re-verified on every major version bump.
25. As a **lab manager**, I want a Tower crash to kill at most the in-flight shot — never durable history — once the `v1-lab` split is deployed, so that years of data survive any single machine failure.
26. As a **lab manager**, I want commissioning data clearly labeled `v1-dev_non_durable` end-to-end (DB, dashboards, exports), so that non-durable data can never silently support a publication claim.
27. As a **lab manager**, I want quarterly restore drills (Postgres, switch config, replica failover) with recorded elapsed times, so that RTO targets are demonstrated rather than assumed.
28. As an **ops engineer**, I want every long-running process wrapped as a supervised Windows service with restart/backoff policy and structured JSON logs, so that the platform runs unattended.
29. As an **ops engineer**, I want NTP drift monitored per host with alerts above 10 ms sustained offset, so that observational timestamps stay trustworthy while OPX owns experimental timing.
30. As a **scheduler engineer**, I want run state held Tower-local-authoritative with an eventually-consistent Postgres mirror, so that an EliteDesk outage pauses durable commit but never halts an executing run.
31. As a **calibration engineer**, I want DAG nodes with declared inputs/outputs, staleness thresholds, and named fitness checks, so that failed candidates are quarantined and downstream nodes never consume them.
32. As a **device engineer**, I want to add a new device family by implementing the eight lifecycle verbs and one typed `Capabilities` branch, so that the base contract never changes when hardware grows.
33. As a **compiler engineer**, I want modeled devices (AOMs, AODs, coils) resolved into bounded OPX `play()` calls from calibration + descriptor, so that no out-of-bounds waveform is even compilable.
34. As a **future maintainer**, I want every load-bearing decision recorded as an ADR with a reversal condition, so that decisions can be safely revisited when evidence changes.

## Implementation Decisions

Decisions below are copied from PLAN-V2 (docs 00–13); the ADR IDs are the authority.

**Topology & authority**
- Tower = run-execution authority: orchestrator + compiler + broker; only the Tower advances run state. EliteDesk = admission validation + pending queue + durable store; deterministic admission so it can run co-located (`v1-dev`) or split (`v1-lab`) without redesign (ADR-0001).
- Rearrangement loop never leaves the Tower's PCIe topology (BitFlow → GPUDirect → RTX 4000 Ada → broker → OPX on VLAN 50). VLAN 50 is an L2-only trust enclave; no other host routes into it (ADR-0008).
- Run-vs-compute GPU arbitration is a Tower-local named OS mutex; Postgres records transitions as append-only audit only (ADR-0016).

**Contracts (5+ year freezes)**
- Lifecycle verbs: `health, capabilities, configure, arm, start, stop, status, disarm`; verbs may be added, never silently changed.
- Run model: `RunRequest`, `AcceptedJob`, `RunPlan`, `ShotResult`, `RunSummary`; run FSM and shot FSM as specified in PLAN-V2 §04, with cancel carrying both request and effective timestamps.
- Provenance chain: `code_commit_sha + descriptor_id + snapshot_id + execution_bundle_id → run_uuid → shot_uuid`; same IDs in DB rows and HDF5 attributes.
- `RearrangementBatchV1`: fixed-width homogeneous QUA `int` vector, 13 header words + 6 words/move; PPU validates version, sequence, hashes, deadline, bounds; missing/late/malformed → safe state; valid partial batches play best-effort (ADR-0002, provisional until Phase 0A).
- `N_MAX_MOVES = 1024` is a placeholder; Phase 0A must derive it from descriptor geometry + assignment policy and prove the OPX/QOP stack accepts the resulting declaration.

**Calibration & persistence**
- Immutable `calibration_snapshots` + append-only `parameter_versions` + candidate `calibration_executions`; currency via append-only `snapshot_activations` / `descriptor_activations` logs (ADR-0003). In-house DAG runner built to the QUAlibrate *shape*, not the library (ADR-0015).
- Per-run `execution_bundles` (compiled QUA + QM config + Python lockfile + firmware + dirty-worktree flag) (ADR-0004).
- Durable shot commit: broker fsync spool → `raw_spooled` → idempotent gRPC → single-transaction metadata mirror → async off-host replication → `committed` only after replica ack (ADR-0005). `durability_tier ∈ {v1-dev_non_durable, v1-lab_durable}` is a first-class column.
- PostgreSQL 16, Alembic migrations, SQLAlchemy 2.x (raw SQL on hot paths); HDF5-per-shot in v1 behind a stable manifest schema — container re-benchmarked in Phase 5 (ADR-0013).

**Timing & safety**
- OPX+ PPU is the timing root; NTP (RB3011 stratum-2) is observational metadata only; no PTP on installed gear (ADR-0006). No Python in the timed loop.
- Independent safety plane = hardware interlocks (L0/L0.5) + QUA-side bounds and PPU watchdog (L1/L1.5). Software layers (broker watchdog, scheduler interlocks, operator E-stop) are defense-in-depth only (ADR-0012). `validation_token` = compile-time HMAC attestation from Layer 4 with short expiry; broker refuses submissions without a valid one; it is never the safety mechanism.

**Stack & operations**
- Python 3.11+ for all non-RT code; QUA DSL (compiler-emitted only, never user-authored) for RT; CUDA C++ via cupy for kernels; TypeScript/React for the read-only dashboard; typer/click CLI.
- gRPC + proto3 + mTLS on VLAN 10 (ADR-0009); QM SDK on VLAN 50; shared-memory queue broker ↔ data-lake writer.
- One process per device-class, wrapped as Windows services via `nssm` (ADR-0011); broker default `HIGH_PRIORITY_CLASS`, pinned cores, priority raised only on measured benefit (ADR-0010).
- `src/` layout modular monolith, single repo; `uv` lockfile committed and embedded in execution bundles; semver.

**Phasing**
- Phase 0A (hardware spike, 4–8 weeks) gates all contract freezes: input-stream latency, GPUDirect bring-up + CPU baseline, process discipline, safety independence, NTP drift. Phases 1–6 follow the existing roadmap (control-plane skeleton → fake execution slice → snapshot & recovery → modeled devices → first local adapter → first remote adapter + `v1-lab` split). Every phase has a written exit gate; the next phase does not start until the gate is met in `.planning/MILESTONES.md`.

## Testing Decisions

- **Good tests assert external behavior at a contract boundary** — FSM transitions observed through the gRPC surface, rows observed in Postgres, rejections observed as typed errors — never internal call sequences or private state.
- **Contract tests are the architectural deliverable** (REQUIREMENTS.md TEST-01): one pytest suite in `tests/contract/` parametrized across every device-service implementation (`fake_camera, fake_slm, fake_psu, fake_lock, fake_arduino, fake_opx` in v1). New device classes opt in by passing the same suite; the suite drives the full verb FSM, idempotent re-issue, fault surfacing, and heartbeat behavior.
- **Unit tests (pytest)** cover pure logic: run/shot FSM transition tables, batch encoding, validation-token issue/verify, admission pinning, idempotency dedup.
- **Integration tests** run against dockerized Postgres + fake broker/fake OPX; they cover enqueue → dequeue → compile-validate → fake-execute → `RunSummary` row.
- **Fault-injection tests** (network faults via toxiproxy-equivalent, process kills, dropped payloads, malformed batches) assert the documented failure outcome, not mere survival.
- **Hardware smoke tests** live in `tests/hardware/`, are excluded from CI, run manually at bring-up, and double as the Phase 0A measurement harness; each Phase 0A test is a re-runnable script.
- **Gates:** `pytest-cov` ≥ 80% on orchestrator, device servers, compiler, and the broker's pure-logic paths; `ruff` + `black` + `mypy --strict` on orchestrator, compiler, contracts, and broker. CI: lint + unit + contract + integration + `alembic upgrade head` on a throwaway DB, per PR.
- **Prior art:** none in-repo (greenfield); the labscript/ARTIQ contract-test pattern cited in PLAN-V2 §10 is the reference shape.

## Out of Scope

Per PLAN-V2 §00 non-goals and §10:

- Mid-shot resume after device failure (recovery is shot-boundary only in v1).
- Routing raw image streams through the orchestrator (bulk stays local).
- Full real-hardware coverage in v1 (Phases 1–6 stop after one local + one remote adapter).
- Remote office submission, rich production dashboards, cloud-hosted control surface (v2: REMOTE-01, UI-02).
- Web-based control UI (anti-pattern A19); off-lab UI is read-only.
- PTP-class sub-µs cross-host sync; Kubernetes; Airflow/Prefect; time-series DBs; LLM-driven orchestration; cloud storage; tape archival.
- Electrical design of hardware interlocks and laser-safety classification (lab hardware-safety documentation owns those).
- Deliberately unfrozen: storage container choice, CUDA classifier/assignment internals, dashboard web framework, LLRS-style FPGA escape path.

## Further Notes

- **Ordering constraint:** Phase 0A measurements gate ADR-0002/0010/0016 acceptance and the `RearrangementBatchV1` freeze. Software work that doesn't depend on those numbers (proto contracts, lifecycle FSM, fakes, schema v1, admission, orchestrator skeleton) can proceed in parallel — that is exactly the slice `PLAN.md` covers.
- **Deployment posture:** everything in the starting slice runs co-located on the Tower (`v1-dev`), but the Admission Validator ↔ orchestrator boundary is a gRPC seam from day one so the `v1-lab` EliteDesk split is a deployment move, not a redesign.
- **ADR discipline:** the seed list in PLAN-V2 §13 becomes real files under `docs/adr/` as decisions are ratified; ADR-0001 and ADR-0016 are already Accepted and should be committed as files during repo bootstrap.
- **Repository layout** follows PLAN-V2 §10 (`proto/`, `schema/`, `src/`, `tests/`, `network/`, `ops/`, `docs/adr/`).
- **Source-of-truth pointers:** `.planning/REQUIREMENTS.md` (PLAT-01…HW-02), `.planning/ROADMAP.md`, and the research inputs under `.planning/research-inputs/` remain authoritative background; this PRD is their operational distillation.
