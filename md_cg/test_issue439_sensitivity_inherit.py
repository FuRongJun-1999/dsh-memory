# -*- coding: utf-8 -*-
"""issue #439 守卫：`MdCGSecure` 三个写入口的密级继承（add_rejected / add_unresolved / add_goal）。

病象（修前）：三者一律 `sensitivity or DEFAULT_SENSITIVITY`，**未声明时把既有节点的
高密级折成 internal**（与 #297 同型，只是走的入口不同）。#297 的单点
`_write_sensitivity` 只接在 `add`/`propose`，故「覆盖语义」的 `add_goal` 每调必重写、
不重传密级即静默降密。

本守卫钉两件事：
  A 三入口**显式声明**时原样落盘；
  B 三入口**未声明**且**同文本再调**时，继承既有密级（不折 internal）。
并按各入口真实语义给出对照（见下）：`add_rejected`/`add_unresolved` 基类是
**幂等 create-once**（`if nid in nodes: return nid` 早退），既有节点根本不再写，
故"显式降级"对其不适用；`add_goal` 是**覆盖语义**，显式降级必须生效。
"""
import io
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from md_cg.mdcos import MdCGSecure                        # noqa: E402
from md_cg.security import Principal                      # noqa: E402

HIGH = "restricted"
LOW = "internal"
_MDCOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "md_cg", "mdcos.py")
_PASS = []
_FAIL = []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  · {detail}" if detail else ""))


def _p(clearance=HIGH):
    return Principal(actor="t", clearance=clearance, can_write=True,
                     can_admin=True, role="designer", session="s", harness="h")


def sens_of(cg, nid):
    try:
        return (cg.get(nid) or {}).get("frontmatter", {}).get("sensitivity")
    except Exception:                                     # noqa: BLE001
        return "<?>"


def main():
    root = tempfile.mkdtemp(prefix="mdcg439_")
    cg = MdCGSecure(root, principal=_p())
    cases = [
        ("add_rejected", False, lambda s=None: cg.add_rejected(
            "假设 X 为真", "反例", verification_basis="test", sensitivity=s)),
        ("add_unresolved", False, lambda s=None: cg.add_unresolved(
            "问 Y 是否成立", known_clues="线索 Z", sensitivity=s)),
        ("add_goal", True, lambda s=None: cg.add_goal("目标 G", sensitivity=s)),
    ]
    print("三入口密级继承（#439）：")
    for name, overwrite, call in cases:
        nid = call(HIGH)
        a = sens_of(cg, nid)
        check(f"A {name} 显式 {HIGH} 原样落盘", a == HIGH, f"实得 {a!r}")
        nid2 = call(None)                     # 同文本再调，不重传密级
        b = sens_of(cg, nid2)
        check(f"B {name} 未声明时继承既有密级", b == HIGH,
              f"实得 {b!r}（修前为 internal 静默降密）")
        nid3 = call(LOW)
        c = sens_of(cg, nid3)
        if overwrite:
            check(f"C {name} 覆盖语义下显式降级生效", c == LOW, f"实得 {c!r}")
        else:
            check(f"C {name} create-once 语义下既有节点不重写（显式降级不适用）",
                  c == HIGH, f"实得 {c!r}")
    print("===== 通过 %d ／ 失败 %d =====" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "; ".join(_FAIL))
    return 1 if _FAIL else 0


def _mutate():
    """把指定入口内的单点调用退回修前语义（`sens = (None) or …` ⇒ 折 internal）。"""
    orig = io.open(_MDCOS, encoding="utf-8").read()
    ok_all = True
    print("变异测试（每条应恰好点红含该入口的 A/B 断言）：")
    for fn in ("add_rejected", "add_unresolved", "add_goal"):
        head = "    def %s(self" % fn
        i = orig.find(head)
        if i < 0:
            print(f"  {fn}: 锚点未命中 ✗")
            ok_all = False
            continue
        j = orig.find("\n    def ", i + 1)
        seg = orig[i:j if j > 0 else len(orig)]
        if "sens = self._write_sensitivity(" not in seg:
            print(f"  {fn}: 入口内无单点调用 ✗")
            ok_all = False
            continue
        new_seg = seg.replace("sens = self._write_sensitivity(",
                              "sens = (None) or (", 1)
        new_src = orig[:i] + new_seg + (orig[j:] if j > 0 else "")
        with io.open(_MDCOS, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_src)
        try:
            # **必须子进程**：同进程里 `md_cg.mdcos` 早已 import，改文件对它无效
            # ⇒ 会得出「变异未点红」的**假结论**（本守卫 v1 就栽在这：9/9 假绿）。
            # `--once` 只跑 main() 并以退出码表示成败，故新进程才会重新 import。
            r = subprocess.run(
                [sys.executable, "-m", "md_cg.test_issue439_sensitivity_inherit",
                 "--once"],
                cwd=_ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180)
            rc = (r.returncode != 0)
            red = [ln.strip() for ln in r.stdout.splitlines() if "[FAIL]" in ln]
            if rc and not red:
                red = [f"{fn} 变异致腿失败（rc={r.returncode}）"]
            print(f"  MUT {fn} 退回修前: {'点红 ✓' if rc and red else '未点红 ✗'}  red={red}")
            if not (rc and red):
                ok_all = False
        finally:
            _PASS.clear()
            _FAIL.clear()
            with io.open(_MDCOS, "w", encoding="utf-8", newline="\n") as f:
                f.write(orig)
            if io.open(_MDCOS, encoding="utf-8").read() != orig:
                print("  !! 还原不一致，硬停")
                return 1
    print("===== " + ("全绿" if ok_all else "失败：存在未达预期变异") + " =====")
    return 0 if ok_all else 1


if __name__ == "__main__":
    if "--once" in sys.argv:
        # `main()` 成功时返回 **0**（falsy）⇒ 不能写 `0 if main() else 1`
        # （会把成功判成失败，进而让变异测试出现**假红**）。0/None/True 皆成功。
        _rc = main()
        sys.exit(0 if (_rc is None or _rc is True or _rc == 0) else 1)
    sys.exit(_mutate() if "--mutate" in sys.argv else main())
