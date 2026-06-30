# 06 — Timing and Synchronization

## The rule

**OPX+ owns experimental timing. NTP timestamps are observational metadata only.**

This is the answer to critique F-18 and the convergent pattern across every durable control system surveyed (`amo-control-system-design.md` §1.10, seam #7). Two consequences:

1. No Python in the timed loop. Every timed action — analog out, digital pulse, conditional branch within a shot — lives inside a QUA program executing on the OPX+ PPU.
2. No cross-host clock guarantee tighter than NTP. Anything that needs sub-µs cross-host coordination is wrong by construction on this hardware.

## What runs where

| Timed-action class | Hardware | Notes |
|---|---|---|
| AOD waveform synthesis | OPX+ PPU analog out | Chirped Blackman AM·FM; deterministic |
| Timed digital gates (shutters, gate pulses) | OPX+ digital out | Sub-100 ns precision |
| In-shot conditional branches (MCM) | OPX+ PPU (`if_`, `assign`) | 224 ns conditional, 272 ns parametric |
| Camera triggers | OPX+ digital out → camera trigger input | Andor / GigE / USB cameras all triggered, not free-running |
| Camera readout | Camera + driver | Not in the PPU clock; surfaces via DMA / TCP |
| Rearrangement plan compute | Tower GPU | Asynchronous to PPU; results re-enter PPU via input stream |
| Calibration node execution | OPX+ PPU + Tower compute | Each node is a small QUA program + Python analysis |
| Run start, shot start, run end | OPX job orchestration | PPU clock ticks recorded into `shots.timing` |

## NTP layout (between hosts)

| Stratum | Source | Sync target |
|---|---|---|
| 0 | Atomic / GPS (institute / public) | upstream of RB3011 |
| 1 | Institute NTP server (preferred) or public pool (fallback) | RB3011 peers upstream |
| 2 | RB3011 NTP server | All lab hosts |

Per-host config:

- Windows: `w32time` configured against `10.10.30.1`; `MaxPosPhaseCorrection` / `MaxNegPhaseCorrection` bounded to ≤ 1 s to avoid silent jumps.
- Linux (if any): `chronyd` against the same.
- Sustained offset > 10 ms is alarmable.

Drift bookkeeping (critique F-18):
- Each host writes `chronyc tracking` / `w32tm /query /status` to a daily log on EliteDesk.
- The dashboard surfaces a clock-health tile per host.
- Upstream NTP loss is logged + alerted; hosts continue with last-known drift; no silent re-step.

PTP is not achievable on installed gear (Cisco 3560G has no PTP support; RB3011 cannot grandmaster). If a future experiment ever needs sub-µs cross-host sync, the upgrade path is a Catalyst IE-3300 / 3650 + Meinberg LANTIME grandmaster. Out of scope for v1–v2.

## OPX-internal sync

- Single OPX+ chassis in v1. Intra-chassis sync is the vendor's responsibility.
- If a second OPX+ is added (potential within 24 months), the QM cluster docs describe inter-chassis sync. Adding a second OPX may add a constraint on the VLAN-50 subnet design — this should be a Phase 5+ decision (`amo-control-system-design.md` §1014, #7).

## SLM HDMI timing constraint

The SLM updates at HDMI cadence (≥ 16.7 ms per frame). Two implications:

1. Any experiment that needs a *new* hologram between consecutive shots inherits this floor.
2. The orchestrator must arm-then-wait for SLM `frame_displayed` before issuing `Start` to the OPX. The lifecycle contract's `arm` → `start` gap is the right home for this wait.

Mitigation when the floor bites: pre-compute holograms for the whole scan offline, push them as a sequence, and let the SLM service step through them on its own trigger input.

## QUA timing constructs

The compiler maps user-level timing intent onto QUA. Reserved capabilities:

| Intent | QUA primitive |
|---|---|
| Pulse on AOD axis X | `play(pulse_name, "aod_x")` |
| Wait | `wait(ticks, "aod_x")` |
| Synchronize multiple elements | `align(...)` |
| Conditional pulse | `if_ / else_` + measurement result |
| Loop | `for_` / `while_` |
| In-shot feedback | `advance_input_stream(params)` |
| Per-shot timestamp | `get_timestamp()` |
| Deadline enforcement | QUA `timeout`-equivalent via `wait_for_trigger` with bounded timeout |

QUA programs are never user-authored directly in v1. The compiler emits them from typed templates + parameters + descriptor + snapshot. Hand-edits to compiled programs are blocked in the device-server queue (`qm_config_hash` check).

## Run-internal clock

Within a run, the PPU clock is authoritative. The shot record stores PPU ticks:

```json
"timing": {
  "armed_at_ppu_tick": 1234567890,
  "first_output_at_ppu_tick": 1234567990,
  "ended_at_ppu_tick": 1234568321,
  "host_wall_at_arm": "2026-05-28T15:33:21.213Z"
}
```

The host wall time at arm is recorded for human-readability; downstream alignment uses PPU ticks.

## Cross-shot ordering

Critique F-18 again: ordering is the database's job, not NTP's.

- Run sequence within the lab = `runs.run_uuid` plus `runs.submitted_at` (server-side).
- Shot sequence within a run = `shots.shot_index` (compiler-assigned).
- Calibration history = `calibration_executions.generated_at` + `calibration_snapshots.published_at`, both server-side.

No client code uses wall-clock comparison across hosts to establish causality.

## Acceptance criteria for timing in Phase 0A

Before any contracts are frozen, Phase 0A must measure (critique F-08, F-09):

1. Wall-clock and PPU-tick alignment across ≥ 10⁵ shots: confirm the host-wall stamp at arm has < 100 ms jitter relative to PPU.
2. NTP offset across the four lab hosts after 24 h cold start: ≤ 10 ms sustained.
3. Round-trip `insert_input_stream → advance_input_stream` latency on the lab's OPX+ at representative payload sizes (16 B, 256 B, 1 KB, 8 KB). Required: p50, p95, p99, p99.9, max. Source of truth: PPU `get_timestamp()` from inside QUA. *Host-side ICMP / ping is excluded — Windows scheduler-bound, not informative.*

These results gate the rearrangement-loop contract design in §07.
