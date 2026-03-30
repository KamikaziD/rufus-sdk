"""
rufus.wasm_component — Component Model support for WASM workflow steps.

Exports:
  COMPONENT_MAGIC  — bytes that identify a WASM Component (vs core module)
  is_component()   — detect whether a binary is a Component Model binary

The WIT interface definition lives in step.wit alongside this file.
"""

# WASM core modules start with b'\x00asm' followed by version bytes 0x01 0x00 0x00 0x00.
# WASM Component Model binaries use the same 4-byte magic (b'\x00asm') but with
# version bytes 0x0d 0x00 0x01 0x00  (layer = 1, version = 0x0d).
_WASM_MAGIC = b"\x00asm"
_CORE_VERSION = b"\x01\x00\x00\x00"
_COMPONENT_LAYER = b"\x0d\x00\x01\x00"

COMPONENT_MAGIC: bytes = _WASM_MAGIC + _COMPONENT_LAYER


def is_component(binary: bytes) -> bool:
    """Return True if *binary* is a WASM Component Model binary.

    Detection is based on the 8-byte WASM preamble:
      bytes 0-3: magic  = \\x00asm  (same for core and component)
      bytes 4-7: version = \\x01\\x00\\x00\\x00 (core)
                         | \\x0d\\x00\\x01\\x00 (component, layer=1)
    """
    if len(binary) < 8:
        return False
    return binary[:4] == _WASM_MAGIC and binary[4:8] == _COMPONENT_LAYER


__all__ = ["COMPONENT_MAGIC", "is_component"]
