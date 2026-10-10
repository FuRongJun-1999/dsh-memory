"""Real stdio: malformed tools/call inputs must fail before tool dispatch.

Run: python -X utf8 -m md_cg.test_mcp_call_argument_types
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from . import mcp_server


class CallArgumentTypesTests(unittest.TestCase):
    def test_invalid_control_input_never_dispatches(self):
        for arguments in ([], None, {"op": 0}, {"action": []}, {"as_unit": False}):
            with self.subTest(arguments=arguments), \
                    mock.patch.object(mcp_server, "call_tool") as dispatch, \
                    mock.patch.object(mcp_server, "_reply") as reply:
                stopped = mcp_server._serve_line(object(), {
                    "id": 7, "method": "tools/call",
                    "params": {"name": "cg", "arguments": arguments}})
                self.assertFalse(stopped)
                dispatch.assert_not_called()
                self.assertEqual(reply.call_args.kwargs["error"]["code"], -32602)

    def test_omitted_arguments_and_business_errors_keep_their_contract(self):
        with mock.patch.object(mcp_server, "call_tool", return_value={}) as dispatch, \
                mock.patch.object(mcp_server, "_reply"):
            mcp_server._serve_line(object(), {"id": 8, "method": "tools/call",
                                            "params": {"name": "cg"}})
            self.assertEqual(dispatch.call_args.args[2], {})
        for tags in ("a,b", ["a", "b"]):
            args = {"op": "read", "tags": tags}
            with self.subTest(tags=tags), \
                    mock.patch.object(mcp_server, "call_tool", side_effect=ValueError("business error")) as dispatch, \
                    mock.patch.object(mcp_server, "_reply") as reply:
                mcp_server._serve_line(object(), {"id": 9, "method": "tools/call",
                                                "params": {"name": "cg", "arguments": args}})
                self.assertIs(dispatch.call_args.args[2], args)
                self.assertTrue(reply.call_args.args[1]["isError"])

    def test_stdio_rejects_bad_types_and_keeps_serving(self):
        bad = [
            {"name": "cg", "arguments": {"op": 123}},
            {"name": "cg", "arguments": {"op": False}},
            {"name": "cg", "arguments": {"op": "status", "action": []}},
            {"name": "cg", "arguments": {"op": "status", "as_unit": 123}},
            {"name": "cg", "arguments": []},
            {"name": "cg", "arguments": [1]},
            {"name": "cg", "arguments": ""},
            {"name": "cg", "arguments": 0},
            {"name": "cg", "arguments": False},
            {"name": "cg", "arguments": None},
            {"name": []},
            {"name": 123},
            {"name": ""},
            {},
        ]
        requests = [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call",
                     "params": params} for i, params in enumerate(bad)]
        good_id = len(requests) + 1
        requests.extend([
            {"jsonrpc": "2.0", "id": good_id, "method": "tools/call",
             "params": {"name": "cg", "arguments": {"op": "status"}}},
            {"jsonrpc": "2.0", "id": good_id + 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": good_id + 2, "method": "shutdown"},
        ])
        with tempfile.TemporaryDirectory(prefix="mcp_call_types_") as tmp:
            env = dict(os.environ, MDCG_ROOT=str(Path(tmp) / "memory"),
                       MDCG_AUX_ROOT=str(Path(tmp) / "auxiliary"),
                       MDCG_DATA_ROOT=str(Path(tmp) / "data"),
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            env.pop("MDCG_TOKEN", None)
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                input="".join(json.dumps(r) + "\n" for r in requests),
                cwd=Path(__file__).resolve().parent.parent, env=env,
                text=True, encoding="utf-8", capture_output=True, timeout=40)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(line) for line in proc.stdout.splitlines() if line]
            self.assertEqual(len(replies), len(requests), proc.stdout)
            by_id = {r["id"]: r for r in replies}
            for i, params in enumerate(bad, 1):
                with self.subTest(params=params):
                    reply = by_id[i]
                    self.assertEqual(reply.get("error", {}).get("code"), -32602, reply)
                    self.assertNotIn("AttributeError", json.dumps(reply))
                    self.assertNotIn("TypeError", json.dumps(reply))
            self.assertFalse(by_id[good_id]["result"]["isError"], by_id[good_id])
            self.assertIn("tools", by_id[good_id + 1]["result"])
            self.assertEqual(by_id[good_id + 2]["result"], {})


if __name__ == "__main__":
    unittest.main()
