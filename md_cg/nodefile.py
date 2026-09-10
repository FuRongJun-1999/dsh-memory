# -*- coding: utf-8 -*-
"""md 认知图 · 节点文件格式（YAML-ish frontmatter + CCG 正文）

格式：
    ---
    id: node_x
    tags: ["a","b"]
    verification_basis: "compiler"   # 验证方式（frontmatter 侧）
    non_applicable_conditions: [...]  # 不适用条件
    ---
    # 功能名：...
    # 生效条件：...（**条件空间四槽声明的合成**——观测位置 ≠ 生效条件，不可省略）
    # 子功能：...
    # 执行：...
    # 验证方式：...（白箱要求"能被验证才能被信任"）
    # 不适用条件：...（白箱第 1 篇第 10 章从 28%→88% 的关键改进）
    正文

解析要点（原型代码 md_cg_prototype.py 的缺陷修复）：
原型用 `re.match(r"---\\n(.*?)\\n---\\n(.*)", txt, re.S)` 非贪婪匹配，正文里只要
出现一行 `---`（markdown 分隔线在知识卡里极常见）就会把正文前半截当成 frontmatter，
字段全丢。这里改为：frontmatter 的所有值都 JSON 序列化（因此不含裸换行），
只切「开头 --- 之后的第一个 \\n---\\n」，正文里的 --- 一律不参与切分。

CCG 要素的语义对应（白箱第 1 篇第 17 章）：
- 生效条件 → MARKS 第 2 行（**必须显式声明**；唯一合法来源见 `condition_space_text`）
- 子功能   → MARKS 第 3 行
- 执行     → MARKS 第 4 行
- 验证方式 → MARKS 第 5 行（frontmatter 同步存 verification_basis 做可查询化）
- 不适用条件 → MARKS 第 6 行（frontmatter 同步存 non_applicable_conditions）

第 1 行「功能名」是 markdown 风格的标题，作为可读标识保留（**结论即功能名本身**，
不进生效条件）。用户许可 MARKS 中内容可前置——故**顺序**不强制。

口径修正（本轮）：「生效条件可隐含」的旧许可已废止。**观测位置 ≠ 生效条件**——
生效条件是**整条条件空间声明的合成**，只能由 `condition_space` 四槽渲染；
拿 `observation_position` 单槽加前缀冒充，等于把坐标的一维当成整条生效条件。
故 CCG_REQUIRED == CCG_MARKS：6 行缺一不可，缺则补写、或按 q-3 判 BLINDSPOT。
"""
import json
import time

_DELIM = "---"
# 完整的 6 行 MARKS：功能名（标题）+ 5 要素（条件、子功能、执行、验证、不适用）。
# 「验证方式」与「不适用条件」是白箱的关键新增，缺则不可证 ACCEPT/REJECT。
CCG_MARKS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
# 门槛即全部 MARKS：原先「生效条件可隐含」的豁免已废止（观测位置 ≠ 生效条件，
# 见 `condition_space_text`）——生效条件必须由 condition_space 四槽合成显式声明，
# 不存在「常用条件默认省略」的合法情形。缺它即缺证据：补写，或判 BLINDSPOT。
CCG_REQUIRED = CCG_MARKS
# 外部验证基底的可取值（frontmatter.verification_basis）
#
# 分两档（口径：文科宽松、理科严格）：
#   · 可复现档（理科）：compiler / test / measurement / formal_proof / data
#     —— 要求可复算、可复现的证据
#   · 来源一致性档（文科）：textbook（人教版教材表述一致）/ public_kb（公开知识库一致）
#     —— 文科知识不是可复现的物理事实，以「权威来源表述一致」为足够基底
VERIFICATION_BASIS = ("compiler", "test", "measurement", "formal_proof", "data",
                      "textbook", "public_kb", "other")

#: 可复现档：理科断言必须落在这一档（复现证据）
REPRODUCIBLE_BASIS = ("compiler", "test", "measurement", "formal_proof", "data")
#: 来源一致性档：文科断言可用（来源表述一致即可）
CONSISTENCY_BASIS = ("textbook", "public_kb")


def dumps(frontmatter: dict, content: str) -> str:
    lines = [_DELIM]
    for k in sorted(frontmatter):
        v = frontmatter[k]
        # 一律 JSON 序列化：值内不会出现裸换行，切分才可靠；数字/字符串也保持可读
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append(_DELIM)
    body = content if content.endswith("\n") else content + "\n"
    return "\n".join(lines) + "\n" + body


