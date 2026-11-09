# -*- coding: utf-8 -*-
"""protect.py 两处 fail-open 的**防漏改守卫**（t98a-20261011 / t2）。

运行：python -X utf8 md_cg/test_t98a_protect_override.py
      python -X utf8 -m md_cg.test_t98a_protect_override
      python -m md_cg.run_tests md_cg -k t98a

被测对象是 `md_cg/protect.py` 的两个单点函数，**不是**子进程脚本，故本套不起
子进程、只在进程内用**最小合成 cg**（stub）直调：

  `_allow(cg, node_id, why, action, override, actor)`  ← fail-open ①
  `require_layer(cg, node_id, layer=…, …)`             ← fail-open ②

stub 的形态取自真实 `MdCG.__init__(self, root, autoflush=64)` 面：
`root` 指向 tempfile 临时目录、`index.nodes` 有对应条目、`principal=None`
（裸 MdCG 无身份模型 —— 这是基类面的**常态**，见 protect.py:470-472）。
临时目录用完即删，**绝不碰真实 ~/.mdcg**。

三条判据（对应验收 ①②③）：

  A **拒授权** —— 无显式授权时 `_allow` 返回的 `override` 必须为**假**；
     且以 monkeypatch 包住 `protect._audit`，断言它**被调用过**：拒绝路径本身
     就是最该留痕的事件，审计不得因拒授权而丢失。
  B **不可判定** —— 裸 MdCG 上调 `require_layer` 必须给出**显式不可判定标记**
     （二元组）或抛错；**不得**是「能当层名用的 str」（拿到层名即视作层闸已过
     的静默放行，在类型上就不成立）。同时断言 `layer_gate` 审计照样落。
  C **正路仍在** —— 显式 override（`override=True` 且 actor/why 带授权语料）
     的调用仍须得到 `override: True`；合法显式 override 不得被一起堵死。
     含「只有旗标、没有语料」的反例（须拒）以证明 C 不是恒真。

沙箱注记：本套不起子进程，故与 CreatePipe 禁令无涉；所有临时目录用
`tempfile.mkdtemp` 造在系统临时区，只读校验后 `rmtree`。
"""
from __future__ import annotations

import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__:
    from . import protect
else:                                  # 直接 `python md_cg/test_t98a_protect_override.py` 也能跑
    sys.path.insert(0, _REPO)
    from md_cg import protect

_PASS = []
_FAIL = []


# 生效条件：cond 为真记录 PASS 并返回 True，否则记录 FAIL 并返回 False；n 为断言名。
def ok(cond: bool, n: str) -> bool:
    if cond:
        _PASS.append(n)
    else:
        _FAIL.append(n)
    return bool(cond)


class _Idx(dict):
    """最小索引 stub。

    `protect._entry` 的实现是 `(getattr(cg, "index", None) or {}).get("nodes")`
    ——索引本身必须是 **dict 面**（有 `.get`），不是「有 nodes 属性的对象」。
    这里直接继承 dict，`{"nodes": {...}}` 即是真实形态。
    """

    def __init__(self, nodes):
        super().__init__(nodes=nodes)


class _StubCG(object):
    """最小合成 cg —— 形态对齐真实裸 MdCG（root / index.nodes / principal）。

    `principal` 缺省 None = 裸 MdCG 无身份模型；置为对象即模拟 `MdCGSecure`
    （此时 require_layer 应**逐位不变**地返回层名 str）。
    """

    def __init__(self, root, node_id, layer="self", sens="public",
                 principal=None, immutable=False, protected=False):
        self.root = root
        self.index = _Idx({node_id: {"layer": layer, "sensitivity": sens,
                                     "path": "%s.md" % node_id,
                                     "immutable": immutable,
                                     "protected": protected}})
        self.principal = principal
        self.actor = None
        self._dirty = {}

    # 下面两个是真实 MdCG 面里 protect 会探到的钩子（探测失败按无语料/不阻断处理）
    def get(self, node_id):                      # noqa: D401 —— stub
        return None

    def _write_node(self, *a, **kw):
        return None


# 生效条件：在 root 下建 .mdcg 之类的落账目录不必要；本函数只造 stub 并返回 (cg, node_id)。
def _mk(tmp, **kw):
    node_id = "n_t98a"
    cg = _StubCG(tmp, node_id, **kw)
    return cg, node_id


