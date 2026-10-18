# -*- coding: utf-8 -*-
"""条件空间闸（condspace）——写入链第一道「信息完整性」闸，可灰度。

背景（统一架构 v1.1 §2.4 / §9.1）：
    理论只承认「可认知信息」——条件空间 C 下可被观测、可被证据支持的断言。
    缺条件空间 = 断言脱离条件 = 0.0.1 所说的越界主张。故写入链应能识别它。

设计取舍（关键）：
    本闸**默认不阻断**。原因：现有全部调用方 payload 都没有 condition_space，
    一上线即强制等于拿全体写入方当实验品。故分三档：

        off      完全不介入（逐位回到接入前行为）
        observe  放行 + 记录缺失/不完整（默认；为后续强制积累覆盖率证据）
        enforce  缺失或不完整 → 短路 **REJECT 打回写入方**，不入审核队列、不落盘
                 （2026-10-18 修：原注释写「短路 DEFER 入审核队列」，与实现相反——
                  缺条件空间是作者责任，不该转嫁给裁决队列）

    三档用环境变量 MDCG_CONDGATE 切换，缺省 observe。

闸的身份：
    **字段域规范化 + 可观测性**，不做内容裁决（内容裁决归 audit）。
    因此它只碰 condition_space 一个键，绝不改写 content。

同槽定义（统一架构 v1.1 §9.1 V4/V5 的前置）：
    槽位键 = CCG 三要素（功能名 / 子功能 / 生效条件）归一化后的指纹。
    「同一信息的多份投影」= 同槽同值；「冲突」= 同槽异值。
    未按 CCG 写注释的内容没有槽位（返回 None）——不猜、不强行归类。
"""

import hashlib
import os
import re

__all__ = ["FOUR_DIMS", "mode", "normalize_condition_space", "slot_key",
           "before_hook", "stats", "reset_stats", "qualify",
           "QUALIFIED", "LEGACY_BLINDSPOT"]

#: 条件空间四维（0.0.1 信息条件性；3.1 四维定义）。键名与库内既有 fm 一致。
FOUR_DIMS = ("observation_position", "observation_tool",
             "time_window", "existence_constraint")

#: 键名别名 → 四维（2026-10-18 供给改造）。
#: 实测：库内已有作者按中文名填写（观测位置/观测工具/存在约束），
#: 因键名不匹配被判「缺失」——那不是没填，是**写法不被识别**。
#: 归一是供给改造的一部分，不改判据强度。
ALIASES = {
    "观测位置": "observation_position", "观测位": "observation_position",
    "观察位置": "observation_position",
    "观测工具": "observation_tool", "观测手段": "observation_tool",
    "时间窗口": "time_window", "时间窗": "time_window", "观测时间": "time_window",
    "存在约束": "existence_constraint", "存在条件": "existence_constraint",
    "物理约束": "existence_constraint",
}


def _canon_keys(cs):
    """把别名键归一为四维英文键；已是四维的保持不变；其余原样保留。"""
    if not isinstance(cs, dict):
        return {}
    out = {}
    for k, v in cs.items():
        canon = ALIASES.get(str(k).strip(), k)
        if canon in out and str(k) in ALIASES:
            continue          # 别名与正式名并存时以先出现者为准，不覆盖
        out[canon] = v
    return out


_CS_LINE = re.compile(r"^[ \t]*#[ \t]*条件空间[ \t]*[：:][ \t]*(.+?)[ \t]*$", re.M)
_CS_PAIR = re.compile(r"([^=＝：:；;]+?)\s*[=＝：:]\s*([^；;]+)")


QUALIFIED = "qualified"
LEGACY_BLINDSPOT = "legacy_blindspot"


