# DSH 端缺陷专项修复报告 v1.0

- **日期**：2026-09-26
- **范围**：DSH 端（插件另一端）在役实测报告四组缺陷的修复落地。定性由编排会话读码完成，本轮为修复与验证的如实汇编；修复落点全部在本仓 `md_cg/`（记忆引擎/工具面）与 `scripts/`（工具孪生件），不改 DSH 侧代码。
- **基线**：工作区 HEAD `2ae15a63`（main）之上的未提交改动——`git status --short` 实测：修改 7 件（`md_cg/evidence.py`、`md_cg/mdcg.py`、`md_cg/mdcos.py`、`md_cg/review_cli.py`、`scripts/linkref_backfill.py`、`scripts/migrate_restricted.py`、`scripts/review_cli.py`），新增守卫 3 件（`md_cg/test_review_cli_visibility.py` 235 行、`md_cg/test_review_cli_attribution.py` 177 行、`md_cg/test_none_id_write_guard.py` 165 行）。未 git commit（编排会话负责）。
- **材料来源**：第二节逐项修复的 target/前后对比/语义变化/验证主体来自编排会话交付的三份修复材料（修复轮实跑记录）；本报告撰写会话对全部关键引证做了逐条读码复核，**材料行号与当前工作区实测有漂移处已按实测修正**（校勘明细见附录清单二末尾），三个守卫套件在本会话重跑全绿（实测输出见第三节、第四节）。

---

## 一、总览

DSH 端在役实测报告四组缺陷，经编排会话读码定性后，处置矩阵如下：

| 组 | 标签 | 缺陷一句话定性 | 处置 | 结果 |
|---|---|---|---|---|
| 可见性 | **P1b** | review_cli 裁决落盘节点在 MCP 读面不可见——autoflush 兜底的第二落点遗漏（server 级 2026-09-16 已修，工具面四处构造漏补） | 代码修复（4 处构造补 `autoflush=1` + 红守卫） | 已修；守卫 10/0（本会话重跑 EXIT=0） |
| 归因 | **P1** | review_cli 随机会话 + accept 落盘 writer 被 designer-cli 覆盖，原始写入者不可追溯 | 代码修复（`--session` + 归因保留 + 红守卫） | 已修；守卫 10/0（本会话重跑 EXIT=0） |
| 归因（环境侧） | **P1-1** | DSH 会话目录若不在 `_normalize_session` 校验面内（`MDCG_DSH_SESSIONS_ROOT` / `~/.dsh/sessions`），该会话在 MCP 写入面降级 anonymous，CLI 与 MCP 两侧归因对不上 | 环境侧回告（按要求非代码修） | 回告，复验清单见第五节 |
| 脏节点 | **P3** | `knowledge/orphan/None.md` 脏节点写入源头——node_id 字符串化污染形态（`"None"`/`"null"`）在写入边界放行 | 代码修复（写入边界整串精确等值闸 + 红守卫）+ 存量清理建议回告 | 已修；守卫 17/0（本会话重跑 EXIT=0） |
| 待排期 | **P4 / P5** | 本轮材料未含其定性细节（如实注明，不入虚构内容） | 入缺陷池 | 不入本轮，见第六节 |

四组归并：①可见性组（P1b）②归因组（P1 + 其环境侧面 P1-1）③脏节点组（P3）④其余（P4/P5 入池）。三项代码修复共用同一条工程链路：读码定性 → 修复落点 → 红守卫先红后绿 → 定向回归 → 组全量/门禁。

---

## 二、逐项修复

### 2.1 P1b——review_cli 裁决落盘节点在 MCP 读面不可见（autoflush 兜底第二落点遗漏）

**target**：短命裁决/工具进程被 kill 时，索引增量停留在内存 `_dirty`、分片日志 `_index_log/` 从未落盘，其它进程读面不可见（DSH 在役实测 read null）。server 级同款兜底 2026-09-16 已修（`md_cg/mcp_server.py:3695-3702`，`autoflush=1`），本项补齐**工具面第二落点**。

**落点**（全部本会话读码复核在位）：
- `md_cg/review_cli.py:96-106`——`_cg` 返回 `MdCGSecure(..., autoflush=1)`（`autoflush=1` 在 :106），注释写明根因与 mcp_server 对照；
- `md_cg/evidence.py:509-512`——`_open_cg` 同款补参（`autoflush=1` 在 :512）；
- `scripts/linkref_backfill.py:195-198`——构造补 `autoflush=1` + 注释；
- `scripts/migrate_restricted.py:41-46`——构造补 `autoflush=1` + 注释；
- `md_cg/test_review_cli_visibility.py`——新增红守卫（235 行）。
- `scripts/_mdcg_reindex_code.py:62` 经读码判定**不改**：批式重索引工具（逐文件 add 可达数千条），:128 有显式 `cg.close()` 作为确定性提交边界（flush+compact 落快照），收尾语义与「写完即退的短命工具」不同——per-write `autoflush=1` 只会增加数千次逐条日志 append 的开销而无可见性收益，维持 `autoflush=64`（本会话实测 :62 为 `autoflush=64`、:128 为 `cg.close()`，在位）。

