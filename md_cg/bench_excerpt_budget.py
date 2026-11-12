"""Frozen-source excerpt/recall replay; evidence retention, not QA accuracy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def worker(repo, workspace):
    sys.path.insert(0, str(Path(repo).resolve()))
    for key in list(os.environ):
        if key.startswith("MDCG_"):
            os.environ.pop(key)
    os.environ.update(MDCG_HOTCACHE="0", MDCG_FRESHNESS="0", MDCG_UNIFY_QUERY="0",
                      MDCG_EN_ATOMS="0", MDCG_SEMANTIC="0")
    from md_cg import mdcos
    texts = {"ascii": "a" * 160 + " evidenceKEEP42 " + "tail" * 500,
             "cjk": "甲乙丙丁" * 500,
             "mixed": "Alpha 中文 calibration\n" * 150,
             "japanese": "あいうえおカキクケコ" * 200,
             "whitespace": "a  b\t c\n\u2003d " * 150}
    rows = []
    for name, text in texts.items():
        for budget in (1, 80, 250):
            result = mdcos.excerpt_tokens(text, budget)
            rows.append({"case": name, "budget": budget, "input_chars": len(text),
                         "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                         "result": result, "chars": len(result), "tokens": mdcos.est_tokens(result),
                         "marker_retained": "evidenceKEEP42" in result})
    recalls = []
    with tempfile.TemporaryDirectory(prefix="excerpt_replay_", dir=workspace) as root:
        cg = mdcos.MdCGOS(root)
        try:
            cg.add("english_evidence", "anchorrecord " + texts["ascii"], layer="knowledge",
                   verification_basis="data", verification_state="doubted", source="synthetic:excerpt",
                   session="excerpt-test")
            cg.flush()
            for use_rrf in (False, True):
                out = cg.recall("anchorrecord", budget_tokens=80, max_item_tokens=80,
                                use_rrf=use_rrf, paths=("lexical",), judge=False)
                recalls.append({"use_rrf": use_rrf, "tokens_used": out["tokens_used"],
                                "budget": out["budget"], "skipped": out["skipped"],
                                "pack": [{key: row.get(key) for key in (
                                    "id", "content", "tokens", "score", "state", "truncated", "metadata", "provenance")}
                                         for row in out["pack"]]})
        finally:
            cg.close()
    return {"commit": subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"],
                                             text=True, encoding="utf-8", errors="replace").strip(),
            "mdcos_git_blob": subprocess.check_output(["git", "-C", repo, "hash-object", "md_cg/mdcos.py"],
                                                      text=True, encoding="utf-8", errors="replace").strip(),
            "excerpts": rows, "recalls": recalls}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--output", default="excerpt-replay.json")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.repo, args.workspace), ensure_ascii=False))
    else:
        if not args.baseline:
            parser.error("--baseline is required")
        report = {"limits": ["five synthetic text families and one controlled memory",
                             "actual frozen-source recall in separate processes; no patched production functions",
                             "estimated tokens, not any model tokenizer or QA score",
                             "return packing may retain more text and leave less room for later memories"]}
        for arm, repo in (("before", Path(args.baseline).resolve()), ("after", Path(__file__).resolve().parents[1])):
            proc = subprocess.run([sys.executable, "-X", "utf8", __file__, "--worker", "--repo", str(repo),
                                   "--workspace", str(Path(args.workspace).resolve())],
                                  capture_output=True, encoding="utf-8", check=True)
            report[arm] = json.loads(proc.stdout)
        for old, new in zip(report["before"]["excerpts"], report["after"]["excerpts"]):
            assert old["input_sha256"] == new["input_sha256"]
            assert new["tokens"] <= new["budget"]
            assert new["chars"] >= old["chars"]
        for old, new in zip(report["before"]["recalls"], report["after"]["recalls"]):
            assert len(old["pack"]) == len(new["pack"]) == 1
            for key in ("id", "score", "state", "metadata", "provenance"):
                assert old["pack"][0][key] == new["pack"][0][key], key
            assert "evidenceKEEP42" not in old["pack"][0]["content"]
            assert "evidenceKEEP42" in new["pack"][0]["content"]
            assert new["tokens_used"] <= new["budget"]
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"before": report["before"]["recalls"], "after": report["after"]["recalls"]}, ensure_ascii=False))
