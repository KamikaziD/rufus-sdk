"""
Unit tests for schema compiler

Tests the schema compilation from YAML to database-specific SQL
"""

import pytest
from pathlib import Path
import tempfile
import yaml
import sys

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))

from compile_schema import SchemaCompiler


@pytest.fixture
def sample_schema():
    """Sample schema for testing"""
    return {
        "version": "1.0.0",
        "description": "Test schema",
        "type_mappings": {
            "uuid": {
                "postgres": "UUID",
                "sqlite": "TEXT"
            },
            "jsonb": {
                "postgres": "JSONB",
                "sqlite": "TEXT"
            },
            "timestamp": {
                "postgres": "TIMESTAMPTZ",
                "sqlite": "TEXT"
            },
            "integer": {
                "postgres": "INTEGER",
                "sqlite": "INTEGER"
            },
            "boolean": {
                "postgres": "BOOLEAN",
                "sqlite": "INTEGER"
            }
        },
        "extensions": {
            "postgres": ["uuid-ossp"],
            "sqlite": []
        },
        "tables": {
            "test_table": {
                "description": "Test table",
                "columns": [
                    {
                        "name": "id",
                        "type": "uuid",
                        "primary_key": True,
                        "default": {
                            "postgres": "gen_random_uuid()",
                            "sqlite": "lower(hex(randomblob(16)))"
                        }
                    },
                    {
                        "name": "name",
                        "type": "varchar",
                        "size": 100,
                        "nullable": False
                    },
                    {
                        "name": "data",
                        "type": "jsonb",
                        "nullable": True
                    },
                    {
                        "name": "is_active",
                        "type": "boolean",
                        "default": True
                    },
                    {
                        "name": "created_at",
                        "type": "timestamp",
                        "default": {
                            "postgres": "NOW()",
                            "sqlite": "CURRENT_TIMESTAMP"
                        }
                    }
                ],
                "indexes": [
                    {
                        "name": "idx_test_name",
                        "columns": ["name"]
                    },
                    {
                        "name": "idx_test_active",
                        "columns": ["is_active"],
                        "where": "is_active = TRUE"
                    }
                ]
            }
        },
        "views": {
            "test_view": {
                "description": "Test view",
                "definition": {
                    "postgres": "SELECT id, name FROM test_table WHERE is_active = TRUE",
                    "sqlite": "SELECT id, name FROM test_table WHERE is_active = 1"
                }
            }
        }
    }


@pytest.fixture
def schema_file(sample_schema, tmp_path):
    """Create a temporary schema file"""
    schema_path = tmp_path / "schema.yaml"
    with open(schema_path, 'w') as f:
        yaml.dump(sample_schema, f)
    return str(schema_path)