**前后对比**：
- 修复前：`python -X utf8 -m md_cg.test_review_cli_visibility` → PASS=5 FAIL=5。红项：③落账契约「进程 A'（经生产构造 `_cg` 调库裸 add 2 条 → `os._exit(0)` 模拟被杀，close/atexit 均不执行）退出后盘面 `_index_log/` 已含全部写入记录」实测 `log_ids=[]`（autoflush=64 未达阈值，分片日志从未落）；④四处构造 autoflush 回显均为 64/缺参。
- 修复后：同命令 → PASS=10 FAIL=0（③ `log_ids=['vis-node-1','vis-node-2']`；④ review_cli `_cg` 与 evidence `_open_cg` 行为断言 `autoflush==1`，两个 scripts 源级断言命中）。
- 读面断言①②（进程 A subprocess 跑 review_cli accept/调库落盘 → 进程 B 全新子进程 `_load_index`+read 断言业务节点与审计记录节点可见）修复前后均绿——如实说明：本仓 HEAD 上正常路径已由 09-16 的 review_decide 显式 flush（`md_cg/mdcos.py` 实测三处 `self.flush()` 在 :2258/:2309/:2330）+ review_cli finally `cg.close()`（`md_cg/review_cli.py:204-211`）+ 库层 atexit（`md_cg/mdcg.py:104-118`，`atexit.register` 在 :117，仅覆盖正常退出）覆盖；kill 形态的重开读面已由批次 39（9102df88，2026-09-25）`_load_index` 指纹失配→全扫自愈（`md_cg/mdcg.py:959-970`：指纹不符或旧快照无 `_fingerprint` 键即 `idx=None` 回退 `_scan_nodes` 全扫）兜住，该自愈晚于 09-16 的 autoflush=1 修复（17699ec5）落地——DSH 在役实测的 read null 对应**旧读面**（0.4.x 副本 `_load_index` 盲信既有快照无指纹校验）+ **旧写入面**（无显式 flush/autoflush）的叠加形态，本次补齐的正是写入面兜底在短命工具侧的第二落点（与 server 同款）；①②保留为回归钉，防上述两层兜底未来被移除时旧症复发。

**语义变化**：`autoflush=1` 仅改变索引增量的落账时机：写入经 `_stage` 后立即 flush() 落分片日志 `_index_log/`（`md_cg/mdcg.py:2079-2087` 阈值判定 `len(self._dirty) >= self.autoflush` 在 :2086-2087，1 条即落），任意退出形态（含被 kill）下写入对其它进程立即可见；flush 幂等（`_dirty` 空即 no-op，`md_cg/mdcg.py:1080-1081`），节点文件/索引条目内容、读面结果、权限闸均零变化。四处均为构造参数增补，无 API/文件格式变更。`_mdcg_reindex_code.py` 维持 autoflush=64 是读码判定后的刻意不动（见落点末段理由），非遗漏。

**验证**：
1. 守卫红→绿：`python -X utf8 -m md_cg.test_review_cli_visibility`，修复前 PASS=5 FAIL=5（③ `log_ids=[]`、④ autoflush=64×2 + 源级断言×2 未命中），修复后 PASS=10 FAIL=0。**本报告撰写会话重跑：PASS=10 FAIL=0，EXIT=0**（③ `log_ids=['vis-node-1','vis-node-2']`、④ `autoflush==1`×2 + 源级断言×2，实测输出见第三节）。
2. 回归（修复轮实跑）：`test_review_cli_attribution` 10/0；`test_review_conformance` 38/0；`test_review_onepass` 10/0；`test_p24_evidence` 29 passed（evidence.py 改动的直接回归）。
3. `python -X utf8 -m py_compile` 五个改动文件 → COMPILE_OK；`scripts/migrate_restricted.py --root <临时库>` dry-run 冒烟 exit=0、`scripts/linkref_backfill.py --root <临时库>` 扫描冒烟 exit=0（修复轮实跑）。本会话另对 11 个改动面+新守卫+reindex 工具整体 py_compile → **COMPILE_OK**。
4. 全量测试由编排会话跑（修复轮未跑，本报告会话亦未跑——见第四节门禁与第六节申报）。
5. 实验与测试全程临时目录 + 哑主密钥（`MDCG_MASTER_KEY=ab*32`），实验目录（系统临时目录下 `mdcg_p1b_exp` 及 `clivis_*` 等临时残留）已清理（余量 0）。
6. 读码依据（行号为本会话实测）：`mdcg.py:922`（autoflush 缺省 64）、`mdcg.py:104-118`（`_atexit_flush_all`，atexit 仅正常退出）、`mdcg.py:2079-2087`（`_stage` 阈值落账）、`mdcg.py:1079-1098`（flush 落分片日志）、`mdcg.py:948-975`（`_load_index`=快照+日志重放，:959-970 指纹失配全扫自愈）、`mdcos.py:2258/2309/2330`（review_decide 显式 flush）、`mcp_server.py:3695-3702`（server 级 autoflush=1 对照）、git 时间线 17699ec5（09-16 autoflush）vs 9102df88（批次 39 指纹自愈，09-25）。未触真实令牌库/真实 serve/在役数据目录。

