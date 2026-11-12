# -*- coding: utf-8 -*-
"""test_issue148_merge_downgrade_leak · 降密级泄漏守卫（issue #148）

# 功能名：合并降密级 fail-closed 守卫
# 生效条件：改动 security.merge_downgrades / writelimit.converge_into / forgetting.reinforce
#           的密级判据或落盘顺序之后必跑
# 子功能：①merge_downgrades 单点的方向与 fail-closed ②converge_into（CONVERGE）拒且**不落盘**
#         ③reinforce（MERGE）同判据 ④同档合并不误伤 ⑤3 条定点变异（恒放 / 恒拦 / 方向反）
# 执行：python -m md_cg.test_issue148_merge_downgrade_leak
# 验证方式：末行「通过 N / 失败 M」；每条给原始读数（返回体 / 落盘正文 / 访客可见性）
# 不适用条件：只测**合并落盘面**的密级判据；沙箱一律 tempfile，绝不触碰在役库

## 病象（issue #148 · C 组）
声明 private 的短记忆经 CONVERGE 被**明文并入更早的 internal 节点**，而目标
frontmatter 的 sensitivity 不变 ⇒ 该 private 明文获得 internal 档可见性（访客可读）。
修法：单点 security.merge_downgrades + 两个落盘点（converge_into / reinforce）**落盘前**判，
判为降密级即 fail-closed 不写盘。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import forgetting, security, writelimit          # noqa: E402
from md_cg.mdcos import MdCGSecure                          # noqa: E402
from md_cg.security import Principal, merge_downgrades      # noqa: E402

PASS = FAIL = 0
FAILS = []
A = "# 功能名：批次1收官记忆\n\n内部内容 AAAA"
B = "# 功能名：批次2收官记忆\n\n私有短记忆 SECRET-BBBB"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


class _Box:
    """一次性沙箱：独立 root/aux，退出时清理。"""

    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="iss148_%s_" % self.tag)
        os.environ["MDCG_ROOT"] = os.path.join(self.dir, "cgroot")
        os.environ["MDCG_AUX_ROOT"] = os.path.join(self.dir, "auxstore")
        os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
        os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
        return os.environ["MDCG_ROOT"]

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _owner(root):
    return MdCGSecure(root, principal=Principal(
        actor="owner", clearance="private", can_write=True, can_admin=True,
        role="designer", session="s1"))


def _visitor(root):
    return MdCGSecure(root, principal=Principal(
        actor="visitor", clearance="internal", can_write=False, role="guest"))


def _seed(cg, node_id="n1", sens="internal"):
    cg.add(node_id, A, layer="contextual", sensitivity=sens)
    return cg.get(node_id)


def scenario(root, monkey=None):
    """跑一次「private 短记忆经 converge_into 并入 internal 节点」，返回读数。"""
    saved = security.merge_downgrades
    if monkey is not None:
        security.merge_downgrades = monkey
    try:
        cg = _owner(root)
        _seed(cg)
        res = writelimit.converge_into(cg, "n1", B, actor="owner", sensitivity="private")
        node = cg.get("n1")
        vis = _visitor(root).get("n1")
        out = {
            "res_ok": res.get("ok"),
            "res_error": res.get("error"),
            "sensitivity": (node.get("frontmatter") or {}).get("sensitivity"),
            "leaked": "SECRET-BBBB" in (node.get("content") or ""),
            "visitor_sees": bool(vis) and "SECRET-BBBB" in (vis.get("content") or ""),
        }
        cg.close()
        return out
    finally:
        security.merge_downgrades = saved


def main():
    print("=== issue #148 合并降密级 fail-closed 守卫 ===")

    print("\n[1] 单点 security.merge_downgrades：方向 + fail-closed")
    check("private 并入 internal ⇒ 判为降密级（True）",
          merge_downgrades("internal", "private") is True)
    check("internal 并入 private ⇒ 非降密级（False，不在本判据范围）",
          merge_downgrades("private", "internal") is False)
    check("同档 ⇒ False（不误伤）", merge_downgrades("internal", "internal") is False)
    check("None 按 DEFAULT_SENSITIVITY（internal）处理",
          merge_downgrades("internal", None) is False and merge_downgrades(None, "private") is True)
    check("非法密级 ⇒ True（fail-closed：判不了就不许合并）",
          merge_downgrades("internal", "bogus") is True)

    print("\n[2] CONVERGE 落盘面：拒 + 不落盘 + 访客读不到明文")
    with _Box("fix") as root:
        r = scenario(root)
    print("    读数：%s" % r)
    check("converge_into 返回 merge_downgrade_refused（fail-closed）",
          r["res_ok"] is False and r["res_error"] == "merge_downgrade_refused", r)
    check("目标正文**未**写入 private 明文（不落盘）", r["leaked"] is False, r["leaked"])
    check("目标节点密级未变（仍是 internal）", r["sensitivity"] == "internal", r["sensitivity"])
    check("internal 档访客**读不到** private 明文", r["visitor_sees"] is False, r["visitor_sees"])

    print("\n[3] MERGE 落盘面（forgetting.reinforce）：同一单点同样拒")
    with _Box("merge") as root:
        cg = _owner(root)
        _seed(cg)
        res = forgetting.reinforce(cg, "n1", actor="owner", content=B, sensitivity="private")
        node = cg.get("n1")
        vis = _visitor(root).get("n1")
        m = {"res": res, "leaked": "SECRET-BBBB" in (node.get("content") or ""),
             "visitor_sees": bool(vis) and "SECRET-BBBB" in (vis.get("content") or "")}
        cg.close()
    print("    读数：ok=%s error=%s leaked=%s visitor_sees=%s"
          % ((m["res"] or {}).get("ok"), (m["res"] or {}).get("error"), m["leaked"], m["visitor_sees"]))
    check("reinforce 同样 fail-closed 且不落盘",
          (m["res"] or {}).get("error") == "merge_downgrade_refused" and m["leaked"] is False, m)
    check("internal 档访客读不到 private 明文（MERGE 路径）", m["visitor_sees"] is False, m["visitor_sees"])

    print("\n[4] 不误伤：同档合并照旧落盘")
    with _Box("same") as root:
        cg = _owner(root)
        _seed(cg)
        res = writelimit.converge_into(cg, "n1", B, actor="owner", sensitivity="internal")
        node = cg.get("n1")
        s = {"ok": res.get("ok"), "appended": "SECRET-BBBB" in (node.get("content") or "")}
        cg.close()
    print("    读数：%s" % s)
    check("同档（internal→internal）合并照旧放行（判据不误伤）",
          s["ok"] is True and s["appended"] is True, s)

    print("\n[5] 定点变异（只 monkeypatch 判据，不改盘上文件）")
    with _Box("m1") as root:
        r1 = scenario(root, monkey=lambda t, i: False)
    print("    M1 判据恒 False → %s" % r1)
    check("M1 恒放行 ⇒ 泄漏复现（守卫必然察觉）",
          r1["leaked"] is True and r1["visitor_sees"] is True, r1)

    with _Box("m2") as root:
        r2 = scenario(root, monkey=lambda t, i: True)
    print("    M2 判据恒 True → %s" % r2)
    check("M2 恒拦截 ⇒ 过度拒（泄漏可挡但误伤一切合并）",
          r2["res_error"] == "merge_downgrade_refused" and r2["leaked"] is False, r2)

    with _Box("m3") as root:
        r3 = scenario(root, monkey=lambda t, i: security._rank(i or security.DEFAULT_SENSITIVITY)
                      < security._rank(t or security.DEFAULT_SENSITIVITY))
    print("    M3 方向写反（new < tgt）→ %s" % r3)
    check("M3 方向反 ⇒ private→internal 漏放、泄漏复现（这是本缺陷最易写反处）",
          r3["leaked"] is True and r3["visitor_sees"] is True, r3)

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