class TestSchemaCompiler:
    """Test cases for SchemaCompiler"""

    def test_load_schema(self, schema_file):
        """Test loading schema from YAML file"""
        compiler = SchemaCompiler(schema_path=schema_file)
        assert compiler.schema['version'] == "1.0.0"
        assert 'test_table' in compiler.schema['tables']

    def test_get_type_mapping_postgres(self, schema_file):
        """Test PostgreSQL type mapping"""
        compiler = SchemaCompiler(schema_path=schema_file)
        assert compiler.get_type_mapping('uuid', 'postgres') == 'UUID'
        assert compiler.get_type_mapping('jsonb', 'postgres') == 'JSONB'
        assert compiler.get_type_mapping('timestamp', 'postgres') == 'TIMESTAMPTZ'

    def test_get_type_mapping_sqlite(self, schema_file):
        """Test SQLite type mapping"""
        compiler = SchemaCompiler(schema_path=schema_file)
        assert compiler.get_type_mapping('uuid', 'sqlite') == 'TEXT'
        assert compiler.get_type_mapping('jsonb', 'sqlite') == 'TEXT'
        assert compiler.get_type_mapping('timestamp', 'sqlite') == 'TEXT'

    def test_get_default_value_postgres(self, schema_file):
        """Test getting default values for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        # Dict-based default
        column = {
            "name": "id",
            "type": "uuid",
            "default": {
                "postgres": "gen_random_uuid()",
                "sqlite": "lower(hex(randomblob(16)))"
            }
        }
        assert compiler.get_default_value(column, 'postgres') == "gen_random_uuid()"

        # Boolean default
        column = {"name": "flag", "type": "boolean", "default": True}
        assert compiler.get_default_value(column, 'postgres') == "TRUE"

    def test_get_default_value_sqlite(self, schema_file):
        """Test getting default values for SQLite"""
        compiler = SchemaCompiler(schema_path=schema_file)

        # Dict-based default
        column = {
            "name": "id",
            "type": "uuid",
            "default": {
                "postgres": "gen_random_uuid()",
                "sqlite": "lower(hex(randomblob(16)))"
            }
        }
        assert compiler.get_default_value(column, 'sqlite') == "lower(hex(randomblob(16)))"

        # Boolean default
        column = {"name": "flag", "type": "boolean", "default": True}
        assert compiler.get_default_value(column, 'sqlite') == "1"

        column = {"name": "flag", "type": "boolean", "default": False}
        assert compiler.get_default_value(column, 'sqlite') == "0"

    def test_compile_column_definition_postgres(self, schema_file):
        """Test compiling column definition for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        column = {
            "name": "name",
            "type": "varchar",
            "size": 100,
            "nullable": False
        }

        col_def = compiler.compile_column_definition(column, 'postgres')
        assert "name" in col_def
        assert "VARCHAR(100)" in col_def
        assert "NOT NULL" in col_def

    def test_compile_column_definition_sqlite(self, schema_file):
        """Test compiling column definition for SQLite"""
        compiler = SchemaCompiler(schema_path=schema_file)

        column = {
            "name": "data",
            "type": "jsonb",
            "nullable": True
        }

        col_def = compiler.compile_column_definition(column, 'sqlite')
        assert "data" in col_def
        assert "TEXT" in col_def  # JSONB mapped to TEXT

    def test_compile_table_postgres(self, schema_file):
        """Test compiling table definition for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        table_def = compiler.schema['tables']['test_table']
        table_sql = compiler.compile_table('test_table', table_def, 'postgres')

        assert "CREATE TABLE IF NOT EXISTS test_table" in table_sql
        assert "id UUID PRIMARY KEY" in table_sql
        assert "name VARCHAR(100) NOT NULL" in table_sql
        assert "data JSONB" in table_sql
        assert "is_active BOOLEAN" in table_sql

    def test_compile_table_sqlite(self, schema_file):
        """Test compiling table definition for SQLite"""
        compiler = SchemaCompiler(schema_path=schema_file)

        table_def = compiler.schema['tables']['test_table']
        table_sql = compiler.compile_table('test_table', table_def, 'sqlite')

        assert "CREATE TABLE IF NOT EXISTS test_table" in table_sql
        assert "id TEXT PRIMARY KEY" in table_sql
        assert "name VARCHAR(100) NOT NULL" in table_sql
        assert "data TEXT" in table_sql  # JSONB -> TEXT
        assert "is_active INTEGER" in table_sql  # BOOLEAN -> INTEGER

    def test_compile_indexes_postgres(self, schema_file):
        """Test compiling indexes for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        table_def = compiler.schema['tables']['test_table']
        indexes = compiler.compile_indexes('test_table', table_def, 'postgres')

        assert len(indexes) == 2
        assert any("idx_test_name" in idx for idx in indexes)
        assert any("WHERE is_active = TRUE" in idx for idx in indexes)

    def test_compile_indexes_sqlite(self, schema_file):
        """Test compiling indexes for SQLite"""
        compiler = SchemaCompiler(schema_path=schema_file)

        table_def = compiler.schema['tables']['test_table']
        indexes = compiler.compile_indexes('test_table', table_def, 'sqlite')

        assert len(indexes) == 2
        assert any("idx_test_name" in idx for idx in indexes)
        # Boolean conversion for SQLite
        assert any("WHERE is_active = 1" in idx for idx in indexes)

    def test_compile_views_postgres(self, schema_file):
        """Test compiling views for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        views = compiler.compile_views('postgres')
        assert len(views) == 1
        assert "CREATE OR REPLACE VIEW test_view" in views[0]
        assert "WHERE is_active = TRUE" in views[0]

    def test_compile_views_sqlite(self, schema_file):
        """Test compiling views for SQLite"""
        compiler = SchemaCompiler(schema_path=schema_file)

        views = compiler.compile_views('sqlite')
        assert len(views) == 1
        assert "CREATE OR REPLACE VIEW test_view" in views[0]
        assert "WHERE is_active = 1" in views[0]

    def test_compile_extensions_postgres(self, schema_file):
        """Test compiling extensions for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=schema_file)

        extensions = compiler.compile_extensions('postgres')
        assert len(extensions) == 1
        assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' in extensions[0]

    def test_compile_extensions_sqlite(self, schema_file):
        """Test that SQLite returns no extensions"""
        compiler = SchemaCompiler(schema_path=schema_file)

        extensions = compiler.compile_extensions('sqlite')
        assert len(extensions) == 0

    def test_compile_migration_postgres(self, schema_file):
        """Test compiling complete PostgreSQL migration"""
        compiler = SchemaCompiler(schema_path=schema_file)

        migration_sql = compiler.compile_migration('postgres')

        # Check header
        assert "Rufus SDK - POSTGRES Schema" in migration_sql
        assert "Generated from" in migration_sql

        # Check extensions
        assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' in migration_sql

        # Check table
        assert "CREATE TABLE IF NOT EXISTS test_table" in migration_sql

        # Check indexes
        assert "CREATE INDEX IF NOT EXISTS idx_test_name" in migration_sql

        # Check views
        assert "CREATE OR REPLACE VIEW test_view" in migration_sql

        # Check comments
        assert "COMMENT ON TABLE test_table" in migration_sql

    def test_compile_migration_sqlite(self, schema_file):
        """Test compiling complete SQLite migration"""
        compiler = SchemaCompiler(schema_path=schema_file)

        migration_sql = compiler.compile_migration('sqlite')

        # Check header
        assert "Rufus SDK - SQLITE Schema" in migration_sql
        assert "Generated from" in migration_sql

        # Check table with type conversions
        assert "CREATE TABLE IF NOT EXISTS test_table" in migration_sql
        assert "id TEXT" in migration_sql
        assert "data TEXT" in migration_sql
        assert "is_active INTEGER" in migration_sql

        # Check indexes with boolean conversion
        assert "CREATE INDEX IF NOT EXISTS idx_test_name" in migration_sql
        assert "WHERE is_active = 1" in migration_sql

        # Check views
        assert "CREATE OR REPLACE VIEW test_view" in migration_sql

    def test_write_migration(self, schema_file, tmp_path):
        """Test writing migration to file"""
        compiler = SchemaCompiler(schema_path=schema_file)

        output_path = tmp_path / "test_migration.sql"
        compiler.write_migration('postgres', str(output_path))

        assert output_path.exists()

        with open(output_path, 'r') as f:
            content = f.read()
            assert "CREATE TABLE IF NOT EXISTS test_table" in content


