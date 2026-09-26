# -*- coding: utf-8 -*-
"""故障注入套件全量入口：逐 case 子进程实跑 → 与 registry 登记比对 → 退出码。

退出码语义（实验员守则约定）：
  0 = 全部用例观测状态与登记一致（pass 用例绿 + EXPECTED_GAP 用例确认缺口仍在）
  1 = 出现未登记的新 gap（pass 用例回归/防线弱化）或用例与登记不一致
      （含 EXPECTED_GAP 缺口消失——提示改登记结案）或执行层崩溃（untestable）

用法（任意 cwd 均可）：
    python test/chaos_injection/run_all.py            # 全量（R 面 9 + M 面 9 = 18 case）
    python test/chaos_injection/run_all.py -k R04     # 按关键字过滤 case 文件名
    python test/chaos_injection/run_all.py -k M       # 只跑 mdcg 面
    python test/chaos_injection/run_all.py --list     # 只列目标不执行
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
from registry import REGISTRY  # noqa: E402

CASES = [
    "test_fi_r01_clock_rollback.py",
    "test_fi_r02_kill_serve_recover.py",
    "test_fi_r03_fake_result_ok.py",
    "test_fi_r04_wal_flip.py",
    "test_fi_r05_wal_drop_line.py",
    "test_fi_r06_wal_reorder_dep.py",
    "test_fi_r07_double_serve_claim.py",
    "test_fi_r08_default_secret_forge.py",
    "test_fi_r09_replace_handle_collision.py",
    # ---- mdcg 面（md_cg 记忆本体）----
    "test_fi_m01_token_clock_rollback.py",
    "test_fi_m02_transient_read_negative_cache.py",
    "test_fi_m03_reinforce_stale_read.py",
    "test_fi_m04_sustain_concurrent_collision.py",
    "test_fi_m05_twophase_kill_between.py",
    "test_fi_m06_llm_forged_answer_gate.py",
    "test_fi_m07_empty_env_token_fallback.py",
    "test_fi_m08_frozen_digest_flip_a3.py",
    "test_fi_m09_guest_write_denied.py",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", dest="kw", default="", help="按子串过滤 case 文件名")
    ap.add_argument("--list", action="store_true", dest="list_only")
    args = ap.parse_args()

    targets = [c for c in CASES if args.kw.lower() in c.lower()]
    if args.list_only:
        print("\n".join(targets))
        return 0

    results = []
    hard_fail = False
    for c in targets:
        case_id = c[5:11].upper().replace("_", "-")  # test_fi_r01_... → FI-R01
        reg = REGISTRY.get(case_id)
        print(f"\n===== {case_id}  {reg['title'] if reg else '(未登记!)'} "
              f"[登记: {reg['expected_verdict'] if reg else '?'}] =====")
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(_HERE, c)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300, cwd=_REPO)
            elapsed = time.time() - t0
            out = r.stdout
            parsed = None
            for line in out.splitlines():
                if line.startswith("CASE_RESULT "):
                    parsed = json.loads(line[len("CASE_RESULT "):])
            print(out.rstrip()[-2500:])
            if r.returncode not in (0, 1):
                print(f"  !! 执行层异常 rc={r.returncode}（视同 untestable，硬红）")
                print((r.stderr or "")[-800:])
                hard_fail = True
                results.append((case_id, "untestable", reg, elapsed))
                continue
            if parsed is None:
                print("  !! 未产出 CASE_RESULT 结论行（硬红）")
                hard_fail = True
                results.append((case_id, "untestable", reg, elapsed))
                continue
            results.append((case_id, parsed["verdict"], reg, elapsed))
        except subprocess.TimeoutExpired:
            print("  !! 用例超时 300s（硬红）")
            hard_fail = True
            results.append((case_id, "untestable", reg, 300.0))

    print("\n===== 汇总 =====")
    rc = 0
    for case_id, verdict, reg, elapsed in results:
        exp = reg["expected_verdict"] if reg else "?"
        tag = reg["gap_tag"] if reg and reg["gap_tag"] else "-"
        ok = (verdict == exp) and not hard_fail
        if not ok:
            rc = 1
        print(f"  [{'一致' if ok else '不一致'}] {case_id}  "
              f"观测={verdict}  登记={exp}  留档={tag}  ({elapsed:.1f}s)")
    if rc == 0:
        print("\nALL CONSISTENT: 全部用例观测状态与登记一致 → EXIT 0")
        print("（EXPECTED_GAP 格=确认缺口仍在的基线维持；pass 格=防线回归守卫）")
    else:
        print("\nREGISTRY DRIFT: 存在未登记新 gap / pass 用例回归 / "
              "EXPECTED_GAP 缺口消失 → EXIT 1")
        print("（缺口消失属修复落地：请同步改写 registry.py 登记为 pass 结案）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
