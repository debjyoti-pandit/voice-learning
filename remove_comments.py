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
    path.write_text(new_source)


def strip_html_comments(path: pathlib.Path) -> None:
    """Overwrite an HTML file with all <!-- ... --> blocks removed (multi-line safe)."""
    source = path.read_text()
    cleaned = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    path.write_text(cleaned)


def main() -> None:
    repo_root = pathlib.Path(__file__).resolve().parent
    for py_file in repo_root.rglob("*.py"):
        # Skip this script itself to avoid unnecessary churn
        if py_file.resolve() == pathlib.Path(__file__).resolve():
            continue
        strip_python_comments(py_file)

    for html_file in repo_root.rglob("*.html"):
        strip_html_comments(html_file)


if __name__ == "__main__":
    main() 