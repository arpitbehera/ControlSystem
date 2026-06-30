# 01 — Architecture Overview

## The seven seams that must survive 5+ years

Across ARTIQ, labscript-suite, OPX/QUA + QUAlibrate, Pasqal/Pulser, Quantinuum, IBM Qiskit, and Google Optimus, these seven seams converge (`amo-control-system-design.md` §1.10). This plan adopts all seven by name:

1. A **named RT / non-RT boundary**.
2. **Experiment description as data**, compiled to RT bytecode.
3. A **calibration store separate from source control**.
4. **Calibration as a DAG** of nodes updating a parameter registry.
5. **Per-shot calibration snapshot** attached to results.
6. **One driver process per instrument** under a central orchestrator.
7. A **pseudoclock / sequencer as the timing root**, not the host clock.

Every architectural decision below traces to one or more of these seams.

## Layered model

```
┌─────────────────────────────────────────────────────────────────────┐
│ L6  Access & UI                                                     │
│     • Operator CLI / lab-terminal dashboard (write-capable)         │
│     • Off-lab read-only browser dashboard                           │
│     • Scripted clients (agents) with allow-list templates           │
├─────────────────────────────────────────────────────────────────────┤
│ L5  Scheduler & Orchestrator                                        │
│     • RunRequest → RunPlan validator                                │
│     • Run state machine (prepared/armed/executing/committed/…)      │
│     • Calibration DAG traversal runner                              │
│     • Lifecycle coordinator over the shared device contract         │
├─────────────────────────────────────────────────────────────────────┤
│ L4  Compiler & Experiment Description                               │
│     • Pasqal-shaped Builder: Template + params + DeviceDescriptor   │
│       + snapshot → CompiledRun                                      │
│     • Validate-at-submit against DeviceDescriptor (P7)              │
│     • Sequence-transformation compiler passes (MCMR, DD)            │
│     • Emulator backend with strict_validation (P11/P17)             │
├─────────────────────────────────────────────────────────────────────┤
│ L3  Calibration Registry + Metadata DB + Raw Data Lake              │
│     • PostgreSQL on EliteDesk: runs, shots, dag_nodes,              │
│       calibration_executions, parameter_versions,                   │
│       calibration_snapshots, device_descriptors                     │
│     • Execution-bundle store (compiled QUA + config + lockfile)     │
│     • Raw data lake on Tower 12 TB HDD (+ off-host replica)         │
├─────────────────────────────────────────────────────────────────────┤
│ L2  Device-Server Layer (one process per instrument-class)          │
│     • Uniform lifecycle contract (health/capabilities/configure/    │
│       arm/start/stop/status/disarm)                                 │
│     • Managed devices: cameras, SLM, power supplies, lock           │
│       electronics, stages, Arduinos                                 │
│     • Modeled devices: AOMs, AODs, analog shutters, coils — no      │
│       independent service, but carry calibration + bounds           │
├─────────────────────────────────────────────────────────────────────┤
│ L1  Real-time layer (deterministic timing + waveform synthesis)     │
│     • OPX+ PPU owns all timed analog/digital                        │
│     • Rearrangement loop: GPU plans → PPU plays                     │
│     • RearrangementBatchV1 input-stream contract                    │
│     • Independent safety / interlock plane                          │
├─────────────────────────────────────────────────────────────────────┤
│ L0  Physics                                                         │
│     • Atoms, lasers, optics, vacuum, RF, magnetics                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Seam-to-layer mapping

| Seam | Lives at | Detail |
|---|---|---|
| RT / non-RT boundary | L1 ↔ L2 | `RtJobSubmission` / `RtJobResult` |
| Description as data | L4 | Builder + compiler; emulator backend |
| Calibration store | L3 | Postgres tables; HDF5 attrs reflect IDs |
| Calibration DAG | L5 + L3 | DAG traversal at L5; persistence at L3 |
| Per-shot snapshot | L3 → L1 | `snapshot_id` resolved at compile time, embedded in shot record |
| Driver-per-instrument | L2 | Each device-server is one Windows service or one Python long-running process |
| Pseudoclock as timing root | L1 | OPX+ PPU |

## Communication planes

Per `PROJECT.md` and `amo-control-system-design.md` §3.0:

### Control plane

Carries small, typed, latency-tolerant messages:

- Service discovery + registration.
- `health` / heartbeat / `capabilities` exchange.
- Configuration + arming commands.
- Run-state events.
- `ShotResult` and `RunSummary` delivery.
- Calibration node submission and results.

Transport: gRPC over TCP on VLAN 10 (`lab-core`). Typed via Protocol Buffers; schema lives in `proto/` under version control. Heartbeats over a separate keep-alive stream.

### Data plane

Carries bulk payloads:

- Raw EMCCD frames (CameraLink → BitFlow → GPU, never crosses the network).
- SLM phase patterns (HDMI on `PC2`, never crosses the network).
- Raw image dumps from GigE cameras (VLAN 20, direct to the host that owns the camera).
- HDF5 raw-data files (written locally on the owning host; ingested asynchronously).

Default rule: **bulk stays local unless a concrete reason requires movement**. Replication for backup happens on a separate schedule from runs.

## Five visual subsystem boundaries

```
                 ┌──────── User & Agents ────────┐
                 │ operator CLI │ browser RO UI  │
                 │ scripted agents (allow-list)  │
                 └──────────────┬────────────────┘
                                │  gRPC, RBAC
                                ▼
       ┌────────── Orchestrator (EliteDesk + Tower-resident broker) ──────────┐
       │   Scheduler   │   Compiler   │   Calibration DAG runner   │ State FSM │
       │   (EliteDesk) │  (EliteDesk) │       (EliteDesk)          │ (EliteDesk)│
       │                                                                       │
       │   Broker (Tower) — owns OPX client, framegrabber, GPU pipeline       │
       └────┬────────────────┬──────────────────┬──────────────────────────────┘
            │ gRPC           │ gRPC             │ gRPC + libs
            ▼                ▼                  ▼
     ┌───────────┐    ┌───────────────┐  ┌──────────────────┐
     │ Managed   │    │   OPX+ PPU    │  │ Calibration DB / │
     │ device    │    │ (RT plane)    │  │ Metadata DB /    │
     │ services  │    │  • AOD        │  │ Data lake / ADRs │
     │ (cameras, │    │  • timed I/O  │  │ (Postgres,       │
     │  SLM, PS, │    │  • input/     │  │  files, repo)    │
     │  …)       │    │    output     │  └──────────────────┘
     └───────────┘    │    streams    │
                      └───────┬───────┘
                              │ RF / analog / digital
                              ▼
                       ┌──────────────┐
                       │   Physics    │
                       └──────────────┘
                              ▲
                              │ optical, image
                       ┌──────┴──────────────────────┐
                       │ Andor + BitFlow + GPUDirect │  (data plane,
                       │ → Tower RTX 4000 Ada        │   never leaves
                       │ → CUDA classifier+assign    │   the Tower)
                       │ → insert_input_stream       │
                       └─────────────────────────────┘
