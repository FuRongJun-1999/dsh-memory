# -*- coding: utf-8 -*-
"""md_cg · 「索引缺条目 → 闸静默跳过」跨进程守卫（N196）

与 N195 同根（`_maybe_reload_index` 未在**做闸判定**的路径上前置），但后果
落在**读隔离**与**授权**两面，与 N195 的写保护面不同：

  ① 读隔离（`MdCGSecure.get`，mdcos.py:4039）：该实现先读
     `self.index["nodes"].get(node_id)`，**缺条目即整段跳过 `_readable`**，
     随后 `super().get()` 内部才重载。他进程（同 actor、异 session）刚写入
     并 compact 的 private（会话绑定档）节点，在常驻实例的**首次** get 被
     解出（第二次读才归 None——那时条目已随重载进索引）。
  ② 授权（`MdCGSecure.verify` falsified 分支，mdcos.py:3887）：N130 的
     `require_layer_write` 只在「索引中有该条目」时执行；他进程刚写入的
     knowledge 层节点在常驻 verifier 实例索引中不存在 → 闸整段跳过 →
     verifier（layers_allow=rejected/contextual）falsified 删掉 knowledge
     层节点，盘上原文消失（先重载则 AccessDenied、原文保留）。

修复口径（与 N195 同款、fail-closed）：闸判定前先 `_maybe_reload_index()`
——「本进程陈旧」与「节点真不存在」两态由此可区分；真不存在时的
not_found / None 语义不变。成本只在未命中路径（一次 stat）。

守卫（两组，全部临时库 + 哑主密钥，绝不触真实 ~/.mdcg）：
  ① 常驻 A(actor=X, session=S1, 非 admin) → 独立写方 B(actor=X, session=S2)
     写 private 节点并 close → A.get 必须 None（读隔离生效）；
     并断言条文条目在重载后确实为「会话绑定档」而非空壳；
  ② 常驻 V(verifier, layers_allow=rejected/contextual) → 独立写方 W 写
     knowledge 节点并 close → V.verify(falsified) 必须 AccessDenied，
     且盘上 knowledge 原文保留（修复前：删除成功、原文消失）。

运行：python -m md_cg.test_n196_stale_gate_skip
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
import tempfile

from .mdcos import MdCGSecure
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []

DUMMY_KEY = "ef" * 32          # 哑主密钥：本进程绝不触真实 ~/.mdcg

READER = "reader_x"            # ① 读写同 actor、异 session（会话绑定档的正例）


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(**kw):
    d = dict(tenant="default", actor=READER, clearance="secret",
             can_write=True, can_admin=False, role="designer",
             auth_mode="test")
    d.update(kw)
    return Principal(**d)


def _md_files(root, layer):
    return [os.path.relpath(p, root).replace("\\", "/") for p in
            glob.glob(os.path.join(root, layer, "**", "*.md"), recursive=True)]


def main():
    roots = []
    os.environ["MDCG_MASTER_KEY"] = DUMMY_KEY     # 哑主密钥先行（纪律）
    try:
        # ---------- ① 读隔离：陈旧索引不得跳过 _readable ----------
        print("\n【①】常驻 A 读他进程写入的同 actor 异 session private 节点")
        root1 = tempfile.mkdtemp(prefix="n196_1_")
        roots.append(root1)
        a = MdCGSecure(root1, principal=_principal(session="S1"))
        a.add("n196_seed", "# 功能名：种子\n# 正文：A 初始记忆", layer="knowledge")
        a.flush()
        # 同 actor（READER）异 session：密文 AAD 只绑 (node_id, tenant, actor)
        # ——actor 一致才能解封，故「读隔离」是这一腿**唯一**的拦截面。
        b = MdCGSecure(root1, principal=_principal(session="S2"))
        b.add("n196_priv", "# 功能名：私密\n# 正文：S2 的会话绑定档",
              layer="knowledge", sensitivity="private")
        b.close()
        check("setup：A 索引尚未含该节点（A 未发生任何读面调用）",
              "n196_priv" not in (a.index.get("nodes") or {}))
        got = a.get("n196_priv")
        check("① 绿：A.get 归 None（跨会话 private 未被解出）",
              got is None, repr(got and got.get("content"))[:80])
        a._maybe_reload_index()
        e = (a.index.get("nodes") or {}).get("n196_priv") or {}
        check("① 对照：重载后条目确为会话绑定档（非空壳，才谈得上被拦）",
              e.get("session") == "S2"
              and _rank_private(e.get("sensitivity")),
              str({k: e.get(k) for k in ("session", "sensitivity")}))
        check("① 对照：重载后再次 get 仍 None（口径一致）",
              a.get("n196_priv") is None)
        res, _ = a.search("会话绑定档")
        check("① 对照：search 面同样不可见",
              not any(n.get("id") == "n196_priv" for n, _s, _q in res),
              str([n.get("id") for n, _s, _q in res])[:80])
        # 同 session 读：绑定档正常可见（防「一律拒读」的过度收紧）
        c = MdCGSecure(root1, principal=_principal(session="S2"))
        own = c.get("n196_priv")
        check("① 反向：同 session 实例可读（未过度收紧）",
              own is not None, repr(own and own.get("content"))[:60])
        c.close()
        a.close()

        # ---------- ② 授权：陈旧索引不得跳过 N130 层写闸 ----------
        print("\n【②】常驻 verifier falsified 他进程新建的 knowledge 层节点")
        root2 = tempfile.mkdtemp(prefix="n196_2_")
        roots.append(root2)
        v = MdCGSecure(root2, principal=_principal(
            actor="verifier_1", role="verifier",
            layers_allow=("rejected", "contextual")))
        v.add("n196_ver_seed", "# 功能名：种子\n# 正文：verifier 自有",
              layer="rejected")
        v.flush()
        w = MdCGSecure(root2, principal=_principal(actor="writer_w"))
        w.add("n196_know_target", "# 功能名：被验证目标\n# 正文：knowledge 原文",
              layer="knowledge")
        w.close()
        check("setup：V 索引尚未含该节点",
              "n196_know_target" not in (v.index.get("nodes") or {}))
        denied = None
        try:
            out = v.verify("n196_know_target", evidence="伪证", verdict="falsified")
            denied = "RET:%r" % (out,)
        except AccessDenied as e:
            denied = e
        check("② 绿：falsified 被 AccessDenied 拒绝（层写闸生效）",
              isinstance(denied, AccessDenied), repr(denied)[:140])
        check("② 绿：knowledge 层原文保留（未被 falsified 删除）",
              _md_files(root2, "knowledge") == ["knowledge/orphan/n196_know_target.md"],
              str(_md_files(root2, "knowledge")))
        # 对照：真不存在时仍走 not_found 透传（未把闸改成无条件拒绝）
        out2 = v.verify("n196_no_such_node", evidence="e", verdict="falsified")
        check("② 反向：索引/盘面皆无此节点时仍透传 None（not_found 语义不变）",
              out2 is None, repr(out2)[:80])
        v.close()
    finally:
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


def _rank_private(sens):
    from .security import SENSITIVITY_ORDER
    try:
        return SENSITIVITY_ORDER.index(sens) >= SENSITIVITY_ORDER.index("private")
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
