# -*- coding: utf-8 -*-
"""md_cg · MCP server（记忆操作系统对外接口）

把 MdCGOS（认知图 + 记忆 OS 七项能力）暴露为标准 MCP 服务：
  · 传输：stdio（逐行 JSON-RPC 2.0，UTF-8）
  · 协议：2024-11-05
  · 零第三方依赖（D-005）

启动：
    MDCG_ROOT=<认知图目录> MDCG_ACTOR=<调用方> python -m md_cg.mcp_server

DSH 侧配置（cordis.yml / MCP client）：
    command: python
    args: ["-m", "md_cg.mcp_server"]
    env: { MDCG_ROOT: "...", PYTHONPATH: ".../dsh-memory" }

工具面（默认 kernel 只暴露 2 个基元 cg/stg；MDCG_MCP_SURFACE=full 时
另有 29 个细粒度工具，供兼容/调试）：
  写：mdcg_remember（gated=true 走主动遗忘闸门）/ mdcg_rejected /
      mdcg_unresolved / mdcg_propose
  目标/近期：cg(op=goal) 目标槽 / cg(op=recent) 近期事件窗口
  读：mdcg_get / mdcg_search / mdcg_recall / mdcg_review_list /
      mdcg_review_records
  认知：mdcg_reflect / mdcg_verify / mdcg_flywheel / mdcg_mine_fix_pairs /
      mdcg_consistency（节点间冲突检测：check/history/stats/catalog）/
      mdcg_metacognition（独立元认知：report/trace/calibration/blindspots/
      trust/self_check/history/catalog）/
      mdcg_self_state（自我状态层：snapshot/refresh/bootstrap/relate/
      relations/index/dimensions/audit/history/summary/catalog）/
      mdcg_predict（生成式预测：routes/feedback/stats/catalog）/
      mdcg_causal（因果推理：path/gate/chain/explain/catalog）
  生命周期：mdcg_forget（override）/ mdcg_restore / mdcg_review_decide
  保护/遗忘：mdcg_protect（盘点/查询/标记/快照/历史）/
      mdcg_forgetting_history（三问四态留痕）
  身份识别：mdcg_identity（observe/anchor/trait/profile/positions/catalog）
  运维：mdcg_health / mdcg_whoami / mdcg_ingest / mdcg_watermarks /
      mdcg_service_info
"""
from __future__ import annotations

import json
import json
import os
import sys

SERVER_NAME = "mdcg-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


# --------------------------------------------------------------------------
# 工具定义
# --------------------------------------------------------------------------

def _s(_desc, **props):
    return {"type": "object", "properties": props, "required":
            [k for k, v in props.items() if v.get("_req")]}


def _p(t, desc, req=False):
    d = {"type": t, "description": desc}
    if req:
        d["_req"] = True
    return d


def _make_query_expand(exp):
    """把调用方（LLM/多智能体）提供的扩展词包装成 query_expand 注入函数。

    黑箱只在**查询时刻**：调用方给出 {term,weight}，索引侧仍是白箱词表匹配。
    返回的函数与 md_cg.mdcg.expand_query_terms_weighted 同构，并在 __source__ 标注 llm。
    """
    if not exp:
        return None
    from .mdcg import expand_query_terms_weighted

    def _expand(q, _exp=exp):
        out = expand_query_terms_weighted(q)
        for it in _exp:
            if isinstance(it, dict):
                term = str(it.get("term") or "").strip()
                try:
                    w = float(it.get("weight", 0.5))
                except (TypeError, ValueError):
                    w = 0.5
            else:
                term, w = str(it).strip(), 0.5
            if term:
                out[term] = max(out.get(term, 0.0), max(0.0, min(1.0, w)))
        out["__source__"] = "llm"
        return out

    return _expand


