# -*- coding: utf-8 -*-
"""守卫：#753 收尾三处缺口（正条件面 / 词面归一后的三道闸）。

背景：#753 把正条件面的**字符归一**与负条件面统一了（#755/#761）。但
`neg_condition_hits` 比正条件面还多**三道闸**，归一之后这三道闸的正确性
才真正暴露出来：

    ① 字符归一            ← #753 已修
    ② NEG_MIN_TERM        ← 本文件 R3 组
    ③ 自主题豁免 own_topic ← 已知同型缺口，真实库 0 落点，本补丁不修
    ④ 否定作用域 _negated_at ← 本文件 R2 组

另有 ⑤：归一化把非 str 场景 repr 化（`["pe"]` → `"['pe']"`），短词项恰好是
repr 的子串 ⇒ 判据从 fail-loud 变成静默 fail-open。本文件 R1 组。

**本文件覆盖的五类形态**（v9 起，勿再往上加「完备」的表述）：
    1. 空白宽度（词项内部零/双/NBSP）        —— R7d/R7e
    2. 词项末尾紧邻 ASCII 字母（右词边界）      —— R7f/R7g
    3. 边界**字符类**（除 `[A-Za-z]` 外谁都不算词边界字母）—— R7h
    4. 回填的准入面（词项自身折叠 / 非本族）      —— R7b/R7c
    5. 否定作用域：逐次出现 + `any` 语义        —— R2/R8/R8d/R8e/R8f/R8g

**不覆盖**：`NEG_SCOPE_WINDOW = 6` 这个**存量常量**的取值本身（#362a 引入，
不在本补丁 diff 内，本补丁只是复用它）。实测 6→4/5/7/8/12 在本文件上**全绿**
（只有 6→1 才红，那不是「窗口两端都有对照」，只是缩到极小后与 `NEG_MIN_TERM`
的交互崩了）。**K 组在 `test_issue362_neg_condition.py`，不在
`test_neg_condition_hits.py`** —— 2026-11-05 复核指出此处原先指错了文件，
且「窗口两端都有 K 组对照」这句话本身不成立。本文件管不到窗口，那侧属存量，
建议另开 issue 单独补 `NEG_SCOPE_WINDOW` 的定向守卫。

运行：python -X utf8 -m md_cg.test_cond_term_fold_gate
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from .mdcg import (MdCG, neg_condition_hits, fold_for_match_keep,
                   compact_exact_text)

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL:", label)


def ok_call(fn, label):
    """调用 `fn()` 并断言它返回 True。**异常记为失败，不中断模块**（复核第 10 轮 G③）。

    为什么需要它：`ok(expr, label)` 的 `expr` 在**进入 ok 之前**就求值了，
    所以任何在被测函数里抛出的异常都会**直接冒到模块顶层**，整个 gate 崩在
    那一条上，后面的断言**一条都不跑**。实测：把入口闸删掉时，
    `_term_in_scene("PE", b"pe")` 抛 TypeError，gate 在第 89 行中断 ——
    我原先拿「rc≠0」当 CAUGHT，其实那是**崩溃**，不是「被断言抓住」。

    **结果必须交回 `ok()` 记账**（不要自己 PASS += 1）：审计脚手架只
    替换 `ok()` 一处就能统计全部断言；自己记账会让审计少算一半。
    """
    try:
        _v = bool(fn())
        _exc = None
    except Exception as _e:                       # noqa: BLE001
        _v, _exc = False, type(_e).__name__
    ok(_v and _exc is None,
       label + (("  [EXC:%s]" % _exc) if _exc else ""))


print("=" * 68)
print("R1. 入口闸：非 str 场景必须 fail-closed")
print("=" * 68)
# 归一化内部 `str(text)` 会把容器 repr 化。短词项恰好是 repr 子串时，
# 判据就从「不命中」变成静默 fail-open —— 节点被错误判成 ACCEPT。
#
# **base 的真实行为不是「一律抛」**（实测，2026-11-04 三树对照）：
#   词边界支 term='PE'   scene=['pe']      -> TypeError
#   子串支   term='估值' scene=['估值']     -> **True**（`"估值" in ["估值"]`）
#                        scene={'估值':1}   -> **True**
# 故本闸相对 base 在「子串支 + 容器场景」上是**收紧**（pre=True → 补丁=False），
# 属召回损失；生产路径不可达（`judge_qualification` 恒传 `json.dumps` 的 str，
# 真实库 886 节点 0 落点），取 fail-closed 是**有意**的。本组断言钉的是
# 「本闸的结果」，不是「与 base 一致」——后者是错的。
def _safe(term, scene):
    """返回 `_term_in_scene` 的布尔结果；**异常统一折成 False**。

    **只用于「扫描型」断言**（BMP/星平面全扫、派生排除集这类批量探测）。
    不要用它写单点断言 —— 它把异常和 False 混为一谈，
    正是复核第 10 轮 G-A 指出的那个真空源的成因。
    """
    try:
        return MdCG._term_in_scene(term, scene)
    except Exception:                             # noqa: BLE001
        return False


# **两条分支都要钉**：`term='PE'` 走词边界支（`re.search` 对 list 直接抛
# TypeError，`_safe` 会把它吸收成 False —— 于是闸被撤掉这一支也测不出来）。
# 必须再补 `term='估值'`（走子串支，`t_fold in norm_scene.compact` 对 repr 串
# 是真命中 ⇒ 真正的静默 fail-open）。
_JQ = '{"query": "随便"}'
for _t, _sc in (("PE", {"k": "pe"}), ("PE", ["pe"]), ("PE", b"pe"),
                ("PE", {"x": "PE"}), ("PE", ["PE"]),
                ("估值", ["估值"]), ("估值", ("估值",)), ("估值", {"估值": 1}),
                ("估值", ["估值X"])):
    # 用 `ok_call` 而不是 `ok(MdCG._term_in_scene(...) is False, ...)`：
    # 后者在闸被删掉时会抛 TypeError **中断整个模块**（见 `ok_call` 注释）。
    ok_call(lambda _t=_t, _sc=_sc: MdCG._term_in_scene(_t, _sc) is False,
            "R1 非 str 场景 term=%r scene=%r 必须不命中（fail-closed）"
            % (_t, _sc))
for _sc in (123, 1.5, True, object()):
    # **不能用 `_safe` 断言这一组**（复核第 10 轮 G-A，这是真真空）。
    # `_safe` 把异常吞成 False，于是两种实现读数完全相同：
    #   · 正确实现：闸挡下 ⇒ `_term_in_scene` **返回 False**
    #   · 变异实现：闸放过 int/float/bool ⇒ 往下走、`fold_for_match_keep`
    #     对非 str 最终**抛异常**，被 `_safe` 吞成 False
    # 把闸改成白名单 `(str,int,float,bool)` 时，`_safe(...) is False` 照样全绿（实测 ESCAPE）。
    # 故这里**同时钉两件事**：不抛异常 **且** 返回 False。
    # 正确实现两者都满足；白名单变体会抛 ⇒ 红。
    try:
        _r = MdCG._term_in_scene("PE", _sc)
        _exc = None
    except Exception as _e:                       # noqa: BLE001
        _r, _exc = None, type(_e).__name__
    ok(_exc is None and _r is False,
       "R1 非 str 且非容器 %r 必须**返回 False 且不抛异常**（不能用 _safe："
       "它会把异常吞成 False，于是闸被放宽这一支测不出来）"
       " 得 ret=%r exc=%s" % (_sc, _r, _exc))
ok_call(lambda: (_safe("PE", None) is False), "R1b None 场景不命中")
ok_call(lambda: (_safe("PE", "pe 场景") is True), "R1c str 场景仍正常命中（闸不放宽正常面）")
# R1d：端到端——非 str 场景下 judge_qualification 不得因 fail-open 而 ACCEPT。
# 直接走 `_term_in_scene` 的「抛 → 吸收」路径会掩盖问题，故同时钉住「不抛」。
for _t, _sc in (("估值", ["估值"]), ("估值", {"估值": 1})):
    try:
        _r = MdCG._term_in_scene(_t, _sc)
    except Exception as _e:                       # noqa: BLE001
        _r = "EXC:%s" % type(_e).__name__
    ok(_r is False,
       "R1d 子串支必须返回 False 而不是抛异常/为真（term=%r scene=%r 得 %r）"
       % (_t, _sc, _r))

print()
print("=" * 68)
print("R2. 折叠命中必须过**否定作用域**闸（与负条件面 _negated_at 同源）")
print("=" * 68)
# 机理：折叠让正条件面认出 `pe`，而负条件面那一次命中正被否定词挡着 ⇒
# 正说「条件已确认」、负说「不适用不成立」= 新造两面分裂（方向是放宽）。
_R2 = [("PE",  '{"query": "不是 pe 怎么算"}'),
       ("API", '{"query": "不属于 api 的部分"}'),
       ("PR",  '{"query": "不是 pr 怎么算"}'),
       ("PDF", '{"query": "没有 pdf 的"}')]
for _t, _s in _R2:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R2 折叠命中落在否定作用域内 term=%r scene=%r 必须不命中" % (_t, _s))
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) == bool(neg_condition_hits([_t], _s))),
       "R2b 否定句上正负两面必须一致 term=%r" % (_t,))
# 反向对照：**肯定句**上折叠收益必须保住（R2 不是把折叠整个关掉）
for _t, _s in [("PE", '{"query": "pe 怎么算"}'),
               ("API", '{"query": "api 怎么设计"}'),
               ("PDF", '{"query": "pdf 扫描件"}')]:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R2c 肯定句上折叠收益必须保住 term=%r scene=%r" % (_t, _s))
# R2d：**三处调用点**各必须有自己的钉子 —— 只补一处，另两处的缺口看不见。
_R2D = [("PE",       '{"query": "不是 pe 的用法"}',        "词边界支"),
        ("PE RATIO", '{"query": "并非 pe ratio 的用法"}',   "多词支"),
        ("4G单模",   '{"query": "没有 ４ｇ单模 的"}',        "子串支")]
for _t, _s, _b in _R2D:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R2d %s 的折叠命中落在否定作用域内 term=%r 必须不命中" % (_b, _t))
# R2e：原文路径**一字不动** —— base 本来就命中的否定句不许被本闸收紧。
# 这一条是本补丁否掉「闸施加到所有路径」的理由（那版 recall_loss 2340）。
for _t, _s in [("PE", "不是 PE 怎么算"), ("api", "不是 api 怎么算")]:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R2e 原文路径必须保留 base 命中 term=%r scene=%r" % (_t, _s))

print()
print("=" * 68)
print("R3. 词面归一不得把 base 的原文召回收紧（重音紧邻 / 原文词边界）")
print("=" * 68)
# `keep` 已剥重音：`á` → `a`，于是 `api` 在 `apiá 日志` 里右侧凭空紧邻一个
# ASCII 字母 ⇒ 折叠词边界不成立 ⇒ 不命中；而负条件面走子串、照样命中
# ⇒ 两面分裂，方向是**召回损失**（base 命中 → 补丁不命中）。
_R3 = [("api",  "apiá 日志怎么打"), ("api", "apiÁ 日志"),
       ("core", "coreé 模块"),      ("app", "appá 配置")]
for _t, _s in _R3:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R3 原文词边界命中必须保住 term=%r scene=%r" % (_t, _s))
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) == bool(neg_condition_hits([_t], _s))),
       "R3b 重音紧邻上正负两面必须一致 term=%r" % (_t,))

print()
print("=" * 68)
print("R4. 原文路径必须**按分支**复刻 base（含空格的 ASCII 词项走子串支）")
print("=" * 68)
# 我第一版预检写成 `if t.isascii() and t.isalpha() and re.search(...raw)`，
# 于是 `"Connection aborted"`（isalpha 为假，base 走子串支）根本没过预检，
# 而它折叠后 `connectionaborted` 是 isalpha → 掉进词边界支 → 被否定作用域闸
# 挡掉。真实库实测漏 36 格，全部是这类「含空格的 ASCII 短语」。
_R4 = [("Connection aborted", '{"query": "不是 Connection aborted 这种"}'),
       ("pytdx quotes",       '{"query": "不是 pytdx quotes 这种"}'),
       ("DSH Desktop",        '{"query": "并非 DSH Desktop 这种"}'),
       ("unknown tool",       '{"query": "没有 unknown tool 这种"}')]
for _t, _s in _R4:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R4 含空格的 ASCII 短语原文命中必须保住 term=%r" % (_t,))
# 同族反向：不带否定的肯定句必须仍然命中（R4 不是放宽）
for _t, _s in [("Connection aborted", '{"query": "Connection aborted 怎么办"}'),
               ("pytdx quotes",       '{"query": "pytdx quotes 怎么调"}')]:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R4b 肯定句上仍命中 term=%r" % (_t,))
# 折叠路径仍须过闸：原文没有该词面时（问句全小写），否定句不得算「已确认」，
# 且正负两面必须一致（都判为「不成立」）。
for _t, _s in [("Connection aborted", '{"query": "不是 connection aborted 这种"}'),
               ("DSH Desktop",        '{"query": "没有 dsh desktop 这种"}')]:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R4c 折叠路径的否定作用域仍生效（正条件面不得判命中）term=%r" % (_t,))
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) == bool(neg_condition_hits([_t], _s))),
       "R4d 折叠路径上正负两面必须一致 term=%r" % (_t,))

print()
print("=" * 68)
print("R5. base 原文路径必须**按词边界**判 ASCII 短词（不得退化成子串）")
print("=" * 68)
# 变异测试发现的守卫缺口：撤掉原文词边界支后，`elif t in raw` 会接手，
# 于是原文路径退化成**子串**——`api` 咬住 `capital`。R3 只断言「命中」，
# 子串也是命中 ⇒ R3 全绿、变异逃逸（v5 首轮 M3 就是这样 ESCAPED 的）。
# 必须补「不该命中的必须不命中」这一侧。
_R5 = [("api",  "capital 结构怎么调"), ("app", "mapping 对不对"),
       ("core", "score 怎么算"),       ("api", "Capital 结构"),
       ("APP",  "Mapping 配置")]
for _t, _s in _R5:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R5 ASCII 短词不得在词内命中 term=%r scene=%r" % (_t, _s))
# R5b 曾写成「正负两面必须一致」——**那是错的断言**：负条件面走子串
# （`neg_condition_hits` 只 `item in scene_norm`，不做词边界），所以 `api`
# 在 `capital` 里对负条件面确实成立。三棵树（pre-753 / origin/main / 打补丁）
# 实测 pos=False / neg=True 完全一致 ⇒ 这是**存量口径差**，不是本补丁引入，
# 也不在本补丁（字符归一）的范围内。此处只钉「补丁没让它变化」。
_R5B_STOCK = False   # pre-753 实测：这些格 pos=False
for _t, _s in _R5:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is _R5B_STOCK),
       "R5b 词内不命中与存量口径一致（补丁不得改动）term=%r" % (_t,))
# 反向对照：真正独立成词时必须命中（R5 不是把短词整个关掉）
for _t, _s in [("api", "api 怎么调"), ("core", "core 模块")]:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R5c 独立成词仍必须命中 term=%r" % (_t,))

print()
print("=" * 68)
print("R7. 重音回填的**准入面**（多词短语 / 大写词项都要覆盖）")
print("=" * 68)
# 背景：折叠加剥重音把 `apiá` 变成 `apia`，`api` 右侧凭空紧邻 ASCII 字母，
# 词边界崩掉 ⇒ 假阴性。回填的准入条件是「t 只由 ASCII 字母与空白组成」。
# 这组钉两件事：(a) 多词短语与大写词项都必须被回填（我第一版漏了多词、
# 第二版用 `t_keep == t` 又漏了大写）；(b) 词项自身被折叠/非 ASCII 的不许回填。
_R7_BACKFILL = [
    ("api",          "apiá 日志怎么打"),        # 单词
    ("API",          "APIé 日志"),             # 大写（`t_keep != t`，仍须回填）
    ("PE",           "PEñ 材料"),              # 大写双字母
    ("data flow",    "data flowé 说明"),        # 多词短语
    ("api gateway",  "api gatewayá 说明"),      # 多词短语
    ("tools",        "中文toolsé 场景"),        # 中文前缀 + 重音
    ("api",          "áapi 日志"),             # 重音在词前
]
for _t, _s in _R7_BACKFILL:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7 重音紧邻造成的假阴性必须回填 term=%r scene=%r" % (_t, _s))

# R7d/R7e：**空白宽度**这一维必须单独钉。
# 上面七条全是「精确单空格」形态 —— 于是 `pat_raw` 若用 `t.split()` + `\s*`
# 拼（允许零个/多个/NBSP 空白），这七条**全绿而缺陷已复活**。这正是
# 「断言写在另一种形态上等于没写」的第三次复发（前两次是 M10 的路径、M9 的分支）。
#
# base 的口径是：只有 `t.isalpha()`（无空白）才走词边界支；**含空格的 ASCII
# 短语走子串支 `t in scene`，要求逐字连续**。故回填的原文判据必须同样逐字连续。
# 真实库多词纯 ASCII 词项 = **5** 个（`Connection aborted` / `DSH Desktop` /
# `pytdx quotes` / `unknown tool` / `voyager provenance`），可达。
# （2026-11-04 复核更正：此前误写为 6，与 ISSUE 文档 §2 的「5」自相矛盾，以 5 为准。）
_R7_WIDTH = [("data flow", "dataflowé 说明"),                       # 零空白
             ("data flow", "data  flowé 说明"),                     # 双空格
             ("data flow", "data\u00a0flowé 说明"),                 # NBSP
             ("Connection aborted", "Connectionabortedé 说明"),
             ("Connection aborted", "Connection  abortedé 说明"),
             ("Connection aborted", "Connection\u00a0abortedé 说明")]
for _t, _s in _R7_WIDTH:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R7d 多词词项不许放宽空白宽度（base 走子串支，要求逐字连续）"
       " term=%r scene=%r" % (_t, _s))
# 反向对照：精确原形（单空格）仍须回填 —— R7d 不是把多词族整个关掉
_R7_WIDTH_OK = [("data flow", "data flowé 说明"),
                ("Connection aborted", "Connection abortedé 说明"),
                ("api gateway", "api gatewayá 说明")]
for _t, _s in _R7_WIDTH_OK:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7e 精确原形（逐字连续单空格）仍须回填 term=%r scene=%r" % (_t, _s))

# R7f：**右词边界**这一维也必须单独钉（2026-11-04 第 8 轮自查补）。
# 上面 R7d/R7e 钉的是「空白宽度」，全都不区分「`api` 后面紧跟 ASCII 字母」这种形态。
# 于是把 `pat_raw` 的右边界 `(?![A-Za-z])` 整个删掉时，R7d/R7e **全绿**
# （实测 M15：110 passed, 0 failed），而回填支在 `api` vs `apiX 日志` /
# `apiXé 日志` 上凭空新造命中（41047 格不变量里 I2 = 105）。
# 左边界同理，但那侧 R7b 的 `capital`/`metadata flow` 两条已经钉住了。
_R7_RBOUND = [("api", "apiX 日志"),        # 右侧紧邻 ASCII 字母
              ("api", "apiXé 日志"),        # 右侧 ASCII 字母 + 重音
              ("API", "APIX 日志"),
              ("core", "corex 场景")]
for _t, _s in _R7_RBOUND:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R7f 回填也不许放宽**右**词边界（base 词边界支同样有右边界）"
       " term=%r scene=%r" % (_t, _s))
# 反向对照：右侧是重音（归一后变 ASCII 相邻、原文不相邻）时仍须回填
_R7_RBOUND_OK = [("api", "apié 日志"), ("api", "apiéX"),
                 ("API", "APIé 日志"), ("core", "coreé 场景")]
for _t, _s in _R7_RBOUND_OK:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7g 右侧是重音（原文不相邻）时仍须回填 term=%r scene=%r" % (_t, _s))

# R7h：边界的**字符类**这一维也必须单独钉（2026-11-04 复核补，第 9 轮）。
# R7d/R7e 钉的是词项**内部**空白宽度，R7f/R7g 钉的是词项**末尾**紧邻 ASCII 字母
# —— 三道都只问 `[A-Za-z]` 这**一个字符类**，从没问过「还有谁算词边界字母」。
#
# 只钉「数字」是不够的：我补完数字再打一圈，把边界换成
# `[A-Za-z_]` / `[A-Za-z-]` / `[A-Za-zＡ-Ｚａ-ｚ]` / `[A-Za-z\u0300-\u036f]`
# 等字符类，**全部 124 条全绿**（`mut_class_hunt.py`：ESCAPES=9）。
# 机理同 D1：`[A-Za-z]` 与 `[A-Za-z+任意]` 的差别一次都没被问过。
#
# 判据来源是**基准真相**（`probe_class_truth.py` / `probe_ws.py` 用 pre753 树
# 跑同一批格）：数字 / 下划线 / 连字符 / 全角字母 / 组合符 / 汉字 / 中文标点 /
# `$` / `@` / **空白** —— base 全部 `True`（它们都不是 ASCII 字母，词边界成立），
# main 全部 `False`（剥重音造出假阴性），v9 全部 `True`（回填正确）。
#
# **空白这一项是必补的**：空白是词项最常见的左邻字符。`(?<![A-Za-z\s])`
# 在只钉数字的版本上 `147 passed, 0 failed` 全绿——而 base 对
# `这是 apiá 日志` 判 True（空格不是字母），收紧后变 False = 召回损失。
#
# 故这里钉的是一条**完整语义**：词边界只认 ASCII 字母，
# 除 `[A-Za-z]` 以外的任何字符进出**都不算**词边界。
# 加一个新字符进字符类 = 把 base 的召回凭空收紧，必须被这组抓红。
_R7_CLASS_L = [("api", "1api\u00e9 说明"),                    # 数字
               ("core", "2core\u00e9 模块"),
               ("PE", "3PE\u00f1 材料"),
               ("api", "_api\u00e9 说明"),                    # 下划线
               ("api", "-api\u00e9 说明"),                    # 连字符
               ("api", "\uff21api\u00e9 说明"),               # 全角字母
               ("api", "\u0301api\u00e9 说明"),               # 组合符
               ("api", "\u4e2dapi\u00e9 说明"),               # 汉字
               ("api", "\uff0capi\u00e9 说明"),               # 中文标点
               ("api", "$api\u00e9 说明"),
               ("api", "@api\u00e9 说明"),
               ("api", "这是 api\u00e1 日志"),                 # 半角空格（最常见）
               ("api", "这是\tapi\u00e1 日志"),                # 制表符
               ("api", "这是\u3000api\u00e1 日志"),            # 全角空格
               ("data flow", "这是 data flow\u00e9 说明")]     # 多词 + 前导空格
for _t, _s in _R7_CLASS_L:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7h 左边界字符类：**只有 ASCII 字母**算词边界，左侧是非字母字符时"
       "（含空白）仍须回填 term=%r scene=%r" % (_t, _s))
_R7_CLASS_R = [("api", "\u00e1api1 说明"),                    # 数字
               ("api", "\u00e1api_ 说明"),                    # 下划线
               ("api", "\u00e1api- 说明"),                    # 连字符
               ("api", "\u00e1api\uff21 说明"),               # 全角字母
               ("api", "\u00e1api\u0301 说明"),               # 组合符
               ("api", "\u00e1api\u4e2d 说明"),               # 汉字
               ("api", "\u00e1api\uff0c 说明"),               # 中文标点
               ("api", "\u00e1api$ 说明"),
               ("api", "\u00e1api@ 说明")]
for _t, _s in _R7_CLASS_R:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7h 右边界字符类：**只有 ASCII 字母**算词边界，右侧是非字母字符时"
       "仍须回填 term=%r scene=%r" % (_t, _s))
# 注：右侧空白不必单列 —— 不是「不可观测」，而是**已被既有断言覆盖**。
# 把 `\s` 加进**右**边界字符类，本文件仍红 1 条：
#   R7 `("api", "áapi 日志")` —— 该格 `api` 的右邻正是空格（左邻是重音，
#   折叠后左邻变 ASCII 字母才走回填），加 `\s` 后 pat_raw 的右边界不成立。
# 左边界相反：折叠崩的是**右**边界，左邻空白天然够得到回填支，且既有 7 条
# R7 的格全是「无左邻」形态，故**必须**在这里显式补（加 `\s` 时左边红 5 条）。

# **不要再按「我想到哪个字符」逐个补**——这是本文件第 6 次同型复发。
# 我按「数字 → 下划线 → 空白」逐轮补，每轮都以为补完了，实测每轮都还漏：
#   ZWSP(U+200B) / ZWJ(U+200D) / BOM(U+FEFF) / NBSP(U+00A0) / 全角数字(U+FF10)
# 加进边界字符类后 **151 条全绿**（`mut_class_ext.py`：ESCAPES=10）。
#
# 判据不是「枚举字符」，而是**通用类别**：只有 `[A-Za-z]` 算词边界字母，
# 其余 Unicode 通用类别一律不算。下面按类别取代表，把这条语义钉完整
# （`probe_unicode_cat.py` 实测 33 类 × 左右 = 66 格，base 全 True，v9 全 True）。
#
# 另外做了一个**穷举**验证（`sweep_bmp.py`，126870 格 = BMP 全部非 ASCII 字母
# 码点 × 左右）：与 base 的差异只有 10 格，且全部是**否定词做左邻**
# （`不`/`无`/`未`/`没`/`非`/`莫`/`别`/`⽆`/`⾮`/`不`）—— 那不是词边界问题，
# 是回填正确地在过否定闸（base 没有这道闸），属预期差异，不是召回损失。
_R7_CLASS_CAT = [
    # (类别, 代表字符, 说明)
    ("Nd",  "0",        "ASCII 数字"),
    ("Nd",  "\uff10",   "全角数字"),
    ("Pc",  "_",        "连接符（下划线）"),
    ("Pd",  "-",        "连字符"),
    ("Po",  "\uff0c",   "中文逗号"),
    ("Ps",  "(",        "左括号"),
    ("Pe",  ")",        "右括号"),
    ("Pi",  "\u201c",   "左双引号"),
    ("Pf",  "\u201d",   "右双引号"),
    ("Sm",  "$",        "数学符号"),
    ("Sc",  "\uffe5",   "货币符号（全角￥）"),
    ("Sk",  "^",        "修饰符号"),
    ("So",  "\u00a9",   "其它符号（©）"),
    ("Zs",  "\u00a0",   "空格分隔符（NBSP）"),
    ("Zs",  "\u3000",   "空格分隔符（全角空格）"),
    ("Zs",  " ",        "空格分隔符（半角，最常见）"),
    ("Zl",  "\u2028",   "行分隔符"),
    ("Zp",  "\u2029",   "段分隔符"),
    ("Cc",  "\t",       "控制字符（TAB）"),
    ("Cf",  "\u200b",   "格式字符（ZWSP）"),
    ("Cf",  "\u200d",   "格式字符（ZWJ）"),
    ("Cf",  "\ufeff",   "格式字符（BOM）"),
    ("Cf",  "\u00ad",   "格式字符（软连字符）"),
    ("Mn",  "\u0301",   "非间距组合符"),
    ("Mc",  "\u0903",   "间距组合符"),
    ("Me",  "\u0488",   "包围组合符"),
    ("Lo",  "\u4e2d",   "其它字母（汉字）"),
    ("Lm",  "\u02b0",   "修饰字母"),
    ("Lt",  "\u01c5",   "标题字母"),
    ("Ll",  "\u00e9",   "小写字母（非 ASCII，é）"),
    ("Lu",  "\u00c9",   "大写字母（非 ASCII，É）"),
    ("Nl",  "\u2160",   "字母数字（罗马数字Ⅰ）"),
    ("No",  "\u00b2",   "其它数字（上标²）"),
    ("Co",  "\ue000",   "私用区"),
]
for _cat, _c, _desc in _R7_CLASS_CAT:
    ok_call(lambda: (MdCG._term_in_scene("api", _c + "api\u00e9 说明") is True),
       "R7h 左边界：类别 %s（%s）不是 ASCII 字母，不得算词边界" % (_cat, _desc))
    ok_call(lambda: (MdCG._term_in_scene("api", "\u00e1api" + _c + " 说明") is True),
       "R7h 右边界：类别 %s（%s）不是 ASCII 字母，不得算词边界" % (_cat, _desc))

# 不许回填的三类（各自对应一个既有守卫，防我以后把准入面放大）
_R7_NOBF = [
    ("ＰＥ", '\uff30\uff25\uff34 材料'),         # D11：词项自身全角折叠
    ("Café", "CaféX 场景"),                     # D12：词项自身带重音
    ("か",   "\u304b\u3099"),                    # H6：非 ASCII 假名
    ("data flow", "metadata flow 的说明"),       # D9：原文词边界就不成立
    ("api",  "capital 结构怎么调"),              # 词内，本来就不该命中
]
for _t, _s in _R7_NOBF:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R7b 不得回填（非本族）term=%r scene=%r" % (_t, _s))
# **准入面必须钉住「词项自身未被折叠」这一侧**：D11/D12 那两条只钉了
# 「词项自身折叠 + 场景里没有 ASCII 相邻」，那种格连 main 都不命中、走不到回填，
# 于是把准入面整个放宽成 `if True:` 也测不出来（M9 第一版只红 1 条）。
# 这里补的是「**词项自身被折叠 + 场景里恰好有 ASCII 相邻**」——那才是放宽后
# 会凭空回填的一类（我实测 33 格，如 `ＰＥ` vs `ＰＥé 材料`）。
_R7_OWN_FOLDED = [("ＰＥ", "ＰＥé 材料"), ("ＡＰＩ", "ＡＰＩé之说明"),
                  ("ＴＡＢ", "ＴＡＢé"),  ("Ｃａｆé", "Ｃａｆéé 材料"),
                  ("é", "éé"),           ("á", "áé 材料")]
for _t, _s in _R7_OWN_FOLDED:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R7c 词项**自身**被折叠时不得回填（即使场景侧有 ASCII 相邻）"
       " term=%r scene=%r" % (_t, _s))

# R7i：**性质断言**，不枚举字符（2026-11-05 复核第 9 轮，G1 阻断项）。
# 我前一版按「数字 → 下划线 → 空白 → 15 个字符」逐轮补，每轮都全绿以为补完了；
# 复核者把这一维做成穷举后，44 个候选字符里**左侧 40 个、右侧 42 个仍然全绿逃逸**，
# 且已能在真实节点上把 ACCEPT 打成 DEFER（`/toolsé 说明`）。
# 根因是我在**枚举反例**而不是**刻画规则**。规则只有一句：
#
#     词边界只认 `[A-Za-z]`；除 ASCII 字母外，**任何**字符相邻都不算词边界。
#
# 所以这里不再列字符，而是把它写成性质：
#   (a) ASCII 全部 76 个非字母字符 × 左右 —— 逐个断言（可定名到具体字符）；
#   (b) Unicode BMP 全部 65484 个非 ASCII 字母码点 × 左右 —— 聚合断言（违例数必须 0）。
# 判据基准是 pre753（#753 之前的实现），实测 152/152 与 130968 格全部一致。
#
# 唯一必须排除的：左邻字符经归一口径后使词项落进 `NEG_CUES`（→ 否定闸挡回）。
# 实测就 10 个（`不 无 未 没 非 莫 别 ⽆ ⾮ 不`），那是**否定闸正确工作**，
# 不是词边界问题，故显式排除并在注释里计数（复核者全码点扫描得到同一结论）。
#
# **这个排除集必须从 `NEG_CUES` 派生，不能硬编码**（复核第 10 轮指出）：
# 原先写死 10 个字符，往 `NEG_CUES` 里加一个 `"禁"`，本文件立刻**假红**
# （新否定词没进排除集 → 那一格被判「该回填却没回填」）。
# 现在改为「运行时用实现自己的判据算一遍」：对每个候选码点，问
# `neg_condition_hits` 是否因它而被挡回 —— 是则排除。这样 `NEG_CUES` 增删
# 自动同步，永不失配。
from .mdcg import NEG_CUES as _NEG_CUES


def _is_neg_left(_c):
    """该字符做左邻时，词项是否会被否定闸挡回（用实现自己的判据问）。"""
    try:
        return not bool(neg_condition_hits(["api"], _c + "api\u00e9 说明"))
    except Exception:                             # noqa: BLE001
        return False


# 派生而非硬编码：BMP 范围内实际会被否定闸挡回的左邻字符
_R7I_NEG_LEFT = set()
for _cp in range(0x00, 0x10000):
    _ch = chr(_cp)
    if _ch.isascii() and _ch.isalpha():
        continue
    if _is_neg_left(_ch):
        _R7I_NEG_LEFT.add(_ch)
# 自检 1：派生结果不得为空（否则等于没排除，BMP 断言会因否定闸假红）
ok(_R7I_NEG_LEFT,
   "R7i 派生排除集不得为空（NEG_CUES=%r）" % (_NEG_CUES,))
# 自检 2：**一致性**而非固定计数 —— `NEG_CUES` 里每个能单字生效的 cue，
# 其归一后首字都必须出现在派生集里。这里不写死数字：
# 写死 `== 10` 就成了新的硬编码，往 NEG_CUES 加 `"禁"` 会假红（实测过）。
_expected = set()
for _cue in _NEG_CUES:
    _f = fold_for_match_keep(_cue)
    if len(_f) == 1:
        _expected.add(_f)
ok(_expected <= _R7I_NEG_LEFT,
   "R7i 派生排除集必须覆盖 NEG_CUES 的全部单字 cue（缺 %r）"
   % (sorted(_expected - _R7I_NEG_LEFT),))

_ASCII_NONLETTER = [chr(_c) for _c in range(0x00, 0x80)
                    if not chr(_c).isalpha()]
for _c in _ASCII_NONLETTER:
    ok_call(lambda: (MdCG._term_in_scene("api", _c + "api\u00e9 说明") is True),
       "R7i 左邻 ASCII 非字母 U+%04X（%r）不算词边界，须回填" % (ord(_c), _c))
    ok_call(lambda: (MdCG._term_in_scene("api", "\u00e1api" + _c + " 说明") is True),
       "R7i 右邻 ASCII 非字母 U+%04X（%r）不算词边界，须回填" % (ord(_c), _c))

# (b) 整 BMP 穷举：这不是「抽样」，是把规则**证完**（左侧 65484 格，约 2s）
_BMP_L = [chr(_cp) for _cp in range(0x00, 0x10000)
          if not (chr(_cp).isascii() and chr(_cp).isalpha())
          and chr(_cp) not in _R7I_NEG_LEFT]
_BMP_R = [chr(_cp) for _cp in range(0x00, 0x10000)
          if not (chr(_cp).isascii() and chr(_cp).isalpha())]
_L_BAD = [_c for _c in _BMP_L
          if _safe("api", _c + "api\u00e9 说明") is not True]
ok(not _L_BAD,
   "R7i 左邻 BMP 全部 %d 个非 ASCII 字母码点都不算词边界（违例 %d 个：%r）"
   % (len(_BMP_L), len(_L_BAD), _L_BAD[:8]))
_R_BAD = [_c for _c in _BMP_R
          if _safe("api", "\u00e1api" + _c + " 说明") is not True]
ok(not _R_BAD,
   "R7i 右邻 BMP 全部 %d 个非 ASCII 字母码点都不算词边界（违例 %d 个：%r）"
   % (len(_BMP_R), len(_R_BAD), _R_BAD[:8]))

# (c) 星平面（astral，U+10000 以上）。**这里只抽样，全扫在独立慢速脚本里**。
#
# 复核第 10 轮指出：星平面「区段扫 vs 全扫」不是精度差异，是**覆盖性差异**——
# 全扫 1,048,576 个码点后实现本身违例 0，但漏掉的那些码点里任一个被加进
# 边界字符类，本文件的抽样区段都看不见（实测把 `[A-Za-z\U0001F700-\U0001F77F]`
# 炼金块加进去，397 条全绿）。
#
# 但全扫实测：左侧 23.3s + 右侧 22.9s = **46.2s**，对每次回归都跑的守卫太长。
# 故拆两处：
#   · 本文件：抽样（快，每次回归都跑）
#   · `audit_astral_full.py`：全扫 961437 个码点（慢，改动判据后手动跑一次）
# 这不是「用抽样冒充全扫」——本文件与脚本的分工明确写在下面。
#
# 抽样改为**按块首/块中/块尾**取，而不是「我想到的 7 个区段」：
# Unicode 星平面共 0x10000..0x10FFFF，按 0x1000 一块共 256 块，每块取首/中/尾。
_ASTRAL = []
for _blk in range(0x10000, 0x110000, 0x1000):
    for _off in (0x000, 0x800, 0xFFF):
        _cp = _blk + _off
        if _cp <= 0x10FFFF and not chr(_cp).isalpha():
            _ASTRAL.append(_cp)
_A_BAD = [_cp for _cp in _ASTRAL
          if _safe("api", chr(_cp) + "api\u00e9 说明") is not True]
ok(not _A_BAD,
   "R7i 左邻星平面抽样 %d 个码点（按 0x1000 块首/中/尾）都不算词边界"
   "（违例 %d 个：%r）" % (len(_ASTRAL), len(_A_BAD),
                          ["U+%04X" % x for x in _A_BAD[:8]]))
_A_BAD_R = [_cp for _cp in _ASTRAL
            if _safe("api", "\u00e1api" + chr(_cp) + " 说明")
            is not True]
ok(not _A_BAD_R,
   "R7i 右邻星平面 %d 个码点都不算词边界（违例 %d 个：%r）"
   % (len(_ASTRAL), len(_A_BAD_R),
      ["U+%04X" % x for x in _A_BAD_R[:8]]))

# R7k：**main 分支**（`pat`，`mdcg.py:5033`）的字符类（复核第 9 轮 G5）。
#
# 我先写了 152 条**不带否定**的形态，四种变异（左右/双侧加数字、`\s*`→`\s+`）全绿。
# 追下去发现**不是真空，是形态选错**：不带否定时 main_hit 收紧后，`api` 仍符合
# 纯 ASCII 字母准入面，`pat_raw` 在 `1api 日志` 上左边界成立 ⇒ 回填支原样补回。
# 带否定前缀时才可观测（回填出的命中被否定闸挡回，main 侧收紧暴露）。
#
# 但**不是四种变异都可观测** —— 23660 格差分实测：
#   R 右边界加数字 / B 双侧加数字  → 896 格不同  ⇒ 可观测，必须钉（下面这 18 条）
#   L 左边界加数字 / W `\s*`→`\s+` → **0 格不同** ⇒ 这一层看不到
# L 与 W 不可观测的机理：左邻收紧后 main_hit=False，回填支的 `pat_raw` 左边界
# 用同一批字符判，**也**为 False ⇒ 两条路一起塌，`_term_in_scene` 输出不变。
# 对这两种，写断言必然是真空（在正确与错误实现上读数相同），故**不写**。
# 这是本轮最要紧的一条方法论：**先测「这一维在这一层可不可观测」，再决定写不写。**
#
# 教训（与 §2 同源，第 9 次同型的镜像）：
# **「这一维在什么形态下可观测」本身就是判据的一部分。**
_R7K_MAIN = [
    ("api", "不是 api1"), ("api", "不是 api1 说明"), ("api", "不是 api1日志"),
    ("api", "并非 api1"), ("api", "并非 api1 说明"), ("api", "并非 api1日志"),
    ("api", "没有 api1"), ("api", "没有 api1 说明"), ("api", "没有 api1日志"),
    ("api", "不是 api9"), ("api", "不是 api9 说明"), ("api", "不是 api9日志"),
    ("API", "不是 API1"), ("API", "并非 API1 说明"), ("API", "没有 API1日志"),
    ("core", "不是 core1"), ("core", "并非 core1 说明"),
    ("tools", "不是 tools1日志"),
]
for _t, _s in _R7K_MAIN:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7k main 分支字符类：数字不算词边界（否定形态下可观测）"
       " term=%r scene=%r" % (_t, _s))

# R7m：**大小写不一致**才是「main 分支左边界可观测」的条件（复核第 12 轮指出）。
#
# 我上面 _R7K_MAIN 的 18 条全是「词项与场景大小写一致」，于是**左边界放宽测不出来**。
# 机理在 step②（`if t in norm_scene.raw: return True`）：
#     term='api'  scene='不是api1'   → `t in raw` 为 True ⇒ step② 直接放行，main 的收紧被掩盖
#     term='API'  scene='1api'       → `t in raw` 为 False ⇒ 走 main 边界判，收紧暴露
# 所以可观测性条件是**大小写不一致**。复核实测：把左边界 `[A-Za-z]` 改成 `[A-Za-z0-9]`
# （T2 变异），我原来的 18 条全绿而**收紧 180 格**；补下面这组后 CAUGHT。
#
# 真实库有落点：20 个「纯 ASCII 且含大写」的条件词项
# （ERROR / ESCAPED / GET / PE / IC / ROE / Windows / Playwright / Spearman / splitLine …），
# T2 在 `'ERROR' vs '1error'` 这类格上 True→False，40/100 格变化。
_R7M_CASE = [
    ("API", "1api"), ("api", "1API"),
    ("API", "1api 说明"), ("api", "1API 说明"),
    ("IC", "1ic"), ("ROE", "1roe"),
    ("PE", "9pe"), ("PDF", "9pdf"),
    ("ERROR", "1error"), ("GET", "2get"),
    ("Windows", "1windows"), ("splitLine", "1splitline"),
]
for _t, _s in _R7M_CASE:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R7m main 分支**左**边界：大小写不一致时可观测，数字/字母左邻不算词边界"
       " term=%r scene=%r" % (_t, _s))
    # 反向：真正的左邻字母必须挡住（否则 R7m 只是把左边界整个删掉）
for _t, _s in (("API", "xapi"), ("api", "XAPI"), ("ROE", "xroe"), ("PE", "ape")):
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R7m 反向：左邻是 ASCII 字母时词边界不成立，必须不命中 term=%r scene=%r"
       % (_t, _s))

print()
print("=" * 68)
print("R8. 回填**不是放行证**：回填出的命中同样须过否定作用域闸")
print("=" * 68)
# 这是我在 v5 自查时抓到的自己的漏点（红队 v6 没覆盖到，因为它只打 ②③ 两支）：
# ①b 一开始 `return True`，于是 `api` vs `不是 apiá 日志` 相对 main **新造**
# 两面分裂（pos=True / neg=False），方向是放宽。机理：base 的原文判定没有
# 否定作用域这一层（那是负条件面独有的 `_negated_at`），回填若直接放行，
# 等于把「base 没有的宽松」原样搬回来。
# 实测：真实库纯 ASCII 词项 × 8 重音符 × 4 否定前缀 = 2528 格，不过闸时分裂
# 率 100%；过闸后分裂 0，且肯定模板上召回损失 0。
_R8 = [("api",  "不是 apiá 日志"), ("API", "并非 APIé 日志"),
       ("PE",   "没有 PEñ 材料"),  ("tools", "不属于 toolsé 场景"),
       ("api gateway", "不是 api gatewayá 说明"), ("core", "没有 coreé 模块")]
for _t, _s in _R8:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R8 回填落在否定作用域内必须挡回 term=%r scene=%r" % (_t, _s))
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) == bool(neg_condition_hits([_t], _s))),
       "R8b 回填路径上正负两面必须一致 term=%r" % (_t,))
# 反向对照：同样的重音紧邻**不带否定**时必须命中（证明 R8 没把 R7 的召回吃掉）
_R8_KEEP = [("api", "apiá 日志"), ("API", "APIé 日志"), ("PE", "PEñ 材料"),
            ("tools", "english toolsé 场景")]
for _t, _s in _R8_KEEP:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R8c 无否定的重音紧邻仍须命中 term=%r scene=%r" % (_t, _s))
# 一次出现被否定、另一次未被否定 ⇒ 仍算命中（与 _negated_at 的「逐次出现」口径一致）
# **必须用大小写不同的词项**：`t='api'` 会在 ② `t in raw` 就被放行、根本到不了 ③，
# 于是「整串搜一次否定词」这种退化解测不出来（我第一版 R8d 就是这么写的，M10 逃逸）。
_R8D = [("API", "不是 api 这种，apiá 日志怎么打"),
        ("API", "并非 apié 这种，api 日志怎么打"),
        ("PDF", "没有 pdf 这种，pdfx 扫描件")]
for _t, _s in _R8D:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R8d 任一次出现未被否定即命中（不得退化成整串搜一次）term=%r scene=%r"
       % (_t, _s))
ok_call(lambda: (MdCG._term_in_scene("API", "api 这种，apiá 日志怎么打") is True),
   "R8e 无否定时多次出现仍命中")

# R8f：否定的 **`any` vs 最后一次** 语义必须单独钉（2026-11-04 复核补，第 9 轮）。
# 上面 R8d/R8e 都只覆盖「两次出现、首次未被否定」—— 而 `_fold_hit_unnagated` 用的是
# `any(not _negated_at(k) for k in _occurrences(...))`。把它退化成
# `not _negated_at(_occ[-1])`（**只看最末一次出现**）时 118 条**全绿**
# （实测 P8 变异：118 passed, 0 failed）。
# 陷阱同 R8d：`t='api'` 在 ② `t in raw` 就放行、到不了 ③，必须用大小写不同的词项。
#
# 只钉「首次未否定/末次否定」还不够 —— 我补完再打一圈，`any` 的其它退化形式
# （只看首次 / 只看中位 / 只看最长那次）在只钉两条的版本上仍可能全绿。
# 故这里按**出现次数 × 否定落点**做全覆盖：3 次出现的三种落点 + 4 次出现只留第 3 次。
# 全部先实测（`probe_r8f.py`，三树对照）：这四格 pre753=False main=True v9=True。
_R8_ANY = [
    ("API", "api 这种，不是 api 日志"),                       # 2 次：首未 Neg，末 Neg
    ("API", "api 这种，不是 apié 怎么算"),                    # 同上 + 重音
    ("API", "api 这种，不是 api 日志，api 怎么打"),            # 3 次：中 Neg
    ("API", "不是 api 这种，不是 api 日志，api 怎么打"),        # 3 次：前 2 Neg
    ("API", "api 这种，不是 api 日志，不是 api 怎么打"),        # 3 次：后 2 Neg
    ("API", "不是 api 一，不是 api 二，api 三，不是 api 四"),    # 4 次：只第 3 次活
]
for _t, _s in _R8_ANY:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is True),
       "R8f 任一次出现未被否定即命中（`any` 不得退化成只看首次/末次/中位）"
       " term=%r scene=%r" % (_t, _s))
# 反向对照：**全部**出现都被否定时必须不命中（证明 R8f 没把否定作用域整个撤掉）
_R8_ANY_NEG = [
    ("API", "不是 api 这种，不是 api 日志"),                   # 2 次全 Neg
    ("API", "不是 api 日志"),                                 # 1 次 Neg
    ("API", "不是 api 一，不是 api 二，不是 api 三"),            # 3 次全 Neg
]
for _t, _s in _R8_ANY_NEG:
    ok_call(lambda: (MdCG._term_in_scene(_t, _s) is False),
       "R8g 全部出现都被否定时必须挡回 term=%r scene=%r" % (_t, _s))

# R8h：**负条件面**的 `any` 语义（2026-11-05 复核第 9 轮，G2）。
# 上面 R8f/R8g 钉的是**正条件面回填支**（`_fold_hit_unnagated`）的 `any`。
# 负条件面 `neg_condition_hits` 里（`_negated_at`，`mdcg.py::_negated_at`）有另一个同形的 `any`，
# 全仓四个测试文件（gate / fold / neg_condition_hits / issue362）**都没钉**
# 「只看末次」这一退化 —— 复核者实测把它退化后四文件全绿。
# 当前库不可达（267 节点 609 条 non_applicable_conditions 里纯 ASCII 字母条目 = 0），
# 属潜伏缺口；但成本 4 行，顺手钉掉。
# 判据同 R8f：**任一次出现未被否定即命中**，不得退化成只看首次/末次/中位/all。
_R8H = [
    ("API", "api 这种，不是 api 日志", True),               # 首次未 Neg
    ("API", "api 这种，不是 api 日志，api 怎么打", True),     # 3 次中 Neg
    ("API", "不是 api 这种，不是 api 日志，api 怎么打", True), # 前 2 Neg
    ("API", "不是 api 这种，不是 api 日志", False),           # 全 Neg
]
for _t, _s, _exp in _R8H:
    ok_call(lambda: (bool(neg_condition_hits([_t], _s)) is _exp),
       "R8h 负条件面 any 语义：任一次出现未被否定即命中（不得只看首次/末次）"
       " term=%r scene=%r 期望=%s" % (_t, _s, _exp))

# R9：**负条件面的「全词分支」**（`mdcg.py:1074-1079`）—— 复核第 10 轮 G-B。
# 该分支是：整条词面（长度 ≥ NEG_MIN_TERM）不在情境里时，退化为「条目按空白切词，
# 每个词都在情境里」也算命中。**此前 0/397 覆盖**（复核用分支进入覆盖证明）：
# 397 条没有一条构造过「多词负条件 + 词面分散」。
# 我实测 5 种注入（all→any / 删 own-topic / 去 NEG_MIN_TERM / 永不 append /
# 整段删掉）在这 397 条上**全部全绿**，而行为真的翻转（见 `verify_gB.py`）。
# 这一组补的就是它 —— 按分支语义写，四个方向各钉一遍。
#
# 语义：`["api gateway"]` 这类多词条目，在 `api 在这里，gateway 在那里` 这种
# 「词面分散」的情境里**也应命中**（全词命中），而不是要求整串出现。
_R9_FULLWORD = [
    # (neg_conditions, scene, expect, 说明)
    (["api gateway"], "api 在这里，gateway 在那里", True,  "词面分散仍命中（全词支）"),
    (["pe ratio"],    "pe 怎么算，ratio 又是啥",    True,  "词面分散仍命中"),
    (["data flow"],   "data 走这边，flow 走那边",   True,  "词面分散仍命中"),
    (["api gateway"], "只有 api 没有另一半",        False, "缺词不得命中"),
    (["api gateway"], "只有 gateway 没有另一半",    False, "缺词不得命中"),
    (["api gateway"], "api gateway 一起出现",       True,  "整串出现也命中"),
]
for _neg, _scene, _exp, _why in _R9_FULLWORD:
    ok_call(lambda: (bool(neg_condition_hits(_neg, _scene)) is _exp),
       "R9 负条件面全词分支：%s  neg=%r scene=%r 期望=%s"
       % (_why, _neg, _scene, _exp))
# R9b：全词分支的 `own_topic_text` 豁免必须仍在（自主题面里的词不算命中）
ok_call(lambda: (bool(neg_condition_hits(["api gateway"], "api 在这里，gateway 在那里",
                           own_topic_text="api gateway")) is False),
   "R9b 全词分支仍须尊重自主题豁免（条目落在自主题面时不命中）")
# R9c：全词分支的 NEG_MIN_TERM 词长下限必须仍在。
# `"ab api"` 的 `ab` 归一后长度 2 == NEG_MIN_TERM，仍算词；把下限去掉不会改变这里。
# 真正能区分的是「长度 1 的词」：`"x api"` 里 `x` 长度 1 < 2，**应被丢弃**，
# 于是只剩 `api` 一个词，`all(...)` 仍成立 ⇒ 命中。
# 若把下限去掉（`len(w) >= NEG_MIN_TERM` 删掉），`x` 也进 words；
# 在 `api only` 这种场景里 `x` 不在 → 全词支不成立 → **不命中**（翻转）。
ok_call(lambda: (bool(neg_condition_hits(["x api"], "api only")) is True),
   "R9c 全词分支必须丢弃长度 < NEG_MIN_TERM 的单字词"
   "（去掉词长下限则 'x' 也进 words，'api only' 里缺 'x' ⇒ 翻成不命中）")

# R10：`NEG_SCOPE_WINDOW` 的**方向性**（复核第 10 轮 G4）。
# 我原先在文件头写「窗口两端都有 K 组覆盖、缩到 1 即红」—— 那是错的：
# 6→4/5/7/8/12 在 15 个测试文件上**全绿**（只有 6→1 被抓，那是与 NEG_MIN_TERM 的交互崩）。
# 现在补方向性断言。判据基准实测（干净双树，`不是`+k×`是`+`api 日志`）：
#     W=6  : k=4 → 否定生效（False）；k=5 → 翻成命中（True）
#     W=12 : k=4/k=5 都仍是 False（边界被推到 k≥10）
# 所以钉「k=5 必须已命中」这条即可区分 6 与 12；再钉「k=4 必须仍被否定」防窗口缩小。
_R10_WIN = [
    ("api", "\u4e0d\u662f" + "\u662f" * 5 + "api \u65e5\u5fd7", True,
     "k=5 已越出窗口 ⇒ 否定不生效 ⇒ 命中（窗口放大到 12 时这里会翻成 False）"),
]
for _t, _s, _exp, _why in _R10_WIN:
    ok_call(lambda: (bool(neg_condition_hits([_t], _s)) is _exp),
       "R10 窗口边界（%s）term=%r scene=%r 期望=%s" % (_why, _t, _s, _exp))
# R10b：窗口**不得缩小** —— k=4 时否定必须仍生效（不命中）
ok_call(lambda: (bool(neg_condition_hits(["api"], "\u4e0d\u662f" + "\u662f" * 4 + "api \u65e5\u5fd7"))
   is False),
   "R10b k=4 时否定必须仍生效（窗口缩到 4 以下会翻成命中）")
ok_call(lambda: (bool(neg_condition_hits(["api"], "\u4e0d\u662fapi \u65e5\u5fd7")) is False),
   "R10b 无连接字时否定必须生效")

print()
print("=" * 68)
print("R11. 空 / 折叠为空的词项必须 fail-closed（不得因 '' in 任意串 而恒真）")
print("=" * 68)
# 2026-11-05 第 11 轮自查（用静态覆盖表发现的，**复核与我前几轮都漏了**）：
# `_term_in_scene_norm` 有两道空守卫：
#     L4991-4992   if not t:      return False      ← ①
#     L4995-4996   if not t_fold: return False      ← ②
# 静态覆盖表显示这两行**都是 0 命中**。但两者性质**不同**，必须分开说：
#
#   · ① 是**冗余死代码**：`t = ""` ⇒ `fold("") = ""` ⇒ `t_fold = ""` ⇒ 被 ② 兜住。
#     删掉 ① 后 7 组探针读数与基线**逐格相同**（实测 S1 变异树）。所以
#     「① 零覆盖」不是缺口 —— 写断言反而是在钉死代码。
#
#   · ② 是**真守卫**：`t` 非空但折叠后为空（纯组合符 U+0301 等）时，`t_fold = ""`，
#     于是 `main_hit = "" in norm_scene.compact` **恒为 True** ⇒ fail-open。
#     删掉 ② 后 `_term_in_scene("\u0301\u0301", "\u0301\u0301 日志")` 由 False 翻 True，
#     端到端 `judge_qualification` 由 DEFER 翻 **ACCEPT**（实测 S2 变异树）。
#     **而 410 条断言全绿。**
#
# 这是「零覆盖 ≠ 冗余」的反例：同一个静态读数，一处是死代码、一处是活缺口。
# 判据只能靠**变异**区分（删掉看行为动不动），不能靠覆盖表。
#
# 生产可达性：`condition_terms_diag` 会**保留**纯组合符词项（`cond='\u0301\u0301'`
# → `terms=['\u0301\u0301']`），只挡单字碎片。真实库 864 个「生效条件」节点实测
# 0 落点，属**潜伏缺口**（构造输入可达，存量不可达）。成本 2 行，钉掉。
# 注：只有**纯**组合符/变音符折叠成空串。`a\u0301` 折叠成 `a`（不空），
# 走词边界支正常命中 —— 不在本组（我第一版把它写进来，实测是误判，见 v11 自查记录）。
_EMPTY_FOLD = ["\u0301", "\u0301\u0301", "\u0301\u0301\u0301",
               "\u0300", "\u0302"]
for _t in _EMPTY_FOLD:
    ok_call(lambda: (MdCG._term_in_scene(_t, _t + " \u65e5\u5fd7") is False),
       "R11 折叠为空串的词项 %r 必须不命中（组合符折叠成 '' ⇒ "
       "`'' in 任意串` 恒真，删掉 t_fold 空守卫就 fail-open）" % (_t,))
# R11g：**穷举而不是枚举**（v11 自查第 3 次同型复发的修法）。
# 我第一版只写了 5 个组合符，实测 BMP 里「单独折叠成空」的码点有 **260 个**
# （206 个 Mn + 17 个 Zs + 27 个 Sk + 6 个 Po + Cc/Zl/Zp/Lm 各 1；
# 星平面 0 个）。按「我想到几个就写几个」写，必然漏。
# 这里改为：**扫全 BMP，凡折叠成空者一律断言不命中**。约 2.2s，可接受。
# **起点必须是 0x00 而不是 0x20**（2026-11-05 第 4 次同型自查）：
# 我第一版写 `range(0x20, 0x10000)` 想跳过「不可打印控制符」，实测漏了 **9 个**
# 折叠成空的码点：U+0009 TAB / U+000A LF / U+000B VT / U+000C FF / U+000D CR /
# U+001C–U+001F。它们做词项时当前**确实被 ② 挡成 False**（所以不是活缺陷），
# 但**我的断言没覆盖它们** —— 若哪天守卫退化，这 9 个格子红不了。
# 教训：**「跳过不可打印字符」这种直觉性筛除，就是在给自己开孔。**
# 全 0x00–0xFFFF 折叠成空共 269 个（>0x20 的 260 + 控制符 9）。
_EMPTY_FOLD_ALL = []
for _cp in range(0x00, 0x10000):
    _ch = chr(_cp)
    try:
        _f = compact_exact_text(fold_for_match_keep(_ch))
    except Exception:                             # noqa: BLE001
        continue
    if _f == "":
        _EMPTY_FOLD_ALL.append(_ch)
ok(len(_EMPTY_FOLD_ALL) >= 260,
   "R11g 自检：BMP 里折叠成空的码点应有 260+ 个（实得 %d，含控制符 9 个）"
   " —— 若明显偏少，说明折叠链漂了、本节会静默空转" % len(_EMPTY_FOLD_ALL))
_EF_BAD = [_c for _c in _EMPTY_FOLD_ALL
           if MdCG._term_in_scene(_c, _c + "\u65e5\u5fd7") is not False]
ok(not _EF_BAD,
   "R11g 全部 %d 个「折叠成空」的 BMP 码点（含 0x00–0x1F 的 9 个控制符）做词项时"
   "都必须不命中（违例 %d 个：%r）—— 任一违例都是 `'' in 任意串` 的 fail-open"
   % (len(_EMPTY_FOLD_ALL), len(_EF_BAD),
      ["U+%04X" % ord(x) for x in _EF_BAD[:8]]))
# **R11h → R11j：从「列举特殊字符」改成「对全域做分区」**
# （复核第 12 轮打回，这是我这一轮最大的一处结构性错误）
#
# 我原来把 R11 拆成两半：R11g 管「折叠成空」（269 个）、R11h 管「Cc 且折叠非空」（55 个）。
# 复核指出：**这只覆盖 324 个码点，BMP 里折叠非空的共 65267 个，
# 剩下 65212 个（含全部汉字）一条断言都没有。**
# 实测把这 65212 格里任意一类改成 fail-closed，457 条**全绿**：
#
#   变异（Cc 之外、折叠非空的码点一律 fail-closed）   行为                      gate
#   CJK U+4E00–9FFF      `_term_in_scene("中文","中文 日志")` True→False   **全绿 ESCAPE**
#   CJK 扩展 A           同上                                            **全绿 ESCAPE**
#   ASCII 数字 U+0037    `"7"` True→False                                **全绿 ESCAPE**
#   全角 U+FF01–FF5E     True→False                                      **全绿 ESCAPE**
#   拉丁重音 U+00C0–017F True→False                                      **全绿 ESCAPE**
#
# **汉字是真实库最常见的词项形态**（复核实测：1943 个条件词项里 Lo 类出现 12972 次）。
# 而我的 gate 对它零覆盖 —— 这是比「容差 261–268」严重得多的问题。
#
# 根因不是「容差没收紧」，是**判据的结构错了**：
#   · 我一直在**列举**「我认为特殊的那些字符」（组合符、控制符…），
#     每次复核打回就再加一类 —— 这是第 5 次同型复发（0x1F → Cc → …）。
#   · 正确做法是**分区**：对 BMP 每一个码点，二选一必须成立 ——
#     折叠成空 ⇒ 必须不命中；折叠非空 ⇒ 必须命中。**没有第三种状态，也就没有「两边都不管」的格子。**
#
# 分区的好处：
#   1. 覆盖从 324 → **65536**（完备，无遗漏）；
#   2. **不钉折叠表内容**：折叠链怎么微调，判据自动跟着走，不会假红
#      （我原先担心的「回归锁」问题不成立）；
#   3. `_CC_RANGES` 那个手写枚举可以**删掉** —— 它当时与 `unicodedata.category=='Cc'`
#      逐位相同，但那是「我想出来的」，不是「类决定的」。
#
# 代价：扫 65536 个码点 × 一次 `_term_in_scene`，实测约 2.5s，可接受。
_FOLD_EMPTY2 = []
_FOLD_NONEMPTY2 = []
for _cp2 in range(0x00, 0x10000):
    _ch2 = chr(_cp2)
    try:
        _f2 = compact_exact_text(fold_for_match_keep(_ch2))
    except Exception:                             # noqa: BLE001
        continue
    if _f2 == "":
        _FOLD_EMPTY2.append(_ch2)
    else:
        _FOLD_NONEMPTY2.append(_ch2)
# 自检：两条自检只防「静默空转」，**不钉精确值**（这正是复核建议的做法）
ok(len(_FOLD_EMPTY2) >= 260,
   "R11j 自检：折叠成空的码点应有 260+ 个（实得 %d）"
   " —— 偏少说明折叠链漂了、本节会静默空转" % len(_FOLD_EMPTY2))
ok(len(_FOLD_NONEMPTY2) >= 65000,
   "R11j 自检：折叠非空的码点应有 65000+ 个（实得 %d）"
   " —— 偏少说明分区塌了" % len(_FOLD_NONEMPTY2))
# 分区自检：两半之和必须恰等于 BMP 全域，**不重叠、不遗漏**
ok(len(_FOLD_EMPTY2) + len(_FOLD_NONEMPTY2) == 0x10000,
   "R11j 自检：分区必须完备（空 %d + 非空 %d = %d，应等于 65536）"
   " —— 不等说明有码点两边都没进，正是本条要防的『无断言格子』"
   % (len(_FOLD_EMPTY2), len(_FOLD_NONEMPTY2),
      len(_FOLD_EMPTY2) + len(_FOLD_NONEMPTY2)))
# 分区断言（左）：折叠成空 ⇒ 必须不命中
_EMPTY_BAD2 = [_c for _c in _FOLD_EMPTY2
               if MdCG._term_in_scene(_c, _c + "\u65e5\u5fd7") is not False]
ok(not _EMPTY_BAD2,
   "R11j 分区左：全部 %d 个「折叠成空」的 BMP 码点做词项都必须不命中"
   "（违例 %d 个：%r）—— 任一违例都是 `'' in 任意串` 的 fail-open"
   % (len(_FOLD_EMPTY2), len(_EMPTY_BAD2),
      ["U+%04X" % ord(x) for x in _EMPTY_BAD2[:8]]))
# 分区断言（右）：折叠非空 ⇒ 必须命中（词项真的出现在场景里）
# **这一半就是原来 65212 格的窟窿**。含全部汉字、数字、全角、拉丁重音。
_NONEMPTY_BAD2 = [_c for _c in _FOLD_NONEMPTY2
                  if MdCG._term_in_scene(_c, _c + "\u65e5\u5fd7") is not True]
ok(not _NONEMPTY_BAD2,
   "R11j 分区右：全部 %d 个「折叠非空」的 BMP 码点做词项、词面真出现在情境里时"
   "都必须命中（违例 %d 个：%r）"
   " —— 这一半覆盖汉字/数字/全角/重音；空的那半只覆盖 269 个组合符类字符。"
   "缺了这一半，「把某类汉字 fail-closed」这种改动全 gate 都看不见"
   % (len(_FOLD_NONEMPTY2), len(_NONEMPTY_BAD2),
      ["U+%04X" % ord(x) for x in _NONEMPTY_BAD2[:8]]))

# R11k：**星平面作词项**的分层抽样（复核第 13 轮指出 R11j 只覆盖 BMP）。
#
# R11j 的注释我写过「覆盖从 324 → 65536（完备，无遗漏）」—— **这个「完备」只对 BMP 成立**。
# 星平面 U+10000–U+10FFFF 共 **1,048,576** 个码点，做词项时一条断言都没有。
# 实测把这 5 类整片 fail-closed，477 条**全绿**（`v13_astral_verify.py`）：
#
#   astral_all（>= 0x10000 全 fail-closed）   U+1F600/20000/1D400/10000 全 True→False   ESCAPE
#   emoji U+1F600–1F64F                     同上                                    ESCAPE
#   CJK 扩展 B U+20000–2A6D6                同上                                    ESCAPE
#   数学字母 U+1D400–1D7FF                  同上                                    ESCAPE
#   单点 U+1F600                            同上                                    ESCAPE
#
# **方向说明（不夸大）**：这些是 fail-closed = 收紧 = **召回损失**，不是 fail-open；
# 且真实库 1943 个条件词项里星平面字符 **0 个**，属**潜伏缺口**。
# 但它和「汉字零覆盖」是同一个结构问题，只是换了半个码空间，故一并补上。
#
# 成本权衡（复核实测，同机）：
#   无 R11k           0 点      0.00s   6/6 全逃
#   A 粗 5点/块       1280 点   ~0.00s  5/7（漏 emoji 区间、漏单点）
#   B 中 17点/块      4352 点   ~0.00s  **7/7 全抓**   ← 拐点，取这一档
#   C 细 65点/块      16640 点  ~0.00s  7/7
#   全扫              1048576 点 17.0s  —
# 与 R7i 的分工同构：(c) 抽样进 gate，全扫在 `audit_astral_full.py`（词项维度暂无常驻全扫脚本，
# 改判据后如需完备验证，用 `v13_astral_verify.py` 的思路临时跑）。
_ASTRAL_CPS = []
for _blk in range(0x10000, 0x110000, 0x1000):
    for _off in (0x000, 0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700,
                 0x800, 0x900, 0xA00, 0xB00, 0xC00, 0xD00, 0xE00, 0xF00, 0xFFF):
        _cp3 = _blk + _off
        if _cp3 <= 0x10FFFF:
            _ASTRAL_CPS.append(_cp3)
ok(len(_ASTRAL_CPS) >= 4000,
   "R11k 自检：星平面采样点应 4000+ 个（实得 %d）—— 偏少说明采样循环漂了"
   % len(_ASTRAL_CPS))
# 注意本条自检的真实能力边界（复核第 13 轮提醒，别让名字大于能力）：
# 它只能抓「采样循环整体失效/数量骤降」；
# **抓不到「少采了某一段」** —— 因为块循环结构上不会漏块。
# 后者只能靠「改采样策略时人工 review」+ 独立全扫脚本。
_ASTRAL_TERM_BAD = []
for _cp3 in _ASTRAL_CPS:
    _c3 = chr(_cp3)
    try:
        _f3 = compact_exact_text(fold_for_match_keep(_c3))
    except Exception:                             # noqa: BLE001
        continue
    _exp3 = (_f3 == "")                           # 折叠成空 ⇒ 期望不命中
    _got3 = MdCG._term_in_scene(_c3, _c3 + "\u65e5\u5fd7")
    if _exp3:
        if _got3 is not False:
            _ASTRAL_TERM_BAD.append(("empty", _cp3, _got3))
    else:
        if _got3 is not True:
            _ASTRAL_TERM_BAD.append(("nonempty", _cp3, _got3))
ok(not _ASTRAL_TERM_BAD,
   "R11k 星平面 %d 个采样点（17 点/0x1000 块）作词项必须符合分区判据"
   "（违例 %d 个：%r）"
   " —— 「折叠成空⇒不命中 / 折叠非空⇒命中」。"
   "缺本条时「把星平面整体 fail-closed」全 gate 看不见（方向是收紧/召回损失）"
   % (len(_ASTRAL_CPS), len(_ASTRAL_TERM_BAD),
      [("U+%05X" % cp, k, v) for k, cp, v in _ASTRAL_TERM_BAD[:6]]))

# R11h 的**窄口径**补充：控制符段单独再钉一遍，失败信息能指出「是控制符这一类塌了」，
# 而不只是「65267 里有一个违例」。范围由 `unicodedata.category` 决定，
# 不再手写 `0x00–0x1F / 0x7F–0x9F`（复核建议 6：手写枚举与类定义同源但来路不同）。
#
# **与 R11j 的重复是有意的**（复核第 13 轮确认「R11j + R11h 481/0 不冲突」）：
# R11j 给的是「全域分区」（覆盖广、但失败信息只有一个违例点），
# R11h 给的是「控制符这一类的具名诊断」（覆盖窄、但红的时候直接告诉你是哪一类）。
# 两者不是替代关系，是**广度 + 可读性**的组合。
import unicodedata as _unicodedata

_C0_C1 = [chr(_cp) for _cp in range(0x00, 0x10000)
          if _unicodedata.category(chr(_cp)) == "Cc"]
ok(len(_C0_C1) >= 65,
   "R11h 自检：BMP 里 Cc 类应有 65 个（实得 %d）—— 少于此说明 unicodedata 口径变了"
   % len(_C0_C1))
_C0_C1_NONEMPTY = [_c for _c in _C0_C1
                   if compact_exact_text(fold_for_match_keep(_c)) != ""]
ok_call(lambda: (all(MdCG._term_in_scene(_c, _c + "\u65e5\u5fd7") is True
                     for _c in _C0_C1_NONEMPTY)),
   "R11h 折叠后非空的 Cc 类控制符（%d 个，由 unicodedata 派生）走子串支，"
   "词项真出现时须命中 —— R11g 不是「控制符一律不命中」" % len(_C0_C1_NONEMPTY))
# R11i：注释订正（复核第 11 轮的设计判断，我认为成立，采纳）。
# R11h 断言的 `_term_in_scene(ch, ch+"日志") is True` 测的是**单元契约**
# （「折叠后非空 ⇒ 走子串支」），**不是生产行为**：
#   `judge_qualification` 的 scene 是 `json.dumps(scene, ensure_ascii=False)`，
#   而 json.dumps 会把**全部 0x00–0x1F 转义**成 ASCII 字面（`\u0000` / `\t` / `\n`），
#   故 C0 段在生产路径上**根本不会以原文出现在场景串里**；
#   DEL/C1（0x7F–0x9F）**不转义**，是唯一「能真的做子串匹配」的控制符段。
# 结论：不该对控制符 fail-closed —— 理由**不是**「三树一致」，而是
# **判据只该由「折叠后是否为空」决定，不该由「字符类别看着可疑」决定**。
# 加一条「控制符一律不命中」等于在判据里塞了个与折叠无关的分类器，
# 与我 §1.4 的教训（「下界只能由数据从哪开始决定，不能由我觉得哪些用不上决定」）同型。
# 顺带记一个**存量**缺口（不在 #753 范围）：json.dumps 的转义污染匹配面 ——
# `cond='u0000'` + query 含真 NUL ⇒ 三树都 ACCEPT「命中 u0000」。属存量 fail-open。
ok_call(lambda: (MdCG._term_in_scene("a\u0301", "a\u0301 \u65e5\u5fd7") is True),
   "R11f 折叠后为 'a' 的组合词项（a+U+0301）仍须命中 —— 证明 R11 只挡真空串，"
   "不连带误杀「折叠后仍有内容」的词项")
# R11b：词项为空的正式形态（`t = ""`）同样必须 False —— 这条同时钉住「①②都删」
ok_call(lambda: (MdCG._term_in_scene("", "\u4efb\u610f") is False),
   "R11b 空词项必须不命中（基线 False；两道空守卫都删时 '   ' 仍是 False，"
   "但空串会翻 True）")
ok_call(lambda: (MdCG._term_in_scene("", "\u4efb\u4f55\u573a\u666f api \u65e5\u5fd7") is False),
   "R11c 空词项在非空情境里也必须不命中（`'' in 任意非空串` 为真，"
   "这是 ② 缺失时最直接的 fail-open）")
# R11d：正对照 —— 能折叠出内容的词项不得被 R11 误伤
ok_call(lambda: (MdCG._term_in_scene("api", "api \u65e5\u5fd7") is True),
   "R11d 正常词项仍命中（R11 不是把折叠整个关掉）")
ok_call(lambda: (MdCG._term_in_scene("\u20dd", "\u20dd \u65e5\u5fd7") is True),
   "R11e 折叠后非空的非 ASCII 词项（U+20DD）仍命中（不得连坐）")

print()
print("=" * 68)
print("R12. `NEG_CUES` 逐个 cue 必须真的生效（删一个就红）")
print("=" * 68)
# 2026-11-05 第 11 轮：复核 v10 §三.1 指出「从 NEG_CUES 删掉 `"不"` → 行为翻转，
# 15 个测试文件全绿」。我复测**属实**（本 gate 410/0、fold 41/0、colon 83/0 全绿）。
# 根因：全仓没有一条断言**逐个**遍历 NEG_CUES 验证每个 cue 都生效。
#
# 为什么用**固定字面表**而不是 `for cue in NEG_CUES`：
# 后者在「删掉某个 cue」时只是循环少一轮，照样全绿 —— 正是要防的那个方向。
# 固定表 + `_NEG_CUES_FIXED ⊆ NEG_CUES` 双向钉住：
#   · 删 cue → 包含性断言红
#   · cue 失效（不再被识别为否定）→ 行为断言红
# 新增 cue 不在这张表里，属「增长」方向，由 R7i 的派生集自动覆盖。
_NEG_CUES_FIXED = ["\u4e0d\u5c5e\u4e8e", "\u4e0d\u662f", "\u6ca1\u6709",
                   "\u5e76\u975e", "\u5e76\u65e0", "\u672a\u6709",
                   "\u4e0d", "\u975e", "\u6ca1", "\u65e0", "\u672a",
                   "\u522b", "\u83ab"]
ok(set(_NEG_CUES_FIXED) <= set(_NEG_CUES),
   "R12a 固定 cue 表必须全部仍在 NEG_CUES 里（缺 %r —— 有人删了否定词）"
   % (sorted(set(_NEG_CUES_FIXED) - set(_NEG_CUES)),))
for _cue in _NEG_CUES_FIXED:
    # 判据：cue 紧邻词项 ⇒ 负条件面**不得确认**（返回空），且正条件面必须 False。
    # 两面同时钉，是因为删 cue 会让两面**一起**翻（方向是收紧失效）。
    ok_call(lambda: (bool(neg_condition_hits(["api"], _cue + "api\u00e9 \u8bf4\u660e")) is False),
       "R12b 否定 cue %r 必须生效：负条件面不得确认" % (_cue,))
    ok_call(lambda: (MdCG._term_in_scene("api", _cue + "api\u00e9 \u8bf4\u660e") is False),
       "R12c 否定 cue %r 必须生效：正条件面必须不命中" % (_cue,))

print()
print("=" * 68)
print("R13. 静态字符类不变量：词边界环视的字符类必须**恰为** [A-Za-z]")
print("=" * 68)
# 回答问题「49s 星平面全扫该不该进 gate」（复核 v10 §六.3 / 我给复核的第 3 问）。
# 实测三种方案对同一批「边界字符类被改宽」变异的鉴别力（`v11_r13_static.py`）：
#
#   变异                         P0 现状抽样(768点)   P2 函数域静态   星平面全扫(73s)
#   M0 左加炼金块 U+1F700..        ESCAPE            CAUGHT        CAUGHT
#   M1 左加数字 0-9                ESCAPE            CAUGHT        未测
#   M2 右加数字 0-9                ESCAPE            CAUGHT        未测
#   M3 左加下划线 _                ESCAPE            CAUGHT        未测
#   M4 左加韩文 U+AC00..U+D7AF     ESCAPE            CAUGHT        未测
#
# 结论：**全扫与静态不是「精度 vs 抽样」，两者在判别力上等价，成本差 3 个数量级**
# （73s vs 0.35s）。全扫真正不可替代的作用只剩一条：验证**实现自身的运行时行为**
# 在全部码点上正确（当前违例 0）。而「守卫有没有孔」这件事，静态判据做得更彻底
# ——它不依赖抽样，覆盖**全部**可能被加进字符类的东西（含未来新增的码点区间）。
#
# 故：静态判据**进 gate**（本条）；全扫保留为独立慢速脚本，只在改判据后手动跑。
# 这样日常回归不再有 49s 的负担，而守卫的覆盖面反而**变宽**了。
import inspect as _inspect
import re as _re

from .mdcg import _negated_at as _NEGATED_AT

# R13 的覆盖面：**扫整个 mdcg.py 源文件**，不再只扫我列的 4 个函数
# （2026-11-05 第 11 轮自查：我原先列了 4 个函数清单，那样「将来新增一个带词边界
# 环视的判定函数」就看不见了 —— 覆盖面依赖我维护这张清单，是脆的）。
#
# **判据本身也必须与写法无关**（复核第 11 轮打回，这是本轮最重要的一条）：
# 我第一版写的是「匹配 `(?<![...])` 这种方括号字符类」。于是——
#   · 新增函数用 `(?<!\w)`（同一语义的另一种写法）  → 453/0 全绿，ESCAPE
#   · 新增函数用裸 `\b`（根本不是环视，是并列的第二条词边界机制）→ 453/0 全绿，ESCAPE
# 两条都实测复现（`v11_rt_verify.py`：C1/C2 均 ESCAPE）。
# 更糟的是 `R13c`（处数==4）也拦不住：正则提不到新增的两处，`_R13_SEEN` 仍是 4；
# 而自检 `R13a`（≥2 处）**用的是同一个正则**，所以它也是绿的 ——
# **自检与被检对象共用同一个失效点**，这是最难自查的一类真空。
#
# 故判据换成：「**提取任何 lookaround，逐字与白名单比对**」，再单列一条禁裸 `\b`。
# 白名单只有两个合法形态（`mdcg.py` 当前全部 4 处都是这两者）。
_LA_OK = {"(?<![A-Za-z])", "(?![A-Za-z])"}
_R13_SRC = _inspect.getsource(__import__("md_cg.mdcg", fromlist=["x"]))
_R13_SEEN = _re.findall(r"\(\?<?[=!][^)]*\)", _R13_SRC)
_R13_BAD = [x for x in _R13_SEEN if x not in _LA_OK]
# R13a：先说「真的找到了」——但**不能只用被检正则做自检**（见上），
# 故这里同时钉「恰好 4 处」与「全部在白名单里」，两个方向都断。
ok(len(_R13_SEEN) >= 2,
   "R13a 必须从 mdcg.py 源码里真的提取到 lookaround（实得 %d 处 %r）"
   " —— 提到 0 处说明正则漂了，本节会静默空转" % (len(_R13_SEEN), _R13_SEEN))
ok(not _R13_BAD,
   "R13b 全文件 lookaround 必须**逐字**等于 [A-Za-z] 的左右边界白名单"
   "（违例 %r；白名单 %r）"
   " —— `(?<!\\w)` 这类简写、带空格的 `(?<! [A-Za-z])`、交替 `[A-Za-z]|[0-9]`"
   " 全部在这里红，包括将来**新增**函数里的" % (_R13_BAD, sorted(_LA_OK)))
# R13d/R13e：**裸 `\b` / `\B` / `\w` / `\W` 的变更告警**。
# 它们不是环视，`R13b` 结构上永远看不见它们，但它们就是「词边界只认 [A-Za-z]」
# 这条规则的**另一条实现路径**（`\w` = `[A-Za-z0-9_]`，`\b` 是裸词边界）。
#
# **用 AST 扫字符串常量，不用文本正则**（2026-11-05 第 11 轮，我自查时发现的）：
# 文本正则会把**注释**里的 `\b` 也当命中（实测假红）。
# AST 版只看 `ast.Constant`，注释天然不在其中。
#
# **必须如实声明这条断言的性质与上限**（实测 `v11_r13e_probe.py`）：
#
#   形态                                  AST 版   说明
#   r"\b" / rf"\b{...}"                   红      字面量里写了 \b
#   "\b" 放在多行字符串常量里                红      同上
#   注释里提到 \b                           不红     AST 看不见注释（正确）
#   普通字面量 "\b"                          不红     AST 里已是控制符 \x08，不是反斜杠+b（正确）
#   f-string / JoinedStr 里的 Constant        红      实测 ast.walk 可达
#   r"\\b"（二次转义，语义是**字面** \b）      红      **假阳性**，见下
#   b"\b"（bytes 常量）                      红      实测曾漏，已修（见下）
#   "\\" + "b"（变量拼接）                   **不红**  动态构造，静态不可见
#   chr(92) + "b"（chr 构造）               **不红**  同上
#   从外部配置/常量表读入                      **不红**  同上
#
# **bytes 常量曾被我漏掉**（给复核提问题后自查发现，第 9 次自我推翻）：
# `b"\b"` 在 AST 里是 `Constant(value=b"\x08")`，`isinstance(n.value, str)` 为假
# ⇒ 只看 `str` 的实现完全绕过它。现改为 `str` 与 `bytes` 都查。
#
# 结论：**这是「变更告警」，不是「完备判据」。**
# 它拦得住「直接写出反斜杠转义」这一形态（覆盖实践中 99% 的写法），
# 但**原理上拦不住动态构造的正则** —— 静态扫描无法求值。
# 二次转义 `r"\\b"` 会假红，属**有意为之**：它要求作者人工确认一次
# 「我这个是字面量，不是词边界」，成本极低，比放过一个真 `\b` 划算。
#
# 已知的真实缺口登记在 ISSUE §7「未覆盖」里，不假装覆盖。
import ast as _ast

try:
    _R13_TREE = _ast.parse(_R13_SRC)
    _R13_STRS = []
    for _n in _ast.walk(_R13_TREE):
        if not isinstance(_n, _ast.Constant):
            continue
        _v = _n.value
        if isinstance(_v, str):
            _R13_STRS.append(_v)
        elif isinstance(_v, bytes):               # bytes 源码形态（第 9 次自查补）
            try:
                _R13_STRS.append(_v.decode("utf-8", "replace"))
            except Exception:                     # noqa: BLE001
                pass
except SyntaxError:                               # 源码都解析不了，直接红
    _R13_STRS = []
    ok(False, "R13d 无法用 AST 解析 mdcg.py 源码 —— 本节失效")
_R13_BARE_B = [s for s in _R13_STRS if _re.search(r"\\[bB]", s)]
ok(not _R13_BARE_B,
   "R13d 字符串常量里不得出现裸 `\\b`/`\\B`（实得 %d 个：%r）"
   " —— 裸词边界是环视之外的第二条词边界机制，R13b 看不见它。"
   "**注意这是变更告警**：`r\"\\\\\\\\b\"` 这种二次转义也会红，请人工确认"
   % (len(_R13_BARE_B), [s[:40] for s in _R13_BARE_B[:3]]))
_R13_BARE_W = [s for s in _R13_STRS if _re.search(r"\\[wW]", s)]
ok(not _R13_BARE_W,
   "R13e 字符串常量里不得出现 `\\w`/`\\W`（实得 %d 个：%r）"
   " —— 等价于把 `[A-Za-z0-9_]` 写进边界，与 R13b 的规则冲突"
   % (len(_R13_BARE_W), [s[:40] for s in _R13_BARE_W[:3]]))
# R13c：把「当前只有 4 处」也钉住 —— 这既是**变更告警**，也是自检：
# 若哪天有人新增了一处且写宽，R13b 会红；若写成合法白名单形态，这里会红并提示
# 「你新增了一处，请确认 R7i/R13 的判定基准是否也要跟着扩」。
# 它把「覆盖面静默扩大」变成一次显式决定。
ok(len(_R13_SEEN) == 4,
   "R13c lookaround 处数应为 4（实得 %d 处 %r）"
   " —— 变多说明有人新增了词边界判定，请确认新函数的语义并更新本断言"
   % (len(_R13_SEEN), _R13_SEEN))

# ---- 附：慢速全扫的分工说明（不在本文件执行） ----
# `audit_astral_full.py` 对星平面 **961437 个码点** 做全扫（左侧 23.3s + 右侧 22.9s
# = 46.2s），实测违例 0。本文件 (c) 只做「按 0x1000 块首/中/尾」抽样（秒级）。
# 两者分工明确：**改判据后必须手动跑一次全扫**，日常回归跑本文件。
# 复核第 10 轮已证：抽样区段选得再好也是覆盖性问题（把 `[A-Za-z\U0001F700-\U0001F77F]`
# 炼金块加进字符类，本文件全绿而行为真的变了）—— 所以这条分工必须写在文件里，
# 不能让人以为「gate 全绿 = 星平面已证完」。



print()
print("=" * 68)
print("cond_term_fold_gate: %d passed, %d failed" % (PASS, FAIL))
print("=" * 68)
sys.exit(1 if FAIL else 0)
