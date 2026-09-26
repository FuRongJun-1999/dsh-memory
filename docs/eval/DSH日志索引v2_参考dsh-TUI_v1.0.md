# DSH 日志索引 v2 报告（参考 dsh-TUI）v1.0

- **日期**：2026-09-27
- **对象**：`scripts/dsh_log_index.py` 工作树当前版（git status 仅此一个 M 文件，相对 HEAD `014bad50` 的改动未提交，编排会话负责 commit）及其 `dsh-log-` 检索面
- **前置版本**：`docs/eval/DSH日志索引效果验证_v1.0.md`（对应 HEAD `014bad50` 形态：private 会话绑定、turn 整体成章、「两类+静默跳过」，下称 v1.0 报告）
- **参照项目**：`ccch1mneyyy/dsh-TUI`（gh api 可读），参照面 = `src/adapter/channel/session-projection.ts` 的 `KNOWN_DSH_EVENT_TYPES`
- **材料来源标注**：本文实测记录分两类——**【实现会话实测】**指本批次改码/验证会话实跑（逐项改动的红绿腿、临时库摄取、四查询回查；本撰写会话按隐私纪律不重复触达私有会话根与私有数据，未重跑）；**【撰写会话实跑】**指本报告撰写会话本轮实跑复核。凡撰写会话未重跑的检查逐处如实标注，不冒充为本会话实跑。
- **隐私**：全文不含 DSH 会话日志正文原文；只含统计/计数/节点 id/章节标题（turn·k/N 结构形态）/布尔命中；查询词为纪律允许的验证用查询词；全文不含盘符绝对路径、工作区编码目录名与任何密钥字面（命令中一律以 `<DSH会话根>`、`<活库root>`、`<临时库>` 占位；哑密钥只写形态不写字面）。

---

## 一、参照与改进总览

### 1.1 参照面：dsh-TUI 的显式清单与 fail-closed 纪律

dsh-TUI 的 `session-projection.ts` 维护一份 `KNOWN_DSH_EVENT_TYPES` 显式全集（`new Set<string>([...])`，单引号字面量逐行排列、注释分组）。其投影纪律三条（撰写会话拉取原文核对）：

1. **显式全集、不用前缀匹配**——文件头注释明言 "This is NOT a prefix list"：如 `user/unknown-required` 不因 `user/` 前缀而被认作已知，只有精确出现在清单里的类型才被识别；
2. **未知事件不静默跳过（fail-closed 投影）**——未知类型必须显式标记 `ignorable: true` 才允许跳过，否则一律标记上抛，防新版事件类型无声消失；
3. **清单修订须回对上游事件类型全集**——清单与 dsh 事件类型定义文件做 conformance 全量对照。

### 1.2 机械 diff（【撰写会话实跑】复现【实现会话实测】同结果）

命令：`gh api repos/ccch1mneyyy/dsh-TUI/contents/src/adapter/channel/session-projection.ts` → base64 解码 → 逐行提取声明区字面量（跳过注释行、`re.fullmatch(r"'([^']+)',?")`）→ 与 `scripts/dsh_log_index.py` 的 `KNOWN_DSH_EVENT_TYPES` frozenset（importlib 挂载模块读取）双向 diff。输出：

```text
remote_count=81 local_count=82
missing_from_local=[]
extra_in_local=['session']
```

即 **dsh-TUI 线上全集 81 项本地零遗漏**；本地仅增补一项 `'session'`——本日志文件首行元数据行型（dsh-TUI 投影面输入为 events 数组不含首行，故其清单无此项；本工具按整文件消费，必须识别）。

### 1.3 fail-closed 的本地落地

- 清单内、无处理分支的行型 → 计入 `known_other`（识别但不处理）；
- 清单外行型 → **unknown 逐类型计数** + 摄取结束 stderr 单行 WARNING（不失败，退出码不变）+ `--verbose` 逐类型列出（类型×行数×会话）——「新版 DSH 事件类型可静默消失」从结构上封死；
- 修订规则写入模块 docstring：新增类型须回对 dsh-TUI `session-projection.ts`；本地增补行型只增不减。

### 1.4 三项改进与 gap 编号对照

