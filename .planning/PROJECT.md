# Neutral Atom Lab Control System

## What This Is

This repository is the foundation of a new lab control platform for a neutral atom optical tweezer experiment. It is intended to replace a fragile script-and-server system with a future-proof architecture built around a centralized orchestrator, typed run contracts, device abstractions, and strict separation between control traffic and bulk data movement.

The first milestone is not full lab coverage. It is a validated control-platform foundation: the orchestrator runs on `PC1`, discovers fake or real device services across lab PCs, accepts a `RunRequest`, advances a visible run state machine, and receives a `ShotResult` from a fake `camera/OPX` pipeline.

## Core Value

Scientists can run reproducible, typed, recoverable experiments from one orchestrator without coupling hardware control, analysis, and UI into a fragile monolith.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Establish `PC1` as the fixed orchestrator host for lab runs
- [ ] Define a typed control-plane contract for orchestrator-to-device communication
- [ ] Keep high-volume payloads off the orchestrator by default through a separate data-plane strategy
- [ ] Model experiments as `RunRequest -> RunPlan -> ShotResult -> RunSummary`
- [ ] Support both managed device services and OPX-backed modeled devices with calibration-aware semantics
- [ ] Build the first end-to-end fake execution slice with automated contract and integration tests

### Out of Scope

- Full support for every lab device in the first release — the platform contract must stabilize before broad adapter work
- Rich operator UX in the first milestone — a minimal observer client is enough to validate state and result flow
- Remote office job submission in the first milestone — lab-local orchestration comes first
- Mid-shot recovery — only shot-boundary retry/resume is scientifically safe in v1
- Routing raw image streams through the orchestrator — this adds latency and coupling without helping real-time feedback

## Context

The current lab stack already uses the right physical control instincts: `OPX+` owns deterministic timing, vendor SDKs tend to be isolated into separate processes, and image analysis participates in the experiment loop. The weakness is software structure. Control flow, device ownership, GUI behavior, analysis, and persistence bleed into one another, which makes the system fragile and hard to test.

The target lab topology is:

- `PC1`: fixed orchestrator host, directly attached to `OPX+` and the EMCCD camera, and home of local high-speed processing
- `PC2`: host for the `SLM`
- `PC3`: host for miscellaneous USB and network instruments such as power supplies, oscilloscopes, spectrum analyzers, Arduinos, and similar devices
- `PC4`: optional dashboard-only machine with no role in run execution

All lab PCs are connected over Ethernet. Raw image and similar bulk payloads should remain local to the host that owns them unless movement is explicitly required. For the EMCCD path, `PC1` receives CameraLink data, performs local processing, and feeds results back to `OPX+`; the orchestrator should receive metadata and derived outputs rather than raw image traffic.

This repository currently contains domain reference material in `Wiki/` and early architecture thinking in `docs/PRIMITIVE_PLAN.md`, but no actual platform implementation yet.

## Constraints

- **Topology**: `PC1` is the fixed orchestrator host in v1 — run ownership must stay centralized on the main lab machine
- **Runtime**: Windows-first lab environment — orchestration, testing, packaging, and deployment must work on Windows
- **Timing**: Python is never in the hard-timing loop — `OPX+` remains the timing authority
- **Data Movement**: Bulk payloads should avoid the control path — raw images and large patterns stay local by default
- **Reliability**: Recovery is checkpoint-based — v1 may retry or resume only at shot boundaries
- **Longevity**: The platform should remain extensible for roughly 15 years — contracts and boundaries matter more than short-term convenience
- **Incremental Adoption**: The new platform must allow fake devices and phased real-device onboarding — broad rewrites without validation are too risky

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use a modular monolith with supervised runtime processes | Keeps abstractions shared and testable without turning the lab stack into an ops-heavy microservice system | — Pending |
| Split communication into control plane and data plane | Small commands/results and bulk payloads have different latency and transport needs | — Pending |
| Put the orchestrator on `PC1` | The main lab machine already owns the `OPX+` and EMCCD path and is the natural control anchor | — Pending |
| Standardize on a shared lifecycle contract for managed device services | The orchestrator needs one durable way to coordinate diverse devices without hiding device-specific meaning | — Pending |
| Represent OPX-driven analog elements as modeled devices | AOMs, AODs, and similar elements need calibration-aware software semantics even without their own network service | — Pending |
| Treat testing as part of the architecture, not cleanup | The platform needs contract tests and fake devices before real hardware adapters are safe | — Pending |
| Allow recovery only at shot boundaries in v1 | Mid-shot resume is not a safe default for timing-critical experimental runs | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-08 after initialization*
