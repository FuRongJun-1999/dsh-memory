# -*- coding: utf-8 -*-
"""Default exports must preserve each snapshot, including concurrent requests.

Run from the repository root: python -X utf8 -m md_cg.test_export_snapshots
Only synthetic data in temporary directories; no external service or Rust needed.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from . import export
from .mdcos import MdCGOS
from .mcp_server import call_tool
from .security import Principal


class ExportSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mdcg-export-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict(os.environ, {
            "MDCG_EXPORT_ROOT": str(self.root), "MDCG_ROOT": str(self.root / "brain"),
            "MDCG_STATE_ROOT": str(self.root / "state"),
            "MDCG_AUX_ROOT": str(self.root / "aux"),
            "MDCG_DATA_ROOT": str(self.root / "data"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.graph = self.open_graph()
        self.add_node("first", 1)
        self.clock = patch.object(export.time, "strftime", return_value="20261008_214500")
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def open_graph(self):
        graph = MdCGOS(str(self.root / "brain"), actor="export-regression")
        graph.principal = Principal(
            tenant="default", actor="export-regression", clearance="internal",
            can_write=True, can_admin=True, role="designer")
        return graph

    def add_node(self, node_id, value, tags=None):
        self.graph.add(
            node_id, "value = %d" % value, layer="contextual", content_kind="code",
            verification_basis="test", consistency=False, tags=tags or [])

    def export(self, action, graph=None, **arguments):
        result = call_tool(graph or self.graph, "cg", {
            "op": "export", "action": action, **arguments})
        self.assertTrue(result["ok"])
        return result

    def rows(self, result):
        return [json.loads(line) for line in Path(result["out"]).read_text(
            encoding="utf-8").splitlines()]

    def assert_preserved(self, first, first_bytes, second):
        self.assertNotEqual(first["out"], second["out"])
        self.assertEqual(Path(first["out"]).read_bytes(), first_bytes)
        for result in (first, second):
            self.assertEqual(len(self.rows(result)), result["written"])
            self.assertEqual(Path(result["out"]).stat().st_size, result["bytes"])
            self.assertEqual(Path(result["out"]).parent, self.root / "brain")
            self.assertFalse(Path(result["out"] + ".tmp").exists())

    def test_graph_exports_keep_the_previous_snapshot_after_memory_changes(self):
        first = self.export("graph")
        first_bytes = Path(first["out"]).read_bytes()
        self.add_node("second", 2)
        second = self.export("graph")
        self.assert_preserved(first, first_bytes, second)
        self.assertEqual([row["id"] for row in self.rows(first)], ["first"])
        self.assertEqual({row["id"] for row in self.rows(second)}, {"first", "second"})

    def test_nodes_exports_keep_each_requested_selection(self):
        self.add_node("second", 2)
        first = self.export("nodes", ids=["first"])
        first_bytes = Path(first["out"]).read_bytes()
        second = self.export("nodes", ids=["second"])
        self.assert_preserved(first, first_bytes, second)
        self.assertEqual([row["id"] for row in self.rows(first)], ["first"])
        self.assertEqual([row["id"] for row in self.rows(second)], ["second"])

    def test_slice_exports_keep_each_filter_result(self):
        self.add_node("tagged-a", 2, tags=["group-a"])
        self.add_node("tagged-b", 3, tags=["group-b"])
        first = self.export("slice", tag="group-a")
        first_bytes = Path(first["out"]).read_bytes()
        second = self.export("slice", tag="group-b")
        self.assert_preserved(first, first_bytes, second)
        self.assertEqual([row["id"] for row in self.rows(first)], ["tagged-a"])
        self.assertEqual([row["id"] for row in self.rows(second)], ["tagged-b"])

    def test_unchanged_memory_exports_have_identical_content_at_distinct_paths(self):
        first = self.export("graph")
        first_bytes = Path(first["out"]).read_bytes()
        second = self.export("graph")
        self.assert_preserved(first, first_bytes, second)
        self.assertEqual(first_bytes, Path(second["out"]).read_bytes())

    def test_explicit_output_path_keeps_the_requested_replacement_behavior(self):
        out = str(self.root / "chosen.jsonl")
        first = self.export("graph", out=out)
        first_bytes = Path(out).read_bytes()
        self.add_node("second", 2)
        second = self.export("graph", out=out)
        self.assertEqual(first["out"], out)
        self.assertEqual(second["out"], out)
        self.assertNotEqual(Path(out).read_bytes(), first_bytes)
        self.assertEqual({row["id"] for row in self.rows(second)}, {"first", "second"})

    def test_concurrent_default_exports_do_not_share_a_temporary_file(self):
        other = self.open_graph()
        ready_to_publish = threading.Barrier(2)
        publish = export.publish

        def synchronized_publish(source, destination):
            # Real writes and real publication; synchronize only the publication boundary.
            ready_to_publish.wait(timeout=10)
            return publish(source, destination)

        with patch.object(export, "publish", synchronized_publish):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.export, "graph", graph=graph)
                           for graph in (self.graph, other)]
                results = [future.result(timeout=15) for future in futures]
        self.assertNotEqual(results[0]["out"], results[1]["out"])
        for result in results:
            self.assertEqual([row["id"] for row in self.rows(result)], ["first"])
            self.assertEqual(len(self.rows(result)), result["written"])
            self.assertFalse(Path(result["out"] + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