class TestRealSchema:
    """Test with actual rufus schema.yaml"""

    @pytest.fixture
    def rufus_schema_path(self):
        """Get path to actual rufus schema.yaml"""
        schema_path = Path(__file__).parent.parent / "migrations" / "schema.yaml"
        if not schema_path.exists():
            pytest.skip("Rufus schema.yaml not found")
        return str(schema_path)

    def test_compile_rufus_postgres(self, rufus_schema_path):
        """Test compiling actual rufus schema for PostgreSQL"""
        compiler = SchemaCompiler(schema_path=rufus_schema_path)
        migration_sql = compiler.compile_migration('postgres')

        # Check for all expected tables
        expected_tables = [
            'workflow_executions',
            'tasks',
            'compensation_log',
            'workflow_audit_log',
            'workflow_execution_logs',
            'workflow_metrics'
        ]

        for table in expected_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in migration_sql

        # Check for triggers
        assert "CREATE TRIGGER workflow_executions_updated_at" in migration_sql
        assert "CREATE TRIGGER workflow_update_trigger" in migration_sql

        # Check for views
        assert "CREATE OR REPLACE VIEW active_workflows" in migration_sql
        assert "CREATE OR REPLACE VIEW workflow_execution_summary" in migration_sql

    def test_compile_rufus_sqlite(self, rufus_schema_path):
        """Test compiling actual rufus schema for SQLite"""
        compiler = SchemaCompiler(schema_path=rufus_schema_path)
        migration_sql = compiler.compile_migration('sqlite')

        # Check for all expected tables with type conversions
        assert "CREATE TABLE IF NOT EXISTS workflow_executions" in migration_sql
        assert "id TEXT PRIMARY KEY" in migration_sql  # UUID -> TEXT

        # Verify no PostgreSQL-specific types
        assert "UUID" not in migration_sql
        assert "JSONB" not in migration_sql
        assert "TIMESTAMPTZ" not in migration_sql
        assert "BOOLEAN" not in migration_sql

        # Check for SQLite triggers
        assert "CREATE TRIGGER IF NOT EXISTS workflow_executions_updated_at" in migration_sql

        # Check for views with SQLite-specific SQL
        assert "CREATE OR REPLACE VIEW active_workflows" in migration_sql
        assert "julianday" in migration_sql  # SQLite date function


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
