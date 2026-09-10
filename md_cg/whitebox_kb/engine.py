# -*- coding: utf-8 -*-
"""whitebox_kb.engine — 白箱引擎的**进程内门面**。

替代旧的「子进程 `python -m aeis.mcp.server`」调用路径：白箱知识库已随主仓
自带，故直接进程内调用，不再需要外部 MCP 服务，也不再需要理论仓。

对外两级接口
------------
· 业务级：`WhiteboxEngine.chat / remember / service_info`
· 工具级：`WhiteboxEngine.call_tool(name, args)`（返回形状对齐 MCP `tools/call`
  的 `{isError, text, data}`，供 `md_cg.whitebox.WhiteboxClient` 直接复用）

路由语义（重要）
----------------
`_decide_route` 逐字迁自 `aeis/layered.py:185-247`——它是**纯逻辑、零 LLM 依赖**，
决定「白箱能否自答」。刻意**不带入** LLM 续答层（`layered.route_reply` /
`llm_complete`）：那需要外部大模型密钥，不属于白箱知识库。
因此当判定为 `llm`（白箱把握不足，本该交给 LLM）时，本门面降级为
`self_fallback` —— 与原著在 LLM 不可用时的行为**一致**，不谎称自答。
"""
from __future__ import annotations

import os
import shutil
import threading

from . import DEFAULT_DB, KNOWLEDGE_DIR, SEED_DIR, WISDOM_DIR  # noqa: F401

_OPEN_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 图库定位与首启播种
# --------------------------------------------------------------------------

def resolve_db_path(db_path=None):
    """白箱图库位置。

    优先级：显式参数 > `WHITEBOX_DB` / `MDCG_WHITEBOX_DB` 环境变量 >
    `MDCG_ROOT/data/whitebox/graph.db`（插件场景）>
    `~/.md_cg/whitebox/graph.db`（独立场景，开箱可用）。

    注意：**永不**把随包云库（`DEFAULT_DB`）当作可写工作库——它只作种子源，
    避免写坏只读安装或污染种子。
    """
    if db_path:
        return os.path.abspath(db_path)
    env = os.environ.get("WHITEBOX_DB") or os.environ.get("MDCG_WHITEBOX_DB")
    if env:
        return os.path.abspath(env)
    root = os.environ.get("MDCG_ROOT")
    if root:
        return os.path.join(os.path.abspath(root), "data", "whitebox", "graph.db")
    return os.path.join(os.path.expanduser("~"), ".md_cg", "whitebox", "graph.db")


def _ensure_db(path):
    """确保图库文件存在。新建时以随包云库为底（137 卡），返回是否新建。"""
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.abspath(path) != os.path.abspath(DEFAULT_DB) and os.path.exists(DEFAULT_DB):
        shutil.copy2(DEFAULT_DB, path)
    return True


def _seed_cards(dex):
    """从随包卡源（seed_knowledge/wisdom_cards/）播种知识卡。失败不阻断。"""
    try:
        from wisdom_cloud import _seed_cards as _seed
        return _seed(dex)
    except Exception:
        return 0


_SEED_META_KEY = "whitebox_seed_cards"


def _seed_targets():
    """卡源 .md 数量（0 表示无卡源，无需播种）。"""
    try:
        from wisdom_cloud import SEED_CARDS_DIR
        return len([f for f in os.listdir(SEED_CARDS_DIR)
                    if f.endswith(".md")])
    except Exception:
        return 0


# --------------------------------------------------------------------------
# 路由判定（逐字迁自 aeis/layered.py:185-247，勿改语义）
# --------------------------------------------------------------------------

