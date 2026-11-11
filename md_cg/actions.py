# -*- coding: utf-8 -*-
"""记忆动作面（T90 / E-T90a）：store / retrieve / summarize / discard 统一入口。

**定位**：这是灵枢的**对外能力面**上的一个薄适配层——把四个「模型可自行调用的
记忆动作」接到库层真实现上，让调用方不必知道每个动作该调哪个方法、每个参数的
真实名字。它**不重新实现任何语义**：四个函数全部是转发，返回值原样透传，
异常原样抛出（不包装、不吞、不打印）。

库层真实现（签名以 mdcos.py / mdcg.py 现状为准）：
  · store     → ``MdCGSecure.remember_event``（mdcos.py:7486；父类 mdcg.py:4575）
                 追加一条**近期事件**（原始、未结构化），返回 ``{"event", "dropped"}``。
  · retrieve  → ``MdCGOS.recall``（mdcos.py:3034）按 token 预算装包，返回
                 ``{pack, tokens_used, budget, skipped, recent, meta}``。
  · summarize → ``MdCGOS.consolidate_run``（mdcos.py:5485）离线固化面；
                 ``action="promote"`` 走 ``consolidate.promote_memories``
                 （contextual → knowledge，``apply=False`` 时是纯只读盘点）。
  · discard   → ``MdCGSecure.forget_gated``（mdcos.py:4652 → MdCGOS:3171）
                 软删的档位路径（MCP 工具面专用，先过保护/自治资格闸）。
"""

import argparse
import json
import os

# MdCGSecure 不在顶部导入：脚本直跑（__package__ 为空）时相对导入会失败，
# 改由文件末尾的 __main__ 入口在修好 sys.path 后按包身份导入。

# ---------- 动作面规格（desc/target/params/returns 四字段齐） ----------

ACTION_SPECS = {
    "store": {
        "desc": "把一段内容写入记忆图",
        "target": "remember_event",
        "params": ["content", "tags", "meta", "node_id"],
        "returns": "事件记录 dict（含 event 与 dropped 计数）",
    },
    "retrieve": {
        "desc": "按 query 取回相关记忆",
        "target": "recall",
        "params": ["query", "k", "budget_tokens"],
        "returns": "装包结果 dict（pack / tokens_used / budget / skipped / meta）",
    },
    "summarize": {
        "desc": "把 contextual 层记忆固化为 knowledge 层",
        "target": "consolidate_run",
        "params": ["limit", "apply", "actor"],
        "returns": "固化盘点结果 dict（apply=False 时不写层）",
    },
    "discard": {
        "desc": "按 node_id 遗忘一个记忆节点",
        "target": "forget_gated",
        "params": ["node_id", "reason", "override"],
        "returns": "遗忘结果 dict（ok / id / 后续去向）",
    },
}

ACTIONS = frozenset(ACTION_SPECS)


def action_spec(name):
    """取单个动作的规格；未知名 raise ValueError 并列出可用动作。"""
    try:
        return ACTION_SPECS[name]
    except KeyError:
        raise ValueError(
            "未知记忆动作：%r（可用：%s）" % (name, ", ".join(sorted(ACTIONS)))
        ) from None


# ---------- 四个动作：只做入参转发，不包装结果 ----------

def store(cg, content, *, tags=None, meta=None, node_id=None):
    """写入一段内容。

    node_id=None（缺省）→ 库层 ``remember_event``（近期事件窗口）。
    给了 node_id → ``remember_gated`` 的 gated=False 旁路分支
    （mdcos.py:817-4448：直接落到 ``add``，返回体带 ``node_id``；
    demo 的 discard 需要真实 node_id 时走这一路，语义仍是「写一个节点」，
    不是新造语义）。
    """
    if node_id is None:
        return cg.remember_event(role="user", text=content, tags=tags, meta=meta)
    return cg.remember_gated(node_id, content, layer="contextual", tags=tags,
                             gated=False, meta=meta)


