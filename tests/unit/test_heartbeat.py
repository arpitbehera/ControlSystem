from orchestrator.heartbeat import HeartbeatMonitor

NS = 1_000_000_000


def test_service_healthy_within_threshold() -> None:
    mon = HeartbeatMonitor(
        expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3
    )
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=2 * NS) == set()


def test_service_unhealthy_after_three_misses() -> None:
    mon = HeartbeatMonitor(
        expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3
    )
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=4 * NS) == {"cam"}


def test_beat_recovers_service() -> None:
    mon = HeartbeatMonitor(
        expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3
    )
    mon.beat("cam", now_ns=0)
    assert mon.unhealthy(now_ns=4 * NS) == {"cam"}
    mon.beat("cam", now_ns=4 * NS)
    assert mon.unhealthy(now_ns=5 * NS) == set()


def test_expected_service_that_never_beats_is_unhealthy() -> None:
    mon = HeartbeatMonitor(
        expected_services=frozenset({"cam"}), period_s=1.0, miss_threshold=3
    )
    assert mon.unhealthy(now_ns=0) == {"cam"}