TOOLS = [
    {
        "name": "mdcg_remember",
        "description": "写入一条记忆节点（md 认知图）。content 建议含 CCG 5 要素注释"
                       "（# 功能名/# 生效条件/# 子功能/# 执行/# 验证方式/# 不适用条件）。"
                       "gated=true 时先经主动遗忘闸门（三问→四态：ACCEPT/MERGE/DROP/DEFER），"
                       "适用于写入情景层记忆时的筛选（未指定 layer 时默认 contextual）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id（省略则自动生成）"),
                          content=_p("string", "节点内容", True),
                          layer=_p("string", "层：anchor|structural|knowledge|contextual|self"),
                          role=_p("string", "角色：knowledge|user|assistant|tool-output|command|edit"
                                            "（兼作来源证据：user=外部惊奇，command/tool-output=内部确定性）"),
                          tags=_p("array", "标签"), importance=_p("number", "重要性 0-1"),
                          importance_hint=_p("number", "闸门的重要性提示（≥0.7 保护优先直接 ACCEPT）"),
                          gated=_p("boolean", "启用主动遗忘闸门（默认否；写情景层建议开）"),
                          override=_p("boolean", "覆盖受保护节点需显式 true"),
                          consistency=_p("boolean", "写入前节点间自动冲突检测（三级决策，默认 true）"),
                          on_conflict=_p("string", "冲突处置：reject（默认，抛错）|defer（不写）|record（记录放行）"),
                          condition_space=_p("object", "条件空间"),
                          verification_basis=_p("string", "验证基底"),
                          non_applicable_conditions=_p("array", "不适用条件")),
                          },
    {
        "name": "mdcg_recall",
        "description": "按 token 预算召回记忆包（RRF 多路融合，超大条目跳过而非停下）。"
                       "会话开始或重要工作前调用。可选启用第 5 路模糊召回（分级隶属度）"
                       "与第 6 路条件语义路（条件结构驱动），并注入调用方 LLM 的查询"
                       "扩展词（索引侧始终白箱）。",
        "inputSchema": _s("", query=_p("string", "描述当前任务的查询", True),
                          budget_tokens=_p("integer", "token 预算（默认 1200）"),
                          k=_p("integer", "候选上限"), context=_p("object", "当前情境条件空间"),
                          include_work=_p("boolean", "是否含工具输出/命令/编辑（默认否）"),
                          fuzzy=_p("boolean", "启用第 5 路模糊召回（分级隶属度，默认否）"),
                         semantic=_p("boolean", "启用第 6 路条件空间结构化匹配"
                                               "（白箱语义路：CCG 生效条件 + condition_space "
                                               "四槽，不适用条件命中即剔除；默认否）"),
                          expand=_p("array", "LLM 查询侧扩展词：[{term,weight}] 或 [\"词\"]；"
                                             "仅在查询时刻生效，索引侧仍白箱"),
                          goal=_p("string", "当前目标（第 5 篇第 3 章）：启用 goal 路给召回定向；"
                                            "省略则自动取活跃目标"),
                          goal_path=_p("boolean", "启用目标定向路（默认否；给 goal 即自动启用）"),
                          include_recent=_p("boolean", "是否附「近期事件」窗口（默认否）"),
                          recent_limit=_p("integer", "近期事件条数（默认 10）"),
                          fusion=_p("string", "融合模式：sum（经典 RRF，奖励多路共识）"
                                              "| max（取各路最高贡献，不奖励共识）。"
                                              "fuzzy=true 时缺省 max——实测 sum 会低估"
                                              "「只有模糊路捞到」的目标，self@1 −10.1%")),
    },
    {
        "name": "mdcg_search",
        "description": "精确检索（T0–T3 阶梯 + 四态资格判定）。返回 score/state/tier。",
        "inputSchema": _s("", query=_p("string", "查询", True), k=_p("integer", "条数"),
                          layer=_p("string", "限定层"), context=_p("object", "情境"),
                          roles=_p("array", "限定角色"), include_work=_p("boolean", "含工作角色")),
    },
    {
        "name": "mdcg_get",
        "description": "按 id 读取一个记忆节点（frontmatter + content）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True)),
    },
    {
        "name": "mdcg_reflect",
        "description": "反思单元：记录本次查询的信息差 D(t,C) 与二阶 d²D/dt²，写 _reflection.jsonl。",
        "inputSchema": _s("", query=_p("string", "查询", True), k=_p("integer", "取前 k 条"),
                          feedback=_p("string", "用户反馈（可选）")),
    },
    {
        "name": "mdcg_verify",
        "description": "验证单元：对节点做外部裁决 confirmed/weakened/falsified"
                       "（falsified 会移入 rejected/ 负记忆）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True),
                          evidence=_p("string", "证据", True),
                          verdict=_p("string", "confirmed|weakened|falsified", True)),
    },
    {
        "name": "mdcg_flywheel",
        "description": "知识飞轮：把一次误差（预期状态 vs 实际状态）转为 unresolved 条目，驱动补条件。",
        "inputSchema": _s("", error_report=_p("object", "错误报告 {query,expected_state,actual_state,missing}", True)),
    },
    {
        "name": "mdcg_mine_fix_pairs",
        "description": "从行为日志自动挖掘「错误→修复」对：产出可路由修复知识 + rejected 负记忆。",
        "inputSchema": _s("", events=_p("array", "事件列表 [{role,text}] 或 [{error,fix}]", True)),
    },
    {
        "name": "mdcg_rejected",
        "description": "写入负记忆（被证伪的假设），防重复踩坑；同内容幂等。",
        "inputSchema": _s("", hypothesis=_p("string", "假设", True), reason=_p("string", "否决原因", True),
                          verification_basis=_p("string", "验证基底"), tags=_p("array", "标签")),
    },
    {
        "name": "mdcg_unresolved",
        "description": "写入未解问题（驱动主动探索）。",
        "inputSchema": _s("", question=_p("string", "问题", True), known_clues=_p("string", "已知线索"),
                          goal=_p("string", "目标")),
    },
    {
        "name": "mdcg_propose",
        "description": "把一个候选记忆放入审核队列（海马体 inbox），等待 review_decide。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), content=_p("string", "内容", True),
                          layer=_p("string", "层"), tags=_p("array", "标签"),
                          condition_space=_p("object", "条件空间"),
                          verify=_p("object", "验收判据（内联声明，裁决阶段只读）")),
    },
    {
        "name": "mdcg_review_list",
        "description": "列出待审核候选；被红队打回待再审批的条目带 status=needs_reapproval。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_review_decide",
        "description": "审核裁决：accept / reject / edit / merge（merge 需 merge_into）。"
                       "redteam.verdict=reject 不落库，转 needs_reapproval，"
                       "修复后须带递增 round 的 pass 再审批；判据只读不可改。",
        "inputSchema": _s("", pid=_p("string", "提案 id", True),
                          decision=_p("string", "accept|reject|edit|merge", True),
                          edits=_p("object", "edit 时的覆盖字段"), merge_into=_p("string", "merge 目标节点 id"),
                          reason=_p("string", "裁决理由"),
                          redteam=_p("object", "红队裁决 {verdict:pass|reject, issues:[], round:n}"),
                          issues=_p("array", "问题清单（打回理由）")),
    },
    {
        "name": "mdcg_review_records",
        "description": "裁决记录审计：列出 md 审计节点（self 层，供其他来源审计）；"
                       "给 node_id 则复核该记录的 record_hash 与 "
                       "hippocampus/decisions.jsonl 是否一致。",
        "inputSchema": _s("", pid=_p("string", "只看某提案的记录"),
                          node_id=_p("string", "复核该审计节点 id")),
    },
    {
        "name": "mdcg_forget",
        "description": "软删除（tombstone）：节点移入 trash/ 并写入删除清单，可审计。"
                       "受保护节点（self/anchor 层、protected 标记、importance≥0.7）"
                       "不可遗忘，需显式 override=true（旧版本自动快照 + 留痕）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), reason=_p("string", "原因"),
                          override=_p("boolean", "受保护节点需显式 true 才可删除")),
    },
    {
        "name": "mdcg_protect",
        "description": "写保护（不可遗忘/不可覆盖）：action=stats 盘点 / check 查询某节点"
                       "保护状态 / mark 打保护标记（需 can_admin）/ snapshot 快照当前版本 / "
                       "history 列历史版本 / forgetting 读主动遗忘裁决留痕。",
        "inputSchema": _s("", action=_p("string", "stats|check|mark|snapshot|history|forgetting"),
                          node_id=_p("string", "check/mark/snapshot/history 的节点 id"),
                          reason=_p("string", "mark 的保护原因"),
                          limit=_p("integer", "forgetting 的最近条数（默认 100）")),
    },
    {
        "name": "mdcg_forgetting_history",
        "description": "主动遗忘裁决留痕：ACCEPT/MERGE/DROP/DEFER 四态及三问判据"
                       "（重复度/重要度/自信息代理），可审计「为什么没被记住」。",
        "inputSchema": _s("", limit=_p("integer", "最近条数（默认 100）")),
    },
    {
        "name": "mdcg_identity",
        "description": "身份特征识别（不止「用户画像」）：识别每个主体（智能体自身 self / "
                       "协作者 user / 扮演角色 role / 其他智能体 agent）的身份锚点、位置效应"
                       "（智能论 v3.4 五大单元：记录=全/反思=新/验证=稳/输出=通/维生=存）"
                       "与条件特征。action=observe 记行为证据（memory 接口）/ anchor 写身份"
                       "锚点（不可遗忘，role 不得进 self 层）/ trait 写条件特征（values 接口）"
                       "/ profile 取画像 / positions 看主体位置分布 / catalog 读位置效应表。",
        "inputSchema": _s("", action=_p("string", "observe|anchor|trait|profile|positions|"
                                                 "catalog|history"),
                          subject_id=_p("string", "主体：self:xx|user:xx|role:xx|agent:xx"),
                          subject_kind=_p("string", "主体类型：self|user|role|agent"),
                          content=_p("string", "observe/anchor 的文本"),
                          trait=_p("string", "trait 的特征文本"),
                          role=_p("string", "observe 的行为角色（兼作来源证据）"),
                          position=_p("string", "位置效应：record|reflect|verify|output|sustain"),
                          layer=_p("string", "observe 落层（默认 knowledge）"),
                          tags=_p("array", "标签"),
                          condition_space=_p("object", "条件空间（=触发时机）"),
                          importance=_p("number", "重要度 0-1"),
                          verification_basis=_p("string", "验证基底"),
                          evidence=_p("string", "证据来源标记"),
                          requested_layer=_p("string", "anchor 目标层（role≠self 时禁止 self）"),
                          override=_p("boolean", "覆盖受保护锚点需显式 true"),
                          limit=_p("integer", "positions/history 返回条数")),
    },
    {
        "name": "mdcg_consistency",
        "description": "节点间自动冲突检测（写入前校验，三级决策）："
                       "L0 情绪=信息差二阶变化（approaching/stable/avoiding，独立通道"
                       "不参与信任计算）→ L1 反思=条件论「反题」冲突检测"
                       "（自否定/违反纪律/条件互斥）→ L2 递归反思（受深度/节点数/"
                       "循环/信息增益门槛约束）。action=check 预检待写内容（不落盘）/ "
                       "history 判定留痕 / stats 汇总 / catalog 自描述。"
                       "冲突自动触发飞轮（误差→补条件→结构更新）。",
        "inputSchema": _s("", action=_p("string", "check|history|stats|catalog"),
                          content=_p("string", "check 的待写内容"),
                          layer=_p("string", "check：只与该层节点比对"),
                          condition_space=_p("object", "check：待写节点的条件空间"),
                          non_applicable_conditions=_p("array", "check：不适用条件"),
                          tags=_p("array", "check：标签"),
                          exclude=_p("string", "check：排除自身节点 id"),
                          depth=_p("integer", "check：递归反思深度上限"),
                          auto_flywheel=_p("boolean", "check：冲突时自动投递飞轮"),
                          limit=_p("integer", "check 扫描上限 / history 条数")),
    },
    {
        "name": "mdcg_metacognition",
        "description": "独立元认知（观察自身认知的二阶单元，不参与裁决）："
                       "情绪=信息差二阶变化 d²D/dt²（§十一）→ 轨迹面；"
                       "自信校准（期望正确率 vs 实际验证通过率，过度自信/过度保守）→ 校准面；"
                       "盲区地图（反复 BLINDSPOT 的查询邻域 + 未解问题，推论三）→ 盲区面；"
                       "P_gap/P_trust + 情感 d²T/dt²（§十）→ 信任面。"
                       "action=report 完整报告（含确定性建议）/ trace / calibration / "
                       "blindspots / trust / self_check（回答前自检：该直接答还是先补条件）"
                       " / history / catalog。只读留痕，不改事实层。",
        "inputSchema": _s("", action=_p("string", "report|trace|calibration|"
                                                "blindspots|trust|self_check|"
                                                "history|catalog"),
                          query=_p("string", "self_check 的待答查询"),
                          k=_p("integer", "self_check：相似历史条数"),
                          window=_p("integer", "轨迹/信任的滚动窗口"),
                          limit=_p("integer", "calibration 扫描上限 / "
                                              "blindspots、history 条数")),
    },
    {
        "name": "mdcg_self_state",
        "description": "自我状态层（薄自我 + 富索引）：self 层只放一张自我状态卡"
                       "（单例）+ 有向关系节点，登记八项自我信息的当前值与指针"
                       "（信息差 D/d1/d2、信任 P_gap/P_trust、情绪=d²D/dt²、"
                       "情感=d²T/dt²、短期记忆窗口摘要、重要性、身份锚点、关系度）；"
                       "具体任务/人物/会话/时间/信任的细节仍留在原层，按五维索引"
                       "（task/person/session/time/trust）连接过来，不搬运内容。"
                       "action=snapshot 读卡 / refresh 刷新（幂等 + 版本链） / "
                       "bootstrap 会话启动加载 / relate 写关系 / relations 列关系 / "
                       "index 按维度反查详情 / dimensions 看索引 / audit 一致性审计 / "
                       "history 留痕 / summary 一句话 / catalog 自描述。",
        "inputSchema": _s("", action=_p("string", "snapshot|refresh|bootstrap|relate|"
                                                "relations|index|dimensions|audit|"
                                                "history|summary|catalog"),
                          subject=_p("string", "主体（默认 self:lingshu）"),
                          window=_p("integer", "聚合窗口（反思/验证/近期条数）"),
                          importance=_p("number", "refresh：自我重要性权重"),
                          important_refs=_p("array", "refresh：显式重要节点 id"),
                          dimensions=_p("object", "refresh：五维索引标签，"
                                                  "{task,person,session,time,trust}"),
                          links=_p("array", "refresh：指向详情节点的边"),
                          force=_p("boolean", "refresh：强制写入（跳过幂等）"),
                          strict=_p("boolean", "refresh：版本链断裂时拒绝写入"),
                          frm=_p("string", "relate：源主体"),
                          to=_p("string", "relate：目标主体"),
                          relation_type=_p("string", "relate：collaborator|user|peer|"
                                                     "mentor|student|adversary|tool|other"),
                          strength=_p("number", "relate：强度 0-1"),
                          condition=_p("string", "relate：生效条件"),
                          note=_p("string", "relate：备注"),
                          reciprocal=_p("boolean", "relate：同时写反向关系"),
                          direction=_p("string", "relations：out|in|both"),
                          dim=_p("string", "index：task|person|session|time|trust"),
                          value=_p("string", "index：维度取值"),
                          with_content=_p("boolean", "index：是否附正文摘要"),
                          limit=_p("integer", "index/history 条数")),
    },
    {
        "name": "mdcg_predict",
        "description": "生成式预测（候选未来，非必然未来）：沿因果/时序边 + 语义邻近"
                       "（经 D-002 伪因果过滤门）生成局部路线，输出 uncertainty_bound / "
                       "extrapolation_validity（smooth|jump|unknown）/ T_pred 四维评分"
                       "（trend .40 / boundary .20 / verification .25 / balance .15）。"
                       "支持盲区驱动（blindspot_id 指向 unresolved 节点/盲区邻域；"
                       "声明「不可预测」则拒绝生成）与命中反馈（D-006 动态校准："
                       "命中 → 边置信度 +0.05，未命中 → 登记 rejected）。"
                       "action=routes|feedback|stats|catalog。",
        "inputSchema": _s("", action=_p("string", "routes|feedback|stats|catalog"),
                          start_id=_p("string", "routes：起点节点 id"),
                          blindspot_id=_p("string", "routes：盲区驱动（unresolved 节点 id "
                                                   "或盲区邻域键）"),
                          horizon=_p("integer", "routes：最大前推步数（默认 3，上限 16）"),
                          max_branches=_p("integer", "routes：每步最大分支"
                                                     "（默认 5，上限 32）"),
                          sort=_p("string", "routes：composite|trend|verification|"
                                            "boundary|balance"),
                          limit=_p("integer", "routes：返回条数；stats：最近留痕条数"),
                          semantic=_p("boolean", "routes：是否并入语义邻近候选"
                                                 "（默认是，须过伪因果过滤门）"),
                          predicted_node_id=_p("string", "feedback：被预测命中的节点 id"),
                          actual_node_id=_p("string", "feedback：实际走向节点 id"),
                          hit=_p("boolean", "feedback：是否命中"
                                            "（缺省按 predicted==actual）"),
                          note=_p("string", "feedback：备注")),
    },
    {
        "name": "mdcg_causal",
        "description": "因果推理：`causal` 边 = 条件依赖因果（A 是 B 成立的条件），"
                       "链 = 条件序列。action=path 判断 A 能否沿因果/时序边到达 B"
                       "（可达性，伪因果防护的完整语义）/ gate 跑 D-002 伪因果过滤门"
                       "（语义邻近须能说清关系才准入）/ chain 沿因果链展开（每跳带"
                       "条件与权重）/ explain 人类可读链式解释 / catalog 自描述。",
        "inputSchema": _s("", action=_p("string", "path|gate|chain|explain|catalog"),
                          a=_p("string", "path/gate：源节点 id"),
                          b=_p("string", "path/gate：目标节点 id"),
                          node_id=_p("string", "chain/explain：起点节点 id"),
                          max_depth=_p("integer", "path/chain：最大跳数"),
                          relation_types=_p("array", "chain：限定边类型，"
                                                     "默认 ['causal']"),
                          direction=_p("string", "chain：out|in"),
                          sort=_p("string", "chain：strength|length")),
    },
    {
        "name": "mdcg_evolution",
        "description": "演化账本（md 载体 `_evolution/ledger.md`）：每一次修改 = 对一条"
                       "缺失条件的补充；账本正文是人类可读的**认知规律 + 状态**"
                       "（confidence/layer/importance/负条件/验证基底），不记实现细节"
                       "（实现属于 git）。action=record 追加 / entries 列表 / show 单条 / "
                       "history 某节点演化史 / patterns 按缺失条件维度聚类出规律 / "
                       "summary 一句话 / rollback 撤回某条演化的状态（dry_run 可预演；"
                       "撤销本身也记一条条目，不可静默）/ catalog 自描述。",
        "inputSchema": _s("", action=_p("string", "record|entries|show|history|"
                                                "patterns|summary|rollback|catalog"),
                          node_id=_p("string", "绑定节点 id"),
                          rule=_p("string", "record：规律（必填，一句话认知规律）"),
                          missing=_p("string", "record：补的是哪一维缺失条件"),
                          change=_p("string", "record：这次具体改了什么"),
                          kind=_p("string", "record：condition_gap|layer_shift|general"),
                          evidence=_p("string", "record：触发本次演化的验证依据"),
                          source=_p("string", "record：consolidate|verify|manual"),
                          entry_id=_p("string", "show/rollback：条目 id"),
                          note=_p("string", "rollback：备注（覆盖默认规律）"),
                          dry_run=_p("boolean", "rollback：只预演不落盘"),
                          limit=_p("integer", "entries/history/patterns 条数")),
    },
    {
        "name": "mdcg_restore",
        "description": "恢复被 forget 的节点；若在删除清单中且未 force 则拒绝（恢复时删除检查）。",
        "inputSchema": _s("", node_id=_p("string", "节点 id", True), force=_p("boolean", "强制恢复")),
    },
    {
        "name": "mdcg_health",
        "description": "健康度：分桶健康 + CCG 完整度 + 验证基底覆盖率 + OS 指标（审核/墓碑/审计）。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_whoami",
        "description": "身份与权限：tenant / actor / clearance / 可见节点数 / 可读密级列表。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_ingest",
        "description": "设备驱动：从会话文件增量摄取事件（自动 fix-pair 挖掘 + watermark 去重）。"
                       "source=auto 时自动发现本机 DSH 会话。",
        "inputSchema": _s("", source=_p("string", "会话文件路径，或 'auto' 自动发现 DSH 会话"),
                          max_events=_p("integer", "单次最多摄取事件数"),
                          mine_fix_pairs=_p("boolean", "是否自动挖掘错误→修复对（默认是）"),
                          dry_run=_p("boolean", "只统计不写入")),
    },
    {
        "name": "mdcg_watermarks",
        "description": "各事件源的摄取水位（增量摄取状态，可审计）。",
        "inputSchema": _s(""),
    },
    {
        "name": "mdcg_whitebox",
        "description": "显式调用白箱能力库（AEIS，已下线为本地库）并验证其能力。"
                       "action=ask 问白箱（wisdom_chat）；action=remember 让白箱编码一条知识；"
                       "action=verify_encoding 验证「编码能力」（记住口令→追问命中）；"
                       "action=verify_existing 验证「已有知识回答能力」（route=self 且非空）；"
                       "action=ping 连通性探测；action=report 汇总验证留痕。"
                       "验证结论写回认知图 self 层（tags 含 whitebox:verify）。",
        "inputSchema": _s("", action=_p("string", "ask|remember|verify_encoding|"
                                                "verify_existing|ping|report", True),
                          question=_p("string", "ask/verify 的问题"),
                          message=_p("string", "ask：问题（question 的别名）"),
                          content=_p("string", "remember：待编码内容"),
                          importance=_p("number", "remember：重要性 0-1"),
                          tags=_p("array", "remember：标签"),
                          session_id=_p("string", "会话 id"),
                          marker=_p("string", "verify_encoding：唯一口令标记"),
                          fact=_p("string", "verify_encoding：待编码事实"),
                          questions=_p("array", "verify_existing：探针问题列表"),
                          limit=_p("integer", "report：返回条数")),
    },
    {
        "name": "mdcg_service_info",
        "description": "服务信息（信任透明度）：身份/版本/根目录/节点统计/工具数/权限。",
        "inputSchema": _s(""),
    },
]


