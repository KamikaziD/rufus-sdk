"""
Output formatting for Ruvon CLI.

Provides beautiful terminal output using the rich library.
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.tree import Tree
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class Formatter:
    """Base formatter for CLI output"""

    def __init__(self, use_rich: bool = True):
        """
        Initialize formatter.

        Args:
            use_rich: Whether to use rich library for formatting
        """
        self.use_rich = use_rich and RICH_AVAILABLE
        self.console = Console() if self.use_rich else None

    def print(self, text: str, style: Optional[str] = None) -> None:
        """
        Print text with optional styling.

        Args:
            text: Text to print
            style: Rich style (e.g., "bold green", "red")
        """
        if self.use_rich and self.console:
            self.console.print(text, style=style)
        else:
            print(text)

    def print_error(self, text: str) -> None:
        """Print error message"""
        self.print(f"❌ {text}", style="bold red")

    def print_success(self, text: str) -> None:
        """Print success message"""
        self.print(f"✅ {text}", style="bold green")

    def print_warning(self, text: str) -> None:
        """Print warning message"""
        self.print(f"⚠️  {text}", style="bold yellow")

    def print_info(self, text: str) -> None:
        """Print info message"""
        self.print(f"ℹ️  {text}", style="bold blue")


class WorkflowListFormatter(Formatter):
    """Formatter for workflow list output"""

    def format(self, workflows: List[Dict[str, Any]], verbose: bool = False, json_output: bool = False) -> None:
        """
        Format and print workflow list.

        Args:
            workflows: List of workflow dicts
            verbose: Whether to show verbose output
            json_output: Whether to output as JSON
        """
        if json_output:
            print(json.dumps(workflows, indent=2, default=str))
            return

        if not workflows:
            self.print_info("No workflows found")
            return

        if self.use_rich:
            self._format_rich_table(workflows, verbose)
        else:
            self._format_plain_table(workflows, verbose)

    def _format_rich_table(self, workflows: List[Dict[str, Any]], verbose: bool) -> None:
        """Format using rich table"""
        table = Table(title="Workflows", box=box.ROUNDED)

        # Add columns
        table.add_column("Workflow ID", style="cyan", no_wrap=True)
        table.add_column("Type", style="magenta")
        table.add_column("Status", style="yellow")
        table.add_column("Current Step", style="green")
        table.add_column("Created", style="blue")
        table.add_column("Updated", style="blue")

        if verbose:
            table.add_column("Priority", style="white")

        # Add rows
        for wf in workflows:
            status_style = self._get_status_style(wf.get("status", "UNKNOWN"))

            row = [
                wf.get("id", "N/A")[:16] + "...",  # Truncate long IDs
                wf.get("workflow_type", "N/A"),
                f"[{status_style}]{wf.get('status', 'UNKNOWN')}[/{status_style}]",
                wf.get("current_step_name", "-") or "-",
                self._format_timestamp(wf.get("created_at")),
                self._format_timestamp(wf.get("updated_at"))
            ]

            if verbose:
                row.append(str(wf.get("priority", 5)))

            table.add_row(*row)

        self.console.print(table)
        self.print(f"\nTotal: {len(workflows)} workflow(s)")

    def _format_plain_table(self, workflows: List[Dict[str, Any]], verbose: bool) -> None:
        """Format using plain text table"""
        # Header
        headers = ["WORKFLOW ID", "TYPE", "STATUS", "CURRENT STEP", "CREATED", "UPDATED"]
        if verbose:
            headers.append("PRIORITY")

        # Print header
        print("  ".join(f"{h:20}" for h in headers))
        print("-" * (22 * len(headers)))

        # Print rows
        for wf in workflows:
            row = [
                (wf.get("id", "N/A")[:18] + "..") if len(wf.get("id", "")) > 20 else wf.get("id", "N/A"),
                wf.get("workflow_type", "N/A")[:18],
                wf.get("status", "UNKNOWN")[:18],
                (wf.get("current_step_name", "-") or "-")[:18],
                self._format_timestamp(wf.get("created_at"))[:18],
                self._format_timestamp(wf.get("updated_at"))[:18]
            ]

            if verbose:
                row.append(str(wf.get("priority", 5))[:18])

            print("  ".join(f"{cell:20}" for cell in row))

        print(f"\nTotal: {len(workflows)} workflow(s)")

    def _get_status_style(self, status: str) -> str:
        """Get rich style for workflow status"""
        status_styles = {
            # Active states
            "ACTIVE": "bold green",
            "PENDING_ASYNC": "bold cyan",
            "PENDING_SUB_WORKFLOW": "bold cyan",
            # Paused/waiting states
            "PAUSED": "bold yellow",
            "WAITING_HUMAN": "bold yellow",
            "WAITING_HUMAN_INPUT": "bold yellow",
            "WAITING_CHILD_HUMAN_INPUT": "bold yellow",
            # Terminal states
            "COMPLETED": "bold blue",
            "FAILED": "bold red",
            "FAILED_ROLLED_BACK": "bold magenta",
            "FAILED_CHILD_WORKFLOW": "bold red",
            "CANCELLED": "bold dim",
        }
        return status_styles.get(status, "white")

    def _format_timestamp(self, ts: Optional[Any]) -> str:
        """Format timestamp for display"""
        if not ts:
            return "N/A"

        try:
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            elif isinstance(ts, datetime):
                dt = ts
            else:
                return str(ts)

            # Show relative time
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            delta = now - dt

            if delta.days > 0:
                return f"{delta.days}d ago"
            elif delta.seconds > 3600:
                return f"{delta.seconds // 3600}h ago"
            elif delta.seconds > 60:
                return f"{delta.seconds // 60}m ago"
            else:
                return f"{delta.seconds}s ago"
        except Exception:
            return str(ts)[:18]


class WorkflowDetailFormatter(Formatter):
    """Formatter for workflow detail output"""

    def format(self, workflow: Dict[str, Any], show_state: bool = False,
               show_logs: bool = False, show_metrics: bool = False,
               json_output: bool = False) -> None:
        """
        Format and print workflow details.

        Args:
            workflow: Workflow dict
            show_state: Whether to show full state
            show_logs: Whether to show logs
            show_metrics: Whether to show metrics
            json_output: Whether to output as JSON
        """
        if json_output:
            print(json.dumps(workflow, indent=2, default=str))
            return

        if self.use_rich:
            self._format_rich_detail(workflow, show_state, show_logs, show_metrics)
        else:
            self._format_plain_detail(workflow, show_state, show_logs, show_metrics)

    def _format_rich_detail(self, workflow: Dict[str, Any], show_state: bool,
                            show_logs: bool, show_metrics: bool) -> None:
        """Format using rich panels"""
        # Overview panel
        overview = f"""
