"""Behavior and allocation-work guards for state projection; stdlib, temporary roots.

Run: python -X utf8 -m unittest md_cg.test_state_projection_streaming
Timing thresholds are deliberately excluded: these tests guard unnecessary work,
complete consumption, observable diagnostics, and the existing query contract.
"""
import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from . import state_events, state_slots, stg


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="mdcg_projection_")
        self.addCleanup(self.directory.cleanup)
        self.cg = SimpleNamespace(root=self.directory.name)
        self.path = Path(state_events.ledger_path(self.cg))

    def write(self, rows):
        self.path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                     for row in rows), encoding="utf-8")

    def test_page_matches_complete_projection_after_retirement_and_revival(self):
        rng = random.Random(391)
        values = [None, "", " \t", "值", False, 0, [], {"nested": [1]}]
        for trial in range(20):
            rows = [dict(subject=rng.choice([None, "甲", "乙", 0, "0"]),
                         slot=rng.choice([None, "住所", "工具"]),
                         new=rng.choice(values), old=rng.choice(values),
                         t=100-i, seq=-i, tier=rng.choice([None, False, "", "一手"]),
                         evidence={"source": i}, actor="guard") for i in range(60)]
            self.write(rows)
            for history, retired in itertools.product((False, True), repeat=2):
                # The established replay path is independent of the current-state reducer.
                expected = state_slots._project(rows, include_retired=retired, history=history)
                for cap in (None, -3, 0, 1, 4, 100, "2", 1.9):
                    with self.subTest(trial=trial, history=history, retired=retired, cap=cap):
                        total, items = state_slots.project_page(
                            self.cg, include_retired=retired, history=history, limit=cap)
                        self.assertEqual(total, len(expected))
                        stop = None if cap is None else max(0, int(cap))
                        self.assertEqual(items, expected[:stop])

    def test_only_returned_histories_are_constructed(self):
        rows = [dict(subject=f"s{i:03}", slot="x", new=i) for i in range(200)]
        # First key retires late; last key revives late. Neither changes file ordering.
        rows += [dict(subject="s000", slot="x", new=" "),
                 dict(subject="s199", slot="x", new=None),
                 dict(subject="s199", slot="x", new=False)]
        self.write(rows)
        with patch.object(state_slots, "_hist_item", wraps=state_slots._hist_item) as item:
            total, page = state_slots.project_page(self.cg, limit=2)
            self.assertEqual(total, 199)
            self.assertEqual([u["subject"] for u in page], ["s001", "s002"])
            self.assertEqual(item.call_count, 2)
        for history in (False, True):
            with patch.object(state_slots, "_replay", side_effect=AssertionError("unreturned unit")):
                self.assertEqual(state_slots.project_page(self.cg, history=history, limit=0),
                                 (199, []))

    def test_page_consumes_tail_once_and_preserves_diagnostics(self):
        self.write([dict(subject=f"s{i}", slot="x", new=i) for i in range(4)])
        with self.path.open("ab") as output:
            output.write(b'{"subject":"partial\xe4')
        before = self.path.read_bytes()
        for history, cap in itertools.product((False, True), (0, 1, 50)):
            with patch.object(state_events, "iter_read", wraps=state_events.iter_read) as read:
                count = state_events.BAD_ROWS
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    total, page = state_slots.project_page(self.cg, history=history, limit=cap)
                self.assertEqual(total, 4)
                self.assertEqual(len(page), min(4, cap))
                self.assertEqual(state_events.BAD_ROWS, count + 1)
                self.assertIn("5", errors.getvalue())
                self.assertEqual(read.call_count, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path])

    def test_current_and_status_do_not_retain_raw_events(self):
        class TrackedRecord(dict):
            pass

        def stream():
            refs = []
            for i in range(200):
                rec = TrackedRecord(subject="one", slot="x", new=i, evidence="e" * 1024)
                refs.append(weakref.ref(rec))
                self.assertLessEqual(sum(ref() is not None for ref in refs), 2)
                yield rec
        with patch.object(state_events, "iter_read", side_effect=lambda *a, **k: stream()):
            self.assertEqual(state_slots.project(self.cg, history=False)[0]["event_count"], 200)
            self.assertEqual(state_slots.status(self.cg)["events"], 200)

    def test_filters_and_append_visibility(self):
        self.write([dict(subject="甲", slot="x", new="旧"),
                    dict(subject="甲", slot="y", new="另"),
                    dict(subject="乙", slot="x", new="乙")])
        total, first = state_slots.project_page(self.cg, subject="甲", slot="x")
        snapshot = json.dumps(first, ensure_ascii=False)
        self.assertEqual((total, first[0]["value"]), (1, "旧"))
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(dict(subject="甲", slot="x", new="新")) + "\n")
        self.assertEqual(state_slots.project_page(self.cg, subject="甲", slot="x")[1][0]["value"], "新")
        self.assertEqual(json.dumps(first, ensure_ascii=False), snapshot)
        self.assertEqual(state_slots.project_page(self.cg, subject="不存在"), (0, []))

    def test_stg_limits_counts_and_disabled_branch(self):
        self.write([dict(subject=f"s{i:03}", slot="x", new=i) for i in range(80)])
        with patch.dict(os.environ, {"MDCG_STG_STATE": "0"}):
            with patch.object(state_events, "iter_read", side_effect=AssertionError("disabled")):
                self.assertEqual(stg.state_chain(self.cg)["error"], "disabled")
        with patch.dict(os.environ, {"MDCG_STG_STATE": "1"}):
            for cap in (None, -2, 0, 1, 50, "2", 1.9):
                result = stg.state_chain(self.cg, limit=cap)
                kept = 0 if cap is None else min(80, max(0, int(cap)))
                self.assertEqual((result["count"], result["kept"], result["truncated"]),
                                 (80, kept, kept < 80))
                self.assertEqual(result["limit"], cap)
            self.assertEqual(len(stg.state_chain(self.cg)["items"]), 50)
            with self.assertRaises(ValueError):
                stg.state_chain(self.cg, limit="invalid")


if __name__ == "__main__":
    unittest.main()
