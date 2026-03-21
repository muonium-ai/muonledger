"""
Tests for the format string parser and evaluator.

Covers:
  - Basic %(expr) evaluation
  - Width formatting (left/right alignment)
  - Truncation
  - Combined width + truncation
  - Literal text
  - Multiple expressions in one format string
  - Backslash escapes
  - Edge cases (nested parens, quoted strings, etc.)
"""

import pytest

from muonledger.format import (
    ElisionStyle,
    ElementKind,
    Format,
    FormatElement,
    FormatError,
)
from muonledger.scope import CallScope, SymbolScope
from muonledger.value import Value


# ---------------------------------------------------------------------------
# Helper: build a scope with named variables
# ---------------------------------------------------------------------------


def _make_scope(**kwargs) -> SymbolScope:
    """Create a SymbolScope pre-populated with the given name=value pairs."""
    scope = SymbolScope()
    for name, val in kwargs.items():
        scope.define(name, Value(val) if not isinstance(val, Value) else val)
    return scope


# ===================================================================
# 1. Parsing
# ===================================================================


class TestFormatParsing:
    """Tests for format string parsing into elements."""

    def test_literal_only(self):
        fmt = Format("hello world")
        assert len(fmt.elements) == 1
        assert fmt.elements[0].kind == ElementKind.STRING
        assert fmt.elements[0].data == "hello world"

    def test_empty_string(self):
        fmt = Format("")
        assert len(fmt.elements) == 0

    def test_single_expression(self):
        fmt = Format("%(account)")
        assert len(fmt.elements) == 1
        assert fmt.elements[0].kind == ElementKind.EXPR

    def test_literal_before_expr(self):
        fmt = Format("Name: %(account)")
        assert len(fmt.elements) == 2
        assert fmt.elements[0].kind == ElementKind.STRING
        assert fmt.elements[0].data == "Name: "
        assert fmt.elements[1].kind == ElementKind.EXPR

    def test_literal_after_expr(self):
        fmt = Format("%(account) end")
        assert len(fmt.elements) == 2
        assert fmt.elements[0].kind == ElementKind.EXPR
        assert fmt.elements[1].kind == ElementKind.STRING
        assert fmt.elements[1].data == " end"

    def test_multiple_expressions(self):
        fmt = Format("%(account)  %(total)")
        assert len(fmt.elements) == 3
        assert fmt.elements[0].kind == ElementKind.EXPR
        assert fmt.elements[1].kind == ElementKind.STRING
        assert fmt.elements[1].data == "  "
        assert fmt.elements[2].kind == ElementKind.EXPR

    def test_percent_escape(self):
        fmt = Format("100%%")
        assert len(fmt.elements) == 2
        assert fmt.elements[0].kind == ElementKind.STRING
        assert fmt.elements[0].data == "100"
        assert fmt.elements[1].kind == ElementKind.STRING
        assert fmt.elements[1].data == "%"

    def test_width_specifier(self):
        fmt = Format("%20(account)")
        assert len(fmt.elements) == 1
        elem = fmt.elements[0]
        assert elem.min_width == 20
        assert elem.max_width == 0
        assert elem.align_left is False

    def test_left_align_specifier(self):
        fmt = Format("%-20(account)")
        assert len(fmt.elements) == 1
        elem = fmt.elements[0]
        assert elem.min_width == 20
        assert elem.align_left is True

    def test_max_width_only(self):
        fmt = Format("%.10(account)")
        assert len(fmt.elements) == 1
        elem = fmt.elements[0]
        assert elem.min_width == 0  # max_width does not set min_width
        assert elem.max_width == 10

    def test_combined_width(self):
        fmt = Format("%20.30(account)")
        assert len(fmt.elements) == 1
        elem = fmt.elements[0]
        assert elem.min_width == 20
        assert elem.max_width == 30

    def test_left_align_combined(self):
        fmt = Format("%-20.30(account)")
        assert len(fmt.elements) == 1
        elem = fmt.elements[0]
        assert elem.min_width == 20
        assert elem.max_width == 30
        assert elem.align_left is True


# ===================================================================
# 2. Backslash Escapes
# ===================================================================


