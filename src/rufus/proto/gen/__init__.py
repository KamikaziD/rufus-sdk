"""
Proto generated code — backend-conditional re-exports.

Selects between google.protobuf (_pb2) and betterproto backends based on
the RUFUS_PROTO_BACKEND environment variable (default: "betterproto").

Set RUFUS_PROTO_BACKEND=google to use the google.protobuf C-extension
backend (~3-4× faster encode/decode). betterproto is the default to
preserve backward compatibility and avoid a hard dependency on protobuf.

If the selected backend's generated code is missing (run `buf generate`
or `make proto`), the import is silently skipped — callers that do
lazy `try: from rufus.proto.gen import X` will handle ImportError.
"""

import os

_BACKEND = os.getenv("RUFUS_PROTO_BACKEND", "betterproto")

if _BACKEND == "google":
    try:
        from .edge_pb2 import HeartbeatMsg, CommandMsg, CommandBatch  # type: ignore
        from .edge_pb2 import EncryptedTransaction, SyncBatch, SyncResponse  # type: ignore
        from .edge_pb2 import ConfigRequest, ConfigResponse, WorkflowSyncBatch  # type: ignore
        from .edge_pb2 import MeshRelayMeta  # type: ignore
        from .workflow_pb2 import WorkflowRecord, TaskDispatch, TaskResult  # type: ignore
        from .events_pb2 import WorkflowEvent  # type: ignore
    except ImportError:
        _BACKEND = "betterproto"  # graceful fallback

if _BACKEND == "betterproto":
    try:
        from .edge import HeartbeatMsg, CommandMsg, CommandBatch  # type: ignore
        from .edge import EncryptedTransaction, SyncBatch, SyncResponse  # type: ignore
        from .edge import ConfigRequest, ConfigResponse, WorkflowSyncBatch  # type: ignore
        from .edge import MeshRelayMeta  # type: ignore
        from .workflow import WorkflowRecord, TaskDispatch, TaskResult  # type: ignore
        from .events import WorkflowEvent  # type: ignore
    except ImportError:
        pass  # generated code not yet built — run: buf generate (or make proto)