| 改进 | 修的 gap（本报告口径） | v1.0 报告 §四 对应编号 |
|---|---|---|
| 一：显式清单 + unknown 告警 | 新增防线（防新版事件类型静默消失） | ——（v1.0 未暴露此项） |
| 二：turn 内二次分章（≤600 字/章） | **gap②** docindex 摘要截断 | gap① 覆盖率的「截断」半边 |
| 三：internal 共享档 + 派生标识 + workspace 锚（附 retire 处置） | **gap③** 会话绑定可见性；附带修 **gap①** private 误标触发 at-rest 加密致检索零命中 | gap② 可见性；gap① 覆盖率的「加密」半边 |

> **编号注**：v1.0 报告 §四 的 gap 编号是 ①摄取覆盖率 ②可见性 ③排名；本报告沿用改进材料口径 ①加密检索语义 ②摘要截断 ③会话绑定可见性——两套编号按上表映射，后文一律用本报告口径。

**版本演进注**：脚本内部按 v1（HEAD `014bad50`，461 行）→ v2（事件清单，改进一）→ v3（turn 内分块，改进二）→ v4（internal+派生标识+retire，改进三）演进；**工作树当前 = v4 形态（773 行，撰写会话实读）**。下文「v2/v3/v4 代码」指该演进步骤。材料中的行号引证系**各步实现时的快照**，与最终 v4 文件存在位移——§二各改进的改动点均以「材料记录 → v4 复核」双行号并标，v4 行号经撰写会话对全文 773 行逐处实读核对。

---

## 二、逐项改进

### 改进一：事件类型处理升级——「两类+静默跳过」→「显式清单+unknown 告警」

**目标**：`scripts/dsh_log_index.py` 的 DSH 会话日志事件类型处理升级，参照 dsh-TUI `session-projection.ts` 的 `KNOWN_DSH_EVENT_TYPES` 与 fail-closed 纪律。

**改动点**（行号：材料记录 → v4 工作树复核）：

| 改动 | 材料 | v4 复核 |
|---|---|---|
| 模块 docstring：日志形态节补 system/developer/审计/unknown 语义 + 新增「事件类型显式清单」来源节 | :19-49 | 日志形态节 :34-60、清单来源节 :62-69（密级/派生标识节 :10-32 由改进三续写） |
| `KNOWN_DSH_EVENT_TYPES` 显式 frozenset 82 项 + `AUDIT_EVENT_TYPES` 六类型 + `CONTEXT_MSG_TYPES` | :115-171 | :146-186 / :188-190 / :192-194 |
| `parse_session_log` docstring | :214-221 | :243-250 |
| stats 扩展：audit / unknown_types / unknown_lines / context 各计数 | :232-241 | :261-270 |
| CONTEXT 正文提取分支 + audit 计数分支 + known_other 分支 + unknown 逐类型计数分支 | :315-344 | :344-366 / :367-368 / :369-370 / :371-373 |
| `_ROLE_LABELS` 角色标题映射 | :354-358 | :388-390 |
| `--verbose` 参数 | :459-460 | :599-600 |
| total/row 扩展：msgs_context / chars_context / audit / unknown 四组键 + per_session_unknown 收集 | :491-548 | total 初始化 :621-627、row :644-663、per_session_unknown :680-682 |
| 摄取结束 stderr 单行告警 + `--verbose` 逐类型明细 | :604-619 | :753-768 |

**修前/修后**【实现会话实测】：