class _AuditSpy(object):
    """monkeypatch `protect._audit`，记录调用次数与动作名，并转发给原函数。

    用 try/finally 还原 —— 断言失败也不把全局 patch 漏给后面的用例。
    """

    def __init__(self):
        self.calls = []
        self._orig = None

    def __enter__(self):
        self._orig = protect._audit

        def _spy(cg, action, node_id, reason, actor=None, snapshot=None):
            self.calls.append({"action": action, "node_id": node_id,
                               "reason": reason, "snapshot": snapshot})
            try:
                return self._orig(cg, action, node_id, reason,
                                  actor=actor, snapshot=snapshot)
            except Exception:            # noqa: BLE001 —— 落账失败不该打断判定本身
                return None

        protect._audit = _spy
        return self

    def __exit__(self, *exc):
        protect._audit = self._orig
        return False


# 生效条件：无前置；protect 可导入且两个单点可调用时返回 True，否则记录 FAIL 并返回 False。
def _g0_target_present():
    """G0 前置：protect 在，且 `_allow` / `require_layer` 可调用。"""
    ok(hasattr(protect, "_allow"), "G0 protect._allow 存在")
    ok(callable(getattr(protect, "_allow", None)), "G0 _allow 可调用")
    ok(callable(getattr(protect, "require_layer", None)),
       "G0 require_layer 可调用")
    return callable(getattr(protect, "_allow", None))


# 生效条件：fail-open ① —— 无显式授权（override 假值 / 只有旗标无语料）时 _allow 返回的 override 为假，且 _audit 仍被调用一次。
def _g1_allow_denies_without_authorization(tmp):
    """A 无显式授权 → `override` 假，**且审计照写**。"""
    cg, nid = _mk(tmp)
    with _AuditSpy() as spy:
        r = protect._allow(cg, nid, "测试原因", "override_write",
                           False, None)
    ok(isinstance(r, dict), "A1 _allow 返回 dict（实得 %r）" % (type(r),))
    if not isinstance(r, dict):
        return
    ok(r.get("override") is False,
       "A1 无 override 旗标 → override 为假（实得 %r）" % (r.get("override"),))
    ok(len(spy.calls) == 1,
       "A1 拒绝路径 _audit 被调用 1 次（实得 %d）" % len(spy.calls))
    if spy.calls:
        ok(spy.calls[0]["action"] == "override_write",
           "A1 审计 action 传对（实得 %r）" % (spy.calls[0]["action"],))

    # 反例：**只有自报旗标、没有授权语料** —— 旗标 != 授权凭据
    cg2, nid2 = _mk(tmp)
    with _AuditSpy() as spy2:
        r2 = protect._allow(cg2, nid2, "测试原因", "override_write",
                            True, None)
    ok(isinstance(r2, dict) and r2.get("override") is False,
       "A2 只有 override=True 而无语料 → 仍为假（实得 %r）"
       % (r2.get("override") if isinstance(r2, dict) else r2,))
    ok(len(spy2.calls) >= 1,
       "A2 该拒绝路径 _audit 也被调用（实得 %d）" % len(spy2.calls))

    # 返回值键集与改前同形（调用方 guard_* 的返回面不变）
    if isinstance(r, dict):
        for k in ("override", "reason", "snapshot", "audit"):
            ok(k in r, "A3 返回 dict 含键 %r" % (k,))


