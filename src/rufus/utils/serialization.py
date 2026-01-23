"""
High-performance JSON serialization utilities using orjson.

orjson is a Rust-based JSON library that's 3-5x faster than stdlib json
and produces smaller output with more efficient encoding.

Features:
- Fast serialization (3-5x faster than json.dumps)
- Fast deserialization (2-3x faster than json.loads)
- Automatic datetime/UUID handling
- Compact output (no unnecessary whitespace)
- Memory efficient
"""

import os
from typing import Any, Optional, Dict, List, Union

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


def get_backend() -> str:
    """
    Get the current JSON serialization backend.

    Returns:
        "orjson" or "json (stdlib)"
    """
    return _backend


# Convenience aliases for backwards compatibility
dumps = serialize
loads = deserialize
