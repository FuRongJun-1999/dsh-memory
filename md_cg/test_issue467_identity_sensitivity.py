# -*- coding: utf-8 -*-
"""test_issue467_identity_sensitivity.py · #467 身份锚点/特质写入口的密级透传守卫

## 缺陷
`identity.set_anchor` / `identity.add_trait` 内部都走 `cg.add(...)`，但**都不接受也不透传
`sensitivity`**。于是：

  · 调用方想给身份锚点标密级 → **无处可传**（形参不存在，只能靠 TypeError 才被发现）；
  · 即便用别的途径（如 mdcg 的门面）写进去，本入口写出的节点 `fm.sensitivity` 仍是 `None`
    ⇒ 走 `internal` 缺省（`protect._resolve_target` 对缺键回落 internal #450）。

⇒ 身份类内容（往往含真实姓名 / 口令 / 私钥提示）**无法声明更高密级**，只能吃最低档；
而同一 `cg.add` 的其它写入口是可传的——**同族写入口不一致**。

## 本守卫钉住
A. `set_anchor(sensitivity=...)` 落盘节点 `fm.sensitivity` 必须等于声明值（不是 None）。
B. `add_trait(sensitivity=...)` 同上。
C. **缺省零变更**：不传 sensitivity 时行为与修复前逐位一致（`None`），不得自作主张改缺省。
D. 对照：同 cg 上 `cg.add(..., sensitivity=...)` 本身可写通（证明不是 cg 层的问题）。

跑法：
    python -m md_cg.test_issue467_identity_sensitivity            # 断言
    python -m md_cg.test_issue467_identity_sensitivity --mutate    # 变异自证
"""
import io
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


_CHILD = r'''
import os, sys, tempfile
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
from md_cg.mdcg import MdCG
from md_cg import identity

root = tempfile.mkdtemp(prefix="i467_")
cg = MdCG(root)

# A 锚点透传
identity.set_anchor(cg, "user:alice", "口令提示：hunter2", sensitivity="private")
aid = identity.subject_node_id("user:alice")
a_fm = (cg.get(aid) or {}).get("frontmatter") or {}

# B 特质透传（用返回值取 node_id，比前缀扫描可靠）
rb = identity.add_trait(cg, "user:alice", "常用 8812 端口", sensitivity="private")
t_fm = (cg.get(rb["node_id"]) or {}).get("frontmatter") or {}

# C 缺省零变更
rc = identity.add_trait(cg, "user:bob", "默认密级")
t2_fm = (cg.get(rc["node_id"]) or {}).get("frontmatter") or {}

# D cg.add 本身可写
cg.add("probe467", "探针", sensitivity="private")
p_fm = (cg.get("probe467") or {}).get("frontmatter") or {}

import json
print("RESULT " + json.dumps({
    "a_sens": a_fm.get("sensitivity"),
    "t_sens": t_fm.get("sensitivity"),
    "t2_sens": t2_fm.get("sensitivity"),
    "p_sens": p_fm.get("sensitivity"),
}, ensure_ascii=False))
'''


def run_legs():
    cmd = [sys.executable, "-c", _CHILD, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT "):
            import json
            return json.loads(line[len("RESULT "):])
    return {"error": (r.stdout or "")[-400:] + (r.stderr or "")[-400:]}


# 断言单一真源：显示与判决共用同一组 (名称, 谓词)，避免"显示 PASS 却报失败"的自相矛盾。
_CHECKS = [
    ("A set_anchor 透传 sensitivity=private", lambda d: d.get("a_sens") == "private"),
    ("B add_trait 透传 sensitivity=private", lambda d: d.get("t_sens") == "private"),
    ("C 不传 sensitivity 时保持缺省 None（零变更）", lambda d: d.get("t2_sens") is None),
    ("D 对照 cg.add 本身可写 sensitivity", lambda d: d.get("p_sens") == "private"),
]


def assertions(d):
    """返回失败断言名列表（红名单）。子进程无判据 ⇒ 全红。"""
    if not d or d.get("error"):
        return [name for name, _ in _CHECKS] + ["子进程未产出判据"]
    return [name for name, pred in _CHECKS if not pred(d)]


_MUTS = [
    ("MUT-A set_anchor 不透传（=修复前）",
     "require:identity.py",
     'verification_basis="data", override=override,\n'
     '           **({"sensitivity": sensitivity} if sensitivity else {}))',
     'verification_basis="data", override=override)'),
    ("MUT-B add_trait 不透传（=修复前）",
     "require:identity.py",
     'importance=importance, verification_basis=verification_basis,\n'
     '           override=override,\n'
     '           **({"sensitivity": sensitivity} if sensitivity else {}))',
     'importance=importance, verification_basis=verification_basis,\n'
     '           override=override)'),
    ("MUT-C add_trait 缺省改成 private（过度收紧）",
     "require:identity.py",
     'override=False, node_id=None, sensitivity=None):',
     'override=False, node_id=None, sensitivity="private"):'),
]


def _target_path(tag):
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "identity.py")


def main():
    if "--once" in sys.argv:
        d = run_legs()
        red = assertions(d)
        for k, v in (d or {}).items():
            print(f"    {k} = {v!r}")
        print(f"===== {'全绿' if not red else '失败'} =====")
        if red:
            print("失败项：" + "; ".join(red))
        return 0 if not red else 1
    if "--mutate" in sys.argv:
        print("变异测试（每条应恰好点红对应断言）：")
        base = run_legs()
        base_red = assertions(base)
        if base_red:
            print(f"  基线就红：{base_red} —— 先修再变异")
            return 1
        print(f"  基线：未点红 ✓")
        ok_all = True
        for name, tag, old, new in _MUTS:
            p = _target_path(tag)
            src = io.open(p, encoding="utf-8").read()
            if src.count(old) != 1:
                print(f"  {name}: **锚点命中 {src.count(old)} 次（应为 1）**")
                ok_all = False
                continue
            bak = p + ".mutbak"
            with io.open(bak, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(src)
            try:
                with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(src.replace(old, new))
                d = run_legs()
                red = assertions(d)
                if red:
                    print(f"  {name}: 点红 ✓  (red={red})")
                else:
                    print(f"  {name}: **未点红 ✗ 假守卫**")
                    ok_all = False
            finally:
                # 必须 with 关闭（flush）后再删备份；并**校验还原后与原文逐字一致**——
                # 否则残留的变异态会污染**下一个**变异，造出无从解释的假红/假绿。
                with io.open(bak, encoding="utf-8") as fh:
                    back = fh.read()
                with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(back)
                os.remove(bak)
                with io.open(p, encoding="utf-8") as fh:
                    if fh.read() != src:
                        print(f"  **还原校验失败：{p} 与变异前不一致，停止**")
                        return 1
        print(f"===== {'全绿' if ok_all else '失败：存在未达预期变异'} =====")
        return 0 if ok_all else 1
    d = run_legs()
    print("identity 身份写入口密级透传守卫（#467）：")
    for k, v in (d or {}).items():
        print(f"    {k} = {v!r}")
    red = assertions(d)
    for name, pred in _CHECKS:
        check(name, bool(d) and not d.get("error") and pred(d))
    print(f"\n===== 通过 {PASS} ／ 失败 {FAIL} =====")
    if red:
        print("失败项：" + "; ".join(red))
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