def qualify(fm):
    """判定一条**已存在**的信息的资格姿态（P0-5 legacy 姿态）。

    **入参必须是节点的 frontmatter，不能是索引条目。**
    实测（2026-10-18）：索引条目共 42 个键但**不含 condition_space**，生产库
    31139 个节点里索引带该字段的数量为 **0**——条件空间只存在于节点文件 frontmatter。
    故传索引条目进来会恒判 legacy_blindspot，那是「数据在别处」而不是「判据有效」。
    这条同时说明 P0-5 的根因比「姿态未定义」更深：**检索面手里没有这个数据**，
    要用它必须逐条读文件（31139 节点不可接受）或把该字段写进索引（须单独权衡）。

    背景（外部评审第二份 P0-5）：库内 954/957 条存量无条件空间。检索命中它们时
    两种默认都不对——默认隐藏会一夜失去 99.3% 的记忆；默认照常返回则静默违反
    P1-1（无条件空间不得 ACCEPT）。

    故给出第三种姿态：**可读，但不得 ACCEPT**——返回本函数的判定，由调用方在
    结果上标注，而不是把节点藏起来或假装它合格。

    返回：
        qualified         四维齐全，可进入正常资格判定
        legacy_blindspot  条件空间缺失/不完整 → 应标 BLINDSPOT，且**不回填**
                          （从内容反推条件空间属于猜，违反 0.0.1）
    """
    if not isinstance(fm, dict):
        return LEGACY_BLINDSPOT
    cs = fm.get("condition_space")
    normalized, missing, _unknown = normalize_condition_space(cs)
    if normalized and not missing:
        return QUALIFIED
    return LEGACY_BLINDSPOT


def parse_condition_space_from_content(content):
    """从正文的「# 条件空间：...」一行解析出四维（2026-10-18 补）。

    背景：作者指南 v1 已声明这是**推荐写法**，但首版实现只认 condition_space
    字段，导致「按指南写」的样本照样被打回——文档承诺了、代码没做，属假承诺。
    本函数补上该解析，键名走 ALIASES 归一。

    写法：  # 条件空间：观测位置=X；观测工具=Y；存在约束=Z
    分隔：  维间用全/半角分号；键值用 = ／ ＝ ／ ： ／ :
    缺省：  解析不到的维度不填（不猜），time_window 仍由 autofill 补。
    """
    text = str(content or "")
    m = _CS_LINE.search(text)
    if not m:
        return {}
    body = m.group(1)
    out = {}
    for k, v in _CS_PAIR.findall(body):
        key = ALIASES.get(k.strip(), k.strip())
        if key in FOUR_DIMS and str(v).strip():
            out[key] = str(v).strip()
    return out


def autofill_time_window(cs, now=None):
    """time_window 缺失时用**系统时间**补 [now, now]（2026-10-18 使用者裁定）。

    诚实边界：这填的是「观测发生的时刻」，不是「有效期」。需要更宽有效期的
    作者应显式声明区间；本函数不替作者推测有效期（那是猜）。
    """
    import time as _t
    cs = dict(cs or {})
    tw = cs.get("time_window")
    if tw in (None, "", [], {}):
        n = _t.time() if now is None else float(now)
        cs["time_window"] = [n, n]
    return cs

ENV_MODE = "MDCG_CONDGATE"
MODES = ("off", "observe", "enforce")

_STATS = {"seen": 0, "complete": 0, "partial": 0, "missing": 0, "enforced": 0}


_WARNED_MODES = set()


def mode():
    """当前档位。非法值回落 observe（文档缺省），并**写一次 stderr 告警**。

    P0-3（外部评审 2026-10-18）：condgate 与 condaccept 曾对非法值回落**相反方向**
    （一个 fail-open 变不拦、一个 fail-closed 变全拦），且都静默。同一条写路径上
    两个闸方向相反又不告警，等于让操作者以为配置生效了。现统一为「回落文档缺省
    并显式告警」——方向仍按各自缺省（职责不同），但绝不静默。
    """
    raw = (os.environ.get(ENV_MODE) or "").strip().lower()
    if raw and raw not in MODES:
        if raw not in _WARNED_MODES:
            _WARNED_MODES.add(raw)
            import sys as _sys
            _sys.stderr.write(
                "[condgate] 非法档位 %r（可选 %s），回落文档缺省 observe\n"
                % (raw, "|".join(MODES)))
        return "observe"
    return raw or "observe"


def reset_stats():
    for k in _STATS:
        _STATS[k] = 0


def stats():
    """覆盖率读数（只读快照）。供观察期判断何时可转 enforce。"""
    return dict(_STATS)


