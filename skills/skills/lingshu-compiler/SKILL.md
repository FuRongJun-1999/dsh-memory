---
name: lingshu-compiler
description: >-
  灵枢白箱条件单元域入口：中文编译器（116 单元 / 10 子域）。触发词：编译、词法分析、语法分析、字节码、虚拟机、递归编译、类型检查、调试。
  场景：任务命中本域任一子域主题时使用。先查下方路由表定位单元，语义模糊时经 mdcg cg op=route 路由；
  单元正文在 units/<slug>/SKILL.md 按需回读（KCCS 四要素在各单元内，不随本入口加载）。
  【不适用】Not for：任务不属于本域任何子域主题（负路由）；跨域方向判断改用 designer-perspective 元技能。
license: MIT
allowed-tools: Read Grep Glob Bash
metadata:
  version: "2.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-09-11"
  domain: compiler
  unit-count: 116
  kccs:
    trigger_words: ["编译", "VM", "分析", "词法", "语法", "调试", "字节码", "校验", "对接", "求值"]
    when: "任务命中本域单元的生效条件（子域主题见路由表；单元级条件在 units/<slug>/SKILL.md）"
    sub: ["编译", "VM", "分析", "词法", "语法", "调试", "字节码", "校验", "对接", "求值"]
    execute: "① 定位：路由表或 mdcg cg op=route → ② 回读 units/<slug>/SKILL.md → ③ 按单元 KCCS 执行 → ④ 验证交灵枢 MCP（编译/运行/断言）"
    not_applicable: ["任务不属于本域任何子域主题（负路由）", "需要全局观测/资格裁决时改用 designer-perspective（元技能不执行操作层）"]
---

# 灵枢 中文编译器域入口（lingshu-compiler）

白箱条件单元域入口（v2.0 层级化重组）。本域 116 个单元收纳于 `units/`，
本文件只承载**子域路由**——description 进上下文做域级命中，单元按需回读。

## 路由表（子域 → 单元）

