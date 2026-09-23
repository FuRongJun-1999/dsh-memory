# -*- coding: utf-8 -*-
"""批次11：互验时序原语冒烟——派发 → verify_runner 真跑 → verdict 落盘 + 入库。

runner 的套件命令经 env 注入轻量探针（不跑真 cargo——冒烟只验「断言→verdict→
脱敏→落盘→入库」链路；全量套件行为由真实互验轮次承载）。
运行：python -m md_cg.test_p39_verify_flow  （退出码 0 = 全绿）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.interop import (dispatch_verify_job, freeze, make_verdict,
                           sanity_check_verdict, write_verdict_to_repo)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main():
    repo = os.path.dirname(os.path.abspath(__file__)) and \
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="mdcg_b11_")
    try:
        iter_id = "iter_b11_smoke"
        # 冻结（真 manifest）
        frozen = freeze(iter_id)
        check("1a 冻结凭证落 repo 标准位置",
              os.path.isfile(os.path.join(repo, "hive", "interop", iter_id,
                                          "frozen.json")))

        # 派发原语：spec 落验证实例 jobs 目录（非阻塞）
        vjobs = os.path.join(tmp, "vjobs")
        rep = dispatch_verify_job(vjobs, iter_id, subject_fingerprint="fp_main")
        check("1b 派发写 spec+status 且非阻塞返回",
              rep.get("ok") is True
              and os.path.isfile(os.path.join(rep["dispatched"], "spec.json")))

        # runner 冒烟：env 注入轻量探针命令 + 身份/冻结/subject_fp
        env = dict(os.environ)
        env.update({
            "HIVE_INSTANCE": "verifier", "HIVE_ROLE": "verifier",
            "SUBJECT_FP": "fp_main", "ITER_ID": iter_id,
        })
        # freeze 的 digest 基于真判据面——runner 内 A3 用同一 digest，须一致：
        # runner 在本 repo 内跑，判据面未变 → A3 成立
        r = subprocess.run([sys.executable, os.path.join(repo, "hive",
                                                         "verify_runner.py"),
                            iter_id, "--smoke"], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           cwd=tmp)  # cwd≠repo：验证 runner 以自身位置锚定
        out = json.loads(r.stdout)
        check("2a runner 产出 verdict（ok 结构）",
              out.get("ok") is True and "valid" in out, r.stdout[:160])
        vp = os.path.join(repo, "hive", "interop", iter_id, "verdict.json")
        v = json.load(open(vp, encoding="utf-8"))
        check("2b 三断言全过 → valid=true 且 verdict=pass",
              v.get("valid") is True and v.get("verdict") == "pass",
              str(v.get("details"))[:160])
        check("2c 套件计数经宽松解析累加（3+4=7）",
              v.get("passed") == 7, f"passed={v.get('passed')}")

        # 角色守卫：非 verifier 拒跑
        env2 = dict(env)
        env2["HIVE_ROLE"] = "primary"
        r2 = subprocess.run([sys.executable, os.path.join(repo, "hive",
                                                          "verify_runner.py"),
                             iter_id], env=env2, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        check("2d 角色守卫：primary 拒跑互验（§7.1）",
              r2.returncode == 3 and "角色守卫" in r2.stdout,
              f"rc={r2.returncode} out={r2.stdout[:120]} err={r2.stderr[:120]}")

        # 脱敏纵深 + 入库（不 commit）
        bad = dict(v)
        bad["details"] = [{"leak": r"E:\private\node.log"}]
        try:
            sanity_check_verdict(bad)
            check("3a 落盘前脱敏纵深拦截", False, "违规未拦")
        except Exception:
            check("3a 落盘前脱敏纵深拦截", True)
        w = write_verdict_to_repo(v, repo=repo, do_commit=False)
        check("3b verdict 入受版本控制目录（hive/interop/<iter>/）",
              w.get("ok") is True
              and "hive" in w["path"] and "interop" in w["path"], w.get("path"))
        try:
            write_verdict_to_repo({**v, "iter_id": "../evil"}, repo=repo)
            check("3c iter_id 路径注入拒绝", False, "未抛")
        except ValueError:
            check("3c iter_id 路径注入拒绝", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(os.path.join(repo, "hive", "interop", iter_id),
                      ignore_errors=True)

    print(f"\n=== verify flow tests: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
