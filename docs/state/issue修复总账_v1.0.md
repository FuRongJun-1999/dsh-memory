# issue 修复总账 v1.0

> 生成：2026-10-18 · 输出单元（只读汇总，不改生产码）
> 范围：本轮 19 个单元（U02–U21，U05 未出现在材料）的 21 份结果与复核（U18/U20 各两轮），以及维生巡检、总体方案。
> 材料：各单元 `result/review`、维生巡检、`总体方案`、`.tmp/issues_open.json`（47 件，快照 2026-10-17 11:18:33）、共享派工书 `.tmp/WORKFLOW_BRIEF.md`。
> 现场：分支 `main`；输出时 `git log --oneline --graph` 显示 HEAD 已到 `1a528ea5`（会话起始快照为 `e81caab0`，期间前进一笔）。工作树含多单元未提交成品；关键风险见 §5.1。
> 口径：**判定列＝单元快照判定**；**归属列＝输出单元对 git/grep/源码的定点核验**；**守卫读数＝单元/复核实跑的材料读数，输出单元未复跑任何守卫**（见 §5.2）。

---

## 一、结论（三句话内）

按单元快照去重，**42 件开放 issue** 的判定为：**26 fixed、6 duplicate、4 件多站点部分修复（#426/#446/#352/#492）、5 件整件 blocked（#447/#278/#443/#522/#424）、1 件 intake（#354：17 条中 7 修/9 duplicate/1 deferred）**；另有 #471 已在开放快照外（已关闭），单元复核判 duplicate（`e3f5e6f6`），未纳入本批的 5 件为 #463（R0 他线已修待核销）与 #437/#428/#423/#111（证据类）。deferred 子项 2 条（#426-A、#354 P2-16），无整件 deferred。上述均为单元/复核材料读数，本输出单元未复跑守卫；采信前须先处置 §5.1 的 **HEAD `e81caab0`(#899) 回退面**，否则多件 fixed 不能当作当前 HEAD 的事实。

---

## 二、逐单元总表

> 判定口径：`fixed`=复现→修→守卫→变异自证全过（单元口径）；`duplicate`=当前 main 已被既有修复覆盖；`deferred`=设计/性能裁定；`blocked`=环境/权限/缺前置。  
> “读数”列均为**材料读数**；`--mutate` 红项为单元/复核打印的指定项。`未核`＝输出单元没有独立复跑或没有找到可核的提交/符号。  
> 多站点 issue（#426/#446/#352/#492）的**整体合成状态**见 §2.3；本表每行保留该单元对该分面的原始 verdict，只有标“部分修复”的行是合成判定。

### 2.1 主表

