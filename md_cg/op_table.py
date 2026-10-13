# -*- coding: utf-8 -*-
"""MCP 工具面 op 元数据**单点真源**（issue #133 + #140）。

【为什么】
修前 op 元数据分散在 6 处（mcp_server 的 op 枚举串字面量 / cg 工具 description 的
段落文本 / `_ACTION_SIGS` / `_ACTION_DEFAULT` / `_cg_dispatch` 的 `require_op` 实参 /
`tool_face.TOOL_BRIEFS` 的散文计数），且 `tool_face.py` 的散文里写死「34 op」（实为 38）。
四份 op 清单互不对账：枚举串 / 段落 / dispatch 分支 / 散文计数——实测把枚举串里的
`|ccg|` 删掉，`test_tool_face`（23 passed）与 `test_protocol`（44 passed）**双双仍绿**，
而服务端仍接受 `ccg`。

【怎么做】本模块是 op 元数据的**唯一权威**：名字、段落文本、专属参数、权限词、
dispatch 目标、二级子 op（action）登记、缺省 action 与签名推导——都只在这里写一次；
mcp_server / tool_face 各处**从它派生**（枚举串、段落拼接、散文计数、缺省动作表、
签名表、require 词）。**分发结构不动**：`_cg_dispatch` 的 `if op == "x":` 链保持原样，
故 `protocol.dispatch_ops()` 的 AST 提取面逐位不变，仍是可对账的独立读数。

【守卫】`scripts/check_op_table_parity.py` 做三向对账（enum ↔ dispatch AST ↔ schema）
＋「其它处均为派生」的 AST 断言，并做定点变异自证（删掉枚举串里任一 op ⇒ 当场转红）。

【不适用】本模块只登记**元数据**；op 的实际分发逻辑仍在 `md_cg/mcp_server.py`
（`_cg_dispatch`），本模块**不**构成第二套分发。
"""
from __future__ import annotations

# cg 工具 description 的前缀（`op=` 段落之前的部分）
CG_DESC_PREFIX = "认知图接口（唯一入口）。"

