#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_id_charset_blocks.py · 蜂巢 job_id 字符白名单「唯一真源」区块表的生成器与陈化守卫。

契约：2026-09-30 使用者裁定「①-(c) 判据从属性判定换成区块白名单」。本脚本是 c1 那份唯一
真源数据（`hive/id_charset_blocks.txt`）的**唯一生成入口**，同时是它的陈化守卫（`--check`：
重算 != 盘上 ⇒ 退出 1）。契约与登记：`docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md`
§四.4 / §四.8。改判据面须先改本脚本的 CANDIDATE_RANGES，再重跑落盘 —— **不要手改数据文件**。

数据源：标准库 `unicodedata`，且**只查类目与 NFC**（不查任何其它 Unicode 属性库 ⇒ 三处读者
的运行期判据不依赖两侧属性表版本，版本差结构性不可能）。生成判据（= 判据本身，不是一次性
动作，与 c3 逐字对应）：在 CANDIDATE_RANGES 给的候选区块内逐码点取交集 ——
(a) `unicodedata.category(c)` ∈ {Lu, Ll, Lt, Lm, Lo, Nd}，
(b) NFC 稳定（`unicodedata.normalize('NFC', c) == c`）；
保留者**归并成最小区间**。即：**区块选择**决定表达面，**类目 + 稳定性**过滤掉区块内的
标点/符号/会改写的形态。

诚实边界（必读）：
  · 本表是**本地 unicodedata 版本的快照**（版本号写进表头）。跨版本会陈化：解释器升级后必须
    重跑本脚本并复核 `--check`。点名现场：CJK 扩展I（2EBF0-2EE5D）在 Unicode 15.0 下整体判
    未分配(Cn) ⇒ 本表采纳 0 码点（该段是 Unicode 15.1 新增）；Python 升到 ≥15.1 后重跑即自动
    纳入 —— 这是版本陈化，**不是判据缺陷**，表头已显式点名，不静默。
  · 单字符 NFC 稳定 **不等于** 整串已归一化：conjoining Hangul Jamo（1100-11FF）单字符稳定，
    却会在字符串层面被 NFC 组合成音节（实测 U+1100 U+1161 → U+AC00）—— 故只收预组合音节
    AC00-D7A3（见 EXCLUDED_RANGES 与 TARGET 面之外的拒收立场）。
  · `_`(U+005F, Pc) 与 `.`(U+002E, Po) **不在本表内**：它们由三处读者的**结构分支**处理
    （`_` = 槽分隔符；`.` = 非尾点、非单独才收）。故 c13 的「字符判据 ≡ 本表」断言范围是
    **字符类判据**，不含这两个结构字符。
  · 本脚本只生成/复核数据，不改任何判据实现；三处读者（Rust / mcp_server / md_cg）各自
    fail-closed 读这份文件（表缺失 / 解析出空区间集 ⇒ 判据一律 false，绝不放行）。

用法：
    python -X utf8 scripts/gen_id_charset_blocks.py            # 干跑：逐区块贡献 + 未收明细 + 自检
    python -X utf8 scripts/gen_id_charset_blocks.py --write    # 落盘 hive/id_charset_blocks.txt
    python -X utf8 scripts/gen_id_charset_blocks.py --check    # 守卫：盘上 != 重算 ⇒ 退出 1（表缺失也 1）
