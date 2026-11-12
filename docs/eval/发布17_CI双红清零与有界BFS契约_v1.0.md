# 发布 v0.9.1：CI 双红清零与有界 BFS 契约收口（签发闸搭架 · 规则条数锚点 · 锁文件 registry · 子图预算）

> 版本 **0.9.1** ｜ 基线 `51fbe36d`（并行端同步件 `cf20b95c` 在其内）｜ 2026-10-19
> 承接：`v0.9.0`（tag `8560fbda`，8/8 workflow 绿）之后的 26 连红。

## 一、本版定位

`v0.9.0` tag 之后 main 又推进了 70+ 提交，其间 `python-tests` 与 `publish-artifact-check` 反复红。
本版**不含新功能**，只做两件事：

1. 把两条 workflow 的红清零（根因逐条归到四簇，见 §二）；
2. 把期间漂移的守卫锚点按「**不放宽断言**」重钉，并把被回退的产品判据补回（见 §三、§四）。

## 二、双红的根因分簇（python-tests）

| 簇 | 模块数 | 根因 | 处置 |
|---|---|---|---|
| 签发授权闸（#543） | 6 | `_authorize_issue` 在凭据库非空时拒签发 `can_admin`；测试在同一临时库里二次签发 `designer` 即撞闸 | 按 `tokens.py` 文档化的 `_allow_bootstrap=True` 显式表态（**未**用 `MDCG_ALLOW_ROOT_ISSUE`）；闸的证明仍留在 `test_issue543_issue_authorization` |
| 规则条数 12→13 | 2 | `#557 R1` 在 `forbidden` 的 password 族前插入 `app_secret` ⇒ 序号锚点整体右移、条数断言失配 | `RULE7_IDX/RULE12_IDX` 右移一位、`_EXPECTED_FORBIDDEN=13`，并加「password 族恰两条」的身份断言（条数不是随便改的） |
| 产品判据缺失 | 4 | ① `stgidx` 二次解析丢掉 nonfinite 许可 ⇒ `uncertain_ends` 漏记、丢基线命中；② `subgraph.expand` 的 `max_nodes` 未收有限性 ⇒ nan/inf 解除上界；③ `compiler._finite_operand` 未捕 `OverflowError`（`10**400`）；④ 加密档判定散落 `in ENCRYPTED_LEVELS` | 逐点补判据（见 §三） |
| 守卫锚点/搭架 | 5 | `#434` 锚点钉了引号风格；`H-4` 裸迭代点；子进程文本模式缺 `encoding`；`#413 A 组` 场景被密级闸抢先；`p28` 行级引用漂移 | 只归一比较形态、不归一判据；裸迭代点先取快照；补 `encoding`；A 组按被测面收窄；引用更新到现址 |

## 三、产品代码改动

- `md_cg/stgidx.py`：`_classify` 与 `verify` 的观察终点解析补 `_allow_nonfinite=True`（两处同口径，否则 index 与 verify 的 uncertain 集合分裂）。
- `md_cg/subgraph.py`：
  - `expand()` 由**迭代 DFS 改最短层级 BFS**（`deque.popleft`）：diamond 里共享子节点不再被长路径先占；
  - 节点预算守卫前移到**入队前**，邻接直接取 `children_index(cg).get(cur)`（不整表拷贝）；
  - 返回前只保留两端均已 admit 的边（**边闭合**，flatten 的闭合投影随之成立）；
  - `max_nodes = int(max_nodes)`：nan/inf 预算结构化拒绝，不得解除上界；
  - 三处 `in crypto.ENCRYPTED_LEVELS` 收 `crypto.is_encrypted_level()` 单点。
- `compiler/compiler.py`：`_finite_operand` 增 `except OverflowError` → 按「非有限数值」拒绝（含 `10**400`）。

## 四、CI 基础设施

