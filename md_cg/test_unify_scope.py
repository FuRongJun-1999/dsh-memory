# -*- coding: utf-8 -*-
"""统一归一层作用域收窄守卫（2026-09-30 使用者裁定）

口径：`semantic/unify.py::unify_query` **只对英文内容做翻译归一，中文内容
原样不动**——query 按中文段/非中文段切开，中文段逐字保留、绝不送 segment。
旧口径「含任一 ASCII 字母即整条归一」把中夹英 query 的中文部分逐字切开
（「自我接纳」→「自 我 接 纳」），本件钉住收窄后的语义。

**开关前提**：归一层缺省**关**（2026-09-30 使用者裁定，唯一开态 = 显式
`MDCG_UNIFY_QUERY=1`）；本件第 1 节钉三态，其后各节一律**显式开**下跑。
缺省态的三态与两侧一致性守卫见 `md_cg/test_unify_default_off.py`。

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


# ---- 1 · 开关三态（2026-09-30 使用者裁定：缺省由开翻为关；唯一开态 = 显式 "1"）----
# 本件测的是**作用域收窄**语义，故从本节之后各节必须在**显式开**（=1）下跑：
# 缺省已关（未设即关），若不显式开，下面 3~8 节全会退化成恒真（对实现零约束力）。
# 缺省三态守卫另立一件：md_cg/test_unify_default_off.py（两件分工不同，勿互推）。
ok(unify_on() is False,
   "MDCG_UNIFY_QUERY 未设即关（缺省关，2026-09-30 翻）")
os.environ["MDCG_UNIFY_QUERY"] = "0"
try:
    ok(unify_on() is False, "=0 显式关")
    for t in ("I eat beef yesterday", "领养 LGBTQ 群体", "自我接纳",
              "  beef 报告  ", "2024 报告"):
        ok(unify_query(t) == t, "开关关：一律原样返回 %r" % t)
finally:
    os.environ.pop("MDCG_UNIFY_QUERY", None)
os.environ["MDCG_UNIFY_QUERY"] = "1"
ok(unify_on() is True, "=1 显式开（英文对照路要用）——本件余下各节的运行前提")

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

# ---- 6 · 结构判据（对**实现产物**断言）：混合 query 的中文段逐字保留 ----
# 2026-09-30 清理批次（甲2）修假守卫：本节此前比的是 fixture 的**期望值**
# （`run in c["out"]`——拿期望比期望），对实现零约束力：做「中文段也送
# segment」变异时本节 0 项红。现改为直接调 `unify_query` 并对**产物**断言：
# 中文段必须在产物里逐字出现，且其逐字切开形（`" ".join(run)`）不得出现。
# 单字中文段（如「年」）的切开形与其本身同形，故切开判据只在 len(run) > 1
# 时施加（否则是恒假的伪红）。
for c in FX:
    got = unify_query(c["in"])
    for run in zh_runs(c["in"]):
        ok(run in got,
           "中文段未逐字保留（被改写）[%s] in=%r 段=%r got=%r"
           % (c["name"], c["in"], run, got))
        if len(run) > 1:
            ok(" ".join(run) not in got,
               "中文段被逐字切开（送了 segment）[%s] in=%r 段=%r got=%r"
               % (c["name"], c["in"], run, got))
# 原型例（任务口径原句）同样对产物断言：中文段逐字保留、英文片段不动
for t in ("领养 LGBTQ 群体", "AI 记忆 系统", "自我接纳", "蜂群调度 依赖门禁"):
    got = unify_query(t)
    for run in zh_runs(t):
        ok(run in got and " ".join(run) not in got,
           "原型例中文段逐字保留 [%r] 段=%r got=%r" % (t, run, got))
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

# ---- 9 · 中文判据边界（2026-09-30 清理批次乙2）：仅长度恰为 1 的串可为真 ----
# 事实读数（本机实测，见清理批次回执）：留池条目 ⑥ 记「`is_zh_char("")` 返回
# True」——**实测不成立**：`ZH_LO <= ch <= ZH_HI` 是链式比较，对空串即假，
# 收紧前 `is_zh_char("")` 已返回 False。真实外溢面是**多字符串**——
# 收紧前 `is_zh_char("中文")` 判真（首字符在区间即真）。两处消费点
# （unify._runs / 本文件 zh_runs）均逐字符传入，故本收紧对存量行为零变更，
# 只把判据面（长度恰为 1）钉死。
ok(is_zh_char("") is False, "空串不是中文（判据面外）")
ok(is_zh_char("中文") is False, "多字符串为假（首字符在区间亦然）")
ok(is_zh_char("中a") is False, "多字符串为假（汉字+ASCII 混合）")
ok(is_zh_char("中") is True, "单汉字为真")
ok(is_zh_char("\u4e00") is True, "区间下界单汉字为真")
ok(is_zh_char("\u9fff") is True, "区间上界单汉字为真")
ok(is_zh_char("\u4dff") is False, "区间下界外单字符为假（U+4DFF）")
ok(is_zh_char("\ua000") is False, "区间上界外单字符为假（U+A000）")
ok(is_zh_char("a") is False, "单 ASCII 字母为假")
# 两侧边界语义一致性：Rust `text::is_zh` 收 char，天然无空/多字符二态；
# 本侧判据收紧后，「长度 != 1 一律 False」与「按 char 判区间」等价
# （见 rust/src/text.rs::is_zh docstring 的边界约定段）。
for ch in ("\u4e00", "\u9fff"):
    ok(is_zh_char(ch) and len(ch) == 1, "单字符区间内 → 真（与 Rust is_zh 等价）%r" % ch)

os.environ.pop("MDCG_UNIFY_QUERY", None)   # 归还进程环境（本件全程已显式开完）

if BAD:
    print("[test_unify_scope] FAILED %d/%d 断言：" % (len(BAD), N))
    for b in BAD:
        print("  - " + b)
    raise SystemExit(1)
print("[test_unify_scope] %d 断言全绿（fixture %d 例，两侧同源）" % (N, len(FX)))
