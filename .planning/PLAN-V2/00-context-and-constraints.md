# 00 — Context & Constraints

## Scientific context

The lab runs a neutral-atom optical-tweezer experiment. The control system must:

- Load atoms into a tweezer array, image them on an EMCCD, rearrange them with an AOD into a defect-free target geometry, and execute a programmable sequence of laser pulses against that array.
- Currently scale ~100 atoms; design target ~1000 atoms within 3–5 years; expected serviceable lifetime ~15 years.
- Survive personnel turnover (postdocs, grad students) without losing reproducibility of historical data.

## Hardware inventory (verified)

### Compute hosts (lab PCs)

| Host | CPU / RAM | GPU | Storage | OS | Pinned hardware |
|---|---|---|---|---|---|
| **HP Z2 Tower** (`PC1`) | Ultra 9 285K (24 cores), 128 GB | RTX 4000 Ada Gen, 20 GB | 4 TB NVMe + 12 TB HDD | Win 11 Pro | BitFlow Axion 1xB CameraLink framegrabber, Andor iXon EMCCD |
| **HP Z2 Mini G1i** (`PC2`) | Ultra 9 285, 64 GB | RTX 4000 SFF Ada | 2 TB NVMe | Win 11 Pro | SLM via HDMI |
| **HP EliteDesk 800 G6** | i7-10700, 64 GB | (integrated) | NVMe | Win 10 LTSC | — |
| **Lenovo ThinkCentre** (`PC3`) | i5-10500T, 16 GB | (integrated) | — | Win 10 LTSC | GigE / USB cameras and misc instruments |

### RT controller and timing

- **Quantum Machines OPX+** with QM router. Drives AOD analog out + all timed digital lines.
- QM client library: `qm-qua` (Python). PPU bytecode is the only firmware in the hard-timing loop.

### Instruments

- Andor iXon EMCCD (CameraLink → BitFlow Axion 1xB → GPUDirect → RTX 4000 Ada).
- Princeton Instruments ProEM HS1024 (GigE).
- 2× DMK 33GX545 GigE cameras, 2× DMK 33GX264 GigE cameras.
- Thorlabs CS165MU1 (USB), PCO Pixelfly ×2 (USB).
- SLM (HDMI, on `PC2`).
- AODs (2 axes) driven by OPX+ analog out → RF amp.
- Misc: power supplies, oscilloscopes, spectrum analyzers, Arduinos, laser locking electronics.

### Networking

- Cisco Catalyst WS-C3560G-48TS-S (48× GbE + 4× SFP, IP Base, IOS 15.0(2)SE-class). **No PTP, no EEE, jumbo MTU is global-only.**
- MikroTik RB3011UiAS-RM router (RouterOS 7, dual QCA8337 switch chips — chip boundary at ports 5/6).
- QM router stays in place between OPX+ controller and lab Ethernet (vendor topology).

## Constraints

| Constraint | Source | Implication |
|---|---|---|
| `PC1` is the fixed orchestrator host in v1 | `PROJECT.md` | Run ownership stays on the Tower; do not split orchestrator across hosts |
| Windows-first runtime | `PROJECT.md` | Orchestration, testing, packaging on Windows; no Linux-only stack |
| Python is never in the hard-timing loop | `PROJECT.md`, OPX architecture | All timed analog/digital lives on the OPX PPU; Python is the builder / planner / consumer |
| Bulk payloads stay off the control path | `PROJECT.md` | Camera frames + SLM patterns local to the host that owns them; orchestrator handles metadata and derived outputs only |
| Recovery is shot-boundary only in v1 | `PROJECT.md` | No mid-shot resume; failed shot is failed |
| Platform must remain extensible ~15 years | `PROJECT.md` | Contracts and seams matter more than today's libraries |
| Fake devices must precede real adapters | `PROJECT.md` | Contract-first, fake-first; every adapter ships with contract tests |
| No PTP on installed switch + router | `amo-control-system-design.md` §3.4.1.1 | NTP-only between hosts; OPX owns experimental timing internally |
| BitFlow Axion 1xB + RTX 4000 Ada are PCIe-bound to the Tower | GPUDirect for Video requires same PCIe topology | Rearrangement compute cannot relocate off the Tower |
| QM router required between OPX+ and lab subnet | QM vendor docs | Cannot bypass without QM support; treat QM router VLAN as trust enclave |
| `insert_input_stream` latency vs payload size is unknown | QM docs publish no number | Phase 0A spike must measure before contracts are frozen (critique F-08) |
| SLM HDMI refresh ≥ 16.7 ms | `PC2` HDMI link | Hard floor on any experiment that updates the hologram between shots |
| QUAlibrate source moved private | github.com/qua-platform/qualibrate | Build to the DAG-shape *contract*, not to the QUAlibrate library |

## Non-goals (v1)

These are explicitly excluded from this plan and remain as `out of scope` in `REQUIREMENTS.md`:

- Mid-shot resume after device failure.
- Routing raw image streams through the orchestrator.
- Full real-hardware coverage in the first roadmap (Phase 1–6 deliberately stop after one local + one remote adapter).
- Remote office submission and rich production dashboard workflows.
- Cloud-hosted control surface.
- PTP-class sub-µs cross-host clock sync (would require new switch + grandmaster).

## What this plan does *not* freeze

Per the critique register (`critique-and-improvements-1.md` §I-15, §F-13, §F-19):

- File-storage container choice (HDF5-per-shot vs chunked HDF5 vs Zarr) — empirically selected after Phase 0A benchmark.
- Exact CUDA classifier model and assignment algorithm — these are 2–3 year rebuildables.
- Specific Python web framework for the read-only dashboard.
- Whether to escape to an LLRS-style framegrabber→FPGA→OPX path — decided after Phase 3 latency measurement.

## What this plan *does* freeze (5+ year contracts)

- Shot-provenance chain: `code_commit_sha` + `device_descriptor_id` + `snapshot_id` + `execution_bundle_id` → `run_uuid` → `shot_uuid`.
- Lifecycle contract verbs: `health`, `capabilities`, `configure`, `arm`, `start`, `stop`, `status`, `disarm`.
- Run model types: `RunRequest`, `RunPlan`, `ShotResult`, `RunSummary`.
- Rearrangement-loop wire message: `RearrangementBatchV1` (fixed-width, versioned, padded). Detailed in §07.
- Role × verb access matrix (verbs may be added, never silently changed).
