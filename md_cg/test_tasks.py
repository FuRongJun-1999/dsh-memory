# -*- coding: utf-8 -*-
"""结构层任务实体（md_cg/tasks.py）验收矩阵（2026-09-16）。

蓝图＝消除 AI 失忆四症状，断言按症状逐条对位：

  ① 忘记已实现的工程 → H 组：session_tasks / session_recall 任务段，
     且**不按 session 过滤**（工程台账跨会话可见，这正是失忆的解）
  ② 计划与实际不符 → F 组：计划每轮覆盖更新 + 「计划变更」节逐轮累积
  ③ 缺核验       → E 组：done 时结果必填闸（缺一不收），拒收后**盘上内容逐字节不变**
  ④ 换表述即新任务 → A/C/I 组：身份＝语义 slug（非内容哈希）；同 slug 幂等更新
     不新增节点；同族只提示、不自动合并

另含 MCP 面对位（L 组：action 推导不吞写意图 / schema 参数声明 / 缺省 list 冒烟 /
未知 action fail-closed）与边界（J 组：串号防护、检索面、反向关联；M 组：权限闸）。
脚本式 assert + 退出码，风格与 test_branches.py / test_action_derive.py 一致。
"""

import os
import re
import sys
import shutil
import inspect
import tempfile
import hashlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from md_cg import mcp_server as M
from md_cg import tasks as T
from md_cg import tokens as TK
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal, AccessDenied

# 语料命名（互不串扰，各症状用独立任务名）
NAME = "记忆失忆修复-工程"
NAME2 = "任务实体-done闸探针"
NAME3 = "mcp面-任务探针"
NAME4 = "任务-未开先done"
NAME5 = "越权任务"

_fails = []
_n = [0]


def check(name, cond, detail=None):
    _n[0] += 1
    if cond:
        print("  ok  %s" % name)
    else:
        print("FAIL  %s  %r" % (name, detail))
        _fails.append(name)


def _raises(fn):
    try:
        fn()
    except Exception as e:          # noqa: BLE001 —— 测试需拿到任何异常作证据
        return e
    return None


def _mk_cg(root, **kw):
    p = Principal(actor="task_test", role="designer", can_write=True, can_admin=True,
                  ops_allow=["*"], layers_allow=["*"], **kw)
    return MdCGSecure(root, principal=p)


def _task_nodes(cg):
    return sorted(n for n in cg.index["nodes"] if n.startswith(T.TASK_PREFIX))


