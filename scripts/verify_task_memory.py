"""Replay the same task-memory request against a baseline or changed checkout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def invoke(repo, root, calls):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MDCG_")}
    env.update(MDCG_ROOT=str(root), MDCG_SUSTAIN="0", MDCG_LEGACY_ENV_AUTH="1",
               MDCG_CAN_ADMIN="1", MDCG_LEGACY_ENV_ADMIN="1", PYTHONPATH=str(repo),
               OPENBLAS_NUM_THREADS="1")
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
    messages.extend({"jsonrpc": "2.0", "id": index + 2, "method": "tools/call",
                     "params": {"name": "cg", "arguments": args}} for index, args in enumerate(calls))
    process = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                             cwd=repo, env=env,
                             input=("\n".join(map(json.dumps, messages)) + "\n").encode(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace")[-2000:])
    responses = [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]
    result = []
    for response in responses:
        if response.get("id", 0) <= 1:
            continue
        if "error" in response:
            raise RuntimeError(response["error"])
        result.append(json.loads(response["result"]["content"][0]["text"]))
    if len(result) != len(calls):
        raise RuntimeError("MCP response count mismatch")
    return result


def replay(repo):
    details = "pytest test_search.py\nERROR: missing fixture 测试环境\n原始数值：timeout=37"
    memory = {"record_id": "first-attempt", "fact": {
        "statement": "搜索超时排查受阻，等待测试环境", "subject": "search.py",
        "outcome": "blocked", "details": details}, "experiences": []}
    with tempfile.TemporaryDirectory(prefix="native-task-memory-replay-") as root:
        first = invoke(repo, root, [
            {"op": "task", "action": "open", "name": "replay-task"},
            {"op": "task", "action": "record_memory", "name": "replay-task", "memory": memory},
        ])[-1]
        if first.get("ok") is False and "未知 task action" in first.get("error", ""):
            return {"state": "absent", "record_error": first["error"]}
        if not first.get("committed"):
            raise RuntimeError(f"record did not commit: {first}")
        recalled, full = invoke(repo, root, [
            {"op": "task", "action": "recall_memory", "name": "replay-task"},
            {"op": "task", "action": "get_memory", "node_id": first["fact_id"]},
        ])
        result = {"state": "supported", "facts": recalled["facts_total"],
                  "experiences": recalled["experiences_total"], "new_process_read": True,
                  "details_exact": full["memory"]["fact"]["details"] == details,
                  "unverified": full["verification_state"] == "unverified"}
        if not (result["facts"] == 1 and result["experiences"] == 0
                and result["details_exact"] and result["unverified"]):
            raise RuntimeError(f"unexpected replay: {result}")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expect", choices=("supported", "absent"), default="supported")
    args = parser.parse_args()
    result = replay(args.repo.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["state"] == args.expect else 1


if __name__ == "__main__":
    raise SystemExit(main())
