from typing import Any, Dict
from rufus.providers.template_engine import TemplateEngine
from jinja2 import Environment, FileSystemLoader, select_autoescape

class Jinja2TemplateEngine(TemplateEngine):
    """A template engine implementation using Jinja2."""

    def __init__(self, context: Dict[str, Any]):
        super().__init__(context)
        # For simplicity, using a basic in-memory environment.
        # A more complex setup might involve loading templates from files.
        self.env = Environment(
            loader=FileSystemLoader('/'),  # Allows loading from absolute paths if needed
            autoescape=select_autoescape(['html', 'xml'])
        )
        self.env.globals.update(context)

    def render(self, template: Any) -> Any:
        """
        Renders a template. If the template is a string, it's treated as a Jinja2 template.
        If it's a dictionary, it's traversed and string values are rendered.
        """
        if isinstance(template, str):
            try:
                jinja_template = self.env.from_string(template)
                return jinja_template.render(self.context)
            except Exception as e:
                # Fallback to direct string if rendering fails (e.g., not a template)
                return template
        elif isinstance(template, dict):
            # Recursively render values in a dictionary
            rendered_dict = {}
            for key, value in template.items():
                rendered_dict[key] = self.render(value)
            return rendered_dict
        elif isinstance(template, list):
            # Recursively render values in a list
            return [self.render(item) for item in template]
        else:
            return template

    def render_string_template(self, template: str, context: Dict[str, Any]) -> str:
        """
        Renders a string template with the given context.

        Args:
            template: The template string to render
            context: The context variables for rendering

        Returns:
            The rendered string
        """
        try:
            jinja_template = self.env.from_string(template)
            return jinja_template.render(context)
        except Exception as e:
            # Fallback to direct string if rendering fails
            return template
