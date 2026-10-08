# -*- coding: utf-8 -*-
"""Guard the CSRE -> md_access import contract without optional numpy dependencies."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


WISDOM = Path(__file__).resolve().parent / "whitebox_kb" / "wisdom"


class CsreMdAccessImportTests(unittest.TestCase):
    def test_imported_md_access_helper_exists_and_is_called(self):
        csre = ast.parse((WISDOM / "csre.py").read_text(encoding="utf-8"))
        access = ast.parse((WISDOM / "md_access.py").read_text(encoding="utf-8"))
        defined = {
            node.name for node in access.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        imports = [
            alias.name for node in ast.walk(csre)
            if isinstance(node, ast.ImportFrom) and node.module == "md_access"
            for alias in node.names
        ]
        self.assertIn("_md_conn_or_none", imports)
        self.assertTrue(set(imports) <= defined, f"undefined md_access imports: {set(imports) - defined}")
        calls = [
            node.func.id for node in ast.walk(csre)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("_md_conn_or_none", calls)


if __name__ == "__main__":
    unittest.main()