class TestBackslashEscapes:
    """Tests for backslash escape handling in format strings."""

    def test_newline_escape(self):
        fmt = Format("hello\\nworld")
        scope = _make_scope()
        assert fmt.calc(scope) == "hello\nworld"

    def test_tab_escape(self):
        fmt = Format("col1\\tcol2")
        scope = _make_scope()
        assert fmt.calc(scope) == "col1\tcol2"

    def test_backslash_escape(self):
        fmt = Format("path\\\\name")
        scope = _make_scope()
        assert fmt.calc(scope) == "path\\name"

    def test_other_escape(self):
        fmt = Format("\\x")
        scope = _make_scope()
        assert fmt.calc(scope) == "x"

    def test_carriage_return(self):
        fmt = Format("line\\r")
        scope = _make_scope()
        assert fmt.calc(scope) == "line\r"

    def test_backspace(self):
        fmt = Format("a\\bb")
        scope = _make_scope()
        assert fmt.calc(scope) == "a\bb"


# ===================================================================
# 3. Basic Expression Evaluation
# ===================================================================


class TestBasicEvaluation:
    """Tests for basic %(expr) evaluation."""

    def test_simple_identifier(self):
        fmt = Format("%(account)")
        scope = _make_scope(account="Expenses:Food")
        assert fmt.calc(scope) == "Expenses:Food"

    def test_integer_value(self):
        fmt = Format("%(total)")
        scope = _make_scope(total=42)
        assert fmt.calc(scope) == "42"

    def test_string_value(self):
        fmt = Format("%(payee)")
        scope = _make_scope(payee="Grocery Store")
        assert fmt.calc(scope) == "Grocery Store"

    def test_boolean_true(self):
        fmt = Format("%(flag)")
        scope = _make_scope(flag=True)
        assert fmt.calc(scope) == "true"

    def test_boolean_false(self):
        fmt = Format("%(flag)")
        scope = _make_scope(flag=False)
        assert fmt.calc(scope) == "false"

    def test_void_value(self):
        fmt = Format("%(missing)")
        scope = _make_scope()
        assert fmt.calc(scope) == ""

    def test_arithmetic_expression(self):
        fmt = Format("%(x + y)")
        scope = _make_scope(x=10, y=20)
        assert fmt.calc(scope) == "30"

    def test_subtraction(self):
        fmt = Format("%(x - y)")
        scope = _make_scope(x=30, y=10)
        assert fmt.calc(scope) == "20"

    def test_multiplication(self):
        fmt = Format("%(x * y)")
        scope = _make_scope(x=5, y=6)
        assert fmt.calc(scope) == "30"

    def test_string_literal_in_expr(self):
        fmt = Format("%(\"hello\")")
        scope = _make_scope()
        assert fmt.calc(scope) == "hello"

    def test_integer_literal_in_expr(self):
        fmt = Format("%(42)")
        scope = _make_scope()
        assert fmt.calc(scope) == "42"

    def test_ternary_true(self):
        fmt = Format("%(flag ? \"yes\" : \"no\")")
        scope = _make_scope(flag=True)
        assert fmt.calc(scope) == "yes"

    def test_ternary_false(self):
        fmt = Format("%(flag ? \"yes\" : \"no\")")
        scope = _make_scope(flag=False)
        assert fmt.calc(scope) == "no"


# ===================================================================
# 4. Width Formatting
# ===================================================================


class TestWidthFormatting:
    """Tests for width specifiers and alignment."""

    def test_right_align_padding(self):
        fmt = Format("%10(name)")
        scope = _make_scope(name="abc")
        result = fmt.calc(scope)
        assert result == "       abc"
        assert len(result) == 10

    def test_left_align_padding(self):
        fmt = Format("%-10(name)")
        scope = _make_scope(name="abc")
        result = fmt.calc(scope)
        assert result == "abc       "
        assert len(result) == 10

    def test_exact_width_no_padding(self):
        fmt = Format("%5(name)")
        scope = _make_scope(name="abcde")
        result = fmt.calc(scope)
        assert result == "abcde"

    def test_wider_than_min_no_truncation(self):
        """When text exceeds min_width but no max_width, text is not truncated."""
        fmt = Format("%3(name)")
        scope = _make_scope(name="abcde")
        result = fmt.calc(scope)
        assert result == "abcde"

    def test_right_align_integer(self):
        fmt = Format("%8(total)")
        scope = _make_scope(total=42)
        result = fmt.calc(scope)
        assert result == "      42"
        assert len(result) == 8

    def test_left_align_integer(self):
        fmt = Format("%-8(total)")
        scope = _make_scope(total=42)
        result = fmt.calc(scope)
        assert result == "42      "
        assert len(result) == 8

    def test_zero_width(self):
        """Zero width means no formatting constraints."""
        fmt = Format("%(name)")
        scope = _make_scope(name="hello")
        assert fmt.calc(scope) == "hello"