- **【前（v1 = HEAD `014bad50`）】**只处理 session / turn-start / user-message / agent-inbox-spliced / assistant-message 五行型，其余全部落入单一 `lines_skipped_other`。红基线（改前对真实日志 dry-run）：session-927e3b6a 1387 行中 **1162 行静默**（`skipped.other_type=1162`）、session-d71a652e **476 行静默**——其中混有清单外类型 `workspace/changes`×1；EXIT=0、stderr 全空，新版事件类型可静默消失；`system/message`（54142 字符系统提示节点）完全不进转写。
- **【后（v2）】**① 82 项显式清单（dsh-TUI 线上全集 81 项机械 diff 零遗漏，本地仅增补 `'session'`，见 §1.2）；② `system/message` 与 `developer/message` 正文提取归档（结构探测实测定字段：正文在 `data.message.content[].text`、与 assistant 同形态；回退 `data.content` 对齐 dsh-TUI firstText 两级语义；目标会话转写新增「turn 1（系统）」章节，节点 19→20）；③ `tool/call|result`、`command/run|done`、`hook/invoked|result` 记行为审计行数（目标会话实测 145/145/1/1/0/0，只计数不摄取正文）；④ 清单外类型逐类型计数：session-d71a652e 报 `"unknown":{"lines":1,"types":{"workspace/changes":1}}`，摄取结束 stderr 单行 WARNING（不失败，EXIT=0），`--verbose` 时逐类型列出。

**语义与边界**：

1. 输出 JSON 结构变化：`skipped.other_type` 键删除，替换为 `skipped.known_other` + `skipped.context_no_text`；row 新增 `msgs_context`/`chars_context`/`audit`/`unknown`；TOTAL 新增 `turns_context`/`audit`/`unknown_lines`/`unknown_types`。依赖 v1 输出键名的下游需同步。
2. 转写内容变化：system/developer 正文进入转写 md（标题「（系统）/（开发者）」）——对已用 v1 摄取过的会话重跑会产生新的章节切分与新增节点（临时库实测 19→20）；既有节点 id 幂等跳过不覆写（活库只增不删），在役库既有 dsh-log- 19 节点本次未触（全部验证在哑密钥临时库）。
3. unknown 告警是新增 stderr 输出：退出码不变（0），但把 stderr 视为失败的自动化管道需知悉。
4. 清单修订规则（写入 docstring）：新增类型须回对 dsh-TUI `session-projection.ts`；本地增补行型只增不减。
5. `developer/message` 在全部真实日志中为 0 条，其提取腿以合成日志验证（已注明）。

**验证**【实现会话实测，除注明外】：

- 清单对照：gh api 拉取解码后与脚本 frozenset 机械 diff——remote 81 / local 82 / missing_from_local=[] / extra_in_local=['session']；**【撰写会话实跑】复现同结果（§1.2）**。
- 红基线：v1 对 session-d71a652e dry-run → `skipped.other_type=476`（workspace/changes 静默混入）、EXIT=0、stderr 空。
- 绿·unknown 告警：v2 同会话 dry-run --verbose → stdout JSON `unknown={lines:1,types:{workspace/changes:1}}`，stderr 两行（WARNING 总告警 + `unknown-type: workspace/changes × 1（会话 …）`），EXIT=0。
- 绿·system 提取：v2 对 session-927e3b6a dry-run → `msgs_context={system:1,developer:0}`、`chars_context=54142`（与逐行结构探测一致）；行账闭合 869+292+178+15+1+32=1387。
- 绿·临时库摄取：哑密钥下 `--root <临时库> --allow-init` 摄取：20 节点全落库全 private（v1 同会话基线 19）；以归属会话 Principal+哑密钥开临时库断言：节点 `dsh-log-…-0001` heading 含「turn 1（系统）」、摘要含系统提示特征标记（布尔命中，未打印原文）、节点数 20>19 PASS。
- 绿·developer 腿：合成日志 session-devtest-0000（内容全合成非敏感、临时目录）摄取：`msgs_context.developer=1`、`dsh-log-session-devtest-0000-0000` 落库；归属读者断言正文含合成标记 DEVNOTE-2026 PASS；跨会话读隔离双向成立（另一会话节点对该读者 get 返回 None）。
- **【撰写会话实跑】HEAD 基线形态核对**：`git show HEAD:scripts/dsh_log_index.py` —— 461 行；含 `lines_skipped_other` 单一计数（:150/:229/:389）、`sensitivity_for(it.get("path"), "private")`（:292）、无 `KNOWN_DSH_EVENT_TYPES`/`derive_session_token`/`CHUNK_MAX`——「前态」叙述与提交物一致。

### 改进二：摄取分块细化——修 gap②「docindex 摘要截断」

**目标**：turn 深处结论不再落在摘要线后被截掉；选方案 a（纯工具侧转写分章，不触产品代码）。

