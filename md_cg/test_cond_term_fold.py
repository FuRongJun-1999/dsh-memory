# -*- coding: utf-8 -*-
"""守卫：正条件面的字符归一（与负条件面同口径）。

背景：`neg_condition_hits` 从 #362b/c 起两侧都过 `fold_for_match`（NFKC + casefold
+ 繁简 + 剥 Mn），但 `MdCG._term_in_scene`（正条件面的唯一命中判据，PR #735 引入）
两侧都是**裸原文**。同一份判据的两个面因此口径分裂：

    负条件 item='PE' vs 场景 'pe 为负'   → 命中
    正条件 term='PE' vs 场景 'pe 为负'   → 不命中

后果：条件里写了 `PE`，用户把英文打成小写就永远 DEFER。
本文件把两侧口径钉在一起，并锁住「补归一时不得放宽词边界」。

运行：python -X utf8 -m md_cg.test_cond_term_fold
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from .mdcg import MdCG, fold_for_match, neg_condition_hits
from . import nodefile

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL:", label)


def _node(cond_text, neg=None):
    return {
        "frontmatter": {
            "verification_basis": "test",
            "non_applicable_conditions": neg or [],
        },
        "content": (
            "# 功能名：探针\n"
            "# 生效条件：" + cond_text + "\n"
            "# 子功能：x\n"
            "# 执行：y\n"
            "# 验证方式：z\n"
            "# 不适用条件：无\n"
        ),
    }


COND = "载体/位置：QuantBot2 backend；方法：PE、估值；约束：无"
TERMS = nodefile.condition_terms_diag(COND)["terms"]

print("=" * 68)
print("A. 切分结果（前置条件：`PE` 是独立词项，不是长句的一部分）")
print("=" * 68)
ok("PE" in TERMS, "A1 `PE` 必须被切成独立词项（否则本守卫测不到归一）")
print("  terms =", TERMS)

print()
print("=" * 68)
print("B. 正条件面：同一词项，问句只改大小写/全半角")
print("=" * 68)
for q in ("PE 为负怎么处理", "pe 为负怎么处理", "Pe 为负怎么处理",
          "ＰＥ 为负怎么处理"):
    ok(MdCG._term_in_scene("PE", q) is True,
       "B 正条件 term='PE' 必须命中 %r" % q)
    _r = MdCG.judge_qualification(_node(COND), q)
    ok(_r["state"] == "ACCEPT" and "命中「PE」" in (_r.get("reason") or ""),
       "B 端到端 %r 必须 ACCEPT 且 reason 记录命中词（实际 %r）"
       % (q, _r.get("reason")))

print()
print("=" * 68)
print("C. 归一这一半口径必须一致（词边界是两面**有意**不同的一半，见 C4）")
print("=" * 68)
for term, scene in [("PE", "pe 为负"), ("PDF", "pdf 扫描件"),
                    ("4G单模", "4g单模终端")]:
    pos = MdCG._term_in_scene(term, scene)
    neg = bool(neg_condition_hits([term], scene))
    ok(pos == neg, "C term=%r scene=%r 正条件=%s 负条件=%s（归一后必须相同）"
       % (term, scene, pos, neg))
# C4：**已知不对称（不是规范）**——词边界只在正条件面（#735），负条件面无词边界。
# 事实：api 在正条件面 False、负条件面 True。
# 理由：正条件词项来自条件空间**切分**（backend/app/core、/api/uzi 这类路径碎片），#735 收的是
#       「碎片误咬」；负条件来自**人工声明**的排除词（通常是完整词），#362 起从未收紧，
#       且漏拒/误拒代价不对称。
# 追踪：若负条件面也出现同类碎片误拒的现场报告，C4 应**同步翻转**并合并为统一判据；
#       本次不动是因为无现场证据，不是因为它正确。
ok(MdCG._term_in_scene("api", "apiserver") is False
   and bool(neg_condition_hits(["api"], "apiserver")) is True,
   "C4 词边界面有意不一致：正条件 False / 负条件 True（禁止误统一）")

print()
print("=" * 68)
print("D. 补归一时**不得放宽**词边界（PR #735 的 P1~P17 口径全部保持）")
print("=" * 68)
ok(MdCG._term_in_scene("api", "capital 结构是否合理") is False,
   "D1 api 不得命中 capital")
ok(MdCG._term_in_scene("app", "这个 mapping 对不对") is False,
   "D2 app 不得命中 mapping")
ok(MdCG._term_in_scene("core", "计算 score 的方式") is False,
   "D3 core 不得命中 score")
ok(MdCG._term_in_scene("pe", "type 字段") is False,
   "D4 pe 不得命中 type（新增，同族）")
ok(MdCG._term_in_scene("api", "后端 /api/uzi/peers 有没有问题") is True,
   "D5 api 在真路径里仍命中")
ok(MdCG._term_in_scene("UTC", "时区是 UTCX 还是本地") is False,
   "D6 UTC 右侧紧邻字母仍不命中")
ok(MdCG._term_in_scene("本机进程", "cpu本机进程是否可用") is True,
   "D7 中文紧邻拉丁字母仍命中")
ok(MdCG._term_in_scene("9:00", "到了上午 9:00 开始开会") is True,
   "D8 非字母 ASCII 仍走子串")

print()
print("D9. 收紧方向显式留痕：纯 ASCII 多词短语 / 全角 / 重音词项由「子串」搬入「词边界」")
print("    （复核判定：多数是修对了——api 不咬 capital，data flow 也不该咬 metadata flow；但必须可见）")
ok(MdCG._term_in_scene("data flow", "metadata flow 的说明") is False,
   "D9 data flow 不咬 metadata flow（由子串收紧为词边界）")
ok(MdCG._term_in_scene("A B", "XA B") is False,
   "D10 A B 不咬 XA B（同上）")
ok(MdCG._term_in_scene("ＰＥ", "ＰＥＴ 材料") is False,
   "D11 全角 ＰＥ 不咬 ＰＥＴ（归一路径改变）")
ok(MdCG._term_in_scene("Café", "CaféX 场景") is False,
   "D12 Café 不咬 CaféX（剥重音后进入词边界路径）")

print()
print("=" * 68)
print("E. 归一会去空白，词边界必须在**保留空白**的串上判（本条的踩坑点）")
print("=" * 68)
# fold_for_match 去全部空白："fdata financials" -> "fdatafinancials"
ok(fold_for_match("fdata financials") == "fdatafinancials",
   "E1 前置：fold_for_match 确实去空白")
ok(MdCG._term_in_scene("fdata", "fdata financials 的 ROE") is True,
   "E2 `fdata` 在 `fdata financials` 里是独立词（不得因去空白被误杀）")
ok(MdCG._term_in_scene("dsh-memory 插件", "dsh-memory 插件上游投稿") is True,
   "E3 带空格多词短语仍命中")
ok(MdCG._term_in_scene("形态 B", "纯中文形态 B 绕过") is True,
   "E4 中英混排短语仍命中")

print()
print("=" * 68)
print("F. 反向对照：不得超出「NFKC + casefold + 繁简 + 剥 Mn」多归一")
print("=" * 68)
ok(MdCG._term_in_scene("C++", "用 C 语言写") is False,
   "F1 `C++` 不得命中「C 语言」（不删标点）")
ok(MdCG._term_in_scene("A-B", "AB 两个字母") is False,
   "F2 `A-B` 不得命中「AB」（不删连字符）")

print()
print("=" * 68)
print("G. 空值/None 不得因归一而变真")
print("=" * 68)
ok(MdCG._term_in_scene(None, "任意") is False, "G1 None 不命中")
ok(MdCG._term_in_scene("", "任意") is False, "G2 空串不命中")
ok(MdCG._term_in_scene("   ", "任意 都有空白") is False, "G3 全空白不命中（含空白场景）")

print()
print("=" * 68)
print("H. 重音折叠（与负条件面同口径，issue #636 的 fold_accents）")
print("=" * 68)
ok(MdCG._term_in_scene("café", "cafe 场景") is True,
   "H1 预合成 é 侧需命中无重音查询")
ok(MdCG._term_in_scene("cafe", "café 场景") is True,
   "H2 反向同样成立（对称）")
ok(MdCG._term_in_scene("café", "café 场景") is True, "H3 原文命中")
ok(bool(neg_condition_hits(["café"], "cafe 场景"))
   == MdCG._term_in_scene("café", "cafe 场景"),
   "H4 重音这半边两面也必须同口径")
# issue #659：假名浊点不得被折叠（那是不同词，不是重音）
ok(MdCG._term_in_scene("が", "か") is False,
   "H5 假名浊点不折叠（#659：が ≠ か）")
ok(MdCG._term_in_scene("か", "\u304b\u3099") is False,
   "H6 NFD 形态浊点仍不折叠（が=か+U+3099；#659 只剥拉丁组合记号区）")
ok(MdCG._term_in_scene("ᾀ", "α") is True,
   "H7 归一顺序端到端：ᾀ → α（反序会得 αι ⇒ 不命中）")

print()
print("=" * 68)
print("cond_term_fold: %d passed, %d failed" % (PASS, FAIL))
print("=" * 68)
sys.exit(1 if FAIL else 0)
