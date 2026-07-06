import grpc

from proto_gen import lifecycle_pb2, lifecycle_pb2_grpc

from device_servers.fake_camera.main import serve


def test_fake_camera_over_real_grpc() -> None:
    server = serve(50061)
    try:
        channel = grpc.insecure_channel("127.0.0.1:50061")
        stub = lifecycle_pb2_grpc.ManagedDeviceStub(channel)
        health = stub.Health(lifecycle_pb2.HealthRequest(), timeout=5)
        assert health.state == "UNINIT"
        caps = stub.Capabilities(lifecycle_pb2.Empty(), timeout=5)
        assert caps.camera.sensor_width == 256
    finally:
        server.stop(grace=None)