**改动点**（行号：材料记录 → v4 复核）：

| 改动 | 材料 | v4 复核 |
|---|---|---|
| docstring 转写结构节：二次分章规格 + 截断根因引证 + gap② 判据 | :56-70 | :71-84 |
| `CHUNK_MAX = 600` 常量与取值理由 | :178-184 | :196-200 |
| `_split_long_para`：句读→空格→字符三级断点，不改动/丢弃一字，兜住无句读长段 | :377-395 | :393-410 |
| `_chunk_body`：按空行分段、贪心聚合 ≤600 字章，纯函数确定性 | :397-417 | :413-432 |
| `render_transcript`：每消息分章、章数>1 时标题带「· k/N」小节号，ATX 转义逐字保留 | :419-443 | :435-460 |

**根因读码（未改产品；【撰写会话实跑】逐处复核一致）**：`md_cg/docindex.py:42`（`MAX_SUMMARY=200`）、`:127`（`_summary` 压平后 `text[:limit]` 截 200）、`:199`（合并子节后再 `[:MAX_SUMMARY]`）、`:266`（render 执行栏 `summary[:MAX_DOC]`，`MAX_DOC=400` 在 `:43`）——产品为「不存全文，节点正文=CCG 模板+摘要，正文一律 ref 回读」设计（`md_cg/docindex.py:13-14`；`MIN_BODY=200` 在 `:41`），而本工具有意不写 doc_ref 绑定（转写是临时暂存物），故章太大时章内深处结论物理不入库。

**修前/修后**【实现会话实测】：

- **【修前（红，改码前工作树=turn 整体成章）】**v1.0 报告 C2 案：转写 43878 字符仅 14805 入库（覆盖率 33.7%），turn2 助手消息 3058 字整体成一章，章摘要只留前 200 字，深处「仓库位置」结论未入库。本次红腿（改码前 v2 代码摄取新临时库）：20 节点中 turn 2 相关节点与全部 20 节点 content 检索词「dsh-memory-main」零命中；主 search 仅返回 0.33 分分词噪声，检索无从命中。
- **【修后（绿）】**turn 内按段落贪心聚合 ≤600 字章（turn2 3058 字 → 7 章），结论词 9 次出现中 7 次落在章摘要（压平前 200 字）内；摄取 114 节点全落库（哑密钥临时库），其中 `dsh-log-…-0035/0036/0037`（heading=turn 2（助手）· 3/7、4/7、5/7）content 真含结论词；词法路单测三节点 rank 1/2/3（lexical_sim=1.000 满分）；主 cg.search 自然语查询「DSH 的工作区目录和真实仓库 dsh-memory-main 在哪里」第一个真命中 rank=1、「dsh-memory-main 仓库位置」rank=4，均命中 turn 2 章。转写全 211 章正文 min/median/max=2/553/599 字、零超限。

**语义与边界**：

1. 转写结构变化：turn 级章节变为 turn·k/N 小节章（单章消息不带小节号）——同会话重跑摄取会产生与 v1/v2 不同的新节点集（`dsh-log-<标识>-NNNN` 序列内容位移），旧节点保留不覆写（活库只增不删）；对已用 v1/v2 摄取过的会话跑 v3 属「新增细化节点」而非原位升级，旧 19/20 节点成为粗粒度冗余版本，回收需另行处置。
2. 节点数增长：同会话 20 → 114（短消息压平 <200 字的章按 docindex 既有 MIN_BODY 语义合并进父节摘要，不单独成节点）。
3. docindex 摘要仍截 200 字/章——600 字章的摘要覆盖章前 1/3；分块是「提高结论落入某章摘要线的概率与密度」，不是全文入库；全文回读仍需 doc_ref（本工具仍不写，v1.0 报告覆盖率 gap 的 doc_ref 缺席不变）。
4. 主 cg.search 默认多路融合对 CCG 模板词共振噪声仍会压低纯词法强命中（实测单词查询真命中排 13-15、自然语查询 rank 1-4）——融合层行为属产品检索面（与 v1.0 报告排名 gap 现象同源），不在本次工具侧修复范围。
5. 幂等与 dry-run 语义不变：分块纯函数确定性 → 同日志逐字节同转写（实测两次 sha256 一致，`093bb6a7…905313`）；重跑摄取 indexed=0/skipped=114。