def retrieve(cg, query, *, k=20, budget_tokens=None):
    """按 query 取回相关记忆 → 库层 ``recall``。"""
    if budget_tokens is None:
        return cg.recall(query, k=k)
    return cg.recall(query, budget_tokens=budget_tokens, k=k)


def summarize(cg, *, limit=None, apply=False, actor=None):
    """把 contextual 层记忆固化为 knowledge 层 → 库层 ``consolidate_run``。"""
    kw = {"limit": limit, "apply": apply}
    if actor is not None:
        kw["actor"] = actor
    return cg.consolidate_run("promote", **kw)


def discard(cg, node_id, *, reason="", override=False):
    """按 node_id 遗忘一个记忆节点 → 库层 ``forget_gated``。"""
    return cg.forget_gated(node_id, reason=reason, override=override)


DISPATCH = {
    "store": store,
    "retrieve": retrieve,
    "summarize": summarize,
    "discard": discard,
}


def dispatch(cg, action, **kwargs):
    """按动作名分派；未知名 raise ValueError 并列出可用动作。"""
    fn = DISPATCH.get(action)
    if fn is None:
        raise ValueError(
            "未知记忆动作：%r（可用：%s）" % (action, ", ".join(sorted(ACTIONS)))
        )
    return fn(cg, **kwargs)


# ---------- CLI 演示：四类动作各真实调用一次，落一行 JSON 记录 ----------

def _demo_principal():
    """demo 用 designer principal（照 md_cg/test_action_derive.py:51-54）。"""
    if __package__:
        from .security import DEFAULT_SENSITIVITY, Principal
    else:  # 脚本直跑：__main__ 已把包根塞进 sys.path，按包身份导入
        from md_cg.security import DEFAULT_SENSITIVITY, Principal
    return Principal(actor="t90a-demo", clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer",
                     session="t90a-demo", harness="actions-demo")


def _brief(value):
    """返回值短摘要：dict 取关键字段，其余按 str 前 200 字。"""
    if not isinstance(value, dict):
        return str(value)[:200]
    keys = ("ok", "id", "node_id", "dropped", "pack", "tokens_used", "budget",
            "skipped", "promoted", "candidates", "moved_to", "error")
    brief = {}
    for k in keys:
        if k not in value:
            continue
        v = value[k]
        if isinstance(v, (list, tuple)):
            brief[k] = "len=%d" % len(v)
        elif isinstance(v, dict):
            brief[k] = "{...%d keys}" % len(v)
        elif isinstance(v, str):
            brief[k] = v[:200]
        else:
            brief[k] = v
    return brief or {"keys": sorted(value)[:20]}


def _record(fh, op, ok, args, target, result=None, error=None, reason=None):
    """写一行调用记录（字段顺序固定）。"""
    row = {"op": op, "ok": ok}
    if error is None:
        row["target"] = target
        row["args"] = args
        row["result_summary"] = _brief(result)
    else:
        if reason is not None:
            row["reason"] = reason
        row["error"] = error
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    fh.flush()
    return 1


