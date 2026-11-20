"""实验台 · 派发器：按预注册 spec 批量提交 hive 任务并落原文。

设计要点（都是踩过的坑）：
  ① 不用 MCP 面，走 CLI `hive submit --spec <file>`——确定性编排不进 MCP。
  ② 命令统一 subprocess.run(argv) + shell=False + 显式 UTF-8（工作纪律第 15 条）。
  ③ 不依赖轮询接口：直接盯 `hive/jobs/<job_id>/result.json` 落盘。
  ④ 本文件不写任何本机绝对路径：hive 可执行文件与 jobs 目录由 --hive-bin / --hive-jobs 或环境变量给。

用法：
    python -X utf8 scripts/exp_runner.py --spec experiments/specs/persona_v1.json \
        --repo-root <目标仓根> --out artifacts/persona_v1 \
        --hive-bin <hive.exe> --hive-jobs <hive/jobs> --limit 4
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

ENV = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")


def _argv(args):
    return [str(a) for a in args]


def submit(hive_bin, spec_obj, cwd, identity, task, unit):
    """提交一个 job，返回 job_id（失败抛 RuntimeError 并带原始输出）。"""
    tmp = os.path.join(cwd, ".exp_spec_tmp.json")
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f, ensure_ascii=False)
    p = subprocess.run(_argv([hive_bin, "submit", "--spec", tmp,
                                 "--identity", identity, "--task", task,
                                 "--unit", unit]),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV, shell=False, timeout=120)
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if d.get("ok") and d.get("job_id"):
            return d["job_id"]
        raise RuntimeError("submit 被拒：%s" % json.dumps(d, ensure_ascii=False)[:300])
    raise RuntimeError("submit 无输出（exit=%s）：%s" % (p.returncode, out[:300]))


def wait_result(jobs_dir, job_id, timeout_s=600):
    """等 `hive/jobs/<id>/result.json` 出现并解析。"""
    path = os.path.join(jobs_dir, job_id, "result.json")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if os.path.isfile(path):
            try:
                with io.open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(3)
    return None


def build_prompt(task, arm, spec):
    """题面 + 前缀。支持两种写法：
      ① 旧版 arm["extra"]=True → 取 spec["extra_instructions"]（persona_v1）
      ② 新版 arm["prefix"]="persona" → 取 spec["prefixes"]["persona"]（persona_v2）
    """
    p = task["prompt"]
    pre = ""
    if arm.get("prefix") is not None:
        pre = (spec.get("prefixes") or {}).get(arm["prefix"]) or ""
    elif arm.get("extra"):
        pre = spec.get("extra_instructions") or ""
    if pre:
        p = p + chr(10) + pre
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--repo-root", default=None, help="上下文文件的基准目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hive-bin", default=os.environ.get("HIVE_BIN"))
    ap.add_argument("--hive-jobs", default=os.environ.get("HIVE_JOBS_DIR"))
    ap.add_argument("--limit", type=int, default=0, help=">0 时只跑前 N 个样本（试跑用）")
    ap.add_argument("--model", default="deepseek-flash")
    a = ap.parse_args(argv)
    with io.open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    if not a.hive_bin or not a.hive_jobs:
        print("缺 --hive-bin / --hive-jobs（或 HIVE_BIN / HIVE_JOBS_DIR）")
        return 2
    os.makedirs(a.out, exist_ok=True)
    index = os.path.join(a.out, "index.jsonl")
    done = 0
    for arm in spec["arms"]:
        for task in spec["tasks"]:
            for i in range(int(spec["repeats"])):
                if a.limit and done >= a.limit:
                    print("达 --limit %d，停止" % a.limit)
                    return 0
                ctx = []
                if arm.get("context"):
                    base = a.repo_root or ""
                    ctx = [os.path.join(base, c) for c in task.get("context_files") or []]
                sample_no = done + 1
                job = {
                    "model": a.model,
                    "user_prompt": build_prompt(task, arm, spec) + "\n<!-- sample:%d -->" % sample_no,
                        "timeout_s": 900,
                }
                if ctx:
                    job["context_files"] = ctx
                    job["tools"] = task.get("tools") or ["read_file"]
                jid = submit(a.hive_bin, job, a.out, "dsh端", "人格化消融", "输出单元")
                _t = time.time()
                res = wait_result(a.hive_jobs, jid)
                _wait = time.time() - _t
                rec = {"arm": arm["name"], "task": task["id"], "domain": task["domain"],
                       "repeat": i + 1, "job_id": jid, "ok": res is not None,
                       # result.json 的顶层就是 result（含 content/usage），
                       # 早期版本误读成 res["result"]["content"] ⇒ 60 份全空。此处兼容两种形态。
                       "text": ((res or {}).get("content")
                                or (((res or {}).get("result") or {}).get("content"))
                                if isinstance(res, dict) else None),
                       "usage": ((res or {}).get("result") or {}).get("usage") if isinstance(res, dict) else None,
                       "system_prompt_source": (res or {}).get("system_prompt_source") if isinstance(res, dict) else None,
                       "ts": time.time()}
                fn = os.path.join(a.out, "%s__%s__r%d.json" % (arm["name"], task["id"], i + 1))
                with io.open(fn, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=1)
                with io.open(index, "a", encoding="utf-8") as f:
                    f.write(json.dumps({k: rec[k] for k in ("arm", "task", "domain", "repeat", "job_id", "ok", "system_prompt_source")}, ensure_ascii=False) + chr(10))
                done += 1
                print("[%d] %s / %s / r%d -> %s (%s, %.0fs)" % (done, arm["name"], task["id"], i + 1, jid, "ok" if res else "timeout", _wait))
    print("完成 %d 个样本 → %s" % (done, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())