# -*- coding: utf-8 -*-
# 功能名：状态事件台账「双端触发点」端到端守卫
# 生效条件：python -X utf8 -m md_cg.test_state_ledger_e2e；被测面＝服务端
#   `recent`·add 分支（DSH 的 recentAdd 与 zcode 的 sync_to_window **都**经过它）
#   是否真的把真人轮推进状态台账。
# 子功能：① DSH 形状触发 ② zcode 形状触发 ③ 三类负例不抽 ④ 同值去重 ⑤ 证据字段。
# 执行：temp 隔离库（MDCG_ROOT 全改），走**真实分发入口** `_cg_dispatch`，
#   不直接调抽取器——否则测的是抽取器而不是接线。
# 验证方式：5/5 PASS exit 0。
# 不适用条件：不判抽取规则是否该收窄（见 scripts/test_state_extract.py 的 S4b）；
#   不判台账读写语义（见 test_state_events.py）；不覆盖 npm 实际发货内容。

"""为什么要它（2026-11-02）：

`test_state_ledger_chain.py` 只能静态证明「链在源码里是通的」。静态绿不等于
运行时真落盘——本仓有过「文件能 import ⇒ 以为判据成立」的假绿取证。
故这条守卫做**真调用**：用 `_cg_dispatch` 模拟两端各自的真实载荷形状，
读回 `state_events.read` 验落盘。

关键：**必须走分发入口，不能直接调 `extract_and_record`**。
直接调抽取器能过，但接线块被删掉照样能过——那就是假绿。

夹具坑（本机实测）：`MDCG_AUX_ROOT` 末段不能是 Windows 保留设备名
（首版用 `aux` 被 datapath 守卫拒；改用 `auxdata`）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

_P, _F = [], []


def ok(cond, msg, detail=""):
    (_P if cond else _F).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


def main():
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("MDCG_")}
    root = tempfile.mkdtemp(prefix="chain_e2e_")
    try:
        os.environ["MDCG_ROOT"] = root
        os.environ["MDCG_STATE_ROOT"] = os.path.join(root, "st")
        # 末段不得是保留设备名（aux/con/nul/prn/com1…）——datapath 守卫会拒。
        os.environ["MDCG_AUX_ROOT"] = os.path.join(root, "auxdata")
        from md_cg.mdcos import MdCGOS
        from md_cg import state_events as SE
        from md_cg.mcp_server import _cg_dispatch
        cg = MdCGOS(root)

        def add(**kw):
            return _cg_dispatch(cg, dict({"op": "recent", "action": "add"}, **kw))

        print("== ① DSH 端形状（src/hooks.ts 的 recentAdd：meta 带 session）")
        add(role="user", text="我搬到青岛了",
            meta={"session": "s-dsh", "turn": 1})
        evs = SE.read(cg)
        ok(len(evs) == 1 and evs[0].get("new") == "青岛",
           "① DSH 形状的窗口写入触发了状态记账", evs)

        print("== ② zcode 端形状（sync_to_window：同分支不同 session）")
        add(role="user", text="我最喜欢海边的日落",
            meta={"session": "s-zcode", "turn": 1})
        evs = SE.read(cg)
        ok(len(evs) == 2 and evs[-1].get("new") == "海边的日落",
           "② zcode 形状同样覆盖（证明单点覆盖双端）", evs)

        print("== ③ 负例（怎么让它红：去掉 role/session 两个前置条件）")
        n0 = len(SE.read(cg))
        add(role="assistant", text="我搬到火星了",
            meta={"session": "s-dsh", "turn": 2})          # 助手轮
        add(role="user", text="我搬到月球了", meta={})      # 无 session
        add(role="user", text="今天写了点代码",
            meta={"session": "s-dsh", "turn": 3})          # 无规则命中
        n1 = len(SE.read(cg))
        ok(n1 == n0, "③ 助手轮 / 无 session / 无命中：一律不抽", (n0, n1))

        print("== ④ 同值去重（怎么让它红：删掉 extract_and_record 里的 dedupe）")
        add(role="user", text="我已经搬到了青岛",
            meta={"session": "s-dsh", "turn": 4})
        n2 = len(SE.read(cg))
        ok(n2 == n1, "④ 同值不重复记账（防每轮重复写）", (n1, n2))

        print("== ⑤ 证据字段（可整体甄别/清理的前提）")
        last = SE.read(cg)[-1]
        ok(str(last.get("actor")) == "state_extract"
           and "[auto]" in str(last.get("evidence")),
           "⑤ actor=state_extract 且 evidence 带 [auto] session/turn", last)

        print("== ⑥ 隔离：抽取抛异常不得影响窗口写入")
        # 为什么必须有这条（变异 M4 实测漏网）：
        # 上面 ⑤ 条都建立在「抽取器不抛异常」这个隐含前提上。若把 fail-soft
        # 的 `except Exception` 收窄成某个具体异常，抽取器一旦真抛（规则表未来
        # 改动、盘面权限、编码问题），异常会越过 recent 分支冒到窗口写入调用方
        # ——**为了一个派生面赔掉运行态面**。这条断言专门钉住该边界。
        from md_cg import state_extract as _sx
        _orig = _sx.extract_and_record

        def _boom(*a, **k):
            raise RuntimeError("模拟抽取器内部故障")

        _sx.extract_and_record = _boom
        try:
            # 断言必须能红：拿"窗口写入真的成功了"作判据——查 _recent 里
            # 确实有这一轮，而不是只看"没抛异常"（后者过于宽松，恒真）。
            r = add(role="user", text="我搬到威海了",
                    meta={"session": "s-dsh", "turn": 9})
            wins = cg.recent_events(limit=0)
            got = [w for w in wins
                   if "威海" in str(w.get("text") or "")]
            ok(bool(got),
               "⑥a 抽取器抛异常时窗口写入仍成功（派生面故障不拖垮运行态面）",
               "recent 窗口里找不到该轮；返回=%r" % (r,))
            # 且该轮确实没落台账（故障态不漏记也不假记）
            ok(not any(e.get("new") == "威海" for e in SE.read(cg)),
               "⑥b 故障轮不产生半截台账记录")
        except Exception as exc:  # noqa: BLE001
            ok(False, "⑥a 抽取器抛异常时窗口写入仍成功（派生面故障不拖垮运行态面）",
               exc)
        finally:
            _sx.extract_and_record = _orig
    finally:
        for k in list(os.environ):
            if k.startswith("MDCG_"):
                os.environ.pop(k, None)
        os.environ.update(saved)
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("状态台账双端触发点端到端：%d 通过 / %d 失败" % (len(_P), len(_F)))
    for f in _F:
        print("  -", f)
    return 0 if not _F else 1


if __name__ == "__main__":
    raise SystemExit(main())
