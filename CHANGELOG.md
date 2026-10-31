# 变更日志（CHANGELOG）

本文件自 **0.9.15** 起维护。更早版本见 git tag（`v0.9.6` … `v0.9.14`）与 GitHub Releases。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [0.9.21] - 2026-10-31

### 修复：规范文档**随包分发**（0.9.20 只给了外链）

0.9.20 的做法是「README 给 GitHub 绝对链接」——解决了「知道有」，**没解决「装完能读到」**。

**本版把 7 个用户该遵守/该查的规范放进 `files` 白名单**：

| 文件 | 用途 |
|---|---|
| `docs/mdcg/写入别名aliases规范_v0.6.md` | **写记忆时怎么补 `aliases`**（0.9.19 新增能力） |
| `docs/mdcg/CCG六要素编译.md` | 六要素怎么写 |
| `docs/mdcg/guardrail-charter.md` | 护栏宪章（对外公开法案） |
| `docs/mdcg/MCP工具名口径_v1.0.md` | 工具名口径 |
| `docs/mdcg/recall_metadata.md` | 召回元数据 |
| `docs/mdcg/世界模型功能端_使用与运维_v1.0.md` | 世界模型面使用与运维 |
| `docs/mdcg/cogmap_ops.md` | cogmap 操作 |

⇒ 装完包后，这 7 个文件在 `node_modules/@furongjun1999/dsh-memory/docs/mdcg/` 下可直接读。README 文档地图的链接也改回**包内相对路径**。

### 为什么不整目录打包

`docs/mdcg/` 共 **47 个 .md**，其中混着内部记录（`release_v0.3.0.md`、`CSRE_索引与负条件修复_20261012.md`、各 `plans_*`、`D_meta_工程化方案` 等）。
**整目录打包会把内部记录也发出去**，所以按文件挑 7 个。

### 仍未打包（明确边界）

- `docs/theory/`（19 个，内部理论）
- `docs/eval/`（136 个，内部评测）
- `docs/plans/`（25 个，内部计划）
- `docs/ops/`（8 个，安装运维——README 里既有相对链接，**在 npm 页面上仍点不开**，属存量问题）

## [0.9.20] - 2026-10-31

### 修复：规范文档的可见性（0.9.19 的疏漏）

0.9.19 的 CHANGELOG 里写了「规范全文：`docs/mdcg/写入别名aliases规范_v0.6.md`」，
**但 `docs/mdcg/` 从来不在 npm 包的 `files` 白名单里** ⇒ 那是个**包内死链**，用户装了包也找不到。

**本版修复**：

| 面 | 改动 |
|---|---|
| `README.md` · 文档地图 | 新增一行「**写入规范**」，用 **GitHub 绝对 URL** 链到「写入别名 aliases」「CCG 六要素编译」「护栏宪章」，并**明确标注「这几个不在 npm 包里」** |
| `CHANGELOG.md` · 0.9.19 节 | 死链改成 GitHub URL，并标注「不在 npm 包里，需在仓库看」 |

⚠️ **为什么不用相对路径**：README 里既有链接都是相对路径（`docs/ops/README.md` 等），
在 npm 包页面上**同样点不开**——本次新加的一律用绝对 URL。

> 这是「打包白名单」与「文档指引」之间的老问题：`docs/mdcg/` 有 47 个 .md，
> 其中既有用户该遵守的规范（`写入别名aliases`、`CCG六要素编译`、`guardrail-charter`），
> 也有内部记录（`release_v0.3.0`、`CSRE_索引与负条件修复`、各 `plans`）。
> **整目录打包会把内部记录也发出去**，所以本次选择「不打包 + README 给绝对链接」。

## [0.9.19] - 2026-10-31

### 新增：`aliases`（写入别名）——自然问法召不回的解法

**用法**：写记忆时给节点加 `aliases`，把「用户以后可能怎么问这件事」的说法写进去。