# --------------------------------------------------------------------------
# 基元接口（kernel 暴露面）
#
# 架构决定（2026-09-09）：对外只暴露 2 个认知基元，其余细粒度工具下沉为
# 本地函数（MDCG_MCP_SURFACE=full 时仍可见，供兼容与调试）。
# 认知图只给「知识与建议能力名」，不执行——执行权归调用方。
# --------------------------------------------------------------------------

KERNEL_TOOLS = [
    {
        "name": "cg",
        "description": "认知图接口（唯一入口）。op=route：按情境条件路由，返回相关知识 + "
                       "建议能力名（不执行，由调用方决定）；op=read：召回/检索/按 id 取；"
                       "op=write：写入前按 content_kind 审核（ACCEPT 落盘 / REJECT 进负记忆 / "
                       "DEFER 进审核队列）+ 节点间冲突检测（三级决策：情绪→反思→递归反思；"
                       "consistency=false 可关，on_conflict=reject|defer|record）；"
                       "gated=true 时再经主动遗忘闸门三问→四态，"
                       "未指定 layer 时默认 contextual）；"
                       "op=verify：外部裁决回填；op=review：审核队列；"
                       "op=protect：写保护盘点/查询/标记/快照/历史；"
                       "op=forget：软删除/恢复（受保护节点需 override）；"
                       "op=goal：目标槽（第 5 篇七件套之「目标」，"
                       "action=add|list|status；目标不进召回，只给 read 定向）；"
                       "op=recent：近期事件窗口（七件套之「近期事件」，"
                       "action=add|list|clear，滚动保留最近 N 条）；"
                       "op=identity：身份特征识别（智能论 v3.4 位置效应 + 扮演论"
                       "三接口 memory/anchor/values，不止「用户画像」）；"
                       "op=consistency：节点间自动冲突检测（三级决策：情绪→反思→"
                       "递归反思，冲突自动触发飞轮；不能与已有条件冲突/不能违反纪律）；"
                       "op=metacognition：独立元认知（观察自身认知的二阶单元，不参与裁决；"
                       "action=report|trace|calibration|blindspots|trust|self_check|"
                       "history|catalog）；"
                       "op=self_state：自我状态层（薄自我+富索引：状态卡单例 + 关系节点，"
                       "八项自我信息只存当前值与指针，具体任务/人物/会话/时间/信任由认知图"
                       "按五维索引连接；action=snapshot|refresh|bootstrap|relate|relations|"
                       "index|dimensions|audit|history|summary|catalog）；"
                       "op=info：身份+健康+审核体系自描述；"
                       "op=sustain：持续性自维持（常驻/心跳/自愈/会话续接；"
                       "action=status|beat|peers|diagnose|heal|start|stop|resume|"
                       "note|catalog）；"
                       "op=scrub：记忆自净（抽查/联想/去污染/校准偏差；"
                       "action=sample|associate|audit|decontaminate|calibrate|"
                       "sweep|history|summary|catalog）；"
                       "op=predict：生成式预测（候选未来，非必然未来；沿因果/时序边 + "
                       "语义邻近经 D-002 伪因果过滤门生成局部路线，输出 uncertainty_bound / "
                       "extrapolation_validity / T_pred 四维评分；支持盲区驱动与命中反馈 "
                       "action=routes|feedback|stats|catalog）；"
                       "op=causal：因果推理（causal 边 = 条件依赖因果；action=path 可达性 / "
                       "gate 伪因果过滤门 / chain 因果链 / explain 解释 / catalog）；"
                       "op=evolution：演化账本（md 载体 `_evolution/ledger.md`，"
                       "每一次修改 = 对一条缺失条件的补充，记录认知规律与状态而非实现；"
                       "action=record|entries|show|history|patterns|summary|rollback|catalog，"
                       "rollback 撤回某条演化的状态且撤销本身也留痕）；"
                       "op=index_code：按目录（大域）索引代码，只存注释/接口，"
                       "code_ref 指回源文件，不复制完整代码（后缀按提取器注册表："
                       ".py 走精确 AST、.ts/.js 为弱提取器；返回 truncated 截断状态"
                       "与 skipped_suffixes 覆盖缺口，不再静默不完整）；"
                       "op=ref：按 code_ref 回读源区间（需 node_id 或 ref 对象，"
                       "root 可覆盖；返回 text 与 hash_match，hash_match=False "
                       "即源已漂移、索引位置不再可信）；"
                       "op=whitebox：显式调用白箱能力库（AEIS 已下线为本地库）并验证其"
                       "编码/已有知识回答能力（action=ask|remember|verify_encoding|"
                       "verify_existing|ping|report；结论写回 self 层留痕）；"
                       "op=theory：协议版本层（action=check|show|declare|catalog）；"
                       "op=link：蜂群互联层（对端信任 P_trust + 跨节点证据存储；"
                       "action=ls|show|handshake|observe|promote|degrade|isolate|"
                       "withdraw|decay|policy|card|publish|peers|evidence|export|"
                       "import|catalog）。",
        "inputSchema": _s("",
            op=_p("string", "route|read|write|verify|review|protect|identity|"
                            "consistency|metacognition|self_state|evolution|sustain|"
                            "scrub|predict|causal|"
                            "forget|goal|recent|info|index_code|ref|whitebox|"
                            "theory|link", True),
            intent=_p("string", "route 的查询意图"), query=_p("string", "read 的查询"),
            goal=_p("string", "goal op 的目标文本；read 的定向目标（缺省用活跃目标）"),
            goal_status=_p("string", "goal op：active|done|dropped"),
            priority=_p("number", "goal op：优先级 0-1（兼作定向偏置依据）"),
            deadline=_p("string", "goal op：截止时间（仅排序用，不做硬约束）"),
            conditions=_p("string", "goal op：生效条件"),
            action_hint=_p("string", "goal op：执行说明（写入 CCG 的「执行」栏）"),
            text=_p("string", "recent op 的事件文本"),
            role=_p("string", "recent op 的事件角色：user|assistant|tool-output|command；"
                              "write 时作为来源证据（user=外部惊奇）"),
            meta=_p("object", "recent op：附加元数据"),
            window=_p("integer", "recent op：滚动窗口大小（默认 200）"),
            include_recent=_p("boolean", "read：是否附近期事件窗口（默认否）"),
            limit=_p("integer", "goal/recent 的返回条数；read 的近期事件条数"),
            node_id=_p("string", "节点 id"),
            content=_p("string", "write 的内容（建议含 CCG 5 要素注释）"),
            content_kind=_p("string", "write 的内容类型：code|image_desc|text|permission|work_done|work_wip"),
            layer=_p("string", "层：anchor|structural|knowledge|contextual|self"),
            tags=_p("array", "标签（cap:xxx 会作为 route 的建议能力名）"),
            importance=_p("number", "重要性 0-1"),
            importance_hint=_p("number", "write gated=true 时的重要性提示"
                                        "（≥0.7 触发保护优先，直接 ACCEPT）"),
            gated=_p("boolean", "write 时启用主动遗忘闸门（三问→四态；默认否）"),
            consistency=_p("boolean", "write：写入前做节点间冲突检测"
                                      "（三级决策：情绪→反思→递归反思；默认开）"),
            on_conflict=_p("string", "write：冲突处置 reject|defer|record（默认 defer）"),
            override=_p("boolean", "覆盖/删除受保护节点需显式 override=true"),
            subject_id=_p("string", "identity 的主体：self:xx|user:xx|role:xx|agent:xx"),
            subject_kind=_p("string", "identity 主体类型：self|user|role|agent"),
            trait=_p("string", "identity action=trait 的特征文本"),
            position=_p("string", "identity：位置效应 record|reflect|verify|output|sustain"),
            requested_layer=_p("string", "identity anchor 目标层（role≠self 时禁止 self）"),
            auto_flywheel=_p("boolean", "consistency：冲突时自动投递飞轮（默认否）"),
            exclude=_p("string", "consistency：排除自身节点 id"),
            depth=_p("integer", "consistency：递归反思深度上限"),
            condition_space=_p("object", "条件空间"),
            verification_basis=_p("string", "验证基底"),
            non_applicable_conditions=_p("array", "不适用条件"),
            context=_p("object", "当前情境"),
            k=_p("integer", "返回条数"), budget_tokens=_p("integer", "read 的 token 预算"),
            evidence=_p("string", "verify 的证据"),
            verdict=_p("string", "verify 裁决：confirmed|weakened|falsified"),
            question=_p("string", "whitebox：ask/verify 的问题"),
            message=_p("string", "whitebox ask：问题（question 的别名）"),
            session_id=_p("string", "whitebox：会话 id（默认 md_cg-whitebox-verify）"),
            marker=_p("string", "whitebox verify_encoding：唯一口令标记（缺省自动生成）"),
            fact=_p("string", "whitebox verify_encoding：待编码事实"),
            questions=_p("array", "whitebox verify_existing：探针问题列表"),
            action=_p("string", "review: list|decide|rounds；forget: forget|restore；"
                                "protect: stats|check|mark|snapshot|history|forgetting；"
                                "identity: observe|anchor|trait|profile|positions|catalog；"
                                "consistency: check|history|stats|catalog；"
                                "goal: add|list|status；recent: add|list|clear；"
                                "sustain: status|beat|peers|diagnose|heal|"
                                "start|stop|resume|note|catalog；"
                                "scrub: sample|associate|audit|decontaminate|"
                                "calibrate|sweep|history|summary|catalog；"
                                "evolution: record|entries|show|history|patterns|"
                                "summary|rollback|catalog；"
                                "link: ls|show|handshake|observe|promote|degrade|"
                                "isolate|withdraw|decay|policy|card|publish|peers|"
                                "evidence|export|import|catalog"),
            pid=_p("string", "review decide 的提案 id"),
            decision=_p("string", "review 裁决：accept|reject|edit|merge"),
            edits=_p("object", "review edit 的覆盖字段（不可含 verify）"),
            merge_into=_p("string", "review merge 的目标节点 id"),
            redteam=_p("object", "红队裁决 {verdict:pass|reject, issues:[], round:n}"),
            issues=_p("array", "问题清单（红队打回理由）"),
            reason=_p("string", "原因"), force=_p("boolean", "restore 强制"),
            path=_p("string", "index_code 的目录（大域）；link import 的证据包文件"),
            patterns=_p("array", "index_code 的文件后缀，默认取提取器注册表"
                                 "（.py/.ts/.tsx/.js/.mjs/.cjs）"),
            max_files=_p("integer", "index_code 最多扫描文件数（被截断时返回里会"
                                    "显式给 truncated，不再静默不完整）"),
            ref=_p("object", "ref op：直接给 code_ref 对象（与 node_id 二选一）"),
            root=_p("string", "ref op：覆盖 ref 里记录的 root（索引结果的跨机器搬迁）"),
            name=_p("string", "sustain：心跳名（默认 md_cg）"),
            session=_p("string", "sustain：会话 id（resume/note 用）"),
            ts=_p("number", "sustain note：事件时间戳"),
            seq=_p("integer", "sustain note：事件序号"),
            task_running=_p("boolean", "sustain：任务执行中（心跳阈值放宽）"),
            beat_interval=_p("number", "sustain start：心跳间隔秒（默认 600）"),
            heal_interval=_p("number", "sustain start：巡检间隔秒（默认 300）"),
            auto_heal=_p("boolean", "sustain start：巡检异常时自动修复（默认是）"),
            scrub_interval=_p("number", "sustain start：自净间隔秒（默认 3600）"),
            auto_scrub=_p("boolean", "sustain start：自净执行去污染（默认否，只巡检）"),
            dry_run=_p("boolean", "sustain heal / scrub：只列动作不落盘"),
            ids=_p("array", "scrub：节点 id 列表（缺省全库）"),
            kinds=_p("string", "scrub：限定污染类型，逗号分隔"),
            strategy=_p("string", "scrub sample：stratified|risk|random"),
            seed=_p("integer", "scrub sample：抽样种子（同 seed 同样本）"),
            min_severity=_p("string", "scrub：最低严重度 info|low|medium|high"),
            apply=_p("boolean", "scrub calibrate：写回偏置（默认只给建议）"),
            lexical=_p("boolean", "scrub associate：是否用词法近邻（默认是）"),
            start_id=_p("string", "predict：起点节点 id（缺省取最高重要度节点）"),
            blindspot_id=_p("string", "predict：盲区驱动（unresolved 节点 id / "
                                     "盲区邻域键）；声明不可预测则拒绝生成"),
            horizon=_p("integer", "predict：最大前推步数（默认 3，上限 16）"),
            max_branches=_p("integer", "predict：每步最大分支（默认 5，上限 32）"),
            semantic=_p("boolean", "predict：是否并入语义邻近候选（默认是，"
                                   "须过 D-002 伪因果过滤门）"),
            a=_p("string", "causal path/gate：源节点 id"),
            b=_p("string", "causal path/gate：目标节点 id"),
            relation_types=_p("array", "causal chain：限定边类型，默认 ['causal']"),
            direction=_p("string", "causal chain：out|in"),
            sort=_p("string", "predict：composite|trend|verification|boundary|balance；"
                              "causal chain：strength|length"),
            predicted_node_id=_p("string", "predict feedback：被预测节点 id"),
            actual_node_id=_p("string", "predict feedback：实际走向节点 id"),
            hit=_p("boolean", "predict feedback：是否命中（缺省按 predicted==actual）"),
            rule=_p("string", "evolution record：规律（必填，一句话认知规律）"),
            missing=_p("string", "evolution record：补的是哪一维缺失条件"),
            change=_p("string", "evolution record：这次具体改了什么"),
            kind=_p("string", "evolution：condition_gap|layer_shift|general"),
            entry_id=_p("string", "evolution show/rollback：条目 id"),
            source=_p("string", "evolution record：来源 consolidate|verify|manual；"
                                "link evidence：按来源节点过滤"),
            peer=_p("string", "link：对端节点 id（如 agent:node-x）"),
            subsystem=_p("string", "link：子系统名（缺省 swarm）"),
            position_map=_p("object", "link handshake：对端位置映射 {位置:权重}"),
            peer_theory=_p("object", "link handshake：对端版本声明"),
            peer_version=_p("string", "link handshake：对端版本（peer_theory 简写）"),
            declared_charter=_p("boolean", "link handshake：对端是否声明宪章（默认是）"),
            peer_signature=_p("string", "link handshake/observe：对端签名"),
            negative=_p("boolean", "link observe：是否反例（默认否）"),
            set=_p("object", "link policy：设置子系统签名策略"),
            signers_file=_p("string", "link：签名策略文件（缺省 ~/.mdcg/_signers.json）"),
            swarm=_p("string", "link：跨节点共享目录（缺省 ~/.mdcg/swarm）"),
            subject=_p("string", "link evidence：按主体过滤（如 agent:node-x）"),
            subjects=_p("array", "link export：限定导出的主体列表"),
            out=_p("string", "link export：证据包输出路径"),
            pack=_p("object", "link import：内联证据包（与 path 二选一）")),
    },
    {
        "name": "stg",
        "description": "语义时空图接口：精确得到信息的时间/空间关系。"
                       "op=relation：两节点时空关系（Allen 时间 6 态 + RCC 空间 7 态）；"
                       "op=timeline：按时间排序；op=anchors：落在时间窗/空间范围的节点；"
                       "op=consistency：时空字段自洽性检查。",
        "inputSchema": _s("",
            op=_p("string", "relation|timeline|anchors|consistency", True),
            a=_p("string", "relation 的节点 a"), b=_p("string", "relation 的节点 b"),
            time_window=_p("array", "anchors 的时间窗 [t1,t2]"),
            bbox=_p("array", "anchors 的包围盒 [x1,y1,x2,y2]"),
            layer=_p("string", "限定层"), limit=_p("integer", "返回条数"),
            desc=_p("boolean", "timeline 是否倒序（默认是）")),
    },
]

