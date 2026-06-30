# 07 — Rearrangement Loop

## The seam

The rearrangement loop is the only place in the system where a Python-hosted compute step participates in a per-shot decision. It is also the only place where vendor-coupling to QM is unavoidable. The seam between **GPU plan compute (Python on Tower)** and **AOD waveform synthesis (QUA on PPU)** must be the 5-year contract.

Per `amo-control-system-design.md` §3.5 (with critique F-02, F-06, F-07 corrections applied): GPU computes a versioned `RearrangementBatchV1` message; PPU consumes it via input stream and plays the AOD chirp.

## Physical path

```
[Atoms in tweezers]
       │ optical
       ▼
[Andor iXon EMCCD]
       │ CameraLink (Base / Full)
       ▼
[BitFlow Axion 1xB]                       — PCIe Gen2 ×4, StreamSync DMA
       │ GPUDirect for Video — P2P PCIe write, no CPU bounce
       ▼
[RTX 4000 Ada Generation, 20 GB]          — PCIe Gen4 ×16
       ├── CUDA: site classifier (matched filter / lightweight FFN)
       ├── CUDA: assignment algorithm (parallel multi-tweezer / Hungarian)
       └── CUDA: encode RearrangementBatchV1
       │ cudaMemcpyAsync → pinned host memory (~10 µs)
       ▼
[Broker Python process, Z2 Tower]         — single interpreter, RT priority
       │ job.insert_input_stream("rearr_batch", batch_bytes)
       ▼
[OPX server (QM router, VLAN 50)]
       │
       ▼
[OPX+ PPU input-stream FIFO]
       │ advance_input_stream("rearr_batch")
       ▼
[QUA program on PPU]
       ├── parse RearrangementBatchV1
       ├── validate sequence_no continuity
       ├── enforce deadline_ticks
       ├── on invalid/missing: enter safe state, do not play
       └── play AOD chirp for each move in batch
       │ analog out → RF amp
       ▼
[AOD]
       │ acoustic waves
       ▼
[Atoms rearranged]
```

## The wire message (critique F-02, F-07)

```python
import struct

PROTOCOL_VERSION = 1
N_MAX_MOVES = 1024            # Phase 0A measurement determines target; oversize OK
MOVE_STRUCT = "<4HHfI"        # src_x, src_y, tgt_x, tgt_y (site IDs); group_id;
                              # t_ramp_us (float32); flags (u32)
MOVE_BYTES = struct.calcsize(MOVE_STRUCT)
HEADER_STRUCT = "<HHIIIQI"    # protocol_version, _pad, sequence_no, n_moves,
                              # deadline_ppu_ticks_lo, deadline_ppu_ticks_hi,
                              # snapshot_hash32  (32-bit truncated from sha256)
HEADER_BYTES = struct.calcsize(HEADER_STRUCT)
BATCH_BYTES = HEADER_BYTES + N_MAX_MOVES * MOVE_BYTES   # fixed-width
```

| Field | Meaning |
|---|---|
| `protocol_version` | Bumped on incompatible changes. PPU rejects unknown versions into safe state |
| `sequence_no` | Monotone per run. PPU verifies `sequence_no == last + 1`; mismatch → safe state |
| `n_moves` | Number of valid moves in the padded array. Always ≤ N_MAX_MOVES |
| `deadline_ppu_ticks` | PPU clock tick by which the chirp must start. Missed deadline → safe state |
| `snapshot_hash32` | First 32 bits of `calibration_snapshot.id`-hash. PPU validates that the in-flight snapshot matches |
| `moves[i].src_{x,y}` | Source site ID in the descriptor's lattice index space (not raw coords) |
| `moves[i].tgt_{x,y}` | Target site ID |
| `moves[i].group_id` | Concurrency group; moves in the same group play in parallel where possible |
| `moves[i].t_ramp_us` | Per-move ramp time (float32, microseconds) |
| `moves[i].flags` | Bit 0: "force pause for analysis"; bit 1: "abort if any prior move in group failed"; remaining reserved |

The message is **fixed-width**. The QUA input stream is declared once with size `BATCH_BYTES` and never resized. `n_moves` carried inside the payload (not on a separate IO variable) — this resolves the critique F-02 atomicity bug.

QUA-side validation:

```python
with program() as rearrange:
    batch = declare_input_stream(t=fixed, name="rearr_batch", size=BATCH_BYTES_FLOATS)
    advance_input_stream(batch)
    # parse header from batch
    assign(version, batch[OFFSET_VERSION])
    with if_(version != PROTOCOL_VERSION):
        align(...)                  # bring everything to a known boundary
        play("safe_state", "aod_x"); play("safe_state", "aod_y")
        # mark run unsafe via output stream
        ...
    # similarly for sequence_no, snapshot_hash32, deadline_ppu_ticks
    # on valid: iterate n_moves, play each
```

Python-side production:

```python
def rearrangement_shot(target_geometry, descriptor, snapshot, deadline_tick):
    raw    = framegrabber.grab_into_gpu(gpu_buf)        # GPUDirect, ~200 µs
    occ    = classifier_kernel(raw)                      # ~300 µs
    moves  = assignment_kernel(occ, target_geometry,
                               max_moves=N_MAX_MOVES)    # ~300 µs
    batch  = encode_batch(
                 protocol_version=PROTOCOL_VERSION,
                 sequence_no=next_seq(),
                 n_moves=len(moves),
                 deadline_ppu_ticks=deadline_tick,
                 snapshot_hash32=snapshot.hash32(),
                 moves=pad_to(moves, N_MAX_MOVES),
             )
    job.insert_input_stream("rearr_batch", batch)        # ~ms; Phase 0A measures
```

