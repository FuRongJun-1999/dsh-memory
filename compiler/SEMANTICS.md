# 术数编译链 · 语言语义要点（compiler/）

> 本文件记录 2026-09-14 修复的 5 个实测缺陷所确立/澄清的语义，
> 以及后续批次增补的语言契约（§6：名实校验位置语义/条件空间别名与极性/
> 内建写面闸，N270–N272，2026-10-05）。
> 这些点是**语言契约**，两台 VM（Python `condition_vm.py` / Rust `swarm/rust_runtime/src/vm.rs`）
> 必须一致；双后端等价由 `swarm/tests/test_rust_codegen.py` 与
> `swarm/tests/test_rust_swarm.py` 守卫，缺陷回归由 `compiler/tests/test_defect_regression.py` 守卫。

---

## 1. VM 内建名（名与实一处存储）

编译期名实校验（`name_checker.PREDEFINED_SYMBOLS`）把下列符号声明为合法，
但运行时必须由 VM 绑定——否则会出现「编译期放行、运行期 NameError」的死代码。

| 内建名 | 读（LOAD_NAME） | 写（STORE_NAME） |
|---|---|---|
| `信任值` | `trust_value` 寄存器 | 写 `trust_value` 寄存器 |
| `条件空间` | 当前条件空间名（栈空 → `默认`） | **切换**条件空间（见 §1.2） |
| `伴侣` / `工作` / `默认` / `恢复默认` / `default` | 其自身（字符串） | — |
| `信任阈值` | `0.7`（默认阈值） | — |
| `P_trust` `T_pred` `T_context` `E_weight` `情感权重` | `trust_parts` 寄存器（默认 0.0） | 写 `trust_parts` |

写面标「—」的集（`信任阈值`、`伴侣`/`工作`/`默认`/`恢复默认`/`default`）
**不可写**：编译期 error + 运行期结构化拒，两 VM 同判（N272，见 §6.3）；
写类型闸（信任值/信任分量须数值、条件空间须字符串）亦两 VM 同判。

关键不变式：**`德`(DE) 与 `信任值` 指向同一处存储**。
修复前 `德` 只改寄存器、`信任值` 读符号表，二者互不通信
（仓库自带示例 `python -m compiler.compiler` 因此直接崩溃）。

### 1.1 初值归一的优先级

`run(code, symbols=…, trust=…)` 同时给出时：

1. 若 `symbols` 含 `信任值` → **归一为寄存器初值**，覆盖 `trust` 参数；
2. 否则 `trust` 参数即寄存器初值；
3. `symbols` 含 `条件空间` → 归一为当前空间名（切换）。

理由：`信任值` 在符号里出现是「关于信任值的最具体陈述」，优先级高于通用种子参数。
符号表里**不再保留**这些内建名（归一即弹出）。

> 历史写法提醒：v0.7.1 之前的测试会同时给 `trust` 与 `symbols={"信任值": 0.5}`，
> 那是「无内建」时期的绕过手段。统一后二者会冲突（符号覆盖 trust），
> 应只保留其一——**只给 `trust` 即符合原意**。

### 1.2 条件空间切换

- 写 `条件空间 = <空间名>` → 替换条件空间栈**栈顶**帧（栈空则压入）。
- 写 `条件空间 = 恢复默认` 或 `= 默认` → 弹栈到根并置名 `默认`。
- 读 `条件空间` → 栈顶帧名；栈空视为 `默认`。

由此「`若 条件空间 为 伴侣`」成为**真实运行期比较**（此前是运行期死代码）。

---

## 2. 语句块边界（分隔符语义）

| 分隔符 | 语义 |
|---|---|
| `。` | **全句终止** —— 语句块到此结束，后续语句归上一层（顶层） |
| `；` / `，` | **块内续接** —— 继续收集本块的下一条语句 |
| `1。` `2。` | 九章算术**步骤号**：`；` 后紧跟步骤号/术曰 → 块结束 |

修复前的错误：`。` 也参与续接，导致 `当…执行 A。B。` 把 `B` 吞进循环体；
无步骤编号时更会把其后**全部**顶层语句吞入循环体 —— 若被吞语句重新武装循环条件
（如把计数复位）即为死循环 `RecursionError`。

**写法约定**：循环体/条件体若要写多条语句，用分号：
`当 X 执行 A；B。`（块内两条），`A。B。`（两条独立顶层语句）。

N4（2026-09-26）：『；』续接为**同局限接**——词法不产换行 token，行尾『；』
（后随 token 行号大于分隔符行号）即块终止，下一行语句归上一层作用域
（`定义 f（）：…；⏎结果 = f（4）；⏎止。` 的后续顶层行不被吞进函数体）。
条件 then/else 体、函数体与循环体同用 `_parse_statement_or_block`
（`若 X 则 A；B。` 的 B 属 then 体，受同一条件门控）。

---

## 3. `知足` 的早退语义（真实语义，非缺陷）

`知足 <阈值>` 编译为「信任达标 → **向前跳到程序末尾**」（`ZHIZU` 目标标签 place 在程序末尾）：

- 达标：跳过其后全部指令，**包括 `止`** → 终态 `halt = None`（自然跑完）
- 未达标：顺序执行后续指令，`止` 正常生效 → `halt = "halt"`

测试须据此设计：**不能在 `知足` 之后断言 `halt == "halt"`**。

---

## 4. 步骤内赋值

`术曰：1。甲 = 0.9；2。…` 中的赋值此前被**静默丢弃**
（步骤解析只走多词合并，从不检查 `=`）——不报错、值不对，比崩溃更危险。

