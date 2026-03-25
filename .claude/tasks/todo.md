# NATS JetStream + Protobuf — Hyperdrive to Teleport

## Phase 1 — Proto Schema Layer
- [x] Add `nats` extra to pyproject.toml (root + sub-packages)
- [x] Create buf.yaml, buf.gen.yaml, Makefile
- [x] Create src/rufus/proto/workflow.proto
- [x] Create src/rufus/proto/edge.proto
- [x] Create src/rufus/proto/events.proto
- [x] Update serialization.py — encode_proto, decode_proto, pack_message, unpack_message, get_backend()
- [x] Create tests/benchmarks/benchmark_proto.py

## Phase 2 — EdgeTransport Abstraction + NATS Edge Transport
- [x] Create src/rufus_edge/transport/base.py (Protocol)
- [x] Create src/rufus_edge/transport/http_transport.py
- [x] Create src/rufus_edge/transport/nats_transport.py
- [x] Create src/rufus_edge/transport/__init__.py (factory)
- [x] Modify agent.py — nats_url param, wire _transport, update _send_heartbeat(), start(), stop()
- [x] Create src/rufus_server/nats_bridge.py
- [x] Create docker/nats/nats.conf
- [x] Update docker-compose.test-async.yml

## Phase 3 — NATS Execution Provider + Event Observer
- [x] Create src/rufus/implementations/execution/nats_executor.py
- [x] Create src/rufus/implementations/workers/nats_worker.py
- [x] Create src/rufus/implementations/workers/nats_worker_cli.py
- [x] Create src/rufus/implementations/observability/nats_events.py

## Phase 4 — Proto Wire Encoding
- [x] pack_message/unpack_message in serialization.py (done in Phase 1)
- [x] NATSEdgeTransport uses proto encoding
- [x] NATSBridge decodes proto

## Phase 5 — Dashboard NATS WebSocket
- [x] Create packages/rufus-dashboard/src/lib/nats-client.ts
- [x] Update packages/rufus-dashboard/package.json

## Phase 6 — google.protobuf Codec Backend
- [x] buf.gen.yaml — add protocolbuffers/python:v28 plugin
- [x] pyproject.toml — add protobuf>=4.21 to nats extra
- [x] src/rufus/proto/gen/__init__.py — backend-conditional re-exports (google/betterproto)
- [x] serialization.py — duck-type encode_proto/decode_proto (SerializeToString/FromString)
- [x] serialization.py — pack_message/unpack_message use encode_proto/decode_proto
- [x] tests/benchmarks/benchmark_proto.py — add google.protobuf benchmark block

## Tier 1 — Quick Wins
- [x] device_service._get_pending_commands() — batch UPDATE (1 round-trip vs N)
- [~] device_service.sync_transactions() — transaction wrap SKIPPED: per-row try/except
      breaks if wrapped in single asyncpg transaction (partial success semantics lost)

## Review
- [x] 234 tests pass (tests/sdk + tests/edge excl. pre-existing hung test_agent_wasm_integration.py)
- [x] get_backend() → "orjson+msgspec+proto"
- [x] benchmark: google.protobuf 50× faster encode than betterproto, same wire size
- [x] _pb2.py generated via protoc (buf not available; protoc at /Users/kim/PycharmProjects/tazamaRTC/protoc-28.2/bin/protoc)
- [ ] Verify NATS transport active when RUFUS_NATS_URL is set