### 2.2 P1——裁决面身份归因退化：review_cli 随机会话 + accept 落盘 writer 被 designer-cli 覆盖（原始写入者不可追溯）

**target**：同一批裁决落盘节点会话 id 各自随机（DSH 实录 5 节点 5 个 `sess_*`），且 accept/edit 落盘节点 `frontmatter.writer` 被裁决者 designer-cli 覆盖，提案原始写入者（如 dsh-memory）不可追溯。

**落点**（本会话读码复核在位）：
1. `md_cg/review_cli.py`——模块 docstring :31-44（`--session` 用法 + 落盘归因回告，含 `_normalize_session` 的 DSH 前置条件注记）；:75-80 新增 `_session_of`（`--session` > 环境变量 `MDCG_SESSION` > None）；:83-106 `_cg` 改造（None 时 stderr 告警一行后维持随机会话）；:175-178 argparse common 新增 `--session`，所有子命令通用（`parents=[common]` 挂全部 8 个子命令）。
2. `md_cg/mdcos.py:2240-2249`——review_decide accept/edit 分支：提案记录的原始 actor（propose rec 的 `"actor"`，propose 时库端快照，`md_cg/mdcos.py:1770`）经 `extra.setdefault` 记为落盘节点 `frontmatter.writer`，裁决者 `self.actor` 记入 `frontmatter.reviewer`。
3. `scripts/review_cli.py`——孪生件同款同步（`_session_of` :66、`--session` argparse :153、docstring :11/:26）；本会话实测两文件同步点在位。
4. `md_cg/test_review_cli_attribution.py`——新增红守卫（①~⑥ 共 10 断言，177 行）。

注：git status 中 `md_cg/mdcg.py` 的改动与 `md_cg/test_none_id_write_guard.py` 为并行修复员的 P3（None.md）改动，非本目标所改，未触碰。

**前后对比**：
- 修复前（红守卫实测，`python -m md_cg.test_review_cli_attribution`）：PASS=2 FAIL=8——`accept --session` 报 argparse "unrecognized arguments" 退出码 2；提案人以 actor=dsh-memory propose、designer-cli accept 后节点 `frontmatter.writer="designer-cli"`（原始写入者被覆盖，DSH 缺陷直接复现）；设 `MDCG_SESSION` 亦被无视（落 `sess_41d73208c113` 随机值）；无告警。
- 修复后：同一守卫 PASS=10 FAIL=0——`accept --session sess_decide_01` → `frontmatter.session=="sess_decide_01"`、`writer=="dsh-memory"`（原始写入者在位）、`reviewer=="designer-cli"`（裁决者换字段保留）；同一 `--session` 两次裁决两节点归属一致；仅设 `MDCG_SESSION` 时兜底生效（sess_env_03）；两者皆缺省时 stderr 恰一行随机会话告警且退出码 0、仍落 `sess_*` 随机值（现状兼容）、writer 归因同样在位。
- 孪生件 `scripts/review_cli.py` 端到端（修复轮，临时库+哑密钥）：rc=0，`session='sess_twin_01'`、`writer='dsh-memory'`、`reviewer='designer-cli'`；`_session_of`/`_cg` 两文件逐字一致已 diff 验证（修复轮实跑；本会话复核同步点在位，未重跑孪生端到端——见第六节申报）。