def _decide_route(result, question=""):
    """路由判定：chat() 结果 → self / llm。

    自处理优先级：拦截 > 诚实边界闸门（完整回答）> 情感 > 闲聊 > 记忆 >
    自省 > 转折 > 强命中知识。
    强命中判定看 matched 质量而非只看分数（诊断依据）：
      - 翻译规范词/学科路由命中（['氧化','化学']）→ 强 → self
      - 纯神经语义（['语义']）→ neural ≥0.65 才 self（熵 0.69 self；
        北京旅行 0.385 llm）
      - 纯字面（['字面']）→ score ≥0.60 才 self（相对论争论 0.535 llm）
    v1.23：question 参数供 fp 直答强制 self（考古卡确定性直答）。
    """
    if result.get("blocked"):
        return "self"
    if result.get("honest_kind"):
        return "self"  # 诚实边界闸门（外星人/超光速/保证）已是完整回答
    if result.get("emotion"):
        return "self"
    if result.get("chitchat") or result.get("memory_reply") \
            or result.get("self_reflexive") or result.get("turn") \
            or result.get("trace_reply"):
        return "self"  # trace_reply（v1.16）：「依据是什么」→ 知识引用已是完整回答
    # v1.23 考古直答强制 self（知识考古批次3·2026-08-21）：问题编码命中
    # REVERSE_DAILY 完整概念名（≥4字）时，直答是确定性语义（「什么是内
    # 稳态」「什么是STDP」），不走 LLM——否则 LLM 展开可能丢关键词或
    # 输出英文（STDP→"The mathematical form"）。与 _assemble 的 fp 兜底
    # 一致，这里保证 route 判定也为 self（LLM 路径不经过 _assemble）。
    try:
        import semantic_translate as _st
        _qfp = _st.encode(question)
        # v1.26（错题复测发现）：阈值 3→2——「涌现」「递归」等 2 字概念
        # 在 REVERSE_DAILY 有确定性直答却被 3 字阈值滤掉（涌现 llm 讲偏、
        # 递归依赖 llm 兜底）。REVERSE_DAILY 的 2 字键 46 个全是具体概念
        # （涌现/递归/重力/原子/记忆…），无泛词，放宽安全。
        _long = [t for t in _qfp if len(t) >= 2 and t in _st.REVERSE_DAILY]
        if _long:
            _pres = [t for t in _long if t in question]
            _pool = _pres if _pres else _long
            if _pool:
                return "self"  # 确定性直答存在 → 白箱自答
    except Exception:
        pass
    hits = result.get("hits") or []
    if not hits:
        return "llm"  # 无命中诚实边界 → 智慧之书没把握 → LLM
    # v1.26（持续学习·三角形内角和）：strong 命中检查遍历全部 hits——
    # top 卡可能是纯语义低置信（「三角形」matched=['语义'] neural 不够），
    # 但第 2/3 卡有 strong 匹配（「小学数学」['三角形','字面'] 0.6489）→
    # 应 self。之前只看 hits[0]，次强命中被漏判 → 无谓走 LLM。
    for h in hits[:5]:
        _matched = h.get("matched") or []
        _strong = [m for m in _matched if m not in ("语义", "字面")]
        if _strong and (h.get("score") or 0) >= 0.30:
            return "self"  # 翻译/学科路由命中（生锈 0.757 / 1+1 0.781）
    top = hits[0]
    score = top.get("score") or 0
    neural = top.get("neural_score") or 0
    matched = top.get("matched") or []
    if set(matched) == {"语义"} and neural >= 0.65 and score >= 0.25:
        return "self"  # 神经高置信（熵 0.69）
    if set(matched) == {"字面"} and score >= 0.60:
        return "self"  # 纯字面高分数
    return "llm"


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------

