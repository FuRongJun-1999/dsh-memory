# -*- coding: utf-8 -*-
r"""生命周期策略单点读取：沉底 / 降层 / 进 trash 的**阈值来源**。

与 `audit.py` 的规则库（合规 + 纪律）是**同族的另一个文件**：
    env `MDCG_POLICY_FILE`        → data/policy.json        内容合规（forbidden/required）
    env `MDCG_LIFECYCLE_FILE`     → data/lifecycle_policy.json  生命周期阈值（本模块）

本模块只做三件事：**定位 → 读取 → 形状闸**；不删任何节点、不改任何层。
「谁进候选」在这里定，「怎么处置」仍归 scrub / sustain 的既有闸门。

为什么单点：来源判定（env vs path vs 包内默认 vs 内置）只有这一处，
未来 sink 的调用面读同一个 `load_policy()`——「同一语义两处实现」必然漂移
（本仓既有教训：负条件判据、CCG 冒号形态、策略计数）。

为什么**恒不抛异常**：生命周期策略不可用是**可诊断的事实**，不是致命错误。
抛异常会被上层兜底 `except` 吞成「看起来正常」的默认行为——那才是真缺陷
（audit.py 的 issue #43 病态出口正是同一形状）。故一律回落内置默认值，
并在返回体的 `source` / `invalid` 里**如实标明实际来源与坏键**。

运行：python -X utf8 -c "from md_cg import sink; print(sink.load_policy())"
"""
from __future__ import annotations

import datetime
import json
import os
import time

#: env 名（与 audit.POLICY_ENV 同族命名，便于排查时一眼分辨两面）
SINK_ENV = "MDCG_LIFECYCLE_FILE"
#: 包内随发默认策略相对路径（**判据面**：改这里等于改默认来源）
DEFAULT_LIFECYCLE_REL = ("data", "lifecycle_policy.json")

#: 内置默认值——**唯一一份**（文档默认与回落默认同源，不许再写字面量第二遍）。
#: 改这里只影响「文件也拿不到」时的最后兜底；正常路径应当改 data/lifecycle_policy.json。
BUILTIN_DEFAULTS = {
    "sink_days": 90,
    "keep_access_count": 3,
    "demote_layers": ["knowledge"],
    "trash_days": 180,
    "protected_importance": 0.7,
}

#: 整数型键（**判据面**）：取值必须是 int 且非 bool（`isinstance(True, int)` 为真，
#: 故 bool 必须显式排除——`{"sink_days": true}` 不是「90 天的真值」，是坏形状）。
INT_KEYS = ("sink_days", "keep_access_count", "trash_days")
#: 数值型键：int 或 float（不含 bool）
NUM_KEYS = ("protected_importance",)
#: 列表型键：取值必须是 list/tuple，元素须为字符串
LIST_KEYS = ("demote_layers",)
#: 参与形状判定的全部键——白名单式（而非「所有键都须合法」）是必须的：
#: 默认文件里 `_comment`/`_note` 本就是字符串，泛化闸会把**合法默认策略**判死。
#: 其余键（含未知键）一律不参与形状判定——未知键是「没读到」，不是「读坏了」。
POLICY_KEYS = INT_KEYS + NUM_KEYS + LIST_KEYS


