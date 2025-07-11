#!/usr/bin/env python3
"""Utility to strip comments from Python and HTML files in the repository.

Python: removes all # comments (using the tokenize module for safety) but keeps code and docstrings.
HTML: removes <!-- ... --> comment blocks, including multi-line ones.
"""
import io
import pathlib
import re
import tokenize


def strip_python_comments(path: pathlib.Path) -> None:
    """Overwrite a Python file with all comments removed."""
    source = path.read_text()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    filtered = [tok for tok in tokens if tok.type != tokenize.COMMENT]
    new_source = tokenize.untokenize(filtered)
    path.write_text(normalize_whitespace(new_source))


def strip_html_comments(path: pathlib.Path) -> None:
    """Overwrite an HTML file with all <!-- ...

    --> blocks removed (multi-line safe).
    """
    source = path.read_text()
    cleaned = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    path.write_text(normalize_whitespace(cleaned))


def main() -> None:
    repo_root = pathlib.Path(__file__).resolve().parent
    for py_file in repo_root.rglob("*.py"):
        # Skip this script itself to avoid unnecessary churn
        if py_file.resolve() == pathlib.Path(__file__).resolve():
            continue
        strip_python_comments(py_file)

    for html_file in repo_root.rglob("*.html"):
        strip_html_comments(html_file)


# Helper --------------------------------------------------------------
def normalize_whitespace(text: str) -> str:
    """Return *text* with trailing spaces removed and consecutive blank lines
    collapsed to a single blank line.

    Ensures the final string ends with a newline when non-empty.
    """
    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.splitlines()]

    # Collapse multiple blank lines into a single blank line
    normalized_lines = []
    blank_run = 0  # Number of consecutive blank lines encountered

    for line in lines:
        if line == "":
            if blank_run < 2:  # Allow up to two consecutive blank lines
                normalized_lines.append(line)
            blank_run += 1
        else:
            normalized_lines.append(line)
            blank_run = 0

    return "\n".join(normalized_lines) + ("\n" if normalized_lines else "")


if __name__ == "__main__":
    main()
