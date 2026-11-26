# -*- coding: utf-8 -*-
"""Regression guards for hive keyres path casing, spec numeric bounds, and JSON surrogates."""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def _load_mcp_server():
    path = os.path.join(_HERE, "hive_mcp", "mcp_server.py")
    spec = importlib.util.spec_from_file_location("hive_mcp_guard_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HiveKeyresSpecJsonGuards(unittest.TestCase):
    def test_mcp_result_anchor_key_preserves_token_file_path_casing(self):
        opened: list[str] = []
        raw_path = "/Etc/Hive/UpperCase/ProdToken.TXT"
        missing_cfg = "/nonexistent/hive_guard_missing.json"

        def fake_open(path, *args, **kwargs):
            opened.append(str(path))
            if str(path) == raw_path:
                return io.StringIO("  MiXeD-ToKeN-VaLuE  \n")
            raise FileNotFoundError(path)

        env_overrides = {
            "HIVE_ORCH_TOKEN_FILE": f"  {raw_path}  ",
            "HIVE_CONFIG": missing_cfg,
        }
        with mock.patch.dict(os.environ, env_overrides, clear=False):
            os.environ.pop("HIVE_ORCH_TOKEN", None)
            mod = _load_mcp_server()
            with mock.patch.object(mod, "CONFIG_LOCAL", missing_cfg):
                with mock.patch("builtins.open", side_effect=fake_open):
                    got = mod._result_anchor_key()

        self.assertEqual(opened, [raw_path], f"path casing was altered: {opened!r}")
        self.assertEqual(got, "mixed-token-value")

    def test_mcp_result_anchor_key_real_temp_file_mixed_case(self):
        td = tempfile.mkdtemp(prefix="HiveAnchorUpper_")
        try:
            tok_file = os.path.join(td, "UpperCaseToken.TXT")
            absent_cfg = os.path.join(td, "absent.json")
            with open(tok_file, "w", encoding="utf-8") as fh:
                fh.write("  ABC-Def-123  \n")
            with mock.patch.dict(
                os.environ,
                {
                    "HIVE_ORCH_TOKEN_FILE": tok_file,
                    "HIVE_CONFIG": absent_cfg,
                },
                clear=False,
            ):
                os.environ.pop("HIVE_ORCH_TOKEN", None)
                mod = _load_mcp_server()
                with mock.patch.object(mod, "CONFIG_LOCAL", absent_cfg):
                    self.assertEqual(mod._result_anchor_key(), "abc-def-123")
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_rust_cargo_guards_pass(self):
        cargo = shutil.which("cargo")
        if not cargo:
            self.skipTest("cargo not available")
        env = os.environ.copy()
        env["HIVE_PYTHON"] = sys.executable
        for filt in (
            "keyres::tests::env_chain_priority",
            "spec::tests::nonfinite_and_overflow_numeric_fields_rejected",
            "json::surrogate_and_number_guard_tests",
        ):
            r = subprocess.run(
                [cargo, "test", "--manifest-path", os.path.join(_HERE, "Cargo.toml"), filt],
                cwd=_REPO, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(r.returncode, 0, f"cargo test {filt} failed:\n{r.stdout}\n{r.stderr}")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HiveKeyresSpecJsonGuards)
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)
