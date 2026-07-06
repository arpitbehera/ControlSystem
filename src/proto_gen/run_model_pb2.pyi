from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RunRequest(_message.Message):
    __slots__ = ("user", "template_name", "parameters_json", "required_calibration", "requested_descriptor_id", "idempotency_key")
    USER_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_NAME_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_JSON_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_DESCRIPTOR_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    user: str
    template_name: str
    parameters_json: str
    required_calibration: _containers.RepeatedScalarFieldContainer[str]
    requested_descriptor_id: int
    idempotency_key: str
    def __init__(self, user: _Optional[str] = ..., template_name: _Optional[str] = ..., parameters_json: _Optional[str] = ..., required_calibration: _Optional[_Iterable[str]] = ..., requested_descriptor_id: _Optional[int] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class AcceptedJob(_message.Message):
    __slots__ = ("job_uuid", "request", "descriptor_id", "snapshot_id", "submitted_at", "request_hash")
    JOB_UUID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTOR_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    SUBMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    REQUEST_HASH_FIELD_NUMBER: _ClassVar[int]
    job_uuid: str
    request: RunRequest
    descriptor_id: int
    snapshot_id: int
    submitted_at: str
    request_hash: bytes
    def __init__(self, job_uuid: _Optional[str] = ..., request: _Optional[_Union[RunRequest, _Mapping]] = ..., descriptor_id: _Optional[int] = ..., snapshot_id: _Optional[int] = ..., submitted_at: _Optional[str] = ..., request_hash: _Optional[bytes] = ...) -> None: ...

class Rejection(_message.Message):
    __slots__ = ("code", "reason")
    CODE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    code: str
    reason: str
    def __init__(self, code: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class EnqueueResponse(_message.Message):
    __slots__ = ("accepted", "rejected")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    REJECTED_FIELD_NUMBER: _ClassVar[int]
    accepted: AcceptedJob
    rejected: Rejection
    def __init__(self, accepted: _Optional[_Union[AcceptedJob, _Mapping]] = ..., rejected: _Optional[_Union[Rejection, _Mapping]] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("target", "target_kind", "requested_by", "reason", "idempotency_key")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    TARGET_KIND_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_BY_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    target: str
    target_kind: str
    requested_by: str
    reason: str
    idempotency_key: str
    def __init__(self, target: _Optional[str] = ..., target_kind: _Optional[str] = ..., requested_by: _Optional[str] = ..., reason: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ("ok", "state", "error")
    OK_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    state: str
    error: str
    def __init__(self, ok: _Optional[bool] = ..., state: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class RunSummary(_message.Message):
    __slots__ = ("run_uuid", "status", "shot_count", "shots_ok", "duration_s", "snapshot_id", "descriptor_id", "execution_bundle_id", "durability_tier", "notes")
    RUN_UUID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SHOT_COUNT_FIELD_NUMBER: _ClassVar[int]
    SHOTS_OK_FIELD_NUMBER: _ClassVar[int]
    DURATION_S_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTOR_ID_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_BUNDLE_ID_FIELD_NUMBER: _ClassVar[int]
    DURABILITY_TIER_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    run_uuid: str
    status: str
    shot_count: int
    shots_ok: int
    duration_s: float
    snapshot_id: int
    descriptor_id: int
    execution_bundle_id: int
    durability_tier: str
    notes: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, run_uuid: _Optional[str] = ..., status: _Optional[str] = ..., shot_count: _Optional[int] = ..., shots_ok: _Optional[int] = ..., duration_s: _Optional[float] = ..., snapshot_id: _Optional[int] = ..., descriptor_id: _Optional[int] = ..., execution_bundle_id: _Optional[int] = ..., durability_tier: _Optional[str] = ..., notes: _Optional[_Iterable[str]] = ...) -> None: ...