**验证**【实现会话实测】：根因读码逐处核对（未改产品代码）；分块模拟（改码前对 turn2 真实正文跑拟议算法：7 章中 3 章摘要含判据词 PASS）；红腿摄取临时库（20 节点全库零命中，主 search 仅 0.33 分噪声）；绿腿摄取临时库（114 节点：内容级 3 节点真含词且 heading 均 turn 2；lexical 单路目标三节点 rank 1/2/3、sim=1.0000；主 cg.search 自然语两查询 rank=1 与 rank=4 命中 turn 2（助手）· 5/7）；转写结构（211 章、正文长度 2/553/599、零超 620；判据词 9 次出现 7 次入章摘要）；幂等（绿库重跑 indexed=0/skipped_existing=114；两次 dry-run 转写 sha256 逐字节一致）。门禁回归两件见 §四（【撰写会话实跑】）。

### 改进三：会话绑定可见性修复（gap③）——归因与可见性解耦；附带修 gap①（private 加密致检索零命中）+ 既有 private 旧节点最小处置（软删除）

**目标**：internal 共享档 + 内容寻址派生标识 + 工作区锚；附带修复 private 误标触发 at-rest 加密致检索零命中（gap①），并提供既有 private 旧节点的最小处置。

**改动点**（行号：材料记录 → v4 复核）：

| 改动 | 材料 | v4 复核 |
|---|---|---|
| docstring：密级裁决 internal + 归因/可见性分离 + 派生标识规格 + retire 处置 | :10-33 | :10-32 |
| `import hashlib` | :73-83 | import 块 :115-122（hashlib 在 :116） |
| `derive_session_token`：sha256("{createdAt毫秒}\|{首条 user 消息全文}")[:16] | :472-481 | :472-481（一致） |
| `ingest_transcript`：节点 id=`dsh-log-<token>-<序号>`；sensitivity override="internal"；add 显式 session=token / workspace=工作区目录 / dsh_session_uuid=原 uuid；tags 增 ws: 锚项 | :483-531 | :484-531 |
| `retire_private_legacy`：设计者身份 forget 软删除，判据 fail-closed=`dsh-log-` 前缀 ∧ sensitivity=private | :534-557 | :534-559 |
| `--retire-private-legacy` 参数 | :601-604 | :601-603 |
| token 计算入 row、retire 执行段 | :633-634 / :673 / :741-754 | token 计算 :633-634（一致）、row.session_token :645、retire 执行段 :736-748 |

**关键读码（未改产品；【撰写会话实跑】逐处复核一致）**：`md_cg/mdcos.py:3913-3956`（`_readable`：public/internal=跨会话共享档，不进会话绑定判定——可见性单点在 sensitivity；绑定档判定恒用 principal.session）、`:3796-3807`（`_attribution`：库层调用方显式传 session 可覆盖 principal.session 缺省）、`:2345-2374`（forget=软删除：文件移 trash/ + 删除清单 + 可 restore）、`:3832-3839`（`add(sensitivity=...)`）；`md_cg/crypto.py:62`（`ENCRYPTED_LEVELS=("private","secret")`——internal 不加密）；`md_cg/mdcg.py:907`（`_NODE_ID_RE` 允许 16 hex token）。

**修前/修后**【实现会话实测】：

- **【修前（红）】**用 HEAD 的 v1 基线脚本（private 会话绑定版）摄取哑密钥临时库（19 节点全 private、fm.session=原 uuid）：新会话读者（session=session-aa7b3c21-new-session、clearance=private）search「dsh-memory-main 仓库位置」→ **0 命中**，dsh-log 节点对该读者可见数 **0**——「跨会话回看日志」用途不成立（v1.0 报告可见性 gap 复现）；且 private 触发 at-rest 加密致词法面零命中（gap①）。
- **【修后（绿）】**v4 摄取另一临时库：114 节点全 internal；同一新会话读者 search → **10 条命中（真含词 rank=4）**、dsh-log 可见 114/114；fm 断言全过：sensitivity=internal、session=a5354883dfb88ab2（派生标识）、dsh_session_uuid=原 uuid 留痕、workspace=<工作区目录名>（目录名本报告不录，同 v1.0 口径）、writer=dsh-memory、tags 含 `ws:` 锚项。
- **【retire】**对红库跑 `--retire-private-legacy`：一条命令完成「重摄取 114 internal 新节点 + 旧 19 private 软删除」——retire 后索引中 private dsh-log=0、trash/ 留痕 19 文件、删除清单 19 条、新会话读者检索命中。
- **【稳定性】**派生标识 3 次独立运行同值 `a5354883dfb88ab2`；绿库幂等重跑 indexed=0/skipped=114。

