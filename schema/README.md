# Ruvon Workflow JSON Schema

This directory contains JSON Schema definitions for Ruvon workflow YAML files. These schemas provide IDE autocomplete, validation, and documentation for workflow definitions.

## Files

- **`workflow_schema.json`** - Complete schema for workflow YAML files
- **`workflow_registry_schema.json`** - Schema for workflow registry files

## IDE Integration

### VS Code

VS Code provides automatic validation and autocomplete for YAML files that reference a JSON Schema.

**Option 1: Add `$schema` reference to your workflow files (Recommended)**

Add this line at the top of your workflow YAML files:

```yaml
# yaml-language-server: $schema=../../schema/workflow_schema.json
workflow_type: "MyWorkflow"
workflow_version: "1.0"
initial_state_model: "state_models.MyWorkflowState"
steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "steps.process_data"
```

VS Code will now provide:
- **Autocomplete** for step types, merge strategies, etc.
- **Validation** warnings for missing required fields
- **Hover documentation** for all fields
- **Error highlighting** for invalid values

**Option 2: Configure in `.vscode/settings.json`**

Create or edit `.vscode/settings.json` in your project root:

```json
{
  "yaml.schemas": {
    "./schema/workflow_schema.json": ["*_workflow.yaml", "workflows/*.yaml"],
    "./schema/workflow_registry_schema.json": ["**/workflow_registry.yaml"]
  }
}
```

This applies schemas automatically based on file patterns.

### IntelliJ IDEA / PyCharm

1. Open Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings
2. Click `+` to add new mapping
3. **Name**: Ruvon Workflow Schema
4. **Schema file or URL**: Browse to `schema/workflow_schema.json`
5. **Schema version**: JSON Schema version 7
6. **File path pattern**: Add patterns like `**/*_workflow.yaml`

### Sublime Text

Install the LSP and LSP-yaml packages:

1. Install Package Control
2. Install `LSP` and `LSP-yaml` packages
3. Add to LSP-yaml settings:

```json
{
  "settings": {
    "yaml.schemas": {
      "/path/to/ruvon-sdk/schema/workflow_schema.json": ["*_workflow.yaml"]
    }
  }
}
```

## CLI Validation

Use the enhanced `ruvon validate` command with JSON Schema validation:

```bash
# Basic validation (structure and references)
ruvon validate workflow.yaml

# Strict validation (includes function imports)
ruvon validate workflow.yaml --strict

# JSON output for CI/CD
ruvon validate workflow.yaml --json
```

The validator checks:
- ✅ JSON Schema compliance (if `jsonschema` installed)
- ✅ Required fields present
- ✅ Step dependencies reference existing steps
- ✅ Route targets reference existing steps
- ✅ Parallel task configuration
- ✅ Function paths can be imported (strict mode)
- ✅ State model is valid Pydantic class (strict mode)

### Install jsonschema for Full Validation

```bash
pip install jsonschema
```

Without jsonschema, validation still works but skips schema-level checks.

## Schema Features

### Step Type Validation

The schema enforces type-specific requirements:

```yaml
# PARALLEL step - requires "tasks"
- name: "Parallel_Tasks"
  type: "PARALLEL"
  tasks:  # Required for PARALLEL
    - name: "Task1"
      function: "module.task1"

# HTTP step - requires "http_config"
- name: "Call_API"
  type: "HTTP"
  http_config:  # Required for HTTP
    url: "https://api.example.com"
    method: "POST"

# LOOP step - requires "loop_body" and "mode"
- name: "Process_Items"
  type: "LOOP"
  mode: "ITERATE"  # Required
  loop_body:  # Required
    - name: "Process_Item"
      function: "module.process"
```

### Autocomplete Examples

When editing YAML files with schema support, you'll get autocomplete for:

**Step types**:
```yaml
steps:
  - name: "My_Step"
    type: "S"  # Autocomplete suggests: STANDARD, ASYNC, HTTP, PARALLEL, etc.
```

**Merge strategies**:
```yaml
- name: "Parallel_Step"
  type: "PARALLEL"
  merge_strategy: "S"  # Autocomplete suggests: SHALLOW, DEEP, REPLACE, etc.
```

