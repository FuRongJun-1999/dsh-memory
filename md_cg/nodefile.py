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
import hashlib
import json
import re
import time

_DELIM = "---"
# 完整的 6 行 MARKS：功能名（标题）+ 5 要素（条件、子功能、执行、验证、不适用）。
# 「验证方式」与「不适用条件」是白箱的关键新增，缺则不可证 ACCEPT/REJECT。
CCG_MARKS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
# 门槛即全部 MARKS：原先「生效条件可隐含」的豁免已废止（观测位置 ≠ 生效条件，
# 见 `condition_space_text`）——生效条件必须由 condition_space 四槽合成显式声明，
# 不存在「常用条件默认省略」的合法情形。缺它即缺证据：补写，或判 BLINDSPOT。
CCG_REQUIRED = CCG_MARKS

# ---- 裁定 B（使用者 2026-09-16）：六要素的契约角色（术语真源） -----------------
# 六要素不是注释/描述，而是**接口契约**——每行在契约里有一个确定角色：
#     功能名 = 签名 signature（可执行入口符号）
#     生效条件 = 前置条件 precondition（由 condition_space 四槽合成，唯一入口）
#     子功能 = 内部子功能分解（自述）**兼** 依赖 dependency（跨节点）
#     执行 = 调用 invocation
#     验证方式 = 后置条件 postcondition + test
#     不适用条件 = 拒绝域 rejection_domain
# 「生效条件」的契约角色正是 **precondition**——这与其「不可隐含、必须四槽合成」
# 的既有硬约束同源：缺前置条件的接口无法判定可否调用，故缺参即编译错误。
# 本常量是术语的**唯一真源**；其余模块（如 ccgc.CONTRACT_ROLES）一律引用本处，
# 禁止各自再定义一份，防「术语双写法」漂移。
#
# 「子功能」的**双语义**（收窄裁定 b · 使用者 2026-09-19）——这是本槽位的既成事实，
# 不能只看本常量的 "dependency" 四字：理论真源（智能论 3.4 §6章.3 六要素表）把该行
# 定义为「内部子功能分解（①②③）」= **对自身的描述**；本常量记其契约角色为
# dependency = **寄生于他者**。同一槽位承载两种语义，**靠形态区分**（不是靠猜）：
#   · 自然语言描述本单元内部构成 → **自述**，不构成依赖声明，无需 depends_on；
#   · `@<节点 id>` 显式引用其它单元 → **跨节点依赖声明**，必须落 depends_on。
# 判据真源 = `declares_dependency`（本模块）；闸门 = `ccgc._check_deps` /
# `writepipe._gate_deps`（两闸共用同一判据，收窄一处即两闸同步）。
# **不得再退回「值非哨兵即声明」**：CCG 编译产物六要素必含本行，退回即让每个节点
# 落库后被 E050 永久锁死（test_ccgc V16f 实证），且与理论真源的自述口径直接冲突。
CCG_CONTRACT_ROLES = {
    "功能名":     "签名 signature（可执行入口符号）",
    "生效条件":   "前置条件 precondition",
    "子功能":     "内部子功能分解 self_decomposition ／ 依赖 dependency"
                  "（双语义，以 @<节点 id> 显式引用为界）",
    "执行":       "调用 invocation",
    "验证方式":   "后置条件 postcondition + test",
    "不适用条件": "拒绝域 rejection_domain",
}

# ---- 裁定 C（Phase 0 契约裁决 · 2026-09-17）：索引元条件与功能生效条件字段分家 ----
# 病根：codeindex.render 曾把**机械推导的索引元条件**（本地源码仓 / 全时窗 /
# AST 工具 / 文件可读）写成「生效条件」行，与「功能生效条件」（人工声明：
# 这段代码在何种输入/状态下正确）**共用同一字段名**。检索侧
# mdcos._ccg_field 取首个匹配 → 源码里人工写的生效条件行被永久压制 →
# 「补了注释」与「没补」在检索结果上不可区分。
# 处置（沿用 backfill.py 已裁定先例「观测位置 ≠ 生效条件」）：
#   · 「生效条件」只承载**功能前置条件**，来源仅限人工/源码声明，
#     **不由 render 合成**（合成即冒充）；
#   · 索引元条件改由 INDEX_META_MARK 承载，与 CCG_MARKS **零重名**
#     （机械可判，见 is_ccg_mark）。
# 权威契约：docs/mdcg/代码评审与条件化注释_契约_v0.1.md
INDEX_META_MARK = "索引元条件"


