# 10 — Software Stack

This is the minimum-viable stack for v1. Every choice has an explicit reason; alternative-and-rejected entries record what is *not* chosen and why.

## Languages

| Component | Language | Reason | Rejected alternatives |
|---|---|---|---|
| Orchestrator (scheduler, compiler, DAG runner) | **Python 3.11+** | Vendor SDKs (`qm-qua`, BitFlow, Andor) are Python-first; team familiarity; rich scientific ecosystem | Rust: SDK gaps. Go: no scientific libs. C++: dev velocity |
| Device services | **Python 3.11+** | Same lifecycle contract, same gRPC libs, same conventions | per-language drift |
| CUDA kernels | **CUDA C++** invoked via `cupy` or hand-written `.cu` | Native GPU programming; mature on Windows | Numba: latency too variable |
| QUA programs | **QUA DSL** (Python builder → compiled bytecode) | Vendor-fixed | none |
| Web dashboard | **TypeScript + React** (static build) | Standard; off-lab-friendly | Pure-Python templating: harder maintenance |
| Operator CLI | **Python + typer/click** | In-process with orchestrator client | bash: poor on Windows |
| Schema definitions | **Protocol Buffers (proto3)** | Forward/backward compatible; multi-language | JSON Schema: weaker typing |

Python is the chosen lingua franca for *non-RT* code. RT remains QUA on PPU.

## Runtime

| Layer | Tool |
|---|---|
| Process supervision (Windows) | `nssm` (Non-Sucking Service Manager) wraps each long-running Python process as a Windows service |
| Auto-restart policy | scheduler / broker: restart with exponential backoff, max 5 times in 10 min; device services: restart with same |
| Logging | structured JSON to per-service rotating files + a single aggregated tail file on EliteDesk |
| Config | YAML files committed to repo; environment-specific overlay via env vars |
| Secrets | `pass`/`gopass` or Windows DPAPI; *never* in repo; mTLS certs in OS keystore |

## Data layer

| Component | Tool |
|---|---|
| Metadata DB | **PostgreSQL 16** on EliteDesk NVMe |
| Schema migrations | **Alembic** (SQLAlchemy migrations) |
| ORM | **SQLAlchemy 2.x** for orchestrator-side queries; raw SQL for performance paths |
| Raw data lake | HDF5-per-shot in v1 (re-evaluated in Phase 5 per critique F-13) |
| HDF5 lib | **h5py** with chunked, GZip-9 compression, fletcher32 checksums |
| Replication | Postgres WAL streaming to off-host target |
| Backup | nightly `pg_dump` + 30-day retention |

Rejected:
- **SQLite**: insufficient for concurrent device-server inserts.
- **MongoDB / document store**: relational provenance dominates; SQL joins are right.
- **InfluxDB**: time-series is a v2 add-on if drift dashboards demand it; not the primary store.

## Communication

| Channel | Transport |
|---|---|
| Orchestrator ↔ device services | **gRPC** over TCP, mTLS, on VLAN 10 |
| Orchestrator ↔ dashboards | **gRPC** + HTTP/JSON (read-only) on VLAN 10 / 40 |
| Broker ↔ OPX | **QM SDK** (`qm-qua`) over VLAN 50 |
| Broker ↔ data-lake writer | **shared-memory queue** (POSIX-style via `multiprocessing.shared_memory`) on Tower |
| Scheduler ↔ Postgres | **psycopg3** with connection pool |
| Service heartbeats | gRPC bidi stream |

Rejected:
- **ZeroMQ**: lighter than gRPC but lacks schema enforcement and TLS by default.
- **MQTT**: pub/sub fits IoT-style telemetry but not RPC-shaped lifecycle.
- **REST/HTTP**: weaker typing than proto; chosen only for read-only dashboard.

## Testing

| Test class | Tool |
|---|---|
| Unit | **pytest** |
| Contract (lifecycle FSM) | **pytest** + fake-device fixtures; parametrized across every device-service implementation |
| Integration | **pytest** + dockerized Postgres + fake broker / fake OPX |
| Fault injection | **pytest** + `pytest-toxiproxy` or equivalent for network faults |
| Hardware smoke | dedicated `tests/hardware/` excluded from CI; run manually on bring-up |
| Coverage | `pytest-cov`; CI gate at 80% on `src/orchestrator/`, `src/device_servers/`, `src/compiler/`, and the **pure-logic paths of `src/broker/`** (`encode_batch`, sequence-continuity / snapshot-hash validation, spool fsync + replay) exercised against the fake-OPX. Hardware-interop glue (BitFlow/Andor/CUDA) is excluded and covered by `tests/hardware/` smoke. |
| Lint / format | **ruff** + **black** + **mypy --strict** on orchestrator, compiler, contracts, **and `src/broker/`** (the broker is latency-critical; its logic must be the most typed, not the least) |

