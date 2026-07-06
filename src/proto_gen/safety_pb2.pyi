from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class SafetyState(_message.Message):
    __slots__ = ("safe", "tripped", "detail")
    SAFE_FIELD_NUMBER: _ClassVar[int]
    TRIPPED_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    safe: bool
    tripped: _containers.RepeatedScalarFieldContainer[str]
    detail: str
    def __init__(self, safe: _Optional[bool] = ..., tripped: _Optional[_Iterable[str]] = ..., detail: _Optional[str] = ...) -> None: ...