# ---------------------------------------------------------------------------
# op 元数据单点表（插入序 = op 枚举串顺序 = 对外契约的一部分）
# ---------------------------------------------------------------------------
_OP_TABLE = {
    "route": {
        "doc_order": 0,
        "doc": "按情境条件路由，返回相关知识 + 建议能力名（不执行，由调用方决定）；",
        "impl": "inline",
        "require": "route",
        "params": (
            "intent",
            "view",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "read": {
        "doc_order": 1,
        "doc": "召回/检索/按 id 取（长内容自动截断 2000 行 / 50KB，返回 truncated+next_offset，续读传 offset=next_offset，不静默丢内容）；",
        "impl": "inline",
        "require": "read",
        "params": (
            "query",
            "goal",
            "include_recent",
            "offset",
            "view",
            "budget_tokens",
            "excerpt_strategy",
            "bm25",
            "session",
            "validity",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "write": {
        "doc_order": 3,
        "doc": "写入前按 content_kind 审核（ACCEPT 落盘 / REJECT 进负记忆 / DEFER 进审核队列）+ 节点间冲突检测（三级决策：情绪→反思→递归反思；consistency=false 可关，on_conflict=reject|defer|record）；gated=true 时再经主动遗忘闸门三问→四态，未指定 layer 时默认 contextual）；",
        "impl": "inline",
        "require": "write",
        "params": (
            "content",
            "content_kind",
            "depends_on",
            "importance_hint",
            "gated",
            "consistency",
            "on_conflict",
            "derived_from",
            "relation",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "verify": {
        "doc_order": 4,
        "doc": "外部裁决回填；",
        "impl": "inline",
        "require": "verify",
        "params": (
            "depends_on",
            "evidence",
            "verdict",
            "marker",
            "fact",
            "questions",
            "v_types",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "review": {
        "doc_order": 5,
        "doc": "审核队列；",
        "impl": "inline",
        "require": "review",
        "params": (
            "action",
            "pid",
            "decision",
            "edits",
            "merge_into",
        ),
        "actions": (
            "decide",
            "list",
            "records",
            "rounds",
            "stats",
            "verify",
            "verify_record",
        ),
        "default_action": "list",
        "sigs": (
            (
        "decision",
        "decide",
    ),
            (
        "node_id",
        "verify_record",
    ),
        ),
    },
    "protect": {
        "doc_order": 6,
        "doc": "写保护盘点/查询/标记/快照/历史；",
        "impl": "_protect_call",
        "require": "protect",
        "params": (),
        "actions": (
            "check",
            "forgetting",
            "forgetting_history",
            "history",
            "mark",
            "protect",
            "snapshot",
            "stats",
        ),
        "default_action": "stats",
        "sigs": (),
    },
    "identity": {
        "doc_order": 11,
        "doc": "身份特征识别（智能论 v3.4 位置效应 + 扮演论三接口 memory/anchor/values，不止「用户画像」；另含存在契约记录 action=contract/contracts——§1.6.5/§3.2.1，结构化引用载体落 anchor 层不可篡改、走 admin 闸、显式非自动）；",
        "impl": "_identity_call",
        "require": "identity",
        "params": (
            "subject_id",
            "subject_kind",
            "trait",
            "position",
            "requested_layer",
            "contract_id",
            "grantor",
            "grantee",
            "timestamp",
            "status_summary",
            "doc_ref",
        ),
        "actions": (
            "anchor",
            "catalog",
            "contract",
            "contracts",
            "history",
            "observe",
            "positions",
            "profile",
            "trait",
        ),
        "default_action": "profile",
        "sigs": (),
    },
    "consistency": {
        "doc_order": 12,
        "doc": "节点间自动冲突检测（三级决策：情绪→反思→递归反思，冲突自动触发飞轮；不能与已有条件冲突/不能违反纪律）；",
        "impl": "_consistency_call",
        "require": "consistency",
        "params": (
            "auto_flywheel",
            "exclude",
            "depth",
        ),
        "actions": (
            "catalog",
            "check",
            "history",
            "stats",
        ),
        "default_action": "check",
        "sigs": (),
    },
    "metacognition": {
        "doc_order": 13,
        "doc": "独立元认知（观察自身认知的二阶单元，不参与裁决；action=report|trace|calibration|blindspots|trust|self_check|history|catalog）；",
        "impl": "_metacognition_call",
        "require": "metacognition",
        "params": (),
        "actions": (
            "blindspots",
            "calibration",
            "catalog",
            "d_meta",
            "history",
            "report",
            "self_check",
            "trace",
            "trust",
        ),
        "default_action": "report",
        "sigs": (),
    },
    "self_state": {
        "doc_order": 14,
        "doc": "自我状态层（薄自我+富索引：状态卡单例 + 关系节点，九项自我信息只存当前值与指针，具体任务/人物/会话/时间/信任由认知图按五维索引连接；action=snapshot|refresh|bootstrap|relate|relations|index|dimensions|audit|history|summary|catalog）；",
        "impl": "_self_state_call",
        "require": "self_state",
        "params": (),
        "actions": (
            "audit",
            "bootstrap",
            "catalog",
            "dimensions",
            "get",
            "history",
            "index",
            "read",
            "refresh",
            "relate",
            "relations",
            "snapshot",
            "summary",
        ),
        "default_action": "snapshot",
        "sigs": (),
    },
    "evolution": {
        "doc_order": 20,
        "doc": "演化账本（md 载体 `_evolution/ledger.md`，每一次修改 = 对一条缺失条件的补充，记录认知规律与状态而非实现；action=record|entries|show|history|patterns|summary|rollback|catalog，rollback 撤回某条演化的状态且撤销本身也留痕）；",
        "impl": "_evolution_call",
        "require": "evolution",
        "params": (
            "rule",
            "missing",
            "change",
            "kind",
            "entry_id",
            "source",
        ),
        "actions": (
            "add",
            "catalog",
            "entries",
            "get",
            "history",
            "list",
            "log",
            "patterns",
            "record",
            "regularities",
            "revert",
            "rollback",
            "show",
            "summary",
            "undo",
        ),
        "default_action": "summary",
        "sigs": (),
    },
    "sustain": {
        "doc_order": 16,
        "doc": "持续性自维持（常驻/心跳/自愈/会话续接；action=status|beat|peers|diagnose|heal|evolve|start|stop|resume|note|catalog；evolve=演化巡检只读盘点固化/重要性候选；heal 默认不动演化，须 allow_evolve=true）；",
        "impl": "_sustain_call",
        "require": "sustain",
        "params": (
            "k",
            "name",
            "ts",
            "seq",
            "task_running",
            "beat_interval",
            "heal_interval",
            "auto_heal",
            "scrub_interval",
            "auto_scrub",
            "evolve_interval",
            "auto_evolve",
            "allow_evolve",
            "dry_run",
            "pools",
            "queries",
        ),
        "actions": (
            "beat",
            "catalog",
            "check",
            "derive_check",
            "diagnose",
            "down",
            "evolve",
            "evolve_check",
            "heal",
            "heartbeat",
            "info",
            "note",
            "peers",
            "pool_ab",
            "pool_bench",
            "pool_catalog",
            "pool_compare",
            "pool_measure",
            "pooling",
            "provenance",
            "record",
            "repair",
            "resume",
            "resume_point",
            "start",
            "status",
            "stop",
            "up",
        ),
        "default_action": "status",
        "sigs": (),
    },
    "scrub": {
        "doc_order": 17,
        "doc": "记忆自净（抽查/联想/去污染/校准偏差；action=sample|associate|audit|decontaminate|calibrate|sweep|history|summary|catalog）；",
        "impl": "_scrub_call",
        "require": "scrub",
        "params": (
            "ids",
            "kinds",
            "strategy",
            "seed",
            "min_severity",
            "apply",
            "lexical",
        ),
        "actions": (
            "associate",
            "audit",
            "calibrate",
            "calibration",
            "catalog",
            "check",
            "decontaminate",
            "history",
            "log",
            "related",
            "repair",
            "run",
            "sample",
            "spot_check",
            "summary",
            "sweep",
        ),
        "default_action": "sweep",
        "sigs": (),
    },
    "predict": {
        "doc_order": 18,
        "doc": "生成式预测（候选未来，非必然未来；沿因果/时序边 + 语义邻近经 D-002 伪因果过滤门生成局部路线，输出 uncertainty_bound / extrapolation_validity / T_pred 四维评分；支持盲区驱动与命中反馈 action=routes|feedback|stats|catalog）；",
        "impl": "_predict_call",
        "require": "predict",
        "params": (
            "start_id",
            "blindspot_id",
            "horizon",
            "max_branches",
            "semantic",
            "sort",
            "predicted_node_id",
            "actual_node_id",
            "hit",
        ),
        "actions": (
            "catalog",
            "feedback",
            "predict",
            "rate",
            "route",
            "routes",
            "stats",
        ),
        "default_action": "routes",
        "sigs": (
            (
        "hit",
        "feedback",
    ),
            (
        "predicted_node_id",
        "feedback",
    ),
            (
        "actual_node_id",
        "feedback",
    ),
        ),
    },
    "causal": {
        "doc_order": 19,
        "doc": "因果推理（causal 边 = 条件依赖因果；action=path 可达性 / gate 伪因果过滤门 / chain 因果链 / explain 解释 / catalog）；",
        "impl": "_causal_call",
        "require": "causal",
        "params": (
            "a",
            "b",
            "relation_types",
            "direction",
        ),
        "actions": (
            "catalog",
            "chain",
            "explain",
            "filter",
            "gate",
            "path",
            "reach",
            "reachable",
        ),
        "default_action": "path",
        "sigs": (),
    },
    "forget": {
        "doc_order": 7,
        "doc": "软删除/恢复（受保护节点需 override）；",
        "impl": "inline",
        "require": "forget",
        "params": (),
        "actions": ("forget", ),
        "default_action": "forget",
        "sigs": (),
    },
    "goal": {
        "doc_order": 8,
        "doc": "目标槽（第 5 篇七件套之「目标」，action=add|list|status；目标不进召回，只给 read 定向）；",
        "impl": "inline",
        "require": "goal",
        "params": (
            "goal",
            "goal_status",
            "priority",
            "deadline",
            "conditions",
            "action_hint",
            "limit",
            # #426-H（2026-10-17 U05b）：目标密级此前**已支持**（MdCGSecure.add_goal
            # 收 sensitivity 并据此做层闸）却没登记 ⇒ 表说「不收」、实际收下又静默丢。
            # 登记与转发是同一件事的两半，同批补
            "sensitivity",
        ),
        "actions": (
            "add",
            "generate",
            "list",
            "set_status",
            "status",
        ),
        "default_action": "list",
        "sigs": (
            (
        "goal",
        "add",
    ),
            (
        "action_hint",
        "add",
    ),
        ),
    },
    "task": {
        "doc_order": 9,
        "doc": "结构层任务实体（跨会话的工程台账，与信任/自我/协议同级；action=open 登记或更新（同名即同卡）、status 状态迁移（进行中/受阻/完成/放弃，迁 完成 时结果必填）、plan_add 追加计划变更、get 单卡全字段、list 清单、find 同族提示（只提示不合并）、session 会话装配面（进行中+近期完成）；任务只存骨架，中间过程不入库，任务知识走 knowledge 层）；",
        "impl": "_task_call",
        "require": "task",
        "params": (
            "task_status",
            "plan",
            "result",
            "acceptance",
            "boundary",
            "note",
            "condition",
            "active_limit",
            "done_limit",
        ),
        "actions": (
            "add",
            "find",
            "get",
            "list",
            "open",
            "plan_add",
            "session",
            "set_status",
            "status",
            "upsert",
        ),
        "default_action": "list",
        "sigs": (
            (
        "name",
        "open",
    ),
            (
        "task_status",
        "status",
    ),
            (
        "result",
        "status",
    ),
            (
        "change",
        "plan_add",
    ),
            (
        "node_id",
        "get",
    ),
        ),
    },
    "recent": {
        "doc_order": 10,
        "doc": "近期事件窗口（七件套之「近期事件」，action=add|list|clear，滚动保留最近 N 条）；",
        "impl": "inline",
        "require": "recent",
        "params": (
            "text",
            "role",
            "meta",
            "window",
            "limit",
        ),
        "actions": (
            "add",
            "append",
            "clear",
            "list",
            "remember",
        ),
        "default_action": "list",
        "sigs": (
            (
        "text",
        "add",
    ),
            (
        "content",
        "add",
    ),
        ),
    },
    "state_event": {
        "doc_order": 36,
        "doc": "状态事件记账（追加一条五元事件subject/slot/old/new/kind；actor 恒取令牌；查询走 stg(op=state_chain)）。",
        "impl": "inline",
        "require": "write",
        "params": (
            "slot",
            "old",
            "new",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "info": {
        "doc_order": 15,
        "doc": "身份+健康+审核体系自描述；",
        "impl": "inline",
        "require": "info",
        "params": ("min_severity", ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "index_code": {
        "doc_order": 21,
        "doc": "按目录（大域）索引代码，只存注释/接口，code_ref 指回源文件，不复制完整代码（后缀按提取器注册表：.py 走精确 AST、.ts/.js 为弱提取器；返回 truncated 截断状态与 skipped_suffixes 覆盖缺口，不再静默不完整）；",
        "impl": "inline",
        "require": "index_code",
        "params": (
            "path",
            "patterns",
            "skip_dirs",
            "prune",
            "max_files",
            "max_items",
            "incremental",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "index_doc": {
        "doc_order": 22,
        "doc": "按目录索引 md 文档的**章节**（只切 level<=3，只存标题+摘要、不存全文），doc_ref 指回原文行区间；layer 与密级显式声明（默认 knowledge/internal，路径命中私有提示降为 private）；正文里的 --- 与围栏代码块内的 # 不会被误切；",
        "impl": "inline",
        "require": "index_doc",
        "params": ("sensitivity", ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "ref": {
        "doc_order": 23,
        "doc": "ref 协议入口（action=read 按 code_ref/doc_ref 回读源区间 / check 漂移·悬空巡检 / stat 看 _refindex.json 水位）。read 需 node_id 或 ref 对象，root 可覆盖；返回 text 与 hash_match，hash_match=False 即源已漂移、索引位置不再可信；check 只读、不抛、不改源文件，报 stale（源已改动）/dangling（源文件已删除）；",
        "impl": "_ref_call",
        "require": "ref",
        "params": (
            "roots",
            "max_nodes",
            "ref",
            "root",
            "sample_n",
            "prefix",
            "verdicts",
            "write",
        ),
        "actions": ("read", ),
        "default_action": "read",
        "sigs": (),
    },
    "whitebox": {
        "doc_order": 24,
        "doc": "显式调用白箱能力库（AEIS 已下线为本地库）并验证其编码/已有知识回答能力（action=ask|remember|verify_encoding|verify_existing|ping|report；结论写回 self 层留痕）；",
        "impl": "_whitebox_call",
        "require": "whitebox",
        "params": (
            "question",
            "message",
            "session_id",
            "marker",
            "fact",
            "questions",
        ),
        "actions": (
            "ask",
            "ping",
            "remember",
            "report",
            "verify_encoding",
            "verify_existing",
        ),
        "default_action": "ping",
        "sigs": (
            (
        "questions",
        "verify_existing",
    ),
            (
        "question",
        "ask",
    ),
            (
        "message",
        "ask",
    ),
            (
        "query",
        "ask",
    ),
            (
        "marker",
        "verify_encoding",
    ),
            (
        "content",
        "remember",
    ),
            (
        "text",
        "remember",
    ),
        ),
    },
    "theory": {
        "doc_order": 25,
        "doc": "协议版本层（action=check|show|declare|catalog）；",
        "impl": "inline",
        "require": "theory",
        "params": (),
        "actions": (
            "catalog",
            "check",
            "declare",
            "show",
        ),
        "default_action": "check",
        "sigs": (),
    },
    "link": {
        "doc_order": 26,
        "doc": "蜂群互联层（对端信任 P_trust + 跨节点证据存储；action=ls|show|handshake|observe|promote|degrade|isolate|withdraw|decay|policy|card|publish|peers|evidence|export|import|catalog；另有节点**派生溯源**（区别于对端信任）：derive 列边、derive_dangling 悬空巡检（只读、不删边）、derive_catalog 自描述、derive_rebuild 按 frontmatter 重建台账（默认预演）；权威声明只在节点写入时产生（write/remember 的 derived_from），本层不新增写入口）；",
        "impl": "inline",
        "require": "link",
        "params": (
            "peer",
            "subsystem",
            "position_map",
            "peer_theory",
            "peer_version",
            "declared_charter",
            "peer_signature",
            "negative",
            "set",
            "signers_file",
            "swarm",
            "subject",
            "subjects",
            "out",
            "pack",
            "child",
            "parent",
            "ledger_only",
        ),
        "actions": (
            "card",
            "catalog",
            "decay",
            "degrade",
            "derive",
            "derive_catalog",
            "derive_dangling",
            "derive_ls",
            "derive_rebuild",
            "evidence",
            "evidence_export",
            "evidence_import",
            "evidence_ls",
            "export",
            "handshake",
            "import",
            "isolate",
            "ls",
            "node_card",
            "observe",
            "peer_list",
            "peers",
            "policy",
            "promote",
            "provenance_catalog",
            "provenance_check",
            "provenance_ls",
            "provenance_rebuild",
            "publish",
            "publish_card",
            "show",
            "withdraw",
        ),
        "default_action": "ls",
        "sigs": (),
    },
    "session": {
        "doc_order": 27,
        "doc": "会话三件套（action=note 写要点 / recall 续接 / compact 压摘要；hook 缺失时的库侧替代——载体负责「何时做」、库保证「一次调用就够用」；note 与 compact(note=True) 需 can_write，recall 只读）；",
        "impl": "_session_call",
        "require": "session",
        "params": (),
        "actions": (
            "compact",
            "note",
            "recall",
        ),
        "default_action": "recall",
        "sigs": (
            (
        "summary",
        "note",
    ),
            (
        "text",
        "note",
    ),
            (
        "content",
        "note",
    ),
        ),
    },
    "ingest": {
        "doc_order": 28,
        "doc": "文件摄取（action=file|dir|jsonl|stat|hive；写链需 can_write，支持 dry_run 预演与 incremental 增量去重、watermark 留痕；mine_fix_pairs 全入口默认关（先落账后挖矿，显式开启走 propose 队列）；hive=蜂巢任务事件源——path=hive/jobs 目录或 env MDCG_HIVE_JOBS，只落 contextual，error 事件自动 private）；",
        "impl": "_ingest_call",
        "require": "ingest",
        "params": ("max_events", ),
        "actions": (
            "dir",
            "file",
            "hive",
            "jsonl",
            "stat",
        ),
        "default_action": "stat",
        "sigs": (),
    },
    "export": {
        "doc_order": 29,
        "doc": "全库导出（action=graph|nodes|slice|stat；导出整库属管理操作，一律 require_admin）；",
        "impl": "_export_call",
        "require": "export",
        "params": (
            "subjects",
            "out",
            "include_content",
            "since",
            "until",
            "tag",
        ),
        "actions": (
            "graph",
            "nodes",
            "slice",
            "stat",
        ),
        "default_action": "stat",
        "sigs": (),
    },
    "maintain": {
        "doc_order": 30,
        "doc": "记忆维护（action=stat|history|importance|longterm|prefeed|separate|rollback|backfill|cap|exempt|vision_evidence|refine|propagate 及其 *_history；propagate = 验证态的**多跳**失效传播巡检（默认预演，apply 需 admin）；权限按 action 分档：只读放行、prefeed 写入需 can_write、批量改写与 rollback 需 admin；dry-run 只出报表不改盘）；",
        "impl": "_maintain_call",
        "require": "maintain",
        "params": (
            "max_rows",
            "keep",
            "mode",
            "snapshot_id",
            "aeis_root",
            "sample_n",
            "prefix",
            "verdicts",
            "batch",
            "entry_ids",
            "min_jaccard",
            "min_delta",
            "write",
            "include_partial",
            "min_conf",
            "basis_text",
        ),
        "actions": (
            "backfill",
            "backfill_rollback",
            "cap",
            "cap_rollback",
            "exempt",
            "exempt_rollback",
            "history",
            "importance",
            "longterm",
            "prefeed",
            "propagate",
            "refine",
            "rollback",
            "separate",
            "stat",
            "vision_evidence",
            "vision_evidence_rollback",
        ),
        "default_action": "stat",
        "sigs": (),
    },
    "consolidate": {
        "doc_order": 31,
        "doc": "离线固化（action=promote 提升 | induce 归纳 | contextualize 语境化，及其 _rollback/_history；批量提升属管理操作，一律 require_admin）；",
        "impl": "_consolidate_call",
        "require": "consolidate",
        "params": (
            "reason",
            "prefixes",
            "min_cluster",
            "min_merge",
            "min_importance",
            "require_conditions",
            "source_layer",
            "target_layer",
        ),
        "actions": ("promote", ),
        "default_action": "promote",
        "sigs": (),
    },
    "insight": {
        "doc_order": 32,
        "doc": "洞察（action=window|record|verify|list|report|reconstruct|learn|outlook|catalog|fork|branch_rewrite|branch_search|branch_merge|branch_discard|branches|tickets；权限按 action 分档：只读放行、条件记账与分支写需 can_write、落库 apply 与分支弃置需 admin）；",
        "impl": "_insight_call",
        "require": "insight",
        "params": (
            "clues",
            "statement",
            "category",
            "v_types",
            "state",
            "window_days",
            "neighbors",
            "recent_days",
            "sample_limit",
            "bypass_gain",
        ),
        "actions": (
            "branch_discard",
            "branch_merge",
            "branch_rewrite",
            "branch_search",
            "branches",
            "catalog",
            "fork",
            "learn",
            "list",
            "outlook",
            "reconstruct",
            "record",
            "report",
            "tickets",
            "verify",
            "window",
        ),
        "default_action": "outlook",
        "sigs": (
            (
        "statement",
        "record",
    ),
        ),
    },
    "ccg": {
        "doc_order": 33,
        "doc": "CCG 六要素编译器（action=compile|review|attest|link|recalibrate|units|catalog；入参统一在 ccg 对象里）。把对话记录编译为六要素候选 → **编外复核**（裁定 A：编译者不得自证，E041 机械拒绝）→ 落库；复核优先走蜂巢 reflect/verify 单元，蜂巢不可用则提示配置，或显式 allow_degrade 降级 harness 端子代理。",
        "impl": "_ccg_call",
        "require": "ccg",
        "params": (),
        "actions": (
            "attest",
            "catalog",
            "compile",
            "link",
            "recalibrate",
            "review",
            "units",
        ),
        "default_action": "compile",
        "sigs": (),
    },
    "status": {
        "doc_order": 34,
        "doc": "**可验证记忆单元**读面（验证态 unverified|verified|doubted|expired|rechecking + 依赖 depends_on + 双时间轴 valid_from/valid_until + 履历台账）；给 node_id 看单节点全貌、不给看全库摘要、action=ledger 读台账。所有读面返回体统一带 status_head 状态头（✓已验证 / △已修改 / !异常 / ?存疑），hint 亦升级为该格式（MDCG_STATUS_HEAD=0 回退旧文本）。",
        "impl": "_status_call",
        "require": "status",
        "params": (),
        "actions": (
            "ledger",
            "log",
        ),
        "default_action": None,
        "sigs": (),
    },
    "edges": {
        "doc_order": 35,
        "doc": "**三元组反查**读面（阶段二 4.2）：按派生边任意端 / 谓词 / 时间反查「这条记忆从哪来、谁由它派生」——subject/predicate/object ≡ child/relation/parent（`derived_from` 派生的三元组）。支持排序（ordering=desc 按写入时刻新→旧，缺省/asc）、分页（offset/limit）、**分页前全集**聚合（aggregation=by_relation|by_parent|by_child）、端点索引摘要（expand_nodes=true）。时间条件缺省走**观察轴**（派生边只有写入时刻 t，无效力声明）——与 op=read 缺省效力轴**有意不同**，由库层单点校验。",
        "impl": "_edges_call",
        "require": "edges",
        "params": (
            "child",
            "parent",
            "ordering",
            "aggregation",
            "expand_nodes",
        ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "audit": {
        "doc_order": 2,
        "doc": "证据审计视图（只读组装，需 node_id；返回现值/出处链/两存备择/盲区/退役史五面；路线 C）；",
        "impl": "inline",
        "require": "audit",
        "params": ("cap", ),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
    "help": {
        "doc_order": None,
        "doc": None,
        "impl": "_help_call",
        "require": None,
        "params": (),
        "actions": (),
        "default_action": None,
        "sigs": (),
    },
}

# 无 op 归属的通用参数（每次调用都可能传的旋钮；由守卫对账 schema.properties）
_GENERIC_PARAMS = (
        "ccg",
        "check_strength",
        "condition_space",
        "context",
        "end_operator",
        "end_time",
        "force",
        "importance",
        "issues",
        "layer",
        "node_id",
        "non_applicable_conditions",
        "override",
        # #426-E（2026-10-17 U05c）：restore 覆写在位节点需显式确认；与 force 分开命名
        # ——force=忽略前置条件，不是「允许覆写同 id 在位节点」（语义压进一个布尔会让
        # 既有调用方的 force=True 静默改变行为）。
        "overwrite_live",
        "prune_dry_run",
        "redteam",
        "start_operator",
        "start_time",
        "tags",
        "time_axis",
        "valid_from",
        "valid_until",
        "verification_basis",
    )

# stg（语义时空图）op 面：单点真源，供 stg 的 op 枚举与散文计数派生
_STG_OPS = (
        "relation",
        "timeline",
        "anchors",
        "consistency",
        "state_chain",
    )


def op_names() -> tuple:
    """顶层 op 名（顺序 = 枚举串顺序）。"""
    return tuple(_OP_TABLE)


def op_enum() -> str:
    """cg 工具 op 参数的**枚举串**（`|` 连接，逐字即对外契约）。"""
    return "|".join(_OP_TABLE)


def stg_op_enum() -> str:
    """stg 工具 op 参数的枚举串。"""
    return "|".join(_STG_OPS)


def cg_description() -> str:
    """cg 工具 description：前缀 + 各 op 段落（按 doc_order 拼，逐字复原）。"""
    rows = sorted((t["doc_order"], n, t["doc"]) for n, t in _OP_TABLE.items()
                  if t.get("doc"))
    return CG_DESC_PREFIX + "".join("op=%s：%s" % (n, d) for _, n, d in rows)


def op_section(name: str):
    """取某 op 的段落原文（未登记回 None）。"""
    row = _OP_TABLE.get(name)
    return row["doc"] if row else None


def action_default() -> dict:
    """op → 缺省 action（只含登记了缺省值的 op）。"""
    return {n: t["default_action"] for n, t in _OP_TABLE.items()
            if t.get("default_action")}


def action_sigs() -> dict:
    """op → 签名推导表（(依据键, action) 有序元组）。"""
    return {n: tuple(tuple(x) for x in t["sigs"]) for n, t in _OP_TABLE.items()
            if t.get("sigs")}


def require_of(op: str, default=None):
    """该 op 在 `_cg_dispatch` 里 require_op 用的**权限词**；未登记回 default。"""
    row = _OP_TABLE.get(op)
    return row["require"] if row else default


def sub_ops(op: str) -> tuple:
    """该 op 已登记的**二级子 op**（action）名。"""
    row = _OP_TABLE.get(op)
    return tuple(row["actions"]) if row else ()


def all_sub_ops() -> dict:
    """op → 二级子 op 名元组（只含登记了子 op 的 op）。"""
    return {n: tuple(t["actions"]) for n, t in _OP_TABLE.items() if t["actions"]}


def params_of(op: str) -> tuple:
    """该 op 的专属参数名（schema.properties 的子集）。"""
    row = _OP_TABLE.get(op)
    return tuple(row["params"]) if row else ()


def generic_params() -> frozenset:
    """无 op 归属的通用参数名。"""
    return frozenset(_GENERIC_PARAMS)


def stg_ops() -> tuple:
    return tuple(_STG_OPS)