**语义与边界**：

1. 可见性语义变化：dsh-log- 节点从 private 会话绑定档（仅归属会话+设计者可读）改为 internal 跨会话共享档——私有活库内任何 clearance≥internal 的本机授权身份可检索（与手工归档节点同暴露面）；正文不再加密、参与全文索引（使用者裁决「日志不加密」）。
2. 身份锚变化：节点 id 与 fm.session 从 uuid 改为派生标识 sha256(createdAt|首条 user 全文)[:16]——内容寻址，同逻辑会话重跑幂等；取舍：不同会话若 createdAt+首条 user 全文恰相同（如同问重开）会派生同 id 被幂等跳过，第二个会话内容不入库（内容寻址固有语义）。
3. 归因与可见性分离：fm.session=派生标识、dsh_session_uuid=原 uuid、workspace=目录名、writer=actor 全量留痕，但都不参与可见性判定（`_readable` 对 internal 不看这些字段）；workspace 另落 tags `ws:` 项作检索锚。
4. 读码修正预设：原设想「读码确认 session 过滤层后让新会话读者可检索」——实测结论是 `_readable` 的可见性单点在 sensitivity，无独立 session 过滤层可改；internal 档位本身即解，workspace 锚是检索/溯源维度而非可见性闸。
5. 既有 private 节点处置选型：覆盖不可行——v3 分块后章节边界与旧 19 节点内容错位，同 id 覆盖会张冠李戴；故选 forget 软删除（文件移 trash/ 留痕、可 restore、删除清单审计），最小且合规「只增不删」的保守解释。
6. 输出结构：row 新增 session_token；TOTAL/输出新增 retire_private_legacy 摘要；`--retire-private-legacy` 缺省不动任何既有节点（显式开关），dry-run 下跳过。
7. 在役活库执行说明：本轮验证全部在哑密钥临时库，未触在役库——在役库 19 个 private 节点的实际重摄取+retire 需运维编排以真实身份跑同一条命令（脚本能力已就绪并验证）。

**验证**【实现会话实测】：读码引证（上表）逐处核对；红腿（git show HEAD 建基线副本摄红库 19 节点 {'private':19} → 新会话读者 search hits=0、可见数=0、fm sensitivity=private/session=uuid）；绿腿（v4 摄取 114 节点 {'internal':114}、token=a5354883dfb88ab2 → 同读者可见 114/114、search 10 命中（真含词 rank=4）、fm 七项断言 PASS）；retire（--retire-private-legacy 对红库：retired=19、retire 后索引 private=0/internal=114、trash 19 文件、删除清单 19 条、新读者检索真命中 1）；稳定性（token 三次独立进程派生同值）；幂等（绿库重跑 indexed=0/skipped_existing=114）。

---

## 三、v1.0 未命中四查询回查结果

**判定口径与方法**【实现会话实测】：v4 形态脚本（工作树当前版=分块+internal+派生标识）对真实日志 session-927e3b6a…（1387 行）摄取进哑密钥临时库（114 节点全 internal）；4 查询用 v1.0 报告原查询句、k=10，判 hit=期望事实专有词出现在返回节点 CCG content 中；**归属会话读者（session=原 uuid）与新会话读者（session=session-aa7b3c21-new-session）两身份结果逐位一致**——internal 共享档使可见性不再随会话漂移，双身份一致本身就是改进三（gap③ 修复）的直接验证。

**总表**：**3/4 hit**。

