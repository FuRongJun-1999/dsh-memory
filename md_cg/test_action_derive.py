# -*- coding: utf-8 -*-
"""test_action_derive · action 缺省静默降级防呆（与 op 推导同构）

背景：`op` 传了、`action` 漏了 → 各分支按字面量默认 action 执行。若默认恰是
读类（list / routes / stat / outlook / ping），写意图会被**静默吞掉**且返回
形似正常的结果。最典型是文档化契约 `cg(op=review, pid, decision, reason)`
（不带 action，见 docs/mdcg/主代理子代理记忆架构设计.md）实际静默走
review_list —— 裁决从未落盘，属契约与实现漂移。

修复（md_cg/mcp_server.py `_ACTION_SIGS` / `_action_sig` / `_cg_call`）：
  ① 签名明确指向非默认 action → 按签名推导并补进 args（不再被默认吞掉）；
  ② 无签名可依 → 维持默认执行，但透出 action_derived + hint_action（不再静默）；
  ③ 判据用「键存在且非 None」——False / 0 / "" 属显式传入，避免真值判断误吞；
  ④ `_ACTION_DEFAULT` 是「分支缺省 action 字面量」的唯一登记表，本测试含
     **同源守卫**（表 ↔ 源码双向比对），防表与实现漂移。

边界：action 仍是可选参数；推导只在「缺 action 且签名明确」时生效，显式传
action 的行为逐位不变；`ingest` 的 path→类型推导取**保守优先**（file 最保守：
若实为目录会报错可见，而不会误把整棵目录树摄进来）。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK：带圈数字等非 GBK 字符打印即 UnicodeEncodeError，且崩在
# 断言之后、报告之前 —— 同一测试「因环境而异」。自带 UTF-8 兜底。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mcp_server as M
from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[PASS] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _p(actor="tester", session="sess_a"):
    return Principal(actor=actor, clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer",
                     session=session, harness="test-harness")


def _raises(fn):
    try:
        fn()
        return None
    except Exception as e:                                   # noqa: BLE001
        return e


# ==================== A. 纯函数：签名推导 ====================
SIG = M._action_sig

check("A1 review+decision→decide（契约漂移核心）",
      SIG({"decision": "accept"}, "review") == ("decide", "decision"))
check("A2 review+node_id→verify_record",
      SIG({"node_id": "n1"}, "review") == ("verify_record", "node_id"))
check("A3 review 仅 pid 不猜（保持 list，避免误判 rounds/records）",
      SIG({"pid": "p1"}, "review") == (None, None))
check("A4 recent+text→add", SIG({"text": "hi"}, "recent") == ("add", "text"))
check("A4b recent+content→add",
      SIG({"content": "hi"}, "recent") == ("add", "content"))
check("A5 goal+goal→add", SIG({"goal": "G"}, "goal") == ("add", "goal"))
check("A6 predict+hit=False 仍推导（键存在即签名，非真值判断）",
      SIG({"hit": False}, "predict") == ("feedback", "hit"))
check("A7 predict 空参数→不猜", SIG({}, "predict") == (None, None))
check("A8 session+summary→note",
      SIG({"summary": "s"}, "session") == ("note", "summary"))
check("A9 insight+statement→record",
      SIG({"statement": "x"}, "insight") == ("record", "statement"))
check("A10 whitebox+question→ask",
      SIG({"question": "q"}, "whitebox") == ("ask", "question"))
check("A10b whitebox+questions→verify_existing",
      SIG({"questions": ["q"]}, "whitebox") == ("verify_existing", "questions"))
check("A11 ingest+*.jsonl→jsonl",
      SIG({"path": "a/b.jsonl"}, "ingest") == ("jsonl", "path(*.jsonl)"))
check("A12 ingest+patterns→dir",
      SIG({"path": "d", "patterns": ["*.md"]}, "ingest") == ("dir", "patterns"))
check("A13 ingest 裸 path→file（保守优先，不猜 dir）",
      SIG({"path": "d"}, "ingest") == ("file", "path"))
check("A14 ingest 空 path→不猜", SIG({"path": "   "}, "ingest") == (None, None))
check("A15 非推导 op 不猜", SIG({"decision": "accept"}, "link") == (None, None))
check("A16 显式 None 不算签名",
      SIG({"decision": None, "node_id": "n1"}, "review") == ("verify_record", "node_id"))


# ==================== B. 同源守卫：表 ↔ 源码双向 ====================
_MCP_SRC = open(M.__file__, encoding="utf-8", errors="replace").read()
_WB_SRC = open(os.path.join(os.path.dirname(M.__file__), "whitebox.py"),
               encoding="utf-8", errors="replace").read()
# 源码中所有 `a.get("action") or "<默认>"` 形式的缺省字面量
_pairs = set(re.findall(r'a\.get\("action"\)\s*or\s*"([a-z_]+)"', _MCP_SRC))
# ccg 的嵌套形态：`o.get("action") or a.get("action") or "<默认>"`
_oc = set(re.findall(r'o\.get\("action"\)\s*or\s+a\.get\("action"\)\s*or\s*"([a-z_]+)"',
                     _MCP_SRC))
_wb_pairs = set(re.findall(r'a\.get\("action"\)\s*or\s*"([a-z_]+)"', _WB_SRC))
_src_vals = _pairs | _oc | _wb_pairs
_table_vals = set(M._ACTION_DEFAULT.values())
check("B1 源码每个缺省 action 都在 _ACTION_DEFAULT 值域内（防漏列）",
      _src_vals <= _table_vals, sorted(_src_vals - _table_vals))
check("B2 _ACTION_DEFAULT 每项都在源码中真实出现（防幻影表）",
      _table_vals <= _src_vals, sorted(_table_vals - _src_vals))
check("B3 whitebox dispatch 的缺省 action=ping 真实存在（跨文件守卫）",
      'ping' in re.findall(r'a\.get\("action"\)\s*or\s*"([a-z_]+)"', _WB_SRC), _wb_pairs)
# 推导规则的目标 action 必须真实存在于对应分支识别面（抽样防幻影推导）
for _op, _acts in M._ACTION_SIGS.items():
    _missing = [act for _, act in _acts
                if ('"%s"' % act) not in _MCP_SRC and ('"%s"' % act) not in _WB_SRC]
    check("B4 推导目标 action 在分支中被识别：%s" % _op, not _missing, _missing)


# ==================== C. 端到端：不再静默吞意图 ====================
root = tempfile.mkdtemp(prefix="mdcg_act_")
try:
    cg = MdCGSecure(root, principal=_p())

    # C1 review 契约漂移：带 decision 但不带 action（文档化契约形态）
    out = M._cg_call(cg, {"op": "review", "pid": "no_such_pid",
                          "decision": "accept", "reason": "防呆测试"})
    check("C1 review+decision 不再静默走 list（旧行为返回 pending）",
          "pending" not in out, out)
    check("C1b 确实进了 decide 分支（pid_not_found 属预期）",
          out.get("error") == "pid_not_found", out)
    check("C1c 透出 action_derived + hint_action",
          out.get("action_derived") is True and bool(out.get("hint_action")), out)

    # C2 全链路：真实提案 → 不传 action 裁决 accept → 必须真实落盘
    pid = cg.propose("act_probe_1", "防呆测试候选内容（裁决真实落盘）",
                     layer="knowledge")
    out2 = M._cg_call(cg, {"op": "review", "pid": pid, "decision": "accept",
                           "reason": "防呆测试：不带 action 的契约形态"})
    check("C2 不带 action 的裁决真实落盘", out2.get("ok") is True, out2)
    check("C2b 裁决后队列清空", len(cg.review_list()) == 0, cg.review_list())
    got = cg.get("act_probe_1")
    check("C2c 候选节点已按裁决写入", bool(got) and
          "防呆测试候选内容" in (got.get("content") or ""), got)

    # C3 recent + text 不再静默走 list（事件必须落盘）
    out3 = M._cg_call(cg, {"op": "recent", "text": "防呆事件A"})
    check("C3 recent+text 推导 add（旧行为返回 events 列表）",
          "events" not in out3 and "event" in out3, out3)
    _evs = cg.recent_events(limit=5)
    check("C3b 事件确实写入近况窗口",
          any("防呆事件A" in (e.get("text") or "") for e in _evs), _evs)
    check("C3c 透出 action_derived", out3.get("action_derived") is True, out3)

    # C4 goal + goal 不再静默走 list
    out4 = M._cg_call(cg, {"op": "goal", "goal": "防呆目标G"})
    check("C4 goal+goal 推导 add（旧行为返回 goals 列表）",
          out4.get("ok") is True and bool(out4.get("id")), out4)
    check("C4b 目标确实落盘",
          any("防呆目标G" in (g.get("goal") or "") for g in cg.active_goals(limit=10)),
          cg.active_goals(limit=10))

    # C5 显式 action 零回归（推导不得覆盖显式意图）
    out5 = M._cg_call(cg, {"op": "review", "action": "list"})
    check("C5 显式 action=list 行为逐位不变",
          "pending" in out5 and "action_derived" not in out5, out5)

    # C6 无签名缺省：维持默认但可见（不再静默）
    out6 = M._cg_call(cg, {"op": "review"})
    check("C6 无签名缺省走默认 list 且透出",
          "pending" in out6 and out6.get("action_derived") is True
          and out6.get("action") == "list", out6)
    check("C6b hint_action 点名默认 action 便于纠偏",
          "list" in (out6.get("hint_action") or ""), out6)

    # C7 未知 op 仍 fail-closed（不静默）
    check("C7 未知 op fail-closed 抛错",
          _raises(lambda: M._cg_call(cg, {"op": "not_an_op", "query": "x"})) is not None)

    # C8 stg 缺 op fail-closed 且提示可操作
    _e8 = _raises(lambda: M._stg_call(None, {"op": ""}))
    check("C8 stg 缺 op fail-closed 且提示必填",
          _e8 is not None and "必填" in str(_e8), _e8)

    # C9 op 缺省推导仍工作（本轮不回归）
    out9 = M._cg_call(cg, {"content": "op 推导回归探针", "layer": "knowledge"})
    check("C9 op 缺省推导仍透出 op_derived",
          out9.get("op_derived") is True and out9.get("op") == "write", out9)
finally:
    import shutil
    shutil.rmtree(root, ignore_errors=True)

print("=" * 60)
print("action_derive：%d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "; ".join(_fail))
sys.exit(1 if _fail else 0)