# 生效条件：name 无论为何值先经 str().strip() 归一（name 为 None 时即字符串 "None"），归一结果落在模块常量 CCG_MARKS 中即返回 True，否则 False。
def is_ccg_mark(name: str) -> bool:
    """该字段名是否为 CCG 六要素之一（合成区零重名契约的机械判据）。

    给「合成区字段名 ∩ CCG_MARKS = ∅」提供**可执行**判据，而不是靠注释约定：
    test_codeindex 逐行核合成区用到的字段名。
    """
    return str(name).strip() in CCG_MARKS

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

# ---- 裁定 D（2026-09-19）：可验证记忆单元的**字段名真源** --------------------------
# 「子功能」的契约角色是**依赖 dependency**（见 CCG_CONTRACT_ROLES），其落字段即
# `depends_on`——名字与角色对齐（不叫 sub_features，避免同一概念两种写法）。
# 依赖一旦失效，下游的「还成不成立」就变了，故它与验证态、时间轴同属一层。
DEPENDS_ON_FIELD = "depends_on"

#: 双时间轴：何时开始成立 / 何时不再成立（判定未生效·生效中·已过期）。
#: `valid_until` 既有（已被 scrub 的过期消费面使用）；`valid_from` 本轮补齐。
VALID_FROM_FIELD = "valid_from"
VALID_UNTIL_FIELD = "valid_until"

#: 双时间轴的**规范键**（2026-09-19 阶段一）：新写入落此；历史键 `valid_from` /
#: `valid_until` 保留为**读取侧回落别名**（存量不迁移、零破坏）。本处只登记字段名；
#: **行为真源**（取值优先级 `effective_* > valid_* > 其余别名` 与三态判定）见
#: md_cg/trust.py 的 FROM_ALIASES / UNTIL_ALIASES / validity()。
EFFECTIVE_FROM_FIELD = "effective_from"
EFFECTIVE_UNTIL_FIELD = "effective_until"

#: 信念时间：体系**何时确认此条**——取代（supersede）/ 审核的排序锚。
#: **第三类语义**：既不是「尚未开始」也不是「已经结束」，故**不入** scrub 的任一
#: 键族（并入即把「已确认」误判成「已生效 / 已失效」）。物理隔离守卫见
#: test_validity_filter.py 的交叉断言。
BELIEVED_AT_FIELD = "believed_at"

#: 过期时刻（写盘冗余：由 effective_until 派生，供审计 / 对账免计算直读）。
EXPIRED_AT_FIELD = "expired_at"

#: 巩固留痕（2026-09-19 阶段一）：何时巩固 / 巩固进哪一条（成员 → 概念 id）。
#: 与 `promoted_at`（层迁移时刻）同族——把「归并产物可溯源」从流程记录升为一等字段。
#: **行为真源**（写入侧）见 md_cg/consolidate.py 的 induce / promote。
CONSOLIDATED_AT_FIELD = "consolidated_at"
CONSOLIDATED_INTO_FIELD = "consolidated_into"

#: 归纳来源（概念节点侧）：前身成员清单 / 归纳时刻。与 `consolidated_*` 同族——
#: 成员侧列「巩固进哪一条」，概念侧列「前身是谁」，两侧互查即完整血缘。
INDUCED_FROM_FIELD = "induced_from"
INDUCED_AT_FIELD = "induced_at"

#: 巩固 / 归纳留痕字段族（单一真源）：全族**不进索引白名单**（审计/血缘向，非查询
#: 热点），故 `add()` 覆写时须**回读节点文件**继承（索引快照里没有这些键）——
#: 否则概念节点被一次普通覆写（如审核 edit/merge 重写）即丢掉前身清单。
CONSOLIDATION_FIELDS = (CONSOLIDATED_AT_FIELD, CONSOLIDATED_INTO_FIELD,
                        INDUCED_FROM_FIELD, INDUCED_AT_FIELD)

