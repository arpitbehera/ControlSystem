import grpc

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers.fake_opx.main import serve


def test_fake_opx_lifecycle_over_real_grpc() -> None:
    server = serve(50062)
    try:
        channel = grpc.insecure_channel("127.0.0.1:50062")
        stub = lifecycle_pb2_grpc.ManagedDeviceStub(channel)
        health = stub.Health(lifecycle_pb2.HealthRequest(), timeout=5)
        assert health.state == "UNINIT"
        caps = stub.Capabilities(lifecycle_pb2.Empty(), timeout=5)
        assert caps.WhichOneof("specific") == "opx"
        assert "aod_x" in caps.opx.analog_outputs
    finally:
        server.stop(grace=None)
