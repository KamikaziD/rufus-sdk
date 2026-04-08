"""
Version consistency guard.

Verifies that all four rufus packages report the same __version__.
This prevents silent version drift when bumping the release.
"""

import ruvon
import ruvon_edge
import ruvon_server
import ruvon_cli


def test_all_versions_match():
    versions = {
        "ruvon": ruvon.__version__,
        "ruvon_edge": ruvon_edge.__version__,
        "ruvon_server": ruvon_server.__version__,
        "ruvon_cli": ruvon_cli.__version__,
    }
    unique = set(versions.values())
    assert len(unique) == 1, (
        f"Package versions are out of sync: {versions}. "
        "Bump all four __version__ strings to the same value."
    )


def test_version_format():
    """Version must be a valid semver-like string (e.g. '0.6.0')."""
    import re
    pattern = re.compile(r"^\d+\.\d+\.\d+")
    assert pattern.match(ruvon.__version__), (
        f"ruvon.__version__ '{ruvon.__version__}' does not look like semver"
    )
