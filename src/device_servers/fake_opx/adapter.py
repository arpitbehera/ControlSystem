"""Fake OPX lifecycle shell: contract-complete, zero QM SDK dependency."""

from __future__ import annotations

from proto_gen import lifecycle_pb2

from device_servers._base.service import DeviceAdapter


class FakeOpxAdapter(DeviceAdapter):
    def __init__(self) -> None:
        self._armed_run: str | None = None
        self.configure_count = 0
        self.arm_count = 0
        self.safe_default_count = 0

    def on_configure(self, config_yaml: str) -> None:
        self.configure_count += 1

    def on_arm(self, run_uuid: str) -> None:
        self.arm_count += 1
        self._armed_run = run_uuid

    def on_start(self, run_uuid: str) -> None:
        pass

    def on_stop(self) -> None:
        pass

    def on_disarm(self) -> None:
        self._armed_run = None
        self.safe_default_count += 1

    def capabilities(self) -> lifecycle_pb2.Capabilities:
        return lifecycle_pb2.Capabilities(
            service_id="fake_opx",
            firmware="fake-qop",
            driver_version="fake-qm-sdk",
            opx=lifecycle_pb2.OpxCapabilities(
                qop_version="fake",
                analog_outputs=["aod_x", "aod_y"],
                digital_outputs=["aod_enable", "camera_trigger"],
            ),
        )
