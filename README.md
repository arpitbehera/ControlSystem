# ControlSystem

AMO neutral-atom lab control system implementation for PLAN-V2 v1.

This repository starts with the Pre-Phase-1 software-readiness slice from `PLAN.md`:
typed control-plane contracts, lifecycle FSM and contract tests, fake devices, schema v1,
admission validation, orchestrator shell, operator CLI, and Phase 0A hardware-measurement
harness code.

Authoritative planning docs live under `.planning/PLAN-V2/`. Where implementation notes
conflict with those docs, PLAN-V2 wins.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run mypy
uv run ruff check src tests
uv run black --check src tests
```

Hardware tests under `tests/hardware/` are manual lab bring-up tests and are excluded from CI.
