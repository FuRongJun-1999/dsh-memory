# DSH 收尾审计计数 · #606 交付记录

作者：fladyck；日期：2026-10-21。
关联：[issue #606](https://github.com/FuRongJun-1999/dsh-memory/issues/606)。
初始基线：03e5e7527ff18a29384bba70f8d1f25dabcc7217。
最终基线：75a3288221b26ae8190658aa5af8c7198b7bad1c（上游更新 @types/node 后重新构建及回归通过）。

## 功能名

插件关闭、卸载或更新时的一行累计审计计数。

## 生效条件

认知图已启用，自动记忆钩子已安装，且审计文件包含完整、合法的 written / filtered / skipped 计数。使用记录器既有 auditPath；未指定时沿用 DSH_HOME / 缺省审计路径规则。

## 子功能

- 只在收尾时重读最新盘面，分别汇总角色与原因桶；只输出固定文案和数字。
- 缺文件、不可读、JSON 损坏、缺桶、非法数值、合计溢出均不提示；有效零计数照常提示。
- 返回幂等收尾函数，接入 index.ts 既有 disposers；重复调用不重复输出。
- 汇总只读文件，不改写既有计数、消息过滤或记忆内容。

## 执行

正常运行不新增摘要；宿主通过 Cordis 销毁插件时，输出例如：

~~~text
dsh-memory: 自动记忆审计（累计）written=6 filtered=15 skipped=24
~~~

这是累计盘面计数，可能包含其它会话或实例。written 是“成功发起”次数，失败可能同时计入 skipped.failed；三项不构成互斥分区，不代表成功落库率。正在执行的异步回执不在这里等待；摘要是读取时的盘面快照。既有卸载日志仍保留。

实现：[src/hooks.ts](../../src/hooks.ts)、[src/lib/hook_audit.ts](../../src/lib/hook_audit.ts)、[src/index.ts](../../src/index.ts)。

## 验证方式

环境：Windows；Node 24.19.0；Python 3.14.6。先安装锁定依赖：

~~~sh
npm ci --ignore-scripts --include=dev
npm run build
python -X utf8 tests/test_hook_audit_summary.py
python -X utf8 tests/test_hook_audit_summary.py --mutate
~~~

本轮实际读数：原实现运行新增测试 0/18 通过；实现后 18/18 通过。完整插件接线 S8 另 1/1 通过；该用例启动隔离的真实 Python MCP 子进程。S7 使用真实 Cordis，验证卸载、重装更新与宿主关闭。host 夹具同时把辅助身份/凭据根隔离到临时目录 mdcg-aux。

受影响回归命令：

~~~sh
node --import tsx --test --test-concurrency=4 test/hook_audit_summary.test.ts test/hook_audit_observability.test.ts test/hook_audit_concurrent.test.ts test/hook_audit_lock_owner.test.ts test/hook_receipt_audit.test.ts test/h1-source-filter.test.ts test/context-window.test.ts test/session-attribution.test.ts test/turn-reminder.test.ts test/host.test.ts
~~~

实测 **73 tests / 73 pass / 0 fail / 0 skipped**。npm run build 退出码 0。check_line_anchors.py 未登记红项 0，VERDICT=PASS。工作区索引检查通过，本机路径自检及追踪面扫描通过。发布件检查 R1–R7 全部通过，FAIL 规则数 0，1749 件中未扫文本件 0。

本地环境适配：npm 缓存放在工作区；环境只有 npm.exe，发布件检查需要的 npm.cmd 使用仓外临时转发入口调用同一 npm 可执行文件，未修改检查逻辑。tsx 在沙箱内调用 Windows 用户信息接口失败，相关测试改在沙箱外执行；上述测试均使用临时数据。

定点变异预注册在 tests/test_hook_audit_summary.py，期望失败集合与实测集合 **5/5 恰好相等**：

| 变异 | 期望红项 |
|---|---|
| M1 不输出摘要 | S1 / S2 / S5 / S7 |
| M2 删除重复收尾保护 | S1 |
| M3 允许负数 | S3：负数 |
| M4 将模拟正文追加进日志 | S1 / S2 / S5 / S7 |
| M5 index.ts 丢弃收尾函数 | S8（真实完整插件） |

每臂校验真实退出码 1 与失败项集合；拒绝语法/导入/运行器错误，finally 按原始字节恢复源文件。

## 不适用条件与验证状态

**部分验证**：上述本地构建、相关回归、生命周期与故障样本已验证通过；未运行远端 CI、Linux/macOS 矩阵、完整 DSH UI 的人工关闭/在线升级流程，也未跑全仓 npm test / npm run gate。没有把这些未测面写成已通过。

强杀进程、掉电、未走 Cordis 收尾的关闭方式不保证输出；不展示会话正文、审计 last/kinds 原文或文件路径，不新增设置页、计数重置或遥测。

依据用户指定的 AI 编程通用规范与灵枢适配表，先定义验收，再验证失败样本与变异，公开记录只使用相对路径。
