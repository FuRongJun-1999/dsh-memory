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
写类型闸（信任值/信任分量须**有限数值**（inf/nan 拒，#435）、条件空间须
字符串）亦两 VM 同判。

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

非有限闸（#435）：Python `float()` 接受 `'inf'/'nan'/'infinity'`（含大小写
与符号全形态）——`float('inf')` 正是 float，类型闸放行即毒化信任寄存器
（NaN 破坏等式自反性使 止 永不触发、inf 恒过 知足 阈值使其恒早退，
静默错答）。收口为双闸：
- **编译期单点**：`compiler._instr`——`德`/`知足` 操作数 `float()` 后
  `math.isfinite` 拒（`SyntaxError` 名实不符）；双入口
  （`compile_source` strict=True / `pbc.compile_to_pbc` strict=False）同拒，
  非数值阈值同收（修复前 `知足 abc` 的裸 `ValueError` 穿透窄捕获）。
- **运行期闸**（准确范围＝**写闸＋累积闸＋阈值闸＋初值闸**四面；
  fb60b581 初版只收前两面、称「双闸」，阈值/初值两面由技术审返工补全，
  见下）：
  ①`STORE_NAME` 写闸——信任值/分量须**有限**数值；
  ②`德`(DE) 累积先算后验——NaN/inf 操作数与溢出累积（1e308+1e308）
  同拒；
  ③`知足` 阈值闸——阈值非有限拒（-inf 使判定反向早退、inf 恒不可达、
  nan 恒不达标）；
  ④初值闸——`run(trust=…)` 与 `symbols` 种子合并终值、分量种子须有限。
  非有限一律 `VMBuiltinError('nonfinite')`。两 VM 同判（Rust `vm.rs`）。

技术审返工（PR #449 复审，ybyz2 09:04）三面补全：
- **超 double 域整数全函数化**：`math.isfinite(10**400)` 不返回 False 而是
  抛 `OverflowError`（先 int→float）——裸调使闸自身成为新缺陷面（`STORE
  信任值 <- 10**400` 由 base 的成功变为裸 OverflowError）。运行期判定统一
  走全函数 `_finite_num`（OverflowError→False）：STORE_NAME 写闸（信任值/
  分量）、DE 操作数预检与累积后验；`STORE 信任值 <- 10**400` 与
  `assemble('PUSH_CONST 9**400')` 得 `kind='nonfinite'` 而非裸 OverflowError。
- **`知足` 运行期阈值面**：`ZHIZU(inf/-inf/nan/超域 int)` 阈值运行期拒
  ——-inf 使判定反向（任何有限信任恒达标 → 早退、其后的 止 被跳过）、
  inf 恒不可达、nan 恒不达标。编译期闸管不到手搓字节码与 .pbc 往返
  （8 字节 double 保真），此注入面由运行期同判收口（两 VM 同）。
- **初值注入面**：`run(trust=…)` 与 `symbols` 种子合并终值经 `reset`
  单点补 isfinite（种子与 trust 参数**一处判定**，两条注入路径同归）；
  分量种子数值但非有限同拒，非数值仍走 N270 丢弃口径。**选修而非声明
  豁免**的依据：① `VMBuiltinError` 的单点声明本即「初值闸在 reset」——
  写闸收紧为「须有限数值」后初值不同步收口，等于闸上开洞
  （`run(trust=inf)` 绕过全部写闸使 止 被跳过）；② Rust 侧 N246 舍入
  守卫以 inf/nan 初值为夹具的意图是钉 `round3` 单点对特殊值的口径，
  改在单点直接断言（意图不变、载体换位）后无既有钉子与之冲突。
  Rust `vm.rs` 的 `run` 初值归一处理同判。
- 附带（Rust 实跑暴露）：`vm.rs` 信任分量寄存器改**全名投影**（默认 0.0，
  对齐 Python `reset` 的 `{n: 0.0}`）——修前只在种子注入时建键，空符号表
  下 `get_mut` 落空使分量写闸整面失效（`信任分量=inf` 静默落 `symbols`）、
  分量读取报未声明（两 VM 分叉；fb60b581 的 Rust 单测因本机 MSVC linker
  不可用未真跑而未暴露——本返工经 gnu 工具链 `cargo test` 实跑点名收口）。

**孪生面边界（如实登记）**：`md_cg/whitebox_kb/wisdom/core/{compiler,
condition_vm}.py`（白箱自举孪生副本）**无**非有限闸——`德 inf` 在孪生链
仍 `ok=True` 产出 `(DE, inf)`（实测 2026-10-16）。该面非 #435 引入
（base 同漏），本闸收口范围为**主链双后端**（`compiler/` 与
`swarm/rust_runtime`）；「闸已在主入口收口」**不覆盖**孪生副本——孪生
回移沿用 issue #326-② 的孪生对齐守卫范式另件处理，不在本 PR 冒领。

**编译入口第三出口（如实登记）**：编译期闸单点在 `compiler._instr`
（`德`/`知足` 操作数 `float()` 后 isfinite），而 `compiler/api.py` 的
`compile_source`（CLI `pc compile` 的 `cmd_compile` 即走此路径）经
`CodeGenerator` 产 **Python 运行时代码**、**不调** `Compiler._instr`
——`德 inf` 经该出口仍 `success=True`（实测 2026-10-16），编译期闸与
上文两 VM 运行期闸**均不覆盖**该出口（其产物不是条件空间字节码/
`.pbc`，运行期闸无从接手）。收口须把非有限判定上移到两入口共用的
parser/名实校验层（入口架构改动），不在本返工范围，另行登记为
needs-owner-decision。

守卫：`compiler/tests/test_issue435_nonfinite_gate.py` +
`swarm/tests/test_rust_vm_nonfinite_gate_435.py`（Rust 面与双后端同判）＋
`swarm/rust_runtime` 的 `cargo test`（`nonfinite_gate_tests`：写闸/DE/
`知足` 阈值/初值注入面；该守卫 cargo 不可用时打**行首 SKIP** 行，
issue #284 口径——不冒充 PASS）。

修复前：`信任阈值 = 0.9` 落 `symbols` 遮蔽内建读取（两 VM 皆漏）、
`条件空间 = 0.9` Python 数字成空间名（Rust 拒）、`信任值 = "0.9"`
Python 裸 `TypeError`（Rust 拒）。

守卫：`compiler/tests/test_builtin_write_guard_n272.py` +
`swarm/tests/test_rust_vm_builtin_guard_n272.py`（Rust 面与双后端同判）。