| 单元 | issue | 判定（单元/合成） | 归属（可核） | 根因（类） | 改动文件 | 守卫 | 读数（材料） | 变异红项 | 复核 |
|---|---|---|---|---|---|---|---|---|---|
| U02 | #498 | fixed | 本端：`md_cg/twophase.py`；已入库 `19b7b86e`（HEAD 祖先，`_merge_target` 8 处） | C09：`_merge_target` 只遍历 `cg.index["nodes"]`（派生物），缺“索引 miss 回盘面” | `md_cg/twophase.py` | `md_cg/test_issue498_merge_trace_stale_index.py` | 12 PASS/0 FAIL，rc=0 | M1→A03/A04/A05；M2→B01 | approved；A06 端到端可能被 `_snapshot_trusted` 指纹回落救回，判别力在 A01–A05 |
| U02 | #425 | fixed | 本端：`md_cg/sources.py`；已入库 `19b7b86e`（`library_ingest_guard` 5 处） | C03：摄取只判 path 非空；库根/trash/层目录被当外部文档重切，节点密级只看路径段 | `md_cg/sources.py` | `md_cg/test_issue425_ingest_library_path.py` | 15 PASS/0 FAIL，rc=0 | M1→A2/A3/C01；M2→A1/C01；M3→B1 | approved；A5/B2 由 #346 覆写闸兜住，如实打印不作判据 |
| U02 | #452 | fixed | 本端：`md_cg/sources.py`；已入库 `19b7b86e`（`source_sensitivity` 7 处） | C05：`item["path"]` 相对被摄取根，根段被 relpath 抹掉；源 frontmatter 不参与判据 | `md_cg/sources.py` | `md_cg/test_issue452_ingest_root_sensitivity.py` | 12 PASS/0 FAIL，rc=0 | M1 4/4；M2 4/4；M3 1/1 | approved；`item["path"]`/`doc_ref.path` 仍相对，节点 id 不变 |
| U02 | #426（B 面） | duplicate | 单元判 duplicate（`1c990e9e` #346 覆写闸）；`5be2fd1e` root_clash 修复在 git 历史可见；当前 `refindex.py` 被 #899 改动，存活**未核** | C04：`root_clash` 用受 clearance 过滤的 `cg.get`，看不见即判无冲突 | 无（单元未改） | `md_cg/test_issue346_overwrite_sensitivity_gate.py` | 16 PASS/0 FAIL，rc=0 | 无（duplicate） | approved；单元 residual 5 记“冲突回执半面未做” |
| U03 | #446 | **blocked（站点2）** | 部分：站点1/3 由 `7cfa8029` 覆盖；站点2 **当前仍未修**——`md_cg/mdcos.py:5949` 的 `_seal_content` 与 `md_cg/mdcg.py:1778` 落盘闸仍用 `crypto.is_encrypted`，而 `crypto.is_encrypted` 仍是前缀判定（`md_cg/crypto.py:519-520`） | C07：前缀候选同时充当密封短路/落盘闸；真判据应为 `verify_encrypted` | 未改（授权外：`md_cg/mdcos.py`、`md_cg/mdcg.py`） | `md_cg/test_issue446_453_403_verified_evidence.py` | 35 PASS/0 FAIL，rc=0 | M1a→A1/A6/E2；M1b→A4；M2→A6/E3 | approved；blocked 理由成立；他线 PR `010e8fbb/6c6773ba/901460f2` 未入 HEAD |
| U03 | #453 | fixed | 本端：`md_cg/evidence.py`；已入库 `7cfa8029`（随动 `f78adbbd`；`_signer_declaration_rejected` 2 处） | C08：空签名按对端声明豁免；`created_at` 当版本号且无上界 | `md_cg/evidence.py` | 同上 | 35 PASS/0 FAIL，rc=0 | M3→A2/A2b3/A2b4/A2c/A9a–d；M5→A7/A7b；M7→A9a–d | approved；无签名包不再可导入；test_issue147 夹具已补真签 |
| U03 | #403 | fixed | 本端：`md_cg/evidence.py`；已入库 `7cfa8029`（`_local_generation_blocks` 3 处） | C09：判据读本进程索引，代际探活在判据之后；`updated_at` 不在索引 | `md_cg/evidence.py` | 同上 | 35 PASS/0 FAIL，rc=0 | M4→A5/A5b/A8；M6→A8/E7 | approved；A5 表已去掉不存在的 `updated_at` 比较 |
| U04 | #445 | fixed | 本端：`md_cg/metacognition.py`（**工作树未提交**；`_reflections` HEAD 8/WT 12）；守卫 `md_cg/test_issue445_metacognition_ledger_gate.py` 未跟踪 | C12：台账无唯一读取点，各消费面各自 `read_jsonl`，无身份判据 | `md_cg/metacognition.py` | `md_cg/test_issue445_metacognition_ledger_gate.py` | 24 PASS/0 FAIL，rc=0 | M1 7；M2 10；M3 2；M4 5；M5 1 | approved；第四读面 `autonomy.proposals` 已关闭；非设计者反思派生面退化为空（刻意取向） |
| U04 | #447 | **blocked** | 未修：当前 `md_cg/mdcos.py:6542/6546` 仍 `m.get("sensitivity") or DEFAULT_SENSITIVITY`；`_recent_effective_sens` 在 HEAD/WT 均 0 次；他线历史 `9abb0f2c` 被 `e81caab0` 回退 | C10：缺 sensitivity 键 fail-open 降 internal；`_rank(internal) < private` 连带跳过会话绑定 | 未改（授权外：`md_cg/mdcos.py`） | 无（guard_rc=1） | — | — | approved（blocked 理由成立）；需重放/合并 |
| U04 | #471 | duplicate | 他线：`e3f5e6f6`；守卫 `md_cg/test_issue471_identity_readable.py` 10/0；该 issue 已不在开放快照 | C12 同族：identity 三处读面缺可见性判据 | 无（他线） | `md_cg/test_issue471_identity_readable.py` | 10 PASS/0 FAIL，rc=0 | 无 `--mutate`（内建 A'-1/A'-2 对照） | approved；如实登记无变异腿 |
| U04 | #426（D/F 面） | fixed（分面） | 本端：D=`md_cg/metacognition.py`、F=`md_cg/datapath.py`（**工作树未提交**，`datapath.py` M +24） | C12（D：台账读面无身份判据）；C33（F：`_abs_host_path` 不判 U+FFFD 编码失真） | `md_cg/metacognition.py`、`md_cg/datapath.py` | `md_cg/test_issue426f_paths_gbk_failclosed.py` | 10 PASS/0 FAIL，rc=0 | M1→B1/B2/B3/E1/E2/F1/F2 | approved；插件侧 `src/lib/datapath.ts` 仍宽松解码，NEED_FILE |
| U06 | #322 | fixed（产品） | 本端：`md_cg/fsutil.py`、`md_cg/mdcos.py`；已入库 `13bdc99f`/`940c7a69`（`node_write_lock` 1 处、`with node_write_lock` 3 处） | C13：同 id 写链无跨进程互斥；`_move_layer` 直调 `_write_node`；`_write_sensitivity` 读陈旧索引 | `md_cg/fsutil.py`、`md_cg/mdcos.py` | `md_cg/test_issue322_node_write_lock.py` | 18 PASS/0 FAIL，rc=0 | M1→E0b/A1b/A1c/E3；M2→E0c/A3/A4/E4；M3→A5/E5；M3b→A5（**不稳定**）；M4→A4/E6 | **approved=false**：M3b 1/7 假绿（worker 在 t0 前构造实例）；产品修复成立，守卫待 ready 握手 |
| U06 | #348 | fixed | 本端：`md_cg/fsutil.py`、`md_cg/mdcos.py`；已入库 `940c7a69`（`merge_rmw_lock` 11 处） | C13：MERGE/CONVERGE 读改写无跨进程锁，后写吞前写 | 同上 | `md_cg/test_issue348_merge_rmw_lock.py` | 11 PASS/0 FAIL，rc=0 | M1→A1b/A2/E3a/E3d；M2→E3d/E4 | U06 总复核 approved=false（因 #322 M3b）；#348 的 M1/M2 稳定、单独通过；父类 `MdCG._move_layer` 仍无锁（NEED_FILE `md_cg/mdcg.py`） |
| U07 | #362 | duplicate | 他线：`53967111`（a/b/d）；守卫 `md_cg/test_issue362_neg_condition.py` 36/0；c 未修（#523），d 为独立小项 | 条件路由：否定作用域/字符归一/边界词；`#362c` 繁简表缺失 | 无（他线） | `md_cg/test_issue362_neg_condition.py` | 36 PASS/0 FAIL，rc=0 | M1–M9 全命中（集合见单元表） | approved；duplicate 只覆盖 a/b/d |
| U07 | #278 | **blocked** | 未修：`c6d00c07` 去 L1 覆盖率闸后“负条件抄正文片段”漏拒；落点 `md_cg/consolidate.py` 与两个 278 守卫在授权外 | C29：判据与 REFLECT_PROMPT“邻近易混”互斥；词面覆盖率无法区分“抄正文”与“邻近易混” | 无（未改） | 无（guard_rc=1） | — | V1/V3 ANCHOR-MISS；V2 红 8 | approved（blocked 理由成立）；需 owner 裁定语义/条件空间口径 |
| U08 | #434 | fixed | 本端：`compiler/compiler.py`；已入库 `51f72ff9`（`_finite_operand` 7 处） | C21：ZHIZU 分支裸 `float(val)`，无 try；DE 分支有 try | `compiler/compiler.py` | `compiler/tests/test_issue434_zhizu_operand.py` | rc=0 | A01/A02/A03 | approved |
| U08 | #435 | fixed | 本端：`compiler/compiler.py`、`compiler/condition_vm.py`；已入库 `51f72ff9`（`is_finite_number` 10 处） | C21：inf/nan 过“必须是数值”闸；运行期 `isinstance` 不判有限性 | 同上 | `compiler/tests/test_issue435_finite_trust.py` | rc=0 | B01/B04/B06/B08/B10/B12–B16；A 德 inf/nan、A 知足 inf | approved；B12–B18 补大整数/OverflowError |
| U08 | #402 | fixed（主面） | 本端：`compiler/pbc.py`；已入库 `51f72ff9`（`_need` 16 处） | C20：反序列化无长度判据；切片静默截短、越界抛裸异常 | `compiler/pbc.py` | `compiler/tests/test_issue402_pbc_truncation.py` | rc=0 | A03/A01/B02 | approved；残余：指令边界 11 个静默点物理不可判；CLI/Rust/白箱未同步；v2 头 PR `90d76b8f` 未入 HEAD |
| U08 | #436 | fixed | 本端：`compiler/lexer.py`；已入库 `51f72ff9` | C22：未闭合字符串吞换行、不推进行号 | `compiler/lexer.py` | `compiler/tests/test_issue436_unterminated_string.py` | rc=0 | A01/A06/B01 | approved；K06 钉 STRING 列号与 HEAD 一致 |
| U09 | #427 | fixed | 本端：`hive/serve_start.py`；已入库 `b4d3d513` | C23：`json.load(f).get` 对非映射抛 AttributeError；except 只捕 `(OSError, ValueError)` | `hive/serve_start.py` | `md_cg/test_issue427_serve_status_shape.py` | 12 PASS/0 FAIL，rc=0 | M1→A01/A01b/A02/A02b/A03/A03b/A04/A04b/K04；M2→K01/K03/K04 | approved；低危：不可哈希 `state` 仍 TypeError；守卫变异分支不被元守卫 AST 识别 |
| U09 | #511 | fixed | 本端：`hive/scoreboard.py`；已入库 `b4d3d513` | C24：`read_json` docstring 的 `bad_files` 出口不存在；非映射与缺失不可分 | `hive/scoreboard.py` | `md_cg/test_issue511_scoreboard_bad_files.py` | 16 PASS/0 FAIL，rc=0 | M1→A01/A02/A03/A04/A06；M2→A05/A06/A07/K02；M3→A05/A06/A07/K02/K03 | approved；`_file_shape` 二次读盘竞态；`read_json` 返回契约变为哨兵 |
| U10 | #429 | fixed | 本端：`md_cg/test_issue93_remember_redaction.py`、`md_cg/test_issue91_verifier_sandbox.py`、`scripts/check_guard_coverage.py`；已入库 `20c3ea26` | C28：守卫无回退自证腿；#93 G2 只找字样；#91 G1 无 cases | 上述三件 | 两守卫 `--mutate` + `check_guard_coverage.py` | 93 9/0、`--mutate` 红 G5/G6；91 11/0、`--mutate` 红 G1/G7/G8；coverage rc=0、selftest rc=0、配对 15/0 | G5/G6/G1/G7/G8 | approved；整份删除/文档字样/AST 判据/自动链均已补 |
| U10 | #438 | fixed | 本端：`md_cg/test_issue398_toolface_op_parity.py`；已入库 `20c3ea26` | C27：main 双 return，收尾块在 `sys.exit` 后成死代码，每次泄漏临时目录 | 该守卫 | `md_cg/test_issue398_toolface_op_parity.py` | rc=0；S01/S02 PASS | M1–M5 全命中；M5→S01/S02 | approved；临时目录 0 增量；成本默认 0.3s/变异 5.5s |
| U11 | #363 | fixed | 本端：`md_cg/mdcg.py`、`md_cg/test_issue363_lexical_idf.py`、`md_cg/test_retr_s5.py`；已入库 `940c7a69`/`da018cec`（`idf_of` 2 处） | C17：缺省 lexical 只有 `abs(q∩d)/abs(q)`，无 IDF，同分退化写入序 | 上述三件 | `md_cg/test_issue363_lexical_idf.py` | 22/0、`--mutate` 26/0 | M1/M2/M3→A1/A2/A3（M2 另 K5） | approved；probe 41/41→1/41；locomo-zh-500 hit@1 96.8→98.2；Rust legacy 未同步 |
| U11 | #370 | duplicate | 他线：`5d991430`；守卫 `md_cg/test_issue370_readcache_assembly.py` 19/0；`install_default` 2 处 | 性能：readcache 只在 MdCGOS 装配，基类 MdCG 无缓存 | 无（他线） | 该守卫 | 19 PASS/0 FAIL，rc=0 | 未跑（duplicate） | approved |
| U12 | #222 | fixed | 本端：`package.json`、`src/tools.ts`、`src/hooks.ts`；已入库 `f8e15305` | C30：schemastery 被入口静态导入却在 optional peer；无 dependencies 段 | 上述三件 | `test/issue222_optional_peer.test.ts` | 2/2 rc=0 | M1→6 项；M2→src:static:dsh-tools；M3→src:static:dsh-session/dsh-system-prompt | approved；真实 npm pack/install 复验 |
| U12 | #224 | fixed | 本端：`src/lib/token_store.ts`、`src/lib/mdcg_client.ts`、`src/index.ts`、`src/bridge.ts`；已入库 `f8e15305` | C31：租户/aux/令牌库三处各算一遍；密钥环无条件复用 | 上述四件 | `test/issue224_token_store_bind.test.ts` | 1/1 rc=0 | M1–M9 全命中 | approved；相对 `MDCG_AUX_ROOT` 仍分叉（review finding）；`~user` 保留字面量 |
| U12 | #386 | fixed | 本端：`src/lib/datapath.ts`；已入库 `f8e15305`（`expandHome` 6 处） | C32：四个 env 入口各自 `resolve()`，`~` 未展开 | `src/lib/datapath.ts` | `test/issue386_tilde_expand.test.ts` | 2/2 rc=0 | A 11 项；B 2；C 1；D 4 | approved；`~user` 按 PR #385 保留字面量 |
| U13 | #443 | **blocked** | 未修：五个台账落点在授权外（`md_cg/fsutil.py` 的 `append_jsonl`、`md_cg/imgskill.py`、`md_cg/state_events.py`） | C25：长度闸只在 `writepipe.oversize_response`；六台账 5/6 无轮转 | 无（未改） | 无（guard_rc=1） | — | — | approved（blocked 理由成立）；probe 5/5 amplified |
| U13 | #521 | duplicate | 他线：`c455cc9d`（+`798dc03e`）；守卫 `md_cg/test_issue521_rotate_lock_suffix.py` 6/0；`rotate.py:lock_path` 3 处 | C26：锁名后缀拼接职责重叠，产生 `.rotate.lock.lock` | 无（他线） | 该守卫 | 6 PASS/0 FAIL，rc=0 | A1/A2（用 monkeypatch 复现；守卫 `--mutate` 未分派） | approved；如实登记 `--mutate` 名存实亡 |
| U13 | #522 | **blocked** | 未修：当前 `md_cg/mdcos.py:3076-3078` 仍 `extra["sensitivity"]=principal.clearance`；他线 PR `77138822` 未入 HEAD | C06：审计件密级取裁决者 clearance，外部复核面失效 | 未改（`md_cg/mdcos.py` 他线占用） | 无（guard_rc=1） | — | — | approved（blocked 理由成立）；probe private 口径 `node_not_found` |
| U14 | #470 | fixed | 本端：`swarm/rust_runtime/src/swarm.rs`（**工作树未提交**；`sync_data` HEAD 0/WT 5） | C14：`open_wal_for_run` 返回 `File`，`File::flush` 是 no-op；事件行只等轮末 `sync_all` | `swarm/rust_runtime/src/swarm.rs` | `md_cg/test_issue470_wal_event_durable.py` | 13 PASS/0 FAIL，rc=0 | V1→A1c/B1/B2；V2→A1a/A1c/B3；V3→B1b | approved；cargo 真编译/真二进制 |
| U14 | #72 | fixed | 本端：`md_cg/coldverify.py`；已入库 `a41bcba9`（`controlled_drain` 4 处） | 条件层：只有 drain/status，缺权限+限量+审计+失败重入队单点 | `md_cg/coldverify.py` | `md_cg/test_issue72_coldverify_controlled_drain.py` | 27 PASS/0 FAIL，rc=0 | M1→G1a/G1b/B1；M2→G4/B2；M3→G5b/G5c/B3；M4→G6a/G6d/B4 | approved；MCP/CLI 接线与可选阈值项未做；`drain()` 仍是无闸公开方法 |
| U14 | #426（A 面） | deferred | 未修：`md_cg/mdcos.py:2628` `phash=dedup_key or _sig(content)`；:2649-2655 命中 accepted/rejected 即 break；他线 `0828e022` 仅回执归因、未入 HEAD | C16：幂等键缺代际；删除/改回旧值撞已裁决单 | 未改（授权外：`md_cg/mdcos.py`、`md_cg/mcp_server.py`） | 无（未新增） | — | — | approved（deferred 理由成立） |
| U15 | #491 | fixed | 本端：`md_cg/whitebox_kb/wisdom/code_compose.py`、`md_cg/whitebox_kb/wisdom/verifier.py`；已入库 `71d5dc34`（`run_guarded` 9/3 处） | C19：`verify_code` 同进程裸 exec，无受限命名空间/超时 | 上述两件 | `md_cg/test_issue491_compose_sandbox.py` | 9 PASS/0 FAIL，rc=0 | M1→S1/S2；M2→S1/S3；M3→S6；M4→S8；M5→S9 | approved；5 条 low：py_ref `call` 跳过语义漂移（705 单元零命中）、10 域单元收紧、T3b 抖动、residual 归因笔误 |
| U16 | #320 | duplicate | 他线：`620ed054` + `fbc0257d`；守卫 `md_cg/test_issue320_vstate_requires_verify.py` 14/0；`_require_verify_for_vstate` 2 处 | R0：参数面无裁决权判据；显式 verified 绕过 | 无（他线） | 该守卫 | 14 PASS/0 FAIL，rc=0 | V1→A1/A5/A6；V2→A1/A5/A6；V3→A5/A6；V4→A3 | approved；镜像基线缺 `data/policy.json`，V4 判别力被削弱；库层直调 `MdCG.add` 仍接受 verified（显式设计取舍） |
| U16 | #424 | **blocked** | 未修：当前 `md_cg/mdcos.py:4878` `_autonomy_gate_merge` 无 `sensitivity` 形参，:4926 仍 `kw.get("sensitivity")`；他线 `75c59ec2` 未生效 | C02：合并出单取声明密级/目标密级，不取源写入有效密级 | 未改（`md_cg/mdcos.py` 他线占用） | 无（guard_rc=1） | — | — | approved（blocked 理由成立）；probe accept 后目标含 private 串 |
| U16 | #450 | fixed | 本端：`md_cg/protect.py`；已入库 `4ecbe158`（`_resolve_target` 4 处） | C10：既有节点缺 sensitivity 键回落 internal；`_scan_nodes` 回填擦除缺键信号 | `md_cg/protect.py` | `md_cg/test_issue450_writegate_unknown_sens.py` | 13 PASS/0 FAIL，rc=0 | M1→A1/A2/F2；M2→K3；M3→A1/A2/F2 | approved；`_resolve_target` 也供 move layer，影响面更宽；旧守卫 docstring 陈旧 |
| U16 | #469 | duplicate | 他线：`7e06aaf8`（`_move_layer` `override` 8 处）；守卫 `md_cg/test_issue469_scrub_override_passthrough.py` 6/0 | C01：`_move_layer` 恒 `guard_move(override=False)`，上游 override 丢失 | 无（他线） | 该守卫 | 6 PASS/0 FAIL，rc=0 | 无 `--mutate`（手工回退验证 A1） | approved；`set_state` demote 段仍未传 override（生命周期语义待裁） |
| U17 | #326 | duplicate | 他线：`07b18cee`（五守卫：ingest/twin/vm/append/key）；复核更正读数 17/17/27/28/21 | R0/多缺陷：白名单入口不全、孪生漂移、O(depth²)、append 击穿、权限契约、无效形参 | 无（他线） | `md_cg/test_issue326_ingest_auto_whitelist.py`、`md_cg/test_issue326_twin_parser_parity.py`、`md_cg/test_issue326_vm_call_frame.py`、`md_cg/test_issue326_append_jsonl_oserror.py`、`md_cg/test_issue326_key_perms.py` | 17/17/27/28/21，均 0 失败；`--mutate` 除 append M1/M3 锚漂外全命中 | M1/M2 见单元表；append M1/M3 ANCHOR-MISS | approved；单元自报通过数偏高 1–3 项；icacls 未做；clearance 形参保留 |
| U18 | #352 A | duplicate | 他线：`ab0a8581`；守卫 `md_cg/test_issue352_rollback.py` 21/0（复核更正 23→21）；`drifted_since_execute` 4 处在 HEAD | A2：回滚只看执行前像，缺执行后代际探活；落盘无保护/留档/审计 | 无（他线） | 该守卫 | 21 PASS/0 FAIL，rc=0 | M1–M7 全命中 | approved；单元计数 23 是把两行读数算入 |
| U18 | #352 B | **部分修复** | 本端：`md_cg/mdcg.py`（**工作树未提交**；`_body_changed`/`_can_verify` 0→2/3）；守卫 `md_cg/test_issue352b_vstate_no_inherit.py` 未跟踪 | C15：同 id 改写默认继承验证态；缺省 confirm 档 accept 由审核者 principal 调 add | `md_cg/mdcg.py` | `md_cg/test_issue352b_vstate_no_inherit.py` | 15/0（复核更正 16→15）+5 锚点；`--mutate` 8 条全命中 | M1–M8 全命中 | **approved=false**：真实 stdio 复现“record 改写→designer accept→盘面仍 verified”；直写面修好，confirm 面未修 |
| U18 | #352 C | duplicate | 他线：`ab0a8581`；守卫 `md_cg/test_issue352_imgaudit.py` 10/0；`safe_join` 12 处在 HEAD | 本地信任边界：审计台账跟随符号链接 | 无（他线） | 该守卫 | 10 PASS/0 FAIL，rc=0 | M1 4/4、M2 1/1、M3 1/1、M4 2/2 | approved；C2 末段符号链接腿本机跳过（权限限制），E1 源码兜底 |
| U18 | #352 D | duplicate | 他线：`ab0a8581`；守卫 `md_cg/test_issue352_pathsjson.py` 15/0；`utf-8-sig` 在 HEAD | T8/A4：paths.json 解析失败静默回落默认根 | 无（他线） | 该守卫 | 15 PASS/0 FAIL，rc=0 | M1 3/3、M2 3/3、M3 2/2、M4 1/1、M5 2/2、M6 1/1、M7 1/1 | approved |
| U18 | #352 E | duplicate | 他线：`ab0a8581` + `16154f53`；守卫 `md_cg/test_issue352_refindex.py` 14/0 | 跨仓同 id：id 只哈希相对路径，水位按绝对路径 | 无（他线） | 该守卫 | 14 PASS/0 FAIL，rc=0 | 复核补跑 M1 5/5、M2 2/2、M3 2/2、M4 3/3、M5 3/3 | approved；当前 `refindex.py` 被 #899 改动，E 面存活**未核** |
| U19 | #492 | **部分修复** | 本端：`md_cg/writepipe.py`；已入库 `ef9a9cfb`（`include_dup_readout` 6 处）；守卫 `md_cg/test_issue492_dup_readout_opt_in.py` 工作树 M | C18：链尾观测读数无条件付全额成本；无消费者 | `md_cg/writepipe.py` | `md_cg/test_issue492_dup_readout_opt_in.py` | 14 PASS/0 FAIL，rc=0 | M1→A3/E1c；M2→A3/E1b/E1c/E3；M3→E2c | approved；**工具面 `md_cg/mcp_server.py:3924-3927` 仍无条件算**（NEED_FILE `md_cg/mcp_server.py`/`md_cg/protocol.py`）；成本判据是调用次数 |
| U20 | #354（17 条） | intake：7 fixed / 9 duplicate / 1 deferred | 见 §2.2 | T0/T8/A1/A3/A4/第9条（见 §3.1） | `src/lib/mutual.ts`、`src/hooks.ts`、`src/tools.ts`、`md_cg/writelimit.py`（**工作树未提交**） | 见 §2.2 | TS 18/0；writelimit 83/0、TOCTOU 14/0 | M1–M7；V1–V5；A2 | approved（第二轮）；Rust `--mutate` 未重跑；P2-16 deferred |
| U21 | #358 | fixed | 本端：`md_cg/forgetting.py`（**工作树未提交**；`candidate_total` HEAD 0/WT 15）；守卫未跟踪 | T0③（补充挂靠）：`MAX_COMPARE` 截断只存在于 break，返回体无 `candidate_total/truncated` | `md_cg/forgetting.py` | `md_cg/test_issue358_truncation_observable.py` | 17 PASS/0 FAIL，rc=0 | M1→A1a/A1b/A3a/A3b/A3c/A4/A5/A6b/A7；M2→A2a/A2b/A3d/A6a；M3→A1b/A3b/A4/A5/A6b/A7；M4→A3a/A3b | approved；#358② duplicate `a3c3530c`；`committed` 三键未补（独立协议形状） |
| U21 | #303 | fixed | 本端：`md_cg/mdcos.py`、`md_cg/mcp_server.py`（**工作树未提交**；`valid_node_id` HEAD 0/WT 4）；守卫未跟踪 | C34：读面把非法输入静默归一；k 越界无 warning；非法 id 与 not_found 共用 null | `md_cg/mdcos.py`、`md_cg/mcp_server.py` | `md_cg/test_issue303_design_boundaries.py` | 18 PASS/0 FAIL，rc=0 | M1 4 条非法 id；M2→O4a/O4c/O4d；M3→O4f；M4→O4a/O4c/O4d/O4f；M5→4 条非法 id+O5g/O5h | approved；`md_cg/protocol.py` 未登记 `invalid_node_id`（NEED_FILE）；`mdcg_remember` 不透传 content_kind |

