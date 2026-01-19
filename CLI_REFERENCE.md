# Rufus SDK - CLI Reference

The Rufus Command-Line Interface (CLI) provides a convenient way to interact with the Rufus SDK directly from your terminal. It's designed for developers to quickly validate workflow configurations, run workflows locally for testing, and perform other administrative tasks.

## Installation

The Rufus CLI is included as part of the main `rufus` package. Ensure you have Rufus installed in your Python environment:

```bash
pip install rufus
```

If you installed Rufus with the `dev` extra, the CLI is already available:

```bash
pip install rufus[dev]
```

## Usage

The main command for the CLI is `rufus`. You can get help information by running:

```bash
rufus --help
```

### `rufus validate`

The `validate` command checks your workflow YAML files for syntax errors and basic structural integrity. It helps catch common configuration mistakes early in the development cycle.

#### Usage

```bash
rufus validate <workflow_file>
```

*   `<workflow_file>`: Path to the workflow YAML file you want to validate.

#### Examples

Validate a single workflow file:

```bash
rufus validate config/my_loan_workflow.yaml
```

If the validation is successful, you will see a success message:

```
Successfully validated config/my_loan_workflow.yaml (basic checks passed).
```

If there are errors, the CLI will output a detailed error message.

### `rufus run`

The `run` command executes a Rufus workflow locally using in-memory persistence and synchronous execution. This is ideal for rapid prototyping, debugging, and testing workflows without needing a database or a distributed task queue.

#### Usage

```bash
rufus run <workflow_file> [OPTIONS]
```

*   `<workflow_file>`: Path to the workflow YAML file you want to run.

#### Options

*   `-d`, `--data <JSON_STRING>`: (Optional) Initial workflow data as a JSON string. Defaults to `{}`.
*   `-r`, `--registry <REGISTRY_PATH>`: (Optional) Path to the workflow registry YAML file. Defaults to `config/workflow_registry.yaml`.

#### Examples

Run a workflow with default initial data:

```bash
rufus run config/onboarding_workflow.yaml
```

Run a workflow with custom initial data (as a JSON string):

```bash
rufus run config/loan_application.yaml -d '{"applicant_name": "Jane Doe", "loan_amount": 10000}'
```

Run a workflow and specify a custom registry path:

```bash
rufus run my_workflows/my_specific_workflow.yaml --registry my_workflows/workflow_registry.yaml
```

During execution, the `run` command will print the workflow's progress, current state, and step results to the console.

### Common Usage Patterns

*   **Rapid Development Cycle**: Use `rufus validate` frequently to catch errors as you write your workflow YAMLs. Then, use `rufus run` to quickly test the end-to-end flow of your workflow logic locally.
*   **Debugging Step Functions**: When developing custom step functions, `rufus run` allows you to execute them in context and inspect how they modify the workflow state.
*   **Demoing Workflows**: Showcase workflow behavior without requiring a full server setup.

For more detailed information on defining workflows and implementing step functions, refer to the [Usage Guide](USAGE_GUIDE.md) and [YAML Guide](YAML_GUIDE.md).
