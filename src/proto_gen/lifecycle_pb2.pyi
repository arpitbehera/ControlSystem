from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("service_id", "state", "healthy", "detail")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    state: str
    healthy: bool
    detail: str
    def __init__(self, service_id: _Optional[str] = ..., state: _Optional[str] = ..., healthy: _Optional[bool] = ..., detail: _Optional[str] = ...) -> None: ...

class TimingHint(_message.Message):
    __slots__ = ("name", "value")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    name: str
    value: str
    def __init__(self, name: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class CameraCapabilities(_message.Message):
    __slots__ = ("sensor_width", "sensor_height", "trigger_modes")
    SENSOR_WIDTH_FIELD_NUMBER: _ClassVar[int]
    SENSOR_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_MODES_FIELD_NUMBER: _ClassVar[int]
    sensor_width: int
    sensor_height: int
    trigger_modes: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, sensor_width: _Optional[int] = ..., sensor_height: _Optional[int] = ..., trigger_modes: _Optional[_Iterable[str]] = ...) -> None: ...

class SlmCapabilities(_message.Message):
    __slots__ = ("width", "height", "refresh_ms")
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    REFRESH_MS_FIELD_NUMBER: _ClassVar[int]
    width: int
    height: int
    refresh_ms: float
    def __init__(self, width: _Optional[int] = ..., height: _Optional[int] = ..., refresh_ms: _Optional[float] = ...) -> None: ...

class OpxCapabilities(_message.Message):
    __slots__ = ("qop_version", "analog_outputs", "digital_outputs")
    QOP_VERSION_FIELD_NUMBER: _ClassVar[int]
    ANALOG_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    DIGITAL_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    qop_version: str
    analog_outputs: _containers.RepeatedScalarFieldContainer[str]
    digital_outputs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, qop_version: _Optional[str] = ..., analog_outputs: _Optional[_Iterable[str]] = ..., digital_outputs: _Optional[_Iterable[str]] = ...) -> None: ...

class Capabilities(_message.Message):
    __slots__ = ("service_id", "firmware", "driver_version", "timing", "camera", "slm", "opx")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    FIRMWARE_FIELD_NUMBER: _ClassVar[int]
    DRIVER_VERSION_FIELD_NUMBER: _ClassVar[int]
    TIMING_FIELD_NUMBER: _ClassVar[int]
    CAMERA_FIELD_NUMBER: _ClassVar[int]
    SLM_FIELD_NUMBER: _ClassVar[int]
    OPX_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    firmware: str
    driver_version: str
    timing: _containers.RepeatedCompositeFieldContainer[TimingHint]
    camera: CameraCapabilities
    slm: SlmCapabilities
    opx: OpxCapabilities
    def __init__(self, service_id: _Optional[str] = ..., firmware: _Optional[str] = ..., driver_version: _Optional[str] = ..., timing: _Optional[_Iterable[_Union[TimingHint, _Mapping]]] = ..., camera: _Optional[_Union[CameraCapabilities, _Mapping]] = ..., slm: _Optional[_Union[SlmCapabilities, _Mapping]] = ..., opx: _Optional[_Union[OpxCapabilities, _Mapping]] = ...) -> None: ...

class ConfigureRequest(_message.Message):
    __slots__ = ("config_yaml", "idempotency_key")
    CONFIG_YAML_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    config_yaml: str
    idempotency_key: str
    def __init__(self, config_yaml: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class ConfigureResponse(_message.Message):
    __slots__ = ("ok", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error: str
    def __init__(self, ok: _Optional[bool] = ..., error: _Optional[str] = ...) -> None: ...

class ArmRequest(_message.Message):
    __slots__ = ("run_uuid", "idempotency_key")
    RUN_UUID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    run_uuid: str
    idempotency_key: str
    def __init__(self, run_uuid: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class ArmResponse(_message.Message):
    __slots__ = ("ok", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error: str
    def __init__(self, ok: _Optional[bool] = ..., error: _Optional[str] = ...) -> None: ...

class StartRequest(_message.Message):
    __slots__ = ("run_uuid", "idempotency_key")
    RUN_UUID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    run_uuid: str
    idempotency_key: str
    def __init__(self, run_uuid: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class StartResponse(_message.Message):
    __slots__ = ("ok", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error: str
    def __init__(self, ok: _Optional[bool] = ..., error: _Optional[str] = ...) -> None: ...

class StopRequest(_message.Message):
    __slots__ = ("idempotency_key",)
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    idempotency_key: str
    def __init__(self, idempotency_key: _Optional[str] = ...) -> None: ...

class StopResponse(_message.Message):
    __slots__ = ("ok", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error: str
    def __init__(self, ok: _Optional[bool] = ..., error: _Optional[str] = ...) -> None: ...

class DisarmRequest(_message.Message):
    __slots__ = ("idempotency_key",)
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    idempotency_key: str
    def __init__(self, idempotency_key: _Optional[str] = ...) -> None: ...

class DisarmResponse(_message.Message):
    __slots__ = ("ok", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    error: str
    def __init__(self, ok: _Optional[bool] = ..., error: _Optional[str] = ...) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusEvent(_message.Message):
    __slots__ = ("service_id", "state", "kind", "detail", "wall_ns")
    SERVICE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    WALL_NS_FIELD_NUMBER: _ClassVar[int]
    service_id: str
    state: str
    kind: str
    detail: str
    wall_ns: int
    def __init__(self, service_id: _Optional[str] = ..., state: _Optional[str] = ..., kind: _Optional[str] = ..., detail: _Optional[str] = ..., wall_ns: _Optional[int] = ...) -> None: ...
