# -*- coding: utf-8 -*-
"""test_n469_override_passthrough.py · #469 回归守卫

缺陷：`decontaminate(override=True)` 对**受保护节点**——skip-gate 按 override 放行、
`weaken` 成功，但 `demote` 必然死在 `ProtectionError`（layer 不变），且仍进幂等
名单 ⇒ 此后**有权限者也不再能 demote**（幂等毒化）。

根因：`Mdcg._move_layer` 无 `override` 形参，恒调 `guard_move(..., override=False)`；
`scrub.py` 的 demote 分支也未下传 override。

断言
  A 受保护节点 + override=True ⇒ 必须真的降到 contextual（修复前恒 knowledge）
  B 无 override ⇒ 必须仍被拒（不得因为加了形参就默认放行）
  C 非受保护节点 ⇒ 照常降级（对照，证明不是「一律放行」）

用法
  python -m md_cg.test_n469_override_passthrough            # 全绿
  python -m md_cg.test_n469_override_passthrough --mutate   # 变异自证
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0
_NAMES = ["A", "B", "C"]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


_BODY = r'''
import json, os, shutil, sys, tempfile
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
from md_cg.mdcg import MdCG

root = tempfile.mkdtemp(prefix="mdcg_469_")
out = {}


def put(cg, nid, imp):
    cg.add(nid, "# %s\n\n测试节点。" % nid)
    e = cg.index["nodes"][nid]
    n = cg.get(nid)
    f = dict(n["frontmatter"])
    f["layer"] = "knowledge"
    f["importance"] = imp
    cg._write_node(nid, os.path.join(cg.root, e["path"]), f, n["content"])
    e["importance"] = imp


def L(cg, nid):
    return (cg.get(nid) or {}).get("frontmatter", {}).get("layer")


try:
    cg = MdCG(root)
    put(cg, "prot1", 0.9)
    put(cg, "prot2", 0.9)
    put(cg, "free1", 0.1)
    out["pre"] = L(cg, "prot1")
    cg._move_layer("prot1", "contextual", reason="t", override=True, actor="t")
    out["A"] = L(cg, "prot1")
    try:
        cg._move_layer("prot2", "contextual", reason="t")
        out["B"] = "ALLOWED"
    except Exception as ex:
        out["B"] = type(ex).__name__
    cg._move_layer("free1", "contextual", reason="t")
    out["C"] = L(cg, "free1")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("RESULT" + json.dumps(out))
'''


def run_once():
    r = subprocess.run([sys.executable, "-c", _BODY, _REPO],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT"):
            return json.loads(line[6:])
    return {"err": ((r.stdout or "") + (r.stderr or ""))[-300:]}


def _grade():
    global PASS, FAIL
    PASS = FAIL = 0
    d = run_once()
    if "err" in d:
        check("子进程产出判据", False, d["err"])
        return list(_NAMES)
    check("前置：prot1 初始为 knowledge", d.get("pre") == "knowledge", f"实得 {d.get('pre')}")
    res = [d.get("A") == "contextual", d.get("B") == "ProtectionError",
           d.get("C") == "contextual"]
    check("A override=True 受保护节点应降到 contextual", res[0], f"实得 {d.get('A')}")
    check("B 无 override 仍应被拒（不得默认放行）", res[1], f"实得 {d.get('B')}")
    check("C 非受保护节点应正常降级", res[2], f"实得 {d.get('C')}")
    return [n for n, ok in zip(_NAMES, res) if not ok]


_MUTS = [
    ("MUT-A _move_layer 退回无 override 形参", "md_cg/mdcg.py",
     'def _move_layer(self, node_id: str, to_layer: str, reason: str = "",\n'
     '                    override: bool = False, actor: str = None):',
     'def _move_layer(self, node_id: str, to_layer: str, reason: str = ""):'),
    ("MUT-B guard_move 恒 override=False（=修复前行为）", "md_cg/mdcg.py",
     "protect.guard_move(self, node_id, to_layer, override=override, actor=actor)",
     "protect.guard_move(self, node_id, to_layer)"),
]


def main():
    if "--mutate" not in sys.argv:
        _grade()
        print(f"\n===== {PASS}/{PASS + FAIL} 通过 =====")
        return 0 if FAIL == 0 else 1

    print("变异测试（每条必须恰好点红对应断言）：")
    bad = 0
    for name, rel, old, new in _MUTS:
        p = os.path.join(_REPO, rel)
        src = open(p, encoding="utf-8").read()
        if src.count(old) != 1:
            print(f"  {name}: **锚点命中 {src.count(old)} 次，无法变异 ✗**")
            bad += 1
            continue
        open(p, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
        try:
            red = _grade()
        finally:
            open(p, "w", encoding="utf-8", newline="\n").write(src)
        if red:
            print(f"  {name}: 点红 ✓  (red={red})")
        else:
            print(f"  {name}: **未点红 ✗ 假守卫**")
            bad += 1
    print("\n===== 全绿 =====" if bad == 0 else f"\n===== 失败：{bad} 条假守卫 =====")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
