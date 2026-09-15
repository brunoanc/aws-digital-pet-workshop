"""Check the safety of the block formatter."""

import ast
import unittest

from scripts.format_blocks import spaced


class FormatBlocksTests(unittest.TestCase):
    """Keep formatting changes free of syntax changes."""

    def test_spacing_preserves_syntax_and_is_idempotent(self):
        """Separate setup, control, and results without changing code or string contents."""

        source = 'def sample(value):\n    """Return a checked value."""\n    result = value\n    if result:\n        return result\n    return None\n'
        result = spaced(source)

        self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
        self.assertEqual(spaced(result), result)
        self.assertIn("result = value\n\n    if result:", result)

if __name__ == "__main__":
    unittest.main()
