# -*- coding: utf-8 -*-
"""正文裸 id 引用 → reference 边（写入侧低摩擦建链，R-L1b，2026-09-17）。

【为什么不是 `[[双链]]` 语法】（第 4 条取证——全库普查，非相似度判断）
zcode 报告《Obsidian 是什么》建议照搬 Obsidian 的 `[[node_id|显示名]]` 语法。
全库 11,883 节点实测：正文含 `[[...]]` 的仅 **8 节点 / 45 次**，且逐条核对
**全部是误匹配**——`[[tool.uv.index]]`（TOML 数组表）、
`[[ "opencode-deja", {...} ]]`（JSON/JS 嵌套数组）、代码块数组。
**真实双链用例 = 0**；即 `[[...]]` 不是本库写侧的自然语法，且与正文里
已大量存在的 TOML/JSON 语法**物理冲突**：照搬将产出 0 条真边 + N 条垃圾边。
（判定单：R-L1a = REJECT，依据=条件证据「正文会自然写 [[..]]」不成立。）

而**真实存在的自然写法是裸 id**：全库 64 节点 / 169 处正文引用了其他节点 id，
其中 62 节点「已引用但 edges 为空」——本模块即以此为靶区，零语法成本。

【落点选择】（第 4 条取证）
`cg.add` 是**全量重建 fm**（mdcg.py `"edges": list(edges or [])`），故经
`a["edges"]` 注入会在**覆写既有节点时清空其原有边**（破坏性副作用）。
本模块因此只「解析」不「注入」；落盘由 after 钩子经 `append_edge`——边域
窄原语、按 (target, relation_type) 幂等、不动正文与本体字段——完成。

【边类型语义】
`reference` 与 `similar`/`causal` 都不同：正文提及 ≠ 语义相似 ≠ 因果依赖。
故在 `chain.EDGE_WEIGHTS` 单列一类、取弱权重 0.50；且**不入**
`CHAIN_TYPES_DEFAULT`（因果链遍历仍只走 causal/sequential/applies_to），
避免正文提及污染「前提→结论」条件序列。

【判据：通用形态 + 库内存在（双保险），不设前缀白名单】
初版用 8 前缀白名单（node/mem/concept/imgpart/doc/code/ev/gap）。
**2026-09-17 全库普查证伪**：真实库 11,883 个索引键的前缀域有 **48 个**——
doc 3788 / kp 2962 / code 2878 / node 1360 / mem 435 / rev 153 / note 135 /
imgpart 60 / vpipe 32 / arc / unr / swarm / bench6 / self / rej / anchor /
work / whitebox / arch / goal / …（另 40 个前缀）。白名单会**漏掉 kp_* 等
40 个前缀的全部引用**（判据面远小于真源面）。
故改为**通用形态**：`字母前缀_字母数字段`（段长 ≥3），
并以「**必须存在于库内已知 id 集合**」二次拦截——误匹配由第二道滤网兜住，
两道判据都不成立时不建边。形态边界按 **ASCII 字母数字下划线**判定
（不用 `\b`：其中文词义会让「id 紧邻汉字」整条漏抽，见 `ID_RE` 注释）。

【纪律】G8 常态化建链第 2 条：**建链失败不阻断写入**——after 钩子全兜异常。

【不适用条件】（负路由，实测边界）
- `gated=true`（主动遗忘闸）路径：该闸是**替代执行路径**，自己落盘并短路，
  `writepipe.execute` 在短路时直接 return（不跑 after 链）→ 该路径落盘的
  节点**不**自动建 reference 边。与 G8 `derived_from` 在 gated 路径下仍生效
  （`_gate_gated` 显式透传 derived_from）**不同**，属已知非对称边界。
- 引用**尚未入库**的 id：`extract_refs` 以库内已知 id 为白名单，未知 id
  不建边（否则产生「指向不存在节点」的幽灵边，检索侧 `_path_graph` 会追空）。
- **当前身份不可读的目标节点**：白名单口径与库读面一致（`_readable`，见
  `known_ids`）——「不可见即不存在」，读隔离区（`private`/`secret`）的节点
  不被建边。故链接面是**身份相关**的：同一段正文，高 clearance 身份建出的
  边多于低 clearance 身份。这是读隔离的正确投影（且避免把高密级节点 id
  的存在性经 `fm.edges` 泄漏给低 clearance 读者），不是缺陷。
  读隔离有**两个面**、判据必须叠加（20260917 取证补第二面）：①**密级面** =
  `known_ids` 经 `_readable` 看索引里的 `sensitivity` 字段（纯内存）；②**密钥面** =
  `live_targets` 经 `get` 实读——`private`/`secret` 正文是密文，解封需
  **(tenant, actor) 信封里的 DEK**，无 DEK 时 `_open_content` 返回 None。
  只有①时白名单会混入「密级够、密钥不够」的死目标（真实库实测 459 条：
  rev/note/node/imgpart/vpipe/kp/self 七前缀，secret clearance 下候选清单
  因此含 15 个死目标 / 16 条悬空候选）。两面叠加后建边才与 `get` 同口径。
- **源节点在审计留痕层（`layer="self"`）**：该层是灵枢自身运行留痕——
  `rev_<pid尾>_r<N>` 裁决记录节点由 `mdcos._write_review_record` 落盘，
  正文是**模板机械拼装**、必然含被裁决对象的 id。这是「记录指向记录对象」，
  不是记忆之间的语义引用；且每次裁决都会新生一个该层节点，逐条建边会让
  弱边随裁决次数线性增长、稀释检索面。
  判据取**层语义**（`SOURCE_EXCLUDE_LAYERS`）而非 id 前缀 `rev_`——与
  `mdcos.review_records()` 的 self 层口径一致，且不依赖命名约定。
  （20260917 取证：回填后仍残留 gap 的节点实测正是 `rev_*`。）
- **不合形态的脏键不作源、也不被识别为目标**：真实库索引里存在 11 个脏键
  （`None`——历史 `add` 未传 node_id 被字符串化落盘，磁盘上确有
  `knowledge/orphan/None.md`；3 个中文标题式键；`kp_GIL全局解_*` 等 6 个
  含中文的混合 id）。判据不因脏数据松弛：含中文/无下划线的键一律不建边。
  脏数据**源头**（`add` 的 node_id 未规范化）属另一问题，另案处理。
- 身份/授权：本模块不做权限判断——`append_edge` 经 `MdCGSecure` 库层照常
  受 `require_layer_write` 约束（拦截器改不了「谁能写」）。
"""
from __future__ import annotations