def loads(text: str):
    """返回 (frontmatter dict, content str)。非法格式返回 ({}, 原文)。"""
    if not text.startswith(_DELIM + "\n"):
        return {}, text
    rest = text[len(_DELIM) + 1:]
    end = rest.find("\n" + _DELIM + "\n")
    if end < 0:
        return {}, text
    head, content = rest[:end], rest[end + len(_DELIM) + 2:]
    fm = {}
    for line in head.split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        try:
            fm[k] = json.loads(v)
        except ValueError:
            fm[k] = v
    return fm, content


def ccg_completeness(content: str) -> dict:
    """CCG 要素齐全度——白箱可审计性的量化指标。

    「生效条件」**不可隐含**：它不是条件空间的某一维，而是整条条件空间声明的
    合成（`condition_space_text`）。缺声明 = 缺证据，只能补写或判 BLINDSPOT，
    不能被「常用条件默认省略」静默掩盖。故 CCG_REQUIRED == CCG_MARKS，
    `complete` 与 `all_present` 同源；保留两个键只为不动既有调用面。
    """
    all_present = [m for m in CCG_MARKS if f"# {m}：" in content or f"# {m}:" in content]
    required_present = [m for m in CCG_REQUIRED
                        if f"# {m}：" in content or f"# {m}:" in content]
    return {
        "present": all_present,
        "required_present": required_present,
        # 完整 = 全部 MARKS 都在——这是资格判定的硬门槛
        "complete": len(required_present) == len(CCG_REQUIRED),
        # 全齐 = 与 complete 同源（CCG_REQUIRED == CCG_MARKS）
        "all_present": len(all_present) == len(CCG_MARKS),
        "ratio": len(required_present) / len(CCG_REQUIRED),
    }


def verification_basis_valid(fm: dict) -> bool:
    """frontmatter.verification_basis 是否落在可接受枚举里。"""
    vb = fm.get("verification_basis")
    if vb is None:
        return False
    return vb in VERIFICATION_BASIS


# ---- 骨架占位识别 ---------------------------------------------------------
#
# 迁移期生成的空壳节点，其「执行/子功能」是 `[学科·学段] 骨架锚点，内容待填充`
# 这类待填充标记，而**不是**已声明的事实。把它渲染成 `# 执行：` 正文行，等于把
# 「待填充」固化成事实，并会被词面召回命中——故一律排除，转待填充工单。
PLACEHOLDER_MARKERS = ("骨架锚点", "内容待填充", "待填充", "骨架节点")


def is_placeholder_text(value) -> bool:
    """占位标记的纯函数判定：空值或含占位标记 → 不可渲染为事实。

    只认**标记词**，不做语义猜测：宁可漏判（少写一行），不可误判（把真实的
    条件当成占位而丢弃）。
    """
    s = "" if value is None else str(value).strip()
    if not s:
        return True
    return any(m in s for m in PLACEHOLDER_MARKERS)


def has_non_applicable(content: str) -> bool:
    """是否声明了不适用条件——REJECT 路径成立的必要条件。

    没有不适用条件的节点在白箱下不能 REJECT（无法证明「不适用」），
    只能 ACCEPT 或 BLINDSPOT。这是第 1 篇第 10 章从 28%→88% 的关键。
    """
    return "# 不适用条件：" in content or "# 不适用条件:" in content


#: 负条件字段名——它是**反例声明**，不是召回键
NEG_FIELD = "不适用条件"


def positive_body(content: str) -> str:
    """剥离 `# 不适用条件：` 行后的正文——负条件不作召回键。

    不适用条件声明的是「什么时候**不**适用」，其触发词是反例。一旦把它当召回
    键，查询命中反例时节点反而被召回——**恰好在它不该适用的地方被召回**，属实
    质性错误。反例的正确去向是 `judge_qualification` 的 REJECT 路径（读
    `frontmatter.non_applicable_conditions`），而不是召回。

    只剥离真正的 CCG 行（以 `#` 开头且字段名匹配），避免误伤正文里恰好以
    「不适用条件」开头的普通句子。
    """
    keep = []
    for ln in (content or "").split("\n"):
        s = ln.strip()
        if s.startswith("#") and s.lstrip("#").strip().startswith(NEG_FIELD):
            continue
        keep.append(ln)
    return "\n".join(keep)


# ---- 条件空间 → 生效条件声明 -------------------------------------------------
#
# 口径修正（本模块是 condition_space → 文本的**唯一合成入口**）：
#   「生效条件」不是条件空间里的**某一维**，而是**整条条件空间声明**的合成。
#   拿 `condition_space.observation_position` 加个「观测位置：」前缀冒充生效条件，
#   等于把坐标的一维当成整条生效条件——**观测位置 ≠ 生效条件**。
#
# 理论依据（《智能的公理化基石》）：
#   C = (C_position, C_tool, C_time, C_existence)，
#   「任何有效知识都必须能够说明自己处在哪个条件空间中」。
#
# 载体与位置**同源合并**：`observation_position` 一个键同时承载「谁在观察」与
# 「在哪个尺度/视角」；机械拆成「载体X；位置X」两段会出现同值重复，故合并为
# 一段「载体/位置」输出，并保留未来新增独立 carrier 槽再拆分的扩展位。
# 结论不进生效条件：结论 = 功能名本身（MARKS 第 1 行）。

