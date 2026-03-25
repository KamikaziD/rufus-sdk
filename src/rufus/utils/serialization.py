"""
High-performance JSON serialization utilities using orjson, msgspec, and betterproto.

orjson is a Rust-based JSON library that's 3-5x faster than stdlib json
and produces smaller output with more efficient encoding.

msgspec provides typed JSON decode that constructs structs directly from bytes
with no intermediate dict allocation — 5-10× faster on known-type paths.

betterproto provides Protocol Buffer binary encoding — 5-7× smaller than JSON
for NATS wire transport. Enabled when RUFUS_USE_PROTO=true (default) and
betterproto is installed.

Features:
- Fast serialization (3-5x faster than json.dumps)
- Fast deserialization (2-3x faster than json.loads)
- Typed decode via msgspec (zero-copy struct construction)
- Proto binary encoding via betterproto (5-7× smaller for NATS)
- Envelope byte for mixed-protocol rollout (JSON + proto coexistence)
- Automatic datetime/UUID handling
- Compact output (no unnecessary whitespace)
- Memory efficient
"""

import os
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

T = TypeVar("T")

# Try to use orjson for performance, fallback to stdlib json
_ORJSON_ENABLED = os.getenv("RUFUS_USE_ORJSON", "true").lower() == "true"

if _ORJSON_ENABLED:
    try:
        import orjson
        _backend = "orjson"
        _USING_ORJSON = True
    except ImportError:
        import json
        _backend = "json (stdlib)"
        _USING_ORJSON = False
else:
    import json
    _backend = "json (stdlib)"
    _USING_ORJSON = False

# msgspec backend for typed decode
_MSGSPEC_ENABLED = os.getenv("RUFUS_USE_MSGSPEC", "true").lower() == "true"
_USING_MSGSPEC = False
if _MSGSPEC_ENABLED:
    try:
        import msgspec as _msgspec
        _msgspec_json_decoder = _msgspec.json.Decoder()
        _msgspec_json_encoder = _msgspec.json.Encoder()
        _USING_MSGSPEC = True
    except ImportError:
        pass


def serialize(obj: Any, pretty: bool = False) -> str:
    """
    Serialize Python object to JSON string.

    Args:
        obj: Python object to serialize (dict, list, BaseModel, etc.)
        pretty: If True, format with indentation (default: False)

    Returns:
        JSON string

    Examples:
        >>> serialize({"key": "value"})
        '{"key":"value"}'

        >>> serialize({"key": "value"}, pretty=True)
        '{\\n  "key": "value"\\n}'
    """
    if _USING_ORJSON:
        # orjson returns bytes, decode to str
        options = orjson.OPT_INDENT_2 if pretty else 0
        return orjson.dumps(obj, option=options).decode('utf-8')
    else:
        # Fallback to stdlib json
        if pretty:
            return json.dumps(obj, indent=2, default=str)
        return json.dumps(obj, default=str)


def serialize_bytes(obj: Any) -> bytes:
    """
    Serialize Python object to JSON bytes.

    This is more efficient when you need bytes (e.g., for NATS, Redis)
    as it avoids the extra decode step.

    Args:
        obj: Python object to serialize

    Returns:
        JSON bytes

    Examples:
        >>> serialize_bytes({"key": "value"})
        b'{"key":"value"}'
    """
    if _USING_ORJSON:
        return orjson.dumps(obj)
    else:
        return json.dumps(obj, default=str).encode('utf-8')


def deserialize(json_str: Union[str, bytes]) -> Any:
    """
    Deserialize JSON string/bytes to Python object.

    Args:
        json_str: JSON string or bytes to deserialize

    Returns:
        Python object (dict, list, etc.)

    Examples:
        >>> deserialize('{"key": "value"}')
        {'key': 'value'}

        >>> deserialize(b'{"key": "value"}')
        {'key': 'value'}
    """
    if _USING_ORJSON:
        # orjson handles both str and bytes
        return orjson.loads(json_str)
    else:
        # stdlib json needs str
        if isinstance(json_str, bytes):
            json_str = json_str.decode('utf-8')
        return json.loads(json_str)


