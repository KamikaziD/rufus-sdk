"""
Standalone proto vs JSON benchmark — no pytest required.

Run: python tests/benchmarks/benchmark_proto.py

Expected results (approximate):
  HeartbeatMsg  JSON=287B  proto=48B   (6.0x)
  WorkflowRecord JSON=4.2KB proto=690B  (6.1x)
"""
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

ITERATIONS = 10_000


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

HEARTBEAT_DICT = {
    "device_id": "pos-terminal-001",
    "device_status": "online",
    "pending_sync_count": 3,
    "last_sync_at": "2026-03-24T12:34:56.789Z",
    "config_version": "v1.0.0rc6",
    "sdk_version": "1.0.0rc6",
    "sent_at": "2026-03-24T12:35:00.000Z",
}

WORKFLOW_RECORD_DICT = {
    "id": "wf_abc123def456",
    "workflow_type": "PaymentAuthorization",
    "status": "COMPLETED",
    "current_step": 5,
    "state_json": '{"transaction_id":"txn_001","amount":99.99,"currency":"USD","card_last_four":"4242","merchant_id":"merch_xyz","status":"APPROVED","authorized_at":"2026-03-24T12:34:56Z","approval_code":"AUTH123","risk_score":0.12,"is_online":true}',
    "owner_id": "pos-terminal-001",
    "created_at": "2026-03-24T12:34:50.000Z",
    "updated_at": "2026-03-24T12:34:56.789Z",
    "current_step_name": "FinalizePayment",
    "parent_execution_id": "",
    "data_region": "us-east-1",
}


def _bench(label: str, encode_fn, decode_fn, sample_bytes: bytes):
    # Encode
    t0 = time.perf_counter()
    for _ in range(ITERATIONS):
        encoded = encode_fn()
    encode_ms = (time.perf_counter() - t0) * 1000

    encoded = encode_fn()
    size = len(encoded)

    # Decode
    t0 = time.perf_counter()
    for _ in range(ITERATIONS):
        decode_fn(encoded)
    decode_ms = (time.perf_counter() - t0) * 1000

    return size, encode_ms, decode_ms


