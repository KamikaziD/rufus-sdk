"""
PyodideSQLiteProvider — aiosqlite-compatible persistence for the browser.

In a Pyodide / Web Worker environment the Python ``sqlite3`` module is
*unavailable* because it links against native libsqlite3.  Instead we use
**wa-sqlite** — a WebAssembly build of SQLite exposed as a JavaScript ES module.

This shim presents the same async interface as
``rufus.implementations.persistence.sqlite.SQLitePersistenceProvider`` so the
edge agent code is identical in all three environments.

Architecture
------------
::

    Python (Pyodide)
        PyodideSQLiteProvider
            └── _WaSqliteConn          (thin wrapper)
                    └── js.WaSqlite     (JS ESM, loaded by browser_loader.js)
                            └── SQLite data in OPFS (Origin Private File System)

Constraints
-----------
* Requires Pyodide ≥ 0.25 with JSPI support.
* wa-sqlite must be loaded by the host Web Worker before Python starts
  (``browser_loader.js`` does this and exposes ``globalThis.WaSqlite``).
* All SQL is passed as strings — no prepared-statement objects cross the
  Python↔JS boundary (JS strings are cheap in Pyodide).
* This class is **not imported on native CPython** — it is only used when
  ``js`` is importable (i.e. inside Pyodide).

Usage
-----
This provider is instantiated automatically by ``browser_loader.js``::

    from ruvon_edge.implementations.persistence.pyodide_sqlite import (
        PyodideSQLiteProvider,
    )
    persistence = PyodideSQLiteProvider(db_name="ruvon_edge")
    await persistence.initialize()
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _WaSqliteConn:
    """
    Minimal async SQLite connection backed by wa-sqlite in the browser.

    The JS module is accessed via ``globalThis.WaSqlite`` (set by
    ``browser_loader.js`` before Pyodide loads).

    Implements only the subset of the aiosqlite API used by
    ``SQLitePersistenceProvider``:
    - ``execute(sql, params=())``  → cursor
    - ``executemany(sql, rows)``
    - ``commit()``

    Cursors expose:
    - ``fetchone()``
    - ``fetchall()``
    - ``description``   — list of (col_name, ...) 7-tuples
    - ``lastrowid``
    """

    def __init__(self, js_db):
        self._db = js_db  # JS wa-sqlite database handle

    async def execute(self, sql: str, params: tuple = ()) -> "_WaSqliteCursor":
        from pyodide.ffi import to_js  # type: ignore[import]
        rows, columns = await self._db.execute(sql, to_js(list(params)))
        return _WaSqliteCursor(rows, columns)

    async def executemany(self, sql: str, rows):
        from pyodide.ffi import to_js  # type: ignore[import]
        for row in rows:
            await self._db.execute(sql, to_js(list(row)))

    async def commit(self):
        await self._db.commit()

    def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass  # wa-sqlite manages its own connection lifetime


class _WaSqliteCursor:
    def __init__(self, rows, columns):
        # rows: JS array of arrays → convert to Python
        self._rows = [list(r) for r in rows]
        self._columns = list(columns)
        self._pos = 0

    @property
    def description(self):
        return [(col, None, None, None, None, None, None) for col in self._columns]

    @property
    def lastrowid(self):
        return None  # Not tracked by this shim

    async def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    async def fetchall(self):
        result = self._rows[self._pos:]
        self._pos = len(self._rows)
        return result

    def __aiter__(self):
        return self

    async def __anext__(self):
        row = await self.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Public provider
# ---------------------------------------------------------------------------

class PyodideSQLiteProvider:
    """
    Persistence provider for Pyodide (browser) using wa-sqlite.

    Drop-in replacement for ``SQLitePersistenceProvider`` in the browser
    environment.  The public API is identical.

    Args:
        db_name: The OPFS database name (default: ``"ruvon_edge"``).
    """

    def __init__(self, db_name: str = "ruvon_edge"):
        self._db_name = db_name
        self.conn: Optional[_WaSqliteConn] = None

    async def initialize(self):
        """Open the wa-sqlite database and create schema if needed."""
        try:
            from js import globalThis  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "PyodideSQLiteProvider requires a Pyodide browser environment. "
                "Use SQLitePersistenceProvider on native CPython."
            ) from exc

        wa = globalThis.WaSqlite  # type: ignore[attr-defined]
        if wa is None:
            raise RuntimeError(
                "globalThis.WaSqlite is not set. "
                "browser_loader.js must load wa-sqlite before Python starts."
            )

        js_db = await wa.open(self._db_name)
        self.conn = _WaSqliteConn(js_db)
        await self._create_schema()
        logger.info(f"PyodideSQLiteProvider: opened '{self._db_name}' via wa-sqlite")

    async def _create_schema(self):
        """Import and run the standard SQLite schema SQL."""
        from ruvon.implementations.persistence.sqlite import SQLITE_SCHEMA  # type: ignore
        for statement in SQLITE_SCHEMA.split(";"):
            stmt = statement.strip()
            if stmt:
                await self.conn.execute(stmt)
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Helpers (mirrors SQLitePersistenceProvider)
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_json(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            import orjson
            return orjson.dumps(value).decode("utf-8")
        except ImportError:
            return json.dumps(value, default=str)

    @staticmethod
    def _deserialize_json(value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            import orjson
            return orjson.loads(value)
        except ImportError:
            return json.loads(value)

    # ------------------------------------------------------------------
    # Delegated persistence methods
    # ------------------------------------------------------------------
    # The full SQLitePersistenceProvider interface is intentionally NOT
    # re-implemented here — instead we delegate to the base class methods
    # at runtime (monkey-patch style) so we don't duplicate SQL.
    # This is possible because SQLitePersistenceProvider uses self.conn
    # exclusively for DB access.

    def __getattr__(self, name: str):
        """
        Delegate unknown method calls to a SQLitePersistenceProvider instance
        that shares our ``self.conn``.

        This avoids duplicating all the SQL while keeping the class simple.
        """
        from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider  # type: ignore

        base = SQLitePersistenceProvider.__new__(SQLitePersistenceProvider)
        base.conn = self.conn
        method = getattr(base, name, None)
        if method is None:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        return method