[bold]Workflow:[/bold] {workflow.get('id', 'N/A')}
[bold]Type:[/bold] {workflow.get('workflow_type', 'N/A')}
[bold]Status:[/bold] [{self._get_status_style(workflow.get('status', 'UNKNOWN'))}]{workflow.get('status', 'UNKNOWN')}[/]
[bold]Current Step:[/bold] {workflow.get('current_step_name', '-') or '-'}
[bold]Created:[/bold] {workflow.get('created_at', 'N/A')}
[bold]Updated:[/bold] {workflow.get('updated_at', 'N/A')}
"""
        if workflow.get('completed_at'):
            overview += f"[bold]Completed:[/bold] {workflow.get('completed_at')}\n"

        self.console.print(Panel(overview.strip(), title="Overview", border_style="blue"))

        # State
        if show_state and workflow.get('state'):
            state_json = json.dumps(workflow['state'], indent=2)
            syntax = Syntax(state_json, "json", theme="monokai", line_numbers=False)
            self.console.print(Panel(syntax, title="State", border_style="green"))

        # Steps
        if workflow.get('steps_config'):
            self._format_steps_tree(workflow)

    def _format_plain_detail(self, workflow: Dict[str, Any], show_state: bool,
                             show_logs: bool, show_metrics: bool) -> None:
        """Format using plain text"""
        print(f"\nWorkflow: {workflow.get('id', 'N/A')}")
        print(f"Type: {workflow.get('workflow_type', 'N/A')}")
        print(f"Status: {workflow.get('status', 'UNKNOWN')}")
        print(f"Current Step: {workflow.get('current_step_name', '-') or '-'}")
        print(f"Created: {workflow.get('created_at', 'N/A')}")
        print(f"Updated: {workflow.get('updated_at', 'N/A')}")

        if workflow.get('completed_at'):
            print(f"Completed: {workflow.get('completed_at')}")

        if show_state and workflow.get('state'):
            print("\nState:")
            print(json.dumps(workflow['state'], indent=2))

        if workflow.get('steps_config'):
            print("\nSteps:")
            current_step = workflow.get('current_step', 0)
            for i, step in enumerate(workflow['steps_config']):
                status = "✅" if i < current_step else ("⏳" if i == current_step else "⏸")
                print(f"  {status} {step.get('name', 'N/A')}")

    def _format_steps_tree(self, workflow: Dict[str, Any]) -> None:
        """Format steps as a tree"""
        tree = Tree("[bold]Steps[/bold]")
        current_step_name = workflow.get('current_step')

        # Find the index of the current step by name
        steps_config = workflow.get('steps_config', [])
        current_step_index = None
        if current_step_name:
            for idx, step in enumerate(steps_config):
                if step.get('name') == current_step_name:
                    current_step_index = idx
                    break

        for i, step in enumerate(steps_config):
            if current_step_index is not None:
                if i < current_step_index:
                    status = "✅"
                    style = "green"
                elif i == current_step_index:
                    status = "⏳"
                    style = "yellow bold"
                else:
                    status = "⏸"
                    style = "dim"
            else:
                # No current step (workflow not started or completed)
                status = "⏸"
                style = "dim"

            step_name = step.get('name', 'N/A')
            tree.add(f"[{style}]{status} {step_name}[/{style}]")

        self.console.print(tree)

    def _get_status_style(self, status: str) -> str:
        """Get rich style for workflow status"""
        status_styles = {
            # Active states
            "ACTIVE": "bold green",
            "PENDING_ASYNC": "bold cyan",
            "PENDING_SUB_WORKFLOW": "bold cyan",
            # Paused/waiting states
            "PAUSED": "bold yellow",
            "WAITING_HUMAN": "bold yellow",
            "WAITING_HUMAN_INPUT": "bold yellow",
            "WAITING_CHILD_HUMAN_INPUT": "bold yellow",
            # Terminal states
            "COMPLETED": "bold blue",
            "FAILED": "bold red",
            "FAILED_ROLLED_BACK": "bold magenta",
            "FAILED_CHILD_WORKFLOW": "bold red",
            "CANCELLED": "bold dim",
        }
        return status_styles.get(status, "white")


class ConfigFormatter(Formatter):
    """Formatter for configuration output"""

    def format(self, config: Dict[str, Any], json_output: bool = False) -> None:
        """
        Format and print configuration.

        Args:
            config: Configuration dict
            json_output: Whether to output as JSON
        """
        if json_output:
            print(json.dumps(config, indent=2))
            return

        if self.use_rich:
            config_json = json.dumps(config, indent=2)
            syntax = Syntax(config_json, "yaml", theme="monokai", line_numbers=False)
            self.console.print(Panel(syntax, title="Configuration", border_style="blue"))
        else:
            print("\nConfiguration:")
            print(json.dumps(config, indent=2))
