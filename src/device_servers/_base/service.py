"""Base LifecycleService: FSM + adapter hooks behind ManagedDevice gRPC."""

from __future__ import annotations

import abc
import hashlib
import json
import queue
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers._base.fsm import DeviceState, LifecycleFsm, Verb


class DeviceFaultError(Exception):
    """Raised by adapter hooks when device failure should move FSM to FAULT."""


class DeviceAdapter(abc.ABC):
    @abc.abstractmethod
    def on_configure(self, config_yaml: str) -> None: ...

    @abc.abstractmethod
    def on_arm(self, run_uuid: str) -> None: ...

    @abc.abstractmethod
    def on_start(self, run_uuid: str) -> None: ...

    @abc.abstractmethod
    def on_stop(self) -> None: ...

    @abc.abstractmethod
    def on_disarm(self) -> None: ...

    @abc.abstractmethod
    def capabilities(self) -> lifecycle_pb2.Capabilities: ...


_CACHEABLE_VERBS = {Verb.CONFIGURE, Verb.ARM, Verb.START}


def _payload_hash(*parts: str) -> bytes:
    canonical = json.dumps(parts, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()


class LifecycleService(lifecycle_pb2_grpc.ManagedDeviceServicer):
    def __init__(self, adapter: DeviceAdapter, service_id: str) -> None:
        self.adapter = adapter
        self.service_id = service_id
        self.fsm = LifecycleFsm()
        self._subscribers: set[queue.Queue[lifecycle_pb2.StatusEvent]] = set()
        self._subscribers_lock = threading.Lock()
        self._idempotency: dict[tuple[Verb, str], tuple[bytes, bool, str]] = {}
        self._idempotency_lock = threading.Lock()

    def _event(self, kind: str, detail: str = "") -> lifecycle_pb2.StatusEvent:
        return lifecycle_pb2.StatusEvent(
            service_id=self.service_id,
            state=self.fsm.state.value,
            kind=kind,
            detail=detail,
            wall_ns=time.time_ns(),
        )

    def _emit(self, kind: str, detail: str = "") -> None:
        event = self._event(kind, detail)
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def _do(
        self,
        verb: Verb,
        idempotency_key: str,
        request_hash: bytes,
        hook: Callable[..., None],
        *args: Any,
    ) -> tuple[bool, str]:
        cache_key = (
            (verb, idempotency_key)
            if idempotency_key and verb in _CACHEABLE_VERBS
            else None
        )
        if cache_key is not None:
            with self._idempotency_lock:
                cached = self._idempotency.get(cache_key)
            if cached is not None:
                cached_hash, cached_ok, cached_error = cached
                if cached_hash != request_hash:
                    return False, "idempotency_key_reused"
                return cached_ok, cached_error

        transition = self.fsm.apply(verb)
        if not transition.ok:
            ok, error = False, transition.error or "invalid transition"
        elif transition.noop:
            ok, error = True, ""
        else:
            try:
                hook(*args)
            except DeviceFaultError as exc:
                self.fsm.fault(str(exc))
                self._emit("fault", str(exc))
                ok, error = False, str(exc)
            else:
                self._emit("transition", verb.value)
                ok, error = True, ""

        if cache_key is not None:
            with self._idempotency_lock:
                self._idempotency[cache_key] = (request_hash, ok, error)
        return ok, error

    def Health(
        self, request: lifecycle_pb2.HealthRequest, context: Any
    ) -> lifecycle_pb2.HealthResponse:
        return lifecycle_pb2.HealthResponse(
            service_id=self.service_id,
            state=self.fsm.state.value,
            healthy=self.fsm.state is not DeviceState.FAULT,
        )

    def Capabilities(
        self, request: lifecycle_pb2.Empty, context: Any
    ) -> lifecycle_pb2.Capabilities:
        return self.adapter.capabilities()

    def Configure(
        self, request: lifecycle_pb2.ConfigureRequest, context: Any
    ) -> lifecycle_pb2.ConfigureResponse:
        ok, error = self._do(
            Verb.CONFIGURE,
            request.idempotency_key,
            _payload_hash(request.config_yaml),
            self.adapter.on_configure,
            request.config_yaml,
        )
        return lifecycle_pb2.ConfigureResponse(ok=ok, error=error)

    def Arm(
        self, request: lifecycle_pb2.ArmRequest, context: Any
    ) -> lifecycle_pb2.ArmResponse:
        ok, error = self._do(
            Verb.ARM,
            request.idempotency_key,
            _payload_hash(request.run_uuid),
            self.adapter.on_arm,
            request.run_uuid,
        )
        return lifecycle_pb2.ArmResponse(ok=ok, error=error)

    def Start(
        self, request: lifecycle_pb2.StartRequest, context: Any
    ) -> lifecycle_pb2.StartResponse:
        ok, error = self._do(
            Verb.START,
            request.idempotency_key,
            _payload_hash(request.run_uuid),
            self.adapter.on_start,
            request.run_uuid,
        )
        return lifecycle_pb2.StartResponse(ok=ok, error=error)

    def Stop(
        self, request: lifecycle_pb2.StopRequest, context: Any
    ) -> lifecycle_pb2.StopResponse:
        ok, error = self._do(
            Verb.STOP, request.idempotency_key, b"", self.adapter.on_stop
        )
        return lifecycle_pb2.StopResponse(ok=ok, error=error)

    def Disarm(
        self, request: lifecycle_pb2.DisarmRequest, context: Any
    ) -> lifecycle_pb2.DisarmResponse:
        ok, error = self._do(
            Verb.DISARM, request.idempotency_key, b"", self.adapter.on_disarm
        )
        return lifecycle_pb2.DisarmResponse(ok=ok, error=error)

    def Status(
        self, request: lifecycle_pb2.StatusRequest, context: Any
    ) -> Iterator[lifecycle_pb2.StatusEvent]:
        events: queue.Queue[lifecycle_pb2.StatusEvent] = queue.Queue()
        with self._subscribers_lock:
            self._subscribers.add(events)
        try:
            yield self._event("heartbeat")
            while context is None or context.is_active():
                try:
                    yield events.get(timeout=1.0)
                except queue.Empty:
                    yield self._event("heartbeat")
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(events)
