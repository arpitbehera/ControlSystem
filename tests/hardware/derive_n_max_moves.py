"""Derive N_MAX_MOVES candidate from geometry + assignment policy."""

from __future__ import annotations

import json
from pathlib import Path


def derive(max_sites: int, target_sites: int, detour_factor: float) -> int:
    worst_case_moves = int(target_sites * detour_factor)
    return min(worst_case_moves, max_sites)


def main() -> int:
    scenarios = {
        "current_100": derive(max_sites=256, target_sites=100, detour_factor=1.5),
        "projected_1000": derive(max_sites=2048, target_sites=1000, detour_factor=1.5),
    }
    path = Path(__file__).with_name("n_max_moves_derivation.json")
    path.write_text(json.dumps(scenarios, indent=2), encoding="utf-8")
    print(json.dumps(scenarios, indent=2))
    print(
        "ADR-0002 rule: freeze current-operation bound; record 1000-atom scaling trigger."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
