"""
Unit tests for Jinja2TemplateEngine.

The engine is initialised with a context dict and renders Jinja2 templates.

Tests:
1. render(string) — interpolates {{ var }} tokens.
2. render(dict) — recursively renders string values.
3. render(list) — recursively renders string elements.
4. render(non-string scalar) — returns as-is.
5. render_string_template — renders with an explicitly provided context.
6. Missing context variable falls back gracefully (empty string, not crash).
7. Nested state path via context dict.
"""
import pytest

from ruvon.implementations.templating.jinja2 import Jinja2TemplateEngine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_simple_string():
    """{{ amount }} interpolates from context."""
    engine = Jinja2TemplateEngine({"amount": 99.5})
    result = engine.render("Total: {{ amount }}")
    assert result == "Total: 99.5"


def test_render_dict_string_values():
    """render(dict) recurses into string values and renders each."""
    engine = Jinja2TemplateEngine({"name": "Alice", "amount": 200})
    template = {"greeting": "Hello {{ name }}", "total": "{{ amount }}"}
    result = engine.render(template)
    assert result["greeting"] == "Hello Alice"
    assert result["total"] == "200"


def test_render_nested_dict():
    """render(dict) handles nested dict structure recursively."""
    engine = Jinja2TemplateEngine({"env": "prod"})
    template = {"outer": {"inner": "env={{ env }}"}}
    result = engine.render(template)
    assert result["outer"]["inner"] == "env=prod"


def test_render_list():
    """render(list) renders each string element."""
    engine = Jinja2TemplateEngine({"x": "hello"})
    result = engine.render(["{{ x }}", "static"])
    assert result == ["hello", "static"]


def test_render_non_string_scalar_returned_as_is():
    """render(int) returns the integer unchanged."""
    engine = Jinja2TemplateEngine({})
    assert engine.render(42) == 42
    assert engine.render(True) is True
    assert engine.render(None) is None


def test_render_string_template_with_explicit_context():
    """render_string_template uses the provided context, not self.context."""
    engine = Jinja2TemplateEngine({"from_init": "ignored"})
    result = engine.render_string_template("{{ city }}", {"city": "Tokyo"})
    assert result == "Tokyo"


def test_missing_variable_does_not_crash():
    """Rendering a template with a missing variable returns empty string (Jinja2 default)."""
    engine = Jinja2TemplateEngine({})
    result = engine.render("Hello {{ name }}")
    # Jinja2 replaces undefined vars with '' by default
    assert "Hello" in result
    # Should not raise


def test_render_boolean_in_context():
    """Boolean context values render correctly via Jinja2 string coercion."""
    engine = Jinja2TemplateEngine({"approved": True})
    result = engine.render("Approved: {{ approved }}")
    assert "True" in result


def test_render_empty_string():
    """render('') returns empty string."""
    engine = Jinja2TemplateEngine({})
    assert engine.render("") == ""


def test_render_string_no_template_tokens():
    """Plain string with no tokens is returned unchanged."""
    engine = Jinja2TemplateEngine({"x": "ignored"})
    assert engine.render("plain string") == "plain string"