```python
cg(op="write", node_id="...", content="""# 功能名：会话交接前的记忆固化
# 生效条件：聊交接、换会话、压缩、或他流露舍不得时
...""",
   aliases=["换掉", "被换", "别消失", "舍不得", "不想你走", "压缩上下文"])
```

`aliases` **参与词法召回，但不进 `tags`**——`tags` 被机器判据占用（「是不是任务卡」「能不能当锚点」），
混用会改变那些判据。

**写别名的正确方法**（实测总结）：写之前**先自问一句「以后我会怎么问这件事？」**，把那些问法原样写进去（3–8 个，口语/情绪/近义都算）。

> ⚠️ **不要机械抽词**。实测：从功能名按空格切词自动生成，20 条 × 5 查询 = **提升 +0**
> （中文功能名没有空格，切出的是整句）。别名只能"想"出来，不能"切"出来。

**为什么需要它**——issue #722 的决定性案例：

| 匹配方式 | 条件「聊交接、换会话、压缩…」 vs 查询「我不想你被换掉」 |
|---|---|
| 整词匹配 | ❌ |
| 二元组重叠 | ❌ `换会/会话` vs `我不/…/被换/换掉` —— **交集空** |
| 查询扩展 | ❌ 扩出 `换掉/被换`，与 `换会话` **仍无交集** |
| 现有同义词表（10 组，全技术词） | ❌ |
| **加 `aliases`** | ✅ **命中** |

