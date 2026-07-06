# ControlSystem

AMO neutral-atom lab control system implementation for PLAN-V2 v1.

This repository is being built from the Pre-Phase-1 software-readiness slice in `PLAN.md`.
The first goal is a fake-first control-plane skeleton: typed contracts, lifecycle FSM,
contract-tested fake devices, Postgres schema v1, admission validation, orchestrator shell,
operator CLI, and Phase 0A hardware-measurement harness code.

Authoritative planning docs live under `.planning/PLAN-V2/`. Where this README, `PRD.md`,
or implementation notes conflict with PLAN-V2, PLAN-V2 wins.

## Current Status

Implemented:

- Python project bootstrap with `uv`
- `src/` package skeleton
- test package skeleton
- CI workflow scaffold
- accepted ADR files for ADR-0001, ADR-0016, ADR-0017
- Python runtime pinned to latest supported 3.14 patch line

Next planned slices:

- Proto3 wire contracts and generated Python stubs
- Shared lifecycle FSM and contract tests
- Fake camera and fake OPX lifecycle services
- Postgres schema v1 and Alembic migrations
- Admission validator and orchestrator skeleton
- Operator CLI
- Phase 0A hardware harness scripts

## Architecture

High-level constraints from PLAN-V2:

- Tower is run-execution authority.
- EliteDesk owns admission, pending queue, durable Postgres store, and off-host raw replica in `v1-lab`.
- OPX+ PPU owns deterministic timing; Python is never in the hard-timing loop.
- Every managed device implements the same lifecycle verbs:
  `health`, `capabilities`, `configure`, `arm`, `start`, `stop`, `status`, `disarm`.
- Contract tests define device-service compatibility before real hardware adapters exist.
- Calibration snapshots and descriptors are immutable; currency is append-only activation logs.
- `durability_tier` values are `v1-dev_non_durable` and `v1-lab_durable`.

## Repository Layout

```text
.planning/           Authoritative PLAN-V2 docs and planning inputs
.github/workflows/  CI workflow definitions
docs/adr/           Architectural decision records
network/            Network config and topology artifacts
ops/runbooks/       Operational runbooks
proto/              Proto3 control-plane schemas
schema/             Alembic/Postgres schema artifacts
src/                Python packages
tests/              Unit, contract, integration, fault-injection, hardware tests
```

Python packages currently scaffolded:

- `orchestrator`
- `compiler`
- `descriptor`
- `calibration`
- `broker`
- `device_servers`
- `safety`
- `dashboards`
- `proto_gen`

## Environment

Current development workspace:

- OS: Ubuntu 26.04 LTS on WSL2
- Kernel: `6.18.33.2-microsoft-standard-WSL2`
- Branch: `feat/pre-phase-1-readiness`
- Worktree: `/mnt/d/Workspace/ControlSystem/.worktrees/feat-pre-phase-1-readiness`
- Python: `3.14.5`
- Python range: `>=3.14,<3.15`
- Python pin file: `.python-version`
- Package manager: `uv 0.11.19`
- Container runtime: not installed (`docker` and `podman` missing)

Python 3.14 is used because the QM QUA Python library supports `>=3.10,<3.15`; this project
tracks the latest supported 3.14 patch line.

Docker or Podman is required before Postgres integration work:

```bash
docker version
docker run --rm postgres:16 --version
```

## Development

Install dependencies:

```bash
uv sync --all-groups
```

Run checks:

```bash
uv run pytest
uv run mypy
uv run ruff check src tests
uv run black --check src tests
```

At bootstrap, `uv run pytest` reports `no tests ran` and exits with code `5`; this is expected
until Task 2+ adds tests.

## CI

CI is defined in `.github/workflows/ci.yml`.

Planned CI gates:

- `uv sync --all-groups`
- proto codegen when proto files exist
- `ruff`
- `black --check`
- `mypy`
- Alembic upgrade when schema exists
- `pytest --cov --cov-fail-under=80 --ignore=tests/hardware`

## Hardware Tests

`tests/hardware/` is excluded from CI. These tests are manual lab bring-up and Phase 0A
measurement harness scripts. Each script should be rerunnable and write JSON results beside
itself.

## ADRs

Accepted ADRs currently present:

- `docs/adr/0001-execution-authority-and-broker-placement.md`
- `docs/adr/0016-gpu-mutex-locality.md`
- `docs/adr/0017-lifecycle-disarm-returns-uninit.md`

New load-bearing decisions should become ADRs before they become hidden implementation policy.

## Expansion Notes

Keep this README current as each slice lands:

- Add generated proto usage once Task 2 lands.
- Add lifecycle service examples once Task 3 lands.
- Add fake device commands once fake services exist.
- Add DB setup and migration commands once schema exists.
- Add CLI examples once operator commands exist.
- Add deployment notes once `v1-dev` and `v1-lab` runbooks exist.
