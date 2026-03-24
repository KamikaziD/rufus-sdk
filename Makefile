.PHONY: proto proto-clean test

# Generate Python code from .proto files using buf CLI
# Install buf: https://buf.build/docs/installation
proto:
	buf generate src/rufus/proto

proto-clean:
	rm -rf src/rufus/proto/gen

test:
	pytest tests/ -x -q

benchmark-proto:
	python tests/benchmarks/benchmark_proto.py