### 2.2 #354 intake 17 条（U20 第二轮）

| 子项 | 判定 | 归属/覆盖 | 守卫与读数 | 变异 |
|---|---|---|---|---|
| P0-1 深嵌套 JSON 击穿 | duplicate | `#321`；`md_cg/test_issue321_mcp_deep_json.py` | 剔父 shell 令牌环境变量后 14/0；深嵌套行 rc=0、-32700 | V1/V2/V3 红项 5/3/1，指定命中 4/4、2/2、1/1 |
| P0-2 WAL 非法 UTF-8 清空历史 | duplicate | `5cd2b43f`；`md_cg/test_issue354_rust_wal_containment.py` | 33/0/0；W1 快照行幸存、W2 归档、W3 不误归档 | 本轮未重跑（duplicate 口径） |
| P0-3 路径穿越读盘 | duplicate | `5cd2b43f`；`md_cg/test_issue354_rust_index_containment.py` | 30/0/1 skip（符号链接权限限制）；越界条目零命中 | 本轮未重跑 |
| P1-4 combineVerdict fail-open | fixed | 本端 `src/lib/mutual.ts`（工作树未提交） | TS 守卫 18/0；M1 红 P1-4 有限数值项 | M1 |
| P1-5 信任内存 payload | fixed | 本端 `src/lib/mutual.ts`（工作树未提交） | 送审对象=盘上 claim；坏 JSON 抛错且不写 done | M2 |
| P1-6 WAL seq 单调/唯一 | duplicate | `5cd2b43f`；W4/W4b | `wal_continuity` 报告 `ok:false/breaks:1`；连续 WAL ok=true | 本轮未重跑 |
| P1-7 WAL 并发重写 | duplicate | `5cd2b43f`；W5/W6 | 锁被持有→非零退出、WAL 不动；双进程并发已提交前缀幸存 | 本轮未重跑 |
| P1-8 分片整文件解码 | duplicate | `5cd2b43f`；A6/A5/A7 | 坏行前后合法行仍重放；坏 `_index.json` 降级；两源俱好语义不变 | 本轮未重跑 |
| P1-9 `_load` 顶层类型 | duplicate | `05da7c5c`；`md_cg/test_issue354_p1_writelimit_type.py` | 83/0；数组/标量/字符串/null/bool 回落空台账 | V1 |
| P1-10 未来时间戳永久锁死 | duplicate | `05da7c5c`；同守卫 | 8 条未来戳不再 DEFER；全合法仍 DEFER | V2 |
| P1-11 时间戳类型 | duplicate | `05da7c5c`；同守卫 | str/None/dict/混装/bool/NaN/inf 全部不抛 | V3 |
| P1-12 role 不限长 | fixed | 本端 `src/hooks.ts`（工作树未提交） | 窗口载荷 ≤800，第二条正常历史仍注入 | M3 |
| P1-13 日志脱敏 | fixed | 本端 `src/hooks.ts`（工作树未提交） | warn 不含凭据原文、含脱敏标记；非 Error 拒绝值不抛 | M4/M7 |
| P1-14 注入面脱敏 | fixed | 本端 `src/hooks.ts`（工作树未提交） | auto-recall/session-window 均不含凭据原文；无凭据正文不误伤 | M5 |
| P2-15 spec 原型替换 | fixed | 本端 `src/tools.ts`（工作树未提交） | `Object.getPrototypeOf(spec)===null`；`__proto__`/`constructor` 为自有键 | M6 |
| P2-16 `CLOCK$` 保留名 | deferred | 转 U18/datapath 面；`md_cg/test_issue354_p2_datapath_clock.py` | 65/0；`RtlIsDosDeviceName_U` 实测 0、可建目录 ⇒ 报告主张不成立 | 无 |
| P2-17 writelimit 读改写 TOCTOU | fixed | 本端 `md_cg/writelimit.py`（工作树未提交） | `md_cg/test_issue354_p2_writelimit_toctou.py` 14/0；8 进程恰好 8 条 | V1→A2 |

**#354 合计**：7 fixed（P1-4/P1-5/P1-12/P1-13/P1-14/P2-15/P2-17）、9 duplicate（P0-1/P0-2/P0-3/P1-6/P1-7/P1-8/P1-9/P1-10/P1-11）、1 deferred（P2-16）。

### 2.3 多站点 issue 的合成状态

| issue | 站点/分面 | 合成状态 | 说明 |
|---|---|---|---|
| #426 | B（U02）/D+F（U04）/A（U14） | **部分修复** | B 单元判 duplicate（`1c990e9e`；后续 `5be2fd1e` 在历史，当前存活未核）；D/F 本端修（工作树）；A deferred（`md_cg/mdcos.py:2628/2649-2655` 仍旧）。整体不能关单 |
| #446 | 站点1/3（读面/结构）/站点2（密封短路+落盘闸） | **部分修复** | 站点1/3 由 `7cfa8029` 覆盖（`crypto.py:399/598` 的 `verify_encrypted` 在 HEAD）；站点2 仍用 `is_encrypted` 前缀（`mdcos.py:5949`、`mdcg.py:1782`），P0 未闭环 |
| #352 | A/C/D/E（U18 一轮）/B（U18 二轮） | **部分修复** | A（rollback 21/0）、C（imgaudit 10/0）、D（pathsjson 15/0）、E（refindex 14/0）duplicate；B 直写面修好，缺省 confirm 档 accept 仍复现“假正文挂 verified”；守卫 approved=false |
| #492 | 链尾执行器（writepipe）/工具面（mcp_server） | **部分修复** | `writepipe.py` 的 `include_dup_readout` 已入 HEAD（`ef9a9cfb`）；`mcp_server.py:3924-3927` 仍无条件算，NEED_FILE |
| #358 | ① 截断可观测/② BLINDSPOT 静默丢正文 | **fixed（①）+ duplicate（②）** | ① 本端修（工作树）；② `a3c3530c` 已覆盖 |
| #303 | O1/O2/O3/O4/O5 | **fixed（O1/O4）+ 文档化（O2/O3/O5）** | O1/O4 修；O2/O3/O5 按维护方口径保持现状并落文档（A4 诚实） |

---

## 三、理论挂靠表

> 条款关键词与行号引自 `总体方案` 的 `classes[].theory`；输出单元未逐条回读理论原文（当前 `docs/theory/智能的公理化基石.md` 行号与总体方案引用基线不一致，见 §5.2）。`A*`=智能论3.4 公理，`T*`=不可靠系统定理，`D*`=设计推论。