| 子域 | 数 | 单元（slug · 中文主题）|
|---|---|---|
| 编译 | 40 | `compile-assign` · 编译-赋值（compile-assign）、`compile-expr-tree` · 编译-表达式树（compile-expr-tree）、`compile-full-pipeline` · 编译-完整管线（compile-full-pipeline）、`compile-func-def` · 编译-函数定义（compile-func-def）、`compile-if-then` · 编译-若则（compile-if-then）、`compile-logic-expr` · 编译-逻辑表达式（compile-logic-expr）、`compile-recursive` · 编译-递归（compile-recursive）、`compile-scope` · 编译-作用域分析（compile-scope）、`compile-type-check` · 编译-类型检查（compile-type-check）、`compile-while` · 编译-循环（compile-while）、`compiler-0010c4bf` · 编译-指令重排（compiler-0010c4bf）、`compiler-054a0414` · 编译-支配树（compiler-054a0414）、`compiler-05eeed1e` · 编译-名实绑定（compiler-05eeed1e）、`compiler-0622a1f6` · 编译-内联展开（compiler-0622a1f6）、`compiler-08b54217` · 编译-寄存器溢出（compiler-08b54217）、`compiler-1028685f` · 编译-窥孔优化（compiler-1028685f）、`compiler-16661b9b` · 编译-寄存器分配（compiler-16661b9b）、`compiler-25be1262` · 编译-指令选择（compiler-25be1262）、`compiler-2a76ba07` · 编译-尾调用优化（compiler-2a76ba07）、`compiler-2df52f16` · 编译-指令融合（compiler-2df52f16）、`compiler-38378ac7` · 编译-程序（compiler-38378ac7）、`compiler-4cbbda95` · 编译-指令（compiler-4cbbda95）、`compiler-64c4224b` · 编译-中间表示（compiler-64c4224b）、`compiler-66377955` · 编译-寄存器着色（compiler-66377955）、`compiler-6af76fd6` · 编译-常量池（compiler-6af76fd6）、`compiler-6d979db2` · 编译-常量折叠（compiler-6d979db2）、`compiler-724d6c9b` · 编译-类型转换（compiler-724d6c9b）、`compiler-7690177f` · 编译-字符串拼接（compiler-7690177f）、`compiler-83c61634` · 编译-管线静态检查（compiler-83c61634）、`compiler-94b8d72d` · 编译-闭包捕获分析（compiler-94b8d72d）、`compiler-98b4c42f` · 编译-循环展开（compiler-98b4c42f）、`compiler-98e3894a` · 编译-去虚拟化（compiler-98e3894a）、`compiler-9bdfe4b8` · 编译-循环不变式（compiler-9bdfe4b8）、`compiler-aabbd099` · 编译-死代码消除（compiler-aabbd099）、`compiler-afe169d8` · 编译-指令调度（compiler-afe169d8）、`compiler-c10264a7` · 编译-常量传播（compiler-c10264a7）、`compiler-cda9c262` · 编译-边界检查消除（compiler-cda9c262）、`compiler-eb1cf2b5` · 编译-信任流分析（compiler-eb1cf2b5）、`compiler-ecb30d5b` · 编译-链式比较（compiler-ecb30d5b）、`compiler-fa8ff5f7` · 编译-内联缓存（compiler-fa8ff5f7） |
| VM | 17 | `vm-arithmetic` · VM-算术执行（vm-arithmetic）、`vm-array-ops` · VM-数组操作（vm-array-ops）、`vm-closure-call` · VM-闭包调用（vm-closure-call）、`vm-closure-create` · VM-闭包创建（vm-closure-create）、`vm-compare` · VM-比较执行（vm-compare）、`vm-cond-jump` · VM-条件跳转（vm-cond-jump）、`vm-cond-space` · VM-条件空间（vm-cond-space）、`vm-exception` · VM-异常处理（vm-exception）、`vm-func-call` · VM-函数调用（vm-func-call）、`vm-loop-run` · VM-循环执行（vm-loop-run）、`vm-profiling` · VM-指令剖析（vm-profiling）、`vm-refcount` · VM-引用计数（vm-refcount）、`vm-run-loop` · VM-执行循环（vm-run-loop）、`vm-short-circuit` · VM-短路求值（vm-short-circuit）、`vm-stack-guard` · VM-栈保护（vm-stack-guard）、`vm-stack-ops` · VM-栈操作（vm-stack-ops）、`vm-trust-accum` · VM-信任累积（vm-trust-accum） |
| 分析 | 14 | `analyze-type-infer` · 分析-类型推断（analyze-type-infer）、`compiler-0ab24d00` · 分析-圈复杂度（compiler-0ab24d00）、`compiler-0e093688` · 分析-污点分析（compiler-0e093688）、`compiler-2dbea54a` · 分析-循环检测（compiler-2dbea54a）、`compiler-2ec2c9d2` · 分析-活跃变量（compiler-2ec2c9d2）、`compiler-2f8c8f39` · 分析-调用图（compiler-2f8c8f39）、`compiler-6de326c0` · 分析-逃逸分析（compiler-6de326c0）、`compiler-7f471b3a` · 分析-基本块（compiler-7f471b3a）、`compiler-a6daf076` · 分析-字节码转储（compiler-a6daf076）、`compiler-b0678bda` · 分析-数据流分析（compiler-b0678bda）、`compiler-b1396e23` · 分析-循环开销（compiler-b1396e23）、`compiler-ce648068` · 分析-控制流图（compiler-ce648068）、`compiler-e3979fd3` · 分析-栈深度分析（compiler-e3979fd3）、`compiler-f8c8b24b` · 分析-信息差追踪（compiler-f8c8b24b） |
| 词法 | 13 | `compiler-0a62b70c` · 词法-数字字面量（compiler-0a62b70c）、`compiler-0ee9b9b9` · 词法-关键字识别（compiler-0ee9b9b9）、`compiler-56dc9bdd` · 词法-行号跟踪（compiler-56dc9bdd）、`compiler-6f1c0eea` · 词法-注释剥离（compiler-6f1c0eea）、`compiler-8c798c81` · 词法-转义序列（compiler-8c798c81）、`compiler-94f12231` · 词法-标识符解析（compiler-94f12231）、`compiler-95937c16` · 词法-字符串字面量（compiler-95937c16）、`compiler-9f7be5ad` · 词法-字符类别（compiler-9f7be5ad）、`compiler-b09bd196` · 词法-数字后缀（compiler-b09bd196）、`compiler-fe1b058d` · 词法-操作符解析（compiler-fe1b058d）、`lex-chinese-program` · 词法-中文程序（lex-chinese-program）、`lex-dao-de-jing` · 词法-道德经（lex-dao-de-jing）、`lex-nine-chapters` · 词法-九章算术（lex-nine-chapters） |
| 语法 | 11 | `compiler-0361708a` · 语法-元组解析（compiler-0361708a）、`compiler-1f722303` · 语法-括号匹配（compiler-1f722303）、`compiler-39457d2e` · 语法-位运算（compiler-39457d2e）、`compiler-4b230b6b` · 语法-空值字面量（compiler-4b230b6b）、`compiler-57e76ebe` · 语法-数组字面量（compiler-57e76ebe）、`compiler-63eae588` · 语法-布尔字面量（compiler-63eae588）、`compiler-815cad08` · 语法-复合赋值（compiler-815cad08）、`compiler-8dd747ac` · 语法-字典字面量（compiler-8dd747ac）、`compiler-9d9b4e83` · 语法-三元表达式（compiler-9d9b4e83）、`compiler-a8399248` · 语法-语句分隔（compiler-a8399248）、`compiler-d974e5d3` · 语法-函数签名（compiler-d974e5d3） |
| 调试 | 7 | `compiler-0355bffb` · 调试-单步（compiler-0355bffb）、`compiler-11897630` · 调试-覆盖率（compiler-11897630）、`compiler-39fb5926` · 调试-断点（compiler-39fb5926）、`compiler-47f4fbfa` · 调试-调用计数（compiler-47f4fbfa）、`compiler-98a5625b` · 调试-条件断点（compiler-98a5625b）、`compiler-a7995a0c` · 调试-调用栈回溯（compiler-a7995a0c）、`compiler-cb1e8e4b` · 调试-变量监视（compiler-cb1e8e4b） |
| 字节码 | 6 | `compiler-0f3787e6` · 字节码-反序列化（compiler-0f3787e6）、`compiler-674ab4f6` · 字节码-完整性校验（compiler-674ab4f6）、`compiler-7b229a7d` · 字节码-紧凑编码（compiler-7b229a7d）、`compiler-b9b31ce0` · 字节码-指令大小（compiler-b9b31ce0）、`compiler-ccafd438` · 字节码-文件头校验（compiler-ccafd438）、`compiler-cf5776a4` · 字节码-序列化（compiler-cf5776a4） |
| 校验 | 6 | `check-name-real` · 校验-名实（check-name-real）、`compiler-05a1691a` · 校验-信任检查（compiler-05a1691a）、`compiler-4d5a68ff` · 校验-条件空间类型（compiler-4d5a68ff）、`compiler-61ff016b` · 校验-名实一致（compiler-61ff016b）、`compiler-90324d0a` · 校验-条件空间存在性（compiler-90324d0a）、`compiler-f99fedbe` · 校验-条件空间符号类型（compiler-f99fedbe） |
| 对接 | 1 | `compiler-0e82b966` · 对接-协议词法（compiler-0e82b966） |
| 求值 | 1 | `compiler-4a8cd1f1` · 求值-条件表达式（compiler-4a8cd1f1） |

## 路由流程

1. **词面命中**：任务含子域/单元触发词 → 直接查上表回读对应单元
2. **语义模糊**：`mdcg cg op=route intent=<任务描述>` → 返回建议能力名与知识
3. **回读**：`units/<单元slug>/SKILL.md`（含 KCCS 四要素与验证样例）
4. **验证**：灵枢 MCP 工具物理执行（编译/运行/断言裁决），技能说"怎么验证"、MCP 负责"真去跑"

## 真源与纪律

- 知识真源：`md_cg/whitebox_kb/wisdom/compiler_code_units.py`（KCCS 四要素唯一真源）
- 本包为生成投影（2026-09-11 层级化重组 v2.0）：单元内容零改动，仅目录收纳 + 域入口新增
- 触发词全量索引：`md_cg/whitebox_kb/wisdom/trigger_words_index.json`
- 变更须在真源层修改后重新导出（R6 变更验证），勿直接改本目录单元