# 生效条件：始终返回本模块所在包的包根绝对路径（`md_cg/` 的父目录），由 __file__ 反推——与 os.getcwd() 无关，cwd 在任何目录下取值相同。
def package_root() -> str:
    """包根（`md_cg/` 的父目录）——定位方式与 audit.package_root 同款。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：始终返回包内默认生命周期策略文件的绝对路径（<包根>/data/lifecycle_policy.json）；不判存在性、不读盘——存在性由 load_policy 的读取分支判，坏路径在那里可见。
def default_policy_path() -> str:
    """包内随发生命周期策略路径（按包根解析，不依赖 cwd）。"""
    return os.path.join(package_root(), *DEFAULT_LIFECYCLE_REL)


# 生效条件：恒返回 `LAYERS` 元组——延迟导入 mdcg（可能较重，且存在循环导入风险）成功时取该元组，导入失败或 LAYERS 非法时返回空元组（空元组在 _clean_layers 里的语义是「不做层名校验」，即**降级为不判**，绝不抛异常）。
def _layers():
    """mdcg.LAYERS 的**延迟**取值 → tuple；拿不到时返回空元组（＝豁免层名校验）。"""
    try:
        from .mdcg import LAYERS
    except Exception:                                   # noqa: BLE001 —— 导入面降级，不抛
        return ()
    return tuple(LAYERS) if isinstance(LAYERS, (list, tuple)) else ()


# 生效条件：调用 _layers() 后对 value 逐个元素校验——元素非字符串、或在已知层名集合外时，把该元素从生效值里剔除，恒返回 (清洗后的列表, 是否发生了剔除)；_layers() 为空元组（拿不到层清单）时**整体放行**（value 原样浅拷贝、剔除标记为 False），不猜、不擅自清空。
def _clean_layers(value):
    """`demote_layers` 的层名自检 → (layers, dropped)。

    为什么要与 mdcg.LAYERS 对账：层白名单是**导出面**的输入，出现不存在的层名
    （拼写错 / 上游改名 / 手改文件）若不拦，其结果不是报错而是**静默不生效**
    ——「候选永远为空」看起来和「暂时没有可沉底节点」一模一样。
    故：越界层名从生效值里剔除 + 记入 invalid，让调用方看得见。
    """
    layers = list(value)
    known = _layers()
    if not known:
        return layers, False
    kept = [name for name in layers
            if isinstance(name, str) and name in known]
    return kept, len(kept) != len(layers)


# 生效条件：rules 非 dict 时返回 {}（调用方视作「整份文件不可用」）；rules 为 dict 时逐键过形状闸——int 键须为 int 且非 bool、数值键须为 int/float 且非 bool、列表键须为 list/tuple 且元素须为字符串；**任一键坏掉只影响该键**：坏键不进结果、键名记入返回值，其余合法键照常生效；返回 (合法键值 dict, 非法键名列表)，恒不抛异常。
def _shape_filter(rules):
    """形状闸 → (ok_values, invalid_keys)。

    为什么**逐键**回落而不是整份判死：策略文件是**阈值集合**，一个键写坏
    （比如 `keep_access_count` 写成字符串）不应该让另外四个正确的阈值一起失效
    ——那是「一个笔误换掉全部判据」，比坏键本身更危险。
    但「坏键静默用默认」同样不可接受：坏值必须可见，故键名进 `invalid`。
    """
    ok, invalid = {}, []
    for key in POLICY_KEYS:
        if key not in rules:
            continue                                    # 缺键 ≠ 坏键：回落默认，不记 invalid
        value = rules[key]
        broken = False
        if key in INT_KEYS:
            broken = not (isinstance(value, int) and not isinstance(value, bool))
        elif key in NUM_KEYS:
            broken = not (isinstance(value, (int, float))
                          and not isinstance(value, bool))
        elif key in LIST_KEYS:
            broken = (not isinstance(value, (list, tuple))
                      or not all(isinstance(x, str) for x in value))
        if broken:
            invalid.append(key)
        else:
            ok[key] = value
    return ok, invalid


# 生效条件：path 指向的文件可读、json 解析得 dict 时返回 (dict, None)；文件不存在、OSError、JSON 非法、顶层非对象一律返回 (None, 原因串)——调用方据此回落，不抛异常。
def _read_policy_file(path):
    """读单个策略文件 → (rules|None, 原因|None)。"""
    if not os.path.exists(path):
        return None, "文件不存在：%s" % path
    try:
        with open(path, encoding="utf-8") as f:
            rules = json.load(f)
    except OSError as exc:
        return None, "读取失败：%s: %s" % (type(exc).__name__, exc)
    except ValueError as exc:
        return None, "JSON 解析失败：%s" % exc
    if not isinstance(rules, dict):
        return None, "顶层须为 JSON 对象（实得 %s）" % type(rules).__name__
    return rules, None


# 生效条件：env MDCG_LIFECYCLE_FILE 去空后非空时为来源 A（source='env'）、否则 path 去空后非空时为来源 B（source='arg'）、否则回落 default_policy_path()（source='default_file'）——该来源的文件读不到或形状不可用（非 dict / JSON 非法 / 顶层非对象）时一律回落 BUILTIN_DEFAULTS（source='builtin'）；五键逐键取值＝文件里的合法值，否则取内置默认；恒返回九键 dict（五键 + source/invalid/path/error），恒不抛异常。
def load_policy(path=None):
    """生命周期策略读取单点 → dict（**不是元组**）。

    返回体九键：
        sink_days / keep_access_count / demote_layers / trash_days /
        protected_importance  —— 生效值（永远可用，坏键已回落）
        source   —— 'env' | 'arg' | 'default_file' | 'builtin'（实际来源）
        invalid  —— 键名列表（形状坏掉的键；层名越界也记 'demote_layers'）
        path     —— 实际尝试读取的绝对路径（builtin 时为 default_policy_path()）
        error    —— 该路径读取/解析失败的原因串，或 None

    来源优先级（**判据面**）：env > path 参数 > 包内默认 > 内置默认。
    为什么 env 压过 path：env 是「本轮/本进程显式指定」，path 只是调用方给的
    建议值；两者冲突时以更外层的显式决定为准，与 audit.resolve_rulebook 同向。

    为什么不「显式来源坏了就报错」：审计面的策略不可用必须 fail-closed（宁可
    拒写），而生命周期阈值不可用只该 fail-safe（宁可少沉底、绝不误删）——
    后者的正确兜底就是内置默认值 + 把来源标成 'builtin' 让它可见。
    """
    tried = default_policy_path()
    source = "builtin"
    selected = None
    env_path = str(os.environ.get(SINK_ENV) or "").strip()
    arg_path = str(path).strip() if path is not None else ""
    if env_path:
        tried, source, selected = env_path, "env", env_path
    elif arg_path:
        tried, source, selected = arg_path, "arg", arg_path
    else:
        source, selected = "default_file", tried

    rules, error = None, None
    if selected:
        rules, error = _read_policy_file(selected)
    if rules is None:
        # 文件缺失 / 读不了 / JSON 坏 / 顶层非对象 ⇒ 整份回落内置默认。
        # 若 selected 就是包内默认路径，此时 error 亦为 None（本来就打算回落）。
        merged = dict(BUILTIN_DEFAULTS)
        return _result(merged, "builtin", [], tried,
                       error or ("来源不可用，回落内置默认：%s" % (tried,))
                       if selected else None)

    ok, invalid = _shape_filter(rules)
    values = dict(BUILTIN_DEFAULTS)
    values.update(ok)                                   # 合法键覆盖默认，坏键/缺键留默认
    layers, dropped = _clean_layers(values["demote_layers"])
    values["demote_layers"] = layers
    if dropped and "demote_layers" not in invalid:
        invalid.append("demote_layers")                 # 层名越界：剔除 + 如实记下
    return _result(values, source, invalid, tried, error)


# 生效条件：传入五键生效值、来源串、非法键名列表、路径串与错误串时，恒返回九键 dict——五键各取 values 的同名键（缺键取 BUILTIN_DEFAULTS 同名键），invalid 去重后按 POLICY_KEYS 顺序输出以保证可断言，error 为原样透传；恒不抛异常。
def _result(values, source, invalid, tried, error):
    """返回体形状的**单点**（构造只此一处，避免各分支各拼一份）。"""
    body = {key: values.get(key, BUILTIN_DEFAULTS[key]) for key in POLICY_KEYS}
    ordered = [key for key in POLICY_KEYS if key in set(invalid)]
    body.update({"source": source, "invalid": ordered, "path": tried,
                 "error": error})
    return body


# --------------------------------------------------------------------------
# ② 沉底候选盘点（只读） / 降层实修
# --------------------------------------------------------------------------

#: 幂等账本文件名——**另立**，不与 scrub 的 `_scrub.jsonl` 混用一个文件。
#: 为什么必须分开：两条链的 `op` 语义与「已处置」判据不同，混写会让任一侧的
#: `_handled()` 把对方的记录读成自己的历史（本地既有教训：账本共用一个 jsonl
#: ⇒ 幂等判据跨链串味，A 链的处置让 B 链误判为「已处理」而静默跳过）。
SINK_LEDGER = "_sink.jsonl"

#: 降层目标层——**固定为 contextual**（对应「还没定型、先降到上下文层」）。
#: 为什么不写进策略文件：`demote_layers` 是**源层白名单**（允许从哪些层挑候选），
#: 与「降到哪一层」是两件事；目标层属于本模块的处置口径，故为模块级常量单点。
DEMOTE_TO_LAYER = "contextual"

#: 降层后生命周期的目标状态（lifecycle.STATES 里的降权态）。
DEMOTE_STATE = "demoted"

#: trash 目录名——与 `mdcos.MdCGOS.TRASH`（mdcos.py:921）同值；本模块**不新建
#: 目录**，只按 cg.trash_dir / 本常量定位（建目录归 cg 构造面）。另立常量的
#: 理由是「本模块不得依赖 mdcos 的类属性」：sink 是策略与处置面，不 import
#: 引擎——只调引擎的公开方法（忘了这条就会把 sink 拖进引擎的导入图里）。
TRASH_REL_DIR = "trash"

#: 判据名——返回体的 skip 原因按这四条归因，保证「谁拦下的」可分辨。
CRITERIA = ("layer", "stale", "access_count", "importance")
#: 每个判据对应的策略键（用于 skip 记录里回填阈值，便于人读）。
CRITERION_POLICY_KEY = {
    "layer": "demote_layers",
    "stale": "sink_days",
    "access_count": "keep_access_count",
    "importance": "protected_importance",
}


# 生效条件：恒返回 cg.root 下账本文件 SINK_LEDGER 的绝对路径（cg 无 root 属性时按空串处理，得相对路径，不抛异常）。
def ledger_path(cg) -> str:
    """幂等账本路径（`<root>/_sink.jsonl`）——与 scrub 各用各的文件。"""
    return os.path.join(str(getattr(cg, "root", "") or ""), SINK_LEDGER)


# 生效条件：把一条记录（补 t 与 op 后）append 到账本；append_jsonl 抛任何异常都被吞掉（账本不可写不得阻断处置链），恒返回补好的记录 dict。
def _log(cg, op: str, **rec) -> dict:
    """追加一条账本记录（写法对齐 scrub._log；**文件不同**）。"""
    rec = dict(rec, t=time.time(), op=op)
    try:
        from .fsutil import append_jsonl
        append_jsonl(ledger_path(cg), rec)
    except Exception:                                   # noqa: BLE001 —— 记账失败不阻断
        pass
    return rec


# 生效条件：恒返回本账本里所有 op=='demote' 且 ok 为真的 node_id 集合；账本不存在、读失败或无非此类记录时返回空集（read_jsonl 缺失文件返回空），恒不抛异常。
def _handled(cg) -> set:
    """已处置过的 node_id：**审计即状态**，保证重复调用幂等。"""
    out = set()
    try:
        from .fsutil import read_jsonl
        for rec in list(read_jsonl(ledger_path(cg))):
            if rec.get("op") == "demote" and rec.get("ok"):
                nid = rec.get("node_id")
                if nid:
                    out.add(nid)
    except Exception:                                   # noqa: BLE001 —— 账本读不出＝无历史
        return set()
    return out


# 生效条件：value 为 int/float 且非 bool 时返回 float(value)；为 str 时先试 float(value) 成功即返回（epoch 数字串），否则试 ISO8601（含尾部 Z）解析为 epoch 秒返回；其余（None/空串/解析失败/非法类型）返回 None——**None 表示「无有效时间」，与 0.0（1970 纪元）区分**。
def _epoch(value):
    """把 `last_access` 归一成 epoch 秒 → float | None。

    真实形态**两种都有**（实读确认）：
      · 数值 epoch 秒 —— `fold_access_records`（mdcos.py:973；R-101 裁定后
        该接口落在 `MdCGOS` 子类，不再在 mdcg.py）与
        `compact_access`（mdcg.py:7219）写的就是 `float`/`int`；`add()` 落盘
        的初值是 `0`（int，falsy）。
      · ISO8601 串 —— 早期/外部写入面留下的形态（含尾部 `Z` 与 `+08:00`）。
    兼容必须两者都吃下：只认数值形态时，ISO 形态的节点会被读成「无时间」而
    **静默落选或静默入选**——「候选永远为空」与「真的没有候选」同形，正是
    本仓反复登记的那类不可诊断缺陷。
    数值 0（纪元）按「有值但很旧」处理：它确实是 1970 年，会自然落进 stale。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        iso = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            dt = datetime.datetime.fromisoformat(iso)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


