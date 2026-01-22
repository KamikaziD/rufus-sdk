# {{ cookiecutter.project_name }}

This is a Rufus marketplace package providing custom workflow steps for {{ cookiecutter.project_name }}.

## Installation

```bash
pip install {{ cookiecutter.project_slug }}
```

## Usage

Once installed, Rufus will automatically discover the steps provided by this package. You can then use them directly in your workflow YAML:

```yaml
workflow_type: MyWorkflow

steps:
  - name: "ExampleStep"
    type: {{ cookiecutter.step_type_name_example }}
    # Add step-specific configuration here
    inputs:
      some_param: "value"
```

Refer to the `{{ cookiecutter.package_name }}/steps.py` file for details on available steps and their parameters.

## Development

To develop on this package, clone the repository and install in editable mode:

```bash
git clone https://github.com/{{ cookiecutter.github_username }}/{{ cookiecutter.project_slug }}.git
cd {{ cookiecutter.project_slug }}
pip install -e .
```

## License

{{ cookiecutter.license }} License. See the `LICENSE` file for more details.
