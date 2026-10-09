# -*- coding: utf-8 -*-
r"""守卫 · #84.2 越界样例平台化 + #84.4 硬失败按 case 归属（2026-10-09 DSH 端实施）。

背景：
  · #84.2：md_cg/test_imgskill.py 的越界用例写死 Windows 绝对路径——在 POSIX 上
    它不是绝对路径，该腿语义随平台漂移（可能假绿）。
  · #84.4：test/chaos_injection/run_all.py 的汇总判据把 hard_fail 当全局量——任一
    case 硬红，其余本来一致的行也被标「不一致」，读数失真。

判据：
  G1 imgskill 源码不再把 Windows 绝对路径写进越界列表；改为按 os.name 构造
  G2 imgskill 仍保留 ../ 相对越界腿（跨平台语义一致的那条不能被顺带删掉）
  G3 run_all 源码不再有 not hard_fail 的全局污染；改为 case_id 归属集合
  G4 run_all 汇总判据只看本行 + 硬红单列标记
  G5 真跑 imgskill 守卫（本平台）仍通过——证明改动未削弱该腿
运行：python -X utf8 -m md_cg.test_issue84_portability
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SKIPPED = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _pil_available():
    """issue #84 同族：PIL(Pillow) 也是可选依赖；无它时 test_imgskill 根本起不来。"""
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def main():
    img = open(os.path.join(HERE, "test_imgskill.py"), encoding="utf-8").read()
    check("G1 imgskill 越界列表不再写死 Windows 绝对路径（改按 os.name 构造）",
          'for bad in ("../escape.png", "C:/Windows/win.ini"):' not in img
          and '_abs_out = "C:/Windows/win.ini" if os.name == "nt" else "/etc/hosts"' in img, "")
    check("G2 imgskill 仍保留 ../ 相对越界腿",
          'for bad in ("../escape.png", _abs_out):' in img, "")

    runall = open(os.path.join(REPO, "test", "chaos_injection", "run_all.py"),
                  encoding="utf-8").read()
    check("G3 run_all 不再用全局 hard_fail 污染判定（改 case_id 归属集合）",
          "not hard_fail" not in runall and "hard_fail_ids" in runall, "")
    check("G4 run_all 汇总判据只看本行 + 硬红单列",
          "ok = (verdict == exp)" in runall and 'mark = "硬红"' in runall, "")

    if _pil_available():
        # 必须走 `-m`（模块方式）：test_imgskill.py 以相对导入 `from . import imgskill`
        # 取被测件——**直跑脚本**会因「no known parent package」ImportError（rc=1），
        # 那是调用方式的产物，不是该腿被削弱（本守卫的 G5 首版即栽在此）。
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.test_imgskill"],
                           cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, shell=False)
        check("G5 真跑 imgskill 守卫（本平台）仍通过", r.returncode == 0,
              "rc=%r" % (r.returncode,))
    else:
        global SKIPPED
        SKIPPED += 1
        print("  SKIP G5 本解释器无 PIL（Pillow）——按 #84 口径显式跳过，不静默放绿")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d ／ 跳过 %d" % (PASS, FAIL, SKIPPED))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