# 生效条件：value 能转 float（非 bool）时返回该 float；转换抛 TypeError/ValueError 或值为 bool 时返回 fallback——用于 access_count / importance 的容错取值。
def _num(value, fallback=0.0):
    """数值容错取值：坏形状一律回落 fallback（不抛、不猜）。"""
    if isinstance(value, bool):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


# 生效条件：cg 的 index 为真且其 "nodes" 为真时返回该 dict，否则返回 {}——只读盘点面与 scrub._nodes 同口径。
def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


# 生效条件：传入 (节点 id, 命中判据名, 该判据的实际值, 对应策略阈值) 时恒返回一条 skip 记录 dict（五键：id/blocked_by/value/threshold/detail），供 candidates 返回体逐条陈列；恒不抛异常。
def _skip(node_id, blocked_by, value, threshold, detail=""):
    """一条「被拦下」记录——**逐条留痕**，杜绝静默丢弃。"""
    return {"id": node_id, "blocked_by": blocked_by, "value": value,
            "threshold": threshold, "detail": detail}


# 生效条件：只读盘点沉底候选。policy 为 None 时经 load_policy() 取生效策略（读真实 data/lifecycle_policy.json，source='default_file'）；now 为 None 时取当前时间。对 index["nodes"] 中每个节点按四条判据（层∈demote_layers / now-last_access>sink_days*86400 / access_count<keep_access_count / importance<protected_importance）依次短路判定：四条全过 ⇒ 进 candidates；任一条不过 ⇒ 进 skipped 并记 blocked_by=该判据名与实测值与阈值。另外受保护节点（protect.is_protected 为真）与已命中幂等账本（_handled）的节点分别归入 excluded_protected / already_handled，**两者都不进 skipped**（它们不是「判据没过」，是「按定义不参与」）。恒返回 dict（candidates/skipped/excluded_protected/already_handled/counts/policy/now/ledger），**只读**：不写盘、不改层、不写账本；单节点读 fm 抛异常时把该节点记入 skipped 的 detail（不中断整批）。
def candidates(cg, *, now=None, policy=None) -> dict:
    """沉底候选**只读**盘点 → dict（**不删任何节点、不写任何文件**）。

    判据四条 AND（依次短路，**第一条不过的判据名即 blocked_by**）：
        ① 所在层 ∈ policy['demote_layers']
        ② now - last_access > sink_days * 86400
        ③ access_count < keep_access_count
        ④ importance < protected_importance

    返回体：
        candidates         —— 通过四条判据的 id 列表（升序，便于断言）
        skipped            —— 被判据拦下的逐条 [{id, blocked_by, value,
                              threshold, detail}]
        excluded_protected —— 受保护节点（skip 与 protected 两回事）
        already_handled    —— 已命中账本、不再重复处置
        counts             —— 各桶计数 + by_criterion（按判据归因的拦截数）
        policy / now / ledger —— 本次判据用的实际策略、基准时间、账本路径

    为什么**必须回填逐条跳过原因**：只返回候选列表时，「候选为空」与
    「有 100 个节点但全被 importance 拦住」在调用方看来**完全同形**——前者是
    正常静默，后者是策略阈值配歪了，处置面该做的事截然相反。故拦下的每一条
    都要带着「谁的阈值、实测多少」一起返回。
    """
    pol = load_policy() if policy is None else policy
    base_now = float(now if now is not None else time.time())
    demote_layers = list(pol.get("demote_layers") or [])
    sink_days = _num(pol.get("sink_days"), 0.0)
    keep_access = _num(pol.get("keep_access_count"), 0.0)
    prot_importance = _num(pol.get("protected_importance"), 1.0)
    window = sink_days * 86400.0

    try:
        from . import protect
    except Exception:                                   # noqa: BLE001 —— 保护闸拿不到 ⇒ 全员按受保护处理
        protect = None

    done = _handled(cg)
    out = {"candidates": [], "skipped": [], "excluded_protected": [],
           "already_handled": [], "counts": {}, "by_criterion": {},
           "policy": pol, "now": base_now, "ledger": ledger_path(cg)}

    for node_id, entry in sorted(_nodes(cg).items()):
        if node_id in done:
            # 已处置：既不是候选也不是「判据没过」，单列一桶
            out["already_handled"].append(node_id)
            continue

        reason = ""
        if protect is not None:
            try:
                prot, reason = protect.is_protected(cg, node_id)
            except Exception as exc:                    # noqa: BLE001
                prot, reason = True, "保护判定异常：%s" % type(exc).__name__
            if prot:
                out["excluded_protected"].append({"id": node_id, "reason": reason})
                continue

        entry = entry or {}
        try:
            fm = (cg.get(node_id) or {}).get("frontmatter") or {}
        except Exception as exc:                        # noqa: BLE001 —— 单条读失败不中断整批
            out["skipped"].append(_skip(
                node_id, "read_error", None, None,
                "读节点失败：%s: %s" % (type(exc).__name__, exc)))
            continue
        # 索引条目缺键时用 fm 兜底（两者在役进程可能不同代际）
        layer = fm.get("layer") or entry.get("layer") or ""

        if layer not in demote_layers:
            out["skipped"].append(_skip(
                node_id, "layer", layer, demote_layers,
                "层不在 demote_layers（非候选层，不参与沉底）"))
            continue

        raw_last = fm.get("last_access", entry.get("last_access"))
        last = _epoch(raw_last)
        if last is None:
            out["skipped"].append(_skip(
                node_id, "stale", None, sink_days,
                "last_access 缺失或形态不可解析：%r（无有效时间 ⇒ 不判沉底）"
                % (raw_last,)))
            continue
        idle_days = (base_now - last) / 86400.0
        if not ((base_now - last) > window):
            out["skipped"].append(_skip(
                node_id, "stale", round(idle_days, 3), sink_days,
                "闲置 %.3f 天，未超过 sink_days=%s" % (idle_days, sink_days)))
            continue

        acc = _num(fm.get("access_count", entry.get("access_count")), 0.0)
        if not (acc < keep_access):
            out["skipped"].append(_skip(
                node_id, "access_count", int(acc), keep_access,
                "access_count 已达 keep_access_count，免疫沉底"))
            continue

        imp = _num(fm.get("importance"), 0.0)
        if not (imp < prot_importance):
            out["skipped"].append(_skip(
                node_id, "importance", imp, prot_importance,
                "importance 已达 protected_importance 门槛"))
            continue

        out["candidates"].append(node_id)

    by_criterion = {}
    for rec in out["skipped"]:
        key = rec["blocked_by"]
        by_criterion[key] = by_criterion.get(key, 0) + 1
    out["candidates"].sort()
    out["by_criterion"] = by_criterion
    out["counts"] = {
        "nodes": len(_nodes(cg)),
        "candidates": len(out["candidates"]),
        "skipped": len(out["skipped"]),
        "excluded_protected": len(out["excluded_protected"]),
        "already_handled": len(out["already_handled"]),
        "by_criterion": by_criterion,
    }
    return out