#: 验证态字段。**刻意不叫 `state`**——该名已被裁决四态（ACCEPT/REJECT/DEFER/
#: BLINDSPOT）占用，`lifecycle_state` 的先例同此动机（观测位置不同即命名不同）。
#: 状态枚举与合法迁移表的**行为真源是 md_cg/trust.py**；本处只登记字段名，
#: **不复制枚举**——复制即制造第二份真源，与 CCG_CONTRACT_ROLES 的单一真源纪律相悖。
VERIFICATION_STATE_FIELD = "verification_state"

# ---- 「子功能」声明的**值语义**：哨兵与解析 --------------------------------------
# 行存在 ≠ 有声明：`# 子功能：无` 是合法填充（绝大多数知识节点不依赖任何单元），
# 若把它也算成「声明了依赖」，全库普通节点都会被 E050 硬拒——闸门立刻沦为噪声源。
# 故必须区分「行存在」与「构成真实声明」，判据收在这里（单一真源，ccgc/writepipe 共用）。
DEP_DECL_SENTINELS = ("无依赖", "无", "不适用", "不需要", "none", "n/a", "na", "-", "—")


# 生效条件：value 为 None 或 strip 后为空 → True；strip 后等于 DEP_DECL_SENTINELS 任一项、或为该哨兵加尾部括号说明（如「无（不依赖其他单元）」）→ True；其余 False（不做语义判断）；
def is_dep_sentinel(value) -> bool:
    """纯函数：依赖槽的值是否属于「无依赖」哨兵。

    只认**完全相等**或**哨兵+括号说明**两种形态，不做语义猜测——「无法确定」
    这类真实陈述不得被误判为「无」（宁可多要求一次 depends_on，不可漏掉声明）。
    """
    s = "" if value is None else str(value).strip()
    if not s:
        return True
    for mark in DEP_DECL_SENTINELS:
        if s == mark:
            return True
        for lp, rp in (("（", "）"), ("(", ")")):
            if s.startswith(mark + lp) and s.endswith(rp):
                return True
    return False


# 生效条件：content 中不存在名字等于 field_name 的 `# 字段：` 行 → 返回 None；存在 → 返回首个命中行首个冒号之后的 strip 结果（可为空串）；
def ccg_field_value(content, field_name: str):
    """读取 `# <字段>：<值>` 的值（首个命中行；全/半角冒号兼容）。无该行 → None。

    与 `ccgc._upsert_ccg_line` 的解析口径一致（去 `#`→按冒号切名字→名字相等即
    命中）——即**写入口径与读入口径共用同一条行语义**，避免「写进去读不出」。
    """
    for ln in (content or "").split("\n"):
        s = ln.strip()
        if not s.startswith("#"):
            continue
        if s.lstrip("#").strip().split("：")[0].split(":")[0].strip() != field_name:
            continue
        for p in ("# " + field_name + "：", "# " + field_name + ":"):
            if p in ln:
                return ln.split(p, 1)[1].strip()
        return ""
    return None


# ---- 「子功能」行中的**跨节点引用**：显式标记与提取 -------------------------------
# 为什么需要它（收窄判据 · 使用者 2026-09-19 裁定 b）：「子功能」的契约角色是
# dependency，但同一个槽里实际承载着两种语义完全不同的内容——
#   ① **自述子功能**：本单元**内部**由哪些子步骤/子模块构成（如「按扩展名把文件
#      路由到对应摄取器」）。它描述的是自身，不引用任何其它记忆单元。
#   ② **跨节点依赖**：本单元的成立与否**寄生于另一个记忆单元**（如 `@code_xxx`）。
#      只有它才是失效传播的入口，也只有它才需要落 `depends_on`。
# 旧判据「值非哨兵即声明依赖」把①一并判成②：CCG 编译产物六要素必含「子功能」
# 行，于是该节点一旦落库就被永久要求 `depends_on`——第二次 link 必被 E050 硬拒
# （test_ccgc V16f 实证：合法内容被自己的闸门锁死）。故**收窄判据：只有显式引用
# 形态才构成跨节点依赖声明**，自然语言自述不算（依赖不是必填元数据，不得默认要求）。
#
# 形态约定：`@` 紧跟节点 id（`[A-Za-z0-9_]` 起头，可含 `.`/`-`）；`@` 左侧不得是
# 标识符字符——后半条排除 `user@host`（邮箱等）被误读为引用。中文自然语言里 `@`
# 极罕见，故该标记本身就是「这是引用」的显式信号，**不依赖语义猜测**（与哨兵
# 「只认完全相等」同一纪律：能机械判的绝不猜）。
DEP_REF_MARK = "@"
DEP_REF_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_][A-Za-z0-9_.\-]*)")


