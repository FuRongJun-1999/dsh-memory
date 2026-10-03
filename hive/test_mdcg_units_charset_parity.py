# -*- coding: utf-8 -*-
"""hive 面守卫 · md_cg/units.py job_id 字符集闸「区块白名单」同源/同判守卫（c8/c9/c10/c12）

**落点说明（为什么在 `hive/` 而不在 `md_cg/`）**：被守卫对象仍是 `md_cg/units.py::
_valid_job_id`（c10 要求 md_cg 侧逐例对照）——但**新文件不能落在发布清单内的目录**：
`package.json` 的 `files` 含 `md_cg`、**不含 `hive`**，而本批按使用者要求**不 git 提交**，
未入索引的新文件放在 `md_cg/` 会被 npm 门禁的 **R4 非追踪件面**判红
（`scripts/check_publish_artifact.py:46` 的 ALLOW_NONTRACKED 只允许 `lib/`；实测
md_cg 落点 → R4 FAIL、hive 落点 → 绿）。判据、断言与被守卫语义与落点无关，一字未动。

被判据面（2026-09-30 使用者裁定 ①-(c)，该闸是**第三处读者**）：`md_cg/units.py::
_valid_job_id` 的字符集判据从本模块自持的 ASCII 白名单
（`["a"-"z","A"-"Z","0"-"9","_",".","-"]`）换成与 hive 两侧**同一份数据**
`hive/id_charset_blocks.txt` 的区间并集——**读数据文件，不 import hive**
（三处读者共读一份数据；本守卫同理只以文本读 hive 侧源码，不 import 它）。

本守卫钉五组（缺一不可）：
  [1] **字符类判据 ≡ 表**：全码点 0..0x10FFFF 遍历（**仅测试内**，不进生产热路径）。
      左侧 = 生产的 `units._charset_member`；右侧 = 本守卫**独立重算**的区间并集
      （自带解析配方 + 归并/有序/非空不变量断言）。两侧各自「≡ 表」合起来即跨语言
      **零分歧**（同一份数据 + 同一配方），不必喂 hive.exe 逐码点（那是 44 分钟路径）。
  [2] **语料逐例对照（c10）**：`hive/id_contract_corpus_v2.txt` 逐例解码，断言 md_cg 的
      verdict 与语料 verdict 相同——**除有意差异外**，且实际差异集必须**恰好等于**
      本文件显式登记的表（多一条少一条都红；不许默默过滤、不许改语料）。
  [3] **拒收面逐条显式断言（c9/c7）**：零宽 / 双向控制 / 控制字符 / 路径成分 / 单独点与
      尾点 / 首尾空白 / Windows 保留设备名——它们在白名单外是**默认**被拒，但必须
      **逐条显式断**（防将来有人放宽某个区块时把它们一并带进来）；另含长度与类型边界、
      以及「换面确实放宽了」的正向证据（旧机制拒而表收的 14 码点）。
  [4] **三处调用点语义不变（c9）**：submit 落点前 / poll / wait fail-fast——同一批坏 id
      过三处，返回结构与 N178 守卫同构（state=invalid_job_id、content 恒 None、
      job_dir 恒 None），wait 不进轮询。
  [5] **表自身的既有面**：表由脚本可重跑（`scripts/gen_id_charset_blocks.py --check`
      陈化守卫）、表内每码点 NFC 稳定（c5：故判据不必做真 NFC 计算，收下的 id 已是 NFC
      形态）、坏表 fail-closed（空表/坏行一律 False，绝不放行）、c4 的「有意不收」段
      逐段仍在表外。

**诚实边界（有意差异，写死在此、不许默默过滤）**：md_cg 面的 `_valid_job_id` **有意不比**
hive 严格的两处——
  (a) **不要求 `h` 前缀**：`md_cg/test_units_poll.py` 的 "j_empty"/"j_good"/"j_fail"
      是既有对外契约（poll 面向任意宿主派发器写出的 job 目录，前缀收紧会误杀）；
  (b) **允许 `-`**：同上，既有对外契约，不得为「同口径」收紧。
故语料第 79 行（`h_端-1_任务_记录单元_0001`；语料与 `job.rs` 判 reject）在 md_cg 面判
**accept**——这是**判据面差异**而非漏判，登记见 [`_CORPUS_DIVERGENCES`]，并与语料逐例
对照的结果做**对集相等**断言。(a) 在本语料中**无载体**（逐例核过：无一例的拒绝理由只是
缺 `h` 前缀），故它在 [`_PREFIX_ONLY_CASES`] 里以**语料外**的既有契约名单独钉死。
反方向（md_cg 比 hive 严的地方）同样显式登记：(c) **Windows 保留设备名**在 md_cg 的旧
ASCII 白名单下是**放行**的（`CON` 全是 ASCII 字母），本批随换面**收紧为拒**——语料
80-84 行即是本面收紧的钉死例，[3] 另有 22 名 × 5 形态的穷举断言。

运行：python -m hive.test_mdcg_units_charset_parity
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unicodedata

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（c14 / 工作纪律第 15 条）：本守卫读的文件含中文与十六进制表，**必须在任何
# 文件 I/O 之前**保证 UTF-8（形态照 scripts/run_tests.py 的最小写法）。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

from md_cg import units  # noqa: E402

PASS = FAIL = 0
FAILS = []

_REPO = _UTF8_ROOT
_BLOCKS_REL = "hive/id_charset_blocks.txt"
_CORPUS_REL = "hive/id_contract_corpus_v2.txt"
_GEN_REL = "scripts/gen_id_charset_blocks.py"
_MAX_CP = 0x10FFFF

#: 语料例外 = md_cg 面的**有意差异**（键 = 解码后的 id 文本；值 = 为什么两侧有意不同判）。
#: 断言形式：实际差异集 == 本表键集（多一条少一条都红）——**不许默默过滤**。
_CORPUS_DIVERGENCES = {
    "h_端-1_任务_记录单元_0001":
        "md_cg 面有意保留「允许 `-`」（既有对外契约，c8）⇒ 语料/job.rs 判 reject，"
        "md_cg 面判 accept（这是判据面差异，不是漏判）",
}

#: 前缀差异的语料外钉死例（**不是**语料的一部分，故不能写进语料）：job.rs:238
#: `if id.is_empty() || !id.starts_with('h') { return false; }` ⇒ 这三个 id 在 hive 侧
#: 判 reject，md_cg 面**有意收**（`md_cg/test_units_poll.py:44/52/56` 的既有对外契约）。
#: 本组只断言 md_cg 侧行为——rust 侧由 job.rs 单测钉死，此处**不假装跑过 rust**。
_PREFIX_ONLY_CASES = ("j_empty", "j_good", "j_fail")

#: 表内新增而旧机制（`is_alphanumeric` + NFC 排除表）**拒**的 14 个码点（c11 留痕：
#: 换面的改判集；语料未覆盖，理由见表头「有意不收」段）。断言它们**现在被收**——
#: 这是换面「放宽」的正向证据，不是漏判（都是 Lu/Ll/Lt/Lm/Lo/Nd 且 NFC 稳定）。
_WIDENED_CODEPOINTS = [0x0132, 0x0133] + list(range(0x01C4, 0x01CD)) + \
                      list(range(0x01F1, 0x01F4))

#: c4 点名的「有意不收」段（代表段全段 + 表头点名的单例）：断言它们**都在表外**
#: （= 判据拒）。前四段是整段扫描，后一组是表头/语料点名的单例。
_EXCLUDED_RANGES = [
    (0x1100, 0x11FF, "Hangul Jamo（单 Jamo NFC 稳定，但字符串层面相邻 Jamo 会被 NFC "
                     "组合成音节 ⇒ 逐字符判据保证不了整串已归一化）"),
    (0x3130, 0x318F, "Hangul 兼容 Jamo"),
    (0xF900, 0xFAFF, "CJK 兼容表意（含**规范**分解）"),
    (0x2F800, 0x2FA1F, "CJK 兼容表意补充"),
    (0x0300, 0x036F, "组合标记（NFD 形载体）"),
]
_EXCLUDED_SINGLES = [
    (0x00AA, "序数指示符（兼容分解 a a）"),
    (0x2070, "上标零（兼容分解 0）"),
    (0x2160, "罗马数字一（兼容分解 I）"),
    (0xFF11, "全角一（半角全角区块）"),
    (0x2460, "带圈一（带圈字母数字区块）"),
    (0x3200, "括号 CJK（带圈/括号 CJK 与单位区块）"),
    (0x1D400, "数学粗体 A（数学字母数字区块）"),
    (0xFB01, "连字 ﬁ（字母表现形区块）"),
    (0xFE30, "CJK 兼容形式"),
    (0xFE50, "小写变体形式"),
    (0x2126, "欧姆符号（Letterlike 单例分解为 Ω）"),
    (0xFA10, "兼容表意（CJK 兼容表意区块）"),
]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % (name + (" · " + detail if detail else "")))
    else:
        FAIL += 1
        FAILS.append(name + (" · " + detail if detail else ""))
        print("  [FAIL] %s" % (name + (" · " + detail if detail else "")))


def _read_text(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
        return fh.read()


# 生效条件：无入参，返回区块表**独立重算**的区间列表——本守卫自带解析配方
# （正则全文匹配 LO-HI，行内 `#` 之后去掉），并断言表的归并/有序/非空不变量。
# 这条是**对照物**：与生产解析配方互为独立路径（生产按 split('-') 取两段），
# 一致才算「表就是指这份数据」。
_RANGE_RE = re.compile(r"^([0-9A-Fa-f]{4,6})-([0-9A-Fa-f]{4,6})$")


def _oracle_ranges():
    out, bad = [], []
    for lineno, line in enumerate(_read_text(_BLOCKS_REL).split("\n"), 1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        m = _RANGE_RE.match(body)
        if not m:
            bad.append((lineno, line))
            continue
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        out.append((lo, hi, lineno))
    return out, bad


# 生效条件：ranges 为 (lo, hi, lineno) 列表时返回 (归并最小 bool, 非空 bool, 说明)——
# 断言表有序、相邻/相交即未归并（生产解析器同判据，此处独立复核）。
def _oracle_shape(ranges):
    if not ranges:
        return False, False, "独立重算得到空区间集"
    prev_hi = None
    for lo, hi, lineno in ranges:
        if not (0 <= lo <= hi <= _MAX_CP):
            return False, True, "第 %d 行区间非法：%04X-%04X" % (lineno, lo, hi)
        if prev_hi is not None and lo <= prev_hi + 1:
            return False, True, "第 %d 行未归并到最小（相邻/相交/乱序）" % lineno
        prev_hi = hi
    return True, True, "%d 段" % len(ranges)


# ---------------------------------------------------------------- [1] 判据 ≡ 表

def group_charset_equals_table():
    print("\n[1] 字符类判据 ≡ 表（全码点遍历，仅测试内）")
    ranges, bad = _oracle_ranges()
    merged, nonempty, detail = _oracle_shape(ranges)
    check("① 表文件可独立重算且归并到最小", not bad and merged and nonempty,
          detail + ("" if not bad else "；坏行 %r" % (bad[:2],)))
    bm = bytearray(_MAX_CP + 1)
    for lo, hi, _ln in ranges:
        bm[lo:hi + 1] = b"\x01" * (hi - lo + 1)

    mismatch, got_n, want_n = [], 0, 0
    for cp in range(_MAX_CP + 1):
        want = bool(bm[cp])
        got = units._charset_member(chr(cp))
        if want:
            want_n += 1
        if got:
            got_n += 1
        if want != got and len(mismatch) < 8:
            mismatch.append("U+%04X 表=%s 判据=%s" % (cp, want, got))
    check("① 全码点 0..0x10FFFF：判据 == 表的区间并集（零分歧）",
          not mismatch, "；".join(mismatch) if mismatch else "已遍历 %d 码点" % (_MAX_CP + 1))
    # ①b **整闸**同款断言（c13 在第三处读者身上的另一半）。缺它时，在
    # `_valid_job_id` 的字符类分支里额外放行一个表外区块可**完全逃过**本守卫——
    # 复核侧定点变异实测：只把该分支改成 `_charset_member(c) or "\u0600"<=c<="\u06ff"`
    # 时，本组守卫 RC=0 / 全绿（而 `_valid_job_id("h_ع_..")` 已判 True、`_charset_member('ع')`
    # 仍为 False）。Rust 面有 job_id_and_slot_gates_use_table_membership、MCP 面有 C8b2
    # 做了整闸全码点断言，故此处按同款形态补齐为第三份。
    gate_mismatch = []
    for cp in range(_MAX_CP + 1):
        c = chr(cp)
        want = (c != ".") and (c in "_.-" or bool(bm[cp]))
        got = units._valid_job_id(c)
        if want != got and len(gate_mismatch) < 8:
            gate_mismatch.append("U+%04X 期望=%s 整闸=%s" % (cp, want, got))
    check("①b 全码点：**整闸** `_valid_job_id(c)` ≡ （结构字符 或 表成员），单独 `.` 被拒",
          not gate_mismatch,
          "；".join(gate_mismatch) if gate_mismatch else "已遍历 %d 码点" % (_MAX_CP + 1))
    check("① 两侧采纳码点数一致且非空（防「都空」假绿）",
          got_n == want_n and want_n > 0, "判据=%d 表=%d" % (got_n, want_n))
    check("① 表非空且与生产表段数一致（表就是生产读的那一份）",
          len(units.CHARSET_BLOCKS) == len(ranges),
          "生产 %d 段 / 独立重算 %d 段" % (len(units.CHARSET_BLOCKS), len(ranges)))
    check("① 结构字符 `_` `.` `-` **不在表内**（结构分支承载，不算字符类判据）",
          not any(units._charset_member(c) for c in "_.-"))


# ---------------------------------------------------------------- [2] 语料逐例对照

def _load_corpus():
    rows = []
    for lineno, line in enumerate(_read_text(_CORPUS_REL).split("\n"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        verdict, hexs = parts[0].strip(), parts[1].strip()
        desc = parts[2].strip() if len(parts) > 2 else ""
        rows.append((lineno, verdict, hexs, bytes.fromhex(hexs).decode("utf-8"), desc))
    return rows


def group_corpus_parity():
    print("\n[2] 语料逐例对照（c10：md_cg 面 vs 语料 verdict）")
    rows = _load_corpus()
    check("② 语料可读且例数非零（防读出空表假绿）", bool(rows), "%d 例" % len(rows))
    diverge, wrong, dev_rows = [], [], []
    for lineno, verdict, _hexs, jid, desc in rows:
        want = verdict == "accept"
        got = units._valid_job_id(jid)
        # 设备名例的**机械识别**（不看注释措辞）：整 id 或按 `_` 分段的任一段命中保留名
        # ——这些例必须逐例显式断「仍被拒」（c9）。
        is_dev = (units._is_reserved_device_name(jid)
                  or any(units._is_reserved_device_name(seg)
                         for seg in jid.split("_")))
        if is_dev:
            dev_rows.append((lineno, jid))
            if got:                     # 设备名逐例显式断（c9）：不得因换面被放行
                wrong.append("第 %d 行设备名例被收：%r" % (lineno, jid))
        if got == want:
            continue
        if jid in _CORPUS_DIVERGENCES and got:
            diverge.append(jid)
            continue
        wrong.append("第 %d 行不同判：语料=%s md_cg=%s id=%r（%s）"
                     % (lineno, verdict, got, jid, desc[:60]))
    check("② 逐例同判（有意差异除外）", not wrong, "；".join(wrong[:4]))
    check("② 实际差异集 **恰好等于** 显式登记的有意差异集（多/少一条都红）",
          set(diverge) == set(_CORPUS_DIVERGENCES),
          "实际=%r 登记=%r" % (sorted(diverge), sorted(_CORPUS_DIVERGENCES)))
    check("② 语料内设备名拒例已逐例显式断言（c9）", bool(dev_rows),
          "%d 例：%s" % (len(dev_rows), "、".join("%d:%s" % t for t in dev_rows)))
    # 注释点名的设备名例（80/81/82 行）必须被机械识别覆盖；83/84 行（"COM1 段"/"LPT9 段"）
    # 注释只写形态不写「设备名」三字，故用**子集**关系断言（不是相等——注释措辞不是判据面）。
    named = {ln for ln, _v, _h, jid, desc in rows
             if "设备名" in desc and not units._valid_job_id(jid)}
    check("② 注释点名「设备名」的拒例 ⊆ 机械命中的设备名例（注释不是判据面，故取子集）",
          named <= {ln for ln, _j in dev_rows},
          "注释点名=%r 机械=%r" % (sorted(named), sorted(ln for ln, _j in dev_rows)))
    for jid in _PREFIX_ONLY_CASES:
        check("② 语料外：前缀差异钉 md_cg 侧（有意收 %r；hive 侧判 reject）" % jid,
              units._valid_job_id(jid) is True)


# ---------------------------------------------------------------- [3] 拒收面逐条

_GOOD = "h_端_任务_记录单元_0001"
_GOOD_OLD = "h1758000000000_1a2b"


def group_reject_surface():
    print("\n[3] 拒收面逐条显式断言（c9/c7）")
    vj = units._valid_job_id

    # ---- 不可见注入载体：逐码点（零宽 + 双向控制），三个插入位
    invisible = ([(u, "零宽/不可见注入载体", None)
                  for u in list(range(0x200B, 0x2010)) + [0x2060, 0xFEFF]] +
                 [(u, "双向控制", None)
                  for u in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))])
    bad_invisible = []
    for u, kind, _ in invisible:
        c = chr(u)
        for form in (c + _GOOD, "h_端" + c + "_任务_记录单元_0001",
                     _GOOD + c, "j_" + c + "x"):
            if vj(form):
                bad_invisible.append("U+%04X(%s) 被放行" % (u, kind))
    check("③ 零宽（U+200B..200F/U+2060/U+FEFF）与双向控制（U+202A..202E/U+2066..2069）"
          "逐码点拒（%d 码点 × 4 插入位）" % len(invisible), not bad_invisible,
          "；".join(bad_invisible[:4]))

    # ---- 控制字符：C0 全段 / DEL / C1 全段，三个插入位
    ctrls = list(range(0x00, 0x20)) + [0x7F] + list(range(0x80, 0xA0))
    bad_ctrl = []
    for u in ctrls:
        c = chr(u)
        for form in (c + _GOOD, "h_端" + c + "_任务_记录单元_0001", _GOOD + c):
            if vj(form):
                bad_ctrl.append("U+%04X 被放行" % u)
    check("③ 控制字符（C0 0x00..0x1F / DEL 0x7F / C1 0x80..0x9F，含 NUL）逐码点拒",
          not bad_ctrl, "；".join(bad_ctrl[:4]))

    # ---- 路径成分与点形态/空白
    bad_cases = {
        "路径分隔符 /": ["h_端/任务_记录单元_0001", "h/../../x", "/etc", "a/b"],
        "路径分隔符 \\": ["h_端\\x", "..\\victim", "a\\b"],
        "盘符 / ADS :": ["C:x", "h:x", "h_端:1"],
        "相对父段": ["..", "../outside", "../victim"],
        "单独的 . 与 ..": [".", "..", "...", "h_端_任务_记录单元_.."],
        "尾点（Win32 静默剥）": ["x.", "h.", _GOOD + ".", "h_端_任务_."],
        "首尾空白（Win32 静默剥）": [" x", "x ", "   ", "\t" + _GOOD, _GOOD + "\n",
                                     "\u3000x"],
        "空串与超长（>128）": ["", "h" + "a" * 128],
        "非 str（不 str() 归一）": [123, None, 1.5, ["a"], {"a": 1}, b"habc"],
    }
    for kind, ids in bad_cases.items():
        bad = [r for r in ids if vj(r)]
        check("③ 拒：%s（%d 例）" % (kind, len(ids)), not bad, "被放行 %r" % (bad[:3],))

    # ---- 长度边界：128 收 / 129 拒（既有结构判据保留）
    check("③ 长度边界保留：128 收、129 拒",
          vj("h" + "a" * 127) is True and vj("h" + "a" * 128) is False)

    # ---- Windows 保留设备名：22 名 × 5 形态（旧 ASCII 白名单下全字母形态是**放行**的）
    names = units.RESERVED_DEVICE_NAMES
    bad_dev = []
    for name in names:
        for form in (name, name.lower(), name.title(), name + ".txt",
                     name.lower() + ".txt"):
            if vj(form):
                bad_dev.append(form)
        for form in ("h_端_任务_" + name + "_0001", "h_" + name.lower() + "_x",
                     "h_端_" + name + ".txt_记录单元_0001", "j_" + name.lower() + "_y"):
            if vj(form):
                bad_dev.append(form)
    check("③ Windows 保留设备名逐名拒（%d 名：整 id / 小写 / 首字母大写 / CON.txt 形态 / "
          "按 `_` 分段任一段）" % len(names), not bad_dev, "被放行 %r" % (bad_dev[:4],))
    check("③ 设备名判据 ASCII 大小写不敏感（不用 str.upper() 的 Unicode 折叠面）",
          units._is_reserved_device_name("cOn.TxT") is True
          and units._is_reserved_device_name("CONSOLE") is False
          and units._is_reserved_device_name("端") is False)

    # ---- 既有对外契约不误杀（前缀放宽 + `-` 放宽 + 点放宽）
    good_cases = {
        "新形态中文四槽 id": _GOOD,
        "旧形态 id（存量零迁移）": _GOOD_OLD,
        "契约示例（五单元第五项）": "h_维生系统_反思路_记录单元_0001",
        "非尾点、非单独的点": "h_a.b",
        "允许 `-`（既有对外契约）": "h_端-1_任务_记录单元_0001",
        "语料 accept 例「仅 h 前缀」": "h",
        "既有测试契约名（不要求 h 前缀）": "j_empty",
    }
    for kind, jid in good_cases.items():
        check("③ 收：%s %r" % (kind, jid), vj(jid) is True)

    # ---- 换面确实放宽了：旧机制拒而表收的 14 码点（正向证据，非漏判）
    bad_widen = [u for u in _WIDENED_CODEPOINTS
                 if not (units._charset_member(chr(u))
                         and vj("h_%s_任务_记录单元_0001" % chr(u)) is True)]
    check("③ 换面放宽集（旧机制拒 / 表收的 14 码点）现在被收",
          not bad_widen, "未收 %r" % ["U+%04X" % u for u in bad_widen])


# ---------------------------------------------------------------- [4] 三处调用点

def group_call_points():
    print("\n[4] 三处调用点语义不变（submit 落点前 / poll / wait fail-fast）")
    tmp = tempfile.mkdtemp(prefix="mdcg_charset_parity_")
    try:
        pool = os.path.join(tmp, "pool")
        os.makedirs(pool)
        # 结构对照物：合法但池内不存在的 id → poll 的正常形态（键集即契约）
        ref = units.poll("j_none", jobs=pool)
        ref_keys = set(ref)
        probe = ["h_端_任务_记录单元_0001\u200b", "h_端\u202e_任务_记录单元_0001",
                 "h_端_任务_记录单元_0001\x00", "h_端/任务_记录单元_0001",
                 "CON", "h_端_任务_COM1_0001", "x.", " x", "../victim", "h" + "a" * 128]
        for jid in probe:
            r = units.poll(jid, jobs=pool)
            ok = (r.get("state") == "invalid_job_id" and r.get("ok") is False
                  and r.get("terminal") is False and r.get("content") is None
                  and r.get("job_dir") is None and r.get("status") is None
                  and "非法" in str(r.get("error") or "")
                  and set(r) == ref_keys)
            check("④ poll 结构化拒且与既有返回**同键集**：%r" % (jid[:24],), ok,
                  "keys=%r state=%r" % (sorted(r), r.get("state")))
            w = units.wait(jid, jobs=pool, timeout_s=0.3, poll_s=0.05)
            check("④ wait 同闸且 fail-fast（不进轮询）：%r" % (jid[:24],),
                  w.get("state") == "invalid_job_id" and w.get("content") is None
                  and "timeout" not in w and w.get("waited_s") is None,
                  "state=%r waited_s=%r" % (w.get("state"), w.get("waited_s")))

        # submit 落点前：注入生成器产出坏 id（证明落点靠闸，不靠生成器自觉）
        escaped = os.path.join(tmp, "escaped")
        orig_gen = units._job_id
        try:
            for bad_id in ("../escaped", "CON", "h_端_任务_记录单元\u200b"):
                units._job_id = lambda bid=bad_id: bid
                r = units.submit(prompt="探针", role=units.REFLECT,
                                 model="stub-model", jobs=pool)
                check("④ submit 落盘前拒 %r（ok=False）" % bad_id,
                      r.get("ok") is False and "非法" in str(r.get("error") or ""),
                      str(r)[:120])
        finally:
            units._job_id = orig_gen
        check("④ 池外未建出 escaped/spec.json（闸在 makedirs 之前）",
              not os.path.isfile(os.path.join(escaped, "spec.json")))

        # 合法闭环不回归：submit → poll 仍可用（闸不误杀生成器产物）
        sub = units.submit(prompt="探针", role=units.REFLECT, model="stub-model",
                           jobs=pool)
        check("④ 合法 submit 仍可用（生成 id 必过闸）",
              sub.get("ok") is True and units._valid_job_id(sub.get("job_id")) is True,
              str(sub)[:120])
        p = units.poll(sub.get("job_id"), jobs=pool)
        check("④ 合法 poll 读到 pending（不误伤正常路径）",
              p.get("state") == "pending" and p.get("terminal") is False,
              "state=%r" % p.get("state"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- [5] 表自身的既正面

def group_table_hygiene():
    print("\n[5] 表的既有面：可重跑陈化守卫 / NFC 稳定 / fail-closed / 有意不收段")
    p = subprocess.run([sys.executable, "-X", "utf8", _GEN_REL, "--check"],
                       cwd=_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1"), shell=False)
    check("⑤ `gen_id_charset_blocks.py --check` 退出 0（表与生成规则一致，手改即陈化）",
          p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-160:].replace("\n", " "))

    # 跨版本豁免面（2026-10-03 外部报告核验新增）：表是「某版本快照」——当本机
    # unicodedata **低于**表快照（如用 python 3.11 复核 15.0.0 表）时，--check 走
    # 豁免路径（rc 仍 0）且必须**明示理由**（不静默）；同版本/升级态仍走原判据。
    _out = (p.stdout or "") + (p.stderr or "")
    _tv = None
    try:
        with open(os.path.join(_REPO, _BLOCKS_REL), encoding="utf-8") as _fh:
            for _ln in _fh:
                _m = re.search("unicodedata 版本：([0-9.]+)", _ln)
                if _m:
                    _tv = _m.group(1)
                    break
    except OSError:
        _tv = None
    if _tv and tuple(int(x) for x in unicodedata.unidata_version.split(".")) < tuple(int(x) for x in _tv.split(".")):
        check("⑤ 跨版本豁免：本机 %s < 表快照 %s ⇒ --check 明示豁免理由（不静默、rc 0）"
              % (unicodedata.unidata_version, _tv),
              "陈化守卫豁免" in _out, _out[-160:].replace("\n", " "))

    # NFC（c5）：表内每一码点本地重算都 NFC 稳定 ⇒ 判据不必做真 NFC 计算
    unstable = []
    total = 0
    for lo, hi in units.CHARSET_BLOCKS:
        for cp in range(lo, hi + 1):
            total += 1
            c = chr(cp)
            if unicodedata.normalize("NFC", c) != c:
                unstable.append("U+%04X" % cp)
    check("⑤ 表内每码点 NFC 稳定（%d 码点，本地 unicodedata 重算）" % total,
          not unstable, "；".join(unstable[:4]))

    # fail-closed：空表 / 坏行 / 相邻（未归并）/ 逆序 / 越界 → 判据一律 False。
    # 注：「相邻」= 后段起点 <= 前段终点+1（必须并成一段）；`0030-0039` 与 `0040-0045`
    # **不是**相邻（0x3A..0x3F 之间留了真实空隙：标点/符号被类目过滤掉），故它必须 Ok
    # ——与 `job.rs` 单测同判（`parse_id_charset_blocks("0030-0039\n0040-0045").is_ok()`）。
    for text, why in [("", "空表"),
                      ("# 只有注释\n\n", "只有注释"),
                      ("0030\n", "不是 LO-HI"),
                      ("0030-0039\n003A-003F", "相邻未归并"),
                      ("0030-0039\n0038-0045", "相交未归并"),
                      ("0050-0040", "逆序"),
                      ("0030-11000000", "越界")]:
        try:
            units._parse_charset_blocks(text)
            raised = False
        except ValueError:
            raised = True
        check("⑤ 坏表解析抛 ValueError（%s）⇒ fail-closed" % why, raised)
    check("⑤ 留真实空隙的表**不**算未归并（0030-0039 / 0040-0045 → 2 段，与 rust 同判）",
          units._parse_charset_blocks("0030-0039\n0040-0045")
          == [(0x30, 0x39), (0x40, 0x45)])
    saved = units.CHARSET_BLOCKS
    try:
        units.CHARSET_BLOCKS = ()
        check("⑤ 空表下判据对一切字符 False（绝不放行）",
              units._charset_member("a") is False
              and units._valid_job_id(_GOOD) is False
              and units._valid_job_id("h1758000000000_1a2b") is False)
    finally:
        units.CHARSET_BLOCKS = saved
    check("⑤ 恢复后判据复原（上一条不留副作用）",
          units._charset_member("a") is True and units._valid_job_id(_GOOD) is True)

    # c4 的「有意不收」段：整段 + 单例都在表外
    in_table = [("U+%04X" % cp, why) for lo, hi, why in _EXCLUDED_RANGES
                for cp in range(lo, hi + 1) if units._charset_member(chr(cp))]
    check("⑤ c4「有意不收」段**整段**在表外（Jamo / 兼容 Jamo / CJK 兼容表意(补充) / "
          "组合标记）", not in_table, "；".join("%s（%s）" % t for t in in_table[:3]))
    singles = [("U+%04X" % cp, why) for cp, why in _EXCLUDED_SINGLES
               if units._charset_member(chr(cp))]
    check("⑤ c4「有意不收」单例在表外（兼容分解/带圈/上下标/数学字母/全角半角/连字等）",
          not singles, "；".join("%s（%s）" % t for t in singles[:3]))

    # 同源（c2）：三处读者读的是同一份数据——md_cg 面以文本读 hive 侧源码，
    # **不 import hive**（零依赖家法）。
    check("⑤ md_cg 面登记的表路径 == 契约路径", units._CHARSET_BLOCKS_REL == _BLOCKS_REL,
          repr(units._CHARSET_BLOCKS_REL))
    mcp_text = _read_text("hive/hive_mcp/mcp_server.py")
    check("⑤ python 孪生闸读同一份数据（mcp_server 出现同一 rel 路径字面量）",
          '"%s"' % _BLOCKS_REL in mcp_text)
    rust_text = _read_text("hive/src/job.rs")
    check("⑤ rust 侧include_str! 同一份数据（编译期嵌入）",
          'include_str!("../id_charset_blocks.txt")' in rust_text)
    check("⑤ 生成脚本在库（c3：表由脚本生成、可重跑）",
          os.path.isfile(os.path.join(_REPO, _GEN_REL)))


def main():
    print("=" * 68)
    print("md_cg units · 字符集闸「区块白名单」同源/同判守卫（c8/c9/c10/c12）")
    print("=" * 68)
    group_charset_equals_table()
    group_corpus_parity()
    group_reject_surface()
    group_call_points()
    group_table_hygiene()
    print("\n" + "=" * 68)
    print("PASS=%d  FAIL=%d" % (PASS, FAIL))
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