# 生效条件：实修/预演沉底降层。ids 为 None 时取 candidates(cg, now=now, policy=policy)['candidates']；ids 非空时按传入清单处置（不重跑判据，便于精确复现与坏 id 测试）。dry_run=True（**默认值**，与 decontaminate 同款纪律）时只核对不写盘：不调 _move_layer、不调 set_state、不写账本、返回 body 里 applied 恒为空。dry_run=False 时逐条：① protect.is_protected 为真 ⇒ 记入 skipped_protected 并 **continue**（层不变）② 节点取不到 ⇒ 记入 errors 并 continue ③ cg._move_layer(nid, DEMOTE_TO_LAYER, reason=...) 搬层（走引擎唯一正路：层闸/保护闸/demotion 字段/N137 完整条目重 _stage）④ cg.set_state(nid, DEMOTE_STATE, reason=..., actor=actor) 推进生命周期 ⑤ 写账本 op='demote' ok=True。**单条异常一律吞成该条的 error 记进 errors，绝不让整批中断**。恒返回 dict（n_candidates/applied/skipped_protected/already_handled/errors/dry_run/moved/state），**永不删除任何节点**。
def apply_demote(cg, *, ids=None, dry_run=True, actor="sink", policy=None,
                 override=False) -> dict:
    """把沉底候选**降层**到 contextual 并推进生命周期 → dict。

    dry_run=True（**默认**）只预演：不搬层、不改状态、不写账本 —— 默认值必须
    是 True，与既有 `decontaminate` 同款纪律（实修是不可逆的文件搬迁，默认
    动作绝不能是它）；要真动手必须显式传 `dry_run=False`。

    逐条实修路径（顺序即语义）：
        ① `protect.is_protected` 复核 —— 盘点与实修之间节点可能已被打上保护位，
           故**不能**信任盘点结果，必须在此再判一次；为真则记 skipped_protected
           并 continue（层一动都不动）。
        ② `cg._move_layer(nid, DEMOTE_TO_LAYER, reason=...)` —— 降层的**唯一
           正路**（越界层抛 ValueError / 同层返回 None / 内部走
           protect.require_layer + guard_move / 写 fm["demotion"] / 搬文件 /
           按 N137 重 _stage 完整条目，连带 access_count 与 last_access）。
           本函数**绝不自己搬文件、绝不自己改 frontmatter**。
        ③ `cg.set_state(nid, "demoted", ...)` —— 生命周期推进（唯一推进入口，
           非法迁移走负路由返回 ok=False 而不抛）。
        ④ 写账本 `op='demote', ok=True` —— 幂等凭据。

    **单条异常必须吞成该条的 error**：整批里一条坏 id / 一个不可写节点不该
    让其余几十条正当处置全部回滚（那是「一条烂鱼换掉整批」）；但错误必须
    逐条可见，不许降级成静默跳过。

    返回体：
        n_candidates      —— 本次拿到的候选条数（ids 显式传入时即 len(ids)）
        applied           —— 真正成功的 id 列表
        skipped_protected —— 受保护而跳过的 id（附 reason）
        already_handled   —— 账本里已有、本次未重复处置的 id
        errors            —— 逐条 [{id, error}]（**绝不中断整批**）
        dry_run           —— 本次是否只预演（回显，便于调用方断言）
        moved / state     —— 逐条处置结果明细（含 _move_layer 返回值）
    """
    pol = load_policy() if policy is None else policy
    ids_in = ids is not None
    if ids is None:
        picked = candidates(cg, now=None, policy=pol)["candidates"]
    else:
        picked = [str(x) for x in ids]

    body = {"n_candidates": len(picked), "applied": [], "skipped_protected": [],
            "already_handled": [], "errors": [], "dry_run": bool(dry_run),
            "moved": {}, "state": {}, "policy": pol,
            "ledger": ledger_path(cg), "ids_supplied": ids_in}
    if dry_run:
        # 预演：连保护复核都不做（那是写面前置），只把「打算怎么做」回显出来。
        body["planned"] = [{"id": nid, "to_layer": DEMOTE_TO_LAYER,
                            "to_state": DEMOTE_STATE} for nid in picked]
        return body

    try:
        from . import protect
    except Exception:                                   # noqa: BLE001
        protect = None

    done = _handled(cg)
    for nid in picked:
        if nid in done:
            body["already_handled"].append(nid)
            continue
        try:
            if protect is not None:
                prot, why = protect.is_protected(cg, nid)
                if prot:
                    body["skipped_protected"].append({"id": nid, "reason": why})
                    continue
            node = cg.get(nid)
            if not node:
                # 不存在 / 取不回：逐条记错，不中断整批
                body["errors"].append({"id": nid, "error": "node_not_found"})
                continue
            reason = "sink:last_access>%sd" % (pol.get("sink_days"),)
            mv = cg._move_layer(nid, DEMOTE_TO_LAYER, reason=reason)
            body["moved"][nid] = mv
            st = cg.set_state(nid, DEMOTE_STATE, reason=reason, actor=actor,
                              override=override)
            body["state"][nid] = st
            if st.get("ok") is False:
                # 状态没推进：层已搬但状态未变，如实记错（不回滚搬迁——
                # 回滚会再动一次文件，风险大于收益；错误可见即足够）
                body["errors"].append(
                    {"id": nid, "error": "set_state:%s" % st.get("error")})
            body["applied"].append(nid)
            _log(cg, "demote", node_id=nid, ok=True,
                 from_layer=(mv or {}).get("from"),
                 to_layer=DEMOTE_TO_LAYER, to_state=DEMOTE_STATE,
                 reason=reason, actor=actor)
        except Exception as exc:                        # noqa: BLE001 —— 单条吞错，整批继续
            body["errors"].append(
                {"id": nid, "error": "%s: %s" % (type(exc).__name__, exc)})
            _log(cg, "demote", node_id=nid, ok=False,
                 error="%s: %s" % (type(exc).__name__, exc), actor=actor)

    body["counts"] = {
        "n_candidates": body["n_candidates"],
        "applied": len(body["applied"]),
        "skipped_protected": len(body["skipped_protected"]),
        "already_handled": len(body["already_handled"]),
        "errors": len(body["errors"]),
    }
    return body


