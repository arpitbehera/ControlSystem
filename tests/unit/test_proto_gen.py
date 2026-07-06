def test_lifecycle_service_generated() -> None:
    from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

    assert hasattr(lifecycle_pb2_grpc, "ManagedDeviceStub")
    assert hasattr(lifecycle_pb2_grpc, "ManagedDeviceServicer")
    ev = lifecycle_pb2.StatusEvent(service_id="x", state="UNINIT", kind="heartbeat")
    assert ev.service_id == "x"


def test_run_model_generated() -> None:
    from proto_gen import run_model_pb2

    req = run_model_pb2.RunRequest(user="op", template_name="t", idempotency_key="k1")
    assert req.template_name == "t"
