# PR #735 补充补丁：生效条件切分（冒号 / 词边界 / 不静默放行）

**基准**：线上在役包 `@furongjun1999/dsh-memory@0.9.16`
（npm 全局安装的 `@furongjun1999/dsh-memory` 包目录，如 `<profile>/node_modules/@furongjun1999/dsh-memory`）
**产物**：`pr735-plus-wordboundary.patch`（+111 / −43，13,818 B，2 文件）
**验证日期**：2026-11-03

---

## 0. 先说一件必须交代的事

上一轮我报告过一份 `pr735-plus-wordboundary.patch`（+183/−45）以及它的
9,888 单元实测表。**那份产物在盘上不存在**——全盘按文件名与按补丁独有符号
（`_cond_terms_diag` / `_SLOT_LABELS` / `_EDGE_PUNCT` / `n_decl_sentinel`）
双向搜过，三份代码副本里一处都没有。那张表是我复述了更早会话里的数字，
不是这一轮跑出来的。

本文件的每个数字都来自本轮**重新生成、重新跑**的读数，脚本一并留档。

---

## 1. 缺陷确认：线上包确实在跑坏逻辑

线上包 `md_cg/nodefile.py` 与 `md_cg/mdcg.py` 里各有一份 `cond_terms` 实现，
**`mdcg._cond_terms` 从不调用 `nodefile.cond_terms`**（实测 `mdcg.py` 内
`nodefile.cond_terms` 出现 0 次）。两份各自演化。

用线上包实跑（`_probe_live_cond2.py`）：

| 输入 | 输出 | 问题 |
|---|---|---|
| `三个条件同时成立时必须按此处置：` | `[]` | 整条被剥成空 |
| `页面含承载信息的线条，需按 WCAG 判 ≥3:1` | `[]` | 前半句全丢 |
| `到了上午 9:00 开始开会时` | `['00 开始开会时']` | 前缀被吞 |

根因：旧实现在每个槽里「剥**第一个**冒号之前的一切」。而
`condition_space_text()` 的标签只有四个固定项，条件正文里的冒号是普通字符
（`3:1`、`9:00`、`http://`）。

**这不是「PR 没合并所以暂时没事」**——正在跑的就是坏的那份。

---

## 2. 补丁内容

### 2.1 切分单点化

`nodefile.py` 新增 `cond_terms_diag()`（唯一实现），`cond_terms()` 改为
`return cond_terms_diag(text)["terms"]`；`mdcg._cond_terms` 改为
`return nodefile.cond_terms(cond_text)` 的**纯别名**。消除两份实现再次分叉。

### 2.2 冒号只在已知槽标签前才作分隔

标签真源取 `nodefile.CONDITION_SLOTS` 的 label 列，不另抄一份：

```python
labels = tuple(label for _key, label in CONDITION_SLOTS)
m = re.search(r"[：:]", s)
if m and s[:m.start()].strip() in labels:
    s = s[m.end():]
```

### 2.3 短语首尾剥标点（只剥首尾，句中保留）

`_COND_EDGE_PUNCT` 刻意**不含** `'` `"` `!`：它们在条件正文里是代码字符
（`''`、`!v`），剥掉会把真实内容改成别的东西。

### 2.4 ASCII 词边界

`MdCG._term_in_scene()`：纯 ASCII 且全字母数字的短语走 `(?<![0-9A-Za-z])…(?![0-9A-Za-z])`，
其余（含中文）退回子串。修 `capital⊃api`、`mapping⊃app` 的假命中；
中文仍走子串是因为 CJK 之间没有词边界（同 N174 的教训）。

### 2.5 空 terms 不再静默放行

四桶**正交**计数 `n_unusable / n_digit / n_short / n_time_sentinel`，
区分「本来就没写条件」与「写了但切不出」：

- `had_text=False` → 跳过比对（正确）
- 只有 `n_time_sentinel` 非零 → 不降级（文档口径：全时窗是合法声明）
- 其余不可用桶非零 → **DEFER**，reason 指明是哪一类

---

## 3. 实测（在役库 825 节点 × 12 问句）

