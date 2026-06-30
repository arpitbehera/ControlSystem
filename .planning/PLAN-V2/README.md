# PLAN-V2: AMO Neutral-Atom Lab Control System

**Status:** Draft architecture + phased implementation plan
**Date:** 2026-05-28
**Supersedes:** `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` *only where this plan explicitly disagrees*; otherwise extends them.

## Purpose

Concrete architecture and implementation plan for a neutral-atom optical-tweezer control system that scales from the current ~100-atom array toward a ~1000-atom target over 3–5 years while remaining maintainable for ~15 years.

This plan fuses two prior bodies of work:

1. The **software-platform spec** in `.planning/PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md` (orchestrator on `PC1`, typed `RunRequest -> RunPlan -> ShotResult -> RunSummary`, lifecycle contract, fake-first testing).
2. The **physical control-system research** in `.planning/research-inputs/Physical control system design/` (`amo-control-system-design.md` + `critique-and-improvements-1.md`), which adds hardware grounding: OPX+ PPU, BitFlow + GPUDirect rearrangement loop, calibration DAG, network topology, durable provenance, safety plane.

Where the two disagree, this plan resolves the disagreement and records the decision in §13 (ADRs).

## How to read

| # | Document | When to read |
|---|---|---|
| 00 | [Context & Constraints](00-context-and-constraints.md) | First — frames every later decision |
| 01 | [Architecture Overview](01-architecture-overview.md) | The big picture: six-layer model, diagram |
| 02 | [Hardware Topology](02-hardware-topology.md) | Where each subsystem physically lives |
| 03 | [Subsystem Boundaries](03-subsystem-boundaries.md) | Responsibility split: control plane, data plane, RT/non-RT |
| 04 | [Control-Plane Contracts](04-control-plane-contracts.md) | Run model + lifecycle contract + RPC shape |
| 05 | [Data Plane & Storage](05-data-plane-and-storage.md) | Bulk data path, durable shot commit, backup |
| 06 | [Timing & Synchronization](06-timing-and-synchronization.md) | OPX as timing root, NTP scope, RT boundary |
| 07 | [Rearrangement Loop](07-rearrangement-loop.md) | The latency-critical in-shot feedback path |
| 08 | [Calibration & Provenance](08-calibration-and-provenance.md) | Snapshot model, DAG, execution bundle |
| 09 | [Safety & Interlocks](09-safety-and-interlocks.md) | Independent safety plane |
| 10 | [Software Stack](10-software-stack.md) | Languages, libraries, transport, DB |
| 11 | [Risks & Bottlenecks](11-risks-bottlenecks-mitigations.md) | What goes wrong and how it is bounded |
| 12 | [Phased Implementation](12-phased-implementation.md) | Six phases + Phase 0A spike, exit gates |
| 13 | [Architectural Decisions (ADRs)](13-architectural-decisions.md) | One ADR per load-bearing choice |

## Top-level summary

- **Orchestrator on `PC1` (HP Z2 Tower)** — co-located with `OPX+` broker, BitFlow Axion 1xB framegrabber, Andor iXon, and RTX 4000 Ada to keep the rearrangement loop in one PCIe topology. Trade-off: latency-first, A8 risk bounded by strict process isolation and by moving calibration/metadata to the EliteDesk.
- **Six layered seams** (Physics → RT → device-server → calibration/metadata → compiler → scheduler → UI). Layer boundaries are the durable contracts; implementations inside layers are rebuildable.
- **Two communication planes.** Control plane carries typed lifecycle + run messages between orchestrator and services. Data plane keeps bulk payloads (raw images, SLM patterns) local to the host that owns them.
- **OPX+ owns deterministic timing.** Python is never in the timed loop. Rearrangement closes on the PPU with a versioned `RearrangementBatchV1` input-stream message; GPU computes the plan, PPU plays the waveform.
- **Calibration as immutable snapshots over a DAG.** A run points to one `snapshot_id`; downstream snapshots are published transactionally only after fitness checks pass.
- **Independent safety plane.** Hardware interlocks, RF/AOD bounds, watchdog, defined safe states — operate correctly even when the orchestrator is dead.
- **Fake-first, contract-tested.** Every device implements the same lifecycle contract; the orchestrator drives fakes and reals through the same code path.

## Source-of-truth pointers

- Existing requirements: `.planning/REQUIREMENTS.md` (PLAT-01 … HW-02).
- Existing phase queue: `.planning/ROADMAP.md` (6 phases).
- Research design doc: `.planning/research-inputs/Physical control system design/amo-control-system-design.md`.
- Critique that gates this plan: `.planning/research-inputs/Physical control system design/critique-and-improvements-1.md`.

This plan keeps the existing phase queue but inserts a **Phase 0A measurement spike** ahead of Phase 1 to validate the rearrangement-loop assumptions before contracts are frozen — per critique F-08.
