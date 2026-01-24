#!/usr/bin/env python3
"""
Schema Validation Tool

Validates that the generated schema migrations are correct by comparing
structure and ensuring all required components are present.

Usage:
    python tools/validate_schema.py --target postgres
    python tools/validate_schema.py --target sqlite
    python tools/validate_schema.py --all
"""

import argparse
import re
from pathlib import Path
from typing import Set, Dict, List


class SchemaValidator:
    """Validates generated schema migrations"""

    def __init__(self):
        self.postgres_original = Path("confucius/migrations/001_init_postgresql_schema.sql")
        self.postgres_generated = Path("migrations/002_postgres_standardized.sql")
        self.sqlite_generated = Path("migrations/002_sqlite_initial.sql")

    def extract_tables(self, sql_content: str) -> Set[str]:
        """Extract table names from SQL"""
        pattern = r'CREATE TABLE IF NOT EXISTS (\w+)'
        return set(re.findall(pattern, sql_content))

    def extract_indexes(self, sql_content: str) -> Set[str]:
        """Extract index names from SQL"""
        pattern = r'CREATE INDEX IF NOT EXISTS (\w+)'
        return set(re.findall(pattern, sql_content))

    def extract_triggers(self, sql_content: str) -> Set[str]:
        """Extract trigger names from SQL"""
        pattern = r'CREATE TRIGGER(?: IF NOT EXISTS)? (\w+)'
        return set(re.findall(pattern, sql_content))

    def extract_views(self, sql_content: str) -> Set[str]:
        """Extract view names from SQL"""
        pattern = r'CREATE (?:OR REPLACE )?VIEW (\w+)'
        return set(re.findall(pattern, sql_content))

    def validate_postgres(self) -> Dict[str, any]:
        """Validate PostgreSQL schema against original"""
        if not self.postgres_original.exists():
            return {
                "status": "warning",
                "message": "Original PostgreSQL schema not found (expected for new projects)"
            }

        if not self.postgres_generated.exists():
            return {
                "status": "error",
                "message": "Generated PostgreSQL schema not found"
            }

        with open(self.postgres_original, 'r') as f:
            original_sql = f.read()

        with open(self.postgres_generated, 'r') as f:
            generated_sql = f.read()

        # Extract components
        orig_tables = self.extract_tables(original_sql)
        gen_tables = self.extract_tables(generated_sql)

        orig_indexes = self.extract_indexes(original_sql)
        gen_indexes = self.extract_indexes(generated_sql)

        orig_triggers = self.extract_triggers(original_sql)
        gen_triggers = self.extract_triggers(generated_sql)

        orig_views = self.extract_views(original_sql)
        gen_views = self.extract_views(generated_sql)

        # Compare
        results = {
            "status": "success",
            "tables": {
                "original": len(orig_tables),
                "generated": len(gen_tables),
                "missing": list(orig_tables - gen_tables),
                "extra": list(gen_tables - orig_tables),
            },
            "indexes": {
                "original": len(orig_indexes),
                "generated": len(gen_indexes),
                "missing": list(orig_indexes - gen_indexes),
                "extra": list(gen_indexes - orig_indexes),
            },
            "triggers": {
                "original": len(orig_triggers),
                "generated": len(gen_triggers),
                "missing": list(orig_triggers - gen_triggers),
                "extra": list(gen_triggers - orig_triggers),
            },
            "views": {
                "original": len(orig_views),
                "generated": len(gen_views),
                "missing": list(orig_views - gen_views),
                "extra": list(gen_views - orig_views),
            }
        }

        # Check for issues
        issues = []
        if results["tables"]["missing"]:
            issues.append(f"Missing tables: {', '.join(results['tables']['missing'])}")
        if results["indexes"]["missing"]:
            issues.append(f"Missing indexes: {', '.join(results['indexes']['missing'])}")
        if results["triggers"]["missing"]:
            issues.append(f"Missing triggers: {', '.join(results['triggers']['missing'])}")
        if results["views"]["missing"]:
            issues.append(f"Missing views: {', '.join(results['views']['missing'])}")

        if issues:
            results["status"] = "error"
            results["issues"] = issues

        return results

    def validate_sqlite(self) -> Dict[str, any]:
        """Validate SQLite schema structure"""
        if not self.sqlite_generated.exists():
            return {
                "status": "error",
                "message": "Generated SQLite schema not found"
            }

        with open(self.sqlite_generated, 'r') as f:
            sql_content = f.read()

        # Expected components for SQLite
        expected_tables = {
            'workflow_executions',
            'tasks',
            'compensation_log',
            'workflow_audit_log',
            'workflow_execution_logs',
            'workflow_metrics'
        }

        expected_views = {
            'active_workflows',
            'workflow_execution_summary'
        }

        # Extract actual components
        actual_tables = self.extract_tables(sql_content)
        actual_indexes = self.extract_indexes(sql_content)
        actual_triggers = self.extract_triggers(sql_content)
        actual_views = self.extract_views(sql_content)

        results = {
            "status": "success",
            "tables": {
                "expected": len(expected_tables),
                "actual": len(actual_tables),
                "missing": list(expected_tables - actual_tables),
            },
            "indexes": {
                "count": len(actual_indexes)
            },
            "triggers": {
                "count": len(actual_triggers)
            },
            "views": {
                "expected": len(expected_views),
                "actual": len(actual_views),
                "missing": list(expected_views - actual_views),
            }
        }

        # Check for SQLite-specific conversions
        checks = []

        # UUID should be TEXT
        if 'UUID' in sql_content:
            checks.append("❌ Found UUID type (should be TEXT in SQLite)")
            results["status"] = "error"
        else:
            checks.append("✓ UUID correctly mapped to TEXT")

        # JSONB should be TEXT
        if 'JSONB' in sql_content:
            checks.append("❌ Found JSONB type (should be TEXT in SQLite)")
            results["status"] = "error"
        else:
            checks.append("✓ JSONB correctly mapped to TEXT")

        # TIMESTAMPTZ should be TEXT
        if 'TIMESTAMPTZ' in sql_content:
            checks.append("❌ Found TIMESTAMPTZ type (should be TEXT in SQLite)")
            results["status"] = "error"
        else:
            checks.append("✓ TIMESTAMPTZ correctly mapped to TEXT")

        # BOOLEAN should be INTEGER
        if 'BOOLEAN' in sql_content:
            checks.append("❌ Found BOOLEAN type (should be INTEGER in SQLite)")
            results["status"] = "error"
        else:
            checks.append("✓ BOOLEAN correctly mapped to INTEGER")

        # Check for AUTOINCREMENT on INTEGER PRIMARY KEY
        if 'INTEGER PRIMARY KEY AUTOINCREMENT' in sql_content:
            checks.append("✓ BIGSERIAL correctly mapped to INTEGER AUTOINCREMENT")
        else:
            checks.append("⚠️  No AUTOINCREMENT found (expected for metrics/logs tables)")

        results["type_checks"] = checks

        # Check for missing components
        issues = []
        if results["tables"]["missing"]:
            issues.append(f"Missing tables: {', '.join(results['tables']['missing'])}")
        if results["views"]["missing"]:
            issues.append(f"Missing views: {', '.join(results['views']['missing'])}")

        if issues:
            results["status"] = "error"
            results["issues"] = issues

        return results

    def print_results(self, db_type: str, results: Dict[str, any]):
        """Pretty print validation results"""
        print(f"\n{'='*70}")
        print(f"  {db_type.upper()} SCHEMA VALIDATION")
        print(f"{'='*70}\n")

        if "message" in results:
            print(f"  {results['message']}")
            return

        # Tables
        if "tables" in results:
            tables = results["tables"]
            if db_type == "postgres":
                print(f"  Tables:      {tables['generated']}/{tables['original']}")
            else:
                print(f"  Tables:      {tables['actual']}/{tables['expected']}")

            if tables.get("missing"):
                print(f"    ❌ Missing: {', '.join(tables['missing'])}")
            if tables.get("extra"):
                print(f"    ⚠️  Extra: {', '.join(tables['extra'])}")
            if not tables.get("missing") and not tables.get("extra"):
                print(f"    ✓ All expected tables present")

        # Indexes
        if "indexes" in results:
            indexes = results["indexes"]
            if db_type == "postgres":
                print(f"\n  Indexes:     {indexes['generated']}/{indexes['original']}")
                if indexes.get("missing"):
                    print(f"    ❌ Missing: {', '.join(indexes['missing'])}")
                if indexes.get("extra"):
                    print(f"    ⚠️  Extra: {', '.join(indexes['extra'])}")
            else:
                print(f"\n  Indexes:     {indexes['count']}")

        # Triggers
        if "triggers" in results:
            triggers = results["triggers"]
            if db_type == "postgres":
                print(f"\n  Triggers:    {triggers['generated']}/{triggers['original']}")
                if triggers.get("missing"):
                    print(f"    ❌ Missing: {', '.join(triggers['missing'])}")
            else:
                print(f"\n  Triggers:    {triggers['count']}")

        # Views
        if "views" in results:
            views = results["views"]
            if db_type == "postgres":
                print(f"\n  Views:       {views['generated']}/{views['original']}")
                if views.get("missing"):
                    print(f"    ❌ Missing: {', '.join(views['missing'])}")
            else:
                print(f"\n  Views:       {views['actual']}/{views['expected']}")
                if views.get("missing"):
                    print(f"    ❌ Missing: {', '.join(views['missing'])}")

        # Type checks (SQLite only)
        if "type_checks" in results:
            print(f"\n  Type Mappings:")
            for check in results["type_checks"]:
                print(f"    {check}")

        # Overall status
        print(f"\n  Status:      ", end="")
        if results["status"] == "success":
            print("✅ PASSED")
        elif results["status"] == "warning":
            print("⚠️  WARNING")
        else:
            print("❌ FAILED")

        if "issues" in results:
            print(f"\n  Issues:")
            for issue in results["issues"]:
                print(f"    - {issue}")

        print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate generated schema migrations"
    )
    parser.add_argument(
        '--target',
        choices=['postgres', 'sqlite'],
        help='Target database to validate'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Validate all databases'
    )

    args = parser.parse_args()

    if not args.all and not args.target:
        parser.error("Either --all or --target is required")

    validator = SchemaValidator()

    if args.all or args.target == 'postgres':
        results = validator.validate_postgres()
        validator.print_results('postgres', results)

    if args.all or args.target == 'sqlite':
        results = validator.validate_sqlite()
        validator.print_results('sqlite', results)


if __name__ == '__main__':
    main()