**语义变化**（向后兼容）：
1. `frontmatter.writer` 含义变化——accept/edit 落盘节点从「最后落盘者=裁决者（designer-cli）」变为「保留提案原始写入者」（propose 时库端快照的 actor，非裁决期客户端输入，不可伪造面）；裁决者身份不丢失，移入 `frontmatter` 新增字段 `reviewer`。该实现落在引擎层 `mdcos.review_decide`，故 MCP 面 op=review 的 accept/edit 走同一代码路径同样受益。兼容性：提案 extra 里已带 writer 的存量提案不覆盖（`setdefault`，保留既有「库层调用方可显式传值覆盖」通道，`_attribution` 语义不变）；旧格式提案无 actor 时 writer 仍回落裁决者（现状不变）；merge/reject/noop 路径不动。
2. review_cli 全部子命令新增 `--session`：缺省取环境变量 `MDCG_SESSION`，仍无则维持旧随机会话行为、仅多一行 stderr 告警（不拒绝、不阻断）；现有调用形态（不传 `--session`）全部照旧。
3. `frontmatter.session` 语义本身不变（写入时会话归属），变化仅是取值来源受控——DSH 端同一批裁决传同一 `--session` 即得同一落盘归属。
4. **DSH 前置条件回告（P1-1，按要求为回告非代码修）**：MCP 写入面对 DSH 形态会话 id（`session-<8>-<4>-<4>-<4>-<12>`）有 `_normalize_session` 防编造校验（`md_cg/mcp_server.py:3381-3405`，目录根可用 `MDCG_DSH_SESSIONS_ROOT` 覆盖、缺省 `~/.dsh/sessions`，:3397）——会话目录须真存在于其下，否则该会话在 MCP 面降级 anonymous；review_cli 直构 Principal 不经该校验。此注记已写入两份 review_cli 模块 docstring（`md_cg/review_cli.py:39-44`），DSH 端环境侧需自行核对目录在位，否则 CLI 与 MCP 两侧归因对不上。
5. 未做 git commit（按纪律，编排会话负责）。

**验证**（修复轮全部实跑）：
- 修复前红：`python -m md_cg.test_review_cli_attribution` → PASS=2 FAIL=8（关键红：`--session` 未识别退出码 2；writer=designer-cli；`MDCG_SESSION` 被无视落随机值；无告警）。
- 修复后绿：同命令 → PASS=10 FAIL=0。**本报告撰写会话重跑：PASS=10 FAIL=0，EXIT=0**（session/writer/reviewer 三归因逐项断言 + 稳定性 + `MDCG_SESSION` 兜底 + 告警一行 + 随机兼容，实测输出见第四节抽验）。
- 孪生件端到端（修复轮，子进程，临时库 + `MDCG_MASTER_KEY=ab*32` 哑密钥）：`scripts/review_cli.py accept --session sess_twin_01` → rc=0，frontmatter 三归因在位。
- 定向回归全绿（修复轮实跑）：test_review_conformance 38/0、test_index_durability 16/0、test_identity_attribution 19/0、test_propose_tail_index 8/0、test_review_onepass 10/0、test_merge_upsert 11/0、test_n131_merge_gate 17/0、test_p2_mcp 64/0、test_p21_tokens 38/0、test_p2 37/0、test_action_derive 46/0、test_mr_m4 88/0。
- 组全量：`python scripts/run_tests.py md_cg --jobs 4` → 159/159 通过、3 跳过（白箱语料依赖，既有跳过）、exit 0，清单含 PASS `md_cg.test_review_cli_attribution`。
- `python -m md_cg.review_cli accept --help` → `--session` 在列；`python scripts/run_tests.py --list` → 新守卫已入发现面。

### 2.3 P3——knowledge/orphan/None.md 脏节点写入源头（md_cg 写入边界 node_id 污染形态放行）

**target**：DSH 在役库出现 `knowledge/orphan/None.md` 并进入检索与 route 候选（route op 即 `cg.search`，`md_cg/mcp_server.py:2117-2119`，本会话实测）。定性：`str(None)`（Python）/`String(null)`（TS）字符串化污染形态在写入边界放行。

**落点**（本会话读码复核在位）：
- `md_cg/mdcg.py:909-916`——新增模块级 `_NODE_ID_FORBIDDEN = frozenset({"None", "null"})` 及成因注释，紧邻 `_NODE_ID_RE`（:907）；
- `md_cg/mdcg.py:1316-1321`——add 既有白名单闸（None 本体/空串/`..` 穿越/形状）位置；
- `md_cg/mdcg.py:1322-1326`——add() 写入边界新增整串精确等值闸：`nid_s in _NODE_ID_FORBIDDEN` → 结构化 ValueError（消息点名 P3 缺陷与改法）；
- `md_cg/test_none_id_write_guard.py:1-165`——新红守卫，套件自动发现。