**Merge conflict behaviors**:
```yaml
merge_conflict_behavior: "P"  # Suggests: PREFER_NEW, PREFER_EXISTING, RAISE_ERROR
```

### Pattern Validation

The schema includes regex patterns to catch common errors:

```yaml
# ❌ Invalid: workflow_type must start with uppercase letter
workflow_type: "myWorkflow"  # Schema error!

# ✅ Valid
workflow_type: "MyWorkflow"

# ❌ Invalid: step names should be PascalCase
- name: "process_data"  # Warning in strict mode

# ✅ Valid
- name: "Process_Data"

# ❌ Invalid: function path format
function: "process_data"  # Schema error - must be "module.function"

# ✅ Valid
function: "steps.process_data"
```

## Common Validation Errors

### Missing Required Fields

```yaml
# ❌ Error: Missing "type" field
- name: "My_Step"
  function: "steps.my_step"

# ✅ Fixed
- name: "My_Step"
  type: "STANDARD"
  function: "steps.my_step"
```

### Invalid Dependency References

```yaml
steps:
  - name: "Step_A"
    type: "STANDARD"
    function: "steps.a"

  - name: "Step_B"
    dependencies: ["Step_C"]  # ❌ Error: Step_C doesn't exist!
```

CLI validation catches this:
```bash
$ ruvon validate workflow.yaml
✗ Validation failed for workflow.yaml

1 Error(s):
  1. Step 'Step_B': dependency 'Step_C' does not exist in workflow
```

### Type-Specific Requirements

```yaml
# ❌ Error: PARALLEL step missing "tasks"
- name: "Parallel_Step"
  type: "PARALLEL"
  # Missing tasks!

# ✅ Fixed
- name: "Parallel_Step"
  type: "PARALLEL"
  tasks:
    - name: "Task1"
      function: "module.task1"
```

## Extending the Schema

If you add custom step types or fields to Ruvon, update the schema:

1. Edit `workflow_schema.json`
2. Add new types to the `type` enum in the step definition
3. Add new fields to `properties`
4. Add conditional requirements to `allOf` section if needed

Example:
```json
{
  "properties": {
    "type": {
      "enum": [
        "STANDARD",
        "ASYNC",
        "MY_CUSTOM_TYPE"  // Add here
      ]
    },
    "my_custom_field": {  // Add custom field
      "type": "string",
      "description": "Custom field for MY_CUSTOM_TYPE"
    }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "type": { "const": "MY_CUSTOM_TYPE" }
        }
      },
      "then": {
        "required": ["my_custom_field"]  // Make required for this type
      }
    }
  ]
}
```

## Testing Schema Changes

After modifying the schema, test it:

```bash
# Validate an example workflow against the schema
ruvon validate examples/fastapi_api/order_workflow.yaml --strict

# Check all example workflows
for f in examples/**/*_workflow.yaml; do
    echo "Validating $f..."
    ruvon validate "$f"
done
```

## Benefits

1. **IDE Autocomplete**: Discover available fields and values
2. **Real-time Validation**: Catch errors as you type
3. **Documentation**: Hover tooltips explain each field
4. **Consistency**: Enforce naming conventions and structure
5. **CI/CD Integration**: Automated validation in pipelines
6. **Onboarding**: New developers learn workflow syntax faster

## Troubleshooting

**"Schema not found" errors in VS Code**:
- Ensure the `$schema` reference path is correct relative to the YAML file
- Check `.vscode/settings.json` has correct absolute or workspace-relative paths

**No autocomplete appearing**:
- Install YAML extension for VS Code: `redhat.vscode-yaml`
- Reload VS Code window after adding schema reference
- Check file is recognized as YAML (bottom right of VS Code)

**Validation seems too strict**:
- Use basic mode first: `ruvon validate workflow.yaml`
- Use `--strict` only when you want import checks
- Some warnings (like PascalCase naming) are suggestions, not errors

**Custom step types not recognized**:
- Update `workflow_schema.json` to include your custom types
- Restart IDE after schema changes