| 类 | 代表 issue | 条款（关键词） | 挂靠（一句话） |
|---|---|---|---|
| C01 | #469 | T8 fail-closed：“验证不可用时，输出必须落向‘声明不可用’，而非‘跳过验证继续’”；D4 四可：可发现/可隔离/可恢复/可追溯 | 受保护节点降级失败却记成功 = 不可追溯 |
| C02 | #424 | T8 fail-closed：有效密级未下传使降密级闸按 DEFAULT 判“同档” | 合并出单取声明/目标密级 = 跳过源密级验证 |
| C03 | #425 | T8 fail-closed：未设外部根时白名单回落库根本身 = 把“无外部根可验”当“库根合法” | 摄取白名单只堵空 path |
| C04 | #426-B | T8 + A4：“读不到”不等于“不存在”；不确定必须可声明 | 受 clearance 过滤的 `cg.get` 被当存在性判据 |
| C05 | #452 | A4 诚实：“声明不确定，永远优于编造确定”；T8 | 密级判据输入面取相对路径 = 编造 internal |
| C06 | #522 | D3 信任度量：“验证链闭环（自己验自己）= 零信任”；D4 可追溯 | 审计件取裁决者密级使外部复核面闭环 |
| C07 | #446 | A4 + T8 + T12 端到端：“低层校验只能降低成本，不能替代端到端判据” | 前缀候选同时充当密封短路/落盘闸/读面判据 |
| C08 | #453 | T8 fail-closed；A2 时间不可信：“墙钟可漂移、回拨、跳变，事件次序只承认逻辑时序”；T2 消息不可信 | 免签凭据=对端声明；包版本=对端自报时间 |
| C09 | #403/#498 | A1 真源唯一：“唯一可信终点是 append-only 落盘原文，索引态等均为易失派生物”；T9 自稳定 | 恢复期判据读索引派生物，而非盘面真源 |
| C10 | #447/#450 | T8 + A4：“缺键”不得被编造为 internal | 同一“缺 sensitivity 键”信号四面分叉（fail-open） |
| C11 | #348-C | T12 端到端 + A4：正文加密是低层校验，节点整体密级一致性才是端到端 | 派生索引字段不继承正文密级 |
| C12 | #445/#426-D | T8 + A4：读面无法判身份时仍输出 = 跳过验证 | 台账读面没有身份判据，查询原文按明文返回 |
| C13 | #322/#348-B | T2 消息不可信：“丢失、重复、乱序、任意延迟、内容篡改”；D5 合法态/自稳定。**明确不用 T7**（T7 限定“消息重复场景”） | 同 id 跨进程读改写无互斥，后写吞前写 |
| C14 | #470 | A1 真源唯一：“append-only 落盘原文”要求真的落盘；T9 恢复边界只覆盖已 sync 的前缀 | `File::flush` 是 no-op，事件行只等轮末 `sync_all` |
| C15 | #352-B | T8 fail-closed：“未声明”被解释为“沿用已验证”；T3 无特权裁决 | 同 id 改写默认继承验证态 = 跳过验证继续 |
| C16 | #426-A | A1 真源唯一：对账以 append-only 队列原文的**代际**为准；D6 幂等基准（内容哈希）本身在此不完备 | 审核队列幂等键缺代际，删除/改回旧值撞已裁决单 |
| C17 | #363 | 无可挂条款（诚实声明）：智能论3.4 §2.7 定义信息差为 JS 散度/四维 D_norm，不含检索名次/IDF；A3 讲验证预算分级，与 IDF 缺失无因果。改挂工程判据：#130“lexical 按真实打分排序”的前提被证伪 | 缺省 lexical 无 IDF，名次退化为写入序 |
| C18 | #492 | A3 验证有成本：“验证强度必须分级，按风险分配”；零消费者付全额成本 = 不按风险分配 | 观测读数无条件付 97% 开销 |
| C19 | #491 | T5 独立验证：“不经过被验组件自身的独立验证路径，是采信为事实的必要条件”；T4 静默错误/崩溃恢复 | 同进程裸 exec 使验证与被验同域，且无超时 |
| C20 | #402 | T0 ③ 静默错误：“正常响应，内容错——不可观测——独立验证路径（T5）——唯一防御”；T4；T8 | 截断 `.pbc` 静默执行成错结果 |
| C21 | #434/#435 | T0 ③ 静默错误；T8 fail-closed | 数值判据类型有、有限性无、分支不对称；inf/nan 过闸 |
| C22 | #436 | T0 ② 显式错误：“报错但内容错——可观测”；T12 端到端 | 未闭合字符串不推进行号，错误定位系统性偏小 |
| C23 | #427 | T8 fail-closed；T12 | 非映射 status.json 让 AttributeError 逃出，整条 `--status` 崩 |
| C24 | #511 | A4 诚实；T12：“最终判据落在原文子串/committed/HMAC，不落在‘组件说成功’” | docstring 声称的 `bad_files` 出口在实现里不存在 |
| C25 | #443 | D4 可追溯：无界台账最终不可读即不可追溯；A3 验证有成本 | 六台账无长度上限、5/6 无轮转，调用方 1:1 放大 |
| C26 | #521 | 无可挂条款（诚实声明）：A1 讲真源 vs 派生物，不覆盖命名拼接；纯工程判据=后缀拼接职责单点 | 锁名双后缀 `.rotate.lock.lock` |
| C27 | #438 | T1 观测者同罪：“检测组件 c 失效的组件 d，自身满足 T0；不存在特权观测者”；T0 | 守卫自身双 return/死代码/临时目录泄漏 |
| C28 | #429 | T5 独立验证；D3 信任度量；T4 失败/静默路径测试证明力高于成功路径 | 安全守卫无回退自证腿，撤回修复仍全绿 |
| C29 | #278 | 无可挂条款（诚实声明）：§0.0.1 只讲“信息差依赖条件空间”，不规定负条件词面/语义判据；冲突本质是判据自相矛盾，取向属设计裁定 | `neg_separated` 要词面换域，`REFLECT_PROMPT` 要语义邻近 |
| C30 | #222 | 无可挂条款（诚实声明）：T8/T12/A1 均不涉及打包解析；工程契约=dependencies 必须覆盖入口静态 import | optional peer 被入口静态导入，干净安装全断 |
| C31 | #224 | T9 自稳定：“任意瞬态故障后可有限步回到结构合法态”；A4 诚实 | 自动签发令牌不带 tenant，配置一变即 rc=3，重启不自愈 |
| C32 | #386 | A4 诚实：两个实现给出不同落点却不声明；T12 端到端一致 | `~` 在 Node 侧不展开，落仓根字面目录，Python 落家目录 |
| C33 | #426-F | T8 fail-closed：解码失败应落“配置不可用”，而非用 U+FFFD 继续；A4 | GBK/ANSI paths.json 被宽松解码成乱码根 |
| C34 | #303 | T8 fail-closed：无法判定输入合法性时给出正常结果 = 跳过验证 | NUL 正文判合法、负 k 静默给空结果 |
| R0 | #320/#326/#362/#370/#463 | T5 独立验证 + D3：核销理由不能是“有提交”，必须是“撤回即红”的实跑读数 | 已修待核销，不能先核销 |
| R1 | #111/#354/#358/#423/#428/#437 | A4 诚实 + D3：复现 ≠ 修复验证；报告自陈性质必须如实对待 | 证据/报告类，不据此关单 |
| R2 | #72 | A4 诚实：报告自陈“不是现有 bug”；T9/D5 仅作参照 | 需求类：coldverify 无受控消费入口，默认不自动消费是安全取舍 |

### 3.1 Lead 补充挂靠（U17/U18/U19/U20/U21）

- **U17 #326（六条独立缺陷）**：①白名单绕过＝A1 真源唯一 + 边界判据必须对**全部入口**成立（未认证入参不得决定是否过闸）；②孪生副本漂移＝第 6 条双副本纪律的机器化 + 智能论3.4 §3.2.1「结构锚定记录」——同一中文源码在两条链上必须产出同一字节码，静默错值比崩溃更危险；③VM 内存 O(depth²)＝A3 验证有成本（资源必须有显式上限，fail-closed）；④append_jsonl 击穿＝D4「可恢复」+ T0 失效定理——簿记失败不得升级为业务路径失败；⑤凭据权限＝第 9 条敏感信息隔离 +「声明与实现不符」；⑥无效形参＝判据必须可判（签名承诺的鉴权语义必须真参与判定，否则删掉）。
- **U18 #352 A–D**：A 回滚越界＝A2 时间不可信（前像不得当无条件真源，必须做执行后代际探活）+ immutable 面；B 继承验证态＝#320 同族（无裁决权不得自证，验证态不得跨代继承）；C 台账跟随符号链接＝本地信任边界（落点必须过根内判定）；D paths.json 静默回落＝A4 诚实公理 / T8 fail-closed——解析失败必须可观测，不得静默换根。
- **U19 #492**：A3 验证有成本——观测读数必须有显式开启的预算边界；「缺省字段由有值变缺键」属可观测形态变更，必须声明并配守卫。
- **U20 #354（17 条）**：P0-1 深嵌套＝T0 失效定理的「可用性失效」+ 已有 #321 覆盖；P0-2 WAL 非法 UTF-8 清空历史＝A1 真源唯一（已提交历史即真源，不得被无痕原位清空）+ T8 fail-closed；P0-3 路径穿越＝本地信任边界（读面必须过 containment）；P1-4 combineVerdict fail-open＝A4 诚实公理（判据不可用不得落 pass）；P1-5 信任内存 payload＝A1（内存态是派生物，判据必须读真源）；P1-6/P1-7 WAL seq 与并发重写＝A2 时间不可信 + D6 幂等；P1-9~P1-11/P2-17 writelimit＝A3 验证有成本（限流判据不得因坏输入崩溃或永久锁死）+ D4 可恢复；P1-12~P1-14 hooks＝第 9 条敏感信息隔离 + A1（注入面与日志面都必须过脱敏单点）；P2-15 原型替换＝判据不得被外部键名改写；P2-16 CLOCK$＝平台保留名判据必须完整（转 U18 面）。
- **U21 #358/#303**：#358 的两条新缺陷＝T0 ③「静默错误」（不可观测，唯一防线是 T5 独立验证）——截断与丢弃必须可观测；#303 的 O4/O5＝「静默归一」同一类（调用方拿不到非法信号），O1/O2/O3＝有意取舍、文档化即可（A4 诚实公理：把「已判过」写清楚，不是把所有边界都改成报错）。

---

## 四、未完成与需裁定

### 4.1 blocked 根因与下一步

| issue | 根因（条件层） | 卡点 | 下一步 |
|---|---|---|---|
| #446 站点2 | 前缀候选同时充当密封短路/落盘闸；真判据 `verify_encrypted` 已在 `crypto.py`，但两个消费点未接 | `md_cg/mdcos.py`、`md_cg/mdcg.py` 不在 U03 授权；当前树仍 `is_encrypted` | 扩权或另派持有两文件的单元：`_seal_content` 与落盘闸改用 `verify_encrypted`（有 dek 解密试算、无 dek 结构校验），复跑 `probe_446_seal` 直到伪前缀不再明文落盘；站点1/3 不重做 |
| #447 | `recent_events` 对缺 sensitivity 键 `or DEFAULT_SENSITIVITY`，fail-open 且跳过会话绑定 | `md_cg/mdcos.py` 授权外；他线 `9abb0f2c` 被 `e81caab0` 回退 | 重放/合并 `9abb0f2c` 的 `_recent_effective_sens`（缺键按 `secret`），复跑 `probe_447` 到 B1=false |
| #424 | `_autonomy_gate_merge` 出单取 `kw.get("sensitivity")`（常态 None），`propose` 按合并目标继承 internal | `md_cg/mdcos.py` 他线占用；`75c59ec2` 未生效 | 在出单前传源写入 `_sens_eff`（声明值 ∨ 继承源节点密级，取更严）；accept 侧 `merge_downgrades` 闸已在；复跑 `probe_424` 到目标不含 private 串 |
| #522 | 审计件密级取 `principal.clearance`，外部复核面失效 | `md_cg/mdcos.py` 当前仍缺陷；他线 PR `77138822` 未入 HEAD | 合并/重放 `77138822`（固定 `internal` 或按件类型定档），跑 `probe_522` 复验外部 `verify_ok=True`；档位取舍见 §4.3 |
| #443 | 长度判据只在 `writepipe.oversize_response`；五个台账落点无上限/无轮转 | 落点 `md_cg/fsutil.py`、`md_cg/imgskill.py`、`md_cg/state_events.py` 授权外 | 扩权：`append_jsonl` 统一限长并留 `truncated len=` 标记；imgskill/state_events 裸 open 同口径；接 `Rotator`；阈值见 §4.3 |
| #278 | `c6d00c07` 去 L1 覆盖率闸后“负条件抄正文片段”漏拒；词面覆盖率无法区分“抄正文”与“邻近易混” | `md_cg/consolidate.py` 与两个 278 守卫授权外；需语义/条件空间口径 | 先由 owner 裁定判据（§4.3），再把 `consolidate.py` + 两守卫同批派给持有者；裁定前不要重派原 ask |
| #352-B confirm 面 | 缺省 confirm 档 accept 由审核者 principal 调 `add`，`_can_verify=True`，假正文仍继承 verified | 直写面已修（工作树），confirm 面未覆盖 | 在 `_mutation_execute` 把**提出者**身份/非 verifier 判据带入，或按 issue B.6 对正文变化一律降 doubted；守卫补 confirm/accept 用例 |
| #492 工具面 | `mcp_server.py:3924-3927` 无条件算 prior/self_coverage/redundancy | `md_cg/mcp_server.py`、`md_cg/protocol.py` 授权外 | 复用 `writepipe._dup_readout`/`readout_calls` 做同一 `include_dup_readout` 门；`VERB_SPECS['write']['optional']` 与 cg inputSchema 增同名参数 |
| #402 残余 | 裸指令流在指令边界截断与合法短程序物理不可判；11 个静默点全在边界 | `compiler/cli/__init__.py`、Rust `pbc.rs`、白箱孪生授权外 | 版本化容器头（魔数+载荷长度+CRC32）需与 Rust/白箱同批；CLI 把 ValueError 转可读回执；PR `90d76b8f` 未入 HEAD |
| #426-A | `propose` 幂等键缺代际；accepted/rejected 旧单直接 break | `md_cg/mdcos.py`、`md_cg/mcp_server.py` 授权外；`0828e022` 仅回执归因 | 命中 accepted/rejected 时照常入队，或键并入代际；需 owner 定“被 reject 的正文再提是否照常入队”（§4.3） |
| #469 残余 | `set_state` demote 段未传 override，受保护节点停在 `demote_state:protected` | 生命周期保护语义待裁 | 由 owner 决定 `set_state` 是否吃 override；未裁前只登记 |
| #72 残余 | 只落最小能力；`drain()` 仍是无闸公开方法 | MCP/CLI 接线与阈值属运维配置面 | 若需要，单独立项受控入口/阈值告警；默认不自动消费的安全取舍保留 |
| #322 守卫 M3b | A5 worker 在 t0 前构造 `MdCGSecure`，进程抖动可使快照已含 A 的写入，撤掉探活仍绿 | 守卫文件在授权外（U06 授权面） | 只改守卫：worker 构造完成写 ready 握手，父进程等齐再设 t0；连跑 7 次验证 M3b 稳定只红 A5 |
| #429 元守卫 | 两条新守卫的变异分支写成 `if "--mutate" in argv`（局部 list），`check_guard_coverage` 的 AST 判据不识别 | `scripts/check_guard_coverage.py` 已入库，但新守卫未登记 | 若登记进 `MUTATE_GUARDS`，先改分支为 `"--mutate" in sys.argv`；否则元守卫会误判“缺变异腿” |