**前后对比**：
- 修前（修复轮，临时库实弹复现）：`MdCGOS.add("None", …)` 返回 `'None'` 并落盘 `knowledge/orphan/None.md`；`add("null")` 同（白名单 `_NODE_ID_RE` 形状合法放行——str(None)/String(null) 字符串化污染形态）；该文件经 `_scan_nodes` 收录为 id="None"，search_rrf 实测命中 `('None', 0.016)`，与 DSH 在役『None.md 出现在检索与 route 候选』病理吻合。
- 修后：add 在唯一写入边界拒 `"None"`/`"null"`（ValueError），盘面无 None.md、索引无该条目；防误杀与既有语义不回退（`'NoneBot_1'`/`'nullify_test'` 子串 id 正常写入；`add(None)`/`''`/`0` 仍 P0-1 ValueError）。
- 红→绿：守卫修前 9 通过/7 失败，修后 17 通过/0 失败。**本报告撰写会话重跑：17 通过/0 失败，EXIT=0**（[1] 字符串 "None" 拒写 4 断言、[2] "null" 拒写、[3] 防误杀、[4] 既有语义不回退、[5] writepipe 链不落盘、[6] 存量脏数据收录取证与清理路径实证，实测输出见第四节抽验）。

**语义变化**：
1. 行为变化仅一处：node_id 与 `"None"`/`"null"` **整串精确等值**（大小写敏感、不扩子串）的写入由『成功落盘』变『ValueError 拒绝』。全部写入链（writepipe 执行器、review accept、identity、consolidate、branches）最终经 add 单点落盘，行为同步收敛；已持有存量 id="None" 节点的库再覆写该 id 将被拒——预期 fail-closed。
2. 定性（取证结论）：None.md 出自两段叠加——①批次 24（2a57c2a2，2026-09-24）之前 add 无任何校验、`f"{node_id}.md"` 直拼，`add(None)` 直落 None.md（修复轮 `git show 2a57c2a2^:md_cg/mdcg.py` 实证：旧 add 无校验、path 直拼，DSH 在役库的存量 None.md 属该历史脏数据）；②现行代码 `add(None)` 本体已拒，但字符串形态 `add("None")` 仍可造出 None.md——这是现行残留洞而非纯历史问题，故本次修复成立，非『修不存在的缺陷』。
3. 存量清理建议（未代执，不触真实库）：删除 `<root>/knowledge/orphan/None.md` 后 `rebuild_index()` 即从索引与检索/route 候选消失（守卫 [6] 三断言实证该路径有效）；勿用 `add("None")` 覆写清理（修后被拒）。
4. 相邻发现（如实报告，未修，超本目标）：①`add(123)` 等非字符串真值 id 以原值入索引键，flush 落快照后重开 `_load_index` 的 `sorted(nodes)` 混型键 TypeError 整库打不开（修复轮探针实测）；②`propose(None)` 抛裸 TypeError 非 ValueError（`md_cg/mdcos.py:1770` 附近，不产生 None.md，未动）。建议入池，见第六节。
5. 工作区内 mdcos.py/review_cli.py 等另有并行改动（P1/P1b 修复员所为），未触碰；未 git commit（编排会话负责）。

**验证**（修复轮实跑）：
1. 红态：`python -X utf8 -m md_cg.test_none_id_write_guard` → 9 通过/7 失败 exit 1（[1][2][5] 污染形态红，[3][4][6] 防误杀/既有语义/取证面绿）。
2. 绿态：同命令 → 17 通过/0 失败 exit 0。本会话重跑一致（EXIT=0）。
3. 回归：`test_security_audit` 13/0；`test_security_audit_v21` 49/0；`test_session_isolation` 19/0。
4. 全量：`python scripts/run_tests.py --jobs 4` → 「SUMMARY 213/213 通过，5 跳过（依赖缺失/平台不符）」exit 0，且 `_discover()` 列表（218 件）含 `md_cg.test_none_id_write_guard`。
5. 取证：grep 写入路径构造点（`_node_disk_path`、add path 派生、`_scan_nodes`、writepipe execute/executor）+ `git show 2a57c2a2^:md_cg/mdcg.py` + 临时库探针（add 13 种 None-ish 调用形态枚举，仅 `add("None")` 复现 None.md）；探针与守卫临时目录均已删除，未触真实令牌库/真实在役数据。

---

## 三、跨进程可见性红转绿证据（P1b）

**红态**（修复前，`python -X utf8 -m md_cg.test_review_cli_visibility`）：PASS=5 FAIL=5。

