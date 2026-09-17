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


# 生效条件：给定 root、job_id（及 ok、extra）时，在 root/jobs_src/job_id 下建目录并写 spec.json、result.json、log.txt；ok 为真值时 result.json 写 ok=True 成功形态，ok 为假值（False）时写 ok=False 与 error="API 限流"；仅当 extra 为真值时额外写以 extra 命名的产物文件，最后返回该目录路径。
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


# 生效条件：给定 tmp 与 cases 时，按序对 cases 中每个可调用项执行 fn(tmp) 并打印 "  PASS <fn.__name__>"，无返回值。
def _run(tmp: str, cases: list) -> None:
    for fn in cases:
        fn(tmp)
        print(f"  PASS {fn.__name__}")


def make_cases():
    state: dict = {}

# 生效条件：给定 tmp 时，对 tmp/wm 调 wm.cmd_init 断言 out["ok"] is True 且 out["branch"]=="main"、wm._git(wm_dir,"rev-parse","--verify","main") 的 returncode==0，再对同一 wm_dir 二次 cmd_init 断言 ok 为 True 且 note 含 "幂等"，最后写 state["wm"]=wm_dir。
    def t_init(tmp):
        wm_dir = os.path.join(tmp, "wm")
        out = wm.cmd_init(wm_dir)
        assert out["ok"] is True and out["branch"] == "main", out
        r = wm._git(wm_dir, "rev-parse", "--verify", "main")
        assert r.returncode == 0, r.stderr
        out2 = wm.cmd_init(wm_dir)  # 幂等
        assert out2["ok"] is True and "幂等" in out2["note"]
        state["wm"] = wm_dir

# 生效条件：给定 tmp 时，用 _mk_job(tmp,"j1",ok=True,extra="out.json") 造 job 并调 wm.cmd_snapshot(job, state["wm"], artifacts="out.json")，断言 out["ok"] is True、branch=="task/j1"、out["commit"] 为真、out["artifacts"]==["out.json"]、message 含 "verdict=ok"，且 rev-parse --abbrev-ref HEAD 回到 "main"。
    def t_snapshot_ok(tmp):
        job = _mk_job(tmp, "j1", ok=True, extra="out.json")
        out = wm.cmd_snapshot(job, state["wm"], artifacts="out.json")
        assert out["ok"] is True and out["branch"] == "task/j1", out
        assert out["commit"] and out["artifacts"] == ["out.json"], out
        assert "verdict=ok" in out["message"], out
        # HEAD 还原回 main（串行契约）
        cur = wm._git_ok(state["wm"], "rev-parse", "--abbrev-ref", "HEAD").strip()
        assert cur == "main", cur

# 生效条件：给定 tmp 时，对 _mk_job(tmp,"j_fail",ok=False) 造出的 job 调 wm.cmd_snapshot(job, state["wm"])（不传 artifacts），断言 out["ok"] is False、out["error"] 含 "凭证不足"、out["verdict"]=="API 限流"。
    def t_snapshot_rejects_failed_job(tmp):
        job = _mk_job(tmp, "j_fail", ok=False)
        out = wm.cmd_snapshot(job, state["wm"])
        assert out["ok"] is False and "凭证不足" in out["error"], out
        assert out["verdict"] == "API 限流", out

# 生效条件：给定 tmp 时，仅建出 tmp/jobs_src/j_empty 空目录（无 result.json）并调 wm.cmd_snapshot(d, state["wm"])，断言 out["ok"] is False 且 out["error"] 含 "不存在"。
    def t_snapshot_rejects_no_result(tmp):
        d = os.path.join(tmp, "jobs_src", "j_empty")
        os.makedirs(d, exist_ok=True)
        out = wm.cmd_snapshot(d, state["wm"])
        assert out["ok"] is False and "不存在" in out["error"], out

# 生效条件：给定 tmp 时，对 _mk_job(tmp,"j2",ok=True)（extra 为默认 None，不写产物）调 wm.cmd_snapshot(job, state["wm"], artifacts="nope.bin")，断言 out["ok"] is False 且 out["error"] 含 "artifacts 缺失"。
    def t_snapshot_rejects_missing_artifact(tmp):
        job = _mk_job(tmp, "j2", ok=True)
        out = wm.cmd_snapshot(job, state["wm"], artifacts="nope.bin")
        assert out["ok"] is False and "artifacts 缺失" in out["error"], out

# 生效条件：给定 tmp 时，调 wm.cmd_merge("task/j1", state["wm"])，断言 out["ok"] is True、out["merged"]=="task/j1"，且 state["wm"]/jobs/j1/artifacts/out.json 的 os.path.isfile 为真、其内容含 "j1"。
    def t_merge(tmp):
        out = wm.cmd_merge("task/j1", state["wm"])
        assert out["ok"] is True and out["merged"] == "task/j1", out
        f = os.path.join(state["wm"], "jobs", "j1", "artifacts", "out.json")
        assert os.path.isfile(f), f
        with open(f, encoding="utf-8") as fh:
            assert "j1" in fh.read()

# 生效条件：给定 tmp 时，先 wm._git_ok(state["wm"],"checkout","-B","task/j1") 使 HEAD 不在 main，再调 wm.cmd_merge("task/j1", state["wm"])，断言 out["ok"] is False 且 out["error"] 含 "main"；最后在 finally 中 checkout 回 main。
    def t_merge_requires_main(tmp):
        wm._git_ok(state["wm"], "checkout", "-B", "task/j1")
        try:
            out = wm.cmd_merge("task/j1", state["wm"])
            assert out["ok"] is False and "main" in out["error"], out
        finally:
            wm._git_ok(state["wm"], "checkout", "main")

# 生效条件：给定 tmp 时，在 wm 中构造 task/a 与 task/b 两条对 shared.txt 写入不同内容的分支，先调 wm.cmd_merge("task/a", ...) 断言 ok True，再调 wm.cmd_merge("task/b", ...) 断言 ok False 且 conflict is True、hint 含 "--abort"，收尾用 git merge --abort 恢复。
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

# 生效条件：给定 tmp 且 HEAD 位于 main、shared.txt 为 "from A\n"、jobs/j1/result.json 的 isfile 为真时，取 rev-parse --short HEAD 调 wm.cmd_revert(sha, state["wm"]),断言 ok True、revert 后 shared.txt 回到 "base\n"、jobs/j1/result.json 仍在，且 cmd_log(state["wm"], limit=3) 的日志行含 "Revert" 或小写 "revert"。
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

# 生效条件：给定 tmp 时，以 sys.executable 加 os.path.join(_HERE,"..","hive","wm.py") 及 "status --wm" state["wm"] 起动子进程，断言 returncode==0，并解析 stdout 末行 JSON 得 out["ok"] is True 且 out["branch"]=="main"。
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


# 生效条件：无必需形参；调用 make_cases() 得到 cases，在 tempfile.TemporaryDirectory(prefix="hive_wm_test_") 中执行 _run(tmp, cases)，随后打印 len(cases)/len(cases) 全绿并返回 0。
def main() -> int:
    cases = make_cases()
    with tempfile.TemporaryDirectory(prefix="hive_wm_test_") as tmp:
        _run(tmp, cases)
    print(f"{len(cases)}/{len(cases)} 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())