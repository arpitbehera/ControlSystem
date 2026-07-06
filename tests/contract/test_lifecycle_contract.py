"""Lifecycle contract every managed device service must pass."""

from typing import Any

from proto_gen import lifecycle_pb2

from device_servers._base.fsm import DeviceState
from device_servers._base.service import LifecycleService


def test_initial_state_is_uninit_and_healthy(service: LifecycleService) -> None:
    health = service.Health(lifecycle_pb2.HealthRequest(), None)
    assert health.state == "UNINIT" and health.healthy


def test_capabilities_are_typed_and_identified(service: LifecycleService) -> None:
    caps = service.Capabilities(lifecycle_pb2.Empty(), None)
    assert caps.service_id != ""
    assert caps.WhichOneof("specific") is not None


def test_full_verb_cycle(service: LifecycleService) -> None:
    assert service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok
    assert service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None).ok
    assert service.Stop(lifecycle_pb2.StopRequest(), None).ok
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT


def test_verbs_are_idempotent(service: LifecycleService) -> None:
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    assert service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None).ok
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    assert service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None).ok


def test_out_of_order_verb_is_typed_error_not_crash(service: LifecycleService) -> None:
    resp = service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert not resp.ok and resp.error != ""


def test_disarm_forces_reconfigure(service: LifecycleService) -> None:
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Disarm(lifecycle_pb2.DisarmRequest(), None)
    assert not service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2"), None).ok


def test_configure_exact_replay_uses_cache_before_fsm(service_case: Any) -> None:
    service = service_case.service
    first = service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert first.ok
    assert service.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None
    ).ok
    before = service_case.configure_count()
    replay = service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert replay.ok == first.ok and replay.error == first.error
    assert service_case.configure_count() == before
    assert service.fsm.state is DeviceState.ARMED


def test_arm_key_reuse_with_different_payload_rejected(service_case: Any) -> None:
    service = service_case.service
    service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg", idempotency_key="cfg-1"), None
    )
    assert service.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None
    ).ok
    before = service_case.arm_count()
    resp = service.Arm(
        lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-1"), None
    )
    assert not resp.ok and resp.error == "idempotency_key_reused"
    assert service_case.arm_count() == before


def test_direct_disarm_from_running_applies_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT
    assert service_case.safe_default_count() >= 1
    assert not service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2"), None).ok


def test_stop_then_disarm_applies_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(lifecycle_pb2.ConfigureRequest(config_yaml=""), None)
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1"), None)
    service.Start(lifecycle_pb2.StartRequest(run_uuid="r1"), None)
    service.Stop(lifecycle_pb2.StopRequest(), None)
    assert service.Disarm(lifecycle_pb2.DisarmRequest(), None).ok
    assert service.fsm.state is DeviceState.UNINIT
    assert service_case.safe_default_count() >= 1


def test_disarm_reused_key_still_invokes_safe_default(service_case: Any) -> None:
    service = service_case.service
    service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg1", idempotency_key="cfg-1"),
        None,
    )
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r1", idempotency_key="arm-1"), None)
    service.Start(
        lifecycle_pb2.StartRequest(run_uuid="r1", idempotency_key="start-1"), None
    )
    service.Disarm(lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None)
    first_disarm_count = service_case.safe_default_count()
    service.Configure(
        lifecycle_pb2.ConfigureRequest(config_yaml="cfg2", idempotency_key="cfg-2"),
        None,
    )
    service.Arm(lifecycle_pb2.ArmRequest(run_uuid="r2", idempotency_key="arm-2"), None)
    service.Start(
        lifecycle_pb2.StartRequest(run_uuid="r2", idempotency_key="start-2"), None
    )
    assert service.Disarm(
        lifecycle_pb2.DisarmRequest(idempotency_key="disarm-1"), None
    ).ok
    assert service_case.safe_default_count() == first_disarm_count + 1
