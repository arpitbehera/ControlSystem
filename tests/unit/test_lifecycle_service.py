from proto_gen import lifecycle_pb2

from device_servers._base.fsm import DeviceState
from device_servers._base.service import (
    DeviceAdapter,
    DeviceFaultError,
    LifecycleService,
)


class _Recorder(DeviceAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_on: str | None = None
        self.safe_default_applied = False

    def _hook(self, name: str) -> None:
        if self.fail_on == name:
            raise DeviceFaultError(f"{name} failed")
        self.calls.append(name)

    def on_configure(self, config_yaml: str) -> None:
        self._hook("configure")

    def on_arm(self, run_uuid: str) -> None:
        self._hook("arm")

    def on_start(self, run_uuid: str) -> None:
        self._hook("start")

    def on_stop(self) -> None:
        self._hook("stop")

    def on_disarm(self) -> None:
        self.safe_default_applied = True
        self._hook("disarm")

    def capabilities(self) -> lifecycle_pb2.Capabilities:
        return lifecycle_pb2.Capabilities(
            service_id="rec", firmware="0", driver_version="0"
        )


def _service() -> tuple[LifecycleService, _Recorder]:
    adapter = _Recorder()
    return LifecycleService(adapter, service_id="rec"), adapter


def test_configure_arm_start_calls_hooks_in_order() -> None:
    svc, adapter = _service()
    assert svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    assert svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok
    assert svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None).ok
    assert adapter.calls == ["configure", "arm", "start"]
    assert svc.fsm.state is DeviceState.RUNNING


def test_invalid_order_returns_error_and_skips_hook() -> None:
    svc, adapter = _service()
    resp = svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert not resp.ok and "invalid" in resp.error
    assert adapter.calls == []


def test_adapter_fault_moves_fsm_to_fault() -> None:
    svc, adapter = _service()
    adapter.fail_on = "arm"
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    resp = svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    assert not resp.ok
    assert svc.fsm.state is DeviceState.FAULT


def test_health_reports_state() -> None:
    svc, _ = _service()
    health = svc.Health(lifecycle_pb2.HealthRequest(), None)
    assert health.state == "UNINIT" and health.healthy


def test_noop_reissue_does_not_recall_hook() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert adapter.calls == ["configure"]


def test_configure_exact_replay_uses_cache_before_fsm() -> None:
    svc, adapter = _service()
    first = svc.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert first.ok
    assert svc.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None
    ).ok
    replay = svc.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert replay.ok == first.ok and replay.error == first.error
    assert adapter.calls == ["configure", "arm"]
    assert svc.fsm.state is DeviceState.ARMED


def test_arm_key_reuse_with_different_payload_rejected() -> None:
    svc, adapter = _service()
    svc.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert svc.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None
    ).ok
    resp = svc.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-1"), None
    )
    assert not resp.ok and resp.error == "idempotency_key_reused"
    assert adapter.calls == ["configure", "arm"]


def test_direct_disarm_from_running_applies_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert svc.fsm.state is DeviceState.UNINIT
    assert adapter.calls[-1] == "disarm"
    assert adapter.safe_default_applied


def test_stop_then_disarm_applies_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    svc.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    svc.Stop(lifecycle_pb2.StopRequest(), None)
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert svc.fsm.state is DeviceState.UNINIT
    assert adapter.calls[-2:] == ["stop", "disarm"]
    assert adapter.safe_default_applied


def test_disarm_reused_key_still_invokes_safe_default() -> None:
    svc, adapter = _service()
    svc.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg1", idempotency_key="cfg-1"),
        None,
    )
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None)
    svc.Start(
        lifecycle_pb2.StartRequest(run_uuid="r1", idempotency_key="start-1"), None
    )
    svc.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None)
    first_disarm_count = adapter.calls.count("disarm")
    svc.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg2", idempotency_key="cfg-2"),
        None,
    )
    svc.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-2"), None)
    svc.Start(
        lifecycle_pb2.StartRequest(run_uuid="r2", idempotency_key="start-2"), None
    )
    assert svc.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None).ok
    assert adapter.calls.count("disarm") == first_disarm_count + 1


def test_status_events_fan_out_to_all_subscribers() -> None:
    svc, _ = _service()
    s1 = svc.Status(lifecycle_pb2.StatusRequest(), None)
    s2 = svc.Status(lifecycle_pb2.StatusRequest(), None)
    next(s1)
    next(s2)
    svc.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert next(s1).kind == "transition"
    assert next(s2).kind == "transition"
