# 灵枢 · 已知红名单（known-red）

> 基线读数来源：`python scripts/run_tests.py md_cg --jobs 1 --timeout 300`
> 口径：**串行 --jobs 1（无并发噪声）**
> 观测时刻：2026-11-10 19:23（日志 mtime），日志 `run_tests_serial.log`
> 总读数：**PASS 275 / FAIL 84 / SKIP 3（359 目标）**

## 这张表的用途

不是「可以忽略的红」，而是「**动代码前必须先知道的既有红**」。
任何改动之后重跑全量，与本表比对：

- 本表里的条目**消失** ⇒ 变好了，删掉对应行
- 出现**本表没有**的条目 ⇒ 新回归，`git checkout` 回退
- 本表的条目**原因变了** ⇒ 停下核对（可能被别的改动干扰）

## 统计

| 类别 | 条数 | 性质 |
|---|---|---|
| 默认值/契约漂移 | 14 | — |
| 超时（>300 s，需定性为性能或死循环） | 2 | — |
| 环境依赖缺失（设计内 fail-closed，不是代码缺陷） | 2 | — |
| 硬崩（KeyError 等未捕获异常） | 6 | — |
| 守卫锚点漂移（变异自证 fail-closed） | 4 | — |
| 行为回归（断言不满足，待逐条定性） | 56 | — |
| **合计** | **84** | — |

---

## 默认值/契约漂移（14 条）

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_action_derive` | 失败项：B4 推导目标 action 在分支中被识别：review |
| `md_cg.test_b1_foreign_read` | - ②跨身份读拿不到内容（预期隔离） / - ②b记 read_foreign（0→0） / - ③跨身份读仍拿不到内容 |
| `md_cg.test_h4_sustain_snapshot` | PASS G4b 目标级（真线程，默认 switchinterval）：写 110 条 + 全默认 diagnose 对撞零 RuntimeError / PASS G4c 目标级（真线程，switchinterval=1e-6）：写 80 条 + 全默认 diagnose 对撞零 RuntimeError / PASS G5 真实并发（写 54 条 + 巡检对撞）零异常 |
| `md_cg.test_issue43_default_policy` | PASS G8-str F op=info 仍返回正常载荷且 write_policy 报不可用+code / PASS G8-Str G 字符串键未被拆成单字符规则（计数=0，非长度 27） / PASS G8-Str H 消费面纵深：直喂标量 rules 不按字符建规则（旧写法同输入 ⇒ 27 条单字符规则） |
| `md_cg.test_issue52_scan_condition_first` | FAIL D6b desc=False 升序（(start,end,id) 序不变） / PASS D6c session="*" 与缺省同义（跨会话读全） / == G5 结构：_scan 内不再有索引序切片（AST 判据） == |
| `md_cg.test_p3_legacy_closure` | OK   D 类型集只从 EDGE_WEIGHTS 里挑子集（t in EDGE_WEIGHTS） / OK   D 方向固定为依赖方向（出边）：walk 缺省 direction == 'out' / OK   D 措辞已改准（docstring 写明「部分满足」与三件口径） |
| `md_cg.test_p4_freshness` | OK   temporal_gamma() 常数级（修前 = 1×N；γ 的实际读取点） / OK   自证腿：全缺省签名仍自算（四路 spy 各 ≥1，判别力在位） / OK   显式 enabled+now+γ 透传与自算同值（逐位一致） |
| `md_cg.test_retr_s5` | [PASS] 无负记忆命中：不落 s5 审计 / [PASS] S5 幂等：重复检索同口径 / [PASS] S5 幂等：索引重建后同口径 |
| `md_cg.test_t24a_split` | [PASS] 今天把 report.pdf 生成一下，我主力语言是 Pyt...：fm 正文 == 整句输入 / [PASS] 帮我生成一份报告，我的性格是喜欢简洁的...：默认关 add 成功写入（got=t24a_def_1） / [PASS] 帮我生成一份报告，我的性格是喜欢简洁的...：fm 无判定字段夹带 |
| `md_cg.test_t63a_access_count` | FAIL  G2c 重开后索引仍读到 access_count=0（真落盘，非内存假象） / FAIL  G2d 重开后 last_access 仍是有效时间戳（0） / FAIL  G6d 缺省 True 时计数递增（0 → 0） |
| `md_cg.test_t65a_supersede_real` | [FAIL] mdcg._supersede_try 存在（E-T15a t1 交付点）  attr=None / [PASS] is_enabled() 在未设 MDCG_JUDGMENT 时为 False（默认关） / [PASS] is_enabled() 在显式 1 时为 True |
| `md_cg.test_t91a_scrub_ledger` | FAIL [G1] 缺省（auto_scrub 取真源 False）的 tick 也记 dry_run=True：False/None / t91a_scrub_ledger: 34 passed, 3 failed / - [G1] auto_scrub=True 的 tick：last_scrub dry_run/auto_scrub = False/None |
| `md_cg.test_t98a_default_strict` | a2u_ihdf\\\\\\\\weak\\\\\\\\_signers.json\'（realpath → \'C:\\\\\\\\Users\\\\\\\\Raven243\\\\\\\\AppData\\\\\\\\Local\\\\\\\\Temp\\\\\\\\t98a_a2u_ihdf\\\\\\\\weak\\\\\\\\_signers.json\'） 不在受信目录 \'C:\\\\\\\\Users\\\\\\\\Ra… |
| `md_cg.test_validity_filter` | [PASS] ⑦mdcg_recall 透传 validity（expired 剔除） / [FAIL] ⑦默认关：mdcg_recall 缺省 expired 可见  · [{'id': 'mem_future', 'score': 0.016393, 'state': 'BLINDSPOT', 'tokens': 12, 'content': '量子咖啡机萃取压力曲线 下一代规格预告\n', 'frontmatter': {'acc… |

## 超时（>300 s，需定性为性能或死循环）（2 条）

**需定性**：是性能问题还是死循环。已知候选：`_clip_text` 在 `max_lines=0` 时 `next_offset` 不推进（修理表 P3「算法/口径细节」）。

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_mr_m1` | 超时（>300s） |
| `md_cg.test_time_core_lint` | 超时（>300s） |

