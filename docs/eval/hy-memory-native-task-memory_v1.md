# 原生任务双层记忆：交付证据 v1

## 意图、预期结果与信任边界

一次任务会话可以有值得续接的结果，却没有可复用经验。新增原生任务动作分别保存
结果与经验候选；保留原始证据、明确历史替代关系，并让经验继续服从资格与验证规则。
参考 Hy-Memory 的双层设计，未接入其 SDK，也未复制其实现代码。

这是新增能力，不把旧版本缺少新动作冒充既有数据损坏。基线固定为
`fe31327edfefdcdcf51afbaad49a598e563691ed`。真实模型抽取、自动 hook、生产数据收益、
跨任务语义路由、实际 DSH 宿主端到端、腾讯完整 System 2 与代码 diff 链均不在本交付的已验范围。

## 同一真实入口的改前/改后对照

用新检出中的探针驱动基线检出的 MCP server；输入内容完全相同，数据根各自临时隔离。

```bash
python -X utf8 scripts/verify_task_memory.py --repo BASELINE_CHECKOUT --expect absent
python -X utf8 scripts/verify_task_memory.py
```

基线原始 stdout：

```json
{"record_error": "未知 task action：'record_memory'", "state": "absent"}
```

改后原始 stdout：

```json
{"details_exact": true, "experiences": 0, "facts": 1, "new_process_read": true, "state": "supported", "unverified": true}
```

改后验证包含两个独立 server 进程：第一个写入，第二个回读；原始中文错误与
`timeout=37` 的数值保持相等，没有用摘要代替证据。

## 守卫与反面证明

Windows / Python 3.12：`python -X utf8 -m md_cg.test_task_memory`，18 项通过，0 失败，
新增守卫无 SKIP。覆盖真实 stdio、重启持久化、历史保留、重复请求、跨任务/主体拒绝、
密级/会话隔离、原生与 MCP 两层权限、写入策略、隐藏元数据审核、独立返回预算和来源失效。

`python -X utf8 -m md_cg.test_task_memory --mutate` 的原始结论：

```text
Mutations: 13/13 killed; failures=[]
```

每组先确认对应未变异守卫为绿，再只运行预注册的同一守卫；修改在内存模块中进行，
不改工作区源码。必须恰好点名预期守卫，否则该组不计通过。

| 变异 | 短路的约束 | 必须转红的守卫（`test_` 前缀省略） |
|---|---|---|
| M1 | 跳过结果持久化 | blocked_result_survives_without_an_experience |
| M2 | 放过相同编号的冲突重试 | record_identity_rejects_conflicting_retry |
| M3 | 不过滤已取代结果 | immutable_replacement_keeps_full_history |
| M4 | 丢弃来源结果链接 | experiences_deduplicate_and_keep_source_links |
| M5 | 丢弃原始证据 | blocked_result_survives_without_an_experience |
| M6 | 绕过原生操作权限 | permissions_are_enforced_by_native_and_mcp_entries |
| M7 | 让拒绝候选占 Top-K | rejected_experience_does_not_take_budget |
| M8 | 取消任务范围过滤 | scoped_filters_and_independent_budgets_precede_limit |
| M9 | 经验失败导致整条链抛错 | partial_failure_preserves_fact_and_retry_repairs_candidates |
| M10 | 放过草稿额外字段 | batch_validation_precedes_fact_write |
| M11 | 不声明来源依赖 | experience_is_doubted_when_its_evidence_is_falsified |
| M12 | 跳过结果写入审核 | unavailable_write_policy_blocks_persistence |
| M13 | 跳过经验写入审核 | admission_checks_metadata_and_preserves_fact_on_rejected_experience |

## 相关回归与交付检查

以下既有模块均退出 0，未输出 SKIP：

```text
md_cg.test_tasks
md_cg.test_issue398_toolface_op_parity
md_cg.test_tool_face
md_cg.test_p47_session_view
md_cg.test_p45_session_identity
md_cg.test_session_isolation
md_cg.test_p42_provenance
md_cg.test_trust
md_cg.test_security_audit_v21
```

TypeScript 构建与 op 元数据三向对账通过。`npm test` 在 Windows 实际 Python 3.12
解释器处于 PATH 首位时为 164 通过、0 失败、0 SKIP；WindowsApps 占位符与虚拟环境
启动器不作为这一轮的解释器，后者会干扰子进程父 PID 断言。
Linux CI 另行执行上述变异与跨进程回放。
生成的源码映射与工作区索引须随本次提交
更新；PR 当前 head 的 CI 链接与完整套件 PASS/SKIP 清单在提交说明中单独记录，
不能用本地定向测试替代。

基线的 `scripts/check_local_paths.py` 有一项既有 FAIL：
`md_cg/test_issue405_git_pathspec.py:131` 被判命中 DSH 本机 home 前缀；在上述基线检出
运行相同检查得到同一文件、同一行的 FAIL；PR #516 第一轮 Linux CI 亦复现。
独立共享前置 [PR #517](https://github.com/FuRongJun-1999/dsh-memory/pull/517) 将说明性注释
改成中性路径，并让 Python CI 完整检出 Git 历史，满足既有 `git log -S` / `git show`
修复前原形自证；不修改运行时代码、断言、扫描规则或豁免名单。此分支包含同一前置，
不作为任务双层记忆的核心贡献重复申报。前置清理后本机路径扫描退出 0。

主线旧 CI 的 9 份失败中，8 份需要完整历史；首轮完整历史 Linux CI 已全部通过。
Windows 的这 8 份整模块 7/8 退出 0；`test_issue265_coldverify_multiproc` 保留既有
S8a 时延失败（中位 7.910ms，高于 5ms 上界），不计通过、不改阈值。

另一份 `test_issue404_heal_receipt` 的 6 条 Linux 失败属于置景问题：POSIX 的删除权限
由父目录决定，文件 `chmod(0444)` 不能模拟 Windows 的只读删除失败。共享前置对
POSIX 的指定合成文件注入 `PermissionError`，Windows 仍使用真实只读位，不改原断言。
Windows 与 WSL/Kali Python 3.13.12 均已正向通过；M1/M2/M3 仍分别精确点红
8/1/2 项，镜像基线与骨架回退自证均通过。

首轮完整历史 CI 还检出新增数据类与 H-4 源码镜像加载器的兼容问题：延迟注解解析
需要临时模块在 `sys.modules` 中可见。共享前置在 `exec` 期间登记并于 `finally`
还原原值；不存在、显式 `None` 与已有模块三种状态已单独回放验证。全域扫描与
并发/逐位不变断言保持原样；Linux 完整 CI 的最终结果在提交说明中单独列出。

## 验收状态

本页是实现与可复跑证据，不是维护者的通过或结算。外部贡献通过 `intake` 申报，
CI、复现、守卫/变异与维护者人审分别登记；最终难度、影响和是否纳入悬赏由维护者裁定。