def normalize_condition_space(cs):
    """规范化条件空间。

    返回 (normalized, missing_dims, unknown_keys)：
        normalized   仅含四维且值非空的子集（保持输入类型，字符串原样、其它原样）
        missing_dims 四维中缺失或值为空的维度名（按 FOUR_DIMS 顺序）
        unknown_keys 输入里不属于四维的键（不丢弃信息，交由调用方决定是否告警）

    非 dict 输入一律视为空（不猜结构）；None/空 dict 同样返回空 normalized。
    """
    cs = _canon_keys(cs)
    normalized = {}
    missing = []
    for k in FOUR_DIMS:
        v = cs.get(k)
        if isinstance(v, str):
            v = v.strip()
        if v in (None, "", [], {}):
            missing.append(k)
        else:
            normalized[k] = v
    unknown = [k for k in cs.keys() if k not in FOUR_DIMS]
    return normalized, missing, unknown


_CCG_FIELDS = (
    ("function", re.compile(r"^#\s*功能名\s*[：:]\s*(.+?)\s*$", re.M)),
    ("sub", re.compile(r"^#\s*子功能\s*[：:]\s*(.+?)\s*$", re.M)),
    ("when", re.compile(r"^#\s*生效条件\s*[：:]\s*(.+?)\s*$", re.M)),
)


def _norm_text(s):
    """槽位文本归一化：去 markdown 装饰、压空白、统一全半角冒号后的空格差异。"""
    s = str(s or "")
    for ch in ("*", "_", chr(96)):
        s = s.replace(ch, "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def slot_key(content):
    """CCG 三要素 → 槽位指纹。

    三要素任一缺失即返回 None：没有槽位的断言无法参与「同槽」判定，
    此时上游应退化为「按内容指纹去重」，而不是强行归槽（不猜）。
    """
    text = str(content or "")
    parts = {}
    for name, pat in _CCG_FIELDS:
        m = pat.search(text)
        if not m:
            return None
        parts[name] = _norm_text(m.group(1))
        if not parts[name]:
            return None
    raw = "\u0001".join(parts[k] for k in ("function", "sub", "when"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def before_hook():
    """返回可注册进 writepipe 的 before 拦截器。

    语义：返回 None = 放行（链继续）；返回 dict = 短路终态。
    """
    def _gate_condspace(ctx):
        m = mode()
        if m == "off":
            return None
        a = ctx["a"]
        # 供给改造（2026-10-18）：字段优先，缺失处由正文「# 条件空间：」行补齐，
        # 最后用系统时间补 time_window。三级来源都显式，不猜。
        from_field = _canon_keys(a.get("condition_space"))
        from_content = parse_condition_space_from_content(a.get("content"))
        merged = dict(from_content)
        merged.update({k: v for k, v in from_field.items() if v not in (None, "", [], {})})
        cs = autofill_time_window(merged)
        ctx["condspace_source"] = {
            "field_keys": sorted(from_field.keys()),
            "content_keys": sorted(from_content.keys()),
        }
        a["condition_space"] = cs
        normalized, missing, unknown = normalize_condition_space(cs)
        _STATS["seen"] += 1
        if not normalized:
            _STATS["missing"] += 1
            state = "missing"
        elif missing:
            _STATS["partial"] += 1
            state = "partial"
        else:
            _STATS["complete"] += 1
            state = "complete"

        ctx["condspace"] = {"state": state, "missing": missing,
                            "unknown": unknown, "mode": m}

        if m == "observe":
            return None

        # enforce：完整才放行；缺失/不完整一律短路（不落盘、入审核队列语义由调用方给）
        if state == "complete":
            a["condition_space"] = normalized
            return None
        _STATS["enforced"] += 1
        # 打回写入方（REJECT），不入审核队列——缺条件是作者的责任，不是裁决者的。
        return {
            "ok": False,
            "id": ctx.get("nid"),
            "committed": False,
            "moved_to": "rejected_condspace",
            "verdict": {"state": "REJECT", "kind": "condspace",
                        "basis": None,
                        "evidence": "条件空间%s；请补齐后重新提交" % ("缺失" if state == "missing" else "不完整"),
                        "detail": {"missing": missing, "unknown": unknown,
                                   "return_to": "author",
                                   "action": "resubmit_with_condition_space"}},
            "condspace": ctx["condspace"],
            "hint": ("写入被打回：断言必须声明条件空间四维 %s，当前缺失 %s。"
                     "补齐后重新提交；本条未入审核队列（不占用裁决资源）。"
                     % (list(FOUR_DIMS), missing)),
        }

    return _gate_condspace
