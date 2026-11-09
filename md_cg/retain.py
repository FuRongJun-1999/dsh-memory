# -*- coding: utf-8 -*-
r"""保留规则（第一块）：**谁算「还在服役」** —— 判定 + 只读盘点。

与生命周期处置面的分工（**判据与处置分离**）：
    `sink.py`       —— 阈值来源单点（`load_policy`）+ 沉底/降层处置
    `retain.py`（本模块）—— **只判「留不留」**，不搬层、不改 frontmatter、
                             不写任何账本；写面留给后续 promote（t2）

为什么单独立一块：`sink.candidates` 判的是「谁该**下去**」（四条 AND），
而「谁该**上来/留下**」是**另一条语义轴**——它不看层、不看闲置时长，只看
「用过几次」与「够不够重要/受没受保护」。把两条轴塞进同一个函数会让
「候选为空」的归因含混：到底是层不对、太新鲜、还是被保护拦下？故此处
**另立判据面**，与 sink 共用同一份阈值（`sink.load_policy`），但不复用它的
判定顺序。

## RETAIN_FLOOR_IMPORTANCE=0.35 与 sink 的 protected_importance=0.70 的关系
**这两个数不是同一条线，不得混同**：

    protected_importance = 0.70  —— 「**跳过全部生命周期处置**」的保护线。
                                    达线即免疫沉底/降层/进 trash（sink 口径）。
    RETAIN_FLOOR_IMPORTANCE=0.35 —— 「retained 节点的重要性**下限**」。
                                    本模块用来给「留」这一档兜底：一个高
                                    access_count 但 importance 偏低的节点
                                    仍应被 retain 认下，它不该因为自己
                                    不够"重要"就在盘点里消失。

换言之 0.70 是**闸门**（拦住处置），0.35 是**地板**（托住保留）。把两者
当成同一个阈值，会导致「0.35 以上 0.70 以下的节点」既不被保护也不算保留
——盘点里凭空蒸发，正是本仓反复登记的「静默消失」缺陷族。

## 恒不抛异常
判定面被上层批处理循环调用，单节点坏形状（fm 不是 dict、access_count 是
字符串、节点文件读不出）**不该让整批中断**，也不该被 `except` 吞成「看起来
正常」——故一律**回落 + 如实归因**：取不到节点给 `node_not_found`，坏形状
按缺省值判并把原因写进 `why`。这与 `sink.load_policy` 的 fail-safe 同向。

运行：
    python -X utf8 -c "from md_cg import retain, mdcg; cg=mdcg.MdCG(r'<root>'); print(retain.retain_scan(cg))"
"""
from __future__ import annotations

import json

import os
import time

#: retained 节点的**重要性下限**（0.35）——见模块 docstring：这是「托住保留」
#: 的地板，**不是** sink 的 protected_importance（0.70，那是「拦住处置」的闸门）。
#: 两者语义分开、取值分开，任何调用方都不得把本常量当保护线用。
RETAIN_FLOOR_IMPORTANCE = 0.35

#: importance 缺省值——与 mdcg.add 的默认参数（importance: float = 0.5）同源。
#: 本模块不 import mdcg 取该默认值（会引入重依赖与循环导入风险），故就地声明；
#: 判据面若上游改了 add 的默认值，此处也必须跟着改（已在测试 G3 钉住语义）。
DEFAULT_IMPORTANCE = 0.5

#: 判定结果里的 why 关键字——**供人读也供断言**。写成模块常量是为了让
#: 「原因串的措辞」只有一处，避免各分支各拼一份后漂移（本仓既有教训：
#: 同一语义两处实现必然漂移）。
WHY_NODE_NOT_FOUND = "node_not_found"
WHY_ACCESS = "access_count"
WHY_PROTECTED = "保护"
WHY_NOT_RETAINED = "not_retained"


# 生效条件：cg 的 index 为真且其 "nodes" 为真时返回该 dict，否则返回 {}——与
# sink._nodes 同口径（只读盘点的索引面只有这一处读法，两模块各自的这份必须同形状）。
def _log_counts(cg):
    """从 `_access.log` 统计每个节点被检索命中的次数（账 115 / B 档）。

    frontmatter 里的 `access_count` 参与排序打分（账 41 正反馈老病灶），
    重新累加它会改排序分布；`_access.log` 是只追加的事件流水、不进打分，
    正好给「服役判定」提供独立计数。
    """
    path = getattr(cg, "access_log", None)
    counts = {}
    if not path:
        return counts
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return counts
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ids = rec.get("ids")
            if isinstance(ids, list):
                for nid in ids:
                    if isinstance(nid, str) and nid:
                        counts[nid] = counts.get(nid, 0) + 1
    return counts