Contract tests are the architectural deliverable per `REQUIREMENTS.md` TEST-01. They are parametrized across `[fake_camera, fake_slm, fake_psu, fake_lock, fake_arduino, fake_opx]` in v1; new device classes opt in by passing the same test set.

## CI

| Job | Where |
|---|---|
| Lint + unit + contract | GitHub Actions on PR |
| Integration with dockerized Postgres + fake services | GitHub Actions on PR |
| Hardware smoke | manual lab terminal run; results posted to PR |
| Schema migration apply | `alembic upgrade head` on a throwaway DB; CI gate |

## Packaging + deployment

| Concern | Approach |
|---|---|
| Project layout | `src/` layout (PEP 621); single repo (modular monolith) |
| Dependency mgmt | **uv** or **poetry** for lockfile; deterministic builds |
| Lockfile | committed; included in `execution_bundles.lockfile` for provenance |
| Distribution | wheel built per release; installed into venvs on each host |
| Deployment | a `make deploy-pc1` / `make deploy-elitedesk` target per host; idempotent |
| Versioning | semver; major bumps require schema migration documentation |
| Release notes | per-release `CHANGES.md`; archived to release tag |

## Repository layout (proposed)

```
.
├── proto/                   # Proto3 schemas — wire contracts
│   ├── lifecycle.proto
│   ├── run_model.proto
│   ├── safety.proto
│   ├── rearrangement.proto
│   └── scheduler.proto
├── schema/                  # Postgres schema + migrations
│   ├── alembic.ini
│   └── versions/
├── src/
│   ├── orchestrator/        # scheduler, run FSM, DAG runner
│   ├── compiler/            # builder → CompiledRun
│   ├── descriptor/          # DeviceDescriptor + validation
│   ├── calibration/         # DAG types + snapshot model
│   ├── broker/              # OPX broker + GPU pipeline + spool
│   ├── device_servers/
│   │   ├── _base/           # lifecycle FSM, contract base
│   │   ├── camera_andor/
│   │   ├── camera_gigE/
│   │   ├── slm/
│   │   ├── psu/
│   │   ├── lock/
│   │   └── arduino/
│   ├── dashboards/
│   │   ├── operator_cli/
│   │   ├── readonly_backend/
│   │   └── readonly_frontend/
│   └── safety/              # validation_token issuance + validators; safe-state definitions
├── tests/
│   ├── contract/            # lifecycle FSM contract tests
│   ├── unit/
│   ├── integration/
│   ├── fault_injection/
│   └── hardware/            # excluded from CI
├── network/
│   ├── ip_reservations.yaml
│   ├── lab-switch.cfg       # 3560G running-config (track in git)
│   ├── lab-router.rsc       # RouterOS export
│   ├── RESTORE.md
│   ├── MINIMAL_OPX.md
│   └── ntp_fallback.md
├── ops/
│   ├── deploy/
│   ├── backups/
│   └── runbooks/
├── .planning/               # this directory tree
└── docs/
    └── adr/                 # one ADR per major decision
```

## What is *not* in v1

- Kubernetes / container orchestration — out of scope.
- Apache Airflow / Prefect — scheduler is a custom thin process; the DAG runner is the calibration DAG runner, not a general workflow engine.
- Async/streaming OLAP (DuckDB, ClickHouse) — analyst queries run on Postgres replica; if performance becomes a concern in v2, an OLAP layer is added behind the dashboard backend.
- LLM-driven orchestration — out of scope.
- A web-based control UI — anti-pattern A19 in v1; v2 dashboard is read-only.

## What v2 will add (per existing `REQUIREMENTS.md` v2 + this plan)

| v2 feature | Mechanism |
|---|---|
| REMOTE-01 Remote office job submission | gRPC gateway on EliteDesk + OAuth-on-VPN; agent token; no orchestrator off `PC1` |
| UI-02 Richer operator dashboard | TS/React; same gRPC backend; mutating verbs gated on operator role |
| DATA-01 Bulk-data archive + replay | Background indexer over the lake; signed manifests; replay client reads HDF5 + snapshot to drive offline reanalysis |
| DEV-01 More device families | New `device_servers/<family>/`; contract tests get a new parametrize case |
