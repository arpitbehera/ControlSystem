# ControlSystem

AMO neutral-atom lab control-system skeleton. Current state is Pre-Phase-1
software readiness for `v1-dev` co-located bring-up, not architecture Phase 1
completion.

## Quickstart

Start local Postgres:

```bash
docker run -d --name cs-pg \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=controlsystem \
  -p 5432:5432 \
  postgres:16
```

Set DB URL:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:test@localhost:5432/controlsystem'
```

Install deps and apply schema:

```bash
uv sync --all-groups
(cd schema && uv run alembic upgrade head)
```

Run verification:

```bash
uv run ruff check src tests
uv run black --check src tests
uv run mypy
uv run pytest --ignore=tests/hardware
```

Run a scheduler service:

```bash
uv run python - <<'PY'
from orchestrator.admission import AdmissionValidator
from orchestrator.core import Orchestrator
from orchestrator.db import make_engine
from orchestrator.grpc_server import serve_scheduler

engine = make_engine("postgresql+psycopg://postgres:test@localhost:5432/controlsystem")
validator = AdmissionValidator(engine, frozenset({"noop_template"}))
orchestrator = Orchestrator(engine)
serve_scheduler(validator, orchestrator, port=50070).wait_for_termination()
PY
```

Use operator CLI:

```bash
uv run lab submit-run --user op --template noop_template --params '{}' --key demo-1
uv run lab list-runs
uv run lab status --events 1
```

Hardware/Phase 0A scripts live under `tests/hardware/` and are excluded from CI.