# --------------------------------------------------------------------------
# ③ trash 候选盘点（只读） / 进 trash 实修
# --------------------------------------------------------------------------

#: trash 判据名——与 CRITERIA 分开另立：两条链的**第一道闸不同**
#: （沉底问「在哪层」、进 trash 问「降过层没有」），共用一份判据名会让
#: `by_criterion` 的归因在两条链之间串味。
TRASH_CRITERIA = ("demoted", "stale", "access_count", "importance")
#: 每个 trash 判据对应的策略键（回填阈值便于人读）。
TRASH_CRITERION_POLICY_KEY = {
    "demoted": "trash_days",
    "stale": "trash_days",
    "access_count": "keep_access_count",
    "importance": "protected_importance",
}


# 生效条件：fm 为节点 frontmatter、entry 为同名索引条目（可为 None/{}）时，返回 (是否已降过层:bool, 判据形态名:str)；命中顺序为 frontmatter.demotion（dict 且非空）→ frontmatter.demotion_at → 索引条目 demotion（同款）→ frontmatter.demotion_reason 非空 → (层已是 contextual 且存在 legacy 降层痕迹)，皆不命中返回 (False, "")；恒不抛异常。
def _demoted(fm, entry):
    """「已降过层」的**形态单点** → `(bool, 形态名)`。

    为什么**不看 `demote_layers`**：那条键是 sink/candidates 的**源层白名单**
    （允许从哪里挑沉底候选），而本函数问的是「这个节点是否**已经**被降过层」。
    「降出」与「降过」是两件事——降过层的节点必然**不在** demote_layers 里
    （它已经搬到 contextual 了），拿源层白名单当判据会得到恒假的候选集，
    且与 `demote_layers` 的语义（"允许降出"）直接冲突。

    为什么**多形态都认**：真实库里 contextual 层的节点有三个来源——①
    `_move_layer` 降下来的（带 `fm["demotion"]`）② `add(layer="contextual")`
    直接写进上下文档的 ③ 早期无 `demotion` 字段的旧数据。形态名如实回传，
    让调用方能分辨自己看到的是哪一种；只在**有降层痕迹**时才认，绝不把
    「住在 contextual」本身当成「降过层」（那样会把直接写进上下文层的节点
    误判成已降层）。
    """
    fm = fm or {}
    entry = entry or {}
    dem = fm.get("demotion")
    if isinstance(dem, dict) and dem:
        return True, "frontmatter.demotion"
    at = fm.get("demotion_at")
    if isinstance(at, dict) and at:
        return True, "frontmatter.demotion_at"
    edem = entry.get("demotion")
    if isinstance(edem, dict) and edem:
        return True, "index.demotion"
    if str(fm.get("demotion_reason") or "").strip():
        return True, "frontmatter.demotion_reason"
    if (str(fm.get("layer") or entry.get("layer") or "") == DEMOTE_TO_LAYER
            and str(entry.get("demotion_state") or fm.get("demotion_state")
                    or fm.get("lifecycle_state") or "") == DEMOTE_STATE):
        return True, "layer+state"
    return False, ""


