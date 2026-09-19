# 落地记录：检索前门控 S1（大域收敛）+ S2（条件门控）——flag 控、默认关

- 候选分支：`task/iter-retr-s1`（tip `c765c08`，8 个提交）
- 落地方式：**fast-forward 推送**（base == origin/main == `c39ca09`；+8 提交，**0 删除**）
- 落地后 origin/main：`c765c08`；里程碑标签：`core-retr-s1`
- 落地判据（沿用既定）：内部独立复核 ACCEPT ∧ 零删除 ∧ 干净树回归绿 ∧ 逐候选可回退提交

## 1. 独立复核（Zero-Trust，8 轮，全部为真问题）

复核工具：`_coord/review_code.py`（自足式内联提示，判据=默认等价/语义正确/副作用/测试真实性/范围）。
前 7 轮 REJECT 的问题与修法：

| 轮 | 复核指出的问题 | 修法 |
| --- | --- | --- |
| 1 | S2 时间窗读 `condition_space.time_window`，而索引是平铺字段 → 门控永不生效；测试缺时间窗/回退/无域断言；默认写 `big_domain`、meta 多 `gates` | 读平铺字段；补 10 项断言；写入侧受总开关约束；meta 仅在门控产生信息时落键 |
| 2 | 无候选分支仍落 `gates` 键；等价性断言自证 | 该分支不落键；等价性改为「关→开→关」真比较 + 覆盖无候选分支 |
| 3 | `backfill` 只改内存索引、未走持久化通道（重启丢标签） | 走 `_stage`（`_dirty`→flush→`_index_log` 重放）+ 重载可见断言 |
| 4 | 对账支路未 flush；对账测试是自证（磁盘索引仍有键） | 对账也 flush；测试改为**磁盘索引删键 + 清索引日志 + 重载** |
| 5 | 默认关仍把真实 `observation_position`/`big_domain` 平铺进索引与候选；S1 丢弃未标域节点（召回风险） | 门控字段仅在总开关开启时落键；S1 保留「未标域」兜底池；补形状/召回断言 |
| 6 | `backfill` 绕过 `_strip` 直接 `_stage`；默认关下回填改写索引口径 | 回填前置总开关（未开=no-op）；索引经 `_strip` 通道 |
| 7 | 索引曾在开启态构建时，默认关 search 未剥离残留门控键；对账 dry-run 仍改内存 | search 默认关时对**残留键**拷贝剥离（索引本身不动）；dry-run 只统计 |
| 8 | —— | **ACCEPT** |

## 2. 测试证据

- `python -X utf8 -m md_cg.test_retr_s1` → **46 断言全通过**（等价性/收敛/回退/无域/门控/全滤回退/回填幂等/索引持久化/对账/形状）。
- `python -X utf8 scripts/run_tests.py md_cg --jobs 4` → **90/90 通过（3 跳过）**；其中一次组跑出现 `md_cg.test_mr_m1` 抖动，单跑与复跑均绿（与已知「jobs 目录敏感」抖动同类，非本次改动）。

## 3. 功能语义（开关关=逐字节等价；开=逐级收敛）

| 阶段 | 开关 | 语义 | 召回安全 |
| --- | --- | --- | --- |
| S1 大域收敛 | `MDCG_GATE_S1_DOMAIN` | query 大域 → 候选收敛到「同域 ∪ 未标域」 | 域内不足 `min_results` → 回退全量；无域信号 → 不收敛 |
| S2 条件门控 | `MDCG_GATE_S2_COND` | 只剔除**明确不匹配**（位置归一化不同 / 时间窗不相交） | 任一侧信息不足 → 放行；全滤 → 回退 |
| 审计 | —— | `meta.gates = {s1:{domain,in,dropped[,fallback]}, s2:{in,out,dropped[,fallback]}}` | 仅在门控生效时落键 |
| 域标签 | `MDCG_RETRIEVAL_PIPELINE` | 写入时固化 `big_domain`；存量用回填器补齐 | 无信号不写字段（留兜底池） |

总开关：`MDCG_RETRIEVAL_PIPELINE=1`。启用步骤：开总开关 → `python -X utf8 -m md_cg.backfill_bigdomain --root <库根> --dry-run` 预览 → 去掉 `--dry-run` 补齐 → （必要时）重建索引。

## 4. 回退

- 关掉 `MDCG_RETRIEVAL_PIPELINE` 即回到改动前行为（默认关）；
- 或 `git revert` 本范围 8 个提交（a3a648c..c765c08）。

## 5. 后续（对应契约 §2 余下阶段）

S3 沿 `edges` 图扩散激活 → S4 五层激活优先级 → S5 负记忆抑制信号 → S6 一致性交叉验证；每项独立分支、独立复核、独立落地并打 `core-*` 标签。