| # | 查询（v1.0 案） | 期望事实（专有判据） | hit | 关键命中 |
|---|---|---|---|---|
| Q1 | C1 沙箱启动错误 | SetNamedSecurityInfoW（turn 深处） | **否** | 证据已在库（-0033 真含词）但 top10 乃至 k=60 未召回 |
| Q2 | C2 工作区空目录与真实仓库位置 | 真实仓库在 dsh-memory-main（turn2） | **是** | rank=2（-0037，turn 2（助手）· 5/7）；该事实 3 节点在库（-0035/0036/0037） |
| Q3 | C4 dsh web 重启不生效 | pwsh 不存在 + DETACHED_PROCESS 被宿主回收 | **是** | rank=5（-0086，turn 9（助手）· 2/3，含 DETACHED_PROCESS）+ rank=6（-0087 · 3/3，含 pwsh），因果链两块同进 top10 |
| Q4 | C5 落盘成功但在役 MCP read 返回 null | P1b-2 读面缓存代际（turn12 时间戳链） | **是** | rank=4（-0094，turn 12（助手）· 4/6，真含 14135 与 dsh_restart_recheck）；P1b 主题块另占 rank=2（-0074）与 rank=10（-0059） |

**Q1（唯一未召回案）**：top10 无任何期望事实块——核心判据词 SetNamedSecurityInfoW 所在节点 `dsh-log-a5354883dfb88ab2-0033`（heading=turn 2（助手）· 1/7）在 top10 乃至 k=60 内均未被召回；辅助判据 worker-exit 块（-0028）也未进 top10。根因：-0033 的 CCG 摘要行与查询词面零交叠（实测摘要不含 沙箱/写权限/worker/run_code/退出/挂 任一词），自然语描述与专有 API 名之间无词法桥可召回。注意：**事实本身已在库**（内容级 -0033 content 真含 SetNamedSecurityInfoW）——属「已入库但检索面未召回」，与 v1.0 的「根本未入库」性质不同。

**对照结论与口径注记**：

- v1.0 报告五案在重放库+归属读者的全事实命中为 1/5（且为部分事实）；本轮四案回查 **3/4**——Q2（v1.0 重点未命中案：检索词在 19 块解密内容零命中、覆盖率 33.7% 的代表性失败）**直接翻案**（rank=2），Q3、Q4 时间戳链块也已入库并进 top5，**gap②（摘要截断）修复实效成立**。
- v1.0 报告 C1 曾记「命中 -0000 score 1.0」，按本轮严格判据（期望事实专有词被召回）该命中并非证据块命中。
- Q3 的 turn 号在 v1.0 报告记为 turn10、本轮转写为 turn9，系两轮 turn 号口径差 1，不影响事实判定。
- Q1 属检索器语义桥问题（gap①「加密检索语义」邻域的检索器面，见 §五），非本轮摄取侧改动范畴，如实留档。
- 隐私纪律：全程哑密钥临时库、判据只用专有词/布尔与节点 id，未打印任何日志正文。

---

## 四、门禁（【撰写会话实跑】，环境 PYTHONUTF8=1、仓库根执行）

| # | 检查 | 命令 | 结果 | 退出码 |
|---|---|---|---|---|
| ① | python 回归·docindex 面 | `python -m md_cg.test_p27_docindex` | 通过 98 / 失败 0 | 0 |
| ② | python 回归·ref 根守卫面 | `python -m md_cg.test_p1x_ref_root` | 10/10 通过 | 0 |
| ③ | 脚本模块载入 | diff 挂载经 importlib 执行 `scripts/dsh_log_index.py` 顶层（§1.2 机械 diff 之一环） | 成功（82 项清单载入） | 0 |

三项命令均为本报告撰写会话本轮实跑，退出码逐项实测为 0——门禁 **python=通过（退出码 0）**。

---

## 五、遗留

按影响排序：

