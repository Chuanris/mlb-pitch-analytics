"""Remove executed output and machine-local metadata before publication."""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat


def sanitize(path: Path) -> None:
    notebook = nbformat.read(path, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.execution_count = None
            cell.outputs = []
    notebook.metadata.pop("widgets", None)
    nbformat.write(notebook, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="+", type=Path)
    args = parser.parse_args()
    for notebook_path in args.notebooks:
        sanitize(notebook_path)
        print(f"Sanitized {notebook_path}")


if __name__ == "__main__":
    main()
