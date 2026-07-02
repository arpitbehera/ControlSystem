# State

**Initialized:** 2026-04-08
**Current phase:** Phase 1 - Control-Plane Skeleton
**Current status:** Ready for phase discussion and planning

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-04-08)

**Core value:** Scientists can run reproducible, typed, recoverable experiments from one orchestrator without coupling hardware control, analysis, and UI into a fragile monolith.
**Current focus:** Establish the control-plane skeleton on `PC1`, including service discovery, lifecycle contracts, typed run entry points, and baseline liveness monitoring.

## Latest Milestone Context

- Approved design spec exists at `docs/superpowers/specs/2026-04-08-control-system-platform-design.md`
- The initial roadmap is intentionally contract-first and fake-first
- `PC1` is fixed as the orchestrator host for v1
- Bulk data should stay off the orchestrator by default
- Recovery is allowed only at shot boundaries in v1

## Phase Queue

1. Phase 1 - Control-Plane Skeleton
2. Phase 2 - Fake Execution Slice
3. Phase 3 - Snapshot And Recovery Policy
4. Phase 4 - Modeled Device Foundation
5. Phase 5 - First Local Hardware Adapter
6. Phase 6 - First Remote Hardware Adapter

## Next Command

Run `/gsd-discuss-phase 1` to clarify implementation details before planning, or `/gsd-plan-phase 1` to go directly into the implementation plan.

---
*Last updated: 2026-04-08 after initialization*