def _hits(cg, q, **kw):
    res, _meta = cg.search(q, **kw)
    return [h[0].get("id") for h in res]


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_tasks_")
    try:
        _root = os.path.join(tmp, "root")
        cg = _mk_cg(_root)
        nid = T.task_node_id(NAME)

        # ---------------- A. 身份判据＝语义 slug（症状④ 的根） ----------------
        print("\n[A] 身份判据：语义 slug，非内容哈希")
        check("A1 中文名原样保留（语义身份可读）",
              T.slugify(NAME) == NAME, T.slugify(NAME))
        check("A2 路径分隔符折叠（防目录穿越）",
              T.slugify("a/b\\c") == "a-b-c", T.slugify("a/b\\c"))
        _trav = T.slugify("../../etc/passwd")
        check("A3 `..` 与 `/` 全部折叠，不留穿越形态",
              ".." not in _trav and "/" not in _trav and "\\" not in _trav, _trav)
        check("A4 空白/纯符号名拒收（无身份不建卡）",
              T.task_node_id("   ") is None or T.slugify("   ") == "", T.slugify("   "))
        check("A4b 纯符号名 slug 为空", T.slugify("!!!") == "", T.slugify("!!!"))
        check("A5 已带前缀不重复叠（task_x → task_x）",
              T.task_node_id("task_x") == "task_x" == T.task_node_id("x"),
              (T.task_node_id("task_x"), T.task_node_id("x")))
        check("A6 超长名截断（≥64 上限护栏）",
              len(T.task_node_id("a" * 200)) <= len(T.TASK_PREFIX) + 64,
              len(T.task_node_id("a" * 200)))
        _o = T.upsert(cg, "任务 名（一）", plan="探针")
        check("A7 归一化透明（原名与 slug 同返，不静默改名）",
              _o.get("ok") and _o.get("slug_normalized") == "任务-名-一"
              and _o.get("node_id") == "task_任务-名-一", _o)

        # ---------------- B. 创建与读回（结构层定位） ----------------
        print("\n[B] 创建与读回：structural 层一等节点")
        r = T.upsert(cg, NAME, goal="消除 AI 四症状失忆",
                     plan="1) 建 tasks.py 2) 接 MCP 3) 会话段 4) 测试",
                     acceptance="四症状逐条有对位断言", boundary="不动 LAYERS",
                     condition="有跨会话任务台账需求")
        check("B1 首次登记建卡成功", r.get("ok") is True and r.get("created") is True, r)
        g = T.get_task(cg, nid)
        _idx = cg.index["nodes"].get(nid) or {}          # 层/权重以索引真源为准
        check("B2 读回六要素齐备（CCG 骨架）",
              g.get("goal") and g.get("plan") and g.get("acceptance")
              and g.get("boundary") and g.get("condition"), g)
        check("B3 落盘层＝structural（使用者指定位置，不新增层）",
              _idx.get("layer") == "structural", _idx.get("layer"))
        check("B4 标签含 task 与 task:<slug>（可反向关联）",
              T.TASK_TAG in g.get("tags", []) and ("task:" + NAME) in g.get("tags", []),
              g.get("tags"))
        check("B5 重要性 0.8（进入写保护域，不可被随意覆写）",
              abs(float(_idx.get("importance") or 0) - T.DEFAULT_IMPORTANCE) < 1e-9,
              _idx.get("importance"))
        check("B6 状态缺省 active", g.get("status") == "active", g.get("status"))

        # ---------------- C. 幂等：同 slug 即同任务（症状④ 的机制解） ----------------
        print("\n[C] 幂等：同 slug 走同一节点更新，不新建卡")
        _before = len(_task_nodes(cg))
        r2 = T.upsert(cg, NAME, plan="1) 建 tasks.py 2) 接 MCP 3) 会话段 4) 测试（已更新）")
        check("C1 重复登记不新建卡（created=False）",
              r2.get("ok") is True and r2.get("created") is False, r2)
        check("C2 节点数不变（换表述不产生新任务）",
              len(_task_nodes(cg)) == _before, _task_nodes(cg))
        g2 = T.get_task(cg, nid)
        check("C3 未提供字段沿用旧值（goal 未被清空）",
              g2.get("goal") == "消除 AI 四症状失忆", g2.get("goal"))
        check("C4 已提供字段被覆盖（plan 更新生效）",
              "（已更新）" in (g2.get("plan") or ""), g2.get("plan"))
        check("C5 与 goals 不双写（任务走自有状态机，不依赖 goal_ 节点）",
              not [n for n in cg.index["nodes"] if n.startswith("goal_")],
              [n for n in cg.index["nodes"] if n.startswith("goal_")])

        # ---------------- D. 结果不可被静默清空 ----------------
        print("\n[D] 结果维护：不可静默清空")
        T.upsert(cg, NAME, result="首版结果：tasks.py 骨架落地")
        check("D1 结果可写入",
              "首版结果" in (T.get_task(cg, nid).get("result") or ""),
              T.get_task(cg, nid).get("result"))
        T.upsert(cg, NAME, note="仅改进度，不碰结果")
        check("D2 本次不带 result → 旧结果保留（非清空）",
              "首版结果" in (T.get_task(cg, nid).get("result") or ""),
              T.get_task(cg, nid).get("result"))
        T.upsert(cg, NAME, result="")
        check("D3 空串视为未提供 → 仍保留旧结果",
              "首版结果" in (T.get_task(cg, nid).get("result") or ""),
              T.get_task(cg, nid).get("result"))

        # ---------------- E. done 结果必填闸（症状③ 缺核验） ----------------
        print("\n[E] 完成闸：done 无结果拒收，缺一不收")
        e1 = T.upsert(cg, NAME4, status="done")
        check("E1 新任务直接 done 且无结果 → 拒收",
              bool(e1) and e1.get("ok") is False and "结果" in (e1.get("error") or ""), e1)
        check("E1b 拒收不留半成品节点（盘上无残留）",
              T.task_node_id(NAME4) not in cg.index["nodes"])
        T.upsert(cg, NAME2, goal="验证完成闸", plan="1) 造 active 卡 2) 裸转 done")
        n2 = T.task_node_id(NAME2)
        _c_before = (cg.get(n2) or {}).get("content") or ""
        e2 = T.set_status(cg, n2, "done")
        check("E2 已有任务裸转 done（无结果）→ 拒收",
              bool(e2) and e2.get("ok") is False, e2)
        _c_after = (cg.get(n2) or {}).get("content") or ""
        check("E2b 拒收后盘上内容逐字节不变（拒绝不是软提示）",
              hashlib.md5(_c_before.encode("utf-8")).hexdigest()
              == hashlib.md5(_c_after.encode("utf-8")).hexdigest())
        check("E2c 状态未被偷偷推进（仍 active）",
              T.get_task(cg, n2).get("status") == "active",
              T.get_task(cg, n2).get("status"))
        e3 = T.set_status(cg, n2, "done", result="已交付：完成闸 41 断言全绿")
        check("E3 带结果转 done → 通过",
              bool(e3) and e3.get("ok") is True, e3)
        check("E3b 状态落盘 done 且结果可检索",
              T.get_task(cg, n2).get("status") == "done"
              and "已交付" in (T.get_task(cg, n2).get("result") or ""),
              T.get_task(cg, n2).get("status"))

        # ---------------- F. 计划覆盖 + 计划变更累积（症状②） ----------------
        print("\n[F] 计划与变更：计划覆盖、变更累积")
        T.upsert(cg, NAME, plan="1) 建模块 2) 接 MCP 3) 会话段 4) 测试 5) 归档")
        check("F1 计划每轮覆盖更新（当前态唯一）",
              "5) 归档" in (T.get_task(cg, nid).get("plan") or ""),
              T.get_task(cg, nid).get("plan"))
        f2 = T.plan_add(cg, nid, "发现 add 是全量重建 fm，需先读旧 fm 再合并")
        check("F2 计划变更可追加（变更记入独立节）",
              bool(f2) and f2.get("ok") is True, f2)
        T.plan_add(cg, nid, "MCP 面 action 推导顺序调整：写意图优先于读意图")
        ch = T.get_task(cg, nid).get("changes") or ""
        check("F3 变更逐轮累积（两轮 = 两行，差异可追溯）",
              ch.count("- [") == 2, ch)
        check("F4 变更不覆盖计划（两节独立）",
              "5) 归档" in (T.get_task(cg, nid).get("plan") or ""), ch)
        _empty = T.plan_add(cg, nid, "   ")
        check("F5 空变更拒收（不写空行噪声）",
              bool(_empty) and _empty.get("ok") is False, _empty)

        # ---------------- G. 状态机 ----------------
        print("\n[G] 状态机：四态可切换，未知态拒收")
        T.upsert(cg, NAME3, goal="MCP 面探针", plan="1) 推导 2) 冒烟")
        n3 = T.task_node_id(NAME3)
        check("G1 blocked 可切换",
              T.set_status(cg, n3, "blocked").get("ok") is True
              and T.get_task(cg, n3).get("status") == "blocked")
        T.set_status(cg, n3, "active")
        _bad = T.set_status(cg, n3, "moving")
        check("G2 未知状态拒收（状态机封闭）",
              bool(_bad) and _bad.get("ok") is False, _bad)

        # ---------------- H. 会话装配（症状① 的机制解） ----------------
        print("\n[H] 会话召回：带出进行中与近期完成，跨会话可见")
        st = T.session_tasks(cg)
        check("H1 进行中任务被带出（忘记已实现的解）",
              any(t["name"] == NAME for t in st["active"]), [t["name"] for t in st["active"]])
        check("H2 近期完成单列且带结果摘要",
              any(t["name"] == NAME2 and t.get("result") for t in st["done"]),
              st["done"])
        _other = MdCGSecure(_root, principal=Principal(
            actor="task_test_other", role="designer", can_write=True, can_admin=True,
            ops_allow=["*"], layers_allow=["*"], session="sess_other"))
        check("H3 换会话（新 Principal 同 root）仍带出任务（工程台账跨会话）",
              any(t["name"] == NAME
                  for t in _other.session_recall()["tasks"]["active"]))
        check("H3b session_tasks 无 session 形参（设计：台账不按会话切分）",
              "session" not in inspect.signature(T.session_tasks).parameters,
              list(inspect.signature(T.session_tasks).parameters))
        pack = cg.session_recall()
        check("H4 session_recall 含 tasks 段（上下文装配面已接）",
              "tasks" in pack and any(t["name"] == NAME for t in pack["tasks"]["active"]),
              list(pack.get("tasks", {}).get("active", []))[:2])
        check("H5 预算裁剪上报字段在位（任务段最后让位）",
              "tasks_truncated" in pack, sorted(pack.keys()))
        check("H6 done 任务不进进行中段（不冒充未完成）",
              all(t["name"] != NAME2 for t in st["active"]),
              [t["name"] for t in st["active"]])

        # ---------------- I. 同族提示（只提示，不合并） ----------------
        print("\n[I] 同族提示：由人裁决，不自动合并")
        s_exact = T.find_similar(cg, NAME)
        check("I1 完全同名可判别（exists=True，防重复开工）",
              s_exact.get("exists") is True, s_exact)
        _cnt_before = len(_task_nodes(cg))
        s_near = T.find_similar(cg, NAME + "-续")
        check("I2 近名给出疑似同族（提示面可用）",
              isinstance(s_near.get("similar"), list), s_near)
        check("I3 提示不改盘（同族绝不自动合并）",
              len(_task_nodes(cg)) == _cnt_before, _task_nodes(cg))
        s_new = T.find_similar(cg, "完全无关的新任务-xyz")
        check("I4 全新名不误报同族（exists=False）",
              s_new.get("exists") is False, s_new)

        # ---------------- J. 边界：串号 / 检索 / 反向关联 ----------------
        print("\n[J] 边界：串号防护、检索面、知识反向关联")
        cg.add("trait_probe", "非任务的结构层节点（探针）", layer="structural",
               verification_basis="other", consistency=False, tags=["trait"])
        check("J1 非任务 structural 节点不混入清单（层内串号防护）",
              all(t["id"] != "trait_probe" for t in T.list_tasks(cg)["tasks"]),
              [t["id"] for t in T.list_tasks(cg)["tasks"]])
        _ids = _hits(cg, NAME, layer="structural")
        check("J2 任务节点在 structural 层可被检索（按需调用面）",
              nid in _ids, _ids)
        cg.add("kp_task_rel", "任务相关知识：四症状的机制解与验收判据",
               layer="knowledge", verification_basis="test", consistency=False,
               tags=["task:" + NAME])
        _kp = cg.get("kp_task_rel")
        check("J3 任务知识挂 knowledge 层并以 tags 反向关联",
              _kp.get("frontmatter", {}).get("layer") == "knowledge"
              and ("task:" + NAME) in (_kp.get("frontmatter", {}).get("tags") or []),
              _kp.get("frontmatter", {}).get("tags"))
        check("J4 任务清单按 layer 过滤（知识节点不入台账）",
              all(t["id"] != "kp_task_rel" for t in T.list_tasks(cg)["tasks"]))

        # ---------------- K. 留痕：复用既有审计面 ----------------
        print("\n[K] 生命周期留痕：复用 _audit，不新造日志格式")
        _seen = []
        _orig = cg._audit

        def _spy(op, nid_, **kw):
            _seen.append(op)
            return _orig(op, nid_, **kw)

        cg._audit = _spy
        try:
            T.upsert(cg, "审计探针-任务", plan="x")
            T.plan_add(cg, T.task_node_id("审计探针-任务"), "变更一行")
        finally:
            cg._audit = _orig
        check("K1 建卡留痕 task_open", "task_open" in _seen, _seen)
        check("K2 更新留痕 task_update", "task_update" in _seen, _seen)

        # ---------------- L. MCP 面对位 ----------------
        print("\n[L] MCP 面：action 推导不吞写意图 / schema 可传 / 缺省 list")
        SIG = M._action_sig
        check("L1 task+name → open", SIG({"name": "X"}, "task") == ("open", "name"),
              SIG({"name": "X"}, "task"))
        check("L2 task+change → plan_add",
              SIG({"change": "c"}, "task") == ("plan_add", "change"),
              SIG({"change": "c"}, "task"))
        check("L3 task+name+change → open（open 兼容 change，写意图不丢）",
              SIG({"name": "X", "change": "c"}, "task") == ("open", "name"),
              SIG({"name": "X", "change": "c"}, "task"))
        check("L4 task+node_id → get",
              SIG({"node_id": "task_x"}, "task") == ("get", "node_id"),
              SIG({"node_id": "task_x"}, "task"))
        check("L5 task+node_id+change → plan_add（写优先于读，不静默当只读）",
              SIG({"node_id": "task_x", "change": "c"}, "task") == ("plan_add", "change"),
              SIG({"node_id": "task_x", "change": "c"}, "task"))
        check("L6 task+task_status → status",
              SIG({"task_status": "done"}, "task") == ("status", "task_status"),
              SIG({"task_status": "done"}, "task"))
        check("L7 task 无签名不猜（交 _ACTION_DEFAULT 承接）",
              SIG({}, "task") == (None, None), SIG({}, "task"))
        check("L8 _ACTION_DEFAULT['task'] == 'list'",
              M._ACTION_DEFAULT.get("task") == "list", M._ACTION_DEFAULT.get("task"))
        _src = open(os.path.join(_HERE, "mcp_server.py"), encoding="utf-8").read()
        _vals = set(re.findall(r'a\.get\("action"\)\s*or\s*"([a-z_]+)"', _src))
        check("L9 缺省字面量在源码真实存在（防幻影表）", "list" in _vals, sorted(_vals))

        out = M._cg_call(cg, {"op": "task", "name": NAME3, "plan": "1) 推导 2) 冒烟"})
        check("L10 op=task 缺 action → 推导 open 且透出（不静默）",
              out.get("ok") is True and out.get("action_derived") is True
              and out.get("action") == "open", out)

        def _chg():
            _g = M._cg_call(cg, {"op": "task", "action": "get", "node_id": n3})
            return _g.get("changes") or ""

        _c_before = _chg()
        out2 = M._cg_call(cg, {"op": "task", "node_id": n3, "change": "MCP 面追加一行"})
        check("L11 node_id+change 真实落盘（写意图未被吞）",
              out2.get("ok") is True and _chg().count("- [") == _c_before.count("- [") + 1,
              out2)

        out3 = M._cg_call(cg, {"op": "task"})
        check("L12 无签名 → 缺省 list 且透出 action_derived",
              out3.get("action_derived") is True and out3.get("action") == "list"
              and bool(out3.get("tasks")) is True, out3)
        out4 = M._cg_call(cg, {"op": "task", "action": "nope", "name": NAME})
        check("L13 未知 action fail-closed（返回 error，不静默降级）",
              out4.get("ok") is False and bool(out4.get("error")), out4)
        out5 = M._cg_call(cg, {"op": "task", "action": "session"})
        check("L14 action=session 会话装配面可经 MCP 取用",
              out5.get("ok") is True and bool(out5.get("active")), out5)
        out6 = M._cg_call(cg, {"op": "task", "action": "find", "name": NAME})
        check("L15 action=find 同族提示可经 MCP 取用",
              out6.get("ok") is True, out6)

        _tool = [t for t in M.KERNEL_TOOLS if t.get("name") == "cg"][0]
        _props = _tool["inputSchema"]["properties"]
        check("L16 op 枚举含 task（客户端可见面同步）",
              "task" in [x.strip() for x in _props["op"]["description"].split("|")])
        _miss = [k for k in ("plan", "result", "task_status", "acceptance", "boundary",
                             "active_limit", "done_limit") if k not in _props]
        check("L17 cg schema 已声明 task 参数（客户端传得进来）", not _miss, _miss)
        check("L18 tokens.ALL_OPS 含 task（跨面真源同步）",
              "task" in TK.ALL_OPS, [o for o in TK.ALL_OPS if o == "task"])

        # ---------------- M. 权限闸 ----------------
        print("\n[M] 权限闸：写权限不够则拒，角色白名单同步")
        _guest = MdCGSecure(os.path.join(tmp, "guest_root"),
                            principal=Principal(actor="guest1", role="guest",
                                                can_write=False, can_admin=False))
        _ge = _raises(lambda: T.upsert(_guest, NAME5, plan="x"))
        check("M1 无写权限角色写任务被拒（权限闸不可绕）",
              isinstance(_ge, AccessDenied), _ge)
        _rec = TK.ROLE_SPECS["record"]
        check("M2 record 角色 ops 白名单含 task 且可写 structural 层",
              "task" in _rec["ops_allow"] and "structural" in _rec["layers_allow"],
              (_rec["ops_allow"], _rec["layers_allow"]))
        _owner = Principal(actor="owner", role="designer", can_write=True,
                           can_admin=True, ops_allow=["*"], layers_allow=["*"])
        _narrow = TK.narrowed_principal(_owner, "record")
        check("M3 收窄身份（记录单元）可执行 task（本职：保存过程与结果）",
              _narrow.allows_op("task") is True, _narrow.ops_allow)
        _rcg = MdCGSecure(os.path.join(tmp, "record_root"), principal=_narrow)
        _ro = T.upsert(_rcg, "记录单元-任务探针", plan="x")
        check("M4 收窄身份真实落盘成功（端到端）", _ro.get("ok") is True, _ro)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s  %d 项断言，%d 失败" % ("ALL GREEN" if not _fails else "FAILED",
                                       _n[0], len(_fails)))
    if _fails:
        for f in _fails:
            print("  - %s" % f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