关键红项③的契约：进程 A' 经生产构造 `_cg` 调库裸 add 2 条后 `os._exit(0)`（模拟被杀，close/atexit 均不执行），退出后盘面 `_index_log/` 必须已含全部写入记录。修复前 `log_ids=[]`——缺省 `autoflush=64`（`md_cg/mdcg.py:922`）未达阈值，分片日志从未落；此时另一进程 B 重开读面（`_load_index`=快照+日志重放，`md_cg/mdcg.py:948-975`）自然读不到这两条，即 DSH 在役 read null 的机理。

**绿态**（修复后）：PASS=10 FAIL=0。本报告撰写会话重跑实测输出（节选）：

```
【①③】… 进程 B 读回业务节点 vis-acc-node 可见 · READ 1
  进程 B 侧审计记录节点可见（review_records 命中 1 条）
【②③】进程 A' 调库落 2 条即 os._exit（模拟被杀）→ 落账契约 + 进程 B 读
  [PASS] 进程 A' 经生产构造 _cg（autoflush=1 回显） · staged=0 autoflush=1
  [PASS] ③ 落账契约：A' 被杀退出后 _index_log 已含全部 2 条写入记录
         · log_ids=['vis-node-1', 'vis-node-2']
  [PASS] ② 进程 B 读回 kill 形态的两条节点均可见 · READ 1 1
【④】同病工具面 autoflush=1
  [PASS] review_cli._cg 构造 autoflush==1 · 1
  [PASS] evidence._open_cg 构造 autoflush==1 · 1
  [PASS] scripts/linkref_backfill.py 构造语句带 autoflush=1（源级断言）
  [PASS] scripts/migrate_restricted.py 构造语句带 autoflush=1（源级断言）
================================================================
PASS=10  FAIL=0   EXIT=0
```

**证据链要点**：
- 红转绿的唯一变量是四处构造的 `autoflush=1`（写入侧落账时机），读面 `_load_index` 重放逻辑一行未改——同一读面在红态读不到、绿态读到，证明缺陷在写入面，与定性一致。
- ①②读面断言修复前后均绿：正常退出路径在本仓 HEAD 已有三层既有兜底（mdcos review_decide 显式 flush :2258/:2309/:2330；review_cli finally `cg.close()` :204-211；库层 atexit `mdcg.py:104-118`）；kill 形态重开读面另有批次 39 指纹失配→全扫自愈（`mdcg.py:959-970`）。DSH 在役实测命中的是**旧读面（0.4.x 无指纹校验）×旧写入面（无 autoflush）**叠加，两层兜底均晚于其在役版本。①②保留为回归钉。
- 时间线佐证：17699ec5（2026-09-16，server 级 autoflush=1）早于 9102df88（批次 39，2026-09-25，指纹自愈），故在役 0.4.x 两侧皆旧。

---

## 四、门禁

编排会话门禁执行记录（本报告撰写会话**未重跑门禁全套**，如实注明）：

| 门禁项 | 结果 |
|---|---|
| python 全量测试 | 通过（退出码 0） |
| 注入套件 | 18/18，与登记一致（EXIT=0） |
| gate | 1 |

**本报告撰写会话抽验（本会话实跑，均 EXIT=0）**：

| 命令 | 结果 |
|---|---|
| `python -X utf8 -m md_cg.test_review_cli_visibility` | PASS=10 FAIL=0 |
| `python -X utf8 -m md_cg.test_review_cli_attribution` | PASS=10 FAIL=0 |
| `python -X utf8 -m md_cg.test_none_id_write_guard` | 17 通过 / 0 失败 |
| `python -X utf8 -m py_compile`（11 件：7 改动面 + 3 新守卫 + `scripts/_mdcg_reindex_code.py`） | COMPILE_OK |

---

## 五、回告 DSH 端复验清单（复现步骤+预期）

**通用前置**：拉取含本轮修复的 md_cg 构建（三项修复均在本仓未提交工作区，随编排会话提交/发布后生效；在役 0.4.x 副本不含 09-16 autoflush 与批次 39 指纹自愈，须升级方可复验）；复验一律临时库 + 哑密钥，勿触在役数据。

**P1b（跨进程可见性）**
- 步骤 A（守卫）：`python -X utf8 -m md_cg.test_review_cli_visibility`。
  预期：PASS=10 FAIL=0，退出码 0；③项 `log_ids=['vis-node-1','vis-node-2']`。
- 步骤 B（手工复现）：进程 A 以生产构造（review_cli accept 或 `_cg` 裸 add）写入 2 条后立即 `os._exit(0)` 模拟被杀；随后检查 `<root>/_index_log/`。
  预期：A' 退出后分片日志立即含全部 2 条写入记录；进程 B 全新进程 `_load_index`+read 可见业务节点与审计记录节点。