退出码：0 = 一致 / 写入成功；1 = 陈化或自检失败（fail-closed，绝不落盘）；2 = 用法错误。
纪律第 15 条：纯文件读写 + 显式 UTF-8；本脚本不起任何子进程。
"""
from __future__ import annotations

import argparse
import os
import sys
import unicodedata

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——本脚本也是进程入口
# （--write / --check 直跑），报告里含中文与 `⇒`，在未开 UTF-8 模式的 gbk stdout 上会打印即崩。
# 形态照 scripts/run_tests.py / scripts/verify_open_encoding.py 的最小写法（助手在仓根）。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
OUT_REL = "hive/id_charset_blocks.txt"
OUT_PATH = os.path.join(REPO, "hive", "id_charset_blocks.txt")
MAX_CP = 0x10FFFF

# ---------------------------------------------------------------- 判据面常量

#: 采纳类目闭集（c3 的 (a) 条件，逐字）：字母四类 + 标题字母 + 数字(十进制)
TARGET_CATEGORIES = frozenset(("Lu", "Ll", "Lt", "Lm", "Lo", "Nd"))

#: 候选区块（编排侧 c4 裁定，顺序 = c4 原文顺序；**改这份清单 = 改判据面**）：
#: (分组键, 区块标签, 起, 止)。分组键只用于表头/报告的排版分组，不参与判据。
CANDIDATE_RANGES = (
    ("ascii", "ASCII 字母数字与下划线（0020-007E 内按类目过滤）", 0x0020, 0x007E),
    ("latin", "Latin-1 字母", 0x00C0, 0x00FF),
    ("latin", "Latin Extended-A", 0x0100, 0x017F),
    ("latin", "Latin Extended-B", 0x0180, 0x024F),
    ("greek", "希腊与科普特", 0x0370, 0x03FF),
    ("cyr", "西里尔", 0x0400, 0x04FF),
    ("cyr", "西里尔补充", 0x0500, 0x052F),
    ("kana", "平假名", 0x3040, 0x309F),
    ("kana", "片假名", 0x30A0, 0x30FF),
    ("kana", "片假名语音扩展", 0x31F0, 0x31FF),
    ("hangul", "谚文音节（预组合）", 0xAC00, 0xD7A3),
    ("cjk", "CJK 符号与标点", 0x3000, 0x303F),
    ("cjk", "CJK 统一表意", 0x4E00, 0x9FFF),
    ("cjk", "CJK 扩展A", 0x3400, 0x4DBF),
    ("cjk-ext", "CJK 扩展B", 0x20000, 0x2A6DF),
    ("cjk-ext", "CJK 扩展C", 0x2A700, 0x2B73F),
    ("cjk-ext", "CJK 扩展D", 0x2B740, 0x2B81F),
    ("cjk-ext", "CJK 扩展E", 0x2B820, 0x2CEAF),
    ("cjk-ext", "CJK 扩展F", 0x2CEB0, 0x2EBEF),
    ("cjk-ext", "CJK 扩展I", 0x2EBF0, 0x2EE5D),
    ("cjk-ext", "CJK 扩展G", 0x30000, 0x3134F),
    ("cjk-ext", "CJK 扩展H", 0x31350, 0x323AF),
    ("bopo", "注音", 0x3100, 0x312F),
    ("bopo", "注音扩展", 0x31A0, 0x31BF),
)

#: 分组键 → 表头分组标题（仅排版；c4 原文把 CJK 扩展 B..I 写成一段八区间）
GROUP_TITLES = {
    "ascii": "ASCII 字母数字与下划线",
    "latin": "拉丁字母",
    "greek": "希腊与科普特",
    "cyr": "西里尔",
    "kana": "日文假名",
    "hangul": "谚文",
    "cjk": "CJK 符号 / 统一表意 / 扩展A",
    "cjk-ext": "CJK 扩展B..I（c4 原文的一组八区间）",
    "bopo": "注音",
}

#: 有意不收的区块（契约条款，不是遗漏）：(标签, ((起, 止), ...), 理由)
EXCLUDED_RANGES = (
    ("谚文 Jamo（conjoining）", ((0x1100, 0x11FF),),
     "单个 Jamo 自身 NFC 稳定，但**字符串层面**相邻 Jamo 会被 NFC 组合成音节"
     "（实测 U+1100 U+1161 → U+AC00）⇒ 逐字符判据保证不了整串已归一化；只收预组合音节 AC00-D7A3"),
    ("谚文兼容 Jamo", ((0x3130, 0x318F),),
     "与预组合音节同形（NFKC 会改写、可拼回同一音节）。**实测补注（不改裁决）**：兼容 Jamo 无规范"
     "分解，NFC 对它们惰性（实测 NFC(U+3131) == U+3131、NFC(U+3131 U+314F) 不变）——故 c4 给的"
     "『字符串层 NFC』理由严格只覆盖 conjoining Jamo(1100-11FF)；本段的实际理由是 NFKC 改写面 +"
     " 与预组合音节同形"),
    ("谚文 Jamo 扩展-A/B", ((0xA960, 0xA97F), (0xD7B0, 0xD7FF)),
     "conjoining Jamo 的延伸段（字符串层与相邻 Jamo 组合）——与 1100-11FF 同类；"
     "**c4 的『有意不收』原文未点名这两段**（登记缺口，本表按同理由不收）"),
    ("CJK 兼容表意", ((0xF900, 0xFAFF),),
     "有**规范**分解（NFC 会改写）⇒ 也过不了 c3 的 (b) 条件"),
    ("CJK 兼容表意补充", ((0x2F800, 0x2FA1F),), "同上（有规范分解）"),
    ("其余兼容/带圈/上下标/数学字母数字/全角半角",
     ((0x00AA, 0x00AA), (0x00B2, 0x00BA), (0x2070, 0x209F), (0x2100, 0x218F),
      (0x2460, 0x24FF), (0x3130, 0x318F), (0x3200, 0x33FF), (0xFB00, 0xFB4F),
      (0xFE30, 0xFE4F), (0xFE50, 0xFE6F), (0xFF00, 0xFFEF), (0x1D400, 0x1D7FF)),
     "契约点名一揽子不收（区块选择裁决）：它们本就不在候选清单内，故拒收立场不依赖类目/NFC 过滤"),
)


# ---------------------------------------------------------------- 判据实现（生成侧）

# 生效条件：cp ∈ [0, 0x10FFFF] 时返回 None（该码点**采纳**进本表）或未收原因之一——
# "cn"（本地 unicodedata 判未分配）、"category"（类目 ∉ TARGET_CATEGORIES）、
# "nfc"（单字符 NFC 不稳定）。这是本表的**唯一生成判据**，与三处读者的运行期字符判据同源。
def _screen(cp: int) -> str | None:
    """逐码点判据：类目 ∈ TARGET_CATEGORIES ∧ NFC 稳定（c3 的 (a)(b)）。"""
    ch = chr(cp)
    cat = unicodedata.category(ch)
    if cat == "Cn":
        return "cn"
    if cat not in TARGET_CATEGORIES:
        return "category"
    if unicodedata.normalize("NFC", ch) != ch:
        return "nfc"
    return None


# 生效条件：无入参；扫全部候选区间，返回 (adopted, skipped, per_range)——adopted 为采纳码点集合；
# skipped = {原因: [码点]}（合并输出用）；per_range = [(标签, 起, 止, 采纳数, {原因: 计数})]，
# 顺序同 CANDIDATE_RANGES。候选区间两两不相交由 _ranges_disjoint 另行断言（调用方 fail-closed）。
def _scan() -> tuple:
    """扫候选区块，逐码点过 _screen（生成判据的唯一执行点）。"""
    adopted: set = set()
    skipped: dict = {}
    per_range: list = []
    for group, label, lo, hi in CANDIDATE_RANGES:
        adopted_here, reasons = 0, {}
        for cp in range(lo, hi + 1):
            why = _screen(cp)
            if why is None:
                adopted.add(cp)
                adopted_here += 1
            else:
                skipped.setdefault(why, []).append(cp)
                reasons[why] = reasons.get(why, 0) + 1
        per_range.append((group, label, lo, hi, adopted_here, reasons))
    return adopted, skipped, per_range


# 生效条件：pairs 为 (起, 止) 序列时返回它们是否两两不相交（否 ⇒ 生成/复核一律 fail-closed 停手：
# 相交的候选段会让「逐区块贡献」与「码点唯一归属」同时失真）。
def _ranges_disjoint(pairs) -> bool:
    """候选区间两两不相交（生成判据的自明前提）。"""
    ordered = sorted(pairs)
    for (a1, b1), (a2, b2) in zip(ordered, ordered[1:]):
        if a2 <= b1:
            return False
    return True


# 生效条件：points 为码点集合（可空）时返回按码点升序、两两不相邻的**最小区间**列表 [(起, 止)]；
# 空集 → []。归并判据：相邻（p == 上一区间止 + 1）即并入，故输出即最小表示。
def _merge(points) -> list:
    """码点集合 → 最小区间（左闭右闭）。"""
    out: list = []
    for p in sorted(points):
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return [(a, b) for a, b in out]


# 生效条件：lo <= hi 时返回表内区间字面量（大写十六进制、至少四位、`LO-HI`）；越界由调用方保证。
def _hex(lo: int, hi: int) -> str:
    """区间字面量（四位起对齐，与表内正文一致）。"""
    return "%04X-%04X" % (lo, hi)


# 生效条件：text 为表文件全文时返回区间列表 [(起, 止)]——按表头公布的**唯一解析配方**：
# 每行取 `#` 之前部分、strip；空行跳过；余下 split('-') 两段 int(x, 16)。
# 任一行不合形态/越界/逆序即抛 ValueError（fail-closed：绝不静默跳过坏行）。
def _parse(text: str) -> list:
    """表文件 → 区间列表（三处读者的解析配方**唯一真源**，本函数即其可执行规格）。"""
    out: list = []
    for lineno, line in enumerate(text.split("\n"), 1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split("-")
        if len(parts) != 2:
            raise ValueError("第 %d 行不是 LO-HI 形态：%r" % (lineno, line))
        lo, hi = int(parts[0], 16), int(parts[1], 16)
        if not (0 <= lo <= hi <= MAX_CP):
            raise ValueError("第 %d 行区间非法：%r" % (lineno, line))
        out.append((lo, hi))
    return out


# 生效条件：intervals 为区间列表时返回其展开的码点集合（用于「表 ≡ 判据重算集合」的双向比对）。
def _expand(intervals) -> set:
    """区间列表 → 码点集合。"""
    out: set = set()
    for lo, hi in intervals:
        out.update(range(lo, hi + 1))
    return out


# 生效条件：intervals 为区间列表时返回它们是否已归并到最小（升序 ∧ 两两不相邻 ∧ 互不相交）。
def _is_minimal(intervals) -> bool:
    """最小区间判据：升序、相邻即应合并（p_prev_hi + 1 != next_lo）、互不相交。"""
    for (a1, b1), (a2, b2) in zip(intervals, intervals[1:]):
        if not (a1 <= b1 < a2 <= b2) or a2 == b1 + 1:
            return False
    for a, b in intervals:
        if a > b:
            return False
    return True


# ---------------------------------------------------------------- 表文件渲染与自检

# 生效条件：adopted/skipped/per_range/intervals 与无关入参 _dummy 一并给出时，返回表文件全文
# （表头注释 + 每行一个区间的正文）；所有计数由本次重算结果写入（**重跑即刷新，不存在手改面**）。
def _render(adopted: set, skipped: dict, per_range: list, intervals: list,
            version: str, disjoint: bool) -> str:
    """渲染表文件全文（表头 + 正文）。"""
    cand_total = sum(hi - lo + 1 for _g, _l, lo, hi in CANDIDATE_RANGES)
    cand_segs = len(CANDIDATE_RANGES)
    lines: list = []
    add = lines.append
    add("# 蜂巢 job_id 字符白名单 · 区块表（唯一真源；本文件由脚本生成，勿手改）")
    add("#")
    add("# 唯一真源：本文件是 id 字符集判据的**唯一数据源**——三处读者读同一份数据，任何一处都不得")
    add("# 再手写/内嵌区间常量（2026-09-30 使用者裁定 ①-(c)：判据从「Unicode 属性判定」换成「区块")
    add("# 白名单」；旧机制依赖两侧运行时的 Unicode 属性表版本，全码点意义上不可能同判）。")
    add("# 契约与登记：docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md §四.4 / §四.8。")
    add("#")
    add("# 三处读者（全部 fail-closed：表缺失 / 解析出空区间集 ⇒ 判据一律返回 false，绝不放行）：")
    add("#   ① Rust   hive/src/job.rs             —— include_str! 编译期嵌入 + 首次使用惰性解析（纯 std）")
    add("#   ② Python hive/hive_mcp/mcp_server.py —— 模块导入时读一次（不做每调用 I/O）")
    add("#   ③ md_cg  md_cg/units.py              —— 同样读这份文件（读数据不是 import，不违背零依赖家法）")
    add("#")
    add("# 生成命令（本表**由脚本生成、可重跑**；手改必被 --check 判陈化）：")
    add("#   python -X utf8 scripts/gen_id_charset_blocks.py --write    # 落盘")
    add("#   python -X utf8 scripts/gen_id_charset_blocks.py --check    # 守卫：重算 != 盘上 ⇒ 退出 1")
    add("#   python -X utf8 scripts/gen_id_charset_blocks.py            # 干跑：逐区块贡献 + 未收明细 + 自检")
    add("#")
    add("# 生成判据（只用标准库；这是判据本身，不是一次性动作）：")
    add("#   在候选区块内逐码点取交集 —— (a) unicodedata.category(c) ∈ {Lu, Ll, Lt, Lm, Lo, Nd}")
    add("#   且 (b) NFC 稳定（unicodedata.normalize('NFC', c) == c）；保留者**归并成最小区间**。")
    add("#   即 **区块选择**决定表达面，**类目 + 稳定性**过滤掉区块内的标点/符号/会改写的形态。")
    add("#   表内每个码点都 NFC 稳定（生成器与守卫各自全表重算一遍）⇒ 判据不必做真 NFC 计算，")
    add("#   也保证 id 已是 NFC 形态（拒收而非静默归一化）。")
    add("#   `_`(U+005F, Pc) 与 `.`(U+002E, Po) **不在本表内**：它们由三处读者的**结构分支**处理")
    add("#   （`_` = 槽分隔符；`.` = 非尾点、非单独才收）——故「字符判据 ≡ 本表」的断言范围是")
    add("#   **字符类判据**，不含这两个结构字符（c13）。三处读者另有逐条显式拒收（c7/c9）：零宽")
    add("#   U+200B..U+200F/U+2060/U+FEFF、双向控制 U+202A..U+202E/U+2066..U+2069、路径成分")
    add("#   `/` `\\` `:`、单独 `.`/`..`、尾点、首尾空白、控制字符、Windows 保留设备名（含")
    add("#   CON.txt 形态、按 `_` 分段任一段）——**它们不在表内是默认被拒，但读者必须逐条显式断言**。")
    add("#")
    add("# 格式（每行一个左闭右闭十六进制区间，四位起对齐；`#` 开头与空行忽略）：")
    add("#   0030-0039")
    add("#   4E00-9FFF")
    add("# 解析配方（三处读者同此一条，不许各写一套）：line.split('#')[0].strip()；空则跳过；")
    add("#   否则 split('-') 两段 int(x, 16) = (lo, hi)。**正文不含行内注释**（防三种解析各写一套），")
    add("#   表头注释一律以 `#` 起行。")
    add("#")
    add("# 候选区块清单（编排侧 c4 裁定；计数 = 本表从该段采纳的码点数，脚本重跑时重算）：")
    last_group = None
    for (group, label, lo, hi, n, reasons) in per_range:
        if group != last_group:
            add("#   [%s]" % GROUP_TITLES.get(group, group))
            last_group = group
        add("#     %-46s %s  采纳 %d" % (label, _hex(lo, hi), n))
        for why, cn in sorted(reasons.items()):
            add("#       └ 未收 %-8s %d（%s）" % (why, cn, _WHY[why]))
    add("#")
    add("# 有意不收（契约条款，不是遗漏）：")
    for label, ranges, reason in EXCLUDED_RANGES:
        add("#   · %s（%s）：%s" % (label, "、".join(_hex(a, b) for a, b in ranges), reason))
    add("#")
    add("# 统计（脚本每次重跑重算写回，勿手改）：")
    add("#   unicodedata 版本：%s（本表是该版本的**快照**：解释器升级后须重跑并复核 --check）" % version)
    add("#   候选：%d 段 / %d 码点；采纳 %d 码点；归并成 %d 条最小区间；候选段两两不相交：%s"
        % (cand_segs, cand_total, len(adopted), len(intervals), "是" if disjoint else "否（异常！）"))
    for why in ("cn", "category", "nfc"):
        ps = skipped.get(why) or []
        add("#   未收 %-8s %d 码点（%s）" % (why, len(ps), _WHY[why]))
    ext_i = next((r for r in per_range if r[1] == "CJK 扩展I"), None)
    if ext_i is not None:
        _g, label_i, lo_i, hi_i, n_i, reasons_i = ext_i
        add("#   版本陈化点名：%s（%s）在本版本：判未分配(Cn) %d 码点 ⇒ 采纳 %d 码点"
            % (label_i, _hex(lo_i, hi_i), reasons_i.get("cn", 0), n_i))
        add("#     （该段是 Unicode 15.1 新增；Python 升到 ≥15.1 后重跑本脚本即自动纳入，不静默）")
    nfkc = _nfkc_but_kept(adopted)
    add("#   NFKC 面补注（本判据只有 NFC 面）：表内 %d 个码点 NFKC 会改写但 NFC 稳定 ⇒ 按 c3 采纳。"
        % len(nfkc))
    add("#     旧机制（NFC_REWRITE_BLOCKS，本批退休）曾以『兼容分解』为由排除其中的 "
        "0132-0133 / 01C4-01CC / 01F1-01F3（14 码点）——")
    add("#     它们在本表下由拒转收；其余 %d 个旧机制本就采纳。NFKC 改写面**不在本判据面内**。"
        % (len(nfkc) - 14))
    add("#     合并区间：%s" % "、".join(_hex(a, b) for a, b in _merge(nfkc)))
    add("#")
    for lo, hi in intervals:
        add(_hex(lo, hi))
    return "\n".join(lines) + "\n"


#: 未收原因的展示文案（原因码 → 一句话）
_WHY = {
    "cn": "本地 unicodedata 判未分配",
    "category": "类目 ∉ {Lu,Ll,Lt,Lm,Lo,Nd}",
    "nfc": "单字符 NFC 不稳定",
}


# 生效条件：points 为采纳码点集合时返回其中 NFKC 会改写（normalize('NFKC', c) != c）的码点列表（升序）。
def _nfkc_but_kept(points) -> list:
    """采纳面里 NFKC 会改写的码点（NFC 稳定但兼容分解 ⇒ 判据面之外的既知取舍）。"""
    return sorted(cp for cp in points if unicodedata.normalize("NFKC", chr(cp)) != chr(cp))


# 生效条件：adopted/skipped/intervals/disjoint/version 与全部渲染入参给出时，返回自检失败清单——
# 逐项重算（不是复述）：①候选段两两不相交；②表内每码点 ∈ 候选且逐点过 _screen；
# ③判据重算集合 == 表区间展开集合（双向：无漏收/无多收）；④区间已归并到最小（升序/不相邻/不相交）；
# ⑤表内每码点 NFC 稳定（c5 的机械断言，独立重算一遍）；⑥解析往返（_parse(渲染) 展开 == 重算集合）。
# 空清单 = 全过；非空 = fail-closed（调用方绝不落盘）。
def _selfcheck(adopted: set, skipped: dict, intervals: list, text: str, disjoint: bool) -> list:
    """自检六项（逐项独立重算，失败即 fail-closed）。"""
    failures: list = []
    if not disjoint:
        failures.append("① 候选区间存在相交（码点归属不唯一）")
    stray = sorted(cp for cp in adopted if _screen(cp) is not None)
    if stray:
        failures.append("② 表内 %d 个码点未过判据，例：%s"
                        % (len(stray), [_hex(cp, cp) for cp in stray[:5]]))
    expected = set()
    for _g, _l, lo, hi in CANDIDATE_RANGES:
        expected.update(cp for cp in range(lo, hi + 1) if _screen(cp) is None)
    if expected != adopted:
        failures.append("③ 判据重算集合 != 采纳集合（差 %d 个码点）" % len(expected ^ adopted))
    if _expand(intervals) != adopted:
        failures.append("③b 表区间展开 != 采纳集合")
    if not _is_minimal(intervals):
        failures.append("④ 区间未归并到最小（存在相邻/乱序/相交）")
    unstable = sorted(cp for cp in adopted if unicodedata.normalize("NFC", chr(cp)) != chr(cp))
    if unstable:
        failures.append("⑤ 表内存在 NFC 不稳定码点 %d 个，例：%s"
                        % (len(unstable), [_hex(cp, cp) for cp in unstable[:5]]))
    try:
        back = _parse(text)
    except ValueError as exc:
        failures.append("⑥ 解析往返失败：%s" % exc)
    else:
        if _expand(back) != adopted:
            failures.append("⑥ 解析往返集合 != 采纳集合")
        if not _is_minimal(back):
            failures.append("⑥b 解析回的区间未归并到最小")
    if not adopted:
        failures.append("⑦ 采纳集合为空（fail-closed：空表绝不放行）")
    return failures


# 生效条件：intervals 为区间列表时返回其总码点数（= 覆盖码点数）。
def _covered(intervals) -> int:
    """区间覆码点数。"""
    return sum(hi - lo + 1 for lo, hi in intervals)


# ---------------------------------------------------------------- 报告

# 生效条件：per_range/skipped/intervals/adopted/version 给出时打印人读报告
# （逐区块贡献 + 未收明细区间 + 自检结论）；返回 None，只写 stdout。
def _report(adopted: set, skipped: dict, per_range: list, intervals: list,
            failures: list, version: str, disjoint: bool) -> None:
    """打印干跑报告（逐区块贡献 / 未收明细 / 自检）。"""
    cand_total = sum(hi - lo + 1 for _g, _l, lo, hi in CANDIDATE_RANGES)
    print("判据：unicodedata.category(c) ∈ {%s} ∧ normalize('NFC', c) == c（候选区块内取交集后归并）"
          % ", ".join(sorted(TARGET_CATEGORIES)))
    print("unicodedata 版本：%s；候选 %d 段 / %d 码点；采纳 %d 码点 → 归并 %d 条最小区间；"
          "候选段两两不相交：%s"
          % (version, len(CANDIDATE_RANGES), cand_total, len(adopted), len(intervals),
             "是" if disjoint else "否（异常）"))
    print("逐候选区块贡献（采纳 / 该段码点数；未收按原因）：")
    for (group, label, lo, hi, n, reasons) in per_range:
        detail = "，".join("%s %d" % (why, cn) for why, cn in sorted(reasons.items()))
        print("  %-46s %-13s 采纳 %6d / %6d%s"
              % (label, _hex(lo, hi), n, hi - lo + 1, ("；未收：" + detail) if detail else ""))
    print("未收明细（候选内被过滤的码点，按原因归并成最小区间）：")
    for why in ("cn", "category", "nfc"):
        ps = skipped.get(why) or []
        if not ps:
            print("  %-8s 0 码点" % why)
            continue
        merged = _merge(ps)
        head = "、".join(_hex(a, b) for a, b in merged[:8])
        print("  %-8s %d 码点 / %d 条区间（%s）：%s%s"
              % (why, len(ps), len(merged), _WHY[why], head,
                 " …（共 %d 条，看数据文件表头逐区块行）" % len(merged) if len(merged) > 8 else ""))
    nfkc = _nfkc_but_kept(adopted)
    print("NFKC 面补注：表内 %d 码点 NFKC 会改写但 NFC 稳定 ⇒ 按 c3 采纳（合并 %d 条区间；"
          "其中 0132-0133 / 01C4-01CC / 01F1-01F3 共 14 个是本批唯一一类 reject→accept 翻转）"
          % (len(nfkc), len(_merge(nfkc))))
    print("自检（%s）：%s" % ("全过" if not failures else "失败 %d 项" % len(failures),
                            "；".join(failures) if failures else
                            "①候选两两不相交 ②表内逐点过判据 ③判据重算集合 ≡ 表（双向） "
                            "④区间已归并到最小 ⑤表内逐点 NFC 稳定 ⑥解析往返 ⑦表非空"))
    print("覆盖码点数：%d（区间并集；= 采纳码点数：%s）"
          % (_covered(intervals), "是" if _covered(intervals) == len(adopted) else "否（异常）"))


# ---------------------------------------------------------------- 主流程

# 生效条件：v 为「X.Y.Z」形态版本串时返回 int 元组（非数字段按 0，宽松解析不抛）。
def _ver_tuple(v: str) -> tuple:
    return tuple(int(seg) if seg.isdigit() else 0 for seg in str(v).split("."))


# 生效条件：读盘上表头「unicodedata 版本：X」快照版本串；表缺失/无该行返回 None。
def _table_version(path=OUT_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if not ln.startswith("#"):
                    break
                pos = ln.find("unicodedata 版本：")
                if pos >= 0:
                    ver = ln[pos + len("unicodedata 版本："):].split("（")[0].strip()
                    if ver and all(ch.isdigit() or ch == "." for ch in ver):
                        return ver
    except OSError:
        return None
    return None


# 生效条件：argv 给出时按模式执行——缺省（干跑）打印报告；--write 自检通过后落盘并复读校验；
# --check 与盘上逐字比对（缺失/陈化/自检失败均非 0）。返回退出码：0 一致或写入成功；1 陈化/自检失败。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="蜂巢 job_id 字符白名单区块表：生成 / 陈化守卫")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="落盘 %s" % OUT_REL)
    g.add_argument("--check", action="store_true", help="守卫：盘上 != 重算 ⇒ 退出 1")
    args = ap.parse_args(argv)

    version = unicodedata.unidata_version
    disjoint = _ranges_disjoint([(lo, hi) for _g, _l, lo, hi in CANDIDATE_RANGES])
    adopted, skipped, per_range = _scan()
    intervals = _merge(adopted)
    text = _render(adopted, skipped, per_range, intervals, version, disjoint)
    failures = _selfcheck(adopted, skipped, intervals, text, disjoint)
    _report(adopted, skipped, per_range, intervals, failures, version, disjoint)

    if failures:
        print("✖ 自检失败 %d 项：fail-closed，绝不落盘" % len(failures))
        return 1

    if args.check:
        try:
            with open(OUT_PATH, encoding="utf-8") as fh:
                have = fh.read()
        except OSError as exc:
            print("✖ 表缺失或不可读（fail-closed）：%s —— %s" % (OUT_REL, exc))
            return 1
        # 版本三态（2026-10-03 外部报告核验新增；表头本已声明「本表=某版本快照」）：
        #   本机 == 表快照 ⇒ 原路径（逐字比对）。
        #   本机 >  表快照（解释器升级）⇒ 原路径：重算 ≠ 盘上 ⇒ 判陈化、催促重跑
        #     （设计既有语义「解释器升级后须重跑并复核」）。
        #   本机 <  表快照（旧解释器复核新表）⇒ **豁免逐字比对、rc 仍 0**：本环境算不出
        #     生成版本的码点集（实证：python 3.11/unidata 14.0.0 对 15.0.0 表重算
        #     CJK 扩展C 少 1 码点，4153 vs 4154）——判 1 是伪信号（既非表错、也非应按
        #     本机重跑）。豁免明示理由（不静默），版本无关面由测试守卫覆盖。
        _tv = _table_version()
        if _tv and _ver_tuple(version) < _ver_tuple(_tv):
            print("✔ 陈化守卫豁免（跨版本）：本机 unicodedata %s 低于表快照 %s——"
                  "逐字比对需在 ≥%s 的解释器上进行，本环境跳过；表以 %s 为准"
                  % (version, _tv, _tv, _tv))
            return 0
        if have == text:
            print("✔ 陈化守卫通过：%s 与重算结果逐字一致（%d 条区间 / %d 码点）"
                  % (OUT_REL, len(intervals), len(adopted)))
            return 0
        have_lines, want_lines = have.split("\n"), text.split("\n")
        first = next((i for i, (a, b) in enumerate(zip(have_lines, want_lines), 1) if a != b),
                     min(len(have_lines), len(want_lines)) + 1)
        print("✖ 陈化：%s 与重算结果不一致（首个差异在第 %d 行）；重跑 --write 刷新" % (OUT_REL, first))
        print("   盘上：%r" % (have_lines[first - 1] if first <= len(have_lines) else "<缺行>"))
        print("   重算：%r" % (want_lines[first - 1] if first <= len(want_lines) else "<缺行>"))
        try:
            same_set = _expand(_parse(have)) == adopted
        except ValueError as exc:
            same_set = False
            print("   盘上解析失败：%s" % exc)
        print("   区间集合是否相同：%s" % ("相同（仅表头陈化）" if same_set else "不同"))
        return 1

    if args.write:
        # 防降级覆盖（2026-10-03 外部报告核验新增）：本机低于表快照版本时拒绝写入——
        # 降级重生成会用旧码点集覆盖新表（实证差 1 码点），且与 CI（3.12）产生新陈化。
        _tv = _table_version()
        if _tv and _ver_tuple(version) < _ver_tuple(_tv):
            print("✖ 拒绝写入（fail-closed）：本机 unicodedata %s 低于盘上表快照 %s——"
                  "请用 ≥%s 的解释器重生成（仓库 CI 为 Python 3.12）" % (version, _tv, _tv))
            return 1
        with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        with open(OUT_PATH, encoding="utf-8") as fh:
            back = fh.read()
        if back != text:
            print("✖ 落盘后复读不一致（fail-closed）：%s" % OUT_REL)
            return 1
        print("✔ 已落盘 %s：%d 条最小区间 / %d 码点（落盘后复读逐字一致）"
              % (OUT_REL, len(intervals), len(adopted)))
        return 0

    print("干跑结束（未落盘）：落盘用 --write，复核用 --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