import re
import time

__all__ = ["RELATION", "ID_SHAPE", "ID_RE", "ID_SHAPE_RE", "SOURCE_EXCLUDE_LAYERS",
           "known_ids", "live_targets", "is_linkable_id", "is_linkable_source",
           "extract_refs", "make_edge", "before_hook", "after_hook"]

# 节点 id **通用形态**（不设前缀白名单，见模块 docstring 的普查依据）：
#   字母前缀 + `_` + 字母数字段（段长 ≥3）。
# 实例：mem_1789125080573 / concept_d8eee20f2f / doc_b56c18dbf164 /
#       kp_GIL_1787752832598 / node_meta_427035320_1787018623216 / rev_xxx_r1
# 边界用 **ASCII 字母数字下划线 lookaround**（不可用 `\b`）：Python `re` 的
# `\b` 按 Unicode 词义判定、中文属词字符，故 `见 mem_xxx的说明` 这类
# 「id 紧邻汉字」的常见写法会被 `\b` 判为无边界而**整体漏抽**（假阴性）。
ID_SHAPE = r"[A-Za-z][A-Za-z0-9]*_[0-9A-Za-z][0-9A-Za-z_]{2,}"
ID_RE = re.compile(r"(?<![0-9A-Za-z_])(" + ID_SHAPE + r")(?![0-9A-Za-z_])")
ID_SHAPE_RE = re.compile(r"^" + ID_SHAPE + r"$")

# 源节点排除层：self 层是灵枢**自身运行留痕**（`rev_*` 裁决记录节点，
# 见 `mdcos._write_review_record`），其正文引用是模板机械拼装的
# 「记录→记录对象」，不构成记忆之间的语义引用。取层语义而非 id 前缀。
SOURCE_EXCLUDE_LAYERS = ("self",)

RELATION = "reference"
# 解释：正文提及是**确定性文本事实**（不是推断），故 confidence=1.0；
# 弱语义由类型 base 承担（chain.EDGE_WEIGHTS["reference"] = 0.50）。
# 有效传播权重 = base × confidence = 0.50 × 1.0。
EDGE_CONFIDENCE = 1.0
VERIFIED = False          # 未经人工/证据验证——白箱诚实标记


