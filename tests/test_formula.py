"""安全公式求值单元测试。"""
import unittest

from app.core.formula import (FormulaError, compile_formula, evaluate,
                              extract_refs, syntax_ok, validate_formula)


def _eval(formula, **values):
    return evaluate(compile_formula(formula, list(values)), values)


class ArithmeticTest(unittest.TestCase):
    def test_four_operations(self):
        self.assertEqual(_eval("[a] + [b]", a=3, b=4), 7)
        self.assertEqual(_eval("[a] - [b]", a=3, b=4), -1)
        self.assertEqual(_eval("[a] * [b]", a=3, b=4), 12)
        self.assertEqual(_eval("[a] / [b]", a=10, b=4), 2.5)
        self.assertEqual(_eval("[a] % [b]", a=10, b=3), 1)

    def test_parentheses_and_unary(self):
        self.assertEqual(_eval("([a] + [b]) * 2", a=1, b=2), 6)
        self.assertEqual(_eval("-[a]", a=5), -5)
        self.assertEqual(_eval("+[a] - -[b]", a=5, b=3), 8)

    def test_integer_normalized(self):
        self.assertIsInstance(_eval("[a] / [b]", a=10, b=5), int)
        self.assertEqual(_eval("[a] / [b]", a=10, b=5), 2)
        self.assertEqual(_eval("[a] + [b]", a=1, b=2.5), 3.5)

    def test_numeric_strings_and_thousands(self):
        self.assertEqual(_eval("[a] + [b]", a="1,000", b="2"), 1002)


class FunctionTest(unittest.TestCase):
    def test_functions(self):
        self.assertEqual(_eval("round([a] * 1.5, 1)", a=3), 4.5)
        self.assertEqual(_eval("abs([a])", a=-7), 7)
        self.assertEqual(_eval("int([a])", a=3.9), 3)
        self.assertEqual(_eval("float([a])", a=3), 3)
        self.assertEqual(_eval("min([a], [b])", a=3, b=5), 3)
        self.assertEqual(_eval("max([a], [b])", a=3, b=5), 5)


class EmptyAndErrorTest(unittest.TestCase):
    def test_empty_reference_is_none(self):
        self.assertIsNone(_eval("[a] + [b]", a="", b=2))
        self.assertIsNone(_eval("[a] + [b]", a=None, b=2))

    def test_non_numeric_reference_is_none(self):
        self.assertIsNone(_eval("[a] + [b]", a="abc", b=2))

    def test_division_by_zero_is_none(self):
        self.assertIsNone(_eval("[a] / [b]", a=1, b=0))
        self.assertIsNone(_eval("[a] % [b]", a=1, b=0))


class SafetyTest(unittest.TestCase):
    def _rejects(self, formula):
        with self.assertRaises(FormulaError):
            compile_formula(formula, ["a"])

    def test_unknown_column(self):
        with self.assertRaises(FormulaError):
            compile_formula("[nope] + 1", ["a"])

    def test_unknown_function(self):
        self._rejects("foo([a])")

    def test_attribute_rejected(self):
        self._rejects("[a].__class__")

    def test_subscript_rejected(self):
        self._rejects("[a][0]")

    def test_keyword_argument_rejected(self):
        self._rejects("round([a], ndigits=2)")

    def test_power_rejected(self):
        self._rejects("[a] ** 2")

    def test_string_constant_rejected(self):
        self._rejects("[a] + 'x'")

    def test_bool_constant_rejected(self):
        self._rejects("[a] + True")

    def test_import_rejected(self):
        self._rejects("__import__('os')")

    def test_empty_formula_rejected(self):
        self._rejects("   ")


class HelpersTest(unittest.TestCase):
    def test_extract_refs_order_and_dedup(self):
        self.assertEqual(extract_refs("[b] + [a] + [b]"), ["b", "a"])

    def test_syntax_ok(self):
        self.assertTrue(syntax_ok("[a] + round([b], 2)"))
        self.assertFalse(syntax_ok("__import__('os')"))
        self.assertFalse(syntax_ok("[a] ** 2"))
        self.assertFalse(syntax_ok(""))

    def test_validate_formula(self):
        self.assertEqual(validate_formula("[a] + 1", ["a"]), (True, ""))
        ok, msg = validate_formula("[c] + 1", ["a"])
        self.assertFalse(ok)
        self.assertIn("c", msg)

    def test_round_arity(self):
        self.assertTrue(syntax_ok("round([a])"))
        self.assertTrue(syntax_ok("round([a], 2)"))
        self.assertFalse(syntax_ok("round([a], 2, 3)"))


if __name__ == "__main__":
    unittest.main()
