# 第二轮底层修正记录

在新实验前的边界测试中发现了可复现的误拒绝风险，因此只修改 CSRE 的负条件字面匹配；反思算法没有修改。

原有负条件辅助函数按子串计数。例如 `prod` 会命中 `product`，`production` 会命中 `nonproduction`，`生产环境` 会命中 `非生产环境`。第一轮启用负条件门控后，这类命中会实际过滤候选。新增的独立测试在修正前有 12 个失败子例。

修正为：ASCII 条件使用标识符边界；条件按字面转义；识别紧邻的有限中英文否定前缀；同一条件出现多次时，只要有一次非否定命中仍计数；同一条件去重后只计一次。显式关闭门控、门槛、排序补位和来源校验沿用已有契约。

验证记录分别保存：

- `negative-semantics-before.log`、`negative-semantics-after.log`：独立反例修正前后。
- `csre-regressions-fixed/output.log`：54 项 CSRE 与会话回归通过。早期测试夹具清理错误保存在 `csre-regressions/output.log`。
- `bottom-boundaries-after/results.json`：120 个新生成查询与 12 项边界断言，未出现误拒绝或负条件违规。
- `bottom-legacy-*/results.json/results.json`：100/1000 条目下，原始版本负条件违规均为 9/20，修正后均为 0/20；过期、跨库索引均拒绝。
- `native-mcp/boundary/suite.json`：实际 DSH MCP 传输进入实验适配器，13 项边界检查。原生 Memory MCP 的读写权限调用单独保留。

这仍是有限字面规则，不是自然语言语义理解。双重否定、复杂作用域、引用文字和英文条件大小写变化没有获得完整证明。120 个查询来自受限字面契约，不能外推为所有自然语言输入均无误拒绝。

所有状态写入 E 盘实验目录，修正只保存在候选源码工作区。反思默认关闭，未部署生产 DSH 插件。