#: 四槽 → 声明段。顺序即渲染顺序（固定，不依赖 dict 插入顺序）
CONDITION_SLOTS = (
    ("observation_position", "载体/位置"),
    ("time_window", "时间"),
    ("observation_tool", "方法"),
    ("existence_constraint", "约束"),
)
#: 构成一条**完整**条件空间声明所必需的槽：缺任一 → 不构成生效条件
CONDITION_SLOTS_REQUIRED = tuple(k for k, _ in CONDITION_SLOTS)

#: 全时窗哨兵：`[0, 9999999999]` 表示「任意时刻成立」，是**合法声明**而非空占位
FULL_TIME_WINDOW_MIN = 0.0
FULL_TIME_WINDOW_MAX = 9999999999.0
FULL_TIME_WINDOW_TEXT = "全时窗（任意时刻成立）"

#: 旧口径残留行的前缀——「观测位置：X」是单槽冒充，不是生效条件
LEGACY_POSITION_PREFIX = "观测位置："


def _as_slot_text(value) -> str:
    """槽值 → 单行文本；列表值用「、」连接（「；」留给槽间分隔，不可混用）。"""
    if isinstance(value, (list, tuple)):
        return "、".join(str(x).strip() for x in value if str(x).strip())
    if value is None:
        return ""
    return str(value).strip()


def is_full_time_window(value) -> bool:
    """时间窗是否覆盖全时窗（任意时刻成立）。解析不了 → False（不冒充已声明）。"""
    try:
        lo, hi = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    return lo <= FULL_TIME_WINDOW_MIN and hi >= FULL_TIME_WINDOW_MAX


def _fmt_ts(value) -> str:
    """unix 时间戳 → 「YYYY-MM-DD HH:MM」（UTC）；解析不了 → ""。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(value)))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def time_window_text(value) -> str:
    """时间窗 → 可读文本。

    全时窗**不落裸数组**：`[0, 9999999999]` 直接进正文会变成召回键上的噪声
    数字，且人读不出「任意时刻成立」的语义。具体窗口渲染为 UTC 时刻区间。
    """
    if is_full_time_window(value):
        return FULL_TIME_WINDOW_TEXT
    try:
        lo, hi = _fmt_ts(value[0]), _fmt_ts(value[1])
    except (TypeError, IndexError, KeyError):
        return ""
    if not lo or not hi:
        return ""
    return f"{lo}～{hi}（UTC）"


def condition_slot_text(cs, key: str) -> str:
    """单槽 → 可读值；缺失/空/待填充占位 → ""（不冒充已声明）。"""
    if not isinstance(cs, dict):
        return ""
    value = cs.get(key)
    s = time_window_text(value) if key == "time_window" else _as_slot_text(value)
    if not s or is_placeholder_text(s):
        return ""
    return s


def condition_space_slots(cs) -> list:
    """→ [(槽名, 标签, 文本)]，只含**已声明**的槽（缺失槽不写）。"""
    out = []
    for key, label in CONDITION_SLOTS:
        text = condition_slot_text(cs, key)
        if text:
            out.append((key, label, text))
    return out


def condition_space_missing(cs) -> list:
    """缺失槽名清单（待补台账用）；已声明槽不计。"""
    have = {k for k, _l, _t in condition_space_slots(cs)}
    return [k for k, _l in CONDITION_SLOTS if k not in have]


def condition_space_text(cs, require_full: bool = True) -> str:
    """condition_space → 单行生效条件声明。**唯一合成入口**（纯函数，无 IO）。

    `require_full=True`（默认，即生效条件口径）：四槽不全即返回 ""——部分槽
    不构成完整的条件空间声明，「观测位置」单独一维更不是生效条件。
    `require_full=False`：按固定顺序渲染**已声明**的槽（缺失槽不写），供展示 /
    条件链使用，其产物**不是**生效条件的合法来源。
    """
    slots = condition_space_slots(cs)
    if require_full and len(slots) != len(CONDITION_SLOTS):
        return ""
    return "；".join(f"{label}：{text}" for _k, label, text in slots)


def is_legacy_position_condition(text) -> bool:
    """文本是否为「观测位置：X」形态的单槽冒充（旧口径残留）。

    只认前缀形态，不做语义猜测：用于审计与迁移定位，不参与正常渲染。
    """
    s = "" if text is None else str(text).strip()
    return s.startswith(LEGACY_POSITION_PREFIX) and len(s) > len(LEGACY_POSITION_PREFIX)