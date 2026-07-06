"""W0A-5: NTP drift baseline across Windows lab hosts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import platform
import re
import subprocess
import time
from pathlib import Path


def query_offset_s() -> float | None:
    result = subprocess.run(
        ["w32tm", "/query", "/status"],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"Phase Offset:\s*([-\d.]+)s", result.stdout)
    return float(match.group(1)) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()
    path = Path(__file__).with_name(f"w0a5_{platform.node()}.csv")
    deadline = time.time() + args.hours * 3600
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        while time.time() < deadline:
            writer.writerow([dt.datetime.now(dt.UTC).isoformat(), query_offset_s()])
            handle.flush()
            time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