### 4.2 维生巡检归因与下一步（与当前现场对照）

| 单元 | 巡检归因 | 输出单元对照 | 下一步 |
|---|---|---|---|
| U03 | #446 站点2 真实；站点1/3 已由 `7cfa8029` 覆盖 | **成立**：当前 `md_cg/crypto.py:519-520` 仍前缀；`md_cg/mdcos.py:5949`/`md_cg/mdcg.py:1778` 仍消费它 | 扩权/另派；不要重做站点1/3 |
| U04 | #447 真实；`md_cg/mdcos.py` 授权外；reflect 治本点 `md_cg/mdcg.py` | **成立**：当前 `recent_events` 仍 `or DEFAULT_SENSITIVITY`；`_recent_effective_sens` 0 次；`9abb0f2c` 被 `e81caab0` 回退 | 重放/合并；再补 reflect 的 sensitivity/摘要 |
| U06 | 产品修复成立（`f108f17f`/`940c7a69`）；唯一不成立 M3b 竞态 | **成立**：`node_write_lock`/`merge_rmw_lock` 在 HEAD；M3b 代码路径仍是“先构造后对齐” | 只改守卫 ready 握手，第三顺位 |
| U07 | #278 漏拒真实；词面不可区分；需 owner 裁定 | **成立**：当前 `consolidate.py` 未改；`c6d00c07` 的 L1 去闸仍在 | 先裁定，再同批派 `consolidate.py` + 两守卫；裁定前不重派 |
| U13 | #443 真实；#522 落点在 mdcos.py 但被 #303 占用 | **部分过期**：当前 `e81caab0` 后 #303 的 `valid_node_id` 只在工作树未提交；#522 仍缺陷；PR `77138822` 未入 HEAD | #522 待 #303 提交/授权；#443 扩权 |
| U16 | #424 真实；mdcos.py 只剩 #303 两个 hunk | **部分过期**：当前 `_autonomy_gate_merge` 仍无 `sensitivity` 形参；`75c59ec2` 未生效 | 重放/合并；按源有效密级出单 |
| U18 | #352-B 真实；`md_cg/mdcg.py` 已干净可重派 | **部分过期**：二轮已修直写面；复核发现 confirm 档仍复现；当前工作树有直写面未提交 | 重派只做 confirm 面 + 守卫；不要重做直写面 |
| U19 | 工具面第二落点真实；`mcp_server.py`/`protocol.py` 授权外 | **成立**：`mcp_server.py:3924-3927` 仍无条件 | 扩权/另派；writepipe 侧不重做 |
| U20 | 运行被基础设施中断；有通过日志与 5 文件未提交成品 | **已过期**：第二轮 U20 已完成 17 条，复核 approved；工作树仍有 TS/writelimit 未提交成品 | 不需要重派；只需把成品提交/与当前 HEAD 对齐 |
| U18/U20 retry | 巡检建议重派 U18/U20 | U20 已由第二轮覆盖；U18 只需 confirm 面 | 只重派 U18 的 confirm 面；U20 不重派 |

### 4.3 留给维护者的裁定项

