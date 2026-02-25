"""
Unit tests for SimpleExpressionEvaluator.

The evaluator is initialised with a state dict and evaluate(expression) resolves
dot-notation paths against that state.

Tests:
1. Single-key lookup returns the value.
2. Nested dot-notation lookup traverses dicts.
3. Attribute access on objects works via hasattr/getattr.
4. Missing key returns None (safe fallback).
5. Works with numeric and boolean values.
6. Works with list indexing absent → returns None gracefully.
"""
import pytest
from pydantic import BaseModel

from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_single_key_lookup():
    """Flat key lookup returns the correct value."""
    evaluator = SimpleExpressionEvaluator({"amount": 150.0})
    result = evaluator.evaluate("amount")
    assert result == 150.0


def test_nested_dict_lookup():
    """Dot-notation traverses nested dicts."""
    evaluator = SimpleExpressionEvaluator({"order": {"status": "approved"}})
    result = evaluator.evaluate("order.status")
    assert result == "approved"


def test_attribute_access_on_pydantic_model():
    """Dot-notation accesses attributes on objects (e.g. Pydantic models)."""
    class OrderState(BaseModel):
        amount: float = 250.0
        approved: bool = True

    state_obj = OrderState()
    # ExpressionEvaluator.state should be a dict, but the implementation
    # also supports object attribute access via hasattr/getattr
    evaluator = SimpleExpressionEvaluator({"state": state_obj})
    result = evaluator.evaluate("state.amount")
    assert result == 250.0


def test_bool_field_access():
    """Boolean field returns a bool value."""
    class OrderState(BaseModel):
        approved: bool = False

    state_obj = OrderState(approved=True)
    evaluator = SimpleExpressionEvaluator({"state": state_obj})
    result = evaluator.evaluate("state.approved")
    assert result is True


def test_missing_key_returns_none():
    """A path that does not exist returns None without raising."""
    evaluator = SimpleExpressionEvaluator({"x": 1})
    result = evaluator.evaluate("x.nonexistent")
    assert result is None


def test_deeply_nested_dict():
    """Three-level dot-notation resolves correctly."""
    evaluator = SimpleExpressionEvaluator({"a": {"b": {"c": "deep"}}})
    result = evaluator.evaluate("a.b.c")
    assert result == "deep"


def test_integer_value():
    """Integer values are returned as-is."""
    evaluator = SimpleExpressionEvaluator({"retries": 3})
    result = evaluator.evaluate("retries")
    assert result == 3


def test_empty_state_dict():
    """Evaluating against an empty state dict returns None for any path."""
    evaluator = SimpleExpressionEvaluator({})
    result = evaluator.evaluate("anything")
    assert result is None


def test_string_value():
    """String values are returned correctly."""
    evaluator = SimpleExpressionEvaluator({"status": "pending"})
    result = evaluator.evaluate("status")
    assert result == "pending"
