# 世界模型 L2 · `alternatives`（历史遗留候选）落地读数 v1.0

> 设计稿：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §3（L2 槽位 schema）
> 落地批：本批只做 **`alternatives`**，`blindspots` 仍后置；**写侧一字未动**（只读面）。
> 日期：2026-11-02

---

## 一、做了什么

`md_cg/state_slots.py` 里 `alternatives` 原先恒为空列表（模块头明写「判定口径后置，
不得臆造填充」）。本批给出**可判定**的口径并落地。

### 1.1 口径（重要：比设计稿语义**弱**，如实标注）

设计稿 §3 把 `alternatives` 写作「**同期**未决值」。实测后**不能按这个强语义实现**：

| 构想中的判据 | 为什么不可用（实测） |
|---|---|
| 按 `t` 划时间窗 = 同期 | `t` 是 `time.time()` **记账时刻**，不是事件发生时刻。两次相隔数月的记账会被划进同一窗 |
| 按 `seq` 差值判同期 | `seq` 是调用方给的「轮/序号」，**可缺省为 None**，无单调保证 |

故本批采用**可判且不臆造**的定义：

```
alternatives = 该 (subject, slot) 的变迁史中，
               曾被断言过、且不等于当前值的去重值（保持首次出现序）
```

即「这个槽位历史上有过、现在不是它的那些值」——**历史遗留候选**，不是强「同期未决」。
这个降级**已在模块头写清**，不冒充强语义。

### 1.2 语义细节

- **当前值不进 alternatives**（含 retired 态下 `value=None` 时，被撤回的值反而全部进）。
- retired 态（值已撤回）下被撤回的值**仍进 alternatives** —— 可回溯。
- 复位后当前值不入，更旧的遗留值仍在。
- 单遍快速路径 `history=False` **不保留历史、算不出** ⇒ 返回空列表并标注
  `alternatives_partial=True`（**不静默给一个看起来完整的空**）。

---

## 二、改了什么（文件级）

| 文件 | 改动 |
|---|---|
| `md_cg/state_slots.py` | 新增 `_alternatives_of()`；`_replay` 接真值；`_project_current_page` 加 `alternatives_partial=True`；`_project` 按 `history` 路由到同一归约器；模块头补口径 |
| `md_cg/test_alternatives_historical.py` | **新增**守卫，21 条断言（A–H 八组） |
| 写侧（`state_events.py`） | **零改动** |

---

## 三、判据（全部实测）

```
test_alternatives_historical                21 passed / 0 failed
test_state_projection_streaming              6 tests rc=0
test_state_slots                            71 passed / 0 failed
test_state_events                           24 passed / 0 failed
test_issue375_state_slot_retire             全部通过
test_issue383_state_event_write_gate        全部通过
test_state_event_op                         47 passed / 0 failed
test_stg_interval_candidates / _time_blocks rc=0
定点变异                                     8/8 捕获，还原 sha256 逐字节一致
```

---

## 四、过程中踩到的三个真实问题（都改了，不含糊）

### 4.1 我用 `set()` 去重 → 遇 dict 值直接崩

`test_state_projection_streaming` 的 L36 故意用 `{"nested": [1]}` 当值。我的第一版
用 `seen = set()`，遇到不可哈希的 dict 抛 `TypeError`，**5 个测试变 240 个失败**。

修法：改线性「已见列表 + 相等比较」。槽位值个数极小，O(n²) 无实际代价。
**教训：台账 `new` 是任意 JSON 值，不是字符串。**

### 4.2 两个入口口径分叉（`_project` vs `project_page`）

`_project(history=False)` 原先走回放路径，`project_page(history=False)` 走单遍归约器。
以前两者都输出空列表，看不出差别；我加了 `alternatives_partial` 之后，两条路
**一真有值、一恒空**。是 `test_state_projection_streaming` 抓到的。

修法：`_project` 按 `history` 路由到同一归约器 —— **不是**削弱测试断言。

### 4.3 变异测试抓出我自己的断言没牙

第一轮变异 6 个，M3（去掉去重）**没被抓到**。原因：我的样本里每个值只出现一次，
去重逻辑根本没被触发。补了「同一值历史重复出现」的用例（旧家→新家→旧家→新家）后，
M3 才被捕获。

第二轮 M7（`_project` 不路由）也漏，因为抓它的是别人的测试不是我的守卫；
补 H 组断言后 8/8。

> **教训：全绿不等于测到了。突变没被捕获，说明断言是空的。**

---

## 五、边界（诚实）

1. **生产库零数据**。本机真实数据根
   `<家目录>\.dsh\.dsh-memory\data\mdcg` 下 **`_state_events.jsonl` 不存在**
   （旁边 `_audit`/`_trust`/`_reconcile` 等 20+ 个 jsonl 都在），
   `state_slots --status` 读数 `events=0 / subjects=0 / slots=0`。
   ⇒ **本批改动在真实库上暂时零可观测效果**，它只在有台账时才产生值。
   这件事比代码更值得注意：**L0 台账至今未接生产**（设计稿 §1.1 早写了「已实现、未接生产」）。
2. 我没有在真实库上量化「有多少槽位会得到非空 alternatives」——因为没有数据可量化。
   上面的语义细节全部来自**合成台账**（tempfile）。
3. `alternatives` 语义比设计稿「同期未决值」**弱**（见 §1.1）。若将来要给强语义，
   需要 P1 抽取器在事件行里写入「发生时刻」与「是否同期」信号 —— 那属于写侧改动，
   与本批「只读面」边界冲突，本批**不做**。
4. `blindspots` 仍恒空，本批**未动**。
5. 未跑上游全量测试套件（`md_cg` 下 852 个 `.py`），只跑了 9 个相关模块。
