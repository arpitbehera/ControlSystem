# 09 — Safety and Interlocks

## The rule (critique F-03)

The safety plane is **independent of the orchestrator, scheduler, calibration DB, and broker**. It must bring the apparatus to a defined safe state regardless of which software component has died, hung, or run amok.

Data-integrity controls are not a substitute for hardware safety. The control system is incomplete if loss of a Python process can damage the apparatus or harm a person.

## Safety plane components

| Layer | Mechanism | Owner |
|---|---|---|
| **L0 Physical** | Beam blocks, shutters with manual safety interlock, RF amplifier hard-limit on output power | Optical / RF hardware as installed |
| **L0.5 Wired interlocks** | Hardware E-stop button → kills shutter drivers + RF amp enable lines directly; vacuum interlock; laser safety interlock | Hardwired; no software in the path |
| **L1 RT (PPU)** | QUA-side bounds: AOD frequency / amplitude clamps; pulse-duration caps; safe-state pulse defined per channel; rejection of malformed `RearrangementBatchV1` into safe state | OPX+ firmware via compiled QUA |
| **L1.5 Watchdog** | PPU-internal watchdog: if `advance_input_stream` blocks past `deadline_ticks`, play safe-state pulse and surface `safety_trip` | QUA program |
| **L1.7 Broker watchdog** | If broker process dies, OS-level watchdog notifies scheduler; scheduler issues `Disarm` to all device services and signals OPX to halt next shot | Windows service watchdog; scheduler heartbeat |
| **L2 Device-service guards** | Each managed device enforces a `safe_default` on `Disarm`; PSUs ramp down; cameras stop triggering; SLM holds last frame | Device service per family |
| **L5 Scheduler interlocks** | Refuses to issue `Start` when descriptor/safety token is invalid; refuses to enter `armed` state with stale calibration; refuses to publish snapshots that violate descriptor bounds | Scheduler |
| **L6 Operator interlocks** | Operator E-stop on dashboard + lab terminal CLI: `scheduler.abort()` triggers Disarm-all and writes operator acknowledgement requirement | UI + scheduler |

## Safe states (per element)

| Element | Safe state |
|---|---|
| AOD-X analog out | DC 0 V (no chirp); RF amp gated by digital `aod_enable` line set to "disable" |
| AOD-Y analog out | Same |
| Atom-trapping laser shutter | Closed |
| Rydberg/excitation lasers | Closed |
| MOT coils PSU | Ramp to 0 A over the PSU's defined safe-ramp |
| Bias coils PSU | Same |
| Camera triggers | Stop triggering; cameras remain idle but armed |
| SLM | Hold last displayed frame (HDMI stateful; cannot blank without driver action) |
| OPX digital outs | All low except for hardware-defined enables that should remain high (e.g. vacuum interlock pass-through) |

Each safe state is encoded in the `DeviceDescriptor.safety` block per element. The compiler emits a `safe_state` QUA pulse for each timed output, callable from the watchdog branches.

## Watchdog ladder

Multiple watchdogs at different layers, with progressively wider blast radius:

```
Inner ─── PPU watchdog (per-shot deadline)        ─── milliseconds
    │
    │   trips: deadline missed, malformed BATCH
    │   action: play safe_state pulses, set safety_trip flag in output stream
    │
Mid ─── Broker watchdog (per-process)              ─── seconds
    │
    │   trips: insert_input_stream raises, framegrabber stalls, GPU error
    │   action: signal OPX to halt next shot, surface to scheduler, Disarm
    │
Outer ── Scheduler watchdog (per-run)              ─── tens of seconds
    │
    │   trips: heartbeat loss from broker / device services
    │   action: mark run unsafe; Disarm all services; require operator ack
    │
Last ── Hardware E-stop                            ─── instantaneous
        trips: human presses button
        action: cuts shutter + RF amp enable lines directly via interlock relay
                no software in the path; recovery requires manual reset + ops ack
```

The PPU watchdog is the **load-bearing** one for hung input streams (critique F-03 root concern). It is implemented as the bounded form of `advance_input_stream` followed by a deadline check in QUA — see §07 for the wire-message validation.

## Recovery posture

| Trip class | Recovery action | Authorization |
|---|---|---|
| PPU `safety_trip` (single shot) | Mark shot `unsafe`; continue run only if operator confirms | operator |
| Broker watchdog (process death) | Mark run `unsafe`; require Disarm-Arm cycle | operator |
| Scheduler watchdog (heartbeat miss) | Drain run; mark `unsafe`; alert | operator |
| Hardware E-stop | Full lab Disarm; investigate cause; physical reset + signed-off restart procedure | senior_operator |

No automatic replay of a physics shot after a safety trip (critique F-15). Operator must explicitly acknowledge that the safe state was reached and the apparatus is in a known-good condition.

## Safety token

The compiler attaches a `SafetyToken` to every `CompiledRun`. The broker refuses any `RtJobSubmission` without a valid token. Token contents:

```python
@dataclass(frozen=True)
class SafetyToken:
    descriptor_id: int
    snapshot_id: int
    bounds_hash: bytes              # sha256 over evaluated bounds in this compile
    signed_at: datetime
    signature: bytes                # HMAC with key held by Layer 4 only
    expires_at: datetime            # short window — minutes, not hours
```

Properties:
- Tokens cannot be forged by L2 / L3 / L5 — the HMAC key lives only in L4.
- Tokens expire fast. A run that sits in the queue past expiry is recompiled (L4 re-attaches a fresh token).
- The broker validates the token signature and the `(descriptor_id, snapshot_id)` against the current head; mismatch → reject.

## Validation tests

Phase 0A (mandatory) — fault-injection tests that **must** all pass before any user runs:

1. Kill the broker process during a run. PPU enters safe state within one shot. Recovery requires Disarm-Arm.
2. Drop the next expected `insert_input_stream` payload. PPU's `advance_input_stream` deadline trips; safe-state pulse plays; surface as `safety_trip`.
3. Inject a `RearrangementBatchV1` with wrong `protocol_version`. PPU enters safe state; never plays the chirp.
4. Inject a `RearrangementBatchV1` with mismatched `snapshot_hash32`. Same.
5. Inject a move with frequency/amplitude outside descriptor bounds. Compiler refuses to compile; if injected post-compile (synthetic test), PPU enters safe state.
6. Power-cycle the OPX+ mid-run. Scheduler marks run `unsafe`; safety plane (shutters / RF amp via hardware) brings apparatus to safe state independent of OPX state.
7. Trip hardware E-stop. All shutters close + RF amp disable within hardware latency (sub-ms target).

These are durable acceptance gates; they re-run on every major version bump.

## What this plan does *not* do

- It does not specify the *electrical* design of hardware interlocks (relay logic, voltage levels, response time). That lives in the lab's hardware-safety documentation.
- It does not specify the laser-safety classification or radiation-safety procedures. Those follow institutional policy.
- It does not own emergency power-off (EPO) — that is a building / institutional system.

What it *does* own: the contract that says "every safety event has a defined safe state, an independent path to reach it, and a logged acknowledgement before any run resumes."

## Anti-patterns avoided

- **A2** (hidden global state in instrument drivers) — `Disarm` is idempotent; safe-state is descriptor-defined, not driver-cached.
- **A3** (Python in the timed loop) — safety plane has no Python on the hot path; PPU watchdog is QUA-native; hardware E-stop has no software.
- **A8** (one fast box does everything) — broker death is contained; safety plane is independent of the broker.
- **A10** (bypassing sequencer for quick fixes) — the safety token + compiler-only QUA emission prevent "let me just toggle this DO from Python" workarounds.