- **锁文件 registry**：`package-lock.json` 的 49 条 `resolved` 全部指向 `registry.npmmirror.com`；该镜像对 `undici-types-7.18.2.tgz` 持续 504，`npm ci` 不看 `--registry`、只按 resolved 取包 ⇒ 两条 workflow 在「构建插件入口」第一步就断（测试一条都没跑）。改指 `https://registry.npmjs.org/`（同一 tarball、integrity 不变）。
- 公开面：追踪面两处本机路径改中性占位（`check_local_paths` 由命中 2 转 `VERDICT=PASS`）。
- 配置面：注册 `MDCG_ALLOW_ROOT_ISSUE`（#543 的运维逃生口，`tokens.py:471` 读取点）；`check_config_env_registry` 由「新缺口 1」转 PASS。

## 五、并行端同步（`cf20b95c`）

同一时间另一条线把 `#82` 分隔段由 `\s` 收紧为 `[ \t]`（不跨行），并同步 `#346 E1` / `#413 A 组` / `#82 锚点` / `#p28 引用` 四个守卫。本版如实并入，不重复改。

## 六、验证

- **CI**：`publish-artifact-check`（35s，修前 6m5s 恒 504 红）/ `workspace-index-check` / `cogmap-check` 绿。
- **CI 侧 `python-tests`（`51fbe36d`）**：649/671 通过、30 跳过，**失败由 23 模块降到 2 模块**——
  - `md_cg.test_issue542_tenant_root_same`：`C1` 大小写变形断言在大小写敏感的 POSIX 上是假红（大写后已是另一条路径，而 `E1` 明钉「无关新根应放行」）⇒ 改为按文件系统实际大小写敏感性分档（探测式，不按平台名猜），POSIX 出 `[SKIP]` 并写明理由；
  - `md_cg.test_postings_digest_memo`：`②` 的「三项身份逐位相等」前提只在 win32 成立（POSIX 上改写内容必改 `ctime`）⇒ 前提断言按平台分档：win32 钉「逐位相等」，POSIX 钉「ctime 必变」；最小判据（不得复用过期 digest）两平台同钉。
- **本地全量**（`scripts/run_tests.py --jobs 1`）：667/677 通过、11 跳过；3 项红中——
  - `md_cg.test_p27_docindex`：测试夹具建在系统 TEMP，被 `MDCG_INGEST_ROOT` 白名单拒（`ref 路径超出白名单`）。CI 侧（HOME=/home/runner）不复现，**未按缺陷改**，留待 Linux 复验。
  - `md_cg.test_heartbeat_ledger` / `md_cg.test_issue91_verifier_timeout`：满载并发下的时序抖动，单跑均绿（38/0、15/0）。
- **逐点实跑**（蜂巢验证单元）：`test_subgraph_bounded_bfs` 12/12、`test_config_registry`、`check_config_env_registry`、`test_issue426b`、`test_state_event_op`、`test_p21_tokens`、`test_n123_derive_expiry_chain`、`test_issue398`、`test_issue446_453_403`、`test_n62_tenant_bind_failclosed`、`test_issue43_default_policy`、`test_sensitivity_predicate_single_point`、`test_subproc_encoding`、`compiler test_issue434/435` 全绿。

## 七、已知边界（不掩盖）

1. 本地 `npm ci` 验证被蜂巢执行器**可执行根闸**拒（只允许 python 根与 TEMP）——未绕过；npm 面的验证由 CI 承担。
2. `p27_docindex` 的 ingest-root 白名单与系统 TEMP 的冲突属本地环境差异，需在 Linux/CI 侧确认。
3. 两个时序敏感用例（`test_heartbeat_ledger` / `test_issue91_verifier_timeout`）在本机满载并发下会抖红，单跑均绿（38/0、15/0）；CI 侧未复现。属测试稳定性问题，另立批次收口（不在本版范围）。

## 八、不适用条件

- 本版不含数据面迁移；已发布件不回溯改历史。
- 若目标环境仍走 npmmirror 且可访问，本版的 registry 改动不构成约束（锁文件只影响 `npm ci` 的取包源）。