现步骤内容对 `标识符` 先探视下一个 token：`=` 或 `（` → 走赋值/调用；
否则保持多词短语合并（`道 新信任路径` 等不受影响）。

---

## 5. 双后端契约

| 项 | Python | Rust |
|---|---|---|
| 实现 | `compiler/condition_vm.py` | `swarm/rust_runtime/src/vm.rs` |
| 内建名表 | `BUILTIN_*` / `CONDITION_SPACE_NAMES` / `TRUST_COMPONENT_NAMES` | 同名 `const` |
| 一致性守卫 | `compiler/tests/test_defect_regression.py` ⑤ | 双后端等价测试 |

任一侧改动内建名或语义，**必须同步另一侧**，否则 `test_rust_codegen` 的双后端等价检查会红。

### 5.1 关于 `codegen.py`（v0.2 遗留后端，不在契约内）

`compiler/codegen.py` 是更早的「AST → Python 源码」后端，生成的代码依赖
`protocol_runtime` 模块——**该模块在本仓不存在**（磁盘与 `git ls-files` 均无），
故其产物不可运行；测试也只核对 `INSTRUCTION_MAP` 的声明式对照
（`test_compiler_c2` ⑤），不做端到端执行。

它**未**做内建名绑定，因此若将来复活该后端，`若 信任值 …` 一类引用会
沿同一缺陷形态失败。当前定位：**只读参考，不属于双后端契约**。

```bash
# 本仓验证
python -m compiler.tests.test_defect_regression      # 缺陷回归（18 项）
python -m compiler.tests.test_condition_vm           # VM 单元（13 项）
python -m swarm.tests.test_rust_codegen              # 双后端等价（14 项）
python -m swarm.tests.test_rust_swarm                # 蜂群 + 聚合（17 项）
python -m swarm.tests.test_swarm_condition_space     # 条件空间卡（10 项）
```

---

## 6. 名实校验的位置语义与条件空间上下文（N270/N271/N272，2026-10-05）

### 6.1 读取位置未声明即编译期 error（N271）

`name_checker._check_identifier` 区分**位置语义**：

- **读取位置**（经 `_check_expression` 的标识符面——条件/比较/右值/返回/
  实参/嵌套调用实参）：未声明即编译期 `error`，两入口
  （`compiler.compile_source` / `api.compile_source`）同判据；
- **指令操作数位置**：保留既有宽松（多词短语如 `新信任路径`、
  `累积信任值` 自动声明＝文档化的有意设计，不收紧）；
- 函数形参在函数体检查上下文中登记为已声明（检查后还原，不泄漏出函数体）。

修复前读取位置也走隐式自动声明：『若 甲 大于 0.5，则 止。』（甲未声明）
编译期成功且零警告、运行期 VM `LOAD_NAME` 才炸 `NameError`（名实两套）。
守卫：`compiler/tests/test_read_position_undeclared_n271.py`。

### 6.2 条件空间的别名跟随与极性（N270）

- **别名跟随**：静态顺序流别名环境——`甲 = 伴侣` 后 `条件空间 = 甲`
  与 `若 条件空间 为 甲` 均解析出「伴侣」（链式 `甲→乙` 传递；中途
  重赋值为非空间名值即失效；块内赋值按顺序流照常更新）。
  修复前 `_apply_space_assign_switch`/`_check_condition_space_switch`
  只认直接空间名，别名形态使伴侣空间情感权重上限 0.15 整体绕过
  （运行期 VM 真切进「伴侣」空间）。
- **极性**：`若 条件空间 为/等于 X`（正向）then 内处于 X、else 不沿用；
  `若 条件空间 不为/不等于 X`（负向）then 内不沿用、else 处于 X；
  条件语句结束恢复外层已知空间。修复前不看极性：负向条件误拒
  （『若 条件空间 不为 伴侣，则 止情感权重于0.9』误报上限）、
  正向 else 误拦、语句后已知空间丢失。
- **Python VM 条件空间写类型闸**：`STORE_NAME 条件空间` 非字符串 →
  结构化拒（对齐 Rust `vm.rs` STORE_NAME；见 §6.3）。

守卫：`compiler/tests/test_condition_space_alias_n270.py`。

### 6.3 内建写面闸（N272）

以 §1 表为准绳——写面标「—」的集（`信任阈值`、`伴侣`/`工作`/`默认`/
`恢复默认`/`default`）：

- **编译期**：`name_checker` 保护面扩展（`READONLY_BUILTIN_NAMES`）——
  赋值即 `error`（两入口一致）；
- **运行期**：`STORE_NAME` 结构化拒——Python
  `condition_vm.VMBuiltinError('readonly')`、Rust `VmError::Error`
  （两 VM 同判）。

写类型闸（删「结构化错，不裸异常」，Python 单点：`condition_vm.py` 的
`STORE_NAME`/`reset`，对齐 `vm.rs` STORE_NAME 分支）：`信任值`/信任分量
写非数值、`条件空间` 写非字符串 → 拒；注入初值同口径（信任值须数值、
条件空间非字符串不切换）。

修复前：`信任阈值 = 0.9` 落 `symbols` 遮蔽内建读取（两 VM 皆漏）、
`条件空间 = 0.9` Python 数字成空间名（Rust 拒）、`信任值 = "0.9"`
Python 裸 `TypeError`（Rust 拒）。

守卫：`compiler/tests/test_builtin_write_guard_n272.py` +
`swarm/tests/test_rust_vm_builtin_guard_n272.py`（Rust 面与双后端同判）。
