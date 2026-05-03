#!/usr/bin/env python3
"""
Ruvon SDK Schema Compiler

Compiles the unified YAML schema definition (migrations/schema.yaml) into
database-specific SQL migration scripts for PostgreSQL and SQLite.

Usage:
    python tools/compile_schema.py --target postgres --output migrations/002_postgres_standardized.sql
    python tools/compile_schema.py --target sqlite --output migrations/002_sqlite_initial.sql
    python tools/compile_schema.py --all  # Generate both
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml


class SchemaCompiler:
    """Compiles unified YAML schema to database-specific SQL"""

    def __init__(self, schema_path: str = "migrations/schema.yaml"):
        self.schema_path = Path(schema_path)
        self.schema: Dict[str, Any] = {}
        self.load_schema()

    def load_schema(self):
        """Load and parse the YAML schema file"""
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self.schema_path}")

        with open(self.schema_path, 'r') as f:
            self.schema = yaml.safe_load(f)

        print(f"✓ Loaded schema version {self.schema.get('version', 'unknown')}")

    def get_type_mapping(self, column_type: str, target_db: str) -> str:
        """Get the database-specific type for a column"""
        type_mappings = self.schema.get('type_mappings', {})

        if column_type not in type_mappings:
            # Direct type (e.g., 'text', 'integer')
            return column_type.upper()

        db_type = type_mappings[column_type].get(target_db)
        if not db_type:
            raise ValueError(f"No type mapping for '{column_type}' in {target_db}")

        return db_type

    def get_default_value(self, column: Dict[str, Any], target_db: str) -> Optional[str]:
        """Get the database-specific default value for a column"""
        default = column.get('default')

        if default is None:
            return None

        # Database-specific defaults
        if isinstance(default, dict):
            return default.get(target_db)

        # Simple scalar default
        if isinstance(default, bool):
            if target_db == 'sqlite':
                return '1' if default else '0'
            return 'TRUE' if default else 'FALSE'

        if isinstance(default, (int, float)):
            return str(default)

        return default

    def compile_column_definition(self, column: Dict[str, Any], target_db: str) -> str:
        """Compile a single column definition to SQL"""
        parts = []

        # Column name
        parts.append(column['name'])

        # Column type
        col_type = self.get_type_mapping(column['type'], target_db)

        # Add size for VARCHAR
        if column['type'] == 'varchar' and 'size' in column:
            col_type = f"VARCHAR({column['size']})"

        parts.append(col_type)

        # Primary key
        if column.get('primary_key'):
            if target_db == 'sqlite' and column['type'] == 'bigserial':
                parts.append("PRIMARY KEY AUTOINCREMENT")
            elif target_db == 'postgres' and column['type'] != 'bigserial':
                # bigserial doesn't need PRIMARY KEY in type definition
                parts.append("PRIMARY KEY")
            elif target_db == 'postgres':
                pass  # PRIMARY KEY added after table
            else:
                parts.append("PRIMARY KEY")

        # Nullable
        if column.get('nullable') is False:
            parts.append("NOT NULL")
        elif column.get('nullable') is True:
            # Explicit NULL (usually omitted)
            pass

        # Default value
        default_val = self.get_default_value(column, target_db)
        if default_val:
            parts.append(f"DEFAULT {default_val}")

        # Unique constraint
        if column.get('unique'):
            parts.append("UNIQUE")

        return " ".join(parts)

    def compile_table(self, table_name: str, table_def: Dict[str, Any], target_db: str) -> str:
        """Compile a table definition to CREATE TABLE statement"""
        lines = []

        # Table comment
        description = table_def.get('description', '')
        lines.append(f"-- {description}")

        # CREATE TABLE
        lines.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")

        # Columns
        column_defs = []
        foreign_keys = []
        primary_key_cols = []

        for column in table_def['columns']:
            col_def = self.compile_column_definition(column, target_db)
            column_defs.append(f"    {col_def}")

            # Collect foreign keys
            if 'foreign_key' in column:
                fk = column['foreign_key']
                fk_def = self._compile_foreign_key(
                    column['name'],
                    fk['table'],
                    fk['column'],
                    fk.get('on_delete', 'NO ACTION'),
                    target_db
                )
                foreign_keys.append(f"    {fk_def}")

            # Collect primary keys for composite keys or bigserial
            if column.get('primary_key') and column['type'] == 'bigserial' and target_db == 'postgres':
                primary_key_cols.append(column['name'])

        # Add primary key constraint for bigserial (PostgreSQL)
        if primary_key_cols and target_db == 'postgres':
            column_defs.append(f"    PRIMARY KEY ({', '.join(primary_key_cols)})")

        # Combine columns and foreign keys
        all_defs = column_defs + foreign_keys

        lines.append(",\n".join(all_defs))
        lines.append(");")

        return "\n".join(lines)

    def _compile_foreign_key(
        self,
        column: str,
        ref_table: str,
        ref_column: str,
        on_delete: str,
        target_db: str
    ) -> str:
        """Compile a foreign key constraint"""
        return f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) ON DELETE {on_delete}"

    def compile_indexes(self, table_name: str, table_def: Dict[str, Any], target_db: str) -> List[str]:
        """Compile all indexes for a table"""
        indexes = []

        for index in table_def.get('indexes', []):
            index_sql = self._compile_index(table_name, index, target_db)
            indexes.append(index_sql)

        return indexes

    def _compile_index(self, table_name: str, index: Dict[str, Any], target_db: str) -> str:
        """Compile a single index definition"""
        parts = ["CREATE INDEX IF NOT EXISTS"]

        parts.append(index['name'])
        parts.append("ON")
        parts.append(table_name)

        # Column list with optional ordering
        columns = []
        for col in index['columns']:
            col_expr = col
            # Check for ordering
            if 'order' in index and col in index['order']:
                order = index['order'][col]
                col_expr = f"{col} {order}"
            columns.append(col_expr)

        parts.append(f"({', '.join(columns)})")

        # WHERE clause (partial index)
        if 'where' in index:
            where_clause = index['where']
            # SQLite boolean conversion
            if target_db == 'sqlite':
                where_clause = where_clause.replace('= TRUE', '= 1')
                where_clause = where_clause.replace('= FALSE', '= 0')
            parts.append(f"WHERE {where_clause}")

        return " ".join(parts) + ";"

    def compile_triggers(self, target_db: str) -> List[str]:
        """Compile all triggers for the target database"""
        triggers = []

        trigger_defs = self.schema.get('triggers', {}).get(target_db, [])

        for trigger in trigger_defs:
            trigger_sql = self._compile_trigger(trigger, target_db)
            triggers.append(trigger_sql)

        return triggers

    def _compile_trigger(self, trigger: Dict[str, Any], target_db: str) -> str:
        """Compile a single trigger definition"""
        lines = []

        if target_db == 'postgres':
            # PostgreSQL: Create function first, then trigger
            if 'function' in trigger:
                # Check if function is a full definition or a reference
                func_def = trigger['function']
                if func_def.startswith('CREATE OR REPLACE FUNCTION'):
                    lines.append(func_def)
                    lines.append("")

            # Create trigger
            lines.append(f"CREATE TRIGGER {trigger['name']}")
            lines.append(f"{trigger['timing']} ON {trigger['table']}")
            lines.append(f"FOR EACH {trigger['for_each']}")

            # Get function name from trigger or definition
            func_name = trigger.get('function')
            if func_name and not func_name.startswith('CREATE'):
                lines.append(f"EXECUTE FUNCTION {func_name}();")
            elif 'function' in trigger:
                # Extract function name from CREATE FUNCTION
                func_def = trigger['function']
                func_name = func_def.split('FUNCTION')[1].split('(')[0].strip()
                lines.append(f"EXECUTE FUNCTION {func_name}();")

        elif target_db == 'sqlite':
            # SQLite: Inline trigger action
            lines.append(f"CREATE TRIGGER IF NOT EXISTS {trigger['name']}")
            lines.append(f"{trigger['timing']} ON {trigger['table']}")
            lines.append(f"FOR EACH {trigger['for_each']}")

            if 'when' in trigger:
                lines.append(f"WHEN {trigger['when']}")

            lines.append("BEGIN")
            lines.append(f"    {trigger['action']}")
            lines.append("END;")

        return "\n".join(lines)

    def compile_views(self, target_db: str) -> List[str]:
        """Compile all views for the target database"""
        views = []

        view_defs = self.schema.get('views', {})

        for view_name, view_def in view_defs.items():
            view_sql = self._compile_view(view_name, view_def, target_db)
            views.append(view_sql)

        return views

    def _compile_view(self, view_name: str, view_def: Dict[str, Any], target_db: str) -> str:
        """Compile a single view definition"""
        lines = []

        description = view_def.get('description', '')
        lines.append(f"-- {description}")

        definition = view_def['definition'].get(target_db)
        if not definition:
            raise ValueError(f"No definition for view '{view_name}' in {target_db}")

        lines.append(f"CREATE OR REPLACE VIEW {view_name} AS")
        lines.append(definition)

        return "\n".join(lines) + ";"

    def compile_extensions(self, target_db: str) -> List[str]:
        """Compile database extensions (PostgreSQL only)"""
        if target_db != 'postgres':
            return []

        extensions = self.schema.get('extensions', {}).get('postgres', [])
        sql_statements = []

        for ext in extensions:
            sql_statements.append(f'CREATE EXTENSION IF NOT EXISTS "{ext}";')

        return sql_statements

    def compile_migration(self, target_db: str) -> str:
        """Compile the complete migration script for target database"""
        lines = []

        # Header
        lines.append(f"-- Ruvon SDK - {target_db.upper()} Schema")
        lines.append(f"-- Generated from migrations/schema.yaml v{self.schema.get('version')}")
        lines.append(f"-- DO NOT EDIT MANUALLY - Use tools/compile_schema.py")
        lines.append("")

        # Extensions
        extensions = self.compile_extensions(target_db)
        if extensions:
            lines.append("-- ============================================================================")
            lines.append("-- EXTENSIONS")
            lines.append("-- ============================================================================")
            for ext in extensions:
                lines.append(ext)
            lines.append("")

        # Tables
        lines.append("-- ============================================================================")
        lines.append("-- TABLES")
        lines.append("-- ============================================================================")
        lines.append("")

        tables = self.schema.get('tables', {})
        for table_name, table_def in tables.items():
            table_sql = self.compile_table(table_name, table_def, target_db)
            lines.append(table_sql)
            lines.append("")

        # Indexes
        lines.append("-- ============================================================================")
        lines.append("-- INDEXES")
        lines.append("-- ============================================================================")
        lines.append("")

        for table_name, table_def in tables.items():
            indexes = self.compile_indexes(table_name, table_def, target_db)
            if indexes:
                lines.append(f"-- Indexes for {table_name}")
                for idx_sql in indexes:
                    lines.append(idx_sql)
                lines.append("")

        # Triggers
        triggers = self.compile_triggers(target_db)
        if triggers:
            lines.append("-- ============================================================================")
            lines.append("-- TRIGGERS")
            lines.append("-- ============================================================================")
            lines.append("")

            for trigger_sql in triggers:
                lines.append(trigger_sql)
                lines.append("")

        # Views
        views = self.compile_views(target_db)
        if views:
            lines.append("-- ============================================================================")
            lines.append("-- VIEWS")
            lines.append("-- ============================================================================")
            lines.append("")

            for view_sql in views:
                lines.append(view_sql)
                lines.append("")

        # Comments (PostgreSQL only)
        if target_db == 'postgres':
            lines.append("-- ============================================================================")
            lines.append("-- TABLE COMMENTS")
            lines.append("-- ============================================================================")
            lines.append("")

            for table_name, table_def in tables.items():
                description = table_def.get('description', '')
                if description:
                    lines.append(f"COMMENT ON TABLE {table_name} IS '{description}';")

            lines.append("")

        return "\n".join(lines)

    def write_migration(self, target_db: str, output_path: str):
        """Generate and write migration file"""
        migration_sql = self.compile_migration(target_db)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            f.write(migration_sql)

        print(f"✓ Generated {target_db} migration: {output_path}")
        print(f"  Lines: {len(migration_sql.splitlines())}")


def main():
    parser = argparse.ArgumentParser(
        description="Compile unified YAML schema to database-specific SQL"
    )
    parser.add_argument(
        '--target',
        choices=['postgres', 'sqlite'],
        help='Target database (postgres or sqlite)'
    )
    parser.add_argument(
        '--output',
        help='Output SQL file path'
    )
    parser.add_argument(
        '--schema',
        default='migrations/schema.yaml',
        help='Path to schema.yaml file (default: migrations/schema.yaml)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Generate migrations for all databases'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.all and (not args.target or not args.output):
        parser.error("Either --all or both --target and --output are required")

    try:
        compiler = SchemaCompiler(schema_path=args.schema)

        if args.all:
            # Generate both PostgreSQL and SQLite
            compiler.write_migration('postgres', 'migrations/002_postgres_standardized.sql')
            compiler.write_migration('sqlite', 'migrations/002_sqlite_initial.sql')
            print("\n✓ Successfully generated migrations for both databases")
        else:
            # Generate single target
            compiler.write_migration(args.target, args.output)
            print(f"\n✓ Successfully generated {args.target} migration")

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
