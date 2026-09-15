"""Separate Python logic blocks without changing the syntax tree."""

import ast
from pathlib import Path


ROOTS = ("app", "agent_lambda", "lambda", "checkpoints", "scripts", "tests")


def group(statement):
    """Classify adjacent statements as setup, execution, or checks."""

    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return "imports"

    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return "assignments"

    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return "docstring"

    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        function = statement.value.func

        if isinstance(function, ast.Attribute) and function.attr.startswith("assert"):
            return "assertions"

    return type(statement).__name__


def spaced(source):
    """Insert block spacing and verify that only formatting changed."""

    tree = ast.parse(source)
    lines = source.splitlines()
    breaks = {}

    for node in ast.walk(tree):
        for _, values in ast.iter_fields(node):
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, ast.stmt) for value in values)
            ):
                continue

            for previous, current in zip(values, values[1:]):
                definitions = isinstance(
                    current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
                compound = hasattr(previous, "body") or hasattr(current, "body")

                if (
                    not definitions
                    and not compound
                    and group(previous) == group(current)
                ):
                    continue

                start = (
                    min(
                        [current.lineno]
                        + [
                            decorator.lineno
                            for decorator in getattr(current, "decorator_list", [])
                        ]
                    )
                    - 1
                )

                while start > previous.end_lineno and lines[
                    start - 1
                ].lstrip().startswith("#"):
                    start -= 1

                blanks = 0

                while start - blanks > 0 and not lines[start - blanks - 1].strip():
                    blanks += 1

                desired = 2 if definitions and isinstance(node, ast.Module) else 1
                breaks[start] = max(breaks.get(start, 0), desired - blanks)

    output = []

    for index, line in enumerate(lines):
        output.extend([""] * breaks.get(index, 0))
        output.append(line)

    result = "\n".join(output) + "\n"

    if ast.dump(tree, include_attributes=False) != ast.dump(
        ast.parse(result), include_attributes=False
    ):
        raise ValueError(
            "Formatting changed the syntax, so the file will not be saved."
        )

    return result


def main():
    """Apply spacing to maintained code without touching backups or dependencies."""

    root = Path(__file__).resolve().parents[1]
    changed = []

    for directory in ROOTS:
        for path in sorted((root / directory).glob("*.py")):
            original = path.read_text(encoding="utf-8")
            result = spaced(original)

            if original != result:
                path.write_text(result, encoding="utf-8")
                changed.append(str(path.relative_to(root)))

    print("\n".join(changed) or "Block spacing is already consistent.")


if __name__ == "__main__":
    main()
