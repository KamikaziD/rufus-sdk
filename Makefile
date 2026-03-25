.PHONY: proto proto-protoc proto-clean test

# Generate Python code from .proto files using buf CLI
# Install buf: https://buf.build/docs/installation
# Alternative: use make proto-protoc if buf is unavailable
proto:
	buf generate --path src/rufus/proto

# Generate _pb2.py files using local protoc (fallback when buf is unavailable)
# Requires protoc 3.19+: https://github.com/protocolbuffers/protobuf/releases
proto-protoc:
	protoc --python_out=src/rufus/proto/gen \
	       --proto_path=src/rufus/proto \
	       src/rufus/proto/edge.proto \
	       src/rufus/proto/workflow.proto \
	       src/rufus/proto/events.proto

proto-clean:
	rm -rf src/rufus/proto/gen

test:
	pytest tests/ -x -q

benchmark-proto:
	python tests/benchmarks/benchmark_proto.py
