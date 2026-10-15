# dsh-memory：5 项缺陷修复（2026-10-15 审计）

基线 `e39d2f8bd8dd65ed5a0f17d3c8b884300fd671c9`。5 项缺陷各有修前复现、最小修复、修后读数与反例自证。设计背景与代码解析见 [dsh_memory_code_analysis_20261015.md](../dsh_memory_code_analysis_20261015.md)。

## 修复总表

| # | 缺陷 | 修前 → 修后 | 源仓库记录 |
|---|---|---|---|
| 1 | `state_event` 空串撤回不使槽位退役 | `active / 空串 / retired=0` → `retired / None / retired=1` | [#375](<https://github.com/FuRongJun-1999/dsh-memory/issues/375>) |
| 2 | 负条件匹配不做字符归一 | 全角/半角、大小写不同即漏拒，端到端 DEFER → REJECT | [#362 修复证据](<https://github.com/FuRongJun-1999/dsh-memory/issues/362#issuecomment-6190441655>) |
| 3 | 衰减保护下界只认显式 protected 位 | 层保护与按分保护节点 floor `0.001` → `0.777778`（重要度 0.90）；Python 与 Rust 装载器同步 | [#378](<https://github.com/FuRongJun-1999/dsh-memory/issues/378>) |
| 4 | trust/lifecycle 状态降级漏层保护 | anchor 节点 verified→doubted 放行落盘 → `error=protected` 零落盘 | [#377](<https://github.com/FuRongJun-1999/dsh-memory/issues/377>) |
| 5 | 心跳统计丢失败行、失败心跳计入正常周期 | `n=4`、reflect 档 `absent=True` → `n=3`、`failed=3`、reflect 档 `absent=False` | [#376](<https://github.com/FuRongJun-1999/dsh-memory/issues/376>) |

第 2 项只覆盖 #362 的宽度与大小写；否定作用域、繁简、边界问句不在本次范围。

## 代码改动

- `md_cg/state_slots.py`：撤回判据识别 None 与空白字符串，台账原值不改写。
- `md_cg/mdcg.py`：`neg_condition_hits` 对情境、负条件与自身主题统一 NFKC + casefold。
- `md_cg/protect.py`：抽出纯判据 `is_protected_metadata(fm)`；`is_protected` 取元数据后委托该纯判据。
- `md_cg/freshness.py`：衰减下界经同一纯判据；取数键补 `layer`、`importance_source`。
- `rust/src/store.rs`：装载器按同一三条规则计算保护布尔，阈值与来源规则不变。
- `md_cg/trust.py`、`md_cg/lifecycle.py`：降级豁免并上同一纯判据，保留 immutable 与 override。
- `md_cg/sustain.py`：时间序列只取成功 beat；失败 beat 与 tick 进 `failed`/`failures`。
- `docs/eval/心跳台账_v0.1.md`：同步统计口径与新增字段。
- 新增定点守卫：`md_cg/test_audit_{state,write,protection,heartbeat}_20261015.py`；两处旧夹具随修法同步（`test_p4_freshness.py` 未保护样本 0.8→0.5，`test_n209…` 同层控制腿补 `override=True`）。

## 修后读数

| 守卫 | 修后 | 反例自证 |
|---|---|---|
| test_audit_state_20261015 | 17 通过 / 0 失败 | 撤回判据还原只认 None → 9 条断言红 |
| test_audit_write_20261015 | 6 通过 / 0 失败 | 归一函数退化为恒等 → 4 条断言红 |
| test_audit_protection_20261015 | 39 通过 / 0 失败 | 4 个变异各自转红（下界只认显式位 17 条、丢 layer 8 条、trust 位判据 4 条、lifecycle 位判据 2 条） |
| test_audit_heartbeat_20261015 | 19 通过 / 0 失败 | 恢复旧过滤 5 条红、忽略 ok 9 条红 |
| cargo test --offline（rust/） | 38 通过 / 0 失败 | 隔离副本恢复旧布尔 → 指定行为断言失败（factor=0.001），退出码 101 |

旧守卫回归全部通过：

| 守卫 | 结果 |
|---|---|
| test_state_slots / test_neg_condition_hits / test_i50e_readside_protection | 71/0、39/0、53/0（三变异 11/10/10 红） |
| test_heartbeat_ledger / test_p14_sustain / test_sustain_bounded | 38/0、44/0、60/0 |
| test_sustain_mutual / test_h4_sustain_snapshot / test_sleep_p1 | 12/0、43/0、135/0 |
| test_trust / test_lifecycle / test_n209 / test_p4_freshness / test_stgidx_index_parity | 127/0、55/0、23/0、89/0、51/0 |

## 关键实测读数

- 撤回（修前 → 修后）：`new=""` 得到 `('active', '', 0, 1)` → `('retired', None, 1, 0)`，与 `new=None` 对照一致。
- 归一（修前 → 修后）：负条件“４Ｇ单模终端”对问句“4G 单模终端”由不命中到命中；端到端资格 DEFER → REJECT。
- 衰减（Rust 真实装载，重要度 0.90、半衰期 30 天、老化 300 天）：层保护与 hint/缺省来源乘子 `0.00100000000000000` → `0.77777777777777768`。
  乘回重要度与常量 0.70 按 double 逐位相等；heuristic 来源与只有 immutable 位的对照不变。
- 状态降级（真落盘）：anchor 节点 `set_state(verified→doubted)` 由 `ok=True changed=True` 落盘 doubted 变为 `ok=False error=protected` 落盘 verified。
- 心跳（6 行台账：3 成功 beat + 1 失败 beat + 2 失败 tick）：`n=4/longest_s=250/无失败读数` → `n=3/longest_s=200/failed=3/failures 含明细`。
  按 reflect 档查询 `absent=True` → `absent=False, failed=1`。

## 复跑

```bash
python -X utf8 -m md_cg.test_audit_state_20261015
python -X utf8 -m md_cg.test_audit_write_20261015
python -X utf8 -m md_cg.test_audit_protection_20261015
python -X utf8 -m md_cg.test_audit_heartbeat_20261015

python -X utf8 -m md_cg.test_audit_state_20261015 --mutate
python -X utf8 -m md_cg.test_audit_write_20261015 --mutate
python -X utf8 -m md_cg.test_audit_protection_20261015 --mutate
python -X utf8 -m md_cg.test_audit_heartbeat_20261015 --mutate

cargo test --offline --manifest-path rust/Cargo.toml -- --test-threads=1 --nocapture
```

## 查重与不做项

- 已在源仓库 issue、在审 PR 与 bounty 记录中查重：衰减保护、状态降级、心跳统计分别沿用 bounty #506、#514、#513；撤回与归一化无重复条目。
- 审计期间发现的其他缺陷已有归属，不纳入本 PR：
  区间漏召回见 PR #342；插件租户与 env 见 PR #368；审核 merge 密级已由上游 61380931 修复；
  tidy 摘录密级见 PR #371/#373；BLINDSPOT 丢正文见 PR #374。
- 本次只在 Windows / Python 3.13 / Rust stable 实测。
