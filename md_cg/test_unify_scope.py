# -*- coding: utf-8 -*-
"""统一归一层作用域收窄守卫（2026-09-30 使用者裁定）

口径：`semantic/unify.py::unify_query` **只对英文内容做翻译归一，中文内容
原样不动**——query 按中文段/非中文段切开，中文段逐字保留、绝不送 segment。
旧口径「含任一 ASCII 字母即整条归一」把中夹英 query 的中文部分逐字切开
（「自我接纳」→「自 我 接 纳」），本件钉住收窄后的语义。

两侧同源：期望值取自 `md_cg/semantic/unify_fixture.json`——Rust 侧
`rust/src/atoms.rs::tests::unify_mixed_fixture_matches_python` 用 include_str!
嵌入**同一份**文件；任一侧漂移即红（两侧逐位相同）。

跑法：python -X utf8 -m md_cg.test_unify_scope
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg.semantic.canonical import is_zh_char      # noqa: E402
from md_cg.semantic.unify import unify_on, unify_query  # noqa: E402

FIXTURE = os.path.join(HERE, "md_cg", "semantic", "unify_fixture.json")

N = 0
BAD = []


# 生效条件：单参 cond 为真值判定、msg 为说明串；恒累加计数 N，cond 为假时把 msg 记入模块级 BAD（**不中断**）——收集式断言使「定点变异红了几项」可数（首条即停的 assert 风格数不出红项数）。
def ok(cond, msg):
    global N
    N += 1
    if not cond:
        BAD.append(msg)


# 生效条件：单参 text 为任意字符串，按 canonical.is_zh_char 切出其中的中文连续段，返回保序的段列表（无中文段时为空列表）；仅供本守卫做「中文段逐字保留」的结构判据。
def zh_runs(text):
    """文本里的中文连续段（判据同 unify_query：canonical.is_zh_char）。"""
    out, buf = [], []
    for ch in text:
        if is_zh_char(ch):
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


# ---- 1 · 开关语义不变（默认开；=0 一律原样）----
ok(unify_on() is True, "MDCG_UNIFY_QUERY 默认开（口径转正）")
os.environ["MDCG_UNIFY_QUERY"] = "0"
try:
    ok(unify_on() is False, "=0 显式关")
    for t in ("I eat beef yesterday", "领养 LGBTQ 群体", "自我接纳",
              "  beef 报告  ", "2024 报告"):
        ok(unify_query(t) == t, "开关关：一律原样返回 %r" % t)
finally:
    os.environ.pop("MDCG_UNIFY_QUERY", None)

# ---- 2 · 空/None/无 ASCII 字母：原样返回（未 strip 的入参）----
ok(unify_query(None) is None, "None 原样")
ok(unify_query("") == "", "空串原样")
ok(unify_query("  自我接纳  ") == "  自我接纳  ",
   "纯中文（无 ASCII 字母）原样返回入参本身（不 strip）")
ok(unify_query("2024 报告") == "2024 报告", "纯中文+数字（无字母）原样")
ok(unify_query("，。") == "，。", "纯标点（无字母）原样")

# ---- 3 · 纯英文仍翻译（收窄不得关掉英文链路）----
ok(unify_query("I eat beef yesterday") == "我 吃 牛肉 昨天",
   "纯英文仍归一：%r" % unify_query("I eat beef yesterday"))
ok(unify_query("wrote") == "写", "纯英文时态还原仍生效")

# ---- 4 · 纯中文原样（旧口径会被逐字切开）----
for t, why in (("自我接纳", "旧口径「自 我 接 纳」"),
               ("慈善跑", "旧口径「慈 善 跑」"),
               ("蜂群调度 依赖门禁", "旧口径逐字切开")):
    ok(unify_query(t) == t, "纯中文原样（%s）：%r" % (why, t))

# ---- 5 · fixture 逐位对拍（两侧同源：Rust 侧嵌同一份文件）----
with open(FIXTURE, encoding="utf-8") as f:
    FX = json.load(f)["cases"]
ok(len(FX) >= 12, "fixture 用例数 >= 12：%d" % len(FX))
for c in FX:
    got = unify_query(c["in"])
    ok(got == c["out"],
       "fixture 逐位不符 [%s] in=%r got=%r want=%r"
       % (c["name"], c["in"], got, c["out"]))

# ---- 5b · 单侧钉：任务原型例（Python 侧形态）----
# 这两例**不入共享 fixture**：非中文段是未登录的**大写**词（LGBTQ），两侧对
# 「未命中词表的大写词」存在**既有**非对称（Python 保留原大小写 / Rust 经
# normalize_en 一律 lower 化——用 rust 单测实测 `领养 lgbtq 群体` 取证，
# 2026-09-30），故两侧钉不出同一期望值。此非本次收窄引入，也非本次范围；
# 但它是端到端（Python 侧）实际生效的形态，故在此单侧钉死。
for t in ("领养 LGBTQ 群体 支持 包容", "领养 机构 LGBTQ 群体 支持 包容"):
    ok(unify_query(t) == t, "中夹英原型例：中文段逐字保留、英文片段原样：%r" % t)

# ---- 6 · 结构判据：混合 query 的中文段逐字保留（不切分、不送 segment）----
for c in FX:
    for run in zh_runs(c["in"]):
        ok(run in c["out"],
           "中文段被切开/改写 [%s] 段=%r out=%r" % (c["name"], run, c["out"]))
ok(zh_runs("领养 LGBTQ 群体") == ["领养", "群体"], "中文段抽取判据自检")

# ---- 7 · 空白折叠为单空格（段内/段间）----
ok(unify_query("  beef   报告  ") == "牛肉 报告", "前后空白+多空格折叠")
ok(unify_query("beef\t报告") == "牛肉 报告", "制表符折叠为单空格")

# ---- 8 · 异常降级为原样（不阻断检索主链路）----
import md_cg.semantic.canonical as _cn   # noqa: E402
_saved = _cn.query_atoms
_cn.query_atoms = lambda _t: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    src = "beef 报告"
    ok(unify_query(src) == src, "链路抛异常 → 原样返回")
finally:
    _cn.query_atoms = _saved

if BAD:
    print("[test_unify_scope] FAILED %d/%d 断言：" % (len(BAD), N))
    for b in BAD:
        print("  - " + b)
    raise SystemExit(1)
print("[test_unify_scope] %d 断言全绿（fixture %d 例，两侧同源）" % (N, len(FX)))
