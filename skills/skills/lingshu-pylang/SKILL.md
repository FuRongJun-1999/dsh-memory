---
name: lingshu-pylang
description: >-
  灵枢白箱条件单元域入口：Python 语言机制（120 单元 / 25 子域）。触发词：Python、闭包、装饰器、异步、asyncio、推导式、数据结构、元编程。
  场景：任务命中本域任一子域主题时使用。先查下方路由表定位单元，语义模糊时经 mdcg cg op=route 路由；
  单元正文在 units/<slug>/SKILL.md 按需回读（KCCS 四要素在各单元内，不随本入口加载）。
  【不适用】Not for：任务不属于本域任何子域主题（负路由）；跨域方向判断改用 designer-perspective 元技能。
license: MIT
allowed-tools: Read Grep Glob Bash
metadata:
  version: "2.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-09-11"
  domain: pylang
  unit-count: 120
  kccs:
    trigger_words: ["工具", "数据结构", "异步", "异常", "面向对象", "元编程", "求值", "语法", "推导式", "类型", "闭包", "字符串"]
    when: "任务命中本域单元的生效条件（子域主题见路由表；单元级条件在 units/<slug>/SKILL.md）"
    sub: ["工具", "数据结构", "异步", "异常", "面向对象", "元编程", "求值", "语法", "推导式", "类型", "闭包", "字符串", "栈机", "上下文", "函数", "参数", "复合赋值", "环境", "生成器", "程序", "蜂群", "装饰器", "词法", "运算符", "迭代器"]
    execute: "① 定位：路由表或 mdcg cg op=route → ② 回读 units/<slug>/SKILL.md → ③ 按单元 KCCS 执行 → ④ 验证交灵枢 MCP（编译/运行/断言）"
    not_applicable: ["任务不属于本域任何子域主题（负路由）", "需要全局观测/资格裁决时改用 designer-perspective（元技能不执行操作层）"]
---

# 灵枢 Python 语言机制域入口（lingshu-pylang）

白箱条件单元域入口（v2.0 层级化重组）。本域 120 个单元收纳于 `units/`，
本文件只承载**子域路由**——description 进上下文做域级命中，单元按需回读。

## 路由表（子域 → 单元）