**P1（裁决归因）**
- 步骤 A（守卫）：`python -X utf8 -m md_cg.test_review_cli_attribution`。
  预期：PASS=10 FAIL=0，退出码 0。
- 步骤 B（端到端）：以身份 X（如 dsh-memory）propose 一条 → `python -m md_cg.review_cli accept <pid> --session <同一会话id> --reason "…"`（裁决者 designer-cli）。
  预期：退出码 0；落盘节点 `frontmatter.session==<传入值>`、`writer==X`（原始写入者在位）、`reviewer=="designer-cli"`；同一 `--session` 再裁一条，两节点 session 一致。
- 步骤 C（兼容性）：不传 `--session` 亦不设 `MDCG_SESSION` 裁决一条。
  预期：stderr 恰一行随机会话告警、退出码 0、落 `sess_*` 随机值、writer 归因同样在位（不阻断）。
- **P1-1 环境侧核对（回告项）**：核对 DSH 会话目录真实存在于 `MDCG_DSH_SESSIONS_ROOT` 或 `~/.dsh/sessions` 之下。预期：目录在位后，MCP 写入面 `_normalize_session`（`md_cg/mcp_server.py:3381-3405`）不再将该会话降级 anonymous，MCP 面与 CLI 面归因一致；目录不在位时 MCP 面降级 anonymous 属既有防编造设计，CLI 侧（直构 Principal 不经该校验）不受影响，但两侧归因会对不上——需环境侧保证目录在位。

**P3（None.md 脏节点）**
- 步骤 A（守卫）：`python -X utf8 -m md_cg.test_none_id_write_guard`。
  预期：17 通过 / 0 失败，退出码 0。
- 步骤 B（写入拒绝）：修复版库 `add("None", …)` / `add("null", …)`。
  预期：ValueError（消息点名字符串化污染形态与 P3），盘面无 None.md/null.md，索引无该条目；`add("NoneBot_1")`/`add("nullify_test")` 等子串 id 不受影响。
- 步骤 C（存量清理，DSH 端自执，本轮未代执）：核对 `<root>/knowledge/orphan/None.md` 是否存在；存在则删除该文件后 `rebuild_index()`。
  预期：id="None" 从索引、检索结果与 route 候选消失（守卫 [6] 实证该路径）。**勿用 `add("None")` 覆写清理（修后被拒）。**

---

## 六、遗留

1. **读路径自愈长效兜底与升级要求**：批次 39（9102df88，2026-09-25）`_load_index` 指纹失配→全扫自愈（`md_cg/mdcg.py:959-970`）已在库层兜住 kill 形态重开读面；但 0.4.x 旧副本读面盲信快照无指纹校验——DSH 侧**必须升级构建**才能同时获得旧读面自愈与本轮写入面兜底，升级列为第五节复验前置。
2. **P1b 读面断言①②为回归钉**：正常路径与 kill 重开路径的既有兜底（显式 flush / close / atexit / 指纹自愈）若未来被移除，守卫即红。
3. **P3 相邻发现未修**（如实，建议入池）：`add(123)` 等非字符串真值 id 混型索引键可致重开 `_load_index` 的 `sorted(nodes)` TypeError 整库打不开（修复轮探针实测）；`propose(None)` 抛裸 TypeError 非 ValueError（`md_cg/mdcos.py:1770` 附近，无脏文件产生）。
4. **P4/P5 入池**：编排决策不入本轮；定性细节本轮材料未含，本报告不作描述（不虚构）。
5. **存量 None.md 清理在 DSH 真实库的执行**由 DSH 端自执（本轮未代执、未触真实库），路径见第五节 P3 步骤 C。
6. **批式工具 autoflush 取舍**：`scripts/_mdcg_reindex_code.py` 维持 `autoflush=64`（:62）+ 显式 `cg.close()`（:128）——读码判定后的刻意不动（批式数千条逐条落日志无收益，:128 close 即确定性提交边界），非遗漏。
7. **本报告会话未重跑项**：门禁全套（python 全量/注入套件/gate，编排会话执行记录见第四节）、组全量与定向回归套件（修复轮实跑记录见第二节各验证栏）、孪生件端到端（修复轮实跑，本会话仅复核同步点源码在位）。以上均为如实申报，未以本会话名义重报为已跑。

---

## 七、纪律合规声明

