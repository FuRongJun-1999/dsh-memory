# -*- coding: utf-8 -*-
"""蜂巢工作记忆 v0.1 全流程断言测试（三级闸：snapshot→merge→revert）。

直接调模块函数断言返回 dict；末尾补一条 CLI 子进程冒烟（单行 JSON 契约）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "hive_wm", os.path.join(_HERE, "..", "hive", "wm.py"))
wm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wm)


def _mk_job(root: str, job_id: str, ok: bool = True, extra: str | None = None) -> str:
    """造一个蜂巢 job 目录形态：spec.json + result.json + log.txt (+ 产物)。"""
    d = os.path.join(root, "jobs_src", job_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "deepseek-flash", "user_prompt": "x"}, f, ensure_ascii=False)
    result = ({"ok": True, "model": "deepseek-flash", "content": "c", "duration_s": 1.5}
              if ok else {"ok": False, "error": "API 限流", "model": "deepseek-flash"})
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    with open(os.path.join(d, "log.txt"), "w", encoding="utf-8") as f:
        f.write("log line\n")
    if extra:
        with open(os.path.join(d, extra), "w", encoding="utf-8") as f:
            f.write(f"artifact {job_id} {extra}\n")
    return d


def _run(tmp: str, cases: list) -> None:
    for fn in cases:
        fn(tmp)
        print(f"  PASS {fn.__name__}")


def make_cases():
    state: dict = {}

    def t_init(tmp):
        wm_dir = os.path.join(tmp, "wm")
        out = wm.cmd_init(wm_dir)
        assert out["ok"] is True and out["branch"] == "main", out
        r = wm._git(wm_dir, "rev-parse", "--verify", "main")
        assert r.returncode == 0, r.stderr
        out2 = wm.cmd_init(wm_dir)  # 幂等
        assert out2["ok"] is True and "幂等" in out2["note"]
        state["wm"] = wm_dir

    def t_snapshot_ok(tmp):
        job = _mk_job(tmp, "j1", ok=True, extra="out.json")
        out = wm.cmd_snapshot(job, state["wm"], artifacts="out.json")
        assert out["ok"] is True and out["branch"] == "task/j1", out
        assert out["commit"] and out["artifacts"] == ["out.json"], out
        assert "verdict=ok" in out["message"], out
        # HEAD 还原回 main（串行契约）
        cur = wm._git_ok(state["wm"], "rev-parse", "--abbrev-ref", "HEAD").strip()
        assert cur == "main", cur

    def t_snapshot_rejects_failed_job(tmp):
        job = _mk_job(tmp, "j_fail", ok=False)
        out = wm.cmd_snapshot(job, state["wm"])
        assert out["ok"] is False and "凭证不足" in out["error"], out
        assert out["verdict"] == "API 限流", out

    def t_snapshot_rejects_no_result(tmp):
        d = os.path.join(tmp, "jobs_src", "j_empty")
        os.makedirs(d, exist_ok=True)
        out = wm.cmd_snapshot(d, state["wm"])
        assert out["ok"] is False and "不存在" in out["error"], out

    def t_snapshot_rejects_missing_artifact(tmp):
        job = _mk_job(tmp, "j2", ok=True)
        out = wm.cmd_snapshot(job, state["wm"], artifacts="nope.bin")
        assert out["ok"] is False and "artifacts 缺失" in out["error"], out

    def t_merge(tmp):
        out = wm.cmd_merge("task/j1", state["wm"])
        assert out["ok"] is True and out["merged"] == "task/j1", out
        f = os.path.join(state["wm"], "jobs", "j1", "artifacts", "out.json")
        assert os.path.isfile(f), f
        with open(f, encoding="utf-8") as fh:
            assert "j1" in fh.read()

    def t_merge_requires_main(tmp):
        wm._git_ok(state["wm"], "checkout", "-B", "task/j1")
        try:
            out = wm.cmd_merge("task/j1", state["wm"])
            assert out["ok"] is False and "main" in out["error"], out
        finally:
            wm._git_ok(state["wm"], "checkout", "main")

    def t_merge_conflict_honest(tmp):
        """同路径不同内容的两个任务分支：第二个 merge 冲突必须诚实报错不假装成功。"""
        g = lambda *a: wm._git_ok(state["wm"], *a)
        g("checkout", "main")
        with open(os.path.join(state["wm"], "shared.txt"), "w", encoding="utf-8") as f:
            f.write("base\n")
        g("add", "shared.txt")
        g("commit", "-m", "base shared")
        g("checkout", "-B", "task/a")
        with open(os.path.join(state["wm"], "shared.txt"), "w", encoding="utf-8") as f:
            f.write("from A\n")
        g("commit", "-am", "A change")
        g("checkout", "-B", "task/b", "main")
        with open(os.path.join(state["wm"], "shared.txt"), "w", encoding="utf-8") as f:
            f.write("from B\n")
        g("commit", "-am", "B change")
        g("checkout", "main")
        r1 = wm.cmd_merge("task/a", state["wm"])
        assert r1["ok"] is True, r1
        r2 = wm.cmd_merge("task/b", state["wm"])
        assert r2["ok"] is False and r2["conflict"] is True, r2
        assert "--abort" in r2["hint"], r2
        # 现场留给主代理裁决；测试收尾 abort 恢复干净态
        g("merge", "--abort")

    def t_revert(tmp):
        cur = wm._git_ok(state["wm"], "rev-parse", "--abbrev-ref", "HEAD").strip()
        assert cur == "main", cur
        # HEAD 是 merge task/a 的 merge commit：revert 自动 -m 1（保留主线侧），
        # 撤销的只是 task/a 分支引入的变更（shared.txt 回 base）；
        # 更早合并进 main 的 jobs/j1 属主线侧内容，必须保留
        shared = os.path.join(state["wm"], "shared.txt")
        with open(shared, encoding="utf-8") as f:
            assert f.read() == "from A\n"
        j1 = os.path.join(state["wm"], "jobs", "j1", "result.json")
        assert os.path.isfile(j1)
        sha = wm._git_ok(state["wm"], "rev-parse", "--short", "HEAD").strip()
        out = wm.cmd_revert(sha, state["wm"])
        assert out["ok"] is True, out
        with open(shared, encoding="utf-8") as f:
            assert f.read() == "base\n", "revert merge 后分支侧变更应被撤销"
        assert os.path.isfile(j1), "主线侧既有内容不应被撤销"
        log = wm.cmd_log(state["wm"], limit=3)
        assert any("Revert" in ln or "revert" in ln.lower() for ln in log["log"]), log

    def t_cli_smoke(tmp):
        r = subprocess.run(
            [sys.executable, os.path.join(_HERE, "..", "hive", "wm.py"),
             "status", "--wm", state["wm"]],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONUTF8="1"), shell=False,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out["ok"] is True and out["branch"] == "main", out

    return [t_init, t_snapshot_ok, t_snapshot_rejects_failed_job,
            t_snapshot_rejects_no_result, t_snapshot_rejects_missing_artifact,
            t_merge, t_merge_requires_main, t_merge_conflict_honest,
            t_revert, t_cli_smoke]


def main() -> int:
    cases = make_cases()
    with tempfile.TemporaryDirectory(prefix="hive_wm_test_") as tmp:
        _run(tmp, cases)
    print(f"{len(cases)}/{len(cases)} 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