# 生效条件：value 为 None 时按空串处理 → 返回空列表；为任意值且 str 化后正则无命中 → 空列表；命中 → 按出现顺序返回去重后的 id 列表。
def dep_refs(value) -> list:
    """从「子功能」行的值中提取**显式跨节点引用**（`@<节点 id>`）→ 去重保序列表。

    只做**形态提取**，不校验目标是否存在——「声称依赖」与「目标存在」是两件事，
    混在一处会让「声称依赖一个并不存在的节点」被静默当成「没声明」（E051 永不触发）。
    """
    if value is None:
        return []
    out = []
    for m in DEP_REF_RE.finditer(str(value)):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


# 生效条件：content 中「# 子功能：」行缺失 → False；行存在且其值为空或命中依赖哨兵（is_dep_sentinel）→ False；行存在且值含显式跨节点引用（dep_refs 非空）→ True；其余（自然语言自述子功能）→ False；
def declares_dependency(content) -> bool:
    """「# 子功能：」是否构成**跨节点依赖声明**（行存在 ∧ 值非哨兵 ∧ 含 `@<id>`）。

    这是 E050 硬拒的**前置判据真源**：只有**显式声称**依赖某节点，才要求
    `depends_on` 给出可解析目标。行缺失、哨兵、以及**自述子功能**（自然语言描述
    本单元的内部构成）一律按「未声明」处理——依赖不是必填元数据，把自述当声明会
    让每个 CCG 节点（六要素必含「子功能」行）永久被要求 depends_on，闸门反过来
    锁死合法写入。**只有「声称依赖却不落字段」才是契约违规**（声称与落盘不一致，
    被依赖单元变动时下游无处可传，传播链从源头断掉）。
    """
    val = ccg_field_value(content, "子功能")
    if val is None or is_dep_sentinel(val):
        return False
    return bool(dep_refs(val))


