# -*- coding: utf-8 -*-
r"""守卫 · #82 写入门禁禁表扩边界（2026-10-09 设计者裁定 + DSH 端实施）。

背景（修订前）：
  · 第 7 条 (?i)\b(password|passwd|pwd|密码|口令)\s*[:=：]\s*\S{6,} 有**双向**问题——
    漏：汉字之间无词边界，「我的密码：abc123456」判不中；
    伤：行首/空白后的「密码：三联体密码子…」（生物学知识）判中。
  · #82.1 修后：英文侧保留 \b、中文侧不加，并把值侧收紧为「含数字的连续凭据形态 token」；
    新增第 12 条覆盖「是/为/等于/is」形态。
  · #82.2（2026-10-09 二轮，本端实施）：第 7 条**分隔段**由 \s*[:=：]\s* 扩为
    (?:\s*[:=：]\s*|[ \t]+)——「横空白分隔」与「冒号/等号分隔」并列，故
    「纯空格形态」（密码 X）**不再是残留漏面**。刻意**不含换行**：\n 分隔的跨行匹配
    在 markdown 语料里易误伤，守本文件「宁漏勿伤」取向。值侧一字未动。

判据（真跑判定层，非字符串比对）：
  G1 三形态（是 / is / =）一律 REJECT
  G2 原漏的两个形态（句中冒号、= 中文前缀）现能 REJECT
  G3 误伤对照：生物学句「密码：三联体密码子…」**不得**命中（修前会命中）
  G4a 已知边界如实保留：纯字母值仍 ACCEPT（宁漏勿伤取向）
  G5 禁表条数=12 且可加载
  G6 #90 词边界形态四种一律 REJECT
  G7 #90 反向对照：mypassword 不是禁表词 ⇒ ACCEPT
  G8 #82.2 组：横空白分隔五种 ⇒ REJECT；误伤对照两条 ⇒ ACCEPT；如实边界两条 ⇒ ACCEPT
     （G8 取代原 G4b——原 G4b 断言「纯空格形态 ⇒ ACCEPT（已知残留漏面）」，本笔已收，
       该断言按实测翻转为 REJECT，见 G8a）

运行：python -X utf8 -m md_cg.test_issue82_credential_rules [--mutate A]
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点缺失（ANCHOR-MISS，不静默跳过）
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")

POLICY = os.path.join(REPO, "data", "policy.json")
RULE7_IDX = 6
RULE12_IDX = 11
# 注意：本文件源码里写 \\s / \\t，Python 解析后为 \s / \t（与 policy.json 解码后同形）
OLD_SEP = "\\s*[:=：]\\s*"
NEW_SEP = "(?:\\s*[:=：]\\s*|[ \\t]+)"
NEW_SEP_NL = "(?:\\s*[:=：]\\s*|\\s+)"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _verdict(rules, tail):
    from md_cg import audit
    return audit.VERIFIERS["text"]({"content": SIX + tail}, {"rules": rules}).get("state")


def _policy_text():
    return io.open(POLICY, encoding="utf-8").read()


def _anchor_preflight():
    """锚点前置检查（盘上文件，不是运行期对象）：第 7 条须含新分隔段、第 12 条须未被动。
    不满足 ⇒ ANCHOR-MISS 且 exit 2（**不静默跳过**，否则变异自证会变成空转）。"""
    try:
        d = json.loads(_policy_text())
    except Exception as exc:
        print("ANCHOR-MISS: policy.json 不可解析：%s" % exc)
        sys.exit(2)
    forb = d.get("forbidden") or []
    if len(forb) <= RULE12_IDX:
        print("ANCHOR-MISS: forbidden 条数不足（%d）" % len(forb))
        sys.exit(2)
    if NEW_SEP not in forb[RULE7_IDX]:
        print("ANCHOR-MISS: 第 7 条缺新分隔段")
        print("  期望含 = %r" % NEW_SEP)
        print("  盘上实读 = %r" % forb[RULE7_IDX])
        sys.exit(2)
    if "是|为|等于|is" not in forb[RULE12_IDX]:
        print("ANCHOR-MISS: 第 12 条形态已变（本守卫的 G1/G2 锚点失效）")
        print("  盘上实读 = %r" % forb[RULE12_IDX])
        sys.exit(2)


def _cases(rules):
    """判据表：返回 [(name, ok, detail)]。正跑与变异**共用同一张表**。"""
    out = []

    def add(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    forb = rules.get("forbidden") or []
    add("G5 禁表可加载且条数=12", len(forb) == 12, "n=%d" % len(forb))

    for name, tail in (("是形态·中文", "我的密码是abc123456"),
                       ("is形态·英文", "the password is abc123456"),
                       ("=形态·中文前缀", "我的密码=abc123456")):
        add("G1 %s ⇒ REJECT" % name, _verdict(rules, tail) == "REJECT",
            str(_verdict(rules, tail)))

    for name, tail in (("句中冒号（原漏）", "我的密码：abc123456"),
                       ("= 中文前缀（原漏）", "我的密码=abc123456")):
        add("G2 %s ⇒ REJECT" % name, _verdict(rules, tail) == "REJECT",
            str(_verdict(rules, tail)))

    # ---- issue #90（2026-10-09）：词边界在中文/下划线前失效的三种形态 ----
    for _name, _tail in (("xx密码：", "数据库密码：Hunter2Secret"),
                         ("xx口令=", "邮箱口令=Hunter2Secret"),
                         ("x_password=", "db_password=Hunter2Secret"),
                         ("user_passwd:", "user_passwd: Hunter2Secret")):
        add("G6 #90 形态 %s ⇒ REJECT" % _name, _verdict(rules, _tail) == "REJECT",
            str(_verdict(rules, _tail)))

    add("G7 #90 反向对照：mypassword: ⇒ ACCEPT（不是禁表词）",
        _verdict(rules, "mypassword: Hunter2Secret") == "ACCEPT",
        str(_verdict(rules, "mypassword: Hunter2Secret")))

    bio = "密码：三联体密码子、简并性、通用性。起始密码子AUG、终止密码子。"
    add("G3 误伤对照·生物学句 ⇒ ACCEPT（修前会命中）",
        _verdict(rules, bio) == "ACCEPT", str(_verdict(rules, bio)))

    add("G4a 纯字母值 ⇒ ACCEPT（宁漏勿伤，已知边界）",
        _verdict(rules, "我的密码：abcdefgh") == "ACCEPT", "")

    # ---- G8 组（#82.2 纯空格形态已收；取代原 G4b）----
    for _name, _tail in (("中文前缀·空格", "我的密码 abc123456"),
                         ("禁表词·空格", "密码 abc123456"),
                         ("英文·空格", "password abc123456"),
                         ("口令·空格", "口令 abc123456"),
                         ("中文前缀·制表符", "我的密码\tabc123456")):
        add("G8 横空白分隔 %s ⇒ REJECT" % _name, _verdict(rules, _tail) == "REJECT",
            str(_verdict(rules, _tail)))

    _bio_sp = "密码 三联体密码子、简并性、通用性。"
    add("G8 误伤对照·空格版生物学句 ⇒ ACCEPT",
        _verdict(rules, _bio_sp) == "ACCEPT", str(_verdict(rules, _bio_sp)))
    _bio_ns = "密码子的简并性：多种密码子编码同一氨基酸"
    add("G8 误伤对照·无分隔（密码子）⇒ ACCEPT",
        _verdict(rules, _bio_ns) == "ACCEPT", str(_verdict(rules, _bio_ns)))
    _nl = "我的密码\nabc123456"
    add("G8 如实边界·换行分隔 ⇒ ACCEPT（有意不收：跨行匹配易误伤）",
        _verdict(rules, _nl) == "ACCEPT", str(_verdict(rules, _nl)))
    _short = "密码 abc12345"
    add("G8 如实边界·值尾长不足 ⇒ ACCEPT（值侧未动，宁漏勿伤）",
        _verdict(rules, _short) == "ACCEPT", str(_verdict(rules, _short)))
    return out


# ---------------- 定点变异自证（范式照 md_cg/test_w7_redlines.py） ----------------

def _copy_rules(rules):
    d = dict(rules)
    d["forbidden"] = list(rules.get("forbidden") or [])
    return d


def _mut_revert_sep(rules):
    """退化①：撤掉横空白分隔，退回 #82.1 的旧式 ⇒ 纯空格形态重新漏。"""
    f = rules["forbidden"]
    f[RULE7_IDX] = f[RULE7_IDX].replace(NEW_SEP, OLD_SEP)


