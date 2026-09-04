from __future__ import annotations

import os
from pathlib import Path

import nbformat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "01_pipeline_and_sql_tutorial.ipynb"


def main() -> None:
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    namespace = {"__name__": "__notebook_validation__"}
    original_directory = Path.cwd()
    os.chdir(PROJECT_ROOT)
    try:
        code_cell_number = 0
        for cell in notebook.cells:
            if cell.cell_type != "code":
                continue
            code_cell_number += 1
            compiled = compile(cell.source, f"{NOTEBOOK_PATH.name}:cell-{code_cell_number}", "exec")
            exec(compiled, namespace)
            print(f"PASS | code cell {code_cell_number}")
    finally:
        os.chdir(original_directory)
    print(f"Validated {code_cell_number} code cells in one shared Python process.")


if __name__ == "__main__":
    main()
