"""W0A-1: OPX input-stream latency harness.

Run on Tower with lab-side `qm-qua` installed. Output feeds ADR-0002.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from broker.rearrangement_batch import BATCH_WORDS

SIZES = [4, 64, 256, 2048, BATCH_WORDS]
N_SAMPLES = 100_000
OPX_HOST = "192.168.88.10"


def build_program(size: int) -> Any:
    from qm.qua import advance_input_stream, declare_input_stream, declare_stream
    from qm.qua import infinite_loop_, program, save
    from qm.qua._dsl import get_timestamp

    with program() as prog:
        batch = declare_input_stream(int, name="latency_probe", size=size)
        ts_out = declare_stream()
        with infinite_loop_():
            advance_input_stream(batch)
            save(get_timestamp(), ts_out)
    return prog


def quantiles(deltas: list[float]) -> dict[str, float | int]:
    ordered = sorted(deltas)
    return {
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[int(len(ordered) * 0.95)],
        "p99": ordered[int(len(ordered) * 0.99)],
        "p999": ordered[int(len(ordered) * 0.999)],
        "max": ordered[-1],
        "n": len(ordered),
    }


def main() -> int:
    from qm import QuantumMachinesManager

    qmm = QuantumMachinesManager(host=OPX_HOST)
    results: dict[str, object] = {
        "opx_host": OPX_HOST,
        "n_samples": N_SAMPLES,
        "sizes": SIZES,
        "note": "Fill lab config/open_qm/fetch loop before accepting W0A-1.",
    }
    for size in SIZES:
        build_program(size)
        results[str(size)] = {"compiled": True, "measured": False}
    qmm.close_all_quantum_machines()
    path = Path(__file__).with_name("w0a1_results.json")
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