def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


# 生效条件：value 为 bool 时返回 fallback（bool 是 int 的子类，不是数值）；否则
# 能 float(value) 时返回该 float；抛 TypeError/ValueError 时返回 fallback。恒不抛异常。
def _num(value, fallback=0.0):
    """数值容错取值：坏形状一律回落 fallback（不抛、不猜）——与 sink._num 同款。"""
    if isinstance(value, bool):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


# 生效条件：policy 为 None 时经延迟导入的 sink.load_policy() 取生效策略，否则原样用
# 传入的 policy；恒返回 (生效策略 dict, policy_source 串)——policy_source 取来源串：
# 显式传入 policy 时取 policy 自带的 source/policy_source，取不到记 'arg'（调用方显式
# 给的策略文件即「参数来源」）；经 sink 取时取 load_policy 返回体的 'source' 键，缺键
# 记 'unknown'。sink 不可导入（包结构异常）时回落内置默认 dict 并记 source='builtin'。
# 恒不抛异常。
def _resolve_policy(policy=None):
    """策略取值的**单点**：懒导入 sink，绝不重复实现策略解析。

    accept 要求返回体带 `policy_source`，而 `sink.load_policy()` 返回体里该字段
    叫 `source`（九键：五阈值 + source/invalid/path/error）——**键名不同、语义
    同一**，本函数是这一层映射的唯一落点（调用方只看 `policy_source`）。

    为什么懒导入 `from . import sink`：retain 与 sink 同处 md_cg 包，模块级
    互相 import 会在包初始化期形成环；函数内导入把依赖推迟到真正调用时，
    且导入失败可降级（不抛）。
    """
    if policy is not None:
        # 调用方显式给的策略：来源以它自带标记为准，取不到按 'arg' 记
        # （「参数给的」正是 sink.load_policy(path=...) 对应用法）。
        src = policy.get("source") or policy.get("policy_source") or "arg"
        return policy, str(src)
    try:
        from . import sink
        pol = sink.load_policy()
    except Exception:                                   # noqa: BLE001 —— 导入面降级，不抛
        # sink 整个包面不可用：回落**本模块自己的**最小默认（只保本模块判据
        # 需要的两个键），并如实标 'builtin'——绝不假装读到了策略。
        return {"keep_access_count": 3, "protected_importance": 0.7,
                "source": "builtin"}, "builtin"
    if not isinstance(pol, dict):
        return {"keep_access_count": 3, "protected_importance": 0.7,
                "source": "builtin"}, "builtin"
    return pol, str(pol.get("source") or "unknown")


