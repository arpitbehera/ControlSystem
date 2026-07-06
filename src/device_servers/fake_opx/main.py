"""Standalone fake OPX lifecycle service: no QM SDK, no RtJobResult path."""

from __future__ import annotations

import argparse
from concurrent import futures

import grpc

from proto_gen import lifecycle_pb2_grpc

from device_servers._base.service import LifecycleService
from device_servers.fake_opx.adapter import FakeOpxAdapter


def serve(port: int) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    service = LifecycleService(FakeOpxAdapter(), service_id="fake_opx")
    lifecycle_pb2_grpc.add_ManagedDeviceServicer_to_server(service, server)  # type: ignore[no-untyped-call]
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50062)
    args = parser.parse_args()
    serve(args.port).wait_for_termination()