def main():
    results = []

    # --- orjson baseline ---
    try:
        import orjson

        size_hb, enc_hb, dec_hb = _bench(
            "HeartbeatMsg (orjson)",
            lambda: orjson.dumps(HEARTBEAT_DICT),
            lambda d: orjson.loads(d),
            b"",
        )
        size_wf, enc_wf, dec_wf = _bench(
            "WorkflowRecord (orjson)",
            lambda: orjson.dumps(WORKFLOW_RECORD_DICT),
            lambda d: orjson.loads(d),
            b"",
        )
        results.append(("HeartbeatMsg", "orjson (JSON)", size_hb, enc_hb, dec_hb))
        results.append(("WorkflowRecord", "orjson (JSON)", size_wf, enc_wf, dec_wf))
    except ImportError:
        import json
        size_hb = len(json.dumps(HEARTBEAT_DICT).encode())
        size_wf = len(json.dumps(WORKFLOW_RECORD_DICT).encode())
        results.append(("HeartbeatMsg", "json (stdlib)", size_hb, 0, 0))
        results.append(("WorkflowRecord", "json (stdlib)", size_wf, 0, 0))

    # --- betterproto ---
    try:
        # Try generated code first (import directly from module, not via backend switch)
        try:
            from rufus.proto.gen.edge import HeartbeatMsg  # type: ignore
            from rufus.proto.gen.workflow import WorkflowRecord  # type: ignore

            hb = HeartbeatMsg(**{k: v for k, v in HEARTBEAT_DICT.items() if k != "pending_sync_count"},
                               pending_sync_count=HEARTBEAT_DICT["pending_sync_count"])
            wf_state = WORKFLOW_RECORD_DICT.copy()
            wf_state.pop("status")  # status is enum in proto
            wf = WorkflowRecord(**wf_state)

            size_hb_p, enc_hb_p, dec_hb_p = _bench(
                "HeartbeatMsg (proto)",
                lambda: bytes(hb),
                lambda d: HeartbeatMsg().parse(d),
                b"",
            )
            size_wf_p, enc_wf_p, dec_wf_p = _bench(
                "WorkflowRecord (proto)",
                lambda: bytes(wf),
                lambda d: WorkflowRecord().parse(d),
                b"",
            )
            results.append(("HeartbeatMsg", "betterproto", size_hb_p, enc_hb_p, dec_hb_p))
            results.append(("WorkflowRecord", "betterproto", size_wf_p, enc_wf_p, dec_wf_p))

        except ImportError:
            # Generated code not yet built — define inline using standard dataclasses
            import betterproto
            import dataclasses

            @dataclasses.dataclass
            class _HB(betterproto.Message):
                device_id: str = betterproto.string_field(1)
                device_status: str = betterproto.string_field(2)
                pending_sync_count: int = betterproto.int32_field(3)
                last_sync_at: str = betterproto.string_field(4)
                config_version: str = betterproto.string_field(5)
                sdk_version: str = betterproto.string_field(6)
                sent_at: str = betterproto.string_field(7)

            @dataclasses.dataclass
            class _WF(betterproto.Message):
                id: str = betterproto.string_field(1)
                workflow_type: str = betterproto.string_field(2)
                status: str = betterproto.string_field(3)
                current_step: int = betterproto.int32_field(4)
                state_json: str = betterproto.string_field(5)
                owner_id: str = betterproto.string_field(6)
                created_at: str = betterproto.string_field(7)
                updated_at: str = betterproto.string_field(8)
                current_step_name: str = betterproto.string_field(9)
                parent_execution_id: str = betterproto.string_field(10)
                data_region: str = betterproto.string_field(11)

            hb = _HB(**HEARTBEAT_DICT)
            wf = _WF(**WORKFLOW_RECORD_DICT)

            size_hb_p, enc_hb_p, dec_hb_p = _bench(
                "HeartbeatMsg (proto)",
                lambda: bytes(hb),
                lambda d: _HB().parse(d),
                b"",
            )
            size_wf_p, enc_wf_p, dec_wf_p = _bench(
                "WorkflowRecord (proto)",
                lambda: bytes(wf),
                lambda d: _WF().parse(d),
                b"",
            )
            results.append(("HeartbeatMsg", "betterproto (inline)", size_hb_p, enc_hb_p, dec_hb_p))
            results.append(("WorkflowRecord", "betterproto (inline)", size_wf_p, enc_wf_p, dec_wf_p))

    except ImportError:
        print("betterproto not installed — proto results skipped (pip install betterproto)")

    # --- google.protobuf (_pb2) ---
    try:
        _prev_backend = os.environ.get("RUFUS_PROTO_BACKEND")
        os.environ["RUFUS_PROTO_BACKEND"] = "google"
        try:
            from rufus.proto.gen.edge_pb2 import HeartbeatMsg as HB_pb  # type: ignore
            from rufus.proto.gen.workflow_pb2 import WorkflowRecord as WR_pb  # type: ignore

            hb_pb = HB_pb(
                device_id=HEARTBEAT_DICT["device_id"],
                device_status=HEARTBEAT_DICT["device_status"],
                pending_sync_count=HEARTBEAT_DICT["pending_sync_count"],
                last_sync_at=HEARTBEAT_DICT["last_sync_at"],
                config_version=HEARTBEAT_DICT["config_version"],
                sdk_version=HEARTBEAT_DICT["sdk_version"],
                sent_at=HEARTBEAT_DICT["sent_at"],
            )
            wf_state = {k: v for k, v in WORKFLOW_RECORD_DICT.items() if k != "status"}
            # state_json is a bytes field in proto — encode str to bytes
            if "state_json" in wf_state and isinstance(wf_state["state_json"], str):
                wf_state["state_json"] = wf_state["state_json"].encode()
            wf_pb = WR_pb(**wf_state)

            size_hb_g, enc_hb_g, dec_hb_g = _bench(
                "HeartbeatMsg (google.protobuf)",
                lambda: hb_pb.SerializeToString(),
                lambda d: HB_pb.FromString(d),
                b"",
            )
            size_wf_g, enc_wf_g, dec_wf_g = _bench(
                "WorkflowRecord (google.protobuf)",
                lambda: wf_pb.SerializeToString(),
                lambda d: WR_pb.FromString(d),
                b"",
            )
            results.append(("HeartbeatMsg", "google.protobuf", size_hb_g, enc_hb_g, dec_hb_g))
            results.append(("WorkflowRecord", "google.protobuf", size_wf_g, enc_wf_g, dec_wf_g))
        except ImportError:
            print("google.protobuf _pb2 code not found — run: buf generate (or make proto)")
    finally:
        if _prev_backend is None:
            os.environ.pop("RUFUS_PROTO_BACKEND", None)
        else:
            os.environ["RUFUS_PROTO_BACKEND"] = _prev_backend

    # --- Print results table ---
    print()
    print(f"{'Message':<20} {'Backend':<28} {'Size':>8}  {'Enc 10k':>10}  {'Dec 10k':>10}  {'Vs JSON':>8}")
    print("-" * 92)

    json_sizes = {}
    for msg, backend, size, enc_ms, dec_ms in results:
        if "JSON" in backend or "stdlib" in backend:
            json_sizes[msg] = size

    for msg, backend, size, enc_ms, dec_ms in results:
        ratio = ""
        if msg in json_sizes and json_sizes[msg] and size:
            r = json_sizes[msg] / size
            ratio = f"{r:.1f}×" if r >= 1.0 else f"{1/r:.2f}×"
        enc_str = f"{enc_ms:.1f}ms" if enc_ms else "-"
        dec_str = f"{dec_ms:.1f}ms" if dec_ms else "-"
        print(f"{msg:<20} {backend:<28} {size:>7}B  {enc_str:>10}  {dec_str:>10}  {ratio:>8}")

    print()
    print(f"Iterations per measurement: {ITERATIONS:,}")
    print()


if __name__ == "__main__":
    main()