# ===================================================================
# 5. Truncation
# ===================================================================


class TestTruncation:
    """Tests for max_width truncation."""

    def test_trailing_truncation(self):
        fmt = Format("%.10(name)")
        scope = _make_scope(name="Hello World, this is a long string")
        result = fmt.calc(scope)
        assert len(result) == 10
        assert result == "Hello Wo.."

    def test_no_truncation_when_short(self):
        fmt = Format("%.20(name)")
        scope = _make_scope(name="short")
        result = fmt.calc(scope)
        assert result == "short"

    def test_exact_length_no_truncation(self):
        fmt = Format("%.5(name)")
        scope = _make_scope(name="hello")
        result = fmt.calc(scope)
        # len("hello") == 5, max_width == 5, but min_width also == 5
        assert result == "hello"

    def test_truncation_one_over(self):
        fmt = Format("%.5(name)")
        scope = _make_scope(name="helloo")
        result = fmt.calc(scope)
        assert result == "hel.."
        assert len(result) == 5

    def test_leading_truncation(self):
        original_style = Format.default_style
        try:
            Format.default_style = ElisionStyle.TRUNCATE_LEADING
            result = Format.truncate("Hello World", 8)
            assert result == ".. World"
            assert len(result) == 8
        finally:
            Format.default_style = original_style

    def test_middle_truncation(self):
        original_style = Format.default_style
        try:
            Format.default_style = ElisionStyle.TRUNCATE_MIDDLE
            result = Format.truncate("Hello World!", 8)
            assert len(result) == 8
            assert result == "Hel..ld!"
        finally:
            Format.default_style = original_style

    def test_truncate_static_method(self):
        result = Format.truncate("abcdefghij", 6)
        assert result == "abcd.."
        assert len(result) == 6

    def test_truncate_empty(self):
        result = Format.truncate("", 5)
        assert result == ""

    def test_truncate_zero_width(self):
        result = Format.truncate("hello", 0)
        assert result == "hello"

    def test_truncate_short_string(self):
        result = Format.truncate("hi", 10)
        assert result == "hi"


# ===================================================================
# 6. Combined Width + Truncation
# ===================================================================


class TestCombinedWidthTruncation:
    """Tests for combined min_width and max_width."""

    def test_short_text_gets_padded(self):
        """Text shorter than min_width is padded (right-aligned)."""
        fmt = Format("%20.30(name)")
        scope = _make_scope(name="short")
        result = fmt.calc(scope)
        assert len(result) == 20
        assert result == "               short"

    def test_long_text_gets_truncated(self):
        """Text longer than max_width is truncated."""
        fmt = Format("%10.15(name)")
        scope = _make_scope(name="This is quite a long name indeed")
        result = fmt.calc(scope)
        assert len(result) == 15
        assert result == "This is quite.."

    def test_text_between_min_and_max(self):
        """Text between min and max width is not modified."""
        fmt = Format("%5.20(name)")
        scope = _make_scope(name="medium")
        result = fmt.calc(scope)
        assert result == "medium"

    def test_left_aligned_combined(self):
        fmt = Format("%-20.30(name)")
        scope = _make_scope(name="short")
        result = fmt.calc(scope)
        assert len(result) == 20
        assert result == "short               "


# ===================================================================
# 7. Multiple Expressions
# ===================================================================


class TestMultipleExpressions:
    """Tests for format strings with multiple expressions."""

    def test_two_expressions_with_separator(self):
        fmt = Format("%(account)  %(total)")
        scope = _make_scope(account="Expenses", total=100)
        assert fmt.calc(scope) == "Expenses  100"

    def test_expressions_with_literal_prefix_suffix(self):
        fmt = Format("[%(account)] = %(total) USD")
        scope = _make_scope(account="Assets", total=500)
        assert fmt.calc(scope) == "[Assets] = 500 USD"

    def test_three_expressions(self):
        fmt = Format("%(a) + %(b) = %(c)")
        scope = _make_scope(a=1, b=2, c=3)
        assert fmt.calc(scope) == "1 + 2 = 3"

    def test_formatted_columns(self):
        fmt = Format("%-20(account)%10(total)")
        scope = _make_scope(account="Expenses:Food", total=42)
        result = fmt.calc(scope)
        # "Expenses:Food" (13) left-justified to 20 + "42" right-justified to 10
        assert result == "Expenses:Food               42"
        assert len(result) == 30

    def test_adjacent_expressions(self):
        fmt = Format("%(a)%(b)")
        scope = _make_scope(a="hello", b="world")
        assert fmt.calc(scope) == "helloworld"