# 生效条件：恒返回本账本里所有 op=='trash' 且 ok 为真的 node_id 集合；账本不存在、读失败或无非此类记录时返回空集，恒不抛异常。与 _handled（只认 op=='demote'）**分开**：两条链的「已处置」互不相认。
def _handled_trash(cg) -> set:
    """已进过 trash 的 node_id（幂等读）——与 `_handled` 同族但**另一个 op**。"""
    out = set()
    try:
        from .fsutil import read_jsonl
        for rec in list(read_jsonl(ledger_path(cg))):
            if rec.get("op") == "trash" and rec.get("ok"):
                nid = rec.get("node_id")
                if nid:
                    out.add(nid)
    except Exception:                                   # noqa: BLE001 —— 读不出＝无历史
        return set()
    return out


# 生效条件：只读盘点进 trash 候选。policy 为 None 时经 load_policy() 取生效策略；now 为 None 时取当前时间。对 index["nodes"] 中每个节点按五条判据（① 已降过层（_demoted 为真）② now-last_access>trash_days*86400 ③ access_count<keep_access_count ④ importance<protected_importance ⑤ 未命中幂等账本）依次短路判定：五条全过 ⇒ 进 candidates；①~④ 任一条不过 ⇒ 进 skipped 并记 blocked_by=该判据名与实测值/阈值；⑤ 不过 ⇒ 进 already_handled。受保护节点（protect.is_protected 为真）进 excluded_protected。**只读**：不写盘、不移文件、不写账本；单节点读失败记入 skipped 的 detail 而不中断整批。
def trash_candidates(cg, *, now=None, policy=None) -> dict:
    """trash 候选**只读**盘点 → dict（**不删任何节点、不写任何文件**）。

    判据五条 AND（依次短路，**第一条不过的判据名即 blocked_by**）：
        ① 已降过层（`fm["demotion"]` 存在，或其它降层痕迹形态）—— 这是
           「降层**之后**」的前置：没降过层的节点**不是** trash 候选，
           它们该先走 `candidates()`／`apply_demote()`。
        ② now - last_access > trash_days * 86400 —— 与 sink_days **串联**：
           先沉底、再降层，降层后再等 trash_days 天仍未被引用才进 trash。
        ③ access_count < keep_access_count（与 sink 同口径：用过三次以上算在役）
        ④ importance < protected_importance
        ⑤ 未命中幂等账本（op='trash'）

    返回体：candidates / skipped（逐条含 blocked_by/value/threshold/detail）
    / excluded_protected / already_handled / counts / by_criterion / policy
    / now / ledger / criteria。

    为什么受保护节点**单列一桶**而不进 skipped：它们不是「判据没过」，而是
    「按定义不参与处置」——把两者的计数混在一起，会让「某条判据配歪了、
    拦下 100 个」与「100 个都受保护、本该如此」在账面上同形。
    """
    pol = load_policy() if policy is None else policy
    base_now = float(now if now is not None else time.time())
    trash_days = _num(pol.get("trash_days"), 0.0)
    keep_access = _num(pol.get("keep_access_count"), 0.0)
    prot_importance = _num(pol.get("protected_importance"), 1.0)
    window = trash_days * 86400.0

    try:
        from . import protect
    except Exception:                                   # noqa: BLE001 —— 保护闸拿不到 ⇒ 全员按受保护处理
        protect = None

    done = _handled_trash(cg)
    out = {"candidates": [], "skipped": [], "excluded_protected": [],
           "already_handled": [], "counts": {}, "by_criterion": {},
           "policy": pol, "now": base_now, "ledger": ledger_path(cg),
           "criteria": list(TRASH_CRITERIA)}

    for node_id, entry in sorted(_nodes(cg).items()):
        entry = entry or {}
        try:
            fm = (cg.get(node_id) or {}).get("frontmatter") or {}
        except Exception as exc:                        # noqa: BLE001 —— 单条读失败不中断整批
            out["skipped"].append(_skip(
                node_id, "read_error", None, None,
                "读节点失败：%s: %s" % (type(exc).__name__, exc)))
            continue

        # ① 已降过层（「降层之后」的前置；没降过层的该先走 sink/candidates）
        is_demoted, form = _demoted(fm, entry)
        if not is_demoted:
            out["skipped"].append(_skip(
                node_id, "demoted", False, DEMOTE_TO_LAYER,
                "未降过层（层=%r，无降层痕迹）⇒ 不是 trash 候选，"
                "应先走 sink/candidates 沉底降层" % (fm.get("layer") or entry.get("layer"),)))
            continue

        # ② 降层后仍长期未被引用（时间窗）
        raw_last = fm.get("last_access", entry.get("last_access"))
        last = _epoch(raw_last)
        if last is None:
            out["skipped"].append(_skip(
                node_id, "stale", None, trash_days,
                "last_access 缺失或形态不可解析：%r（无有效时间 ⇒ 不判进 trash）"
                % (raw_last,)))
            continue
        idle_days = (base_now - last) / 86400.0
        if not ((base_now - last) > window):
            out["skipped"].append(_skip(
                node_id, "stale", round(idle_days, 3), trash_days,
                "降层后闲置 %.3f 天，未超过 trash_days=%s" % (idle_days, trash_days)))
            continue

        # ③ 仍未被引用（与 sink 同口径）
        acc = _num(fm.get("access_count", entry.get("access_count")), 0.0)
        if not (acc < keep_access):
            out["skipped"].append(_skip(
                node_id, "access_count", int(acc), keep_access,
                "access_count 已达 keep_access_count，仍被引用 ⇒ 免疫进 trash"))
            continue

        # ④ 重要度
        imp = _num(fm.get("importance"), 0.0)
        if not (imp < prot_importance):
            out["skipped"].append(_skip(
                node_id, "importance", imp, prot_importance,
                "importance 已达 protected_importance 门槛"))
            continue

        # 受保护 / 已处置：两者都**不是**「判据没过」，单列各自的桶
        if node_id in done:
            out["already_handled"].append(node_id)
            continue
        if protect is not None:
            reason = ""
            try:
                prot, reason = protect.is_protected(cg, node_id)
            except Exception as exc:                    # noqa: BLE001
                prot, reason = True, "保护判定异常：%s" % type(exc).__name__
            if prot:
                out["excluded_protected"].append({"id": node_id, "reason": reason})
                continue

        out["candidates"].append(node_id)

    by_criterion = {}
    for rec in out["skipped"]:
        key = rec["blocked_by"]
        by_criterion[key] = by_criterion.get(key, 0) + 1
    out["candidates"].sort()
    out["by_criterion"] = by_criterion
    out["counts"] = {
        "nodes": len(_nodes(cg)),
        "candidates": len(out["candidates"]),
        "skipped": len(out["skipped"]),
        "excluded_protected": len(out["excluded_protected"]),
        "already_handled": len(out["already_handled"]),
        "by_criterion": by_criterion,
    }
    return out


