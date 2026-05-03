#!/usr/bin/env python3
"""
Ruvon SDK Installation Verification Script

Run this after installing the package to verify everything works correctly.

Usage:
    python verify_installation.py
"""

import sys
from typing import List, Tuple


def check_imports() -> List[Tuple[str, bool, str]]:
    """Check if core modules can be imported."""
    results = []

    checks = [
        ("ruvon.builder", "WorkflowBuilder"),
        ("ruvon.models", "StepContext"),
        ("ruvon.workflow", "Workflow"),
        ("ruvon.implementations.persistence.sqlite", "SQLitePersistenceProvider"),
        ("ruvon.implementations.execution.sync", "SyncExecutionProvider"),
        ("rufus_cli.main", "app"),
    ]

    for module_path, attr_name in checks:
        try:
            module = __import__(module_path, fromlist=[attr_name])
            getattr(module, attr_name)
            results.append((f"{module_path}.{attr_name}", True, "OK"))
        except ImportError as e:
            results.append((f"{module_path}.{attr_name}", False, f"Import error: {e}"))
        except AttributeError as e:
            results.append((f"{module_path}.{attr_name}", False, f"Attribute error: {e}"))
        except Exception as e:
            results.append((f"{module_path}.{attr_name}", False, f"Error: {e}"))

    return results


def check_cli() -> Tuple[bool, str]:
    """Check if CLI is accessible."""
    import subprocess

    try:
        result = subprocess.run(
            ["ruvon", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "CLI OK"
        else:
            return False, f"CLI error (code {result.returncode}): {result.stderr}"
    except FileNotFoundError:
        return False, "ruvon command not found in PATH"
    except Exception as e:
        return False, f"Error checking CLI: {e}"


def check_dependencies() -> List[Tuple[str, bool, str]]:
    """Check if key dependencies are installed."""
    results = []

    dependencies = [
        "pydantic",
        "yaml",
        "jinja2",
        "typer",
        "aiosqlite",
        "orjson",
        "httpx",
        "cryptography",
        "sqlalchemy",
        "alembic",
    ]

    for dep in dependencies:
        try:
            __import__(dep)
            results.append((dep, True, "Installed"))
        except ImportError:
            results.append((dep, False, "Missing"))

    return results


def check_database_support() -> List[Tuple[str, bool, str]]:
    """Check database backend support."""
    results = []

    # SQLite (required)
    try:
        import aiosqlite
        results.append(("SQLite", True, f"aiosqlite {aiosqlite.__version__}"))
    except Exception as e:
        results.append(("SQLite", False, str(e)))

    # PostgreSQL (optional)
    try:
        import asyncpg
        results.append(("PostgreSQL", True, f"asyncpg {asyncpg.__version__}"))
    except ImportError:
        results.append(("PostgreSQL", False, "Not installed (optional)"))
    except Exception as e:
        results.append(("PostgreSQL", False, str(e)))

    return results


def print_results():
    """Print verification results."""
    print("=" * 70)
    print("  RUFUS SDK INSTALLATION VERIFICATION")
    print("=" * 70)
    print()

    # Python version
    print(f"Python Version: {sys.version.split()[0]}")
    print()

    # Core imports
    print("Core Module Imports:")
    print("-" * 70)
    import_results = check_imports()
    all_imports_ok = all(success for _, success, _ in import_results)

    for name, success, message in import_results:
        status = "✓" if success else "✗"
        print(f"  {status} {name:<50} {message}")
    print()

    # CLI
    print("CLI Availability:")
    print("-" * 70)
    cli_ok, cli_message = check_cli()
    cli_status = "✓" if cli_ok else "✗"
    print(f"  {cli_status} ruvon command: {cli_message}")
    print()

    # Dependencies
    print("Core Dependencies:")
    print("-" * 70)
    dep_results = check_dependencies()
    all_deps_ok = all(success for _, success, _ in dep_results)

    for name, success, message in dep_results:
        status = "✓" if success else "✗"
        print(f"  {status} {name:<30} {message}")
    print()

    # Database support
    print("Database Support:")
    print("-" * 70)
    db_results = check_database_support()

    for name, success, message in db_results:
        status = "✓" if success else "⚠" if "optional" in message.lower() else "✗"
        print(f"  {status} {name:<30} {message}")
    print()

    # Summary
    print("=" * 70)

    if all_imports_ok and cli_ok and all_deps_ok:
        print("  ✓ ALL CHECKS PASSED - Ruvon SDK is ready to use!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Try: ruvon --help")
        print("  2. Run examples: cd examples/sqlite_task_manager && python simple_demo.py")
        print("  3. Read documentation: QUICKSTART.md")
        return 0
    else:
        print("  ✗ SOME CHECKS FAILED - See errors above")
        print("=" * 70)
        print()
        print("Troubleshooting:")

        if not all_imports_ok:
            print("  • Import errors: Reinstall with: pip install --force-reinstall git+https://github.com/KamikaziD/ruvon-sdk.git")

        if not cli_ok:
            print("  • CLI not found: Check that pip install location is in your PATH")
            print("    Or try: python -m rufus_cli.main --help")

        if not all_deps_ok:
            print("  • Missing dependencies: pip install -r requirements.txt")

        return 1


if __name__ == "__main__":
    sys.exit(print_results())