The contract that survives 5+ years: **the fields and the wire layout above**. Everything else (classifier model, assignment algorithm, CUDA kernel internals, even N_MAX_MOVES if it grows) is rebuildable.

## Process discipline on the broker host

Per critique F-09, process discipline is *measured* before priorities are pinned. Default:

| Process | Priority | CPU affinity | Notes |
|---|---|---|---|
| Broker | `HIGH_PRIORITY_CLASS` (raise to RT only after measured benefit) | cores 0–7 of 24 P-cores | single Python interpreter |
| Compute service | `NORMAL_PRIORITY_CLASS` | cores 8–15 | gated by scheduler mutex during armed/executing |
| Andor service | `NORMAL_PRIORITY_CLASS` | cores 16–19 | not in loop; non-loop snaps only |
| Data-lake writer | `BELOW_NORMAL_PRIORITY_CLASS` | cores 20–23 | asynchronous from loop |
| Anything else | normal | unbinned | should be nothing on the broker host |

Mutex semantics: the scheduler holds a row-level lock on a Postgres `broker_resource` row whenever any run is `armed` or `executing`. The compute service polls before running heavy jobs; failures are reported, not buffered.

GPU buffer ownership (critique F-09 unresolved → Phase 0A deliverable):
- Broker owns BitFlow buffer registration during a run.
- Andor SDK ownership during a run = closed (operator cannot trigger non-loop snaps).
- The exact handoff path between Andor SDK initialization (driver service startup) and BitFlow's in-process consumption (broker capture) is benchmarked in Phase 0A. If the SDK ownership model requires Andor SDK to hold the camera handle, the handoff is documented as a hard prerequisite to broker startup; otherwise, the broker may hold the handle directly.

## Latency budget (estimates pending Phase 0A measurement)

| Stage | Best-case | Pessimistic | Source / basis |
|---|---|---|---|
| Andor readout (256×256 ROI) | 0.5 ms | 2 ms | iXon Ultra datasheet, EM-gain dependent |
| Axion 1xB → GPU GPUDirect | 0.1 ms | 0.3 ms | 131 KB / PCIe Gen2 ×4 |
| CUDA classifier kernel | 0.1 ms | 0.5 ms | overprovisioned for 256×256 |
| CUDA assignment kernel | 0.1 ms | 0.5 ms | ~100 atoms |
| GPU → pinned host → Python | 0.05 ms | 0.2 ms | `cudaMemcpyAsync`, pinned memory |
| `insert_input_stream` to PPU FIFO | **0.5 ms** | **5 ms (unknown)** | **Phase 0A measures** |
| `advance_input_stream` + AOD setup | 0.05 ms | 0.1 ms | PPU clock-cycle scale |
| AOD chirp (physics-limited) | 1 ms | 5 ms | not architectural |
| **Total** | **≈ 2–4 ms** | **≈ 7–10 ms** | dominated by stage 6 + chirp |

Phase 0A measurement (acceptance items below) replaces every estimate with a measured number with quantiles.

## Acceptance gates (Phase 0A)

The rearrangement loop contract is **provisional** until these pass:

1. **End-to-end loop latency on the Tower-resident broker**: median, p95, p99, p99.9, max from PPU `get_timestamp()` across ≥ 10⁵ frame-trigger-to-AOD-start cycles. Pass threshold: p99 ≤ 8 ms at current array size; max ≤ 15 ms.
2. **`insert_input_stream` payload-size scaling**: latency curves for 16 B, 256 B, 1 KB, 8 KB, BATCH_BYTES. Pass: curve is flat (within 1 ms) up to BATCH_BYTES.
3. **30-minute no-drop acquisition**: zero `Statistic_Failed_Buffer_Count` (or vendor equivalent) under realistic competing CPU/IO load on the Tower.
4. **Fault injection**: kill broker mid-loop, drop input-stream payload, send malformed BATCH — PPU enters safe state in every case; no analog out beyond bounds; recovery requires operator `Disarm`/`Arm` cycle.
5. **Process discipline measurement**: p99/p99.9 with broker at `HIGH_PRIORITY_CLASS` vs `REALTIME_PRIORITY_CLASS` vs default. Accept only the setting that improves p99.9 without dropped frames or system instability.

## Scaling to 1000 atoms (Phase 5+)

Three knobs available on existing hardware:

1. **Larger BATCH_BYTES**: raise N_MAX_MOVES; the wire layout is forward-compatible if the PPU rejects unknown versions and the producer never under-pads.
2. **Multi-batch per shot**: send N batches in one `insert_input_stream`; QUA reads N times. Same wire-transit cost, lower Python overhead.
3. **Compress trajectory**: RLE on contiguous moves; PPU decompresses inside the QUA program if simple.

Hard limit: the GPU compute headroom. RTX 4000 Ada is overprovisioned for 256×256 ROIs; ROI growth to 1000-atom geometry is benchmarked in Phase 5.

If the Phase-3 budget is exceeded and none of the knobs close the gap, the escape is the LLRS-style framegrabber → FPGA → OPX path. This requires a hardware redesign (Hamamatsu Orca Quest 2 + QM OP-NIC or equivalent) and is explicitly out of scope for v1.

## Anti-patterns avoided

- **A3** (Python in the timed loop) — no Python code runs after `insert_input_stream`. The chirp is QUA on PPU.
- **A7** (same process owns RT-IO + GUI + analysis) — broker is GUI-less; analysis lives in the compute service.
- **A10** (bypassing the sequencer for "quick fixes") — every analog/digital action is QUA-compiled. There is no `qm_machine.set_analog_voltage(...)` path during armed runs.
- **A14** (schemas defined by example) — BATCH layout is `struct`-typed and versioned.
- **A15** (no formal handoff between user code and RT) — only the compiler can emit QUA; no user-authored QUA runs in v1.