## 环境依赖缺失（设计内 fail-closed，不是代码缺陷）（2 条）

**这不是缺陷**：该守卫明确拒绝「静默 SKIP 返回 0」，跑不起来就退 1。前置是 `cd rust && cargo build --release`。

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_rank_parity_score_mode` | !! rust release 二进制缺失：D:\wook\lingshu-src\rust\target\release\mdcg-eval.exe |
| `md_cg.test_unify_default_off` | !! rust release 二进制缺失：D:\wook\lingshu-src\rust\target\release\mdcg-eval.exe |

## 硬崩（KeyError 等未捕获异常）（6 条）

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_issue75_neural_failure` | [neural_retrieve] 降级 stage=search_index exc=KeyError: 'vectors_normed' |
| `md_cg.test_j1_whitebox_sealed` | KeyError: 'sealed_skipped' |
| `md_cg.test_t09a_demand_drop` | KeyError: 'verdict' |
| `md_cg.test_t10a_procedural` | KeyError: 'verdict' |
| `md_cg.test_t11a_noise_drop` | KeyError: 'verdict' |
| `md_cg.test_t18a_judgment` | KeyError: 'verdict' |

## 守卫锚点漂移（变异自证 fail-closed）（4 条）

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_i50c_meta_passthrough` | ANCHOR-MISS 变异锚点缺失：accept 不再映射 condition_space（削弱既有映射）（锚点 '                           condition_space=item.get("conditi'） / ANCHOR-MISS 变异锚点缺失：merge 不再并集不适用条件（既有职责）（锚点 '            neg = list(fm.get("non_applicable_condi… |
| `md_cg.test_i50e_readside_protection` | ANCHOR-MISS 变异锚点缺失：'(_src is None or _src == "hint")' @is_protected / ANCHOR-MISS 变异锚点缺失：'    _src = fm.get("importance_source")\n    if imp >= AUTO_PROTECT_IMPORTANCE and (_src is None or _src == "hint"):\n        retur… |
| `md_cg.test_mutation_rollback` | ANCHOR-MISS 变异锚点缺失：'    ts = (time.strftime("%Y%m%d-%H%M%S",' @md_cg.protect.snapshot_preimage |
| `md_cg.test_p45_session_identity` | ANCHOR-MISS 锚点漂移（命中 0 次，期望恰好 1）：'        if session and str(session).strip() != "*":\n            evs = ' / ANCHOR-MISS 锚点漂移（命中 0 次，期望恰好 1）：'if session and str(session).strip() != "*":' |

## 行为回归（断言不满足，待逐条定性）（56 条）

| 测试 | 失败项（原文摘要） |
|---|---|
| `md_cg.test_audit_rotate_parity` | got = _sha(os.path.join(root, rel)) / ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ / File "D:\wook\lingshu-src\md_cg\test_audit_rotate_parity.py", line 99, in _sha |
| `md_cg.test_autonomy_modes` | 不满足：缺 R1、R2、R3、R4 ——实际生效档位回落 confirm（不静默降级；读数详情：python -X utf8 -m md_cg.admission --root "C:\Users\Raven243\AppData\Local\Temp\autonomy_modes_sandbox_sbi3f6ox\l_empty_r0"）。 / [MdCG 三档自治] MDCG_AUTONOMY=full 但准入读数不满足：缺 R1、… |
| `md_cg.test_b4_shard_dir_selfheal` | - B4-D5·生产链自愈也告警（stderr 含「缺失」与 _index_log） |
| `md_cg.test_b4_shard_dir_selfheal_guard` | File "C:\Users\Raven243\AppData\Local\Programs\Python\Python311\Lib\shutil.py", line 615, in _rmtree_unsafe / onerror(os.scandir, path, sys.exc_info()) / File "C:\Users\Raven243\AppData\Local\Programs\Python\Python311\Li… |
| `md_cg.test_c8_search_rrf_gates` | FAIL P6a MdCGOS.search 源码引用共享门控 apply_retrieval_gates / OK   P6a MdCGOS.search_rrf 源码引用共享门控 apply_retrieval_gates / OK   P6b MdCGSecure.search_rrf 经 super().search_rrf 委托（不自建门控） |
| `md_cg.test_ccg_prose` | PASS D1 超长截断带省略号 120 / FAIL E1 回包有内容 0 / PASS E2 每条都带 plain |
| `md_cg.test_export_snapshots` | PermissionError: export：辅助存储根无法解析，导出落点不可校验（fail-closed 拒）：MDCG_AUX_ROOT 归一后末段是 Windows 保留设备名（'C:\\Users\\Raven243\\AppData\\Local\\Temp\\mdcg-export-xi7s8jg0\\aux'）：GetFullPathNameW 可能把整个目录吞成设备路径（\\.\aux 形态，目录语义静默丢失）；较新 … |
| `md_cg.test_fuzzy_substring_equivalence` | Diff is 7033 characters long. Set self.maxDiff to None to see it. / ---------------------------------------------------------------------- / Ran 6 tests in 0.442s |
| `md_cg.test_g1_tenant_sharing` | - ⑥共享签发：两 actor 得同一把 DEK / - ⑥d重建读方仍是同一把 DEK / - ②b批量只写 1 条 read_cross_actor_batch（O(1) 不放大） |
| `md_cg.test_generation_guard` | [PASS] 四·调用点 —— 1 处调用全在函数体内：main:5803 / == 五 键集对拍：cg(op=info) 真调（临时 root） == / [FAIL] 五·键集 —— 既有键集被改动：多出 ['flush_state', 'full', 'node_count', 'write_gate'] / 丢失 ['bucket_scope', 'buckets', 'ccg_by_layer', 'neg_memory_co… |
| `md_cg.test_issue89a_score_cap_tiebreak` | 失败项：G6 三处排序点 + 携带 + 剥离共 5 类锚点齐备（计数） |
| `md_cg.test_n123_derive_expiry_chain` | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ / File "D:\wook\lingshu-src\md_cg\tokens.py", line 608, in issue / _authorize_issue(role, spec, path=path, authorized_by=_authorized_by, |
| `md_cg.test_n204_n205_n226_n227_n228_n229_exit_gates` | 失败项：4e 设计者 info 面仍带私密台账行（治理面不掏空） |
| `md_cg.test_n209_verify_write_face_gates` | [PASS] 5e 实弹断言计数下限（防某条腿被静默跳过/提前 return） / [RESULT] 21 passed / 2 failed · live=16 / 失败清单： |
| `md_cg.test_n230_dirty_replay` | i = src.index("for nid, e in self._dirty.items():") / ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ / ValueError: substring not found |
| `md_cg.test_n62_tenant_bind_failclosed` | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ / File "D:\wook\lingshu-src\md_cg\tokens.py", line 608, in issue / _authorize_issue(role, spec, path=path, authorized_by=_authorized_by, |
| `md_cg.test_neg_condition_hits` | PASS G6f 行为逐字一致：无冒号形态两侧取到同一个非空值（旧副本在此返回空串） / == G7 端到端（临时库真建节点）== / PASS G7 自主题问句不再 REJECT（state=DEFER） |
| `md_cg.test_p15_scrub` | TypeError: 'NoneType' object is not subscriptable / [fsutil] ShardedLog 分片目录缺失，已重建（目录 _index_log，调用点 append）——本进程持有的分片实例不自愈；本次后进程内累计重建 1 次。排查方向：库根 _index_log/ 被外部清理/还原删掉，或库根被换过；正文 .md 未受影响，索引缺口由重放/全库扫描补齐。 |
| `md_cg.test_p21_tokens` | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ / File "D:\wook\lingshu-src\md_cg\tokens.py", line 608, in issue / _authorize_issue(role, spec, path=path, authorized_by=_authorized_by, |
| `md_cg.test_p24_evidence` | File "D:\wook\lingshu-src\md_cg\signer.py", line 366, in load_policies / p = signers_file(path) / ^^^^^^^^^^^^^^^^^^ |
| `md_cg.test_p27_docindex` | ^^^^^^^^^^^^^^^^ / File "D:\wook\lingshu-src\md_cg\mcp_server.py", line 3973, in _ref_call / check_path_root( |
| `md_cg.test_p28_refcheck` | - 7①同一 id 只留一条节点，ref.root 为后写域（现状钉子，非期望语义） |
| `md_cg.test_p2_mcp` | 失败项：cg info 自描述审核体系 |
| `md_cg.test_p2_six_elements` | == G7 旧库零破坏（条目缺键 / 旧签名）== / FAIL 条目缺两键 → 判 False（未重建的旧快照退回旧行为）  {'hit': False, 'post': False, 'reject': False, 'why': [], 'post_source': None, 'reject_source': None} / OK   _like 三参旧签名：按 positive_body 命中 |
| `md_cg.test_p32_backfill` | 失败项： |
| `md_cg.test_p33_ccg_wiring` | [fsutil] ShardedLog 分片目录缺失，已重建（目录 _index_log，调用点 append）——本进程持有的分片实例不自愈；本次后进程内累计重建 1 次。排查方向：库根 _index_log/ 被外部清理/还原删掉，或库根被换过；正文 .md 未受影响，索引缺口由重放/全库扫描补齐。 |
| `md_cg.test_p40_refine_worklist` | 【14】未知 action 不静默成功 / ====================================================================== / P40 结果：PASS 43 / FAIL 3 |
| `md_cg.test_p42_provenance` | 未通过：⑥父端点缺失可检出 |
| `md_cg.test_p43_pooling` | - (8) 换表即换行为（doc_0: base×0.3=0.041329 → 0.068881） / - (9) 结果构成对分池敏感（0.22 → 0.22） / - (9) 池级截断损失仅启用态可算（关=0.5 开=0.5） |
| `md_cg.test_p47_session_view` | 失败项：B6 具体值只取本会话（他人 private 经授权面剔除）, B7 返回体 session=生效值（非跨会话）, B8 另一会话只取它的节点（含其绑定档）, C3 rebuild 后按会话过滤不静默全空, G1 请求级会话在本调用内生效 |
| `md_cg.test_p9c_dedup_hints` | [PASS] E · 非保护（0.1）+ 近重复  · dedup_skipped=无（期望 无） · verdict=MERGE / 失败项：B2 经链直写也带 dup_of（第二处落盘点同样接线上）、B3 经链直写 dup_ratio 读数存在、B4 经链直写覆写读数存在 |
| `md_cg.test_predict_beta` | File "D:\wook\lingshu-src\md_cg\test_predict_beta.py", line 135, in <module> / main() / File "D:\wook\lingshu-src\md_cg\test_predict_beta.py", line 107, in main |
| `md_cg.test_reach` | 失败项：(4) 单字符 term → 不收敛 |
| `md_cg.test_read_face_input_gates` | 失败项：M1-B4 k 族旧写法全量清零（含 k→n / k→limit 链式） |
| `md_cg.test_readcache_prodpath` | [fsutil] ShardedLog 分片目录缺失，已重建（目录 _index_log，调用点 append）——本进程持有的分片实例不自愈；本次后进程内累计重建 1 次。排查方向：库根 _index_log/ 被外部清理/还原删掉，或库根被换过；正文 .md 未受影响，索引缺口由重放/全库扫描补齐。 |
| `md_cg.test_retr_gates_prodpath` | == P4 覆写防悬空（病灶复发形态的结构守卫）== / FAIL P4a MdCGOS.search 引用共享门控 / OK   P4b MdCG.search 引用共享门控 |
| `md_cg.test_review_queue_batch` | 失败项：G6 加固：AST 枚举 review_cli 的 cg 面，全部落在白名单内 |
| `md_cg.test_state_event_op` | raise TokenError( / md_cg.tokens.TokenError: 拒绝签发管理级令牌（role=designer）：凭据库非空（已有 4 条），而本次签发未出示既有管理级凭据。三条放行方式：① 由既有 designer 令牌经 tokens derive --role designer 派生；② 显式设 MDCG_ALLOW_ROOT_ISSUE=1（运维放行）；③ 全新安装（凭据库为空）时本闸自动放行。（iss… |
| `md_cg.test_stgidx_index_parity` | PASS G6e 与 read 面单点 judge_qualification 逐条同口径（未另写判据） / == G7 结构：资格判据唯一调用点 / _scan 无切片 == / PASS G7a stg 侧 judge_qualification 恰一处调用（不另写第二套资格判据） |
| `md_cg.test_t12a_short_ttl` | TypeError: float() argument must be a string or a real number, not 'NoneType' |
| `md_cg.test_t13a_acceptance` | TypeError: SustainLoop.__init__() got an unexpected keyword argument 'sink_interval' / 失败项：运行期无未捕获异常 |
| `md_cg.test_t13a_sink_demote` | 失败项：G01 无注入 ⇒ source=default_file |
| `md_cg.test_t13a_sink_e2e` | TypeError: SustainLoop.__init__() got an unexpected keyword argument 'sink_interval' / 失败项：运行期无未捕获异常 |
| `md_cg.test_t13a_sink_trash` | 失败项：G11 已降层的受保护节点 ⇒ 盘点面归入 excluded_protected，G11 该节点不进 candidates（受保护优先于候选），G11 实修面同样 skipped_protected（且没搬），G11 该节点文件仍在原处、trash 里没有 |
| `md_cg.test_t15a_supersede` | [PASS] 未设开关时同 key 仍 2 个节点 / [PASS] fm 无 superseded 字段 / [PASS] 显式0时同 key 仍 2 个节点 |
| `md_cg.test_t16a_session_boundary` | [PASS] C10 对照非 DROP：记住我的邮箱 / [PASS] C11 add() 对照：记住我的邮箱 返回节点ID、节点存在 / [FAIL] C12 对照节点存在且 sensitivity 有效（非 None、非空串）  sensitivity=None |
| `md_cg.test_t25a_auto_drop` | [PASS]   └ fm 无判定字段夹带（逐字节一致）：把日志清理一下 / [PASS] 显式0 remember_event 返回体形状不变（仅 event/dropped 两键） / [PASS] 显式0 remember_event 正文原样进窗（未被判定面改写） |
| `md_cg.test_t31a_whykept` | [FAIL] 关闭/=0 role=command 事件照常进窗（无 verdict / why_kept 键夹带）  {'event': {'t': 1794309386.9126353, 'role': 'command', 'text': 'pytest -k login', 'tags': [], 'meta': {'actor': None}, 'id': 're_1794309386912_e9949c'}, 'droppe… |
| `md_cg.test_t63a_mcp_record` | FAIL  G1g mdcg_reflect 不再关记数 / FAIL  G2a route 命中后 _access.log 新增行（0 → 0） / FAIL  G2b 新增行含命中节点 id（record 确已流到 cg.search） |
| `md_cg.test_t64a_dedup` | AttributeError: module 'md_cg.mdcg' has no attribute 'DEDUP_MERGE_COUNT_FIELD' |
| `md_cg.test_t91a_consolidate_prose` | - ③ 二轮后该节点仍只有 1 条留痕条目 / - ④ induce 新增键 prose/prose_written（纯增） / - ④ promote 新增键 prose/prose_written（纯增） |
| `md_cg.test_t96a_op_reachability` | - export 已 daily 可达 / - index_code 已 daily 可达 / - index_doc 已 daily 可达 |
| `md_cg.test_t98a_protect_override` | File "D:\wook\lingshu-src\md_cg\test_t98a_protect_override.py", line 150, in _g1_allow_denies_without_authorization / r = protect._allow(cg, nid, "测试原因", "override_write", / ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^… |
| `md_cg.test_tg4c_acceptance` | 失败项：A01 ccg_completeness.complete is True（六要素齐全），A01 六行齐全（功能名/生效条件/子功能/执行/验证方式/不适用条件） |
| `md_cg.test_twophase` | 失败项：①5 指纹走 nodefile 唯一真源（含写盘尾换行归一）、⑩3 指纹算法与 nodefile 同源（唯一真源，防漂移） |
| `md_cg.test_vector_lane` | PASS   B3 模型缺失不拖垮检索 results=3 paths=['bucket', 'chain', 'entity', 'graph', 'lexical', 'temporal', 'vector'] |

---

## 附：SKIP（3 条，附原因，不是假绿）

| 测试 | 原因 |
|---|---|
| `md_cg.test_md_access_parity  （依赖 md 语料真源 _md_cg_wisdom_graph/（.gitignore 忽略，组 D 需本地真源））` | — |
| `md_cg.test_p44_md_whitebox  （依赖 md 语料真源 _md_cg_wisdom_graph/（.gitignore 忽略，组 D 需本地真源））` | — |
| `md_cg.test_wisdom_md_store  （依赖 md 语料真源 _md_cg_wisdom_graph/（.gitignore 忽略，组 D 需本地真源））` | — |
