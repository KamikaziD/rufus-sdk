"""
Version consistency guard.

Verifies that all four rufus packages report the same __version__.
This prevents silent version drift when bumping the release.
"""

import rufus
import rufus_edge
import rufus_server
import rufus_cli


def test_all_versions_match():
    versions = {
        "rufus": rufus.__version__,
        "rufus_edge": rufus_edge.__version__,
        "rufus_server": rufus_server.__version__,
        "rufus_cli": rufus_cli.__version__,
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
    assert pattern.match(rufus.__version__), (
        f"rufus.__version__ '{rufus.__version__}' does not look like semver"
    )
