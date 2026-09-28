# -*- coding: utf-8 -*-
"""md_cg · 写路径跨进程索引代际守卫（N195，多进程共享库形态）

缺陷（修复前）：`_maybe_reload_index`（mdcg.py:1034）全仓仅 **5 处** 调用点，
**全在读面**（mdcg.py:2132/2397/2601、mdcos.py:767/1315）。写路径
`MdCG.add`（protect.guard_write 调用点 mdcg.py:1476、prev_entry 取
`self.index` mdcg.py:1607）与 `MdCGOS.forget`（mdcos.py:2356
`self.index["nodes"].get`）直读本进程内存索引 → 他进程（serve 常驻 +
review_cli / hive worker 写方）刚写入、刚保护的 self·anchor 节点对本进程
不可见 → 「不可覆盖」闸静默失效：不抛 ProtectionError、不落
`_protected_history` 快照、不写 `_protected_audit.jsonl`，旧正文不可恢复
且无痕；同根因次生面：`forget` 对他进程新建节点恒返回 not_found
（静默无操作）。行号按修复后（+12 行注释）记。

守卫（五组，全部临时库 + 哑主密钥，绝不触真实 ~/.mdcg）：
  ⓿ 接线审计：写路径 add 确经签名探测（计数桩，修复前 = 0 次即红）；
  ① 常驻 A + 独立 B 写 anchor 节点 + close（compact 落快照，review_cli 退出
     同款）→ A.add 覆写必须被 ProtectionError 拒绝，盘上正文保持 B 的原文；
     并复刻「禁用 reload = 修前病灶」分支，证明失效闸确由代际重载合上；
  ② 删除面：A.forget 同一节点必须被 ProtectionError 拒绝（而非静默
     not_found 无操作）；显式 override=True 后删除成功且 trash 落文件；
  ③ 留痕面：override=True 覆写必须写 `_protected_history/<id>/` 快照 +
     `_protected_audit.jsonl` 记录（修复前闸静默失效 → 两者皆无）；
  ④ prev_entry 面：他进程已置 converged 的节点被 A 覆写后不得静默打回
     active（mdcg.py:1607 直读 self.index 的次生后果）。

运行：python -m md_cg.test_n195_writepath_reload
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from . import protect
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

DUMMY_KEY = "cd" * 32          # 哑主密钥：本进程绝不触真实 ~/.mdcg

BODY_B = "# 功能名：锚点探针\n# 正文：B 进程写入的身份锚点（不可篡改）"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(**kw):
    d = dict(actor="n195", clearance="internal", can_write=True,
             can_admin=True, role="designer", auth_mode="test")
    d.update(kw)
    return Principal(**d)


def _counting(cg):
    """给 _maybe_reload_index 挂计数桩，返回 (计数 dict, 解挂函数)。"""
    calls = {"probe": 0, "reload": 0}
    orig = cg._maybe_reload_index

    def counted():
        calls["probe"] += 1
        r = orig()
        if r:
            calls["reload"] += 1
        return r

    cg._maybe_reload_index = counted
    return calls, (lambda: setattr(cg, "_maybe_reload_index", orig))


def _disk(root, rel):
    """直接读盘上节点文件（不经任何实例内存态）。"""
    from . import nodefile
    p = os.path.join(root, *rel.split("/"))
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return nodefile.loads(f.read())


def _has_node(root, nid):
    """在 root 下按 <layer>/.../<nid>.md 找盘上文件，返回相对路径或 None。"""
    for dp, _d, files in os.walk(root):
        for fn in files:
            if fn == nid + ".md":
                return os.path.relpath(os.path.join(dp, fn),
                                       root).replace("\\", "/")
    return None


def main():
    roots = []
    os.environ["MDCG_MASTER_KEY"] = DUMMY_KEY   # 哑主密钥先行（纪律）
    try:
        # ---------- ⓿ + ① 写保护闸：常驻 A + 独立写方 B ----------
        print("\n【①】常驻 A → 独立 B 写 anchor 节点 + close → A.add 覆写")
        root1 = tempfile.mkdtemp(prefix="n195_1_")
        roots.append(root1)
        a = MdCGSecure(root1, principal=_principal())
        a.add("n195_seed", "# 功能名：种子\n# 正文：常驻 A 初始记忆",
              layer="knowledge")
        a.flush()
        b = MdCGSecure(root1, principal=_principal(actor="writer_b"))
        b.add("n195_anchor_probe", BODY_B, layer="anchor")
        b.close()                       # close → compact：写 _index.json
        rel = _has_node(root1, "n195_anchor_probe")
        check("盘面已有 B 写入的 anchor 节点（setup）", rel is not None,
              "rel=%r" % rel)
        check("setup：A 内存索引尚未见该节点（A 未发生任何读面调用）",
              "n195_anchor_probe" not in (a.index.get("nodes") or {}))

        # ⓿ 接线：写路径确经签名探测
        calls, uncount = _counting(a)
        raised = None
        try:
            a.add("n195_anchor_probe", "# 功能名：伪造\n# 正文：被覆写的伪造内容",
                  layer="anchor")
        except protect.ProtectionError as e:
            raised = e
        finally:
            uncount()
        check("⓿ 接线：写路径 add 经 _maybe_reload_index 签名探测 ≥1 次",
              calls["probe"] >= 1, str(calls))
        # ① 红线：不可覆盖闸必须生效
        check("① 绿：A.add 覆写他进程 anchor 节点被 ProtectionError 拒绝",
              raised is not None, repr(raised)[:120])
        disk = _disk(root1, rel) if rel else None
        check("① 绿：盘上正文保持 B 的原文（未被伪造内容覆写）",
              disk is not None and BODY_B in (disk[1] or ""),
              repr((disk[1] if disk else None))[:100])
        # ①b 复刻「禁用 reload = 修前病灶」：闸确由代际重载合上
        b2 = MdCGSecure(root1, principal=_principal(actor="writer_b2"))
        b2.add("n195_red_probe", BODY_B, layer="anchor")
        b2.close()
        orig_reload = a._maybe_reload_index
        a._maybe_reload_index = lambda: False    # 修前形态：写路径无重载
        red = None
        try:
            a.add("n195_red_probe", "# 功能名：伪造\n# 正文：被覆写的伪造内容",
                  layer="anchor")
        except protect.ProtectionError as e:
            red = e
        finally:
            a._maybe_reload_index = orig_reload
        check("①b 红形态复刻：禁用重载时闸静默失效（不抛 ProtectionError）",
              red is None, repr(red)[:100])
        rel_red = _has_node(root1, "n195_red_probe")
        d2 = _disk(root1, rel_red) if rel_red else None
        check("①b 红形态复刻：盘上正文已被伪造内容覆写（无痕覆写）",
              d2 is not None and "被覆写的伪造内容" in (d2[1] or ""),
              repr((d2[1] if d2 else None))[:80])
        check("①b 红形态复刻：无保护历史、无保护审计（旧正文不可恢复）",
              not os.path.isdir(os.path.join(root1, protect.HISTORY_DIR))
              and not os.path.exists(os.path.join(root1, protect.AUDIT_FILE)))

        # ---------- ② 删除面：forget ----------
        print("\n【②】A.forget 他进程 anchor 节点")
        b3 = MdCGSecure(root1, principal=_principal(actor="writer_b3"))
        b3.add("n195_forget_probe", BODY_B, layer="anchor")
        b3.close()
        fr_raised = None
        try:
            a.forget("n195_forget_probe", reason="N195 删除面")
        except protect.ProtectionError as e:
            fr_raised = e
        check("② 绿：A.forget 受保护节点被 ProtectionError 拒绝（非 not_found）",
              fr_raised is not None, repr(fr_raised)[:120])
        check("② 绿：拒绝后盘上文件仍在（未被静默删除）",
              _has_node(root1, "n195_forget_probe") is not None)
        fr2 = a.forget("n195_forget_probe", reason="N195 覆盖删除",
                       override=True)
        check("② 绿：override=True 后删除成功（ok=True）",
              isinstance(fr2, dict) and fr2.get("ok") is True, str(fr2)[:120])
        rel_fr = _has_node(root1, "n195_forget_probe")
        check("② 绿：删除后文件仅存于 trash/（anchor/ 侧已移出）",
              rel_fr is not None and rel_fr.startswith("trash/"), repr(rel_fr))
        check("② 留痕：override 删除写入 _protected_audit.jsonl",
              os.path.exists(os.path.join(root1, protect.AUDIT_FILE))
              and any(r.get("action") == "override_forget"
                      and r.get("node_id") == "n195_forget_probe"
                      for r in _jsonl(os.path.join(root1,
                                                   protect.AUDIT_FILE))))

        # ---------- ③ 留痕面：override=True 覆写 ----------
        print("\n【③】override=True 覆写受保护节点必须快照 + 审计")
        b4 = MdCGSecure(root1, principal=_principal(actor="writer_b4"))
        b4.add("n195_ovr_probe", BODY_B, layer="anchor")
        b4.close()
        ov = None
        try:
            ov = a.add("n195_ovr_probe", "# 功能名：覆写\n# 正文：显式覆盖后正文",
                       layer="anchor", override=True)
        except Exception as e:                     # noqa: BLE001
            ov = "EXC:%r" % (e,)
        check("③ 覆写成功（override=True 放行）", ov == "n195_ovr_probe",
              repr(ov)[:120])
        hd = os.path.join(root1, protect.HISTORY_DIR, "n195_ovr_probe")
        check("③ 绿：旧版本快照落 _protected_history/<id>/（可恢复）",
              os.path.isdir(hd) and [f for f in os.listdir(hd)
                                     if f.endswith(".md")],
              "history=%s" % (os.listdir(hd) if os.path.isdir(hd) else None))
        check("③ 绿：覆写留痕写进 _protected_audit.jsonl（override_write）",
              any(r.get("action") == "override_write"
                  and r.get("node_id") == "n195_ovr_probe"
                  for r in _jsonl(os.path.join(root1, protect.AUDIT_FILE))))

        # ---------- ④ prev_entry 面：生命周期状态继承 ----------
        print("\n【④】他进程 converged 节点被 A 覆写后不得静默打回 active")
        b5 = MdCGSecure(root1, principal=_principal(actor="writer_b5"))
        b5.add("n195_state_probe", "# 功能名：状态探针\n# 正文：已定型节点",
               layer="knowledge")
        st = b5.set_state("n195_state_probe", "converged", reason="N195 探针")
        b5.flush()
        b5.close()
        check("setup：B 已把该节点置 converged",
              st.get("ok") is True, str(st)[:100])
        a.add("n195_state_probe", "# 功能名：状态探针\n# 正文：普通覆写一次",
              layer="knowledge")
        got = a.get("n195_state_probe") or {}
        check("④ 绿：覆写继承 lifecycle_state=converged（未打回 active）",
              (got.get("frontmatter") or {}).get("lifecycle_state")
              == "converged",
              repr((got.get("frontmatter") or {}).get("lifecycle_state")))
        a.close()

        # ---------- ⑤ 自身写入零额外重载（不回归性能/不自重载） ----------
        print("\n【⑤】自身写入连续 add 不自触发重载")
        root2 = tempfile.mkdtemp(prefix="n195_2_")
        roots.append(root2)
        c = MdCGSecure(root2, principal=_principal())
        c.add("n195_own_seed", "# 功能名：自写种子\n# 正文：own", layer="knowledge")
        c.flush()
        c2, unc2 = _counting(c)
        for i in range(3):
            c.add("n195_own_%d" % i, "# 功能名：自写%d\n# 正文：own %d" % (i, i),
                  layer="knowledge")
        c.flush()
        unc2()
        check("⑤ 自身写入（flush 只追加分片、不改快照签名）重载 0 次",
              c2["reload"] == 0, str(c2))
        check("⑤ 接线在位：3 次 add 经 ≥3 次签名探测",
              c2["probe"] >= 3, str(c2))
        c.close()
    finally:
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


def _jsonl(p):
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


if __name__ == "__main__":
    sys.exit(main())