1. **gap① 加密检索语义——待拍板**：Q1 案证据已入库但检索面召回不了，查询自然语描述与证据块 CCG 摘要词面零交叠；主 cg.search 默认多路融合还会压低纯词法强命中（实测单词查询真命中排 13-15、自然语 rank 1-4，与 v1.0 报告排名 gap 现象同源）。属产品检索器面，不在摄取工具范畴，需另行裁决方向（语义检索 / 摘要密度 / 融合权重）。
2. **doc_ref 缺席不变**（v1.0 覆盖率 gap 的另一半）：本工具仍不写 doc_ref 绑定（转写是临时暂存物），全文回读不可用；分块只是提高结论落入某章摘要线的概率，不是全文入库。
3. **在役库执行欠账**：本轮全部验证在哑密钥临时库；在役库既有 19 个 private 版 dsh-log- 节点的「以 v4 重摄取 internal 新节点 + `--retire-private-legacy` 软删除旧节点」需运维编排以真实身份执行（脚本能力就绪并已验证）。
4. **内容寻址固有语义**：不同会话若 createdAt+首条 user 全文恰相同会派生同 token 被幂等跳过（第二会话内容不入库）——如该场景真实发生需另立裁决。
5. **stderr 新增告警输出**：unknown WARNING 使工具开始产 stderr；EXIT 不变（0），但把 stderr 视为失败的自动化管道需适配。
6. **旧粗粒度节点冗余**：分块后同会话重跑产生新节点集，v1/v2 时代旧 19/20 节点成为粗粒度冗余版本；`--retire-private-legacy` 只面向 private 版，internal 旧版（若有）回收须另行处置。
7. **developer/message 真实日志 0 条**：其提取腿以合成日志验证（已注明），真实命中面未测。

---

## 六、纪律合规声明

- **隐私（工程纪律第 9 条）**：DSH 会话日志是私有侧数据，摄取目标仅为私有活库 root（脚本 `_guard_root` 拒绝仓库检出内目标），绝不推公开库；本报告与工具输出均不打印日志正文原文——查询词为纪律允许的验证用查询词，日志派生内容一律以计数/节点 id/章节标题/布尔命中呈现；全文不含盘符绝对路径与工作区编码目录名（占位符替代），不含任何密钥字面（哑密钥只写形态）。
- **实验卫生**：实现会话的全部红绿腿实验在临时目录/哑密钥临时库进行——实验脚本/探测脚本/临时库×5/合成日志/err 残留/转写暂存已全部删除（【实现会话实测】清理记录）；**【撰写会话实跑】临时产物**（参照文件 base64/解码缓存、机械 diff 脚本×3、回归输出×2）测毕即删；两次 git status 复查工作树仅剩 `M scripts/dsh_log_index.py`。
- **在役面未触**：未触真实令牌库、未触真实 serve、未触在役活库——在役库既有 dsh-log- 19 节点（private 版）本次零触碰（只增不删纪律下的保守面）；其处置路径已就绪（§五第 3 条），留待运维编排。
- **只增不删**：所有临时库实验中既有节点零修改零删除；retire 为 forget 软删除（trash/ 留痕 + 删除清单 + 可 restore），非物理删除。
- **撰写会话自查范围（诚实边界）**：本会话实跑项 = ①WORKSPACE_INDEX 定位与 v1.0 报告读档；②`scripts/dsh_log_index.py` 全文 773 行实读（双行号表逐处核对）；③gh api 机械 diff（remote 81 / local 82 / missing=[] / extra=['session']）；④`git show HEAD:scripts/dsh_log_index.py` 基线形态核对；⑤产品码引证逐处读码（docindex :13-14/:41/:42/:43/:127/:199/:266；mdcos :3913-3956/:3796-3807/:2345-2374/:3832-3839；crypto :62；mdcg :907）；⑥门禁三项（§四）；⑦`git status --porcelain`（仅 M scripts/dsh_log_index.py）；⑧隐私预扫描（见下）。红绿基线、临时库摄取、retire、四查询回查为【实现会话实测】记录，撰写会话未重跑（触私有会话根与私有数据，按隐私纪律不重复触达），文中逐处标注。
- **隐私预扫描（【撰写会话实跑】，成稿后对本文件全文执行）**：盘符路径形态（字母+冒号+斜杠）0 条；工作区编码目录名字面 0 条；哑密钥字面 0 条；日志正文原文 0 条（扫描脚本与结果见返回记录，扫描完即删）。