1. **HEAD `e81caab0`(#899) 的 66 文件/-8024 行提交**：实测 `git show --stat e81caab0` 删除 #424/#447/#446/#426-B/#452 等守卫与实现（如 `_recent_effective_sens`、`sensitivity=_sens_eff`、`test_issue424_merge_confirm_sensitivity.py`、`test_issue447_recent_sens_failclosed.py`、`test_issue446_is_encrypted_envelope.py`、`test_issue426b_root_clash_invisible.py`、`test_issue452_ingest_root_hint.py`、`test_issue352_vstateinherit.py`），并删除 `qmd.py`/`qmd_llm.py` 等 8000+ 行。需裁定：revert 该提交、还是按文件重放本批/他线修复；在此之前不能把单元快照的 fixed 当当前事实。
2. **#278 的取向二选一**：把 `REFLECT_PROMPT` 从“邻近易混”改为“换域”，还是把 `neg_separated` 判据改为语义/相对口径？理论判不了——两种改法都能消除自相矛盾，取舍取决于“技术类知识固化率”与“负条件判别力”谁优先。
3. **#522 审计件密级档位**：固定 `internal`、取被裁决节点密级、还是单独 `restricted`？D3 只能判“不得取裁决者 clearance 而使复核面闭环”，不提供档位排序。
4. **#72 是否提供 coldverify 受控消费入口、默认开还是关**：T9/D5 只要求“真源在时可在有限步回合法态”，不要求自动消费；默认关闭是既有安全取舍，排期/默认值属资源/风险裁决。
5. **#426-A 被 reject 的正文再提是否照常入队**：是维持内容哈希去重（回执 `already_decided`），还是按代际键区分并重新入队？属审核队列语义裁定。
6. **#469 `set_state` demote 是否吃 override**：受保护节点 override=True 时是否允许推进到 demoted；属生命周期保护语义。
7. **#443 台账长度/轮转阈值**：A3 只要求“按风险分配”，不给具体字节上限/轮转策略；属资源裁决。
8. **#402 容器头与 Rust/白箱兼容**：版本化头能关闭指令边界截断，但会打断 Rust `pbc.rs` 的裸流读取；需同时改运行时/孪生/迁移文档，属跨端兼容裁定。
9. **#354 的 17 条如何去重、拆分、受理**：intake 的受理权与计分口径归维护者；本总账只给分诊与读数。
10. **#111 外部方案（RRF3 v1.1 + ChronicleDM）是否采纳**：D3 只要求若采纳须走独立验证路径（T5），不判“该不该采纳”。

---

## 五、诚实边界

### 5.1 当前 HEAD 的 #899 回退面（先读这一节）

- 输出时 `git log --oneline --graph` 显示 HEAD 为 `1a528ea5`；其前一笔 `e81caab0`(#899) 的 `git show --stat` 为 **66 files changed, 222 insertions(+), 8024 deletions(-)**，包括删除 `md_cg/qmd.py`、`md_cg/qmd_llm.py`、多份 issue 守卫（#424/#447/#446/#426-B/#452/#352-B/#418/#540/#541/#542/#543 等）与 `docs/benchmarks` 等。
- 实测 `git show --unified=3 e81caab0 -- md_cg/mdcos.py` 删除了 `_recent_effective_sens`、`sensitivity=_sens_eff`、`_autonomy_gate_merge(..., sensitivity=None)` 等；`git log -S "_recent_effective_sens" -- md_cg/mdcos.py` 显示 `e81caab0` 是最后一次改变该串的提交。故 #447/#424 的修复在**当前 HEAD** 不是事实；#522 的 `77138822` 只在 `pr534` 分支，#446 的 `010e8fbb/6c6773ba/901460f2` 只在 `pr454/pr497`，#402 的 `90d76b8f` 只在 `pr533`，`#426-A` 的 `0828e022` 只在 `pr514`。
- 当前工作树仍有未提交成品：`md_cg/metacognition.py`（#445）、`md_cg/datapath.py`（#426-F）、`swarm/rust_runtime/src/swarm.rs`（#470）、`md_cg/mdcg.py`（#352-B 直写面）、`src/lib/mutual.ts`/`src/hooks.ts`/`src/tools.ts`（#354）、`md_cg/writelimit.py`（#354 P2-17）、`md_cg/forgetting.py`（#358）、`md_cg/mdcos.py`/`md_cg/mcp_server.py`（#303）、`md_cg/test_issue492_dup_readout_opt_in.py`（#492 守卫成本计数，M），以及对应未跟踪守卫。另有 `md_cg/audit.py` 等未归属 M 文件，未计入任何单元。
- 符号抽查（`git show HEAD:<file>` 与工作树计数，输出单元实跑）：`compiler/compiler.py:_finite_operand` 7/7；`compiler/condition_vm.py:is_finite_number` 10/10；`compiler/pbc.py:_need` 16/16；`md_cg/fsutil.py:node_write_lock` 1/1；`md_cg/mdcg.py:idf_of` 2/2；`md_cg/mdcos.py:with node_write_lock` 3/3、`merge_rmw_lock` 11/11；`md_cg/mcp_server.py:_require_verify_for_vstate` 2/2；`md_cg/mdcg.py:override=override` 8/9；`md_cg/rollback.py:drifted_since_execute` 4/4；`md_cg/imgskill.py:safe_join` 12/12；`md_cg/datapath.py:utf-8-sig` 2/3；`md_cg/readcache.py:install_default` 2/2；`md_cg/whitebox_kb/wisdom/verifier.py:run_guarded` 9/9；`code_compose.py:run_guarded` 3/3；`md_cg/coldverify.py:controlled_drain` 4/4；`md_cg/evidence.py:_local_generation_blocks` 3/3；`md_cg/sources.py:source_sensitivity` 7/7；`md_cg/rotate.py:lock_path` 3/3；`md_cg/test_issue398_toolface_op_parity.py:S01/S02` 4/4、12/12。**未核**：`refindex.py` 的 #426-B/#452 内读面在 #899 后是否仍完整；`mcp_server.py` 的 #320 门虽计数 2，但 #899 改了该文件 67 行，语义未逐行核。
- 结论：不能把 §二 的 `fixed` 直接当“当前 HEAD 已修复”。本总账的 `fixed` 是**单元快照判定**；当前 HEAD 的存活面需要维护者按 §5.1 的提交裁定后重跑守卫。

### 5.2 未复跑 / 只读核验

- 输出单元**没有运行任何单元守卫、探针或全量 `run_tests`**。所有“12/0、35/0、M1→…”读数均来自单元 `result/review` 的材料；复核单元自称亲手跑过，输出单元未重复。
- 输出单元实际执行的只读命令：`python -X utf8` 读取 `.tmp/issues_open.json`（47 件）；`git log/show/status/merge-base/grep`；对 `HEAD:<file>` 与工作树的符号计数；`Read` 读取 `crypto.py:515-558`、`mdcos.py:2620-2674/3054-3083/4878-4932/5940-5964/6533-6558`、`mdcg.py:1768-1784/3140-3194`、`mcp_server.py:3908-3942`、`test_issue322_node_write_lock.py:235-269/425-466/640-664` 等。
- `总体方案` 的条款行号引用的是其自身基线；当前 `docs/theory/智能的公理化基石.md` 为 792 行，行号与总体方案引用不一致，故 §三 只引**条款关键词/名称**，不把行号当当前原文位置。
- 复核对单元计数的更正已采用：U17 五守卫 20/18/30/31/22 → **17/17/27/28/21**；U18 rollback 23 → **21**；U18 vstate A 组 16 → **15**；U20 TS 守卫 18 条（P1-4/P1-5 等）；U14 #470 13 条；U21 #303 18 条。

### 5.3 只能看见“过滤在场”的判据

- #447/#450：能断言“缺键时 fail-closed”，**不能**断言 `PRIVATE_HINTS` 覆盖真实敏感目录名。
- #452：能断言“根段不再被抹掉”，**不能**断言提示词表完备。
- #363：能断言“名次不再随 id 变化”，**不能**断言 212 题代表真实语料；只复跑了随仓库公开的 500 条池，未复跑《呐喊》/《老残游记》212 题冻结集。
- #425：能断言白名单作用域，**不能**断言“哪些目录算敏感”的目录学正确性。
- #446：`verify_encrypted(dek=None)` 只做结构验证（base64+长度），**不证明能解密**；结构验证 ≠ 解密验证。
- #322/#348/#403/#498：腿覆盖多进程共根，**不能**覆盖跨机、NFS/网络文件系统锁语义；竞争是概率性的，单轮绿无证明力。
- #491：只断言“无超时/无闸”的确定性失效，**不能**断言现实可利用性；当前不在 MCP 工具面（单元自陈）。
- #429：只把“回退即红”覆盖到点名的两份安全守卫，未扩到全部安全守卫（成本问题，A3）。

### 5.4 需要跨机/跨环境的项

- #222/#224：需 npm registry 干净安装与多 Node 版本矩阵；本轮用 `npm pack` + 真实 `npm install` + import 复现，未跑 3 平台×2 Node 矩阵。
- #426-F：需 GBK/ANSI locale 写出的 paths.json；本轮只测接收侧 + 插件侧源码面，未在真实 GBK 环境跑。
- #386：需 Node 与 Python 同机落点对照；本轮有对照探针，但未覆盖 `~user` 的 Windows 真实家目录解析。
- #491：超时路径只在本机 Windows 验证；POSIX `killpg` 路径未实跑。
- #354 Rust `--mutate`：本轮未重跑（会临时改写工作树 `swarm.rs` 并 cargo 重建，触碰他单元未提交改动）；只跑默认模式 + HEAD 源码锚点。
- #446：未测真库存量数据；#403：未测真 stdio MCP 子进程形态（同进程双实例 + 独立 writer）；#72：未做 MCP/CLI 端到端；#470：cargo 在 Windows 本机真编译，未跨平台。
- #402：Rust 运行时/白箱孪生未同步；容器头方案会牵动 `swarm/rust_runtime/src/pbc.rs`，未跨端验证。

### 5.5 其它诚实声明

- `#358` 的 `MAX_COMPARE` 漏比本身按报告口径**保留**；本批只补可观测（`candidate_total/truncated`），未改 limit/顺序/裁决。
- `#303` 的 O1/O2/O3 是**有意取舍并文档化**，不是“全部改成报错”；O5 的 `invalid_node_id` 尚未登记进 `md_cg/protocol.py`。
- `#322` 的产品修复成立，但守卫 M3b 变异腿**不稳定**（复核 7 次中 1 次假绿）；这是守卫可靠性问题，不是产品回归。
- `#492` 的成本判据是**调用次数**（机器无关、可断言），未复测提交信息里的毫秒数；工具面仍未收口。
- `#72` 的 `drain()` 仍是无闸公开方法；“受控”只对新入口 `controlled_drain` 成立。
- `#429` 的 `check_guard_coverage.py` 只判“腿的结构存在性”（AST 真实分支/真实定义），不判“腿跑起来真的按指定红项转红”；运行时证据由各守卫 `--mutate` 提供。
- `#322` 的 `add_rejected`/`add_unresolved` 密级继承读改写仍在锁外（单元 residual ④）；`#469` 的 `set_state` demote 仍无 override。
- 本文件不含本机绝对路径、凭据形态或攻击步骤；缺陷描述只保留防守侧后果与判据位置。

---

## 六、对外回执草稿

> 口径：每件 3–6 行；`fixed` 写判定/复现/修复或结论/守卫/残余；`duplicate` 写覆盖提交/复核读数/残余；`blocked` 写根因/卡点/下一步；报告类写“已收到并核验”，不假装修复。所有读数均为材料读数，输出单元未复跑。

### 6.1 fixed / duplicate（开放快照内 32 件）

#### #498 合并痕迹对账依赖索引新鲜度
- **判定**：fixed（本端 `19b7b86e`）。
- **复现**：pristine HEAD 上索引未持久化时 `_merge_target('n_x')=None`、reconcile 判 `interrupted/node_missing`；盘面已有 `merge_source_ids`。
- **修复**：`twophase._merge_target` 索引 miss 后回盘面扫描，命中仍返回目标；未命中才 `None`。
- **守卫**：`md_cg/test_issue498_merge_trace_stale_index.py` 12/0；M1 红 A03/A04/A05、M2 红 B01。
- **残余**：A06 端到端可能被 `_snapshot_trusted` 救回，判别力在 A01–A05；未跑全量。

#### #425 显式 path/库内文件仍可摄取
- **判定**：fixed（本端 `19b7b86e`）。
- **复现**：库根/trash 被当外部文档重切，restricted 正文以 internal 落库、已删除节点复活。
- **修复**：摄取链加库内保留子树闸（`md_cg/sources.py`），祖先目录剪枝复用 `codeindex.skip_matcher`。
- **守卫**：`md_cg/test_issue425_ingest_library_path.py` 15/0；M1/M2/M3 指定命中 3/3、2/2、1/1。
- **残余**：A5/B2 由 #346 覆写闸兜住；未跑全量。

#### #452 摄取根本身敏感时密级被相对路径抹掉
- **判定**：fixed（本端 `19b7b86e`）。
- **复现**：`path=<敏感根>/private` 摄取后节点密级 internal，同身份读回；`path=<敏感根>` 被拒。
- **修复**：`source_sensitivity` 用绝对路径 + 源 frontmatter 取更严；判据本体仍只有 `docindex.sensitivity_for` 一处。
- **守卫**：`md_cg/test_issue452_ingest_root_sensitivity.py` 12/0；M1 4/4、M2 4/4、M3 1/1。
- **残余**：`item["path"]`/`doc_ref.path` 仍相对，节点 id 不变；若要求带根信息需单独立项。

#### #453 空签名免签 + `created_at` 版本护栏
- **判定**：fixed（本端 `7cfa8029`，随动 `f78adbbd`）。
- **复现**：`signer=null`/空串/signed=false 的空签名包 imported=1；`created_at=9e15` 把 `_xnode_seen` 推到未来，后续合法包永久 replayed。
- **修复**：`_signer_declaration_rejected` 空签名一律拒；`MAX_PACK_FUTURE_SKEW=300s` 上界整包拒收。
- **守卫**：`md_cg/test_issue446_453_403_verified_evidence.py` 35/0；M3/M5/M7 命中 A2/A2b3/A2b4/A2c/A9a–d、A7/A7b、A9a–d。
- **残余**：行为变更——策略未签名的 export_pack 包不可再导入；test_issue147 夹具已补真签。

#### #403 同名本地节点覆写缺代际探活
- **判定**：fixed（本端 `7cfa8029`）。
- **复现**：陈旧索引下 imported=1、盘面被覆写；新鲜索引下谓词 True 但 import 仍覆写。
- **修复**：`_local_generation_blocks` 单点（只认 `updated_at`，无则保守阻断），循环外代际探活；删掉不存在的 `updated_at` 比较。
- **守卫**：同 35/0；M4→A5/A5b/A8、M6→A8/E7。
- **残余**：未测真 stdio MCP 子进程；A5 表已与谓词同口径。

#### #445 反思台账明文查询原文、读面无密级闸
- **判定**：fixed（本端，工作树未提交）。
- **复现**：HEAD 镜像上访客 `cg_insight_explore` 拿到完整查询原文；`self_check` 返回相似度/计数。
- **修复**：`_reflections` 成为唯一读取点，`_can_read_record` 缺 sensitivity 键 fail-closed；五个消费面继承。
- **守卫**：`md_cg/test_issue445_metacognition_ledger_gate.py` 24/0；M1 7、M2 10、M3 2、M4 5、M5 1。
- **残余**：`reflect()` 仍不写 sensitivity 且 query 明文落盘（NEED_FILE `md_cg/mdcg.py`）；非设计者反思派生面退化为空（刻意取向）。

#### #471 identity 读面三处缺口
- **判定**：duplicate（他线 `e3f5e6f6`；该 issue 已关闭）。
- **复核**：`md_cg/test_issue471_identity_readable.py` 10/0；positions/infer_position/profile 三处均接可见性判据。
- **残余**：守卫无 `--mutate`，用内建 A'-1/A'-2 对照；e3f5e6f6 自陈 (c2) profile 锚点/指针面不做。

#### #322 同 node_id 并发写无跨进程锁
- **判定**：fixed（产品，本端 `13bdc99f`/`940c7a69`）。
- **复现**：同 id 并发 6/6 轮丢正文、两份并存；搬迁腿 3/3 轮新值被顶掉；密级继承无锁 6/6 降级、只加 add 锁仍 3/6 降级。
- **修复**：`fsutil.node_write_lock`/`merge_rmw_lock`；`_move_layer` 覆盖、add 整段持锁、`_write_sensitivity` 读前代际探活。
- **守卫**：`md_cg/test_issue322_node_write_lock.py` 18/0；M1–M4 命中；**M3b 不稳定**（1/7 假绿）。
- **残余**：M3b 需 ready 握手；父类 `MdCG._move_layer` 仍无锁（NEED_FILE `md_cg/mdcg.py`）。

#### #348 MERGE/CONVERGE 读改写无锁
- **判定**：fixed（本端 `940c7a69`）。
- **复现**：4 写者同目标 5/5 轮回执 20 条、丢失 15 条新值。
- **修复**：六处 `with merge_rmw_lock(self):` 落点；CONVERGE 支只有结构锚 E2、无并发行为腿（已声明）。
- **守卫**：`md_cg/test_issue348_merge_rmw_lock.py` 11/0；M1→A1b/A2/E3a/E3d、M2→E3d/E4。
- **残余**：父类 `MdCG._move_layer` 无锁；#348-C 派生字段面见 C11（未在 U06 面修）。

#### #434 知足阈值位裸 `float()`
- **判定**：fixed（本端 `51f72ff9`）。
- **复现**：`compile_source('知足 验证单元')` 等三形态裸 `ValueError`；pbc 同径。
- **修复**：`_finite_operand` 单点，DE/ZHIZU 共用；捕获 TypeError/ValueError/OverflowError。
- **守卫**：`compiler/tests/test_issue434_zhizu_operand.py`；M A01/A02/A03 全红。
- **残余**：E 组锚点在场；codegen 面 `api.compile_source` 仍 success=True（issue 自陈守卫盲区，不在本件修法）。

#### #435 inf/nan 穿透数值闸
- **判定**：fixed（本端 `51f72ff9`）。
- **复现**：11 形态 `德 X` 全 ok=True、errors=[]；运行期 `德 nan` 破坏等式自反，`德 inf` 信任 inf。
- **修复**：`is_finite_number` 全函数（int 短路、float 走 isfinite）；编译期 `_finite_operand` 增捕 OverflowError；四落点同口径。
- **守卫**：`compiler/tests/test_issue435_finite_trust.py`；M 三档红项 B01/B04/B06/B08/B10、B12–B16、A 德 inf/nan、A 知足 inf。
- **残余**：Rust `vm.rs` 同族判据未动（授权外）；大整数路径已恢复可用。

#### #402 截断 `.pbc` 静默执行
- **判定**：fixed（主面，本端 `51f72ff9`）。
- **复现**：改前 177 截断点：ValueError 16（全 UnicodeDecodeError）、裸异常 141、静默 19；cut=26 仍 rc=0 跑出错值。
- **修复**：`_need` 长度判据单点（13 处）+ 非 UTF-8 转结构化 ValueError + `save_pbc` 原子写。
- **守卫**：`compiler/tests/test_issue402_pbc_truncation.py`；M A03/A01/B02 红。
- **残余**：改后 165 ValueError、0 裸异常、11 静默——11 点全在合法指令边界（物理不可判）；CLI/Rust/白箱未同步；v2 头 `90d76b8f` 未入 HEAD。

#### #436 未闭合字符串吞换行
- **判定**：fixed（本端 `51f72ff9`）。
- **复现**：单/双未闭合 errors 指向 L2:C8/L3:C8；德/0.5 报 L2（真实 L3）；三连未闭合全报 L1（真实 L4）；EOF 未闭合静默。
- **修复**：`_read_string` 的 `\n` 分支先记错误（指向串首）再 emit、消费换行并 `self.line += 1`；EOF 未闭合记错误。
- **守卫**：`compiler/tests/test_issue436_unterminated_string.py`；M A01/A06/B01；K06 钉 STRING 列号与 HEAD 一致。
- **残余**：parser 的 N4 跨行判定未改（行号修复后其输入已正确）。

#### #427 `--status` 对非映射 status.json 崩
- **判定**：fixed（本端 `b4d3d513`）。
- **复现**：数组/字符串/null/number 四种合法 JSON 均 AttributeError；对照 `{state:done}` 正常。
- **修复**：`hive/serve_start.py` 读回值先过 `isinstance(v, dict)` 形状闸，非映射按读件失败跳过；合法对象缺 state 仍记 `?`。
- **守卫**：`md_cg/test_issue427_serve_status_shape.py` 12/0；M1 红 9 项、M2 红 3 项。
- **残余**：不可哈希 `state`（如数组值）仍 TypeError；守卫变异分支写法不被元守卫 AST 识别；未做 CLI 端到端。

#### #511 docstring 的 `bad_files` 出口不存在
- **判定**：fixed（本端 `b4d3d513`）。
- **复现**：合法/非映射/坏 JSON/缺失四池的 `build()` 顶层均无 `bad_files`；B vs F 逐键相同=True。
- **修复**：`read_json` 用 `_MISSING`/`_BAD_JSON` 哨兵；`_file_shape` 单点观察 `_obj` 输出；`job_record`/`_scan_detail`/`build()` 输出 `bad_files` 与 `totals.bad_files`。
- **守卫**：`md_cg/test_issue511_scoreboard_bad_files.py` 16/0；M1/M2/M3 指定命中。
- **残余**：`_file_shape` 二次读盘竞态；`read_json` 返回契约变为哨兵（仓内无其它调用点，仓外需注意）。

#### #429 安全守卫撤不住回退
- **判定**：fixed（本端 `20c3ea26`）。
- **复现**：改前 `--mutate` 被静默忽略；#93 G2 只找字样；#91 G1 无 cases；撤回修复仍全绿。
- **修复**：#93 真调 `mdcg_remember` 后扫隔离根盘面；#91 G1 带 cases、G7 走生产子进程执行器；`check_guard_coverage` 改 AST、整份删除必报、内嵌判据自检进自动链。
- **守卫**：#93 9/0、`--mutate` 红 G5/G6；#91 11/0、`--mutate` 红 G1/G7/G8；coverage rc=0、selftest rc=0、配对 15/0。
- **残余**：元守卫只判结构存在性、不判运行时转红；#429 的 RRF 候选一路未处理；#91 T3b 有机器级抖动。

#### #438 守卫双 return/临时目录泄漏
- **判定**：fixed（本端 `20c3ea26`）。
- **复现**：`issue #398 结果` 行数=0；`%TEMP%/iss398_*` 每次 +1。
- **修复**：收尾块移入 `main()` 的 return 之前；S01 静态（`__main__` 后无模块级语句、main 顶层 return 恰 1、rmtree 在 return 前）+ S02 行为（隔离 TEMP 子进程跑，结论行恰 1、无残留）。
- **守卫**：`md_cg/test_issue398_toolface_op_parity.py`；M5→S01/S02；默认 0.3s/变异 5.5s。
- **残余**：`check_unreachable.py` 的 TERMINALS 缺口未改（授权外）；未跑全量。

#### #363 缺省 lexical 无 IDF、名次退化写入序
- **判定**：fixed（本端 `940c7a69`/`da018cec`）。
- **复现**：41 文档夹具目标名次 41/41、目标分=干扰分=0.444444、档数 1/41；locomo-zh-500 hit@1 96.8%。
- **修复**：`idf_of` 算术单点（与 bm25 同式），`lexical_sim(df=,n_docs=)` 消费；不传 df 时旧公式逐位不变。
- **守卫**：`md_cg/test_issue363_lexical_idf.py` 22/0、`--mutate` 26/0；`test_retr_s5` 17/0（精度修复）。
- **残余**：Rust `retrieval.rs` legacy 未同步（NEED_FILE）；只跑 locomo-zh-500，未跑 212 题冻结集；`p6_consolidate`/`issue278_neg_separated_tension` 为既有基线红。

#### #370 readcache 只在 MdCGOS 装配
- **判定**：duplicate（他线 `5d991430`）。
- **复核**：`readcache.install_default` 定义于 `md_cg/readcache.py`，MdCG/MdCGOS 两处调用同一入口；守卫 19/0。
- **残余**：本单元未改 `md_cg/readcache.py`；未跑全量。

#### #222 package.json 无 dependencies、入口静态 import optional peer
- **判定**：fixed（本端 `f8e15305`）。
- **复现**：HEAD package.json + 当前 lib 干净安装后 `ERR_MODULE_NOT_FOUND schemastery`；deps field=None、peer optional=true。
- **修复**：schemastery 归位 dependencies；其余 5 个 @deepseek-ai/* 仍 optional peer，但入口改 `import type` + 注册时 `await import`。
- **守卫**：`test/issue222_optional_peer.test.ts` 2/2；M1/M2/M3 红项；真实 npm pack/install 复验。
- **残余**：3 平台×2 Node 矩阵未跑；`~user` 形态与 Python 仍分叉（#386 登记）。

#### #224 自动签发令牌不带 tenant/不读 config.env/密钥环不复核
- **判定**：fixed（本端 `f8e15305`）。
- **复现**：tenant=work 记录 tenant=default，子进程 rc=3；config.env 的 aux 不生效；`~/.mdcg-aux` 落点与 Python 分叉；吊销后仍复用密钥环。
- **修复**：`effectiveTenant` 单点；签发/复核共用 `runTokensCli`；`checkKeyring` 四分类；bridge 按退出码 3 分流；auxRoot `expandHome`。
- **守卫**：`test/issue224_token_store_bind.test.ts` 1/1；M1–M9 全命中。
- **残余**：相对 `MDCG_AUX_ROOT` 仍分叉（review finding，建议后续补）；`~user` 保留字面量；仓根未跟踪 `~/` 由仓主处置。

#### #386 环境变量 `~` 不展开
- **判定**：fixed（本端 `f8e15305`）。
- **复现**：HEAD datapath 的 stateRoot/dataRoot/mdcgRoot 落 `<cwd>/~` 或 `<仓根>/~`，与 Python 落点 SAME=False。
- **修复**：`expandHome` 单点，四个入口全部 `resolve(expandHome(...))`；`~user` 按 PR #385 保留。
- **守卫**：`test/issue386_tilde_expand.test.ts` 2/2；A 11、B 2、C 1、D 4 项。
- **残余**：`~user` 两侧仍分叉（已写入守卫不适用条件）；未跑全量。

#### #521 锁名双后缀
- **判定**：duplicate（他线 `c455cc9d`，随动 `798dc03e`）。
- **复核**：`rotate()` 产 `_audit.rotate.lock`，无双后缀；守卫 6/0；A1/A2 用 monkeypatch 复现红。
- **残余**：该守卫 docstring 声称 `--mutate`，但 `main()` 未分派 argv（名存实亡）；本轮用进程内变异替代。

#### #320 record 令牌自带 `verification_state=verified`
- **判定**：duplicate（他线 `620ed054` + `fbc0257d`）。
- **复核**：record 声明 verified/doubted/未知值一律 AccessDenied 且盘面无节点；中性 unverified/缺参放行；守卫 14/0。
- **残余**：镜像基线缺 `data/policy.json`，V4 判别力被削弱；库层直调 `MdCG.add` 仍接受 verified（显式设计取舍）。

#### #469 scrub override 未下传 `_move_layer`
- **判定**：duplicate（他线 `7e06aaf8`）。
- **复核**：受保护 expired 节点 + override=True → `done=['weaken','demote_state:protected']`、layer 真变；二轮 `already_handled=0`；守卫 6/0。
- **残余**：`set_state` demote 段仍未传 override，受保护节点停在 demote_state；守卫无 `--mutate`（手工回退验证 A1）。

#### #470 swarm WAL 事件行 `flush` 是 no-op
- **判定**：fixed（本端，工作树未提交；`swarm/rust_runtime/src/swarm.rs`，`sync_data` HEAD 0/WT 5）。
- **复现**：`open_wal_for_run` 返回 `std::fs::File`，`File::flush()` 无用户态缓冲、是 no-op；事件行只等轮末 `sync_all`；`wal_durable/event_syncs` 出口不存在（命中 3/4）。
- **修复**：事件行（路由事件 + 修正信号）写完后显式 `wal.sync_data()`，之后才写轮末快照；新增 `WalDurable{event_syncs,last_sync_round}` 随 `report_json` 透出，早退恒 0。
- **守卫**：`md_cg/test_issue470_wal_event_durable.py` 13/0；V1→A1c/B1/B2、V2→A1a/A1c/B3、V3→B1b；cargo test 27+1。
- **残余**：未把 `open_wal_for_run` 改 `BufWriter`；Windows 本机真编译/真二进制，未跨平台。

#### #72 coldverify 无受控消费入口
- **判定**：fixed（本端 `a41bcba9`）。
- **复现**：`controlled_drain` 入口/权限闸/限量闸/失败重入队/dead_letter/消费审计全部缺失；`dry_run` 与 `oldest_age_s` 已在（`35717e8b`）。
- **修复**：`md_cg/coldverify.py` 新增模块级 `controlled_drain` 单点：`can_admin` 权限闸、`0..CONTROL_LIMIT_MAX` 限量闸、`dry_run` 预演、失败重入队/上限/dead_letter、`coldverify_drain` 审计行。
- **守卫**：`md_cg/test_issue72_coldverify_controlled_drain.py` 27/0；M1→G1a/G1b/B1、M2→G4/B2、M3→G5b/G5c/B3、M4→G6a/G6d/B4。
- **残余**：MCP/CLI 接线未做；可选阈值/告警未做；`drain()` 仍是无闸公开方法。

#### #491 同族执行器 `verify_code` 同进程裸 exec
- **判定**：fixed（本端 `71d5dc34`）。
- **复现**：`code_compose.verify_code` 的 L2 两处同进程裸 `exec`（py_ref/Python），无 `__builtins__` 限制、无超时；P1/P2/P3 死循环 HANG，P4 `open()` 载荷 created=True。
- **修复**：不建第二套沙箱；`verifier` 新增公开薄委托 `run_guarded()`（委托 `_run_guarded`），执行器增 `compose` 模式；`code_compose` 删 `_run_case` 与两处裸 exec，统一经 `_load_verifier()`+`_compose_exec()`，保留首可调用/严格相等/call 标记/unpack 语义。
- **守卫**：`md_cg/test_issue491_compose_sandbox.py` 9/0；M1→S1/S2、M2→S1/S3、M3→S6、M4→S8、M5→S9；probe P1 20.03s 有界、P4 created=False。
- **残余**：5 条 low（py_ref `call` 样例由“判负”变“跳过”，705 单元零命中；10 域单元收紧；T3b 抖动；锚点退出码 1 而非 2）；POSIX 未实跑。

#### #450 写面层闸缺 sensitivity 键回落 internal
- **判定**：fixed（本端 `4ecbe158`）。
- **复现**：internal 身份写 legacy 无键节点 -> PASS（越权）；`_resolve_target` 返回 `(knowledge, internal)`；显式 restricted 则 DENY。
- **修复**：`_resolve_target` 既有节点且三来源皆无密级 -> `SENSITIVITY_ORDER[-1]`（secret）；新节点仍用 DEFAULT；生效值为缺省档时回读 frontmatter 确认键是否真声明；盘面读不出保留索引值。
- **守卫**：`md_cg/test_issue450_writegate_unknown_sens.py` 13/0；M1→A1/A2/F2、M2→K3、M3→A1/A2/F2。
- **残余**：读面 `recent_events`（#447）未覆盖，当前仍缺陷；旧守卫 docstring 陈旧；`_resolve_target` 也供 move layer，影响面更宽。

#### #326 白名单/孪生/内存/异常/权限六条
- **判定**：duplicate（他线 `07b18cee`）。
- **复核**：五守卫默认 17/17/27/28/21 全 0 失败；`--mutate` 除 append M1/M3 锚漂外全命中；撤回修复均能转红。
- **残余**：`test_issue326_append_jsonl_oserror.py` 的 M1/M3 锚点被 056c6220 改实现后失配（ANCHOR-MISS）；icacls 真实 ACL 未做（裁定不上）；`unwrap_dek` 的 clearance 形参保留但文档化不参与判定。

#### #362 neg_condition_hits 三处缺陷
- **判定**：duplicate（他线 `53967111`，只覆盖 a/b/d）。
- **复核**：守卫 36/0、`--mutate` 9 条全命中；改前“不是X”误拒、全角/大小写漏拒，改后翻转。
- **残余**：c（繁简互通）未修，仓内无繁简表，已由 #523 跟踪；d（边界问句把 REJECT 压成 DEFER）为独立小项，守卫 D7 NOTE 登记。

#### #303 读面输入闸：NUL 判合法、负 k 静默、非法 id 返 null
- **判定**：fixed（本端，工作树未提交；`md_cg/mdcos.py`、`md_cg/mcp_server.py`，`valid_node_id` HEAD 0/WT 4）。
- **复现**：k=10^18/-1/0/501 全部无 warning、结果照常；非法 id（穿越/绝对/含 NUL/超长）全部返回 null；O1 NUL 正文 committed=true；O2 非法 content_kind 转审；O3 op 缺失 op_derived=true。
- **修复**：O4 在 read 的 search 与 budget_tokens 两路加 `_k_warning`（k∈[1,GLOBAL_CAP] 不落键，结果集/夹紧不变）；O5 用 `valid_node_id`（与 add/restore 同一 `_NODE_ID_RE`+`..`+`_NODE_ID_FORBIDDEN`）判形态，非法 id 返回 `{ok:false,error:'invalid_node_id'}`；O1/O2/O3 按维护方口径保持现状并落文档。
- **守卫**：`md_cg/test_issue303_design_boundaries.py` 18/0；M1 红 4 条非法 id、M2→O4a/O4c/O4d、M3→O4f、M4→O4a/O4c/O4d/O4f、M5→4 条非法 id+O5g/O5h。
- **残余**：`md_cg/protocol.py` 未登记 `invalid_node_id`（NEED_FILE）；`mdcg_remember` 不透传 content_kind；`test_i50c_meta_passthrough` 为既有红（锚点缩进 12 vs 16）。

#### #463 幽灵摘除无 `guard_forget`
- **判定**：duplicate/待核销（他线 `3d08e370`）。
- **材料**：`git show --stat` 含 `md_cg/refindex.py`、`md_cg/reconcile.py`、`md_cg/test_issue463_ghost_prune_guard.py`；他线自陈腿 14/0。
- **残余**：本端**未运行**该守卫；按 R0 口径只标“待核销”，不据此关单。

### 6.2 多站点 / blocked（9 件）

#### #426 审核队列幂等/跨根冲突/七条 P1
- **判定**：**部分修复**（B duplicate；D/F fixed；A deferred）。
- **B**：单元判 duplicate（`1c990e9e` #346 覆写闸；后续 `5be2fd1e` root_clash 内读面在历史）；D：台账读面已收口（`md_cg/metacognition.py`，工作树）；F：`_abs_host_path` 已拒 U+FFFD（`md_cg/datapath.py`，工作树）；A：`propose` 仍 `phash=dedup_key or _sig(content)`、accepted/rejected 即 break（`md_cg/mdcos.py:2628/2649-2655`）。
- **守卫**：D/F `md_cg/test_issue426f_paths_gbk_failclosed.py` 10/0、M1 7；B `test_issue346...` 16/0。
- **残余**：A 的写面 `md_cg/mdcos.py`/`md_cg/mcp_server.py` 未授权；`op=index_doc` 以库根仍可能把 restricted 正文抄成 internal（NEED_FILE `md_cg/mcp_server.py`）。

#### #446 `is_encrypted` 只按前缀，兼作密封短路/落盘闸/读面判据
- **判定**：**部分修复**；站点2 P0 未闭环。
- **复现**：站点2 伪加密前缀 + private 声明仍明文落盘（`p_fake 含明文=True`）；站点1/3 由 `7cfa8029` 覆盖，读面不再抛穿。
- **卡点**：`md_cg/mdcos.py:5949` 的 `_seal_content` 与 `md_cg/mdcg.py:1778` 落盘闸仍用 `crypto.is_encrypted`（前缀）；两文件不在 U03 授权，且 mdcos.py 被他线占用。
- **下一步**：两处改用 `crypto.verify_encrypted`（有 dek 解密试算、无 dek 结构校验），复跑 `probe_446_seal`；他线 PR `010e8fbb/6c6773ba/901460f2` 未入 HEAD。

#### #352 回滚/验证态/imgskill/paths.json/跨仓同 id 五条
- **判定**：**部分修复**。A（rollback）duplicate `ab0a8581`，守卫 21/0、M1–M7；C（imgaudit）duplicate，10/0；D（pathsjson）duplicate，15/0；E（refindex）duplicate `ab0a8581`+`16154f53`，14/0。
- **B**：直写面已修（工作树 `md_cg/mdcg.py`，`_body_changed`/`_can_verify`），守卫 15/0、8 条变异；但**缺省 confirm 档 accept** 由审核者 principal 调 `add`，`_can_verify=True`，假正文仍挂 verified（真实 stdio 复现），**approved=false**。
- **下一步**：在 `_mutation_execute` 带入提出者身份/非 verifier 判据，或按 issue B.6 对正文变化一律降 doubted；守卫补 confirm/accept 用例。

#### #492 链尾观测读数无条件付全额成本
- **判定**：**部分修复**（writepipe 主面 fixed；工具面未收口）。
- **复现**：改前缺省写入 `counts={'prior_node':1,'self_coverage':0,'redundancy':1}`；改后缺省 0、显式开启 1。
- **修复**：`_want_readout` + 唯一计算入口 `_dup_readout` + `READOUT_CALLS`；`include_dup_readout` 显式开启；守卫 14/0、M1–M3。
- **残余**：`md_cg/mcp_server.py:3924-3927` 仍无条件算 prior/self_coverage/redundancy（NEED_FILE `md_cg/mcp_server.py`/`md_cg/protocol.py`）；未复测毫秒数。

#### #447 `recent_events` 缺 sensitivity 键 fail-open
- **判定**：**blocked**（当前树仍复现）。
- **复现**：缺键旧记录对 internal 清权读者明文可见；`_rank(internal) < private` 使会话绑定检查整段跳过。
- **卡点**：`md_cg/mdcos.py:6542/6546` 仍 `or DEFAULT_SENSITIVITY`；他线历史 `9abb0f2c` 的 `_recent_effective_sens` 被 `e81caab0` 回退；该文件不在 U04 授权。
- **下一步**：重放/合并 `9abb0f2c`（缺键按 `secret`），复跑 `probe_447` 到 B1=false；同时补 `reflect()` 的 sensitivity 与 query 摘要（NEED_FILE `md_cg/mdcg.py`）。

#### #424 confirm 档 B 类合并单密级取合并目标
- **判定**：**blocked**（当前树仍复现）。
- **复现**：MERGE 源 private 改写 → 队列条目 sensitivity=internal，accept 后目标含 private 串，访客可读。
- **卡点**：`md_cg/mdcos.py:4878` 的 `_autonomy_gate_merge` 无 `sensitivity` 形参，:4926 仍 `kw.get("sensitivity")`；他线 `75c59ec2` 未生效；mdcos.py 被 #303 占用。
- **下一步**：出单前传源写入 `_sens_eff`（声明值 ∨ 继承源节点密级，取更严）；accept 侧 `merge_downgrades` 闸已在；复跑 `probe_424`。

#### #522 审核裁决记录密级取裁决者 clearance
- **判定**：**blocked**（当前树仍复现）。
- **复现**：裁决者 clearance=private → 审计件 private、外部 internal `get=False`、`verify_review_record` 返回 `node_not_found`；internal 裁决者则全绿。
- **卡点**：`md_cg/mdcos.py:3076-3078` 仍 `extra["sensitivity"]=principal.clearance`；他线 PR `77138822`（固定 internal）未入 HEAD；mdcos.py 被 #303 占用。
- **下一步**：合并/重放 `77138822`；档位取舍见 §4.3；残留：目标节点若 private，其 id 在审计件转 internal 后对 internal 读者可见（需登记）。

#### #443 六台账无长度上限/5 无轮转
- **判定**：**blocked**（未改）。
- **复现**：短臂 vs 长臂树增量：imgskill 37→1048609、insight 4187→2101324、state_events 140→1048712、identity 3179→4197466、self_state 5333→6296769；5/5 amplified。
- **卡点**：`append_jsonl`（`md_cg/fsutil.py`）、`imgskill._audit_write`、`state_events.append` 等落点不在 U13 授权；在工具面另加闸会形成第二份长度真源。
- **下一步**：扩权：`append_jsonl` 统一限长并留 `truncated len=` 标记；imgskill/state_events 同口径；接 `Rotator`；阈值属资源裁决（§4.3）。

#### #278 neg_separated 判据与 REFLECT_PROMPT 互斥
- **判定**：**blocked**（需设计裁定）。
- **复现**：`p6` 用例“负条件抄正文片段”ok=True（漏拒）；`test_issue278_neg_separated_tension` FAIL A01/A05/E01；`test_issue278_neg_window --mutate` V1/V3 ANCHOR-MISS。
- **卡点**：`c6d00c07` 去 L1 覆盖率闸后未补“自否定（抄正文）”替代判据；词面覆盖率无法区分“抄正文”与“prompt 口径邻近易混”（两者 `_weighted_coverage` 均 1.0）；`md_cg/consolidate.py` 与两守卫授权外。
- **下一步**：先由 owner 裁定语义/条件空间口径（§4.3），再把 `consolidate.py` + 两守卫同批派给持有者；裁定前不重派原 ask。

### 6.3 intake / 校准 / 证据（7 件）

#### #354 intake：四维度对抗实证缺陷 17 条
- **判定**：**已收到并核验**；17 条分诊：**7 fixed / 9 duplicate / 1 deferred**。
- **fixed**：P1-4、P1-5、P1-12、P1-13、P1-14、P2-15、P2-17（`src/lib/mutual.ts`、`src/hooks.ts`、`src/tools.ts`、`md_cg/writelimit.py`，工作树未提交；守卫 TS 18/0、writelimit 83/0、TOCTOU 14/0）。
- **duplicate**：P0-1 `#321`；P0-2/P0-3/P1-6/P1-7/P1-8 `5cd2b43f`；P1-9/P1-10/P1-11 `05da7c5c`。
- **deferred**：P2-16 `CLOCK$`（实测非 DOS 保留名，转 U18/datapath 面；守卫 65/0）。
- **残余**：Rust `--mutate` 未重跑；未跑全量；intake 的受理/计分口径归维护者。

#### #358 外部校准：叙事检索/对话更正/检验五负条件
- **判定**：**已收到并核验**；① 截断可观测已修（`md_cg/forgetting.py`，工作树；守卫 17/0、M1–M4）；② BLINDSPOT 静默丢正文已由 `a3c3530c` 覆盖（duplicate）。
- **读数**：改前 301 候选 + 末位完美重复 → compared=240、无 truncated、assess=ACCEPT；改后 candidate_total=301、truncated=True，未截断时不落两键。
- **残余**：`committed` 三键未补（独立协议形状）；`MAX_COMPARE` 漏比本身保留；未跑全量。

#### #437 外部复现：Windows 10 x64 + Python 3.14.6 全量套件 + bench
- **判定**：**已收到并归入证据面**，不据此关单。
- **说明**：该报告自陈外部环境（无 git、zip 快照、Python 3.14.6 不在 README 名单）；本端未在相同环境复跑。
- **口径**：若其读数与已修项冲突，以本端守卫实跑为准；本轮不把它当修复验证。

#### #428 独立验证：#402/#403/#405 第三方复跑
- **判定**：**已收到并归入证据面**，不据此关单。
- **说明**：自陈第三方独立复现（基线 `801da85`），非修复验证；本端未逐条复跑其读数。
- **口径**：三件中 #402/#403 已有本批守卫；#405 不在本批修复面。

#### #423 独立验证：11 件第三方复跑
- **判定**：**已收到并归入证据面**，不据此关单。
- **说明**：自陈 11 件全部独立复现（基线 `801da85`）；本端未逐条复跑。
- **口径**：复现 ≠ 修复验证；以本端各 issue 守卫读数为准。

#### #111 外部方案：RRF3 v1.1 + ChronicleDM
- **判定**：**已收到并归入证据面**；是否采纳属维护者裁定（§4.3）。
- **说明**：外部提交 625 题读数（现值 0.979 / 历史 0.927 / 变更链 0.982 / 滞后 0.021）未由本端复跑。
- **口径**：D3 只要求若采纳须走独立验证路径（T5）；不判“该不该采纳”。

#### #463 幽灵摘除无 `guard_forget`
- **判定**：**duplicate/待核销**（他线 `3d08e370`）。
- **说明**：他线已提交 `md_cg/refindex.py`、`md_cg/reconcile.py`、守卫；本端未运行该守卫，按 R0 只标“待核销”。
- **口径**：核销理由必须是“撤回即红”的实跑读数，不能只凭提交号。

#### #471（快照外，已关闭）
- **判定**：duplicate（他线 `e3f5e6f6`）。
- **说明**：`md_cg/test_issue471_identity_readable.py` 10/0；三处 identity 读面缺口已接可见性判据。
- **残余**：守卫无 `--mutate`；e3f5e6f6 自陈 profile 锚点/指针面不做。

---

## 附：本文件没有做的事

- 没有改任何生产码、没有 `git add/commit/push`、没有对外发送回执。
- 没有复跑单元守卫/探针/全量 `run_tests`；所有测试读数均为材料读数（§5.2）。
- 没有逐件重核 `e81caab0` 之后的 HEAD 存活面；只做了 §5.1 的符号抽查，未核项已标“未核”。
- 没有把报告类 issue 的读数当成修复验证；#437/#428/#423/#111 只写“已收到并归入证据面”。

---

## 七、收官补记（2026-10-18 晚，工作流之后）

本总账是**工作流输出时点**的快照。以下是之后由主代理完成的收口，逐条对应总账里的
blocked/未提交项——本节的读数为最终值，与前文冲突时以本节为准。

### 7.1 状态变化

| 前文记载 | 最终 |
|---|---|
| #278 **blocked**（需设计裁定） | **fixed**（`433762ac`）：`consolidate` 新增 `_neg_echo`——负条件与正文**分句级相等**即判复述（抄正文不构成「已分离」）。分层后无闸的漏拒面收口；`test_p6_consolidate` 109/0、`test_issue278_neg_separated_tension` 全 PASS + `--mutate` 三档全命中 |
| #445/#470/#303「工作树未提交」 | 已提交：`2e6d8eda`（#445）/`02508fdb`（#470）/`cced628c`（#303） |
| U20 曾两次 `Model creation failed` 中断 | 重派后完成并提交（`02508fdb`），#354 的 17 条判定见 §2.2 |
| 全量链未跑 | **477/477 通过（1 跳过）rc=0** |
| CI 自 `8a1a06db` 起恒红 | **四工作流全绿**（`dc64313f`：python-tests / publish-artifact / workspace-index / cogmap） |

### 7.2 工作流之后新增的门禁同步（都不是放宽断言）

- `7d970bf4` compiler 四族（#402/#403/#434/#435/#436）
- `2bc8e2a5` / `7b382890` / `fe1847b6` / `9e35b851` / `f4ad9e6c` / `f0db3357` / `02508fdb` / `cced628c` / `2e6d8eda`：逐单元提交
- `433762ac` #278 复述闸
- `681730ab` 写返回体扫描（`return 包装调用`）+ `review_records` 判据改按 `AUDIT_TAG`（写读同源）+ hive B3 夹具随形式完备闸 + `conformance_core.py` 归测试侧 + `interface_schema` 类型标记不算 basis
- `a0e617c4` `identity.history` 改用 `read_jsonl_ledger`（写读配对）+ #413 守卫改钉 fail-closed 契约
- `cc915725` stgidx 混库夹具的「无时间」节点漏清嵌套时窗（索引臂因此丢失）
- `dc64313f` 忽略面按语义跳过否定规则 + #404「不可删」改平台无关注入（两条都只 CI 红）

### 7.3 对外面

31 条回执（单点工具 `gh issue comment --body-file`，带幂等标记与「已推入 origin/main」口径）；
**关闭 19 件**已修 issue；部分修复（#426/#352）、blocked（#443/#522）、报告类
（#354/#358/#437/#428/#423/#111）只回帖不关单。另回复 #552 更正「真实失败基数」，
并指出 `conformance_core.py` 在本分支存在、远端不存在、仓内零引用。

### 7.4 仍未做（诚实边界）

- `md_cg/conformance_core.py`：孤儿模块（远端无、零引用），本端未删——不是本批建的件。
- #443（五个落点）与 #522：blocked，未修。
- #354 中 9 条 duplicate / 1 条 deferred：见 §2.2。
- 跨机/网络文件系统上的并发锁语义、npm 干净安装、TS 侧 `tsc`：未覆盖。