ALL_TOOLS = KERNEL_TOOLS + TOOLS
SURFACE = os.environ.get("MDCG_MCP_SURFACE", "kernel").strip().lower()


def tools_for_surface():
    """kernel：只暴露 2 个基元；full：2 个基元 + 29 个细粒度工具（兼容/调试）。"""
    return ALL_TOOLS if SURFACE == "full" else KERNEL_TOOLS


# --------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------

def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _pick_source(path):
    """按内容嗅探源类型：DSH 会话格式 vs 通用 JSONL。"""
    from .sources import DSHSessionSource, JsonlSource
    if path.endswith(".zstd"):
        return DSHSessionSource(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                if o.get("type") == "session" or ("type" in o and "seq" in o
                                                  and "data" in o):
                    return DSHSessionSource(path)
                return JsonlSource(path)
    except (ValueError, OSError):
        pass
    return JsonlSource(path)


def _node_view(node):
    if not node:
        return None
    return {"id": node.get("id"), "path": node.get("path"),
            "frontmatter": node.get("frontmatter"), "content": node.get("content")}


# --------------------------------------------------------------------------
# 基元实现
# --------------------------------------------------------------------------

def _protect_call(cg, a):
    """写保护 / 遗忘留痕的统一入口（cg op=protect 与 mdcg_protect 共用）。"""
    from . import protect
    act = (a.get("action") or "stats").strip().lower()
    nid = a.get("node_id") or ""
    if act == "stats":
        return cg.protect_stats()
    if act in ("forgetting", "forgetting_history"):
        return {"records": cg.forgetting_history(limit=int(a.get("limit") or 100))}
    if act == "check":
        prot, why = protect.is_protected(cg, nid)
        imm, iwhy = protect.is_immutable(cg, nid)
        return {"node_id": nid, "exists": nid in (cg.index.get("nodes") or {}),
                "protected": prot, "reason": why,
                "immutable": imm, "immutable_reason": iwhy}
    if act == "history":
        return {"node_id": nid, "versions": protect.history(cg, nid)}
    if act == "snapshot":
        return {"node_id": nid, "snapshot": protect.snapshot(cg, nid)}
    if act in ("mark", "protect"):
        principal = getattr(cg, "principal", None)
        if principal is not None:
            principal.require_admin("protect_mark")
        return protect.mark(cg, nid, a.get("reason") or "显式保护标记")
    raise ValueError(f"protect 未知 action：{act}")


def _identity_call(cg, a):
    """身份特征识别统一入口（cg op=identity 与 mdcg_identity 共用）。

    理论：智能论 v3.4 位置效应（五大单元）+ 扮演论三接口。
    """
    from . import identity
    act = (a.get("action") or "profile").strip().lower()
    sid = a.get("subject_id") or ""
    if act == "catalog":
        return identity.catalog()
    if act == "positions":
        return {"positions": cg.identity_positions(limit=int(a.get("limit") or 0))}
    if act == "profile":
        if not sid:
            return {"subjects": cg.identity_positions(limit=0),
                    "hint": "指定 subject_id 可获取完整画像（锚点+位置+特征）"}
        return cg.identity_profile(sid)
    if act == "observe":
        return cg.identity_observe(
            sid, a.get("content") or a.get("text") or "",
            kind=a.get("subject_kind"), role=a.get("role"),
            layer=a.get("layer"), tags=a.get("tags"),
            condition_space=a.get("condition_space"),
            importance=float(a.get("importance", 0.5)),
            verification_basis=a.get("verification_basis"),
            evidence=a.get("evidence"), override=bool(a.get("override")))
    if act == "trait":
        return cg.identity_trait(
            sid, a.get("trait") or a.get("content") or "",
            condition_space=a.get("condition_space"),
            importance=float(a.get("importance", 0.6)),
            position=a.get("position"), kind=a.get("subject_kind"),
            verification_basis=a.get("verification_basis") or "data",
            override=bool(a.get("override")))
    if act == "anchor":
        principal = getattr(cg, "principal", None)
        if principal is not None:
            principal.require_admin("identity_anchor")
        return cg.identity_anchor(
            sid, a.get("content") or a.get("text") or "",
            kind=a.get("subject_kind"),
            condition_space=a.get("condition_space"),
            importance=float(a.get("importance", 0.9)),
            override=bool(a.get("override")),
            requested_layer=a.get("requested_layer"))
    if act == "history":
        return {"records": cg.identity_history(limit=int(a.get("limit") or 100))}
    raise ValueError(f"identity 未知 action：{act}")


def _consistency_call(cg, a):
    """节点间自动冲突检测统一入口（cg op=consistency 与 mdcg_consistency 共用）。

    理论：智能论 §十一（情绪=信息差二阶变化，独立不参与信任）、
    条件论「反题」、:273（递归受深度/节点/循环/增益门槛约束）、
    知识飞轮（误差→补条件→结构更新）。
    """
    from . import consistency
    act = (a.get("action") or "check").strip().lower()
    if act == "check":
        depth = a.get("depth")
        return cg.check_consistency(
            a.get("content") or a.get("text") or "",
            layer=a.get("layer"), condition_space=a.get("condition_space"),
            non_applicable_conditions=a.get("non_applicable_conditions"),
            tags=a.get("tags"), exclude=a.get("exclude"),
            limit=int(a.get("limit") or consistency.MAX_SCAN),
            depth=int(depth) if depth is not None else consistency.MAX_DEPTH,
            auto_flywheel=bool(a.get("auto_flywheel")))
    if act == "history":
        return {"records": cg.consistency_history(limit=int(a.get("limit") or 100))}
    if act == "stats":
        return cg.consistency_stats()
    if act == "catalog":
        return consistency.catalog()
    raise ValueError(f"consistency 未知 action：{act}")


def _metacognition_call(cg, a):
    """独立元认知统一入口（cg op=metacognition 与 mdcg_metacognition 共用）。

    理论：智能论 §十一（情绪=d²D/dt²）、§十三（五大单元外部观察者）、
    推论三「局部不可知」（盲区即知识）、§十（P_trust / P_gap）。
    独立性：只读留痕，不写 confidence / 资格 / 召回打分。
    """
    act = (a.get("action") or "report").strip().lower()
    window = int(a.get("window") or 50)
    if act == "report":
        return cg.metacognition_report(window=window)
    if act == "trace":
        return cg.metacognition_trace(window=window)
    if act == "calibration":
        return cg.metacognition_calibration(
            max_scan=int(a.get("limit") or 2000))
    if act == "blindspots":
        return cg.metacognition_blindspots(
            limit=int(a.get("limit") or 20), window=window)
    if act == "trust":
        return cg.metacognition_trust(window=window)
    if act == "self_check":
        return cg.self_check(a.get("query") or a.get("text") or "",
                             k=int(a.get("k") or 5))
    if act == "history":
        return cg.metacognition_history(limit=int(a.get("limit") or 100))
    if act == "catalog":
        from . import metacognition
        return metacognition.catalog()
    raise ValueError(f"metacognition 未知 action：{act}")


def _self_state_call(cg, a):
    """自我状态层统一入口（cg op=self_state 与 mdcg_self_state 共用）。

    薄自我：self 层只放状态卡（单例）+ 关系节点，登记八项自我信息的当前值
    与指针；具体任务/人物/会话/时间/信任的细节留在原层，由认知图按五维
    索引连接。一致性由 audit 重算校验（不依赖人的判断）。
    """
    from . import self_state
    act = (a.get("action") or "snapshot").strip().lower()
    subject = a.get("subject") or self_state.DEFAULT_SUBJECT
    if act in ("snapshot", "read", "get"):
        return {"state": self_state.snapshot(cg, subject)}
    if act == "refresh":
        return self_state.refresh(
            cg, subject, window=int(a.get("window") or self_state.RECENT_WINDOW),
            importance=a.get("importance"),
            important_refs=a.get("important_refs"),
            dimensions=a.get("dimensions"), links=a.get("links"),
            actor=a.get("actor") or getattr(cg, "actor", "self_state"),
            force=bool(a.get("force")), strict=bool(a.get("strict")))
    if act == "bootstrap":
        return self_state.bootstrap(
            cg, subject, window=int(a.get("window") or self_state.RECENT_WINDOW),
            actor=a.get("actor") or "bootstrap")
    if act == "relate":
        return self_state.relate(
            cg, a.get("frm") or subject, a.get("to") or "",
            relation_type=a.get("relation_type") or "collaborator",
            strength=a.get("strength", 0.5), condition=a.get("condition") or "",
            note=a.get("note") or "", reciprocal=bool(a.get("reciprocal")),
            actor=a.get("actor") or getattr(cg, "actor", "self_state"))
    if act == "relations":
        return {"relations": self_state.relations(
            cg, subject=a.get("subject"), direction=(a.get("direction") or "both"))}
    if act == "index":
        return self_state.index(cg, a.get("dim"), a.get("value"),
                                limit=int(a.get("limit") or 50),
                                with_content=bool(a.get("with_content")))
    if act == "dimensions":
        return self_state.dimensions(cg, subject)
    if act == "audit":
        return self_state.audit(
            cg, subject, window=int(a.get("window") or self_state.RECENT_WINDOW))
    if act == "history":
        return {"records": self_state.history(
            cg, limit=int(a.get("limit") or 100), subject=a.get("subject"))}
    if act == "summary":
        return self_state.summary(cg, subject)
    if act == "catalog":
        return self_state.catalog()
    raise ValueError(f"self_state 未知 action：{act}")


def _predict_call(cg, a):
    """生成式预测统一入口（cg op=predict 与 mdcg_predict 共用）。

    对齐 AEIS prediction.py 四通道预测引擎的通道 3（生成式·因果路线图）
    + 通道 4（语义式，经 D-002 伪因果过滤门）。输出**候选未来，非必然未来**：
    每条路线都带 uncertainty_bound（不确定性边界）与 extrapolation_validity
    （局部线性近似外推是否仍然成立），并按 T_pred 四维评分排序。
    """
    from . import predict
    act = (a.get("action") or "routes").strip().lower()
    if act in ("routes", "route", "predict"):
        return cg.predict_routes(
            start_id=a.get("start_id") or a.get("node_id"),
            blindspot_id=a.get("blindspot_id"),
            horizon=int(a.get("horizon") or predict.HORIZON_DEFAULT),
            max_branches=int(a.get("max_branches") or predict.MAX_BRANCHES_DEFAULT),
            sort=a.get("sort") or "composite",
            limit=int(a.get("limit") or 0),
            semantic=bool(a.get("semantic", True)))
    if act in ("feedback", "rate"):
        return cg.predict_feedback(
            a.get("predicted_node_id") or a.get("node_id") or "",
            actual_node_id=a.get("actual_node_id"),
            hit=a.get("hit"), note=a.get("note") or "",
            actor=a.get("actor") or getattr(cg, "actor", "predict"))
    if act == "stats":
        return cg.predict_stats(limit=int(a.get("limit") or 20))
    if act == "catalog":
        return predict.catalog()
    raise ValueError(f"predict 未知 action：{act}")


def _causal_call(cg, a):
    """因果推理统一入口（cg op=causal 与 mdcg_causal 共用）。

    `causal` 边 = 条件依赖因果：A 是 B 成立的条件；链 = 条件序列。
    D-002 伪因果过滤门：语义邻近**必须能说清关系**（因果/时序边直通、
    共同父节点的结构模式、偏好权重 > 0.5）才准入，否则视为伪因果拒绝。
    """
    from . import chain, predict
    act = (a.get("action") or "path").strip().lower()
    a_id = a.get("a") or a.get("a_id") or a.get("from") or ""
    b_id = a.get("b") or a.get("b_id") or a.get("to") or ""
    if act in ("path", "reach", "reachable"):
        return predict.causal_path(cg, a_id, b_id,
                                   max_depth=int(a.get("max_depth") or 5))
    if act in ("gate", "filter"):
        ok, why = predict.causal_gate(cg, a_id, b_id)
        return {"ok": True, "admitted": ok, "reason": why, "a": a_id, "b": b_id,
                "note": "语义邻近须能说清关系（因果链/共同父节点/偏好权重>0.5）"}
    if act == "chain":
        return cg.causal_chain(
            a.get("node_id") or a_id,
            relation_types=a.get("relation_types"),
            max_depth=int(a.get("max_depth") or chain.MAX_DEPTH_DEFAULT),
            direction=a.get("direction") or "out",
            sort=a.get("sort") or "strength")
    if act == "explain":
        return cg.explain_chain(a.get("node_id") or a_id)
    if act == "catalog":
        return {"module": "causal", "types": list(chain.CAUSAL_TYPES),
                "chain_types_default": list(chain.CHAIN_TYPES_DEFAULT),
                "edge_weights": chain.EDGE_WEIGHTS,
                "max_depth_default": chain.MAX_DEPTH_DEFAULT,
                "note": "causal = 条件依赖因果，链 = 条件序列",
                "gate": predict.catalog()["decisions"]["D-002"],
                "actions": ["path", "gate", "chain", "explain", "catalog"]}
    raise ValueError(f"causal 未知 action：{act}")


def _evolution_call(cg, a):
    """演化账本统一入口（cg op=evolution 与 mdcg_evolution 共用）。

    载体是 md（`_evolution/ledger.md`）：每一次修改 = 对一条缺失条件的补充，
    记录的是**认知规律**（rule）与**状态**（before→after），不是实现细节。
    rollback 把某条演化的状态撤回 before，撤销本身也记一条条目。
    """
    from . import evolution
    act = (a.get("action") or "summary").strip().lower()
    if act in ("record", "add", "log"):
        return {"entry": cg.evolution_record(
            node_id=a.get("node_id"),
            pattern=a.get("rule") or a.get("pattern") or "",
            missing=a.get("missing") or "",
            action=a.get("change") or a.get("note") or "",
            evidence=a.get("evidence") or "", source=a.get("source") or "",
            kind=a.get("kind") or evolution.KIND_CONDITION_GAP)}
    if act in ("entries", "list"):
        return cg.evolution_entries(
            limit=int(a.get("limit") or 50), node_id=a.get("node_id"),
            kind=a.get("kind"))
    if act in ("show", "get"):
        return cg.evolution_show(a.get("entry_id") or "")
    if act == "history":
        return cg.evolution_history(a.get("node_id") or "",
                                    limit=int(a.get("limit") or 50))
    if act in ("patterns", "regularities"):
        return cg.evolution_patterns(limit=int(a.get("limit") or 10))
    if act == "summary":
        return cg.evolution_summary()
    if act in ("rollback", "revert", "undo"):
        principal = getattr(cg, "principal", None)
        if principal is not None:
            principal.require_admin("evolution_rollback")
        return cg.evolution_rollback(
            a.get("entry_id") or "", dry_run=bool(a.get("dry_run")),
            note=a.get("note") or "")
    if act == "catalog":
        return evolution.catalog()
    raise ValueError(f"evolution 未知 action：{act}")


def _sustain_call(cg, a):
    """持续性自维持统一入口（常驻 / 心跳 / 自愈 / 会话续接）。

    路线图「常驻服务：会话/心跳/自愈」。原则：诊断只读；自愈只碰派生物
    （索引/临时文件/日志边界），永不删节点；缺密钥属于权限事实，只报告不修。
    """
    from . import sustain
    act = (a.get("action") or "status").strip().lower()
    name = a.get("name") or os.environ.get("MDCG_SUSTAIN_NAME") or "md_cg"

    if act in ("status", "info"):
        sm = sustain.summary(cg, name)
        lp = sustain.get_loop(cg, name)
        return {"heartbeat": sm["heartbeat"], "loop": (lp.status() if lp
                                                      else {"running": False}),
                "sessions": sm["sessions"], "watermarks": sustain.watermarks(cg),
                "peers": sustain.peers()}
    if act in ("beat", "heartbeat"):
        return {"beat": sustain.write_stamp(
            name, root=cg.root, task_running=bool(a.get("task_running")))}
    if act == "peers":
        return {"peers": sustain.peers()}
    if act in ("diagnose", "check"):
        return sustain.diagnose(cg, name=name)
    if act in ("heal", "repair"):
        return sustain.heal(cg, name=name, dry_run=bool(a.get("dry_run")))
    if act in ("start", "up"):
        lp = sustain.ensure_loop(
            cg, name,
            beat_interval=float(a.get("beat_interval")
                                or sustain.DEFAULT_BEAT_INTERVAL),
            heal_interval=float(a.get("heal_interval")
                                or sustain.DEFAULT_HEAL_INTERVAL),
            auto_heal=bool(a.get("auto_heal", True)),
            scrub_interval=float(a.get("scrub_interval")
                                 or sustain.DEFAULT_SCRUB_INTERVAL),
            auto_scrub=bool(a.get("auto_scrub", False)))
        return {"loop": lp.start().status()}
    if act in ("stop", "down"):
        lp = sustain.get_loop(cg, name)
        return {"loop": (lp.stop().status() if lp else {"running": False})}
    if act in ("resume", "resume_point"):
        return sustain.SessionLedger(cg.root).resume_point(
            a.get("session") or a.get("node_id") or "")
    if act in ("note", "record"):
        return {"session": sustain.SessionLedger(cg.root).note(
            a.get("session") or a.get("node_id") or "default",
            t=a.get("ts"), seq=a.get("seq"), n=int(a.get("limit") or 1),
            actor=a.get("actor"))}
    if act == "catalog":
        return {"actions": ["status", "beat", "peers", "diagnose", "heal",
                            "start", "stop", "resume", "note", "catalog"],
                "beat_interval": sustain.DEFAULT_BEAT_INTERVAL,
                "heal_interval": sustain.DEFAULT_HEAL_INTERVAL,
                "scrub_interval": sustain.DEFAULT_SCRUB_INTERVAL,
                "thresholds": {"warn": sustain.DEFAULT_WARN_FACTOR,
                               "dead": sustain.DEFAULT_DEAD_FACTOR,
                               "working": sustain.DEFAULT_WORKING_FACTOR},
                "net_dir": sustain.net_dir()}
    raise ValueError(f"sustain 未知 action：{act}")


def _scrub_call(cg, a):
    """记忆自净统一入口（抽查 / 联想 / 去污染 / 校准偏差）。

    路线图「记忆抽查去污染」。原则与 sustain 一致：体检只读；去污染只做
    可逆动作（weaken / demote），**永不删节点**；保护节点跳过。
    """
    from . import scrub
    act = (a.get("action") or "sweep").strip().lower()
    ids = a.get("ids")
    if isinstance(ids, str):
        ids = [s for s in ids.replace(",", " ").split() if s]
    kinds = a.get("kinds")
    if isinstance(kinds, str):
        kinds = [s for s in kinds.replace(",", " ").split() if s]
    node_id = a.get("node_id") or a.get("node")
    target = ids or ([node_id] if node_id else None)

    if act in ("sample", "spot_check"):
        return scrub.sample(
            cg, int(a.get("k") or a.get("n") or scrub.DEFAULT_SAMPLE),
            strategy=a.get("strategy") or "stratified", seed=a.get("seed"))
    if act in ("associate", "related"):
        if not node_id:
            raise ValueError("scrub associate 需要 node_id")
        return scrub.associate(cg, node_id,
                               hops=int(a.get("hops") or scrub.DEFAULT_HOPS),
                               limit=int(a.get("k") or 30),
                               lexical=bool(a.get("lexical", True)))
    if act in ("audit", "check"):
        return scrub.audit(cg, target, hops=int(a.get("hops") or 1),
                           min_severity=a.get("min_severity") or "info")
    if act in ("decontaminate", "repair"):
        return scrub.decontaminate(
            cg, target, kinds=kinds, dry_run=bool(a.get("dry_run", True)),
            min_severity=a.get("min_severity") or "medium",
            hops=int(a.get("hops") or 1), actor=a.get("actor"),
            override=bool(a.get("override")))
    if act in ("calibrate", "calibration"):
        return scrub.calibrate(cg, apply=bool(a.get("apply")),
                               override=bool(a.get("override")),
                               actor=a.get("actor"))
    if act in ("sweep", "run"):
        return scrub.sweep(
            cg, n=int(a.get("k") or a.get("n") or scrub.DEFAULT_SAMPLE),
            seed=a.get("seed"), dry_run=bool(a.get("dry_run", True)),
            hops=int(a.get("hops") or scrub.DEFAULT_HOPS),
            strategy=a.get("strategy") or "stratified",
            apply_calibration=bool(a.get("apply")), actor=a.get("actor"))
    if act in ("history", "log"):
        return scrub.history(cg, limit=int(a.get("k") or 100))
    if act == "summary":
        return scrub.summary(cg)
    if act == "catalog":
        return scrub.catalog()
    raise ValueError(f"scrub 未知 action：{act}")


def _cg_call(cg, a):
    """认知图唯一入口。"""
    op = (a.get("op") or "read").strip().lower()
    _p = getattr(cg, "principal", None)
    if _p is not None and hasattr(_p, "require_op"):
        _p.require_op(op)          # 角色作用域闸门：越权即 AccessDenied

    if op == "theory":
        from . import theory as _th
        act = (a.get("action") or "check").strip().lower()
        if act == "check":
            return _th.check()
        if act == "show":
            return _th.show()
        if act == "catalog":
            return _th.catalog()
        if act == "declare":
            acc = a.get("accepted") or a.get("accepted_versions")
            if isinstance(acc, str):
                acc = [x for x in acc.split(",") if x.strip()]
            return _th.declare(a.get("version"), accepted=acc,
                               actor=(_p.actor if _p is not None else "designer"))
        raise ValueError(f"theory 未知 action：{act}")

    if op == "link":
        from . import links as _lk
        act = (a.get("action") or "ls").strip().lower()
        _actor = _p.actor if _p is not None else "system"
        if act == "catalog":
            return _lk.catalog()
        if act == "ls":
            return _lk.ls(status=a.get("status"), subsystem=a.get("subsystem"))
        if act == "show":
            return _lk.get(a.get("peer"))
        if act == "handshake":
            pm = a.get("position_map")
            if isinstance(pm, str):
                pm = dict(x.split("=", 1) for x in pm.split(",") if "=" in x)
            th = a.get("peer_theory")
            if not th and a.get("peer_version"):
                th = {"version": a.get("peer_version")}
            return _lk.handshake(
                a.get("peer"), peer_theory=th, position_map=pm,
                declared_charter=bool(a.get("declared_charter", True)),
                subsystem=a.get("subsystem"),
                peer_signature=a.get("peer_signature"), actor=_actor)
        if act == "observe":
            return _lk.observe(
                a.get("peer"), evidence=a.get("evidence") or "",
                positive=not bool(a.get("negative")),
                subsystem=a.get("subsystem"),
                peer_signature=a.get("peer_signature"), actor=_actor)
        if act in ("promote", "degrade", "isolate", "withdraw"):
            return getattr(_lk, act)(a.get("peer"), reason=a.get("reason"),
                                     actor=_actor)
        if act == "decay":
            return _lk.decay_all(actor=_actor)
        if act == "policy":                       # 子系统签名策略（D-4）
            from . import signer as _sg
            if a.get("set"):
                return _sg.set_policy(a.get("subsystem"), **{
                    k: a[k] for k in ("signer", "sign_on",
                                      "require_peer_signature",
                                      "on_verify_fail") if k in a})
            return _sg.show()
        # ---- 跨节点证据存储（v0.3）------------------------------------
        if act in ("card", "node_card"):
            from . import evidence as _ev
            return _ev.card(cg.root, subsystem=a.get("subsystem"),
                            signers_file=a.get("signers_file"))
        if act in ("publish", "publish_card"):
            from . import evidence as _ev
            return _ev.publish_card(cg.root, swarm=a.get("swarm"),
                                    subsystem=a.get("subsystem"),
                                    signers_file=a.get("signers_file"))
        if act in ("peers", "peer_list"):
            from . import evidence as _ev
            return _ev.peers(a.get("swarm"), root=cg.root)
        if act in ("evidence", "evidence_ls"):
            from . import evidence as _ev
            return _ev.evidence(
                cg, subject=a.get("subject"), source=a.get("source"),
                limit=int(a.get("limit") or a.get("k") or 100))
        if act in ("export", "evidence_export"):
            from . import evidence as _ev
            subs = a.get("subjects") or a.get("subject")
            if isinstance(subs, str):
                subs = [subs]
            res = _ev.export_pack(
                cg, subjects=subs, since=a.get("since"), swarm=a.get("swarm"),
                subsystem=a.get("subsystem") or _ev.SUBSYSTEM,
                signers_file=a.get("signers_file"))
            if a.get("out"):
                res["written"] = _ev.write_pack(
                    res["pack"], path=a.get("out"), swarm=a.get("swarm"))
            return res
        if act in ("import", "evidence_import"):
            from . import evidence as _ev
            src = a.get("path") or a.get("pack")
            if isinstance(src, str) and src.lstrip().startswith("{"):
                src = json.loads(src)
            if src is None:
                raise ValueError("link/import 需要 path（包文件）或 pack（内联对象）")
            return _ev.import_pack(
                cg, src, subsystem=a.get("subsystem") or _ev.SUBSYSTEM,
                swarm=a.get("swarm"), signers_file=a.get("signers_file"))
        raise ValueError(f"link 未知 action：{act}")

    if op == "info":
        from . import audit
        from . import theory as _th
        from . import links as _lk
        h = cg.health_os()
        h.update({"surface": SURFACE,
                  "tools": [t["name"] for t in tools_for_surface()],
                  "audit_kinds": audit.kinds(), "whoami": cg.whoami()})
        h["theory"] = _th.check()
        h["links"] = _lk.ls()
        return h

    if op == "route":
        intent = a.get("intent") or a.get("query") or ""
        res, meta = cg.search(intent, k=int(a.get("k") or 10),
                              context=a.get("context"), record=False)
        knowledge, caps = [], []
        for n, s, q in res:
            fm = n.get("frontmatter") or {}
            knowledge.append({"id": n.get("id"), "score": s, "state": q.get("state"),
                              "reason": q.get("reason"),
                              "content": (n.get("content") or "")[:500],
                              "verification_basis": fm.get("verification_basis")})
            if fm.get("capability"):
                caps.append(fm["capability"])
            for t in (fm.get("tags") or []):
                if isinstance(t, str) and t.startswith("cap:"):
                    caps.append(t[4:])
        return {"knowledge": knowledge, "suggested_capabilities": sorted(set(caps)),
                "meta": meta,
                "note": "认知图只给知识与建议能力名，不执行；由调用方决定"}

    if op == "read":
        if a.get("node_id"):
            return _node_view(cg.get(a["node_id"]))
        q = a.get("query") or a.get("intent") or ""
        if a.get("budget_tokens"):
            return cg.recall(q, budget_tokens=int(a["budget_tokens"]),
                             k=int(a.get("k") or 20), context=a.get("context"),
                             goal_text=a.get("goal"),
                             include_recent=bool(a.get("include_recent")),
                             recent_limit=int(a.get("limit") or 10))
        res, meta = cg.search(q, layer=a.get("layer"), k=int(a.get("k") or 20),
                              context=a.get("context"))
        return {"meta": meta, "results": [
            {"node": _node_view(n), "score": s, "state": q2.get("state"),
             "reason": q2.get("reason")} for n, s, q2 in res]}

    if op == "write":
        from . import audit
        verdict = audit.audit(
            (a.get("content_kind") or "").strip(),
            {"content": a.get("content", ""), "action": a.get("action"),
             "sensitivity": a.get("sensitivity"),
             "topic": a.get("query") or a.get("intent")},
            {"cg": cg, "principal": getattr(cg, "principal", None)})
        nid = a.get("node_id") or ("mem_" + str(int(__import__("time").time() * 1000)))
        st = verdict["state"]
        if st == audit.ACCEPT:
            # 节点间自动冲突检测（三级决策：情绪→反思→递归反思）：
            # 写入前与既有条件/纪律校验；不通过则不落盘（可进审核队列）。
            # 与 mdcg_remember 同源、默认开启——「信息的修改必须先通过校验」。
            cvd = None
            if bool(a.get("consistency", True)):
                oc = (a.get("on_conflict") or "defer").strip().lower()
                cvd = cg.check_consistency(
                    a.get("content", ""),
                    layer=a.get("layer") or ("contextual" if a.get("gated")
                                             else "knowledge"),
                    condition_space=a.get("condition_space"),
                    non_applicable_conditions=a.get("non_applicable_conditions"),
                    tags=a.get("tags"), exclude=nid, auto_flywheel=True)
                v = cvd.get("verdict")
                blocked = ((v == "REJECT" and oc == "reject")
                           or (v in ("REJECT", "BLINDSPOT") and oc == "defer"))
                if blocked:
                    if oc == "reject":
                        return {"ok": False, "id": nid, "committed": False,
                                "moved_to": "conflict_rejected",
                                "consistency": cvd, "verdict": verdict}
                    pid = cg.propose(nid, a.get("content", ""),
                                     layer=a.get("layer") or "knowledge",
                                     tags=a.get("tags"),
                                     condition_space=a.get("condition_space"))
                    return {"ok": False, "id": nid, "pid": pid, "committed": False,
                            "moved_to": "review_queue", "consistency": cvd,
                            "verdict": verdict}
            if a.get("gated"):
                hint = a.get("importance_hint")
                if hint is None and a.get("importance") is not None:
                    hint = float(a["importance"])
                res = cg.remember_gated(
                    nid, a.get("content", ""), layer=a.get("layer") or "contextual",
                    role=a.get("role"), tags=a.get("tags"),
                    condition_space=a.get("condition_space"),
                    verification_basis=(a.get("verification_basis")
                                        or verdict.get("basis")),
                    non_applicable_conditions=a.get("non_applicable_conditions"),
                    importance_hint=hint, override=bool(a.get("override")),
                    consistency=False)
                v = res.get("verdict")
                committed = v == "ACCEPT"
                out = {"ok": committed, "id": nid, "committed": committed,
                       "gate": res, "verdict": verdict}
                if cvd is not None:
                    out["consistency"] = cvd
                if v == "MERGE":
                    out["moved_to"] = "merged_into:" + str(res.get("merged_into"))
                elif v in ("DROP", "DEFER"):
                    out["moved_to"] = v.lower()
                return out
            cg.add(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
                   tags=a.get("tags"), condition_space=a.get("condition_space"),
                   importance=float(a.get("importance", 0.5)),
                   verification_basis=a.get("verification_basis") or verdict.get("basis"),
                   non_applicable_conditions=a.get("non_applicable_conditions"),
                   override=bool(a.get("override")), consistency=False)
            out = {"ok": True, "id": nid, "committed": True, "verdict": verdict}
            if cvd is not None:
                out["consistency"] = cvd
            return out
        if st == audit.REJECT:
            rid = cg.add_rejected((a.get("content") or "")[:200], verdict["evidence"],
                                  verification_basis=verdict.get("basis") or "test",
                                  tags=a.get("tags"))
            return {"ok": False, "id": rid, "committed": False,
                    "moved_to": "rejected", "verdict": verdict}
        pid = cg.propose(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
                         tags=a.get("tags"), condition_space=a.get("condition_space"))
        return {"ok": True, "id": nid, "pid": pid, "committed": False,
                "moved_to": "review_queue", "verdict": verdict}

    if op == "goal":
        act = (a.get("action") or "list").strip().lower()
        if act == "add":
            gid = cg.add_goal(a.get("goal") or a.get("text") or "",
                              priority=float(a.get("priority", 0.5)),
                              deadline=a.get("deadline"),
                              conditions=a.get("conditions") or "",
                              action=a.get("action_hint") or "",
                              tags=a.get("tags"),
                              status=a.get("goal_status") or "active")
            return {"ok": True, "id": gid}
        if act in ("status", "set_status"):
            return {"ok": True,
                    "goal": cg.set_goal_status(a.get("node_id", ""),
                                               a.get("goal_status") or "done")}
        return {"goals": cg.list_goals(status=a.get("goal_status"),
                                       limit=int(a.get("limit") or 20)),
                "active": cg.active_goals(limit=int(a.get("limit") or 5))}

    if op == "recent":
        act = (a.get("action") or "list").strip().lower()
        if act in ("add", "append", "remember"):
            return cg.remember_event(a.get("role") or "user",
                                     a.get("text") or a.get("content") or "",
                                     tags=a.get("tags"), meta=a.get("meta"),
                                     window=int(a.get("window") or 200))
        if act == "clear":
            return {"cleared": cg.clear_recent()}
        return {"events": cg.recent_events(limit=int(a.get("limit") or 20),
                                           roles=a.get("roles"))}

    if op == "verify":
        return cg.verify(a.get("node_id", ""), a.get("evidence", ""),
                         a.get("verdict", ""))

    if op == "review":
        act = (a.get("action") or "list").strip().lower()
        if act == "list":
            return {"pending": cg.review_list()}
        if act == "rounds":
            pid = a.get("pid", "")
            return {"pid": pid, "rounds": cg.review_rounds(pid)}
        if act == "records":
            return {"records": cg.review_records(pid=a.get("pid"))}
        if act in ("verify_record", "verify"):
            return cg.verify_review_record(a.get("node_id", ""))
        return cg.review_decide(a.get("pid", ""), a.get("decision", ""),
                                edits=a.get("edits"), merge_into=a.get("merge_into"),
                                reason=a.get("reason", ""),
                                redteam=a.get("redteam"), issues=a.get("issues"))

    if op == "forget":
        if (a.get("action") or "forget").strip().lower() == "restore":
            return cg.restore(a.get("node_id", ""), force=bool(a.get("force")))
        return cg.forget(a.get("node_id", ""), a.get("reason", ""),
                         override=bool(a.get("override")))

    if op == "protect":
        return _protect_call(cg, a)

    if op == "identity":
        return _identity_call(cg, a)

    if op == "consistency":
        return _consistency_call(cg, a)

    if op == "metacognition":
        return _metacognition_call(cg, a)

    if op == "self_state":
        return _self_state_call(cg, a)

    if op == "evolution":
        return _evolution_call(cg, a)

    if op == "sustain":
        return _sustain_call(cg, a)

    if op == "scrub":
        return _scrub_call(cg, a)

    if op == "predict":
        return _predict_call(cg, a)

    if op == "causal":
        return _causal_call(cg, a)

    if op == "whitebox":
        return _whitebox_call(cg, a)

    if op == "index_code":
        from . import codeindex
        root = a.get("path") or cg.root
        if not os.path.isdir(root):
            return {"ok": False, "error": f"目录不存在：{root}"}
        items, errors, stats = codeindex.index_dir(
            root, patterns=a.get("patterns"),
            max_files=int(a.get("max_files") or 500))
        ids = []
        for it in items:
            nid = codeindex.node_id(it)
            cg.add(nid, codeindex.render(it),
                   layer=a.get("layer") or "knowledge",
                   tags=["code", "code:" + it["kind"]],
                   condition_space={"observation_position":
                                    it["path"].split("/")[0]},
                   verification_basis=it.get("basis") or "compiler",
                   code_ref={"path": it["path"], "name": it["name"],
                             "kind": it["kind"], "lineno": it["lineno"],
                             "end": it["end"], "lang": it.get("lang"),
                             "precise": bool(it.get("precise", True)),
                             "hash": it.get("hash"), "root": root})
            ids.append(nid)
        note = ("只索引注释/接口（AST 已校验），未存完整代码；"
                "正文用 frontmatter.code_ref + op=ref 指回源文件。"
                "skipped_suffixes 是扫到但**没有提取器**的后缀，用于审计覆盖缺口")
        out = {"ok": True, "indexed": len(ids), "error_count": len(errors),
               "errors": errors[:10], "ids": ids[:20],
               "files": stats["files"], "truncated": stats["truncated"],
               "skipped_suffixes": stats["skipped_suffixes"], "note": note}
        if stats["truncated"]:
            # 截断必须显式说出来：以前静默 return，调用方以为索引是完整的。
            out["truncated_reason"] = stats["truncated_reason"]
            out["note"] = (f"⚠ 索引被截断，结果不完整（{stats['truncated_reason']}），"
                           f"调大 max_files/max_items 后重跑。" + note)
        return out

    if op == "ref":
        return _ref_call(cg, a)

    raise ValueError(f"cg 未知 op：{op}")


def _ref_call(cg, a):
    """按 ref 回读被索引的源位置（认知图只存注释/接口，正文在这里取回）。

    为什么需要它：索引节点存的是**注释与接口**，正文一律不复制（避免出现
    第二份真相）。若没有回读入口，`code_ref` 就只是一串没人消费的坐标——
    「能索引到实际代码」这句话就没有兑现。回读同时用 `codeindex.region_hash`
    复算被引用行的哈希，因此它同时也是**漂移检测**：源文件改过之后，回读会
    明确回 stale=True，而不是继续返回一个已经错位的区间。

    ref 来源二选一：传 `node_id`（取该节点的 frontmatter.code_ref），
    或直接传 `ref` 对象。`root` 可用参数覆盖（ref 里的 root 是索引时的机器本地
    绝对路径，跨机器搬迁后需显式给 root）。
    """
    from . import codeindex
    nid = (a.get("node_id") or "").strip()
    node = None
    if nid:
        node = cg.get(nid)
        if not node:
            return {"ok": False, "error": f"节点不存在：{nid}"}
    ref = a.get("ref") if isinstance(a.get("ref"), dict) else None
    if ref is None and node is not None:
        ref = (node.get("frontmatter") or {}).get("code_ref")
    if not ref:
        return {"ok": False,
                "error": "该节点没有 code_ref（不是代码索引节点）"}
    rel = ref.get("path") or ""
    root = a.get("root") or ref.get("root") or ""
    if not root:
        return {"ok": False, "ref": ref,
                "error": "ref 未记录 root，请显式传 root 参数"
                         "（索引里存的是相对 root 的 path）"}
    fp = os.path.join(root, rel)
    if not os.path.isfile(fp):
        return {"ok": False, "ref": ref, "stale": True,
                "error": f"源文件不存在（索引已悬空）：{fp}"}
    try:
        with open(fp, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "ref": ref, "error": f"读取失败：{exc}"}
    lineno = int(ref.get("lineno") or 1)
    end = int(ref.get("end") or lineno)
    text = "\n".join(lines[max(0, lineno - 1):max(0, end)])
    got = codeindex.region_hash(lines, lineno, end)
    expect = ref.get("hash")
    match = (got == expect) if expect else None
    return {"ok": True, "ref": ref, "text": text,
            "total_lines": len(lines),
            "hash": got, "hash_expected": expect, "hash_match": match,
            "stale": bool(expect) and not match,
            "precise": bool(ref.get("precise", True)),
            "note": "hash_match=False 表示源已漂移，索引位置不再可信，需重跑 "
                    "index_code 重建；precise=False 表示该后缀是弱提取器，"
                    "区间本身就是上界（不是精确范围）。"}


def _whitebox_call(cg, a):
    """显式调用白箱能力库（AEIS 降为本地库后的唯一入口）。

    显式调用映射：md_cg.whitebox.dispatch
    见 docs/功能调用映射表_v0.1.md。
    """
    from . import whitebox
    return whitebox.dispatch(cg, a)


def _stg_call(cg, a):
    """语义时空图唯一入口。"""
    from . import stg
    op = (a.get("op") or "").strip().lower()
    if op == "relation":
        return stg.relation(cg, a.get("a", ""), a.get("b", ""))
    if op == "timeline":
        return stg.timeline(cg, layer=a.get("layer"),
                            limit=int(a.get("limit") or 50),
                            desc=bool(a.get("desc", True)))
    if op == "anchors":
        return stg.anchors(cg, time_window=a.get("time_window"), bbox=a.get("bbox"),
                           layer=a.get("layer"), limit=int(a.get("limit") or 50))
    if op == "consistency":
        return stg.consistency(cg, layer=a.get("layer"),
                               limit=int(a.get("limit") or 50))
    raise ValueError(f"stg 未知 op：{op}")


# --------------------------------------------------------------------------
# 工具实现
# --------------------------------------------------------------------------

def call_tool(cg, name, args):
    a = args or {}
    if name == "cg":
        return _cg_call(cg, a)
    if name == "stg":
        return _stg_call(cg, a)
    if name == "mdcg_whitebox":
        return _whitebox_call(cg, a)

    if name == "mdcg_service_info":
        return {"server": SERVER_NAME, "version": SERVER_VERSION,
                "protocol": PROTOCOL_VERSION, "root": cg.root, "actor": cg.actor,
                "nodes": len(cg.index["nodes"]),
                "surface": SURFACE, "tools": len(tools_for_surface()),
                "tool_names": [t["name"] for t in tools_for_surface()],
                "principal": getattr(cg, "principal", None) and cg.principal.as_dict()}

    if name == "mdcg_remember":
        nid = a.get("node_id") or ("mem_" + str(int(__import__("time").time() * 1000)))
        hint = a.get("importance_hint")
        if hint is None and a.get("importance") is not None:
            hint = float(a["importance"])
        if a.get("gated"):
            res = cg.remember_gated(
                nid, a.get("content", ""), layer=a.get("layer") or "contextual",
                role=a.get("role"), tags=a.get("tags"),
                condition_space=a.get("condition_space"),
                verification_basis=a.get("verification_basis"),
                non_applicable_conditions=a.get("non_applicable_conditions"),
                importance_hint=hint, override=bool(a.get("override")),
                consistency=bool(a.get("consistency", True)),
                on_conflict=a.get("on_conflict") or "defer")
            res.setdefault("ok", res.get("verdict") == "ACCEPT")
            return res
        written = cg.add(nid, a.get("content", ""), layer=a.get("layer") or "knowledge",
                         role=a.get("role"), tags=a.get("tags"),
                         condition_space=a.get("condition_space"),
                         importance=float(a.get("importance", 0.5)),
                         verification_basis=a.get("verification_basis"),
                         non_applicable_conditions=a.get("non_applicable_conditions"),
                         override=bool(a.get("override")),
                         consistency=bool(a.get("consistency", True)),
                         on_conflict=a.get("on_conflict") or "reject")
        if written is None:
            return {"ok": False, "id": nid, "verdict": "DEFER",
                    "reason": "节点间冲突检测未通过（on_conflict=defer）"}
        return {"ok": True, "id": nid}

    if name == "mdcg_recall":
        use_fuzzy = bool(a.get("fuzzy"))
        use_semantic = bool(a.get("semantic"))
        use_goal = bool(a.get("goal_path") or a.get("goal"))
        if use_fuzzy or use_semantic or use_goal:
            paths = ["lexical", "bucket", "entity", "graph"]
            if use_fuzzy:
                paths.append("fuzzy")
            if use_semantic:
                paths.append("semantic")
            if use_goal:
                paths.append("goal")
            paths = tuple(paths)
        else:
            paths = None
        # fuzzy 路缺省用 max 融合：实测（memory-bench-1000，870 查询）sum 会把
        # self@1 拉低 10.1%，因为求和奖励「多路共识」、低估「模糊路独有」的目标。
        # semantic 路同理：条件结构命中常是「独有召回」，故一并缺省 max。
        fusion = a.get("fusion") or ("max" if (use_fuzzy or use_semantic or use_goal) else None)
        return cg.recall(a.get("query", ""),
                         budget_tokens=int(a.get("budget_tokens") or 1200),
                         k=int(a.get("k") or 20), context=a.get("context"),
                         include_work=bool(a.get("include_work")),
                         paths=paths, fusion=fusion,
                         goal_text=a.get("goal"),
                         include_recent=bool(a.get("include_recent")),
                         recent_limit=int(a.get("recent_limit") or 10),
                         query_expand=_make_query_expand(a.get("expand")))

    if name == "mdcg_search":
        res, meta = cg.search(a.get("query", ""), layer=a.get("layer"),
                              k=int(a.get("k") or 20), context=a.get("context"),
                              roles=tuple(a["roles"]) if a.get("roles") else None,
                              include_work=bool(a.get("include_work")))
        return {"meta": meta,
                "results": [{"node": _node_view(n), "score": s, "state": q.get("state"),
                             "reason": q.get("reason")} for n, s, q in res]}

    if name == "mdcg_get":
        return _node_view(cg.get(a.get("node_id", "")))

    if name == "mdcg_reflect":
        res, _ = cg.search(a.get("query", ""), k=int(a.get("k") or 10), record=False)
        return cg.reflect(a.get("query", ""), res, a.get("feedback"))

    if name == "mdcg_verify":
        return cg.verify(a.get("node_id", ""), a.get("evidence", ""), a.get("verdict", ""))

    if name == "mdcg_flywheel":
        return cg.flywheel_step(a.get("error_report") or {})

    if name == "mdcg_mine_fix_pairs":
        return cg.mine_fix_pairs(a.get("events") or [])

    if name == "mdcg_rejected":
        return {"id": cg.add_rejected(a.get("hypothesis", ""), a.get("reason", ""),
                                      verification_basis=a.get("verification_basis") or "test",
                                      tags=a.get("tags"))}

    if name == "mdcg_unresolved":
        return {"id": cg.add_unresolved(a.get("question", ""), a.get("known_clues", ""),
                                        a.get("goal", ""))}

    if name == "mdcg_propose":
        return {"pid": cg.propose(a.get("node_id", ""), a.get("content", ""),
                                  layer=a.get("layer") or "knowledge",
                                  tags=a.get("tags"), condition_space=a.get("condition_space"),
                                  verify=a.get("verify"))}

    if name == "mdcg_review_list":
        return {"pending": cg.review_list()}

    if name == "mdcg_review_decide":
        return cg.review_decide(a.get("pid", ""), a.get("decision", ""),
                                edits=a.get("edits"), merge_into=a.get("merge_into"),
                                reason=a.get("reason", ""),
                                redteam=a.get("redteam"), issues=a.get("issues"))

    if name == "mdcg_review_records":
        nid = a.get("node_id")
        if nid:
            return cg.verify_review_record(nid)
        return {"records": cg.review_records(pid=a.get("pid"))}

    if name == "mdcg_forget":
        return cg.forget(a.get("node_id", ""), a.get("reason", ""),
                         override=bool(a.get("override")))

    if name == "mdcg_restore":
        return cg.restore(a.get("node_id", ""), force=bool(a.get("force")))

    if name == "mdcg_protect":
        return _protect_call(cg, a)

    if name == "mdcg_forgetting_history":
        return {"records": cg.forgetting_history(limit=int(a.get("limit") or 100))}

    if name == "mdcg_identity":
        return _identity_call(cg, a)

    if name == "mdcg_consistency":
        return _consistency_call(cg, a)

    if name == "mdcg_metacognition":
        return _metacognition_call(cg, a)

    if name == "mdcg_self_state":
        return _self_state_call(cg, a)

    if name == "mdcg_predict":
        return _predict_call(cg, a)

    if name == "mdcg_causal":
        return _causal_call(cg, a)

    if name == "mdcg_evolution":
        return _evolution_call(cg, a)

    if name == "mdcg_health":
        return cg.health_os()

    if name == "mdcg_whoami":
        return cg.whoami()

    if name == "mdcg_ingest":
        from .sources import DSHSessionSource, JsonlSource, Ingestor
        src_arg = (a.get("source") or "auto").strip()
        ing = Ingestor(cg)
        if src_arg == "auto":
            files = DSHSessionSource.discover(limit=1)
            if not files:
                return {"error": "no_dsh_session_found"}
            src = DSHSessionSource(files[0])
        else:
            src = _pick_source(src_arg)
        return ing.ingest(src,
                          mine_fix_pairs=bool(a.get("mine_fix_pairs", True)),
                          max_events=a.get("max_events"),
                          dry_run=bool(a.get("dry_run")))

    if name == "mdcg_watermarks":
        from .sources import Ingestor
        return {"watermarks": Ingestor(cg).watermarks()}

    raise ValueError(f"未知工具：{name}")


# --------------------------------------------------------------------------
# JSON-RPC / stdio 主循环
# --------------------------------------------------------------------------

def _reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(_j(msg) + "\n")
    sys.stdout.flush()


def _start_sustain(cg):
    """启动常驻自维持循环（MDCG_SUSTAIN=0 关闭；间隔可用环境变量调）。"""
    if os.environ.get("MDCG_SUSTAIN", "1") in ("0", "false", "False"):
        return None
    from . import sustain
    name = os.environ.get("MDCG_SUSTAIN_NAME") or "md_cg"
    lp = sustain.ensure_loop(
        cg, name,
        beat_interval=float(os.environ.get("MDCG_SUSTAIN_BEAT")
                            or sustain.DEFAULT_BEAT_INTERVAL),
        heal_interval=float(os.environ.get("MDCG_SUSTAIN_HEAL")
                            or sustain.DEFAULT_HEAL_INTERVAL),
        auto_heal=os.environ.get("MDCG_SUSTAIN_AUTOHEAL", "1")
        not in ("0", "false", "False"),
        scrub_interval=float(os.environ.get("MDCG_SCRUB_INTERVAL")
                             or sustain.DEFAULT_SCRUB_INTERVAL),
        auto_scrub=os.environ.get("MDCG_AUTO_SCRUB", "0")
        not in ("0", "false", "False"))
    lp.start()
    return lp


def _build_principal():
    """构造 Principal（令牌优先，fail-closed）。返回 (principal, error)。

    优先级：
      ① MDCG_TOKEN —— 权威路径。校验失败即拒绝启动（不降级为可用）。
      ② MDCG_LEGACY_ENV_AUTH=1 —— 兼容旧部署的 env 直连身份（不推荐）。
      ③ 都没有 —— 降级为只读访客 guest（不写、不管理）。

    版本层（蜂群互联层0）：构造完成后统一附加 theory 状态。声明不合法时
    theory_ok=False → 写/管理操作全拒（保留 theory 修复入口），**不拒绝启动**
    ——身份可信但公理状态未知，禁止改写事实层即可。
    """
    from .security import Principal
    from .tokens import TOKEN_ENV, TokenError, role_spec, verify_token

    token = (os.environ.get(TOKEN_ENV) or "").strip()
    if token:
        try:
            p = verify_token(token, tenant=os.environ.get("MDCG_TENANT"))
        except TokenError as e:
            return None, f"令牌校验失败：{e}"
        return _attach_theory(p), None

    if os.environ.get("MDCG_LEGACY_ENV_AUTH", "0") in ("1", "true", "True"):
        can_admin = os.environ.get("MDCG_CAN_ADMIN", "0") in ("1", "true", "True")
        can_write = os.environ.get("MDCG_CAN_WRITE", "1") not in ("0", "false", "False")
        role = "designer" if can_admin else ("recorder" if can_write else "output")
        spec = role_spec(role)
        p = Principal(
            tenant=os.environ.get("MDCG_TENANT", "default"),
            actor=os.environ.get("MDCG_ACTOR", "mcp-client"),
            clearance=os.environ.get("MDCG_CLEARANCE", "internal"),
            can_write=can_write, can_admin=can_admin, role=role,
            layers_allow=spec["layers_allow"], ops_allow=spec["ops_allow"],
            auth_mode="legacy_env")
        return _attach_theory(p), None

    spec = role_spec("guest")               # 无令牌：只读访客
    p = Principal(
        tenant=os.environ.get("MDCG_TENANT", "default"),
        actor=os.environ.get("MDCG_ACTOR", "mcp-client"),
        clearance="internal", can_write=False, can_admin=False, role="guest",
        layers_allow=spec["layers_allow"], ops_allow=spec["ops_allow"],
        auth_mode="anonymous")
    return _attach_theory(p), None


def _attach_theory(p):
    """附加版本层状态（theory_ok / theory_version）。校验永不抛异常。

    用 `ensure()`：无声明则落盘默认声明（声明常态化），异常声明才降级只读。
    """
    from .theory import ensure as _theory_ensure
    st = _theory_ensure()
    p.theory_ok = bool(st.get("theory_ok"))
    p.theory_version = st.get("version")
    return p


def main():
    root = os.environ.get("MDCG_ROOT")
    if not root:
        sys.stderr.write("[mdcg-mcp] 缺少 MDCG_ROOT 环境变量\n")
        return 2
    from .mdcos import MdCGSecure
    principal, err = _build_principal()
    if err:
        sys.stderr.write(
            f"[mdcg-mcp] {err}\n"
            "[mdcg-mcp] 拒绝启动（fail-closed）。签发令牌：\n"
            "    python -m md_cg.tokens issue --role designer --actor <你>\n"
            "然后设置 MDCG_TOKEN=<返回的明文令牌>。\n")
        return 3
    cg = MdCGSecure(root, principal=principal)
    _start_sustain(cg)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        rid = msg.get("id")

        if method == "initialize":
            _reply(rid, {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": SERVER_NAME,
                                        "version": SERVER_VERSION}})
        elif method in ("notifications/initialized", "initialized"):
            continue                      # 通知，无响应
        elif method == "tools/list":
            _reply(rid, {"tools": tools_for_surface()})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = call_tool(cg, name, args)
                _reply(rid, {"content": [{"type": "text", "text": _j(out)}],
                             "isError": False})
            except Exception as exc:      # noqa: BLE001 —— 工具错误以 MCP 结果返回
                _reply(rid, {"content": [{"type": "text",
                                          "text": _j({"error": f"{type(exc).__name__}: {exc}"})}],
                             "isError": True})
        elif method == "shutdown":
            _reply(rid, {})
            break
        elif rid is not None:
            _reply(rid, error={"code": -32601, "message": f"method not found: {method}"})

    try:                                  # 正常下线：清戳，对端看到的是 stopped
        from . import sustain
        sustain.stop_all()
    except Exception:                     # noqa: BLE001
        pass
    try:
        cg.close()
    except Exception:                     # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
