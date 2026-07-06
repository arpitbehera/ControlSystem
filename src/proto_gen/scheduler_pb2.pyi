import run_model_pb2 as _run_model_pb2
import lifecycle_pb2 as _lifecycle_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ListRunsRequest(_message.Message):
    __slots__ = ("limit",)
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    limit: int
    def __init__(self, limit: _Optional[int] = ...) -> None: ...

class RunRow(_message.Message):
    __slots__ = ("run_uuid", "state", "template_name", "user")
    RUN_UUID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_NAME_FIELD_NUMBER: _ClassVar[int]
    USER_FIELD_NUMBER: _ClassVar[int]
    run_uuid: str
    state: str
    template_name: str
    user: str
    def __init__(self, run_uuid: _Optional[str] = ..., state: _Optional[str] = ..., template_name: _Optional[str] = ..., user: _Optional[str] = ...) -> None: ...

class ListRunsResponse(_message.Message):
    __slots__ = ("runs",)
    RUNS_FIELD_NUMBER: _ClassVar[int]
    runs: _containers.RepeatedCompositeFieldContainer[RunRow]
    def __init__(self, runs: _Optional[_Iterable[_Union[RunRow, _Mapping]]] = ...) -> None: ...