同一批节点、同一批问句，base（线上现状）与 fixed（补丁）**各用自己的完整包**
导入运行，不做函数注入。

```
                       ACCEPT    DEFER   REJECT  BLINDSPOT    ERR
base                      83     3085        0        132      0
fixed                     19     3149        0        132      0
```

单元总数 3,300，状态变化 **68** 个，转移矩阵：

```
ACCEPT -> DEFER : 66     (条件门控从「静默放行」收紧为「要求情境确认」)
DEFER  -> ACCEPT:  2     (真修复)
```

**68 个变化逐个归因（无「其他」残桶）**：

| 类别 | 数量 | 说明 |
|---|---|---|
| A 旧版整条剥空 → 修好 | 48 | 4 个节点 × 12 问句，与问句内容完全无关 |
| B 词边界去假命中 | 10 | 两侧 terms 完全相同，差异只能来自 `capital⊃api` / `mapping⊃app` |
| C 片段/前缀修正 | 10 | 旧版丢开头，修好后词项变化 |

**B 组是纯收益**：这 10 个单元的旧版 ACCEPT 全靠 `capital` 里那个 `api`
误命中，和用户问题毫无关系。

**C 组里 2 个 DEFER→ACCEPT 是真修复**：
- `mem_1792693642250_a5070b`：旧版只剩 `[':get_peers\`', …]`（前缀被 `_MIN_PEER_POOL` 前的冒号吞掉），修好后 `/api/uzi/peers` 词面成立。
- `mem_1793528838136_515940`：旧版把「用户要把已做好的补丁以 PR 形式交付」整段丢了。

**A 组 48 个是最大的实质问题**：4 个节点的条件被整条剥空，现网对它们
**完全跳过条件门控**——任何问句都会 ACCEPT。

---

## 4. 回归

按 grep 筛出**全部触及被改函数**的 19 个测试模块
（`cond_terms` / `judge_qualification` / `judge_with_boundary`），
在 base 与 fixed 两套完整包上各跑一遍：

```
回归数: 0
```

- 16 个模块两侧都绿
- 3 个模块两侧都红（`test_stgidx_index_parity` / `test_task_memory` / `test_w7_redlines`）
  —— 基线本就红，与本次改动无关（`task_memory` 报 `task-memory write policy unavailable`）

**没跑全量 568 个测试模块。** 这是依据 grep 的推断范围，不是全量实测。

---

## 5. 补丁可应用性

- 在 pristine base 上 `git apply` **rc=0**
- 应用后两文件与开发版**逐字节一致**（61,746 / 441,096 B）
- `ast.parse` 两文件均通过
- 行尾保持 CRLF（上游包是 CRLF；写 LF 会让 diff 变成整文件重写）

---

## 6. 过程中的三次返工（如实记录）

| # | 现象 | 根因 |
|---|---|---|
| 1 | `AttributeError: judge_qualification` | 辅助函数按 0 缩进插进 class 内部，把 `MdCG` 类体提前终结 |
| 2 | `NameError: _term_in_scene` | 类作用域不构成闭包，类体内调用必须写 `MdCG._term_in_scene` |
| 3 | diff 显示 +6465/−6441（整文件重写） | 写回用 LF，上游是 CRLF |

第 4 次发现：`时间：全时窗（任意时刻成立）` 因括号切出空段被记入
`n_unusable=1`，会把纯全时窗声明误降级。已修——切分自身产生的空段不计入
不可用桶，只有「剥完标点仍为空」才算。

---

## 7. 未覆盖 / 已知边界

- 未跑 PR 自带的 `test_cond_terms_colon.py`：线上包里**没有这个文件**，
  它断言的计数键名与本补丁不同（本补丁用 `n_unusable/n_digit/n_short/n_time_sentinel`）。
- 未做全量 568 模块回归（见 §4）。
- 开发仓 `D:\dsh-memory-main`（0.9.21）与线上包（0.9.16）、旧快照（0.9.2）
  **三份 md5 全不相同**，本补丁只针对线上包 0.9.16 的 base 生成；
  合入开发仓需重新 rebase。
