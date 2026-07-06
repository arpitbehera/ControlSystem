.PHONY: proto
proto:
	uv run python -m grpc_tools.protoc -Iproto \
	  --python_out=src/proto_gen --grpc_python_out=src/proto_gen --pyi_out=src/proto_gen \
	  proto/lifecycle.proto proto/run_model.proto proto/scheduler.proto proto/safety.proto
	uv run python -c "import pathlib,re; \
	  [p.write_text(re.sub(r'^import (\w+_pb2)', r'from proto_gen import \\1', p.read_text(), flags=re.M)) \
	   for p in pathlib.Path('src/proto_gen').glob('*_pb2*.py')]"