1. **实验环境**：全程系统临时目录 + 哑主密钥（`MDCG_MASTER_KEY=ab*32`）；未触真实令牌库、真实 serve、真实在役数据目录。
2. **清理**：修复轮实验残留（`mdcg_p1b_exp`、`clivis_*`、`cliattrib_*`、`twin_attr_*`、`mdcg_conf_*` 及 P3 探针/守卫临时目录）均已清理，复查余量 0。
3. **提交纪律**：未 git commit（编排会话负责）；工作区未提交改动即本轮修复落点（7 修改 + 3 新守卫，见前言基线）。
4. **引证纪律**：结论均带 `path:line`；验证结果区分「修复轮实跑（材料记录）」与「本报告会话实跑（第四节抽验）」；未跑项如实标注（第六节第 7 条），无以未跑充已跑之处。
5. **路径表述**：本报告不写本机绝对路径，实验目录一律以「系统临时目录下 …」表述。
6. **无法满足项如实列出**：P4/P5 定性细节本轮材料未提供，总览矩阵与遗留仅记「入池」，不作内容描述；材料个别行号与当前工作区实测有漂移（如 review_decide 显式 flush 实测在 `mdcos.py:2258/2309/2330` 而非材料所记 2248/2299/2320），报告已全部按本会话实测修正，未沿用漂移值。

---

### 附：自查双清单

**清单一：结论引证自查（关键结论 → 引证 → 验证方式）**

| 结论 | 引证 | 验证方式 |
|---|---|---|
| P1b 四处落点 `autoflush=1` | `md_cg/review_cli.py:106`、`md_cg/evidence.py:512`、`scripts/linkref_backfill.py:198`、`scripts/migrate_restricted.py:46` | 本会话逐处读码在位 |
| 缺省 autoflush=64、atexit 仅正常退出 | `md_cg/mdcg.py:922`、`mdcg.py:104-118` | 本会话读码 |
| `_stage` 阈值落账 / flush 幂等落分片日志 | `md_cg/mdcg.py:2079-2087`、`mdcg.py:1079-1098` | 本会话读码 |
| `_load_index` 快照+重放、指纹失配全扫自愈 | `md_cg/mdcg.py:948-975`（:959-970） | 本会话读码 |
| P1 三归因改造点 | `md_cg/review_cli.py:31-44/75-80/83-106/175-178`、`md_cg/mdcos.py:2240-2249`、propose actor 快照 `md_cg/mdcos.py:1770` | 本会话读码 |
| P1-1 校验面 | `md_cg/mcp_server.py:3381-3405`（:3397 目录根） | 本会话读码 |
| P3 写入边界闸 | `md_cg/mdcg.py:909-916`、`mdcg.py:1322-1326` | 本会话读码 |
| route op 即 cg.search | `md_cg/mcp_server.py:2117-2119` | 本会话读码 |
| reindex 工具刻意不动 | `scripts/_mdcg_reindex_code.py:62/:128` | 本会话读码 |
| 孪生件同步 | `scripts/review_cli.py:66/:153` 等 | 本会话读码 |
| 三守卫全绿 | 第四节抽验表 | 本会话实跑（EXIT=0） |
| 11 件 py_compile | 第四节抽验表 | 本会话实跑（COMPILE_OK） |
| 门禁三项、组全量、定向回归、孪生端到端、红态 5/5 与 9/7 | 第二节各「验证」栏、第四节门禁表 | 修复轮/编排实跑记录（材料），本会话未重跑 |

**清单二：未实跑/未尽事项申报**

- 门禁全套（python 全量、注入套件 18/18、gate=1）：编排会话执行，本会话未重跑——按记录转述，未冒充本会话结果。
- 全量 213/213、组全量 159/159、定向回归 12 套、孪生件端到端、红态（PASS=5 FAIL=5 / PASS=2 FAIL=8 / 9 通过 7 失败）：修复轮实跑（材料记录），本会话未重跑红态（绿态三守卫已重跑）。
- 存量 None.md 真实库清理：未代执（DSH 端自执）。
- P4/P5：无定性材料，未描述。
- P3 相邻两项（混型索引键 TypeError、propose(None) 裸 TypeError）：未修，已申报入池建议。
- 材料行号校勘：`_stage` 2066-2073→实测 2079-2087；flush 1070-1089→实测 1079-1098；`_load_index`/指纹自愈 939-973/958-961→实测 948-975/959-970；autoflush 缺省 913→实测 922；atexit 104-119→实测 104-118；review_decide 显式 flush 2248/2299/2320→实测 2258/2309/2330；review_cli finally close「196 区」→实测 204-211；argparse --session 165-168→实测 175-178。其余引证与实测一致。

---

*报告撰写会话（报告员）2026-09-26 · 全部抽验命令与输出见第四节；材料与实跑来源已在正文逐处标注。*
