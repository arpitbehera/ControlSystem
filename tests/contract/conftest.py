from collections.abc import Callable
from dataclasses import dataclass

import pytest

from device_servers._base.service import LifecycleService


@dataclass(frozen=True)
class ServiceCase:
    service: LifecycleService
    configure_count: Callable[[], int]
    arm_count: Callable[[], int]
    safe_default_count: Callable[[], int]


def _fake_camera() -> ServiceCase:
    from device_servers.fake_camera.adapter import FakeCameraAdapter

    adapter = FakeCameraAdapter()
    return ServiceCase(
        service=LifecycleService(adapter, service_id="fake_camera"),
        configure_count=lambda: adapter.configure_count,
        arm_count=lambda: adapter.arm_count,
        safe_default_count=lambda: adapter.safe_default_count,
    )


def _fake_opx() -> ServiceCase:
    from device_servers.fake_opx.adapter import FakeOpxAdapter

    adapter = FakeOpxAdapter()
    return ServiceCase(
        service=LifecycleService(adapter, service_id="fake_opx"),
        configure_count=lambda: adapter.configure_count,
        arm_count=lambda: adapter.arm_count,
        safe_default_count=lambda: adapter.safe_default_count,
    )


SERVICE_FACTORIES: dict[str, Callable[[], ServiceCase]] = {
    "fake_camera": _fake_camera,
    "fake_opx": _fake_opx,
}


@pytest.fixture(params=sorted(SERVICE_FACTORIES))
def service_case(request: pytest.FixtureRequest) -> ServiceCase:
    return SERVICE_FACTORIES[request.param]()


@pytest.fixture
def service(service_case: ServiceCase) -> LifecycleService:
    return service_case.service
