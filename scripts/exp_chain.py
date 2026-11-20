"""多轮链式实验：把上一轮输出喂回，测跨轮复述与同轮催稿（#996 两个判据）。

为什么需要链式：复读是跨轮现象，单轮 spawn 测不到。hive 子代理无记忆，
因此由本脚本**显式拼接历史**再提交下一轮 —— 这正是 #996 描述的机制。

用法：python -X utf8 scripts/exp_chain.py --spec <chain_spec.json> --out <dir> --hive-bin ... --hive-jobs ...
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

ENV = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")


def submit(hive_bin, spec_obj, cwd, identity, task, unit):
    tmp = os.path.join(cwd, ".chain_spec_tmp.json")
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f, ensure_ascii=False)
    p = subprocess.run([hive_bin, "submit", "--spec", tmp, "--identity", identity,
                        "--task", task, "--unit", unit],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV, shell=False, timeout=120)
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if d.get("ok") and d.get("job_id"):
                return d["job_id"]
            raise RuntimeError("submit 被拒：%s" % json.dumps(d, ensure_ascii=False)[:200])
    raise RuntimeError("submit 无输出：%s" % out[:200])


def wait(jobs_dir, jid, timeout_s=300):
    p = os.path.join(jobs_dir, jid, "result.json")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if os.path.isfile(p):
            try:
                with io.open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(3)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hive-bin", required=True)
    ap.add_argument("--hive-jobs", required=True)
    ap.add_argument("--model", default="deepseek-flash")
    a = ap.parse_args(argv)
    with io.open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    os.makedirs(a.out, exist_ok=True)
    turns = int(spec.get("turns", 5))
    for arm in spec["arms"]:
        for c in range(int(spec.get("chains", 2))):
            history = []
            chain_rec = []
            for t in range(1, turns + 1):
                prompt = [spec["base_task"]]
                if arm.get("prefix"):
                    prompt.append(arm["prefix"])
                if history:
                    prompt.append("【前几轮的输出】")
                    for i, h in enumerate(history, 1):
                        prompt.append("第 %d 轮：%s" % (i, h[:1200]))
                prompt.append("【现在】请继续完善。直接给新的版本，不要重复前面的原话。")
                body = "\n\n".join(prompt) + "\n<!-- chain:%s-c%d-t%d -->" % (arm["name"], c + 1, t)
                job = {"model": a.model, "user_prompt": body, "timeout_s": 600}
                jid = submit(a.hive_bin, job, a.out, "dsh端", "链条复读", "输出单元")
                res = wait(a.hive_jobs, jid)
                txt = ((res or {}).get("content") or "")
                history.append(txt)
                rec = {"arm": arm["name"], "chain": c + 1, "turn": t,
                       "job_id": jid, "text": txt, "ts": time.time()}
                with io.open(os.path.join(a.out, "%s_c%d_t%d.json" % (arm["name"], c + 1, t)),
                              "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=1)
                chain_rec.append(len(txt))
                print("[%s c%d t%d] %s | %d 字" % (arm["name"], c + 1, t, jid, len(txt)))
    print("完成 → %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())