# 生效条件：content 为 None 或空串时按源码的 content or "" 回落空串计算，非空时按其原值编码，一律返回 sha256(utf-8) 十六进制摘要的前 12 位（content 的 frontmatter 不计入口径由调用方保证）。
def content_hash(content: str) -> str:
    """节点正文的**内容指纹**（sha256 前 12 位）——全仓唯一实现。

    两处共用且必须逐位一致，否则对账/变更探测会永远"匹配成功"而失去意义
    （与 `codeindex.region_hash` 同一纪律：两侧各写一份哈希算法，漂移就悄悄失效）：
      ① 索引快照 `_index.json` 的 `content_hash`（变更探测）；
      ② 写入两段式（`twophase`）的 intent 载荷指纹——崩溃后靠它回答
         「那笔写入到底落盘了没有」。

    口径：只哈希**正文**，不含 frontmatter——frontmatter 会被写路径正常改写
    （importance / protected / 生命周期状态 / 时间戳），把它算进去则「内容没变、
    元数据变了」也会判成不匹配，对账会大面积误报 interrupted。
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:12]


# 生效条件：frontmatter（任意 dict，键按 sorted 输出）与 content（任意 str）均无前置校验即生效；content 不以 "\n" 结尾时补一个换行，返回 "---" + 各键的 "{k}: {json.dumps(v, ensure_ascii=False)}" 行 + "---" 行 + 正文。
def dumps(frontmatter: dict, content: str) -> str:
    lines = [_DELIM]
    for k in sorted(frontmatter):
        v = frontmatter[k]
        # 一律 JSON 序列化：值内不会出现裸换行，切分才可靠；数字/字符串也保持可读
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append(_DELIM)
    body = content if content.endswith("\n") else content + "\n"
    return "\n".join(lines) + "\n" + body


# 生效条件：text 以 "---\n" 开头且其后存在 "\n---\n" 时才解析——head 段内含 ":" 的行按首个 ":" 拆键值（json.loads 成功取值、抛 ValueError 则保留原字符串），不含 ":" 的行跳过，返回 (fm, content)；不满足上述两个起始条件时返回 ({}, text)。
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


# 生效条件：content 中出现 "# {mark}：" 或 "# {mark}:"（中/英文冒号）即把该 mark 计入 present 与 required_present；complete 为 required_present 覆盖全部 CCG_REQUIRED、all_present 为 present 覆盖全部 CCG_MARKS，ratio = len(required_present)/len(CCG_REQUIRED)，四键连同两个清单一起返回。
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


# 生效条件：fm 的 "verification_basis" 缺键或取值为 None 时（.get 回落 None）直接返回 False；取值非 None 时，仅当该值属于模块常量 VERIFICATION_BASIS 才返回 True。
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


# 生效条件：value 为 None 或 str(value).strip() 为空串时返回 True；否则仅当去空白后的字符串包含 PLACEHOLDER_MARKERS 中任一标记词时返回 True，其余返回 False（不做语义判断）。
def is_placeholder_text(value) -> bool:
    """占位标记的纯函数判定：空值或含占位标记 → 不可渲染为事实。

    只认**标记词**，不做语义猜测：宁可漏判（少写一行），不可误判（把真实的
    条件当成占位而丢弃）。
    """
    s = "" if value is None else str(value).strip()
    if not s:
        return True
    return any(m in s for m in PLACEHOLDER_MARKERS)


# 生效条件：content 中含 "# 不适用条件："（全角冒号）或 "# 不适用条件:"（半角冒号）即返回 True，两者都不出现返回 False。
def has_non_applicable(content: str) -> bool:
    """是否声明了不适用条件——REJECT 路径成立的必要条件。

    没有不适用条件的节点在白箱下不能 REJECT（无法证明「不适用」），
    只能 ACCEPT 或 BLINDSPOT。这是第 1 篇第 10 章从 28%→88% 的关键。
    """
    return "# 不适用条件：" in content or "# 不适用条件:" in content


#: 负条件字段名——它是**反例声明**，不是召回键
NEG_FIELD = "不适用条件"


# 生效条件：content 为 None 时按 "" 处理；逐行 strip 后，仅当该行以 "#" 开头且 lstrip("#").strip() 又以 NEG_FIELD 开头时丢弃该行，其余行原样保留（保留原缩进），返回保留行的 "\n".join。
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


# 生效条件：value 为 list/tuple 时用「、」连接各元素 str().strip() 后非空的部分（空元素跳过）；value 为 None 时返回 ""；其余类型返回 str(value).strip()。
def _as_slot_text(value) -> str:
    """槽值 → 单行文本；列表值用「、」连接（「；」留给槽间分隔，不可混用）。"""
    if isinstance(value, (list, tuple)):
        return "、".join(str(x).strip() for x in value if str(x).strip())
    if value is None:
        return ""
    return str(value).strip()


# 生效条件：value 可被 value[0]、value[1] 取下标并 float 化，且 lo <= FULL_TIME_WINDOW_MIN 同时 hi >= FULL_TIME_WINDOW_MAX 时返回 True；取值或 float 转换抛 TypeError/ValueError/IndexError/KeyError 时返回 False。
def is_full_time_window(value) -> bool:
    """时间窗是否覆盖全时窗（任意时刻成立）。解析不了 → False（不冒充已声明）。"""
    try:
        lo, hi = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    return lo <= FULL_TIME_WINDOW_MIN and hi >= FULL_TIME_WINDOW_MAX


# 生效条件：float(value) 能被 time.gmtime 接受时按 UTC 返回 "%Y-%m-%d %H:%M"；转换或格式化抛 TypeError/ValueError/OSError/OverflowError 时返回 ""。
def _fmt_ts(value) -> str:
    """unix 时间戳 → 「YYYY-MM-DD HH:MM」（UTC）；解析不了 → ""。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(value)))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


# 生效条件：先判 is_full_time_window(value) 为真则直接返回 FULL_TIME_WINDOW_TEXT（不落裸数组）；否则取 value[0]、value[1] 的 UTC 文本（下标/取值抛 TypeError/IndexError/KeyError 返回 ""），两者有任一为空串也返回 ""，均非空时返回 "{lo}～{hi}（UTC）"。
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