# 生效条件：实修/预演进 trash。ids 为 None 时取 trash_candidates(cg, now=now, policy=policy)['candidates']；ids 非空时按传入清单处置（不重跑判据）。dry_run=True（**默认值**）时只核对不写盘：不调 cg.forget、不写账本、返回体 trashed 恒为空。dry_run=False 时逐条：① protect.is_protected 为真 ⇒ 记入 skipped_protected 并 continue（节点一动不动）② cg.get 取不到 ⇒ 记入 errors 并 continue ③ cg.forget(nid, reason='sink:降层后 <天数>d 仍未被引用', override=False) ⇒ 走 trash 目录搬迁 + deletions_log + 索引摘除的**唯一正路** ④ 返回 ok 且 tombstone 存在 ⇒ 记入 trashed 并写账本 op='trash' ok=True；返回 moved_to=='autonomy_forbidden' 或 ok=False ⇒ 记入 blocked_by_guard（附 reason/error）⑤ 抛 protect.ProtectionError ⇒ 记入 blocked_by_guard（guard='protect.guard_forget'）。**单条异常一律吞成该条的 error 记进 errors，绝不让整批中断**。恒返回 dict（n_candidates/applied/skipped_protected/already_handled/errors/dry_run/trashed/blocked_by_guard/counts）。
def apply_trash(cg, *, ids=None, dry_run=True, actor="sink", policy=None,
                override=False) -> dict:
    """把 trash 候选**送进 trash** → dict（软删，**绝不物理 unlink**）。

    dry_run=True（**默认**）只预演：不调 `cg.forget`、不写账本 —— 默认值
    必须是 True（进 trash 是真实文件搬迁，默认动作绝不能是它）。

    进 trash 的**唯一正路**是 `cg.forget`（mdcos.py:4596）：
        `_forget_qualify`（索引代际感知 → not_found → `protect.guard_forget`）
        → `_forget_apply`（`publish(src, trash_dir/<id>.md)` → 写
        `deletions_log`（含 t/id/hash/reason/actor/trash）→ `_unstage`
        → 缓存失效 → `_audit("forget", …)`），返回
        `{"ok": True, "id": …, "tombstone": <内容签名>}`。
    本模块**绝不** `os.remove` / `os.unlink` 节点文件：搬进 trash 目录 +
    写删除清单是**可 restore** 的软删，物理 unlink 是不可恢复的硬删——
    后者一旦落进生命周期链，「策略配歪」就从「可回滚的误判」升级成
    「数据真没了」。故 gate 里有一条源码扫描断言把这两个 API 钉死在模块外。

    `override=False` 是**这条链的语义核心**，不是省事：受保护节点（self/
    anchor 层、显式保护位、按分自动保护）必须被 `protect.guard_forget`
    **拦下并如实记为 not_trashed**，绝不许本函数用 override 掀开保护闸
    ——那是「保护位在生命周期链里失效」，比漏删危险得多。

    逐条实修路径（顺序即语义）：
        ① `protect.is_protected` 复核 —— 盘点与实修之间节点可能已被打上保护位，
           故**不能**信任盘点结果，必须再判一次；为真则记 skipped_protected
           并 continue（节点文件一动不动）。本函数因此不需要 import
           `ProtectionError`：保护节点在**调用 forget 之前**就已被摘出，
           `guard_forget` 是第二道闸（防盘点后新打位）而不是唯一一道。
        ② `cg.get(nid)` 取不到 ⇒ 记 errors（不存在 / 已不可读），continue。
        ③ `cg.forget(nid, reason=…, override=override)` ⇒ 唯一正路。
        ④ `ok` 且 tombstone 存在 ⇒ 进 trashed + 写账本。

    **单条异常必须吞成该条的 error**：一条坏 id / 一个不可写节点不该让其余
    几十条正当处置全部中断；但错误必须逐条可见，不许降级成静默跳过。

    返回体：
        n_candidates      —— 本次拿到的候选条数
        applied           —— 索引（与 trashed 一致，便于习惯 candidates 口径的调用方）
        trashed           —— 逐条 [{id, tombstone, reason, trash}]（**tombstone 是成功凭据**）
        skipped_protected —— 受保护而跳过的 id（附 reason）
        blocked_by_guard  —— 被保护/档位闸拦下的 [{id, guard, error, not_trashed}]
                             （**not_trashed 的如实原因**，与 errors 分开）
        already_handled   —— 账本里已有、本次未重复处置的 id
        errors            —— 逐条 [{id, error}]（**绝不中断整批**）
        dry_run           —— 本次是否只预演（回显，便于调用方断言）
    """
    pol = load_policy() if policy is None else policy
    ids_in = ids is not None
    if ids is None:
        picked = trash_candidates(cg, now=None, policy=pol)["candidates"]
    else:
        picked = [str(x) for x in ids]

    body = {"n_candidates": len(picked), "applied": [], "trashed": [],
            "skipped_protected": [], "blocked_by_guard": [],
            "already_handled": [], "errors": [], "dry_run": bool(dry_run),
            "policy": pol, "ledger": ledger_path(cg), "ids_supplied": ids_in,
            "trash_dir": trash_dir(cg)}
    if dry_run:
        # 预演：连保护复核都不做（那是写面前置），只把「打算怎么做」回显出来。
        body["planned"] = [{"id": nid, "op": "forget", "to_trash": True}
                           for nid in picked]
        return body

    try:
        from . import protect
    except Exception:                                   # noqa: BLE001
        protect = None

    done = _handled_trash(cg)
    for nid in picked:
        if nid in done:
            body["already_handled"].append(nid)
            continue
        try:
            if protect is not None:
                prot, why = protect.is_protected(cg, nid)
                if prot:
                    body["skipped_protected"].append({"id": nid, "reason": why})
                    continue
            if not cg.get(nid):
                body["errors"].append({"id": nid, "error": "node_not_found"})
                continue
            node = cg.get(nid) or {}
            fm = node.get("frontmatter") or {}
            last = _epoch(fm.get("last_access"))
            days = None if last is None else round(
                (float(time.time()) - last) / 86400.0, 3)
            reason = "sink:降层后 %sd 仍未被引用" % (days,)
            res = cg.forget(nid, reason=reason, override=override)
            res = res if isinstance(res, dict) else {"ok": False,
                                                     "error": "bad_result"}
            if res.get("ok") and res.get("tombstone"):
                rec = {"id": nid, "tombstone": res.get("tombstone"),
                       "reason": reason, "trash": rel_trash_path(cg, nid)}
                body["trashed"].append(rec)
                body["applied"].append(nid)
                _log(cg, "trash", node_id=nid, ok=True,
                     tombstone=res.get("tombstone"), reason=reason,
                     actor=actor, trash=rec["trash"], days=days)
                continue
            # 没进 trash：如实记「谁拦下的、为什么」，不静默跳过
            guard = res.get("moved_to") or "forget"
            body["blocked_by_guard"].append(
                {"id": nid, "guard": guard,
                 "error": str(res.get("error") or ""),
                 "not_trashed": "cg.forget 未搬入 trash：%s"
                                % (res.get("error") or res.get("moved_to") or res)})
            _log(cg, "trash", node_id=nid, ok=False, guard=guard,
                 error=str(res.get("error") or ""), actor=actor,
                 not_trashed=True)
        except Exception as exc:                        # noqa: BLE001 —— 单条吞错，整批继续
            err = "%s: %s" % (type(exc).__name__, exc)
            body["errors"].append({"id": nid, "error": err})
            _log(cg, "trash", node_id=nid, ok=False, error=err, actor=actor)

    body["counts"] = {
        "n_candidates": body["n_candidates"],
        "applied": len(body["applied"]),
        "trashed": len(body["trashed"]),
        "skipped_protected": len(body["skipped_protected"]),
        "blocked_by_guard": len(body["blocked_by_guard"]),
        "already_handled": len(body["already_handled"]),
        "errors": len(body["errors"]),
    }
    return body