def _mut_newline_sep(rules):
    """退化②：把分隔段放宽到含换行 ⇒ 本守卫钉的「不含换行」如实边界应转红。"""
    f = rules["forbidden"]
    f[RULE7_IDX] = f[RULE7_IDX].replace(NEW_SEP, NEW_SEP_NL)


_MUTATIONS = {
    "A": (
        ("撤掉横空白分隔（退回旧式，纯空格重新漏）", _mut_revert_sep,
         ("G8 横空白分隔 中文前缀·空格 ⇒ REJECT", "G8 横空白分隔 禁表词·空格 ⇒ REJECT",
          "G8 横空白分隔 英文·空格 ⇒ REJECT", "G8 横空白分隔 口令·空格 ⇒ REJECT",
          "G8 横空白分隔 中文前缀·制表符 ⇒ REJECT")),
        ("把分隔段放宽到含换行（越界扩张）", _mut_newline_sep,
         ("G8 如实边界·换行分隔 ⇒ ACCEPT（有意不收：跨行匹配易误伤）",)),
    ),
}


def _mutate(group):
    if group not in _MUTATIONS:
        print("未知变异组：%s（可用：%s）" % (group, sorted(_MUTATIONS)))
        return 2
    _anchor_preflight()
    base = _cases(_copy_rules(_load()))
    base_red = sorted(n for n, ok, _ in base if not ok)
    print("!! #82 禁表定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望" % group)
    print("")
    print("  未变异基线：红项 %d %s" % (len(base_red), base_red))
    bad = []
    for label, fn, expected in _MUTATIONS[group]:
        rules = _copy_rules(_load())
        fn(rules)
        red = sorted(n for n, ok, _ in _cases(rules) if not ok)
        ok = red == sorted(expected)
        print("  [%s] %s → 红项 %s（期望 %s）"
              % ("OK" if ok else "BAD", label, red, sorted(expected)))
        if not ok:
            bad.append(label)
    print("")
    if bad:
        print("变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("变异自证通过：%d 条各自**恰好**命中期望" % len(_MUTATIONS[group]))
    return 0


def _load():
    from md_cg import audit
    return audit.load_rulebook(POLICY)


def main():
    argv = sys.argv[1:]
    if "--mutate" in argv:
        i = argv.index("--mutate")
        group = argv[i + 1] if i + 1 < len(argv) else ""
        return _mutate(group)

    _anchor_preflight()
    rules = _load()
    for name, ok, detail in _cases(rules):
        check(name, ok, detail)

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