def serialize_dict_values(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Serialize all values in a dictionary to JSON strings.

    Useful for storing complex objects in key-value stores like Redis.

    Args:
        data: Dictionary with any values

    Returns:
        Dictionary with JSON string values

    Examples:
        >>> serialize_dict_values({"user": {"id": 1, "name": "Alice"}})
        {'user': '{"id":1,"name":"Alice"}'}
    """
    return {key: serialize(value) for key, value in data.items()}


def deserialize_dict_values(data: Dict[str, str]) -> Dict[str, Any]:
    """
    Deserialize all JSON string values in a dictionary.

    Counterpart to serialize_dict_values.

    Args:
        data: Dictionary with JSON string values

    Returns:
        Dictionary with deserialized values

    Examples:
        >>> deserialize_dict_values({'user': '{"id":1,"name":"Alice"}'})
        {'user': {'id': 1, 'name': 'Alice'}}
    """
    return {key: deserialize(value) for key, value in data.items()}


def decode_typed(json_bytes: Union[str, bytes], type: Type[T]) -> T:
    """
    Deserialize JSON directly into a typed msgspec.Struct — the fast path.

    Constructs the struct from bytes with no intermediate dict allocation.
    Falls back to deserialize() + manual construction if msgspec is unavailable.

    Args:
        json_bytes: JSON string or bytes to decode
        type: The msgspec.Struct subclass to decode into

    Returns:
        An instance of the given type

    Examples:
        >>> record = decode_typed(row_bytes, type=WorkflowRecord)
    """
    if _USING_MSGSPEC:
        if isinstance(json_bytes, str):
            json_bytes = json_bytes.encode("utf-8")
        return _msgspec.json.decode(json_bytes, type=type)
    # Fallback: deserialize to dict then construct manually
    data = deserialize(json_bytes)
    return type(**data)


def encode_struct(obj) -> bytes:
    """
    Encode a msgspec.Struct to JSON bytes.

    Faster than orjson for struct types because msgspec knows the schema upfront
    and skips Python-level introspection.

    Args:
        obj: A msgspec.Struct instance

    Returns:
        JSON bytes

    Examples:
        >>> encode_struct(workflow_record)
        b'{"id":"abc","workflow_type":"Payment",...}'
    """
    if _USING_MSGSPEC:
        return _msgspec_json_encoder.encode(obj)
    # Fallback via orjson/json after converting to dict
    import msgspec
    return serialize_bytes(msgspec.to_builtins(obj))


# ---------------------------------------------------------------------------
# Proto codec (betterproto, optional — gated by RUFUS_USE_PROTO)
# ---------------------------------------------------------------------------

_PROTO_ENABLED = os.getenv("RUFUS_USE_PROTO", "true").lower() == "true"
_USING_PROTO = False
if _PROTO_ENABLED:
    try:
        import betterproto as _betterproto
        _USING_PROTO = True
    except ImportError:
        pass

# Wire-format envelope bytes (leading byte in packed messages)
ENCODING_JSON  = b"\x01"
ENCODING_PROTO = b"\x02"


def encode_proto(msg) -> bytes:
    """
    Encode a proto Message to binary protobuf bytes.

    Supports both google.protobuf (SerializeToString) and betterproto (bytes())
    via duck-typing. Falls back to JSON if proto is unavailable.

    Args:
        msg: A google.protobuf.Message or betterproto.Message instance

    Returns:
        Protobuf binary bytes (or JSON bytes as fallback)
    """
    if _USING_PROTO:
        if hasattr(msg, "SerializeToString"):   # google.protobuf
            return msg.SerializeToString()
        return bytes(msg)                        # betterproto
    # JSON fallback: serialize the message's __dict__
    return serialize_bytes(
        {k: v for k, v in vars(msg).items() if not k.startswith("_")}
    )


def decode_proto(data: bytes, msg_type: Type[T]) -> T:
    """
    Decode protobuf binary bytes into a proto Message.

    Supports both google.protobuf (FromString) and betterproto (parse())
    via duck-typing. Falls back to JSON if proto is unavailable.

    Args:
        data: Protobuf binary bytes
        msg_type: google.protobuf.Message or betterproto.Message subclass

    Returns:
        An instance of msg_type
    """
    if _USING_PROTO:
        if hasattr(msg_type, "FromString"):     # google.protobuf
            return msg_type.FromString(data)
        return msg_type().parse(data)            # betterproto
    data_dict = deserialize(data)
    return msg_type(**data_dict)


def pack_message(payload: Any, proto_msg=None) -> bytes:
    """
    Pack a message with an envelope byte for mixed-protocol coexistence.

    When proto is available and proto_msg is provided, encodes as proto
    with ENCODING_PROTO prefix. Otherwise encodes payload as JSON with
    ENCODING_JSON prefix.

    The leading envelope byte allows JSON-only clients and proto-enabled
    clients to coexist on the same NATS subject during rollout.

    Supports both google.protobuf and betterproto message types.

    Args:
        payload: Python dict / object (used for JSON path)
        proto_msg: A proto Message instance (google.protobuf or betterproto)

    Returns:
        Envelope byte + encoded body
    """
    if _USING_PROTO and proto_msg is not None:
        return ENCODING_PROTO + encode_proto(proto_msg)
    return ENCODING_JSON + serialize_bytes(payload)


def unpack_message(data: bytes, proto_type: Optional[Type[T]] = None) -> Any:
    """
    Unpack a message previously packed with pack_message().

    Reads the leading envelope byte to detect encoding, then decodes
    accordingly. If the envelope byte is missing, falls back to JSON.

    Supports both google.protobuf and betterproto message types.

    Args:
        data: Raw bytes from NATS (envelope byte + body)
        proto_type: Proto Message class for proto decode path

    Returns:
        Decoded Python object (proto message instance or dict)
    """
    if not data:
        return {}

    envelope = data[:1]
    body = data[1:]

    if envelope == ENCODING_PROTO and _USING_PROTO and proto_type is not None:
        return decode_proto(body, proto_type)

    # JSON path (ENCODING_JSON or no envelope byte)
    raw = body if envelope in (ENCODING_JSON, ENCODING_PROTO) else data
    return deserialize(raw)


def get_backend() -> str:
    """
    Get the current serialization backend string.

    Returns:
        One of: "orjson+msgspec+proto", "orjson+msgspec", "orjson", "msgspec",
        "json (stdlib)"
    """
    if _USING_MSGSPEC and _USING_ORJSON and _USING_PROTO:
        return "orjson+msgspec+proto"
    if _USING_MSGSPEC and _USING_ORJSON:
        return "orjson+msgspec"
    if _USING_MSGSPEC:
        return "msgspec"
    return _backend


# Convenience aliases for backwards compatibility
dumps = serialize
loads = deserialize
