"""Fake EMCCD camera: contract-complete, zero hardware."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from proto_gen import lifecycle_pb2

from device_servers._base.service import DeviceAdapter


class FakeCameraAdapter(DeviceAdapter):
    def __init__(self, width: int = 256, height: int = 256, seed: int = 0) -> None:
        self._width = width
        self._height = height
        self._rng = np.random.default_rng(seed)
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
            service_id="fake_camera",
            firmware="fake-1.0",
            driver_version="fake-1.0",
            camera=lifecycle_pb2.CameraCapabilities(
                sensor_width=self._width,
                sensor_height=self._height,
                trigger_modes=["external"],
            ),
        )

    def snap(self) -> npt.NDArray[np.uint16]:
        return self._rng.integers(0, 4096, (self._height, self._width), dtype=np.uint16)