# 生效条件：cs 为非 dict 时返回 ""；否则取 cs.get(key)（缺 key 键得 None），key == "time_window" 走时间窗文本、其余键走槽值文本，结果为假值或经 is_placeholder_text 判为占位时返回 ""，否则返回该文本。
def condition_slot_text(cs, key: str) -> str:
    """单槽 → 可读值；缺失/空/待填充占位 → ""（不冒充已声明）。"""
    if not isinstance(cs, dict):
        return ""
    value = cs.get(key)
    s = time_window_text(value) if key == "time_window" else _as_slot_text(value)
    if not s or is_placeholder_text(s):
        return ""
    return s


# 生效条件：cs（任意值，非 dict 由 condition_slot_text 兜为 ""）下，仅把 CONDITION_SLOTS 中 condition_slot_text(cs, key) 返回非空串的槽按固定顺序收集为 (槽名, 标签, 文本) 列表，缺失槽不写入。
def condition_space_slots(cs) -> list:
    """→ [(槽名, 标签, 文本)]，只含**已声明**的槽（缺失槽不写）。"""
    out = []
    for key, label in CONDITION_SLOTS:
        text = condition_slot_text(cs, key)
        if text:
            out.append((key, label, text))
    return out


# 生效条件：cs（任意值）下，以 condition_space_slots(cs) 实际产出的槽名为已声明集合 have，返回 CONDITION_SLOTS 中不在 have 里的键名列表（已声明槽不计）。
def condition_space_missing(cs) -> list:
    """缺失槽名清单（待补台账用）；已声明槽不计。"""
    have = {k for k, _l, _t in condition_space_slots(cs)}
    return [k for k, _l in CONDITION_SLOTS if k not in have]


# 生效条件：cs 任意值；require_full（默认 True）为真且 condition_space_slots(cs) 的槽数不等于 len(CONDITION_SLOTS) 时返回 ""；否则按固定顺序用「；」连接已声明槽的 "{label}：{text}"（require_full 为 False 时仅部分槽也照渲，无槽则返回 ""）。
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


# 生效条件：text 为 None 时按 "" 处理；去空白后的字符串以 LEGACY_POSITION_PREFIX 开头且长度严格大于该前缀长度时返回 True，其余（含仅等于前缀本身、空串）返回 False。
def is_legacy_position_condition(text) -> bool:
    """文本是否为「观测位置：X」形态的单槽冒充（旧口径残留）。

    只认前缀形态，不做语义猜测：用于审计与迁移定位，不参与正常渲染。
    """
    s = "" if text is None else str(text).strip()
    return s.startswith(LEGACY_POSITION_PREFIX) and len(s) > len(LEGACY_POSITION_PREFIX)


# 生效条件：text 为假值（None/空串）时按空文本处理返回 []；否则按「；/;」拆槽、槽内含「：」或「:」时取首个分隔符之后的内容，再按「，,、/（）()」切短语，丢弃长度 <2、纯数字及命中时间维哨兵关键词的短语并去重后返回 out；
def cond_terms(text: str) -> list[str]:
    """生效条件声明 → 匹配短语列表（确定性切分，无语义猜测）。

    切分规则：按槽分隔「；/;」拆槽（condition_space_text 以「；」连四槽）
    → 每槽剥「槽标签：」前缀（载体/位置、时间、方法、约束等标签是通用词，
    参与命中必误判）→ 槽内按「，,、/（）」切短语 → 丢弃长度 <2、纯数字、
    全时窗哨兵短语（全时窗 = 时间维无信息量，不因其未命中而降级）。
    """
    out, seen = [], set()
    for slot in re.split(r"[；;]", str(text or "")):
        if "：" in slot:
            slot = slot.split("：", 1)[1]
        elif ":" in slot:
            slot = slot.split(":", 1)[1]
        for seg in re.split(r"[，,、/（）()]", slot):
            seg = seg.strip()
            if len(seg) < 2 or seg.isdigit():
                continue
            if "全时窗" in seg or "任意时刻" in seg:
                continue
            if seg not in seen:
                seen.add(seg)
                out.append(seg)
    return out