# 生效条件：cg.index 的 "nodes" 取到条目且 cg._readable 可调用时，仅把 guard(条目) 为真的 id 纳入白名单（判定抛异常即跳过该条）；_readable 不可调用时直接返回 nodes 的全部键；cg.index 取值抛异常或 "nodes" 为假值回落空 dict 时返回空集。
def known_ids(cg):
    """库内**对当前身份可读**的节点 id 集合（白名单；读隔离一致性）。

    与 `md_cg/backfill.py::_readable_guard` 同口径：`MdCGSecure` 的读面
    （`get` / `_candidates` / `search_rrf`）一律「不可见即不存在」，链接面
    必须一致——否则会对当前身份不可读的节点建边，产出检索侧追空的悬空边。
    （20260917 取证：真实库 11885 键里 clearance=internal 仅 7212 可读、
    须 secret 才全读；候选目标 94 个中 21 个落在读隔离区。）

    判定为**纯内存**（索引条目带 sensitivity；缺该字段时 `_readable` 会按
    盘上真相回填并缓存，仅首次有盘读）。异常一律 fail-closed 回退空集。

    注意这是**密级面**过滤：「密级可读 ≠ 实读可得」（加密节点还需本身份的
    DEK）。密钥面由 `live_targets` 补——两者叠加才是完整的「不可见即不存在」。
    """
    try:
        nodes = cg.index.get("nodes") or {}
    except Exception:                                  # noqa: BLE001
        return set()
    guard = getattr(cg, "_readable", None)
    if not callable(guard):
        return set(nodes)               # 非安全库（MdCG）无读隔离概念
    out = set()
    for nid, e in nodes.items():
        try:
            if guard(e):
                out.add(nid)
        except Exception:                              # noqa: BLE001
            continue                    # fail-closed：判不了即不纳入白名单
    return out


# 生效条件：逐 tid∈ids，cache 非 None 且 tid 已在 cache 时用 cache[tid] 作判据，否则以 bool(cg.get(tid)) 为判据（cg.get 抛异常记 False）并在 cache 非 None 时回写 cache[tid]；判据为真才把 tid 追加进 out。
def live_targets(cg, ids, cache=None):
    """从 ids 中筛出**当前身份实读可得**的目标（读隔离的第二道：密钥面）。

    为什么不能只靠 `known_ids`：它经 `_readable` 只看索引里的密级字段，而
    `private`/`secret` 节点**正文是密文**，解封需 (tenant, actor) 信封里的
    DEK；无 DEK 时 `get` 经 `_open_content` 返回 None（并落 `read_locked` 审计）。
    （20260917 取证：真实库 11885 键里 459 条正是此类——文件在、frontmatter
    明文、正文密文、扫描身份无 DEK；`secret` clearance 下混入白名单，使候选
    清单产出 15 条指向死目标的悬空边。）

    cache —— 可选 dict，批量场景复用判定（同一 id 多次出现只读一次盘）。
    异常一律 fail-closed（判不了即不建边，与 `known_ids` 同纪律）。
    """
    out = []
    for tid in ids:
        if cache is not None and tid in cache:
            ok = cache[tid]
        else:
            try:
                ok = bool(cg.get(tid))
            except Exception:                              # noqa: BLE001
                ok = False
            if cache is not None:
                cache[tid] = ok
        if ok:
            out.append(tid)
    return out


# 生效条件：nid 是 str 且 ID_SHAPE_RE.match(nid) 命中时返回 True，否则返回 False。
def is_linkable_id(nid):
    """id 形态是否可作链接面端点（排除 `None`/中文标题键/含中文混合 id 等脏键）。"""
    return bool(isinstance(nid, str) and ID_SHAPE_RE.match(nid))


# 生效条件：is_linkable_id(nid) 为真且 (layer or "") 不属于 SOURCE_EXCLUDE_LAYERS 时返回 True，否则 False（layer 为假值时按空串判定）。
def is_linkable_source(nid, layer):
    """源节点是否可建 reference 边：形态合法 **且** 不在审计留痕层。"""
    return is_linkable_id(nid) and (layer or "") not in SOURCE_EXCLUDE_LAYERS