# 生效条件：恒返回 cg.trash_dir 的绝对路径（cg 有 trash_dir 属性时取之）；cg 无该属性时按 TRASH_REL_DIR 常量与 cg.root 拼出（root 也拿不到时得相对路径），恒不抛异常——**只读**，不 makedirs、不建目录。
def trash_dir(cg) -> str:
    """trash 目录路径（**只读**，不建目录）——判定「搬没搬进去」的判据单点。"""
    got = getattr(cg, "trash_dir", None)
    if got:
        return str(got)
    return os.path.join(str(getattr(cg, "root", "") or ""), TRASH_REL_DIR)


# 生效条件：恒返回 trash 目录相对于 cg.root 的 posix 相对路径（形如 'trash/<id>.md'）；cg 无 root 时回落绝对路径，恒不抛异常——与 mdcos._forget_apply 写进 deletions_log 的 trash 字段同口径。
def rel_trash_path(cg, node_id) -> str:
    """trash 落点的**相对路径**（与 `deletions_log.trash` 字段同口径）。"""
    full = os.path.join(trash_dir(cg), "%s.md" % (node_id,))
    root = str(getattr(cg, "root", "") or "")
    if not root:
        return full.replace("\\", "/")
    return os.path.relpath(full, root).replace("\\", "/")
