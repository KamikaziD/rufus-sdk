"""
Input collection module for interactive workflow execution.

Handles schema-based input collection using Rich prompts.
"""

from typing import Dict, Any, Optional, List
from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
import json


class InputCollector:
    """
    Collects user input based on schema definitions.

    Supports various input types:
    - string: Text input
    - boolean: Yes/No confirmation
    - integer: Integer number input
    - float: Floating point number input
    - json: JSON object/array input
    - choice: Selection from predefined options
    """

    def __init__(self, console: Optional[Console] = None):
        """
        Initialize input collector.

        Args:
            console: Rich Console instance for output (creates new if None)
        """
        self.console = console or Console()

    def collect_from_schema(self, schema: List[Dict[str, Any]], step_name: str = None) -> Dict[str, Any]:
        """
        Collect input based on schema definition.

        Args:
            schema: List of input field definitions
            step_name: Optional step name for context display

        Returns:
            Dictionary of collected input values

        Schema Format:
            [
                {
                    "name": "field_name",
                    "type": "string|boolean|integer|float|json|choice",
                    "prompt": "Prompt text to display",
                    "description": "Optional field description",
                    "required": true|false,
                    "default": "default_value",
                    "choices": ["opt1", "opt2"]  # For type: choice
                }
            ]
        """
        if not schema:
            return {}

        # Display header
        if step_name:
            self.console.print(f"\n[bold cyan]Input Required for Step: {step_name}[/bold cyan]")
        else:
            self.console.print(f"\n[bold cyan]Input Required[/bold cyan]")

        self.console.print()

        collected = {}

        for field in schema:
            field_name = field.get("name")
            field_type = field.get("type", "string")
            prompt_text = field.get("prompt", f"Enter {field_name}")
            description = field.get("description")
            required = field.get("required", True)
            default = field.get("default")
            choices = field.get("choices", [])

            # Show field description if provided
            if description:
                self.console.print(f"[dim]{description}[/dim]")

            # Collect based on type
            try:
                value = self._collect_field(
                    field_name=field_name,
                    field_type=field_type,
                    prompt_text=prompt_text,
                    required=required,
                    default=default,
                    choices=choices
                )

                if value is not None or required:
                    collected[field_name] = value

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Input collection cancelled[/yellow]")
                raise
            except Exception as e:
                self.console.print(f"[red]Error collecting {field_name}: {e}[/red]")
                if required:
                    raise

        return collected

    def _collect_field(
        self,
        field_name: str,
        field_type: str,
        prompt_text: str,
        required: bool,
        default: Any,
        choices: List[str]
    ) -> Any:
        """
        Collect a single field based on type.

        Args:
            field_name: Field name
            field_type: Field type (string, boolean, integer, float, json, choice)
            prompt_text: Prompt text to display
            required: Whether field is required
            default: Default value
            choices: List of choices (for choice type)

        Returns:
            Collected value
        """
        # Add optional indicator to prompt
        if not required:
            prompt_text += " [dim](optional)[/dim]"

        if field_type == "boolean":
            return Confirm.ask(prompt_text, default=default if default is not None else True)

        elif field_type == "integer":
            while True:
                try:
                    value = IntPrompt.ask(prompt_text, default=default)
                    return value
                except Exception:
                    if not required and default is None:
                        return None
                    self.console.print("[red]Please enter a valid integer[/red]")

        elif field_type == "float":
            while True:
                try:
                    value = FloatPrompt.ask(prompt_text, default=default)
                    return value
                except Exception:
                    if not required and default is None:
                        return None
                    self.console.print("[red]Please enter a valid number[/red]")

        elif field_type == "choice":
            if not choices:
                raise ValueError(f"Field {field_name} is type 'choice' but no choices provided")

            self.console.print(f"\n{prompt_text}")
            for idx, choice in enumerate(choices, 1):
                self.console.print(f"  {idx}. {choice}")

            while True:
                selection = Prompt.ask(
                    "Select option (number or text)",
                    default=str(default) if default is not None else None
                )

                # Try as index
                if selection.isdigit():
                    idx = int(selection) - 1
                    if 0 <= idx < len(choices):
                        return choices[idx]

                # Try as exact match
                if selection in choices:
                    return selection

                # Try as partial match
                matches = [c for c in choices if selection.lower() in c.lower()]
                if len(matches) == 1:
                    return matches[0]

                if not required and selection == "":
                    return default

                self.console.print(f"[red]Invalid choice. Please select 1-{len(choices)} or enter choice text[/red]")

        elif field_type == "json":
            while True:
                value_str = Prompt.ask(
                    prompt_text + " [dim](JSON format)[/dim]",
                    default=json.dumps(default) if default is not None else None
                )

                if not value_str and not required:
                    return default

                try:
                    return json.loads(value_str)
                except json.JSONDecodeError as e:
                    self.console.print(f"[red]Invalid JSON: {e}[/red]")
                    if not required:
                        return default

        else:  # string (default)
            value = Prompt.ask(prompt_text, default=default)

            if not value and not required:
                return default

            return value

    def collect_free_form(self, prompt_text: str = "Enter input") -> Dict[str, Any]:
        """
        Collect free-form JSON input.

        Args:
            prompt_text: Prompt text to display

        Returns:
            Dictionary of collected input
        """
        self.console.print(f"\n[bold cyan]{prompt_text}[/bold cyan]")
        self.console.print("[dim]Enter JSON object (e.g., {\"key\": \"value\"})[/dim]")
        self.console.print("[dim]Or press Enter to skip[/dim]\n")

        while True:
            value_str = Prompt.ask("Input", default="{}")

            if value_str == "{}":
                return {}

            try:
                return json.loads(value_str)
            except json.JSONDecodeError as e:
                self.console.print(f"[red]Invalid JSON: {e}[/red]")
                self.console.print("[yellow]Try again or press Ctrl+C to cancel[/yellow]")

    def confirm_action(self, action: str, details: Dict[str, Any] = None) -> bool:
        """
        Confirm an action with optional details display.

        Args:
            action: Action description
            details: Optional details to display

        Returns:
            True if confirmed, False otherwise
        """
        self.console.print()

        if details:
            self.console.print(Panel(
                json.dumps(details, indent=2),
                title=f"[bold]{action}[/bold]",
                border_style="cyan"
            ))

        return Confirm.ask(f"\n[bold yellow]{action}?[/bold yellow]", default=False)

    def display_info(self, title: str, content: str, markdown: bool = False):
        """
        Display information to user.

        Args:
            title: Panel title
            content: Content to display
            markdown: Whether to render content as Markdown
        """
        if markdown:
            content_renderable = Markdown(content)
        else:
            content_renderable = content

        self.console.print(Panel(
            content_renderable,
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan"
        ))
