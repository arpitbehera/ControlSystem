"""Heartbeat policy: 1 Hz default, 3-miss timeout."""

from __future__ import annotations


class HeartbeatMonitor:
    def __init__(
        self,
        expected_services: frozenset[str] = frozenset(),
        period_s: float = 1.0,
        miss_threshold: int = 3,
    ) -> None:
        self._expected = set(expected_services)
        self._window_ns = int(period_s * miss_threshold * 1_000_000_000)
        self._last: dict[str, int] = {}

    def register(self, service_id: str) -> None:
        self._expected.add(service_id)

    def beat(self, service_id: str, now_ns: int) -> None:
        self._expected.add(service_id)
        self._last[service_id] = now_ns

    def unhealthy(self, now_ns: int) -> set[str]:
        return {
            service_id
            for service_id in self._expected
            if service_id not in self._last
            or now_ns - self._last[service_id] > self._window_ns
        }
