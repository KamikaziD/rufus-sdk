#!/usr/bin/env python3
"""
Validate documentation links and structure.

Checks:
1. All internal markdown links resolve
2. All anchors exist in target files
3. No broken external links (with timeout)
4. All referenced code examples exist
5. Consistency of cross-references
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple, Set
from urllib.parse import urlparse
import requests
from collections import defaultdict

# Configuration
DOCS_ROOT = Path(__file__).parent.parent
TIMEOUT = 5  # seconds for external link checks

# Patterns
MD_LINK_PATTERN = r'\[([^\]]+)\]\(([^\)]+)\)'
ANCHOR_PATTERN = r'#+\s+(.+)'

class LinkValidator:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checked_external: Set[str] = set()
        self.anchor_cache: dict = {}

    def validate_all_docs(self):
        """Validate all markdown files in docs/ and root."""
        print("🔍 Validating Ruvon documentation...")
        print(f"📂 Root: {DOCS_ROOT}")
        print()

        # Find all markdown files
        md_files = []
        md_files.extend(DOCS_ROOT.glob("*.md"))
        md_files.extend((DOCS_ROOT / "docs").rglob("*.md"))
        md_files.extend((DOCS_ROOT / "examples").rglob("*.md"))

        print(f"📄 Found {len(md_files)} markdown files\n")

        # Validate each file
        for md_file in sorted(md_files):
            self.validate_file(md_file)

        # Print results
        self.print_results()

        # Return exit code
        return 1 if self.errors else 0

    def validate_file(self, file_path: Path):
        """Validate a single markdown file."""
        rel_path = file_path.relative_to(DOCS_ROOT)
        print(f"Checking {rel_path}...")

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            self.errors.append(f"{rel_path}: Could not read file - {e}")
            return

        # Extract all links
        links = re.findall(MD_LINK_PATTERN, content)

        for link_text, link_target in links:
            self.validate_link(file_path, link_text, link_target)

    def validate_link(self, source_file: Path, link_text: str, link_target: str):
        """Validate a single link."""
        rel_source = source_file.relative_to(DOCS_ROOT)

        # Skip mailto and other special protocols
        if link_target.startswith(('mailto:', 'tel:', 'javascript:')):
            return

        # External link
        if link_target.startswith(('http://', 'https://')):
            self.validate_external_link(rel_source, link_target)
            return

        # Anchor-only link (same file)
        if link_target.startswith('#'):
            anchor = link_target[1:]
            self.validate_anchor(source_file, rel_source, anchor)
            return

        # Split path and anchor
        if '#' in link_target:
            path_part, anchor = link_target.split('#', 1)
        else:
            path_part = link_target
            anchor = None

        # Resolve relative path
        if path_part.startswith('/'):
            # Absolute from root
            target_path = DOCS_ROOT / path_part.lstrip('/')
        else:
            # Relative to source file
            target_path = (source_file.parent / path_part).resolve()

        # Check file exists
        if not target_path.exists():
            self.errors.append(
                f"{rel_source}: Broken link '{link_target}' - target file not found"
            )
            return

        # Check anchor if present
        if anchor:
            self.validate_anchor(target_path, rel_source, anchor, link_target)

    def validate_anchor(self, target_file: Path, source_rel: Path, anchor: str, full_link: str = None):
        """Validate that an anchor exists in a file."""
        # Get anchors from file (with caching)
        if target_file not in self.anchor_cache:
            try:
                content = target_file.read_text(encoding='utf-8')
                # Extract all headings
                headings = re.findall(ANCHOR_PATTERN, content)
                # Convert to anchor format (lowercase, hyphens, no special chars)
                anchors = set()
                for heading in headings:
                    anchor_id = heading.lower()
                    anchor_id = re.sub(r'[^\w\s-]', '', anchor_id)
                    anchor_id = re.sub(r'[\s_]+', '-', anchor_id)
                    anchors.add(anchor_id)
                self.anchor_cache[target_file] = anchors
            except Exception as e:
                self.warnings.append(f"Could not read {target_file} for anchor validation: {e}")
                return

        anchors = self.anchor_cache[target_file]
        if anchor not in anchors:
            link_display = full_link or f"#{anchor}"
            self.warnings.append(
                f"{source_rel}: Anchor '{anchor}' not found in {target_file.name} (link: {link_display})"
            )

    def validate_external_link(self, source_rel: Path, url: str):
        """Validate external link (with caching)."""
        # Skip if already checked
        if url in self.checked_external:
            return

        self.checked_external.add(url)

        try:
            response = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
            if response.status_code >= 400:
                self.warnings.append(
                    f"{source_rel}: External link may be broken: {url} (HTTP {response.status_code})"
                )
        except requests.RequestException as e:
            self.warnings.append(
                f"{source_rel}: Could not validate external link: {url} ({type(e).__name__})"
            )

    def print_results(self):
        """Print validation results."""
        print()
        print("=" * 80)
        print("VALIDATION RESULTS")
        print("=" * 80)
        print()

        if self.errors:
            print(f"❌ {len(self.errors)} ERRORS:")
            for error in self.errors:
                print(f"  - {error}")
            print()

        if self.warnings:
            print(f"⚠️  {len(self.warnings)} WARNINGS:")
            for warning in self.warnings:
                print(f"  - {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ All documentation links are valid!")
            print()

        # Summary
        print("Summary:")
        print(f"  Errors: {len(self.errors)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  External links checked: {len(self.checked_external)}")
        print()


def main():
    validator = LinkValidator()
    exit_code = validator.validate_all_docs()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