| 子域 | 数 | 单元（slug · 中文主题）|
|---|---|---|
| 工具 | 54 | `pylang-074fd698` · 工具-随机采样（pylang-074fd698）、`pylang-10ce3e91` · 工具-迭代工具（pylang-10ce3e91）、`pylang-15f76c64` · 工具-计数器（pylang-15f76c64）、`pylang-1aa3e939` · 工具-格式化（pylang-1aa3e939）、`pylang-1bed54cf` · 工具-归约（pylang-1bed54cf）、`pylang-1dd35612` · 工具-字节编解码（pylang-1dd35612）、`pylang-24273d7b` · 工具-直方图（pylang-24273d7b）、`pylang-2853f59f` · 工具-顺序去重（pylang-2853f59f）、`pylang-2a6bc16e` · 工具-嵌套扁平化（pylang-2a6bc16e）、`pylang-395085ca` · 工具-属性访问（pylang-395085ca）、`pylang-39c72c78` · 工具-数值统计（pylang-39c72c78）、`pylang-486a1e94` · 工具-二分查找（pylang-486a1e94）、`pylang-4963b28a` · 工具-数据类（pylang-4963b28a）、`pylang-4ca283f2` · 工具-过滤（pylang-4ca283f2）、`pylang-5102c069` · 工具-函数缓存（pylang-5102c069）、`pylang-5880b7a1` · 工具-行程压缩（pylang-5880b7a1）、`pylang-621123dd` · 工具-众数统计（pylang-621123dd）、`pylang-642cd625` · 工具-排序键控（pylang-642cd625）、`pylang-672df225` · 工具-字符串哈希（pylang-672df225）、`pylang-67d3368e` · 工具-分组（pylang-67d3368e）、`pylang-6be54340` · 工具-深拷贝（pylang-6be54340）、`pylang-70b2006f` · 工具-模板渲染（pylang-70b2006f）、`pylang-730c3fe4` · 工具-矩阵运算（pylang-730c3fe4）、`pylang-733c1286` · 工具-排列组合（pylang-733c1286）、`pylang-7df8ca78` · 工具-峰值检测（pylang-7df8ca78）、`pylang-8182681d` · 工具-滑动均值（pylang-8182681d）、`pylang-82b73f3d` · 工具-字符串判断（pylang-82b73f3d）、`pylang-8404bbde` · 工具-数学函数（pylang-8404bbde）、`pylang-8584040d` · 工具-正则匹配（pylang-8584040d）、`pylang-8d6ec58a` · 工具-位掩码（pylang-8d6ec58a）、`pylang-91277748` · 工具-累加器（pylang-91277748）、`pylang-943b9dcb` · 工具-打乱（pylang-943b9dcb）、`pylang-a7c3d0e2` · 工具-字符串替换（pylang-a7c3d0e2）、`pylang-ab7dddc2` · 工具-循环轮转（pylang-ab7dddc2）、`pylang-b8040e1c` · 工具-日期时间（pylang-b8040e1c）、`pylang-b8d45f76` · 工具-进制转换（pylang-b8d45f76）、`pylang-ba956e52` · 工具-JSON序列化（pylang-ba956e52）、`pylang-bb18b1f9` · 工具-时间格式化（pylang-bb18b1f9）、`pylang-c910ad31` · 工具-映射（pylang-c910ad31）、`pylang-cf0fca1c` · 工具-最长公共前缀（pylang-cf0fca1c）、`pylang-d2001e1f` · 工具-切片操作（pylang-d2001e1f）、`pylang-d8962e66` · 工具-编辑距离（pylang-d8962e66）、`pylang-db6214cd` · 工具-性能计时（pylang-db6214cd）、`pylang-dfad3dba` · 工具-字符串对齐（pylang-dfad3dba）、`pylang-e1aa3818` · 工具-数值舍入（pylang-e1aa3818）、`pylang-e88e31fd` · 工具-文本分词（pylang-e88e31fd）、`pylang-ecd569d2` · 工具-字符串拆分（pylang-ecd569d2）、`pylang-f127a8d1` · 工具-环境查询（pylang-f127a8d1）、`pylang-f2f40090` · 工具-文件读取（pylang-f2f40090）、`pylang-f4aa9e65` · 工具-分位数（pylang-f4aa9e65）、`pylang-f4f820d4` · 工具-笛卡尔积（pylang-f4f820d4）、`pylang-f5b34833` · 工具-列表分块（pylang-f5b34833）、`pylang-fd7595f0` · 工具-成对迭代（pylang-fd7595f0）、`pylang-fda87aa1` · 工具-字典反转（pylang-fda87aa1） |
| 数据结构 | 11 | `pylang-01b23f80` · 数据结构-有序字典（pylang-01b23f80）、`pylang-0b490bb2` · 数据结构-链表（pylang-0b490bb2）、`pylang-36d178bc` · 数据结构-列表字典（pylang-36d178bc）、`pylang-49026041` · 数据结构-并查集（pylang-49026041）、`pylang-50614726` · 数据结构-最小堆（pylang-50614726）、`pylang-85d8617b` · 数据结构-集合运算（pylang-85d8617b）、`pylang-a4d3d7b1` · 数据结构-枚举（pylang-a4d3d7b1）、`pylang-a88db70d` · 数据结构-队列栈（pylang-a88db70d）、`pylang-b00660e6` · 数据结构-默认字典（pylang-b00660e6）、`pylang-bb46f3f2` · 数据结构-跳表（pylang-bb46f3f2）、`pylang-cd4234a5` · 数据结构-二叉树（pylang-cd4234a5） |
| 异步 | 8 | `pylang-0ca7f08b` · 异步-信号量（pylang-0ca7f08b）、`pylang-3a659480` · 异步-超时控制（pylang-3a659480）、`pylang-4ddf31f3` · 异步-异步生成器（pylang-4ddf31f3）、`pylang-521b1bf8` · 异步-事件循环（pylang-521b1bf8）、`pylang-961e9e43` · 异步-async await（pylang-961e9e43）、`pylang-b880c6c6` · 异步-并发任务（pylang-b880c6c6）、`pylang-beb47b63` · 异步-任务取消（pylang-beb47b63）、`pylang-c5c76a12` · 异步-异步队列（pylang-c5c76a12） |
| 异常 | 5 | `pylang-482be62b` · 异常-捕获（pylang-482be62b）、`pylang-7c4cc6f8` · 异常-抛出（pylang-7c4cc6f8）、`pylang-ac2a4b38` · 异常-传播（pylang-ac2a4b38）、`pylang-afaf67c0` · 异常-自定义异常（pylang-afaf67c0）、`pylang-c1317cd9` · 异常-异常链（pylang-c1317cd9） |
| 面向对象 | 5 | `pylang-61a9102d` · 面向对象-继承（pylang-61a9102d）、`pylang-7c7193ad` · 面向对象-组合（pylang-7c7193ad）、`pylang-8b6f071e` · 面向对象-运算符重载（pylang-8b6f071e）、`pylang-b4d7616d` · 面向对象-类定义（pylang-b4d7616d）、`pylang-c36fabf7` · 面向对象-多态（pylang-c36fabf7） |
| 元编程 | 4 | `pylang-65ca79b7` · 元编程-描述符协议（pylang-65ca79b7）、`pylang-70b215f1` · 元编程-类装饰器（pylang-70b215f1）、`pylang-c42465ec` · 元编程-元类定制（pylang-c42465ec）、`pylang-ca9332cf` · 元编程-动态建类（pylang-ca9332cf） |
| 求值 | 4 | `pylang-81ad40ee` · 求值-逻辑短路（pylang-81ad40ee）、`pylang-9dbd8e2b` · 求值-控制流（pylang-9dbd8e2b）、`pylang-f124f0e6` · 求值-闭包（pylang-f124f0e6）、`pylang-f2d6ec27` · 求值-解包赋值（pylang-f2d6ec27） |
| 语法 | 4 | `pylang-79845f4d` · 语法-多行字符串（pylang-79845f4d）、`pylang-88ab2f96` · 语法-切片赋值（pylang-88ab2f96）、`pylang-b67b1878` · 语法-字典合并（pylang-b67b1878）、`pylang-f6ebb66e` · 语法-优先级（pylang-f6ebb66e） |
| 推导式 | 3 | `pylang-c017681a` · 推导式-字典推导（pylang-c017681a）、`pylang-dfd5aac2` · 推导式-列表推导（pylang-dfd5aac2）、`pylang-f92bc49b` · 推导式-集合推导（pylang-f92bc49b） |
| 类型 | 3 | `pylang-31f5b8db` · 类型-协议接口（pylang-31f5b8db）、`pylang-886935a3` · 类型-类型注解（pylang-886935a3）、`pylang-be55a094` · 类型-运行时检查（pylang-be55a094） |
| 闭包 | 3 | `pylang-38600583` · 闭包-延迟绑定（pylang-38600583）、`pylang-9018c39a` · 闭包-工厂（pylang-9018c39a）、`pylang-d616eb28` · 闭包-捕获更新（pylang-d616eb28） |
| 字符串 | 2 | `pylang-7d86ab5d` · 字符串-切分（pylang-7d86ab5d）、`pylang-962954d9` · 字符串-大写（pylang-962954d9） |
| 栈机 | 2 | `pylang-2ae78997` · 栈机-完整执行（pylang-2ae78997）、`pylang-2bc88f4c` · 栈机-字节码执行（pylang-2bc88f4c） |
| 上下文 | 1 | `pylang-e476915b` · 上下文-管理器（pylang-e476915b） |
| 函数 | 1 | `pylang-f78bdcd7` · 函数-定义调用（pylang-f78bdcd7） |
| 参数 | 1 | `pylang-dcde3040` · 参数-默认值与关键字绑定（pylang-dcde3040） |
| 复合赋值 | 1 | `pylang-1703046f` · 复合赋值-执行内核（pylang-1703046f） |
| 环境 | 1 | `pylang-8fe98252` · 环境-作用域链（pylang-8fe98252） |
| 生成器 | 1 | `pylang-cce90fa0` · 生成器-yield（pylang-cce90fa0） |
| 程序 | 1 | `pylang-4af9140e` · 程序-完整执行（pylang-4af9140e） |
| 蜂群 | 1 | `pylang-ecf27e0c` · 蜂群-服务发现（pylang-ecf27e0c） |
| 装饰器 | 1 | `pylang-a02eac31` · 装饰器-定义使用（pylang-a02eac31） |
| 词法 | 1 | `pylang-8283d7c0` · 词法-记号化（pylang-8283d7c0） |
| 运算符 | 1 | `pylang-399b317e` · 运算符-in 成员判断（pylang-399b317e） |
| 迭代器 | 1 | `pylang-38e8f9ff` · 迭代器-协议（pylang-38e8f9ff） |

## 路由流程

1. **词面命中**：任务含子域/单元触发词 → 直接查上表回读对应单元
2. **语义模糊**：`mdcg cg op=route intent=<任务描述>` → 返回建议能力名与知识
3. **回读**：`units/<单元slug>/SKILL.md`（含 KCCS 四要素与验证样例）
4. **验证**：灵枢 MCP 工具物理执行（编译/运行/断言裁决），技能说"怎么验证"、MCP 负责"真去跑"

## 真源与纪律

- 知识真源：`md_cg/whitebox_kb/wisdom/python_code_units.py`（KCCS 四要素唯一真源）
- 本包为生成投影（2026-09-11 层级化重组 v2.0）：单元内容零改动，仅目录收纳 + 域入口新增
- 触发词全量索引：`md_cg/whitebox_kb/wisdom/trigger_words_index.json`
- 变更须在真源层修改后重新导出（R6 变更验证），勿直接改本目录单元