# 生效条件：value 为 float 且等于其整数部分时返回该 int（3.0 → 3），否则原样返回
# value——仅用于**人读的为什么串**里的阈值渲染。为什么要这一步：阈值经 _num 归一
# 后恒为 float，直接插值会写出 'keep_access_count=3.0' 这种与策略文件原文
# （JSON 里是 3）不一致的形态，读的人会以为阈值被改过。恒不抛异常。
def _fmt(value):
    """阈值渲染：整数形态的 float 去尾（3.0→'3'），其余原样。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# 生效条件：传入 (节点 id, access_count 实测值, keep_access_count 阈值) 时恒返回
# 一条可读 why 串——含判据关键字 'access_count'（供 grep 与断言命中），后接实测
# 值与阈值，便于人读「谁、因为什么、差多少」。恒不抛异常。
def _why_access(node_id, n_acc, keep):
    """access_count 达线 ⇒ 免疫沉底的 why 串。"""
    return ("access_count=%d≥keep_access_count=%s（已用过 %d 次，免疫沉底："
            "生命周期处置面不得沉底/降层本节点）" % (n_acc, _fmt(keep), n_acc))


# 生效条件：恒返回「受保护/重要性达保护线」的可读 why 串（含 '保护' 关键字，
# 供断言与 grep 命中），后半段如实写明是 protected 位还是 importance 达线。
def _why_protected(protected, imp, prot_importance):
    """受保护 / 重要性达保护线 ⇒ 的 why 串。"""
    if protected:
        return ("受保护（frontmatter.protected 为真）⇒ 保留：跳过全部生命周期处置，"
                "importance=%.4g" % (imp,))
    return ("受保护/重要性达保护线（importance=%.4g≥protected_importance=%s）⇒ 保留"
            % (imp, _fmt(prot_importance)))


# 生效条件：恒返回「不保留」的逐条可读 why 串——把「access_count 不足」与
# 「未受保护」两条原因**同时**写出来（而非只写第一条），因为调用方常需据
# 此判断「差多少才够」：只给一句「不够」等于没有归因。
def _why_not_retained(acc, keep, n_acc, imp, prot_importance):
    """不保留 ⇒ 逐条给可读原因（access_count 不足 / 未受保护）。"""
    return ("access_count=%d<keep_access_count=%s（用过 %d 次，不够 %s 次）；"
            "importance=%.4g<protected_importance=%s 且 frontmatter.protected 非真"
            "（未受保护）"
            % (n_acc, _fmt(keep), n_acc, _fmt(keep), imp, _fmt(prot_importance)))


# 生效条件：走 sink.load_policy(path) 的单点取策略（policy 显式传入时直接用，
# 不再读盘），对 cg 中 id 为 nid 的节点做**确定性**保留判定并返回 dict（三键：
# retained/why/policy_source）。判定顺序固定：① cg.get(nid) 取不到 ⇒
# retained=False, why='node_not_found'；② access_count ≥ policy['keep_access_count']
# ⇒ retained=True, why 含 'access_count'（附免疫沉底语义）；③ importance（缺省 0.5）
# ≥ policy['protected_importance'] **或** frontmatter.protected 为真 ⇒ retained=True,
# why 含 '保护'；④ 其余 ⇒ retained=False，why 逐条给原因。**恒不抛异常**：policy 非
# dict、fm 非 dict、取值坏形状、cg.get 抛异常一律吞成相应分支的结果。
def retain_verdict(cg, nid, *, policy=None, now=None, use_count=None):
    """单节点保留判定 → dict（**只读**，不写盘、不改任何字段）。

    "retained=True" 的语义是「该节点**还在服役**，生命周期处置面不该动它」；
    它**不等于** sink 的“受保护”（0.70 那条线）——一个 access_count 达线、
    importance 只有 0.4 的节点是 retained 但**不**受保护：处置面仍可按层/
    闲置等其它判据看待它（那是处置面的口径，本模块不替它决定）。

    返回体三键：
        retained      —— bool
        why           —— 可读原因串（**永远非空**；not-found 时为
                         'node_not_found'，其余分支含判据关键字）
        policy_source —— 本次判据实际用的策略来源
                         ('env'|'arg'|'default_file'|'builtin')

    参数：
        policy —— 显式策略 dict；None 时经 `sink.load_policy()` 取（懒导入）。
        now    —— 基准时间戳。**本模块的判据不依赖时间**（保留看的是
                  「用过几次」与「够不够重要/受不受保护」，二者都与"现在"
                  无关），该参数为**签名兼容与后续 promote 留位**：显式接收
                  并在返回体语义上标明「本次判定与 now 无关」，避免调用方
                  误以为传 now 会改变判定结果。
    """
    pol, source = _resolve_policy(policy)
    if not isinstance(pol, dict):
        pol, source = {}, "unknown"

    # ① 节点取不到 ⇒ 唯一一个「非判据」的 not-retained 分支。
    # 为什么单列：'node_not_found' 与「判据没过」在调用方看来必须可分——
    # 前者是**输入错**（id 拼错/已被删），后者是**策略结果**，处置动作相反。
    try:
        node = cg.get(nid)
    except Exception as exc:                            # noqa: BLE001 —— 读失败不抛
        return {"retained": False,
                "why": "%s（读节点抛 %s: %s）"
                       % (WHY_NODE_NOT_FOUND, type(exc).__name__, exc),
                "policy_source": source}
    if not node:
        # 账 115 附带修：`cg.get()` 对别人的 private 节点恒 None（账 107/127 同族）。
        # 服役判定只要 frontmatter 里几个数，不该被「正文读不出」连坐。
        # 走索引条目 + `_read()`；`_read` 可能返回 dict 或 (dict, content)，两种都收。
        try:
            _e = (cg.index.get("nodes") or {}).get(nid)
            _r = cg._read(_e) if _e else None
            _fm = _r[0] if isinstance(_r, tuple) and _r else _r
            if isinstance(_fm, dict):
                node = {"frontmatter": _fm, "content": ""}
        except Exception:                           # noqa: BLE001
            node = None
        if not node:
            return {"retained": False, "why": WHY_NODE_NOT_FOUND,
                    "policy_source": source}

    fm = node.get("frontmatter") if isinstance(node, dict) else None
    if not isinstance(fm, dict):
        fm = {}                                         # 坏形状按空 fm 判，不抛

    keep = _num(pol.get("keep_access_count"), 3.0)
    prot_importance = _num(pol.get("protected_importance"), 0.7)
    n_acc = int(_num(fm.get("access_count"), 0.0))
    if use_count is not None:
        n_acc = max(n_acc, int(use_count))
    imp = _num(fm.get("importance"), DEFAULT_IMPORTANCE)
    protected = bool(fm.get("protected"))

    # ② access_count 达线：**第一优先**。为什么排在 protected 之前：这一条
    # 的 why 对调用方信息量更大（「用过几次」是可累积的服役证据），且两条
    # 都成立时优先报 access_count 能让「为什么留」的归因稳定可复现。
    if n_acc >= keep:
        return {"retained": True,
                "why": _why_access(nid, n_acc, keep),
                "policy_source": source}

    # ③ 受保护 / 重要性达保护线。注意：protected_importance 用的是 **sink 的
    # 保护线（0.70）**，不是本模块的 RETAIN_FLOOR_IMPORTANCE（0.35）——两者
    # 语义不同，见模块 docstring。
    if protected or imp >= prot_importance:
        return {"retained": True,
                "why": _why_protected(protected, imp, prot_importance),
                "policy_source": source}

    # ④ 其余：逐条给可读原因。
    return {"retained": False,
            "why": _why_not_retained(n_acc, keep, n_acc, imp, prot_importance),
            "policy_source": source}


# 生效条件：只读遍历 cg.index['nodes']，对每个节点调 retain_verdict 并按 retained
# 与「受保护」两个正交标记分入三桶，返回 {'retained':[{id,access_count,importance,why}],
# 'not_retained':[同形状], 'protected':[同形状], 'policy_source':串, 't':基准时间}。
# **零写盘**：不调任何写方法、不写账本、不重建索引、不 touch 任何文件。单节点读
# 异常不中断整批（该节点按 retain_verdict 的降级结果落进对应桶）。恒不抛异常。
def retain_scan(cg, *, policy=None, now=None):
    """全库保留盘点 → dict（**只读**；跑前后盘面逐位不变）。

    三组清单（accept 原文口径）：
        retained     —— retained=True 的节点
        not_retained —— retained=False 的节点（**不含** node_not_found：
                        那只可能来自显式传入的坏 id，遍历索引取不到节点时
                        本身就意味着索引与盘面分叉，此时按 not_retained 记
                        并把 'node_not_found' 写进 why，让分叉可见）
        protected    —— **正交**标记：fm.protected 为真的节点。为什么单列而
                        不并入 retained：受保护的节点**必然** retained，但
                        retained 的节点**不必**受保护（高 access_count 即可）
                        ——把两者混成一桶，「谁是被保护线拦下的、谁是自己
                        用出来的」就再也分不开了

    每条记录四键：id / access_count / importance / why（原始实测值一并给出，
    便于人读「差多少」）。

    为什么每桶都带 why：只给 id 列表时，「保留了 3 个」与「保留了 3 个但其中
    两个是碰巧达线」在调用方看来完全同形；why 让每一条的归因瞬时可读，
    与 sink.candidates 的 skipped 逐条留痕是同一纪律。

    参数 now：同 retain_verdict——本模块判据**与时间无关**，now 只作基准
    时间回显（返回体 't'）与签名兼容位。
    """
    pol, source = _resolve_policy(policy)
    base_now = float(now if now is not None else time.time())

    counts = _log_counts(cg)
    out = {"retained": [], "not_retained": [], "protected": [],
           "policy_source": source, "t": base_now}

    for node_id, entry in sorted(_nodes(cg).items()):
        try:
            verdict = retain_verdict(cg, node_id, policy=pol, now=base_now, use_count=counts.get(node_id))
        except Exception as exc:                        # noqa: BLE001 —— 单条坏不中断整批
            # retain_verdict 自称恒不抛；此处仍兜一层——「恒不抛」是它的承诺，
            # **不是**盘点面可以省略兜底的理由（承诺被打破时，整批盘点不该全废）。
            verdict = {"retained": False,
                       "why": "verdict_error: %s: %s"
                              % (type(exc).__name__, exc),
                       "policy_source": source}

        # 原始实测值：为什么从 fm 重读而不从 verdict 里取——verdict 的返回体
        # 按 accept 只承诺三键（retained/why/policy_source），把 access_count
        # 塞进它会超出契约；盘点面要出这组读数，故在此单读一次。
        fm = {}
        try:
            node = cg.get(node_id) or {}
            fm = node.get("frontmatter") or {}
            if not isinstance(fm, dict):
                fm = {}
        except Exception:                               # noqa: BLE001
            fm = {}

        rec = {"id": node_id,
               "access_count": int(_num(fm.get("access_count"), 0.0)),
               "importance": round(_num(fm.get("importance"), DEFAULT_IMPORTANCE), 4),
               "why": verdict.get("why", "")}

        if bool(fm.get("protected")):
            out["protected"].append(dict(rec))

        if verdict.get("retained"):
            out["retained"].append(rec)
        else:
            out["not_retained"].append(rec)

    return out


# ---- t2：写面（重要性提升） --------------------------------------------------
# 判据与处置**分离**的兑现：本模块上半段只判「留不留」，写面（本段）才动盘面。
# 写盘纪律**照抄 weights.recalc**（唯一范本）：三闸取与 ⇒ allow_apply；否则只预演。
# 三条 blocked_by 措辞是**契约**（accept 原文点名），调用方与守卫按串断言，不得改写。
BLOCKED_NOT_WRITABLE = "本轮未放行写盘"
BLOCKED_NO_WINDOW = "主库可写窗口未开"
BLOCKED_AUTONOMY_FMT = "自治档位闸: %s"

#: 提升动作名（账本 action 与可回滚判定都靠它；`retain_promote`/`retain_rollback`
#: 与 weights 的 `importance`/`importance_rollback` 同族 —— 同一本 _maintain.jsonl）。
ACTION_PROMOTE = "retain_promote"
ACTION_ROLLBACK = "retain_rollback"


# 生效条件：policy 为 None 时经 _resolve_policy() 取生效策略（懒导入 sink），否则原样
# 用；从中取 keep_access_count（缺键回落 3.0）与 protected_importance（缺键回落 0.7），
# 返回 (pol, 数值化的两阈值)——retain_scan 与本函数共用**同一份**阈值解析，绝不各读一份。
def _policy_numbers(policy=None):
    """策略取值的单点复用：返回 (生效策略 dict, keep_access_count, protected_importance)。"""
    pol, _source = _resolve_policy(policy)
    if not isinstance(pol, dict):
        pol = {}
    return pol, _num(pol.get("keep_access_count"), 3.0), \
        _num(pol.get("protected_importance"), 0.7)


# 生效条件：ids 为真值时返回 [str(x) for x in ids]（顺序即调用方给的顺序，不排序——
# 「我点了哪几个」必须原样回显）；否则调 retain_scan 取 retained 清单的 id（按 id 排序，
# 与盘点面同序）；返回 (候选 id 列表, 候选来源串 'ids'|'scan')。恒不抛异常。
def _promote_candidates(cg, ids, pol, now):
    """候选来源二选一：显式 ids 优先，否则 retain_scan 的 retained 清单。"""
    if ids:
        return [str(x) for x in ids], "ids"
    try:
        scan = retain_scan(cg, policy=pol, now=now)
    except Exception:                                   # noqa: BLE001 —— 盘点面自承恒不抛，此处再兜一层
        return [], "scan"
    return [r["id"] for r in scan.get("retained", [])], "scan"


# 生效条件：apply 为真时先判 writable（假 ⇒ 记 BLOCKED_NO_WINDOW 零写盘），再经懒导入的
# autonomy_modes.e_gate() 判档位（decision != ALLOW ⇒ 记 BLOCKED_AUTONOMY_FMT 零写盘）；
# apply 为假 ⇒ 记 BLOCKED_NOT_WRITABLE。返回 (allow_apply: bool, blocked_by: 串)——三闸取与，
# 缺一即拦，**任何一条被拦时本函数不做任何盘面写入**（fail-closed）。
def _write_permits(apply, writable):
    """写盘三闸（照抄 weights.recalc 的档位闸纪律）：apply ∧ writable ∧ e_gate()==ALLOW。"""
    if not apply:
        return False, BLOCKED_NOT_WRITABLE
    if not writable:
        return False, BLOCKED_NO_WINDOW
    from . import autonomy_modes as _am          # 懒导入：避免模块级环（同 _resolve_policy 的 from . import sink）
    try:
        dec = _am.e_gate()
        decision = dec.get("decision")
    except Exception as exc:                     # noqa: BLE001 —— 档位面读不出 ⇒ fail-closed
        # 档位读数不可得不等于可以写：fail-closed 按「非 ALLOW」拦下，并把异常名如实
        # 写进 blocked_by（不伪装成某个具体档位值，读的人能看出是判定本身出了问题）。
        return False, BLOCKED_AUTONOMY_FMT % ("gate_error:%s" % type(exc).__name__)
    if decision != _am.ALLOW:
        return False, BLOCKED_AUTONOMY_FMT % (decision,)
    return True, ""


# 生效条件：传入 cg 与节点 id 时返回该节点磁盘路径——索引条目的 path 优先，其次节点自身
# 的 path，都没有则回落 '<nid>.md'（与 weights.recalc 逐字同口径）；恒不抛异常。
def _node_path(cg, nid, node):
    """节点写盘路径（索引优先，与 weights.recalc 同一取值口径）。"""
    nodes = _nodes(cg)
    return os.path.join(cg.root, (nodes.get(nid) or {}).get("path")
                        or node.get("path") or "%s.md" % nid)


# 生效条件：对候选 id 逐个取节点算 before/after，低于 floor 才进 write_plan（已 ≥ floor 记
# unchanged 不写盘），取不到节点记 skipped；返回 (write_plan, samples, counts)——write_plan 每项
# {id,before,after,floor}，samples 每项含 blocked_by 如实记「被哪一闸拦」（allow_apply 为假时
# 取屏拦串，为真时记 '允许写盘'）。恒不抛异常：单节点坏形状不中断整批。
def _plan_promotions(cg, cand_ids, floor, allow_apply, blocked_by, sample_limit=10):
    """逐候选预演（**只读**）：低于 floor 才抬，账目三键 unchanged/skipped/written 可分辨。"""
    plan, samples = [], []
    unchanged = skipped = 0
    for nid in cand_ids:
        try:
            node = cg.get(nid)
        except Exception:                               # noqa: BLE001 —— 读失败不中断整批
            node = None
        if not node:
            skipped += 1
            continue
        fm = node.get("frontmatter")
        if not isinstance(fm, dict):
            fm = {}                                     # 坏形状按空 fm 判，不抛
        before = _num(fm.get("importance"), DEFAULT_IMPORTANCE)
        # ⑥ 低于 floor 才抬：already ≥ floor ⇒ after == before ⇒ unchanged 不写盘。
        after = before if before >= floor else floor
        if after <= before:
            unchanged += 1
        else:
            plan.append({"id": nid, "before": before, "after": after,
                         "floor": floor})
        if len(samples) < int(sample_limit):
            samples.append({"id": nid, "before": round(before, 4),
                            "after": round(after, 4), "floor": round(floor, 4),
                            "blocked_by": "" if allow_apply else blocked_by})
    return plan, samples, {"unchanged": unchanged, "skipped": skipped}


# 生效条件：allow_apply 为真时逐计划项把 fm['importance']=after（=max(before,floor)）、
# fm['importance_source']='retain'、fm['retained_since']=time.time() 经 cg._write_node 落盘、
# 同步索引条目 importance，并向 cg.root/_maintain.jsonl 追一条 action='retain_promote' 记账；
# 写完 rebuild_index 使内存与盘面对齐；allow_apply 为假时**一行都不执行**（零写盘，含零记账行）。
# 返回 (written, batch)。恒不抛异常：单节点写失败记跳过后继续。
def _apply_promotions(cg, write_plan, actor):
    """写盘支路（**只能在三闸全过时进**）：写节点 + 同步索引 + 记账 + 重建索引。"""
    from .fsutil import append_jsonl                    # 懒导入：模块级 import 会造成包初始化期环
    from .weights import MAINTAIN_LOG                   # 账本名取 weights 的既有口，不写第二份字面量
    now = time.time()
    batch = time.strftime("%Y%m%d-%H%M%S")
    written = 0
    for item in write_plan:
        nid = item["id"]
        try:
            node = cg.get(nid)
            if not node:
                continue
            fm = node.get("frontmatter")
            if not isinstance(fm, dict):
                continue
            fm["importance"] = item["after"]
            fm["importance_source"] = "retain"
            fm["retained_since"] = now
            # 写盘经既有唯一写口（同 weights.recalc 第 552 行），不自己拼文件。
            cg._write_node(nid, _node_path(cg, nid, node), fm,
                           node.get("content") or "")
            entry = _nodes(cg).get(nid)
            if entry is not None:
                entry["importance"] = item["after"]
            # ④ 记账：与 weights 同族（同一本 _maintain.jsonl、同一个 append_jsonl 口），
            # 反向应用见本模块 rollback()（写回 before 并记 'retain_rollback'）。
            append_jsonl(os.path.join(cg.root, MAINTAIN_LOG),
                         {"t": now, "action": ACTION_PROMOTE, "batch": batch,
                          "id": nid, "before": item["before"],
                          "after": item["after"], "floor": item["floor"],
                          "actor": actor})
            written += 1
        except Exception:                               # noqa: BLE001 —— 单节点写失败不废整批
            continue
    if written and hasattr(cg, "rebuild_index"):
        cg.rebuild_index()          # 索引与盘面重新对齐，防内存/磁盘分叉（同 weights.recalc）
    return written, batch


# 生效条件：恒返回 promote 的读数体（键：ok/dry_run/batch/n_candidates/written/
# blocked_by/samples/t，另附候选来源与逐档计数便于人读），风格与 weights.recalc 同族。
def _promote_result(cand_ids, allow_apply, blocked_by, samples, counts,
                    written, batch, t0, source, floor):
    """promote 读数体（与 weights.recalc 的 ok/dry_run/batch/written/samples 同风格）。"""
    return {"ok": True, "dry_run": not allow_apply, "batch": batch,
            "n_candidates": len(cand_ids), "written": written,
            "blocked_by": blocked_by, "samples": samples,
            "floor": floor, "candidate_source": source,
            "unchanged": counts["unchanged"], "skipped": counts["skipped"],
            "t": t0, "elapsed_ms": int((time.time() - t0) * 1000),
            "action": ACTION_PROMOTE,
            "note": ("dry-run：未写盘（%s）" % blocked_by if not allow_apply else
                     "已提升 %d 个节点；回滚见 retain.rollback(batch=%s）"
                     % (written, batch))}


# 生效条件：对 cg 中「retained 且 importance < floor」的节点做重要性提升——
# 候选 = ids 显式给出（原序），否则 retain_scan 的 retained 清单；**写盘三闸**取与
# （apply ∧ writable ∧ autonomy_modes.e_gate() 的 decision==ALLOW）才 allow_apply，
# 缺一即只预演（apply=False 出真读数：每个候选的 before/after/blocked_by），**零写盘**；
# allow_apply 时逐节点写 fm['importance']=max(before,floor)、fm['importance_source']='retain'、
# fm['retained_since']=time.time()，经 cg._write_node 落盘并同步索引条目，向 _maintain.jsonl
# 记 {'t','action':'retain_promote','batch','id','before','after','floor','actor'} 后 rebuild_index；
# **低于 floor 才抬**（already ≥ floor 记 unchanged 不写盘）。返回 {'ok','dry_run','batch',
# 'n_candidates','written','blocked_by','samples','t'}。恒不抛异常。
def promote(cg, *, ids=None, apply=False, writable=False, actor="retain",
            policy=None, floor=RETAIN_FLOOR_IMPORTANCE):
    """重要性提升（t2 写面）：把 retained 节点的重要性托到 floor（缺省 0.35）。

    与 `retain_scan`（只判不留痕）的分工：本函数是**处置面**——它是本模块唯一
    会动盘面的入口，且只有在**三闸取与**时才动。

    ## 写盘三闸（照抄 `weights.recalc` 的档位闸纪律）
        allow_apply = bool(apply) and bool(writable) and (e_gate().decision == ALLOW)
    缺一即**只预演**（`dry_run=True`），此时返回体仍给**真读数**（每个候选的
    before/after/blocked_by 都是实算的），但盘面一位不动。`blocked_by` 如实记
    被哪一闸拦下（三串是契约，见模块常量）：
        '本轮未放行写盘'      —— apply 为假（调用方没点写盘）
        '主库可写窗口未开'    —— writable 为假（没拿到写窗口）
        '自治档位闸: <decision>' —— e_gate() 未 ALLOW（plan 档无计划等）
    为什么三闸要**取与**而不是「apply 为真就写」：apply 是**调用意图**，
    writable 是**环境窗口**，档位是**放权裁决**——三者缺一，写盘就变成了
    「意图覆盖环境/裁决」，正是本仓反复登记的越权写族。故一律 fail-closed。

    ## 为什么「低于 floor 才抬」而不是一律写 floor
    一律写会把 importance=0.50 的节点**压低**到 0.35 —— 一个「提升」动作做出了
    降级的效果。故 after = max(before, floor)：already ≥ floor 记 unchanged、
    **不写盘**（连账本行都不出），这一条也是幂等的来源（⑤）。

    ## 记账与回滚
    每条写 `_maintain.jsonl`（`weights.MAINTAIN_LOG`）一行
    `{'t','action':'retain_promote','batch','id','before','after','floor','actor'}`
    ——与 weights 的 `importance` 记录**同一本账**，故 `weights.rollback` 与本模块
    `rollback` 都能按 action 过滤反向应用（写回 before 并记 'retain_rollback'）。
    为什么把 before 一并记账：没有 before 的账只能「再抬一次」，回不去。

    参数：
        ids      —— 显式候选；None/空时取 `retain_scan` 的 retained 清单。
        apply    —— 是否允许写盘（第一闸）。
        writable —— 主库写窗口是否已开（第二闸）。
        actor    —— 记账主体署名。
        policy   —— 显式生命周期策略；None 时经 `sink.load_policy()` 取。
        floor    —— 重要性地板（缺省 `RETAIN_FLOOR_IMPORTANCE`=0.35）。

    恒不抛异常：节点读不出记 skipped、写单节点失败不废整批，一律如实计数。
    """
    t0 = time.time()
    floor = _num(floor, RETAIN_FLOOR_IMPORTANCE)
    pol, _keep, _prot = _policy_numbers(policy)
    cand_ids, source = _promote_candidates(cg, ids, pol, t0)
    allow_apply, blocked_by = _write_permits(apply, writable)
    plan, samples, counts = _plan_promotions(cg, cand_ids, floor, allow_apply,
                                             blocked_by)
    if not allow_apply:
        # 预演面：真读数、零写盘（不建 batch 目录、不写账本、不 rebuild_index）。
        return _promote_result(cand_ids, False, blocked_by, samples, counts,
                               0, None, t0, source, floor)
    written, batch = _apply_promotions(cg, plan, actor)
    return _promote_result(cand_ids, True, "", samples, counts, written, batch,
                           t0, source, floor)


# 生效条件：cg.root/_maintain.jsonl 可读出 action=='retain_promote' 记录后，entry_ids 为真值时
# 按记录 id 在 {str(x)…} 内过滤；否则 batch 为真值时按 r.get('batch')==batch 过滤；否则取最后
# 一条记录的 batch 再按其过滤；无 promote 记录返回 {'ok':False,'error':'no_records','reverted':0}，
# 过滤后为空返回 {'ok':False,'error':'batch_not_found',...}；对命中且 cg.get(nid) 为真的记录写回
# rec['before']（步骤②同款 _write_node + 索引同步），若 reverted 且 cg 有 rebuild_index 则调用，
# 最后 append_jsonl 记 {'action':'retain_rollback'} 并返回 {'ok':True,'batch','reverted','ids'}。
def rollback(cg, batch=None, entry_ids=None, actor="retain"):
    """把 `promote` 反向应用（提升的可回滚兑现）——写回 before 并记 'retain_rollback'。

    batch 为空则回滚**最近一批**。返回 {ok, reverted, batch, ids}。
    与 `weights.rollback` 的分工：两者读**同一本** `_maintain.jsonl`，只按各自
    的 action 过滤（`importance` vs `retain_promote`）——故互不误伤。
    """
    from .fsutil import append_jsonl, read_jsonl
    from .weights import MAINTAIN_LOG
    log_path = os.path.join(cg.root, MAINTAIN_LOG)
    records = [r for r in read_jsonl(log_path)
               if r.get("action") == ACTION_PROMOTE]
    if not records:
        return {"ok": False, "error": "no_records", "reverted": 0}
    if entry_ids:
        want = {str(x) for x in entry_ids}
        records = [r for r in records if str(r.get("id")) in want]
    elif batch:
        records = [r for r in records if r.get("batch") == batch]
    else:
        batch = records[-1].get("batch")
        records = [r for r in records if r.get("batch") == batch]
    if not records:
        return {"ok": False, "error": "batch_not_found", "batch": batch,
                "reverted": 0}
    reverted, ids = 0, []
    for rec in records:
        nid = rec.get("id")
        try:
            node = cg.get(nid)
            if not node:
                continue
            fm = node.get("frontmatter") or {}
            fm["importance"] = rec.get("before")
            fm["importance_source"] = "retain_rollback"
            cg._write_node(nid, _node_path(cg, nid, node), fm,
                           node.get("content") or "")
            entry = _nodes(cg).get(nid)
            if entry is not None:
                entry["importance"] = rec.get("before")
            reverted += 1
            ids.append(nid)
        except Exception:                               # noqa: BLE001 —— 单节点失败不废整批
            continue
    if reverted and hasattr(cg, "rebuild_index"):
        cg.rebuild_index()
    append_jsonl(log_path, {"t": time.time(), "action": ACTION_ROLLBACK,
                            "batch": batch, "reverted": reverted,
                            "actor": actor})
    return {"ok": True, "batch": batch, "reverted": reverted, "ids": ids}