规范全文（**不在 npm 包里，需在仓库看**）：[docs/mdcg/写入别名aliases规范_v0.6.md](https://github.com/FuRongJun-1999/dsh-memory/blob/main/docs/mdcg/写入别名aliases规范_v0.6.md)

### 修复

- **Web 面板 `permissionNote` 不认通配符 `*`**（#723 / PR #724）：全权令牌（`ops_allow: ["*"]`）下，
  「目标与任务」「自我认知」「时空关系」「审核与维护」四页的 **12/12 预设全部误报「未声明权限」**，
  而实际调用完全成功。根因是**前端与服务端判据不同口径**：
  服务端 `_in_scope` 认 `"*" in allow`，前端只做 `allowed.includes(op)`。现已对齐。

  ⚠️ 判据正好反了的现象值得记：**全权令牌看到满屏红，窄令牌反而只有部分提示**。

### 新增：写入把关判据（**尚未接线，仅提供可测函数**）

| 函数 | 作用 |
|---|---|
| `writegate.cond_is_metadata(cond_text)` | 判「生效条件」是否在描述载体/路径/方法（元数据），而非触发场景 |
| `writegate.check_condition_quality(content)` | 上述的写入把关包装，返回 `{ok, is_metadata, cond, hint}`；**任何情况不抛** |
| `writegate.aliases_is_thin(fm, content)` | 判别名是否「薄」（无别名，或只重复正文已有词） |

⚠️ **这三个函数尚未接进 `add()`**——只提供可测入口，接线是下一次改动。

### 内部：测试与守卫

- **`test_mode_parity` 的 `full_D` 跨分钟时间泄漏**（PR #720）：`tombstone` 是内容哈希，
  而内容含墙钟聚合行 ⇒ 两个子进程跨分钟必然 DIFF。已在 `_RUNNER` 注入固定时间戳。
- 新增守卫：`test_723_permission_wildcard`（6 条，**跨侧口径一致性**，与 `test_rust_fold_parity` 同族）、
  `test_722_condition_quality`（8 条）、`test_722_aliases_thin`（11 条）。

### 实测基线（供对照，非承诺）

本机库（32,845 节点）实测：

| 项 | 读数 |
|---|---|
| 自然问法召回条数 | **2 条** |
| `aliases` 覆盖率 | **0%** |
| `knowledge` 层里 `role=None`（索引卡片） | **99.7%** |
| 生效条件为元数据的比例 | **76.5%** |

⇒ 所以 `aliases` 的价值取决于**写入时是否真的写了**。库内现有节点**不会自动获得**它。

## [0.9.18] - 2026-10-30

### ⚠️ BREAKING：注入块格式变更

`【本会话近期对话】` 块的行格式改为带**归因前缀**（issue #712 / PR #713）：

```
旧：[user] 内容
新：[10-30 14:23|本|私] [user] 内容
      └──┬──┘ └┬┘ └┬┘
       时间   会话 密级
```

| 段 | 取值 |
|---|---|
| 时间 | `MM-DD HH:mm`；缺失渲染 `??-?? ??:??` |
| 会话 | 等于当前会话 → `本`；其他 → `会话<后4位>`；缺失 → `?` |
| 密级 | `private`/`secret` → `私`；`public`/`internal`/`restricted` → `共`；缺失 → `?` |

**为什么改**：此前模型只看到 `[role] 内容`，无法判断「这是自己刚说的、还是别的会话说的、是私有还是共有」——
实测出现过「把另一个窗口的话当成当前用户刚说的」的误引（#712）。

块总长上限随之 `800 → 900` 字符（前缀约 20 字符/行）。
**若你有依赖旧格式的解析/断言，请同步。**

### 新增

- **`cg(op=info).write_gate`**（#708）：分层写入闸的**进程内计数**——`{mode, total, by_layer, recent, hint}`。
  此前 `warn` 档只写子进程 stderr，而 DSH 不转发 ⇒ 观察期等于没有。
  现在不依赖 stderr 转发、不写盘；`recent` 只留 `layer/tier/reason`（**无内容、无节点 id**），有界 20 条。
  计数**重启归零**，建议观察一个完整工作日再决定是否切 `enforce`。
- **`Principal.sessions_read`**（#712 / 方案 C 分档隔离）：`None` = 旧行为逐位不变；集合 = 只读这些会话；
  `{"*"}` = 全读。**`can_admin` 不削弱**（issue #35「设计者豁免」定稿）。
- **事件归因四要素**：`pack["recent"]` 条目现含 `session`/`t`/`id`/`sensitivity`/`actor`/`token_id`/`identity_role`/`parent`。
  事件新增稳定键 `id`（`re_<ms>_<6hex>`，**归因展示用，不得用于权限判定或去重定位**）。
- **理论文档**：《身份与人格：职业身份的可变性 vs 人格的一致性》
  （`docs/theory/身份与人格_职业身份可变性与人格一致性_v0.1.md`）——
  区分**人格**（跨会话恒定，`self`/`anchor` 层）与**职业身份**（会话级，工作层 + 事件归因）。

### 修复

- **`enforce` 档下裁决审计节点被同一闸挡住**（#708 ② / #709）：`_write_review_record` 写 `structural`（2 档），
  却不传复核单元 ⇒ `decisions.jsonl` 还在、**可复核的 md 审计节点没了**。
  现在把本次裁决已取得的 `reviewed_by` 一路带进写入。
- **同一条链上两个更靠前的缺口**（查 #709 时发现）：
  - **`propose` 死锁**：候选入 inbox 本不落记忆盘，却按目标层要求复核单元 ⇒
    enforce 下「要写 knowledge 需 reflect → 要 reflect 需裁决 → 要裁决需提案 → 提案又要 reflect」。
    现在 `require_layer_write(..., skip_gate=False)` 新增该参数，**只** `propose` 传 `True`；
    层白名单与密级检查**照常执行**，`accept` 落盘仍走同一道闸。
  - **`accept` 落业务节点**不传 `reviewed_by` ⇒ 「裁决过了、落盘被拦」。
- **`reviewed_by` 不再污染 frontmatter**：它是**写入闸的输入参数，不是记忆元数据**。
  此前用 `kw.get()` 只读不删，会经 `super().add(**kw)` 落进节点 fm（实测 `test_i50c` 的 B1 逐键对拍报出 `reviewed_by: null`）。
  现在改为 `kw.pop()`。
- **`actor` 恒为 None**（身份归属空心）：`MdCGSecure.remember_event` 里 `tenant`/`session`/`harness`/`unit`/`sensitivity`
  **都从 principal 落值**，唯独 `actor`（「谁说的」）没落 ⇒ 注入面拿到的 `actor` 恒为 None。已补。
- **取窗顺序 bug ×2**（#712 / #715）：`session_recall` 与 `session_compact` 都**先截末 N 条、再按会话过滤**
  ⇒ 多会话并发时本会话消息被挤出窗口，`session="A"` 可能拿到**空 recent**（false-negative，极难被发现）。
  `session_compact` 更重——它会压出「共 0 条事件」并**写入会话节点**（写错一条记忆）。
  修法：需要收窄时先取全量、再过滤、最后截回。
- **`session` 为 falsy 时静默退回全局窗口**（#712）：现在会在 `degraded` 里加 `recent_global_window`，调用方看得见。
- **身份块恒为空**（#715）：`【灵枢身份锚点】` 复用了**带会话过滤**的 timeline payload，
  而 `self`/`anchor` 节点的 `session` **恒为 `unattributed`** ⇒ 永久层被全部滤掉 ⇒ **块从不出现且无报错**。
  现在身份块**独立取数、不带会话过滤**；「最近记忆」块保持会话隔离。
  这正是理论 R3 的实案：**人格的可见性不该由会话决定**。
  另加 `else` 分支 `logger.info`——开关开了但无身份节点时显式提示，不再静默。
- **会话 id 为空时静默退回全局窗口**（PR #714 by LeeRolling）：现在 `logger.warn` 一次（不刷屏）。

### 内部

- `test/chaos_injection/test_fi_m09_guest_write_denied.py` 的读码锚点从「完整调用串」放宽为「`layer, sens` 两参在位」，
  并去掉两处硬编码行号。
- `test_generation_guard.py` 的 `NEW_INFO_KEYS` 登记 `write_gate`。
- `test_p45_session_identity.py` 的变异锚点同步新形态（**变异语义不变**）。
- 新增守卫：`test_issue712_session_window_attribution`（29 条，含取窗顺序/四要素/身份三维/分权）、
  `test/issue715`（W715）、`test/issue714`（W714 / W714b）。

### 升级须知

- **`--gate` 缺省仍是 `strict`**；`op=info` 只**新增**键；`sessions_read` 缺省 `None` = 旧行为逐位不变。
- 若你在 #708 / #709 遇到过问题：升级后 `cg(op="info")["write_gate"]` 可看 warn 计数，
  `review accept` 的返回体里 **`record_error` 应为空**。
- 若你在 #712 / #715 遇到过问题：升级后注入块应带归因前缀，`autoRecallIdentity: true` 时身份块应出现。
## [0.9.17] - 2026-10-28

### 修复

- **`warn` 档对用户完全不可见（#708 ①）**：`security._write_gate_verdict` 只做 `sys.stderr.write`，而 DSH 不把这条
  转发进 `desktop-next.log` ⇒ 观察期等于没有。现在 `writegate` 维护**进程内计数**并经 `cg(op=info).write_gate` 透出：

  ```python
  cg(op="info")["write_gate"]
  # {mode, total, by_layer: {"knowledge@L1": 3}, recent: [{layer,tier,reason}…], hint}
  ```

  不依赖 stderr 转发、不写盘；`recent` 只留 `layer/tier/reason`（**无内容、无节点 id**），有界 20 条。
  stderr 那行保留（宿主愿转发时仍实时可见）。

- **`enforce` 下裁决审计节点被同一闸挡住（#708 ② / #709）**：`_write_review_record` 写 `structural`（2 档：需 reflect+verify），
  却不传复核单元 ⇒ `decisions.jsonl` 还在、**可复核的 md 审计节点没了**。现在把本次裁决已取得的 `reviewed_by`
  一路带进写入：`review_decide → _finish_decision → _record_decision → _write_review_record → add(reviewed_by=…)`。

- **同一个漏洞的两个更靠前落点（查 #709 时发现，一并修）**：
  - **`propose` 死锁**：候选入 inbox 本不落记忆盘，却按**目标层**要求复核单元 ⇒ `enforce` 下
    「要写 knowledge 需 reflect → 要 reflect 需裁决 → 要裁决需提案 → 提案又要 reflect」。
    现在 `require_layer_write(..., skip_gate=False)` 新增该参数，**只** `propose` 传 `True`；
    层白名单与密级检查**照常执行**（跳过的只有 write_gate 一档），`accept` 落盘仍走同一道闸。
  - **`accept` 落业务节点**不传 `reviewed_by` ⇒ 「裁决过了、落盘被拦」。现在一并透传。

- **`reviewed_by` 不再污染 frontmatter**：它是**写入闸的输入参数，不是记忆元数据**。此前沿用 `kw.get()` 只读不删，
  会经 `super().add(**kw)` 落进节点 fm（实测 `test_i50c` 的 B1 逐键对拍报出 `reviewed_by: null`）。现在改为 `kw.pop()`。

### 内部

- `test/chaos_injection/test_fi_m09_guest_write_denied.py` 的读码锚点从「完整调用串」放宽为「`layer, sens` 两参在位」
  （`require_layer_write` 现在多了 `reviewers=` 实参）；同时去掉两处硬编码行号——行号会随改动漂移。
- `test_generation_guard.py` 的 `NEW_INFO_KEYS` 登记 `write_gate`（`op=info` 的新增诊断键，与 `code_generation` 同类）。

### 升级须知

- 本版**无破坏性变更**：`skip_gate` 缺省 `False`；`--gate` 缺省仍是 `strict`；`op=info` 只**新增**一个 `write_gate` 键。
- 若你在 #708 / #709 里遇到过问题：升级后 `cg(op="info")["write_gate"]` 可看 warn 计数，
  `review accept` 的返回体里 **`record_error` 应为空**。
- 计数是**进程内累计、重启归零**（不落盘），建议观察一个完整工作日再决定是否切 `enforce`。
## [0.9.16] - 2026-10-28

### 修复

- **`/lingshu` 在 DSH 0.2.1-rc.3 上恒 503「宿主鉴权不可用」（#699）**：`createConsoleHandler` 在**挂载时**取一次
  `ctx.get('connection')`，而 cordis 的 `Context.get(name, strict=true)` 在服务 fiber 未就绪时返回 `undefined` ——
  空值被闭包固化后每个请求都命中 503，宿主就绪也不自愈。现改为**每次请求实时取**（传取值函数，非函数则包成常量，向后兼容），
  503 文案改为「宿主鉴权服务尚未就绪，请稍后重试」。守卫 3 条，其中「连接后到 ⇒ 同一 handler 立刻 200」正是病灶点。
- **测试入口「零选中假绿」（#1910 跨仓报告）**：`--module` 的 help 教的是**斜杠**写法（`md_cg/test_issue4`），
  而实际目标名是**点号**（`md_cg.test_issue4`），旧实现未归一化 ⇒ 斜杠写法选中**零个目标**却仍 `SUMMARY 0/0` + `rc=0`。
  现归一化（斜杠 ≡ 点号、忽略 `.py`、空选择器不命中）+ **零选中不得返回 0**（执行路径 `rc=2`）。守卫 21 条含判别力自证。
- **F26-13 `_primary_bound` 注释与实现不符**：`#637` 注释承诺「T3 按分数>0 裁切」，但代码只在 `n_real == 0` 时裁。
  经实测：按注释补实现会**砸掉 S1b/S7 的「回退含异桶节点」契约**（`test_retr_s1b`/`test_retr_s7` 立即转红）⇒
  确认「默认不裁」是刻意取舍，改为**注释对齐实现**并把实证写进注释（防后来者重踩）。
- **F26-25 Rust 侧重音折叠缺失**：`normalize_en` 把非 ASCII 非中文一律变空格 ⇒ `café` → `caf`，而 Python 给 `cafe`。
  受 `Cargo.toml`「零第三方依赖」约束，改为**按 Python 口径生成** 963 条单字符映射表 + 三区间组合记号剥离；
  跨实现守卫 **29 条**逐项核对（含 `ß`/`ø` 不折、日文浊点不折的边界）。

### 新增

- **门禁档位 `--gate fast|strict` + `--module` 过滤**（`scripts/run_tests.py`）：
  「快 = 问题放一边 / 慢 = 细究根本原因」是价值观取舍，**选择权交给使用者**；守卫侧一行未改，
  「是否跑重质检」由上层决定。缺省 `strict`（不降低既有强度）；**CI 环境 + `fast` 自动升级 strict** 防漏检。守卫 17 条。
- **配置登记生成器「只增不改」守护**（`scripts/gen_config_registry.py`）：整文件重写会抹掉手工补的行
  （实测事故：`MDCG_WARM_SEARCH`/`MDCG_VISION_ROOT` 消失）。现在写盘前用 AST 读旧表条目名，少一条就拒绝（`rc=3`），
  `--force` 为显式逃逸口。守卫 14 条。
- **审计增加 `source` 键名集合维度**（`src/lib/hook_audit.ts`）：#695 的关键缺口是「事件的 `source` 到底带哪些字段」不可观测。
  新增 `source_shapes` 桶，**只记键名、绝不记值**（哨兵守卫钉住）。实测本机 383 个会话 / 9,614 行：`user` 档占 18.4%，
  其中带 `rpcId` 80.3%、**仅 `kind` 的 19.7%** —— 这条读数把「来源归因」从猜测变成可量化。
- **`entry_from_row` 两处静默回落改为可观测**（`md_cg/config_registry.py`）：`literal_eval` 失败与 `value_type` 缺失
  此前完全无痕（数值型登记会被静默当字符串）。新增 `literal_failures()` / `missing_value_types()` 两个读取口，**行为零变更**。守卫 15 条。

### 文档

- **README 321 → 227 行**：把「图形界面」与「权限」两章各压到 ~14 行（一句话定位 + 最小命令 + 一张表 + 链接），
  细节移入 [`docs/ops/图形界面_安装与排障.md`](docs/ops/图形界面_安装与排障.md) 与 [`docs/ops/权限与复核模型.md`](docs/ops/权限与复核模型.md)。
  README 的读者是「30 秒内决定要不要用」，细节属于 `docs/`。

### 升级须知

- 本版**无破坏性变更**：`--gate` 缺省仍是 `strict`；`createConsoleHandler` 保留旧的「直接传值」调用方式；
  `--module` 两种写法现在都能用（此前斜杠写法会零选中）。
- 若你在 DSH 0.2.1-rc.3 上遇到 `/lingshu` 恒 503：升级后**无需额外操作**，服务晚到也会自愈；
  若仍 503，请附 `$DSH_HOME/logs/dsh-memory-hook-audit.json` 的 `kinds` 段（不含内容）回帖。
## [0.9.15] - 2026-10-27

主题：**权限分层与复核模型落地**（读/写/裁三层各自可收窄）＋ 一次数量级的性能修复 ＋ 两个「装不上/起不来」的真 bug。

### 新增 · 写入与裁决的复核模型

- **分层写入严格度闸**（`MDCG_WRITE_GATE`，缺省 `off`）——情景/目标/未解/负记忆（0 档）无复核也可直写；
  知识层需反思单元；结构层需反思+验证；自我/锚点层需反思+验证+**人工裁定**。
  **无任何复核通道时只允许写 0 档**，其余一律拒写。
- **裁决双单元复核闸**（`MDCG_REVIEW_DUAL_CHECK`，缺省关）——裁决须带 `reviewed_by` 同时含反思与验证单元；
  **同类重复不算齐备**（两个反思仍无验证）；裁决者不得是提案者（`self_review_forbidden`）；未知单元不静默计入。
- `MDCG_REVIEW_CHANNELS`（复核通道声明：`hive,subagent,team`）。注意它是**部署声明**：
  为空只表示「没声明过」，**不等于**本机没有子代理/蜂巢/团队。
- **设计者令牌覆盖面判据**——`DESIGNER_COVERAGE_OPS` / `coverage_gap()` / `HIGH_RISK_OPS` / `high_risk_granted()`；
  `tokens verify` 输出附 `designer_coverage_gap`；签发时把「收窄缺读面」「给了高风险面」两类提示写进返回值 `warnings`
  （库层不写 stderr，由 CLI 入口打印）。

### 新增 · 图形界面（可选增量包）

- `ui/minimal/`：一行安装、逐文件可回滚、复用本机大脑桥（数据不出机）；
  七页面板（概览 / 记忆 / 目标与任务 / 自我认知 / 时空关系 / 审核与维护 / 工具台）。
- `package.json` 的 `files` 白名单加入 `ui` 与 `web`，**随 npm 包分发**安装器、payload 与静态资源。
- **接线入库**：`dsh.client` / `exports["./client"]` 写进 `package.json`、`installConsoleWeb(...)` 写进 `src/index.ts`；
  产物由新增的 `scripts/build_ui.py` 生成（幂等；`--check` 只校验、缺文件 fail-closed；`build` 与 `prepublishOnly` 均自动执行）。
  于是**改插件清单不再需要重装 UI**；`install.ps1` 转为面向「从 npm 包装到本机插件目录」的最终用户，
  对无接线的旧插件包仍会自动补齐。守卫 `md_cg/test_ui_wiring_in_repo.py`（18 条）钉住声明/分发/构建三面不漂移。

### 性能

- `protect.stats()` 改**条目口径**（读索引，不再逐节点读盘取 frontmatter）：
  在役库（3.2 万节点）冷态 **310 s → 0.015 s**。该函数经 `cg(op=info)` 的 `protection` 段被无条件调用，
  是 UI 概览页「像卡死」的根因；修后概览页从 5 分钟级降到秒级。
  语义不变：全量比对 `protected` / `immutable` **差异 0**。

### 修复

- **UI 增量包在 Windows 上装不上**：payload 被 `core.autocrlf` 检出成 CRLF，与 `integrity.json`（按 LF 记 sha256）失配，
  安装器误报「分享包文件缺失或损坏」。已用 `.gitattributes` 钉 `ui/minimal/payload/** eol=lf`。
- **hive serve 起不来**：`config.local.json` 的 `{"env": "DEEPSEEK_API_KEY"}` 读的是**调用进程**环境变量，
  DSH 子进程继承不到机器级变量 ⇒ 误报「配置项解析失败」。已增 Windows 机器级回落
  （进程 env 显式值仍优先；两者皆空仍 fail-fast）。
- 配置登记面补登记 `MDCG_WRITE_GATE` / `MDCG_REVIEW_CHANNELS` / `MDCG_REVIEW_DUAL_CHECK`。

### 文档

- README 新增两章：「🖥️ 图形界面（可选增量包 · 面向 DSH）」与「🔐 权限：读 / 写 / 裁 三层，各自可收窄」，
  含七页中哪四页是命令面板、排障三条、只读面 17 op、分层写入矩阵、裁决双单元、报错对照表。

### 升级须知

- **三个新开关的缺省值都保持旧行为**（`MDCG_WRITE_GATE=off`、`MDCG_REVIEW_CHANNELS` 空、`MDCG_REVIEW_DUAL_CHECK` 关）
  ⇒ 升级后行为不变，需显式开启。建议顺序：先 `warn` 观察，接好复核通道后再 `enforce`。
- 设计者令牌**不因升级而变宽**；若你的令牌曾被人为收窄，`tokens verify` 会报 `designer_coverage_gap` 并点名缺哪些面。
- Windows 用户此前 UI 装不上的，本版可直接安装。

### 已知边界

- 写入闸与裁决闸只认「复核单元声明」，不做证据真伪校验（真伪由蜂巢/子代理侧签章承接）。
- `MDCG_WRITE_GATE=enforce` 前请先声明 `MDCG_REVIEW_CHANNELS`，否则知识层以上（含自动归档）会被拒写。