# 生效条件：text 为假值直接返回 []；否则对 text 中 ID_RE 的每个捕获组 tid，在 tid 不在 seen、不在 ex（exclude 为真时含 str(exclude)）且（known 为 None 或 tid in known）时按首次出现顺序加入 out 并去重。
def extract_refs(text, known=None, exclude=None):
    """抽取正文中指向节点 id 的裸引用。

    参数：
        text    —— 正文（不含 frontmatter）。
        known   —— 库内已知 id 集合；**传集合时启用白名单过滤**（钩子路径
                   必须传，防幽灵边与形态误匹配）；传 None 表示只按通用形态
                   判定（供离线盘点/回填预览使用）。
        exclude —— 需排除的 id（通常为节点自身 id：正文里写自己的 id 不是引用）。

    返回：去重**保序**的 id 列表（保序让边顺序稳定，落盘可复现）。
    """
    if not text:
        return []
    ex = {str(exclude)} if exclude else set()
    seen = set()
    out = []
    for m in ID_RE.finditer(text):
        tid = m.group(1)
        if tid in seen or tid in ex:
            continue
        if known is not None and tid not in known:
            continue
        seen.add(tid)
        out.append(tid)
    return out


# 生效条件：总是返回以 str(target) 为 target、常量 RELATION/EDGE_CONFIDENCE/VERIFIED 为关系与置信字段的 dict，created_at 在 now 非 None 时取 float(now)（now=0 亦取 0.0）、now 为 None 时取 time.time()。
def make_edge(target, now=None, source="auto:linkref"):
    """构造一条 reference 边（形态对齐旁路语料：target/relation_type/...）。"""
    return {
        "target": str(target),
        "relation_type": RELATION,
        "confidence": EDGE_CONFIDENCE,
        "verified": VERIFIED,
        "source": source,
        "created_at": float(now if now is not None else time.time()),
        "reason": "正文引用（写入侧自动解析）",
    }


# 生效条件：无入参，调用即返回闭包 _before 本身，本调用不做任何引用解析或 ctx 写入。
def before_hook():
    """before 拦截器工厂：解析正文引用 → 存 ctx（不落盘、永不短路）。

    写入方可用 `linkref=False` 显式关闭本次自动建链（opt-out）；
    写入 self 层（审计留痕）或非规范 id 时自动跳过。
    """
# 生效条件：ctx 中 a=ctx["a"] 或 {} 的 "linkref" 不为 False、nid=a["node_id"] 或 ctx["nid"] 经 is_linkable_source(nid, a["layer"]) 为真、且 a["content"] 为真时，用 known_ids(ctx["cg"]) 对 content 抽取引用（排除 nid），结果非空则写入 ctx["linkref_targets"]；各条件不满足即提前返回 None，函数始终返回 None。
    def _before(ctx):
        a = ctx.get("a") or {}
        if a.get("linkref") is False:
            return None
        nid = a.get("node_id") or ctx.get("nid")
        if not is_linkable_source(nid, a.get("layer")):
            return None
        content = a.get("content")
        if not content:
            return None
        refs = extract_refs(content, known=known_ids(ctx.get("cg")),
                            exclude=nid)
        if refs:
            ctx["linkref_targets"] = refs
        return None
    return _before


def after_hook():
    """after 拦截器工厂：落盘成功后经 append_edge 建 reference 边（幂等）。

    纪律（G8 第 2 条）：建链失败**不得**阻断写入——所有异常就地吞掉。
    这同时满足 writepipe 的「after 故障不吞」契约（钩子自身不抛即不触发）。
    """
# 生效条件：out 是 dict 且 out.get("committed") 为真、ctx["linkref_targets"] 非空、ctx["cg"] 非 None 且 nid（out["id"] 或 ctx["nid"]）为真时，对 live_targets(cg, targets) 返回的每个 tid 调用 cg.append_edge(nid, make_edge(tid, now=now))，append_edge 抛异常即跳过该条；否则提前返回，函数无返回语句。
    def _after(ctx, out):
        if not isinstance(out, dict) or not out.get("committed"):
            return
        targets = ctx.get("linkref_targets")
        if not targets:
            return
        cg = ctx.get("cg")
        nid = out.get("id") or ctx.get("nid")
        if cg is None or not nid:
            return
        now = time.time()
        # 落边前再经一遍**实读**校验（密钥面读隔离）：`before` 时的白名单只看
        # 索引密级，加密节点的 DEK 可得性只有实读才知道；此处与 `get` 同口径，
        # 避免产出指向死目标的悬空边（20260917 取证：459 条此类节点）。
        for tid in live_targets(cg, targets):
            try:
                cg.append_edge(nid, make_edge(tid, now=now))
            except Exception:                      # noqa: BLE001
                continue    # 建链降级为静默跳过：写入已成功，不回滚、不抛
    return _after