# 生效条件：fail-open ② —— 裸 MdCG（principal=None）上 require_layer 给出二元组标记或抛错，绝不返回可当层名用的 str，且 layer_gate 审计照样落。
def _g2_require_layer_bare_not_pass(tmp):
    """B 裸 MdCG → 显式不可判定标记（或抛错），**不得**是层名 str。"""
    cg, nid = _mk(tmp, layer="self")
    with _AuditSpy() as spy:
        try:
            r = protect.require_layer(cg, nid)
        except Exception as exc:                  # noqa: BLE001 —— 抛错支也算「不静默放行」
            ok(isinstance(exc, protect.ProtectionError),
               "B1 裸 MdCG 抛的是 ProtectionError（实得 %r）" % (type(exc),))
            ok(len(spy.calls) >= 1,
               "B1 抛错支同样落了审计（实得 %d）" % len(spy.calls))
            return
    ok(not isinstance(r, str),
       "B2 裸 MdCG 的返回**不是**可当层名用的 str（实得 %r）" % (r,))
    ok(isinstance(r, tuple) and len(r) == 2,
       "B2 返回二元组显式不可判定标记（实得 %r）" % (r,))
    if isinstance(r, tuple) and len(r) == 2:
        ok(r[1] == "no_principal",
           "B3 标记位为 'no_principal'（实得 %r）" % (r[1],))
        ok(r[0] == "self",
           "B3 标记里仍带解析出的真层（实得 %r）" % (r[0],))
    ok(any(c["action"] == "layer_gate" for c in spy.calls),
       "B4 落了 action='layer_gate' 审计（实得 %r）"
       % ([c["action"] for c in spy.calls],))

    # 硬拒支：确知调用方必须持身份模型时，require_deny_bare=True 保守拒绝
    cg2, nid2 = _mk(tmp, layer="self")
    with _AuditSpy() as spy2:
        try:
            r2 = protect.require_layer(cg2, nid2, require_deny_bare=True)
            ok(False, "B5 require_deny_bare=True 应抛错（实得 %r）" % (r2,))
        except protect.ProtectionError:
            ok(True, "B5 require_deny_bare=True 保守拒绝（抛 ProtectionError）")
        except Exception as exc:                  # noqa: BLE001
            ok(False, "B5 抛的是 ProtectionError（实得 %r）" % (type(exc),))
    ok(any(c["action"] == "layer_gate" for c in spy2.calls),
       "B5 硬拒支同样落了 layer_gate 审计")

    # 对照：principal 在位时判定与返回**逐位不变**（仍返回层名 str）
    class _Principal(object):
        def __init__(self):
            self.seen = []

        def require_layer_write(self, layer, sens):
            self.seen.append((layer, sens))

    cg3, nid3 = _mk(tmp, layer="knowledge", sens="public")
    cg3.principal = _Principal()
    r3 = protect.require_layer(cg3, nid3)
    ok(isinstance(r3, str) and r3 == "knowledge",
       "B6 principal 在位 → 仍返回层名（实得 %r）" % (r3,))
    ok(cg3.principal.seen == [("knowledge", "public")],
       "B6 principal.require_layer_write 被以真层/敏感度调用（实得 %r）"
       % (cg3.principal.seen,))


# 生效条件：验收 ③ —— override=True 且 actor/why 带授权语料时 _allow 返回 override: True，正路未被堵死。
def _g3_explicit_override_still_granted(tmp):
    """C 合法显式 override → `override: True`（正路不得被堵死）。"""
    # C1 授权语料来自形参 actor（字符串字面量 = 显式的「谁」）
    cg, nid = _mk(tmp)
    with _AuditSpy() as spy:
        r = protect._allow(cg, nid, "管理员显式授权覆盖", "override_write",
                           True, "guard-probe")
    ok(isinstance(r, dict) and r.get("override") is True,
       "C1 actor 显式给授权语料 → override 真（实得 %r）"
       % (r.get("override") if isinstance(r, dict) else r,))
    ok(len(spy.calls) == 1, "C1 放行路径同样落一条审计（实得 %d）"
       % len(spy.calls))

    # C2 授权语料来自 cg.principal（真实 MdCGSecure 面）
    class _Principal(object):
        actor = "root"
        why = "管理员显式授权覆盖"

    cg2, nid2 = _mk(tmp)
    cg2.principal = _Principal()
    r2 = protect._allow(cg2, nid2, "reason", "override_write", True, None)
    ok(isinstance(r2, dict) and r2.get("override") is True,
       "C2 principal.actor/why 授权语料 → override 真（实得 %r）"
       % (r2.get("override") if isinstance(r2, dict) else r2,))

    # C3 端到端：guard_write 在受保护节点 + 显式授权下必须给出 override 真值
    #    （而不是只测 _allow 这个内部件）
    cg3, nid3 = _mk(tmp, immutable=True)
    r3 = protect.guard_write(cg3, nid3, override=True, actor="guard-probe")
    ok(isinstance(r3, dict) and r3.get("override") is True,
       "C3 guard_write 受保护节点 + 显式授权 → override 真（实得 %r）"
       % (r3.get("override") if isinstance(r3, dict) else r3,))

    # C4 端到端反例：同样受保护，但**无授权** → override 假（C3 不是恒真）
    cg4, nid4 = _mk(tmp, immutable=True)
    r4 = protect.guard_write(cg4, nid4, override=True, actor=None)
    ok(isinstance(r4, dict) and r4.get("override") is False,
       "C4 受保护节点 + 无授权 → override 假（实得 %r）"
       % (r4.get("override") if isinstance(r4, dict) else r4,))


def main() -> int:
    if not _g0_target_present():                          # 极早失败，信息清楚
        print("protect.py 缺被测单点，无法验收")
        return 1
    tmp = tempfile.mkdtemp(prefix="t98a_protect_")
    try:
        _g1_allow_denies_without_authorization(tmp)
        _g2_require_layer_bare_not_pass(tmp)
        _g3_explicit_override_still_granted(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    for n in _FAIL:
        print("  FAIL  %s" % n)
    print("\nt98a protect 覆写守卫 fail-open 回归：%d 通过，%d 失败"
          % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
