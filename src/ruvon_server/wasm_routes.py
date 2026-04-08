"""
WASM Component Management API Routes.

Endpoints:
  POST /api/v1/admin/wasm-components          — Upload a .wasm binary (admin only)
  GET  /api/v1/wasm-components/{hash}/download — Download a .wasm binary (device or admin)
  GET  /api/v1/wasm-components               — List all registered components (admin)
  GET  /api/v1/wasm-components/{hash}        — Fetch metadata for a component (admin)

Storage:
  Binaries are stored on local disk under the WASM_STORAGE_DIR environment variable
  (defaults to ./wasm_storage). Metadata is persisted in the wasm_components DB table.

Security:
  Upload and list/metadata endpoints require admin role.
  Download accepts either admin or device-level auth (devices need to pull binaries
  during sync_wasm command handling).
"""

import hashlib
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, JSONResponse

router = APIRouter(prefix="/api/v1", tags=["WASM"])

# Storage directory for .wasm binaries (configurable via env var)
WASM_STORAGE_DIR = os.getenv("WASM_STORAGE_DIR", "./wasm_storage")


def _storage_dir() -> str:
    """Return (and lazily create) the WASM storage directory."""
    path = WASM_STORAGE_DIR
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# POST /api/v1/admin/wasm-components
# ---------------------------------------------------------------------------

@router.post("/admin/wasm-components", status_code=201)
async def upload_wasm_component(
    request: Request,
    file: UploadFile = File(..., description=".wasm binary file"),
    name: str = Form(..., description="Human-readable component name"),
    version_tag: str = Form(..., description="Semantic version tag, e.g. v1.2.0"),
    input_schema: Optional[str] = Form(None, description="JSON schema string for module input (optional)"),
    output_schema: Optional[str] = Form(None, description="JSON schema string for module output (optional)"),
):
    """Upload a pre-compiled WebAssembly binary.

    Computes the SHA-256 hash of the uploaded file, writes it to disk, and
    inserts a row into the wasm_components table. Returns the component metadata
    including the binary_hash needed to reference this binary in workflow YAML.

    Requires admin role.
    """
    # Import here to avoid circular imports at module load time
    from ruvon_server.main import persistence_provider, require_admin
    from ruvon_server.auth import get_current_user

    user = await get_current_user(request)
    await require_admin(user)

    if persistence_provider is None:
        raise HTTPException(status_code=503, detail="Persistence provider not initialized")

    # Read binary and compute hash
    binary_data = await file.read()
    if not binary_data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    binary_hash = hashlib.sha256(binary_data).hexdigest()

    # Check for duplicates
    async with persistence_provider.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, name, version_tag FROM wasm_components WHERE binary_hash = $1",
            binary_hash,
        )
    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "message": "Binary already registered (content-addressable dedup)",
                "id": existing["id"],
                "binary_hash": binary_hash,
                "name": existing["name"],
                "version_tag": existing["version_tag"],
            },
        )

    # Write to disk
    storage_dir = _storage_dir()
    file_path = os.path.join(storage_dir, f"{binary_hash}.wasm")
    with open(file_path, "wb") as f:
        f.write(binary_data)

    # Persist metadata
    component_id = str(uuid.uuid4())
    now = datetime.utcnow()
    async with persistence_provider.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO wasm_components
                (id, name, version_tag, binary_hash, blob_storage_path,
                 input_schema, output_schema, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            component_id, name, version_tag, binary_hash, file_path,
            input_schema, output_schema, now, now,
        )

    return {
        "id": component_id,
        "name": name,
        "version_tag": version_tag,
        "binary_hash": binary_hash,
        "blob_storage_path": file_path,
        "size_bytes": len(binary_data),
        "created_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/wasm-components/{binary_hash}/download
# ---------------------------------------------------------------------------

@router.get("/wasm-components/{binary_hash}/download")
async def download_wasm_component(
    request: Request,
    binary_hash: str,
):
    """Download the raw .wasm binary by its SHA-256 hash.

    Accessible by devices (during sync_wasm) and admins. Returns the binary
    as application/wasm with a Content-Disposition header for the filename.
    """
    from ruvon_server.main import persistence_provider

    if persistence_provider is None:
        raise HTTPException(status_code=503, detail="Persistence provider not initialized")

    # Validate hash format (64 hex chars)
    if len(binary_hash) != 64 or not all(c in "0123456789abcdef" for c in binary_hash.lower()):
        raise HTTPException(status_code=400, detail="Invalid binary_hash format (must be 64-char hex SHA-256)")

    async with persistence_provider.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, version_tag, blob_storage_path FROM wasm_components WHERE binary_hash = $1",
            binary_hash,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"WASM component not found: {binary_hash}")

    file_path = row["blob_storage_path"]
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=500,
            detail=f"Binary file missing from disk: {file_path}. Re-upload the component.",
        )

    filename = f"{row['name']}_{row['version_tag']}.wasm"

    def _iter_file():
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        _iter_file(),
        media_type="application/wasm",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /api/v1/wasm-components   (list)
# ---------------------------------------------------------------------------

@router.get("/wasm-components")
async def list_wasm_components(
    request: Request,
    name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all registered WASM components. Requires admin role."""
    from ruvon_server.main import persistence_provider, require_admin
    from ruvon_server.auth import get_current_user

    user = await get_current_user(request)
    await require_admin(user)

    if persistence_provider is None:
        raise HTTPException(status_code=503, detail="Persistence provider not initialized")

    async with persistence_provider.pool.acquire() as conn:
        if name:
            rows = await conn.fetch(
                "SELECT id, name, version_tag, binary_hash, created_at FROM wasm_components "
                "WHERE name = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                name, limit, offset,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, name, version_tag, binary_hash, created_at FROM wasm_components "
                "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )

    return {
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/wasm-components/{binary_hash}   (metadata)
# ---------------------------------------------------------------------------

@router.get("/wasm-components/{binary_hash}")
async def get_wasm_component(
    request: Request,
    binary_hash: str,
):
    """Fetch metadata for a specific WASM component by hash. Requires admin role."""
    from ruvon_server.main import persistence_provider, require_admin
    from ruvon_server.auth import get_current_user

    user = await get_current_user(request)
    await require_admin(user)

    if persistence_provider is None:
        raise HTTPException(status_code=503, detail="Persistence provider not initialized")

    async with persistence_provider.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, version_tag, binary_hash, blob_storage_path, "
            "input_schema, output_schema, created_at, updated_at "
            "FROM wasm_components WHERE binary_hash = $1",
            binary_hash,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"WASM component not found: {binary_hash}")

    data = dict(row)
    # Add live file-exists check
    data["file_exists"] = os.path.exists(row["blob_storage_path"])
    return data