```

## Process layout (Tower-resident broker, EliteDesk-resident orchestrator)

On the Tower (`PC1`), in order of run-criticality:

1. **Broker process** (single Python interpreter, pinned CPU affinity, no GUI). Owns `QuantumMachinesManager`, BitFlow capture, GPU pipeline, `insert_input_stream`, durable local raw spool. *Latency-critical; one process per run.*
2. **Andor service** (separate Windows service). Owns Andor SDK; serves non-loop snaps. Idle / suspended during armed runs.
3. **Compute service** (separate process, same GPU). Non-loop GPU work — offline reanalysis, calibration analyses. **Operator-visible mutex prevents concurrent run + compute.**
4. **Data lake writer** (separate process). Consumes shot records from the broker via shared-memory queue, writes HDF5 + checksums asynchronously.

On the EliteDesk:

1. **Scheduler / orchestrator** (Python long-running process). State FSM, lifecycle coordinator, queue, calibration-DAG runner.
2. **Compiler service** (in-process with scheduler in v1; can be split later).
3. **Postgres** (local NVMe). Metadata DB + calibration registry.
4. **Read-only dashboard backend** (FastAPI on a separate port).
5. **TFTP server** for switch / router config backups.

On `PC2` (HP Z2 Mini):

1. **SLM device service** (lifecycle contract).
2. **Holography compute** (Gerchberg–Saxton / WPGS) — in-process with SLM service in v1.
3. **Emulator host** for the Layer-4 emulator backend.

On `PC3` (Lenovo ThinkCentre):

1. **Slow-camera device services** (one process per camera-family).
2. **Misc instrument device services** (Arduinos, scopes, power supplies).

## What this orientation buys

- **A8 mitigation**: the Tower stays as the broker but never holds the calibration registry — a Tower crash kills an in-flight shot, not history.
- **Latency-first**: the rearrangement loop is entirely in one PCIe topology; no cross-host hop on the critical path.
- **Failure-domain separation**: scheduler and DB on a different host than the loop; backup target on yet another storage domain.
- **Conway-resistant**: layered seams survive personnel turnover (`amo-control-system-design.md` §2.3 / A20).

The remaining documents in this directory fill in the contracts between layers, the durable schemas, the safety plane, and the phased implementation order.