# ===================================================================
# 8. Edge Cases
# ===================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_nested_parens_in_expr(self):
        """Expression containing nested parentheses."""
        fmt = Format("%(a + (b * c))")
        scope = _make_scope(a=1, b=2, c=3)
        assert fmt.calc(scope) == "7"

    def test_quoted_string_with_parens(self):
        """Quoted string containing parentheses."""
        fmt = Format("%(\"hello (world)\")")
        scope = _make_scope()
        assert fmt.calc(scope) == "hello (world)"

    def test_bare_percent_at_end_raises(self):
        with pytest.raises(FormatError):
            Format("hello%")

    def test_unmatched_paren_raises(self):
        with pytest.raises(FormatError):
            Format("%(account")

    def test_unrecognized_specifier_raises(self):
        with pytest.raises(FormatError):
            Format("%z")

    def test_format_repr(self):
        fmt = Format("%(account)")
        assert "%(account)" in repr(fmt)

    def test_format_dump(self):
        fmt = Format("Name: %20(account)")
        dump = fmt.dump()
        assert "STRING" in dump
        assert "EXPR" in dump

    def test_callable_in_scope(self):
        scope = SymbolScope()
        scope.define("greet", lambda cs: Value("hello"))
        fmt = Format("%(greet)")
        assert fmt.calc(scope) == "hello"

    def test_format_with_only_escapes(self):
        fmt = Format("\\n\\t")
        scope = _make_scope()
        assert fmt.calc(scope) == "\n\t"

    def test_format_with_only_percent_percent(self):
        fmt = Format("%%%%")
        scope = _make_scope()
        assert fmt.calc(scope) == "%%"

    def test_complex_format_string(self):
        """A realistic format string with multiple fields."""
        fmt = Format("%-30(account)  %12(total)\\n")
        scope = _make_scope(account="Expenses:Food:Groceries", total=1234)
        result = fmt.calc(scope)
        assert result == "Expenses:Food:Groceries                 1234\n"

    def test_default_constructor(self):
        fmt = Format()
        assert len(fmt.elements) == 0
        scope = _make_scope()
        assert fmt.calc(scope) == ""

    def test_whitespace_only_literal(self):
        fmt = Format("   ")
        scope = _make_scope()
        assert fmt.calc(scope) == "   "


# ===================================================================
# 9. Truncation Style Variants (static method)
# ===================================================================


class TestTruncationStyles:
    """Tests for the static truncate() method with explicit styles."""

    def test_trailing_style(self):
        result = Format.truncate("abcdefghij", 6, style=ElisionStyle.TRUNCATE_TRAILING)
        assert result == "abcd.."

    def test_leading_style(self):
        result = Format.truncate("abcdefghij", 6, style=ElisionStyle.TRUNCATE_LEADING)
        assert result == "..ghij"

    def test_middle_style(self):
        result = Format.truncate("abcdefghij", 6, style=ElisionStyle.TRUNCATE_MIDDLE)
        assert result == "ab..ij"

    def test_middle_style_odd_width(self):
        result = Format.truncate("abcdefghij", 7, style=ElisionStyle.TRUNCATE_MIDDLE)
        # 7-2=5, left=2, right=3
        assert result == "ab..hij"

    def test_truncate_width_2(self):
        result = Format.truncate("abcdef", 2, style=ElisionStyle.TRUNCATE_TRAILING)
        assert result == ".."

    def test_truncate_width_1(self):
        result = Format.truncate("abcdef", 1, style=ElisionStyle.TRUNCATE_TRAILING)
        assert result == "."

    def test_truncate_width_3(self):
        result = Format.truncate("abcdef", 3, style=ElisionStyle.TRUNCATE_TRAILING)
        assert result == "a.."


# ===================================================================
# 10. Format __call__ protocol
# ===================================================================


class TestFormatCallProtocol:
    """Test that Format can be called directly."""

    def test_call_returns_string(self):
        fmt = Format("%(name)")
        scope = _make_scope(name="test")
        assert fmt(scope) == "test"

    def test_call_with_formatting(self):
        fmt = Format("%10(name)")
        scope = _make_scope(name="hi")
        result = fmt(scope)
        assert result == "        hi"
        assert len(result) == 10