def demo(root, out_dir):
    """在 root 上真实调用四类动作各一次，每次调用写成一行 JSON。"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "calls.jsonl")
    # discard 的后端是 forget_gated，首行 _forget_admin() 要求 can_admin
    # （mdcos.py:5584/5592）——照 md_cg/test_action_derive.py:51-54 的既有样例
    # 构造 designer principal，否则 discard 只能记一行失败。
    principal = _demo_principal()
    cg = MdCGSecure(root, principal=principal)
    written = 0

    try:
        with open(path, "w", encoding="utf-8") as fh:
            # 1) store —— 自造 node_id 走 remember_gated 旁路，拿到真 node_id
            content = "E-T90a 记忆动作面验收：store 调用记录"
            tags = ["t90a", "demo"]
            node_id = "t90a-store-demo-1"
            store_result = None
            try:
                store_result = store(cg, content, tags=tags, node_id=node_id)
                written += _record(fh, "store", True,
                                   {"content": content, "tags": tags, "meta": None,
                                    "node_id": node_id},
                                   action_spec("store")["target"], store_result)
            except Exception as e:  # 一次失败不打断后续动作
                written += _record(fh, "store", False, None,
                                   action_spec("store")["target"],
                                   error="%s: %s" % (type(e).__name__, str(e)[:200]))

            # 2) retrieve
            try:
                r = retrieve(cg, "记忆动作面")
                written += _record(fh, "retrieve", True,
                                   {"query": "记忆动作面", "k": 20,
                                    "budget_tokens": None},
                                   action_spec("retrieve")["target"], r)
            except Exception as e:
                written += _record(fh, "retrieve", False, None,
                                   action_spec("retrieve")["target"],
                                   error="%s: %s" % (type(e).__name__, str(e)[:200]))

            # 3) summarize —— apply=False：只读盘点，不写层
            try:
                r = summarize(cg, apply=False)
                written += _record(fh, "summarize", True,
                                   {"limit": None, "apply": False, "actor": None},
                                   action_spec("summarize")["target"], r)
            except Exception as e:
                written += _record(fh, "summarize", False, None,
                                   action_spec("summarize")["target"],
                                   error="%s: %s" % (type(e).__name__, str(e)[:200]))

            # 4) discard —— node_id 取 store 真实返回，取不到才跳过
            node_id = None
            if isinstance(store_result, dict):
                node_id = store_result.get("node_id") or store_result.get("id")
            if not node_id:
                written += _record(
                    fh, "discard", False, None, action_spec("discard")["target"],
                    error="skipped: store 返回里没有 node_id（不伪造 node_id）",
                    reason="no-node-id")
            else:
                try:
                    r = discard(cg, node_id, reason="E-T90a demo")
                    written += _record(fh, "discard", True,
                                       {"node_id": node_id, "reason": "E-T90a demo",
                                        "override": False},
                                       action_spec("discard")["target"], r)
                except Exception as e:
                    written += _record(fh, "discard", False,
                                       {"node_id": node_id}, None,
                                       error="%s: %s" % (type(e).__name__,
                                                         str(e)[:200]))
    finally:
        flusher = getattr(cg, "flush", None)
        if callable(flusher):
            flusher()

    print("[actions] calls written: %d -> %s" % (written, path))
    return path


if __name__ == "__main__":
    # 脚本直跑（python actions.py）时 __package__ 为空，顶部的包内相对导入
    # 会报 attempted relative import；此处先判非包上下文，把包根（本目录的
    # 上一级）加入 sys.path，再以包身份导入 MdCGSecure。
    if not __package__:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from md_cg.mdcos import MdCGSecure
    else:
        from .mdcos import MdCGSecure
    ap = argparse.ArgumentParser(description="灵枢记忆动作面 demo（E-T90a）")
    ap.add_argument("--root", default=None, help="认知图库根目录（不带子命令时用）")
    ap.add_argument("--out", default=r"D:\wook\tmp\t90a-data",
                    help="demo 输出目录（默认 D:\\wook\\tmp\\t90a-data）")
    _sub = ap.add_subparsers(dest="cmd")
    _demo = _sub.add_parser("demo", help="四类动作各落一次真实调用记录")
    _demo.add_argument("--root", default=None, help="认知图库根目录")
    _demo.add_argument("--out", default=r"D:\wook\tmp\t90a-data",
                       help="demo 输出目录（默认 D:\\wook\\tmp\\t90a-data）")
    _ns, _extra = ap.parse_known_args()
    # 优先走 `demo` 子命令（blueprint gate_cmd 口径：actions.py demo --root …）；
    # 不带子命令时沿用既有顶层 --root/--out 接口。子命令缺 --root 时回落顶层值。
    _root = _ns.root or getattr(_ns, "root", None)
    if not _root:
        ap.error("--root 为必填（cognitive graph root）")
    demo(_root, _ns.out)