class WhiteboxEngine:
    """白箱知识引擎（进程内单例式使用；线程安全由调用方串行化）。"""

    def __init__(self, db_path=None, identity="灵枢白箱", seed=True):
        self.db_path = resolve_db_path(db_path)
        self._created = _ensure_db(self.db_path)
        self.identity = identity
        self._dex = None
        self._mem = None
        self._seeded = None
        if seed and self._needs_seed():
            self._seeded = self._do_seed()

    # -- 播种（幂等 · 可自愈） --------------------------------------------
    def _needs_seed(self):
        """是否需要播种。

        判据用 engine_meta 标记，而非「文件是否存在」：首启中断会留下
        **半成品库**（文件在、卡缺失），按文件判据会永久跳过播种，
        静默少一批知识卡且永不自愈。
        """
        if self._created:
            return True
        if _seed_targets() <= 0:
            return False
        try:
            got = self.dex.store.get_meta(_SEED_META_KEY) or {}
        except Exception:
            return False
        return not got.get(_SEED_META_KEY)

    def _do_seed(self):
        added = _seed_cards(self.dex)
        try:
            self.dex.store.set_meta(_SEED_META_KEY, str(added))
        except Exception:
            pass
        return added

    # -- 惰性装配（避免仅探测连通性时加载全部图） --------------------------
    @property
    def dex(self):
        if self._dex is None:
            with _OPEN_LOCK:
                if self._dex is None:
                    from wisdom_book import ConditionDex
                    self._dex = ConditionDex(db_path=self.db_path, fresh=False)
        return self._dex

    @property
    def mem(self):
        if self._mem is None:
            with _OPEN_LOCK:
                if self._mem is None:
                    from aeis_core import SpacetimeMemoryEngine
                    self._mem = SpacetimeMemoryEngine(db_path=self.db_path,
                                                      identity=self.identity)
        return self._mem

    # -- 业务级 -----------------------------------------------------------
    def chat(self, message, session_id="default"):
        """白箱问答。返回含 route 的结果（route 已按无-LLM 情形降级）。"""
        message = (message or "").strip()
        if not message:
            return {"reply": "", "hits": [], "route": "self_fallback",
                    "engine": "whitebox_kb", "llm_available": False}
        import chat_engine
        res = dict(chat_engine.chat(self.dex, message, session_id=session_id) or {})
        route = _decide_route(res, message)
        res["route"] = route if route == "self" else "self_fallback"
        res["engine"] = "whitebox_kb"
        res["llm_available"] = False
        res.setdefault("query", message)
        res.setdefault("session_id", session_id)
        return res

    def remember(self, content, importance=0.5, tags=None, entities=None):
        """白箱编码：把一条知识写入白箱图库（知识层）。"""
        content = (content or "").strip()
        if not content:
            return {"ok": False, "error": "content 为空"}
        node = self.mem.add_perception(
            content, modality="text", importance=float(importance),
            tags=list(tags or []), entities=list(entities or []) or None)
        return {"ok": True, "node_id": getattr(node, "id", None),
                "db": self.db_path}

    def service_info(self):
        """能力库自述（供连通性探测与报告）。"""
        info = {"ok": True, "engine": "whitebox_kb", "identity": self.identity,
                "db": self.db_path, "wisdom_dir": WISDOM_DIR,
                "seed_dir": SEED_DIR, "knowledge_dir": KNOWLEDGE_DIR,
                "seeded_on_open": self._seeded, "llm_available": False}
        try:
            from aeis_core import MemoryLayer
            nodes = self.dex.store.query_nodes(layer=MemoryLayer.KNOWLEDGE,
                                               limit=2000)
            info["knowledge_nodes"] = len(nodes)
        except Exception as exc:
            info["knowledge_nodes"] = None
            info["note"] = f"{type(exc).__name__}: {exc}"
        return info

    # -- 工具级（对齐 MCP tools/call 返回形状） ----------------------------
    def call_tool(self, name, args):
        """返回 {isError, text, data}，形状与 MCP 客户端一致。"""
        import json
        a = dict(args or {})
        try:
            if name == "wisdom_chat":
                data = self.chat(a.get("message") or a.get("question") or "",
                                 session_id=a.get("session_id") or "default")
            elif name == "remember":
                data = self.remember(a.get("content") or a.get("text") or "",
                                     importance=a.get("importance", 0.5),
                                     tags=a.get("tags"),
                                     entities=a.get("entities"))
            elif name in ("service_info", "mdcg_service_info", "info"):
                data = self.service_info()
            else:
                return {"isError": True, "text": f"未知工具：{name}", "data": None}
            return {"isError": False,
                    "text": json.dumps(data, ensure_ascii=False, default=str),
                    "data": data}
        except Exception as exc:
            return {"isError": True,
                    "text": f"{type(exc).__name__}: {exc}", "data": None}

    def close(self):
        self._dex = None
        self._mem = None


_default_engine = None


def get_engine(db_path=None, **kw):
    """进程内默认引擎（懒加载单例）。"""
    global _default_engine
    if _default_engine is None:
        with _OPEN_LOCK:
            if _default_engine is None:
                _default_engine = WhiteboxEngine(db_path=db_path, **kw)
    return _default_engine
