<!-- GSD:project-start source:PROJECT.md -->
## Project

**Neutral Atom Lab Control System**

This repository is the foundation of a new lab control platform for a neutral atom optical tweezer experiment. It is intended to replace a fragile script-and-server system with a future-proof architecture built around a centralized orchestrator, typed run contracts, device abstractions, and strict separation between control traffic and bulk data movement.

The first milestone is not full lab coverage. It is a validated control-platform foundation: the orchestrator runs on `PC1`, discovers fake or real device services across lab PCs, accepts a `RunRequest`, advances a visible run state machine, and receives a `ShotResult` from a fake `camera/OPX` pipeline.

**Core Value:** Scientists can run reproducible, typed, recoverable experiments from one orchestrator without coupling hardware control, analysis, and UI into a fragile monolith.

### Constraints

- **Topology**: `PC1` is the fixed orchestrator host in v1 — run ownership must stay centralized on the main lab machine
- **Runtime**: Windows-first lab environment — orchestration, testing, packaging, and deployment must work on Windows
- **Timing**: Python is never in the hard-timing loop — `OPX+` remains the timing authority
- **Data Movement**: Bulk payloads should avoid the control path — raw images and large patterns stay local by default
- **Reliability**: Recovery is checkpoint-based — v1 may retry or resume only at shot boundaries
- **Longevity**: The platform should remain extensible for roughly 15 years — contracts and boundaries matter more than short-term convenience
- **Incremental Adoption**: The new platform must allow fake devices and phased real-device onboarding — broad rewrites without validation are too risky
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
