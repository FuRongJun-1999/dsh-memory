"""Task-memory behavior guards; real Markdown storage and MCP dispatch."""
from __future__ import annotations

import copy
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from . import audit, task_memory, tasks
from .mcp_server import call_tool, tools_for_surface
from .mdcos import MdCGSecure
from .security import AccessDenied, Principal


def draft(record_id="attempt-1", *, outcome="blocked", subject="search.py", experiences=None):
    return {"record_id": record_id,
            "fact": {"statement": "搜索超时排查：缺少测试环境，等待补充", "subject": subject,
                     "outcome": outcome, "details": "pytest src/test_search.py\nERROR: missing fixture 测试环境"},
            "experiences": experiences or []}


def experience(task="搜索超时诊断", *, boundary="不能用于数据库损坏"):
    return {"task": task, "solution": "先定位请求超时，再核对连接池和重试次数",
            "conditions": "搜索请求超时", "boundary": boundary,
            "verification": "回放 timeout 回归用例", "search_keys": ["timeout", "连接池"]}


class TaskMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-memory-")
        self.root = self.temp.name
        self.cg = MdCGSecure(self.root, principal=Principal(session="session-a", can_admin=True))
        tasks.upsert(self.cg, "search-fix", goal="修复搜索超时", acceptance="回归通过")

    def tearDown(self):
        self.cg.close()
        self.temp.cleanup()

    def call(self, action, **kw):
        return call_tool(self.cg, "cg", {"op": "task", "action": action, "name": "search-fix", **kw})

    def test_blocked_result_survives_without_an_experience(self):
        original = draft()
        result = self.call("record_memory", memory=original)
        self.assertTrue(result["committed"])
        recalled = self.call("recall_memory")
        self.assertEqual(len(recalled["facts"]), 1)
        self.assertEqual(recalled["experiences"], [])
        fact = recalled["facts"][0]
        self.assertEqual(fact["outcome"], "blocked")
        self.assertEqual(fact["verification_state"], "unverified")
        self.assertNotIn("details", fact)
        full = self.call("get_memory", node_id=fact["details_ref"])
        self.assertEqual(full["memory"]["fact"]["details"], original["fact"]["details"])

    def test_immutable_replacement_keeps_full_history(self):
        first = self.call("record_memory", memory=draft(outcome="failed"))
        old_path = Path(self.root, self.cg.get(first["fact_id"])["path"])
        old_bytes = old_path.read_bytes()
        newer = draft("attempt-2", outcome="succeeded")
        newer["fact"]["statement"] = "搜索超时修复，回归通过"
        newer["fact"]["supersedes"] = first["fact_id"]
        second = self.call("record_memory", memory=newer)
        current = self.call("recall_memory")
        self.assertEqual([f["id"] for f in current["facts"]], [second["fact_id"]])
        history = self.call("recall_memory", include_history=True)
        self.assertEqual(history["facts_total"], 2)
        self.assertEqual(old_path.read_bytes(), old_bytes)

    def test_record_identity_rejects_conflicting_retry(self):
        self.call("record_memory", memory=draft())
        changed = draft()
        changed["fact"]["details"] = "different evidence"
        before = len(self.cg.index["nodes"])
        with self.assertRaisesRegex(ValueError, "different content"):
            self.call("record_memory", memory=changed)
        self.assertEqual(len(self.cg.index["nodes"]), before)

    def test_supersession_never_crosses_subject_or_task(self):
        old = self.call("record_memory", memory=draft())
        bad = draft("attempt-2", subject="another.py")
        bad["fact"]["supersedes"] = old["fact_id"]
        before = len(self.cg.index["nodes"])
        with self.assertRaisesRegex(ValueError, "same task and subject"):
            self.call("record_memory", memory=bad)
        tasks.upsert(self.cg, "other-task")
        bad["fact"]["subject"] = "search.py"
        with self.assertRaisesRegex(ValueError, "same task and subject"):
            task_memory.record(self.cg, "other-task", bad)
        self.assertEqual(len(self.cg.index["nodes"]), before + 1)

    def test_experiences_deduplicate_and_keep_source_links(self):
        one = experience()
        first = self.call("record_memory", memory=draft(experiences=[one, one]))
        self.assertEqual(len(first["written"]), 1)
        second = self.call("record_memory", memory=draft("attempt-2", experiences=[one]))
        self.assertEqual(second["written"], [])
        self.assertEqual(second["reused"], first["experience_ids"])
        recalled = self.call("recall_memory")
        self.assertEqual(recalled["facts_total"], 2)
        self.assertEqual(recalled["experiences_total"], 1)
        value = recalled["experiences"][0]
        self.assertEqual(set(value["source_fact_ids"]), {first["fact_id"], second["fact_id"]})
        self.assertEqual(value["verification_state"], "unverified")
        self.assertIn("qualification", value)

    def test_partial_failure_preserves_fact_and_retry_repairs_candidates(self):
        original_add = self.cg.add
        def fail_candidate(*args, **kw):
            if kw.get("layer") == "knowledge":
                raise OSError("injected storage failure")
            return original_add(*args, **kw)
        payload = draft(experiences=[experience()])
        with patch.object(self.cg, "add", side_effect=fail_candidate):
            partial = self.call("record_memory", memory=payload)
        self.assertFalse(partial["ok"])
        self.assertTrue(partial["committed"])
        self.assertTrue(partial["partial"])
        self.assertEqual(self.call("recall_memory")["facts_total"], 1)
        retry = self.call("record_memory", memory=payload)
        self.assertTrue(retry["ok"])
        self.assertTrue(retry["fact_reused"])
        again = self.call("record_memory", memory=payload)
        self.assertEqual(again["written"], [])
        self.assertEqual(self.call("recall_memory")["experiences_total"], 1)

    def test_experience_is_doubted_when_its_evidence_is_falsified(self):
        result = self.call("record_memory", memory=draft(experiences=[experience()]))
        self.cg.verify(result["fact_id"], evidence="回放证实原报告错误", verdict="falsified")
        exp = self.cg.get(result["experience_ids"][0])
        self.assertEqual(exp["frontmatter"]["verification_state"], "doubted")

    def test_batch_validation_precedes_fact_write(self):
        bad_inputs = [None, [], {}, draft(experiences=[{}]), draft()]
        bad_inputs[-1]["fact"]["sensitivity"] = "public"
        before = len(self.cg.index["nodes"])
        for payload in bad_inputs:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.call("record_memory", memory=payload)
        self.assertEqual(len(self.cg.index["nodes"]), before)

    def test_unavailable_write_policy_blocks_persistence(self):
        before = len(self.cg.index["nodes"])
        with patch.object(audit, "resolve_rulebook", return_value=({}, "env", {"code": "injected"})):
            with self.assertRaisesRegex(ValueError, "policy unavailable"):
                self.call("record_memory", memory=draft())
        self.assertEqual(len(self.cg.index["nodes"]), before)

    def test_admission_checks_metadata_and_preserves_fact_on_rejected_experience(self):
        rules, _, error = audit.resolve_rulebook()
        self.assertIsNone(error)
        rules = copy.deepcopy(rules)
        rules["forbidden"].append("FORBIDDEN_EVIDENCE_MARKER")
        payload = draft()
        payload["fact"]["files"] = ["FORBIDDEN_EVIDENCE_MARKER"]
        with patch.object(audit, "resolve_rulebook", return_value=(rules, "test", None)):
            with self.assertRaisesRegex(ValueError, "admission rejected"):
                self.call("record_memory", memory=payload)
            exp = experience()
            exp["search_keys"] = ["FORBIDDEN_EVIDENCE_MARKER"]
            result = self.call("record_memory", memory=draft(experiences=[exp]))
        self.assertTrue(result["committed"])
        self.assertTrue(result["partial"])
        self.assertEqual(self.call("recall_memory")["experiences"], [])
        for nid in self.cg.index["nodes"]:
            self.assertNotIn("FORBIDDEN_EVIDENCE_MARKER", json.dumps(self.cg.get(nid), ensure_ascii=False))

    def test_scoped_filters_and_independent_budgets_precede_limit(self):
        tasks.upsert(self.cg, "another-project")
        for i in range(4):
            task_memory.record(self.cg, "another-project", draft(f"noise-{i}", experiences=[experience()]))
        self.call("record_memory", memory=draft(experiences=[experience()]))
        got = self.call("recall_memory", query="timeout", limit=1)
        self.assertEqual(got["experiences_total"], 1)
        self.assertEqual(len(got["experiences"]), 1)
        all_rows = self.call("recall_memory", limit=1)
        self.assertEqual(len(all_rows["facts"]), 1)
        self.assertEqual(len(all_rows["experiences"]), 1)
        empty = self.call("recall_memory", limit=0)
        self.assertEqual(empty["facts"], [])
        self.assertTrue(empty["facts_truncated"])

    def test_rejected_experience_does_not_take_budget(self):
        self.call("record_memory", memory=draft(experiences=[experience("older"), experience("newer")]))
        original = self.cg.judge_qualification
        def reject_newer(rec, query, context=None):
            if task_memory._memory(rec)["experience"]["task"] == "newer":
                return {"state": "REJECT", "reason": "injected inapplicable candidate"}
            return original(rec, query, context)
        with patch.object(self.cg, "judge_qualification", side_effect=reject_newer):
            got = self.call("recall_memory", limit=1)
        self.assertEqual(got["experiences_total"], 1)
        self.assertEqual([exp["task"] for exp in got["experiences"]], ["older"])

    def test_permissions_are_enforced_by_native_and_mcp_entries(self):
        self.cg.principal.can_write = False
        before = len(self.cg.index["nodes"])
        with self.assertRaises(AccessDenied):
            self.call("record_memory", memory=draft())
        self.cg.principal.can_write = True
        self.cg.principal.ops_allow = ("read",)
        with self.assertRaises(AccessDenied):
            task_memory.record(self.cg, "search-fix", draft())
        self.assertEqual(len(self.cg.index["nodes"]), before)

    def test_private_results_inherit_scope_and_are_hidden_in_other_sessions(self):
        self.cg.principal.clearance = "private"
        self.cg.principal.can_admin = False
        self.cg.add("task_private", "private task", layer="structural", tags=["task"],
                    sensitivity="private", importance=0.5)
        result = task_memory.record(self.cg, "private", draft(experiences=[experience()]))
        for nid in [result["fact_id"], *result["experience_ids"]]:
            self.assertEqual(self.cg.get(nid)["frontmatter"]["sensitivity"], "private")
        self.cg.principal.session = "session-b"
        with self.assertRaises(ValueError):
            task_memory.recall(self.cg, "private")
        with self.assertRaises(ValueError):
            task_memory.get(self.cg, result["fact_id"])

    def test_private_payload_never_appears_in_plaintext_metadata(self):
        self.cg.principal.clearance = "private"
        self.cg.principal.can_admin = False
        self.cg.add("task_private", "private task", layer="structural", tags=["task"],
                    sensitivity="private", importance=0.5)
        payload = draft(experiences=[experience()])
        markers = ("PRIVATE_STATEMENT_731", "PRIVATE_SUBJECT_732", "PRIVATE_DETAILS_733",
                   "PRIVATE_TASK_734", "PRIVATE_SOLUTION_735", "PRIVATE_KEYS_736",
                   "PRIVATE_CONDITIONS_737", "PRIVATE_BOUNDARY_738", "PRIVATE_VERIFICATION_739",
                   "PRIVATE_FILE_740", "PRIVATE_RECORD_741")
        payload["record_id"] = markers[10]
        payload["fact"].update(statement=markers[0], subject=markers[1], details=markers[2], files=[markers[9]])
        payload["experiences"][0].update(task=markers[3], solution=markers[4], search_keys=[markers[5]],
                                          conditions=markers[6], boundary=markers[7], verification=markers[8])
        result = task_memory.record(self.cg, "private", payload)
        self.assertFalse(result["partial"], result)
        for nid in [result["fact_id"], *result["experience_ids"]]:
            raw = Path(self.root, self.cg.index["nodes"][nid]["path"]).read_text(encoding="utf-8")
            for marker in markers:
                self.assertNotIn(marker, raw)
                self.assertNotIn(marker, json.dumps(self.cg.index, ensure_ascii=False))
        for path in Path(self.root).rglob("*"):
            if path.is_file():
                stored = path.read_bytes().decode("utf-8", errors="replace")
                for marker in markers:
                    self.assertNotIn(marker, stored, str(path.relative_to(self.root)))
        again = MdCGSecure(self.root, principal=self.cg.principal)
        try:
            full = task_memory.get(again, result["fact_id"])
            self.assertEqual(full["memory"]["fact"], {**payload["fact"], "supersedes": ""})
            exp = task_memory.get(again, result["experience_ids"][0])
            self.assertEqual(exp["memory"]["experience"]["solution"], markers[4])
            blocked = task_memory.recall(again, "private", query=markers[7])
            self.assertEqual(blocked["experiences_total"], 0)
        finally:
            again.close()

    def test_invalid_limits_and_types_fail_closed(self):
        for limit in (-1, 101, True, "5"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.call("recall_memory", limit=limit)
        with self.assertRaises(ValueError):
            self.call("recall_memory", include_history="false")

    def test_tools_advertise_memory_schema(self):
        rows = tools_for_surface()
        cg_tool = next(item for item in rows if item["name"] == "cg")
        self.assertIn("memory", cg_tool["inputSchema"]["properties"])
        help_result = call_tool(self.cg, "cg", {"op": "help", "query": "task"})
        self.assertIn("record_memory", json.dumps(help_result))

    def test_memory_payload_infers_write_instead_of_silently_opening_task(self):
        result = call_tool(self.cg, "cg", {"op": "task", "name": "search-fix", "memory": draft()})
        self.assertTrue(result["committed"])
        self.assertEqual(self.call("recall_memory")["facts_total"], 1)

    def test_real_stdio_entry_and_process_restart_keep_exact_evidence(self):
        root = str(Path(self.root, "stdio"))
        env = os.environ.copy()
        env.pop("MDCG_TOKEN", None)
        env.update(MDCG_ROOT=root, MDCG_SUSTAIN="0", MDCG_LEGACY_ENV_AUTH="1",
                   MDCG_CAN_ADMIN="1", MDCG_LEGACY_ENV_ADMIN="1")
        def run(calls):
            messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
            messages += [{"jsonrpc": "2.0", "id": i + 2, "method": "tools/call",
                          "params": {"name": "cg", "arguments": args}}
                         for i, args in enumerate(calls)]
            proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                                  cwd=Path(__file__).resolve().parents[1], env=env,
                                  input=("\n".join(map(json.dumps, messages)) + "\n").encode(),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace")[-2000:])
            responses = [json.loads(line) for line in proc.stdout.decode().splitlines()]
            rows = []
            for response in responses:
                if response.get("id", 0) > 1:
                    self.assertNotIn("error", response)
                    result = response["result"]
                    self.assertFalse(result.get("isError"), result)
                    rows.append(json.loads(result["content"][0]["text"]))
            return rows
        first = run([{"op": "task", "action": "open", "name": "entry-test"},
                     {"op": "task", "action": "record_memory", "name": "entry-test", "memory": draft()}])
        fact_id = first[-1]["fact_id"]
        after = run([{"op": "task", "action": "recall_memory", "name": "entry-test"},
                     {"op": "task", "action": "get_memory", "node_id": fact_id}])
        self.assertEqual(after[0]["facts_total"], 1)
        self.assertEqual(after[1]["memory"]["fact"]["details"], draft()["fact"]["details"])


def mutations():
    """Each changed implementation must turn its pre-registered guard red."""
    source = Path(task_memory.__file__).read_text(encoding="utf-8")
    cases = [
        ("M1", "fact persistence", "test_blocked_result_survives_without_an_experience",
         [("if previous is None:", "if False:")]),
        ("M2", "immutable retry", "test_record_identity_rejects_conflicting_retry",
         [('raise ValueError("record_id already names different content; use a new record_id")', 'return None')]),
        ("M3", "current versus historical facts", "test_immutable_replacement_keeps_full_history",
         [("if not include_history and nid in superseded:", "if False:")]),
        ("M4", "evidence links", "test_experiences_deduplicate_and_keep_source_links",
         [('value["source_fact_ids"] = [f["id"] for f in facts\n'
           '                                            if nid in f["data"].get("experience_ids", [])]',
           'value["source_fact_ids"] = []')]),
        ("M5", "verbatim evidence", "test_blocked_result_survives_without_an_experience",
         [('details=_text(fact.get("details", ""), "fact.details", required=False, limit=65536),',
           'details="",')]),
        ("M6", "operation authorization", "test_permissions_are_enforced_by_native_and_mcp_entries",
         [('principal.require_op("task")', 'pass')]),
        ("M7", "qualification before budget", "test_rejected_experience_does_not_take_budget",
         [('if qualification.get("state") == "REJECT":', 'if False:')]),
        ("M8", "task scope before budget", "test_scoped_filters_and_independent_budgets_precede_limit",
         [('if f"task:{task_id}" not in tags:', 'if False:'),
          ('if data.get("task_id") != task_id:', 'if False:')]),
        ("M9", "independent fact commit", "test_partial_failure_preserves_fact_and_retry_repairs_candidates",
         [('errors.append({"id": nid, "error": type(exc).__name__, "reason": str(exc)})', 'raise')]),
        ("M10", "closed input schema", "test_batch_validation_precedes_fact_write",
         [('if not isinstance(value, dict) or set(value) - set(allowed):', 'if not isinstance(value, dict):')]),
        ("M11", "source invalidation", "test_experience_is_doubted_when_its_evidence_is_falsified",
         [('depends_on=[fact_id],', '')]),
        ("M12", "write admission", "test_unavailable_write_policy_blocks_persistence",
         [('_admit(cg, fact_content, sensitivity)', 'pass')]),
        ("M13", "candidate admission", "test_admission_checks_metadata_and_preserves_fact_on_rejected_experience",
         [('_admit(cg, exp_content, sensitivity)', 'pass')]),
        ("M14", "encrypted payload stays out of plaintext metadata", "test_private_payload_never_appears_in_plaintext_metadata",
         [('return {"format": 1, "kind": payload["kind"], "task_id": payload["task_id"],',
           'return {"debug_payload": payload, "format": 1, "kind": payload["kind"], "task_id": payload["task_id"],')]),
        ("M15", "private qualification retains its boundary", "test_private_payload_never_appears_in_plaintext_metadata",
         [('**fm, "non_applicable_conditions": boundary}', '**fm, "non_applicable_conditions": []}')]),
    ]
    failures = []
    package = sys.modules["md_cg"]
    for name, purpose, guard, edits in cases:
        baseline = unittest.TextTestRunner(stream=io.StringIO()).run(TaskMemoryTests(guard))
        if not baseline.wasSuccessful():
            failures.append(name)
            print(f"FAIL: {name} baseline guard is already red: {guard}")
            continue
        changed = source
        for before, after in edits:
            if before not in changed:
                raise AssertionError(f"mutation anchor drift: {name}: {before}")
            changed = changed.replace(before, after)
        module = types.ModuleType("md_cg.task_memory")
        module.__package__ = "md_cg"
        module.__file__ = task_memory.__file__
        with patch.dict(sys.modules, {"md_cg.task_memory": module}), \
                patch.object(package, "task_memory", module), \
                patch.dict(globals(), {"task_memory": module}):
            exec(compile(changed, module.__file__, "exec"), module.__dict__)
            result = unittest.TextTestRunner(stream=io.StringIO()).run(TaskMemoryTests(guard))
        red = {test.id().split(" (", 1)[0] for test, _ in result.failures + result.errors}
        killed = len(red) == 1 and next(iter(red)).endswith("TaskMemoryTests." + guard)
        if not killed:
            failures.append(name)
        print(f"{'PASS' if killed else 'FAIL'}: {name} {purpose} -> {guard}")
    print(f"Mutations: {len(cases) - len(failures)}/{len(cases)} killed; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__" and "--mutate" in sys.argv:
    raise SystemExit(mutations())
elif __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TaskMemoryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"PASS: {result.testsRun - len(result.failures) - len(result.errors)}; "
          f"FAIL: {len(result.failures) + len(result.errors)}")
    raise SystemExit(0 if result.wasSuccessful() else 1)
