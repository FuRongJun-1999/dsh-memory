## v0.4.11（2026-09-20）

**npm**：`@furongjun1999/dsh-memory@0.4.11`（前置不变：Node ≥ 22.19 · DSH 内核 ≥ 0.1.2-rc.1）

> **本版三件事**：①修第三方 v15 报告九项 ②修首装平台差异（issue #19）③**发版门禁**建立与**发布件收口**——0.4.9 / 0.4.10 两个已发布 tarball 夹带非追踪件（4009 件 / ~28 MB）的缺陷由 `cee729a` 收口，**0.4.11 发布件为 1306 件**（本地门禁实测）；事实、根因与处置裁定见 [发布件回溯说明](../发布件回溯说明_v0.1.md)。

> **版本一致性（如实披露）**：npm `0.4.11` 的 tarball **早于本 tag 一步**——其 `docs/工作纪律_认知图条目_v1.1.json` 与各端纪律产物（`codebuddy/CODEBUDDY.md`、`zcode/AGENTS.md`、`codex/AGENTS.md`、`claude/CLAUDE.md`、两份 plugin skill）为 **17 条**；本 tag 为 **18 条**（新增「工作区索引优先」），并含工作区索引管线与投影同步器修复。差异**仅限纪律增量与仓库内工具面**（`scripts/` 不在 npm `files` 白名单内，故脚本增量不入包），功能面一致。npm 同版本号不可覆盖，故此处留痕而不回溯——口径与 §发布件回溯说明一致。

### 本版变更（0.4.10 → 0.4.11，共 7 次提交）

**新增：发版门禁（拦下一次夹带）**
- `scripts/check_publish_artifact.py`：四类硬失败——R1 凭据/密钥 · R2 私有数据面 · R3 隐私文本 · R4 非追踪件；本地模式（`npm pack --dry-run` 清单 × 工作区内容）与 `--registry` 后置核验双模式；退出码 fail-closed（0 通过 / 1 有命中 / 2 环境错误）；内置 `--selftest`。
- `.github/workflows/publish-artifact-check.yml` + `package.json` 的 `prepublishOnly` 挂载：**红着即拦下一次发布**。

**修复**
- **首装平台差异**（issue #19）：解释器默认值写死 `python`，而 Linux / macOS 依 PEP 394 只提供 `python3`（发行版默认状态）→ `spawn ENOENT` → 桥重试 8 次进终态：插件加载不报错、但工具不注册、记忆永不落盘、不自愈；日志被「灵枢调用超时」这一次生现象掩盖第一因。新增 `src/lib/python_path.ts`（平台默认 + `MDCG_PYTHON` 覆盖 + ENOENT 指引文案），`mutual.ensureHarness` 与各端配置样例同步去掉写死的解释器。
- **发布清单解析缺陷**（CI 恒红）：`prepare` 生命周期脚本会向 stdout 打印文本（`[prepare] 跳过构建…`），而清单解析以 `find("[")` 定位 JSON 起点 → 命中 `[prepare]` 首字符 → 解析失败 exit 2。本地装了 typescript 故 `prepare` 静默、该路径从未暴露 → 「本地恒绿 / CI 恒红」双环境盲区。改 `json.JSONDecoder.raw_decode` 逐候选点试解析。
- **`.npmignore` 收口**：`files` 白名单粒度到目录，且 npm 在存在该白名单时**不读根级 `.npmignore`** → 白箱 KB 运行时数据 / `docs/experiments` / 本地记忆面 / 字节码缓存随包分发（R2/R4 各命中 2449 件）。改**子目录级** `.npmignore`（`md_cg/` · `docs/` · `skills/`）：发布清单 4009 → 1306 件。

**第三方 v15 报告九项**
- `coldverify`：`patrol_check` 与 `propagate_depth` 的 `ok` 由**内层结论**决定（不再硬编码 `True`），失败计入 `stats.errors`；`_load_persisted` 与 `enqueue` 同白名单校验 action（拒收计 `skipped`）——冷队列回执不再「假装成功」。
- **147 条 Python 套件接入 CI**：`.github/workflows/python-tests.yml`（此前不在任何 workflow 内，红基线无人可见）；刻意不加 `paths` 过滤，避免「改动不入门禁」盲区。
- `hive/exec.py` 落盘面补 `TOOL_DUMP_MAX_CHARS` 上限（此前回喂面已收紧、磁盘面无天花板），docstring 与实现对齐。
- `md_cg/trust.py` 澄清 `propagate` 的 `reachable/updated` 口径（本次需新标记数，完整波及集须叠加 `passed_doubted`）；`test_datapath_root` 按 `os.path.isabs` 判据复算（POSIX 不再必红）；编码「唯一构造点」由主张升为**被守护的不变量**（互斥面站点扫描，剥离注释与字符串避免字面量自伤）。

**纪律与文档**
- **工作纪律新增第 18 条「工作区索引优先」**：查工作区文件先读 `WORKSPACE_INDEX.md`（仓根，由 `scripts/workspace_index.py` 从 git 追踪面机械生成），无则先生成再读，不以重复全盘浏览代替；索引纳入 CI 陈化守卫（`.github/workflows/workspace-index-check.yml`）——守卫面已在文档内显式声明（目录集合 / 根级文件集合 / 职责与关键入口 / 正文逐字），**承诺项与守卫面一致**。
- 修纪律投影节点同步器两处缺陷：①同批次「新建」节点的 nid 碰撞——`now` 在循环外只取一次，多条纪律共用同一文件名，后写覆盖前写（实测 18 条只留最后 1 条）；②root 缺 `_md_cg_` 前缀守卫——该前缀目录是工具链导出/评测产物，禁止作为认知图 root（与 MCP server 同名守卫同口径，fail-closed）。
- 详情 README 更名 `README详细版_v0.4.10.md`（7 处引用同步）+ 新增「0.4.6 → 0.4.10 变更速览」表；智能论 v3.4 同步（白箱 KB 种子实体逐字节取自 `docs/theory/智能论3.4.md`）。

### 验证

- `npm test` **26/26** 通过
- Python 套件 **147/147** 通过（本版起全量接入 CI）
- 三门禁全绿：`verify_discipline` **8/8**（含认知图投影节点 **18/18**）· `cogmap check` · `link_check`（OK 190 / BROKEN 0）
- 发布件门禁 `VERDICT=PASS`：清单 **1306 件**、非追踪件 24 = 允许上限 24
- 新件自检：`test/python-path.test.ts` 8 断言 · `python-utf8-mode.test.ts` 语义匹配 · 门禁 `--selftest` 全绿

### 升级

```bash
npm i -g @furongjun1999/dsh-memory@0.4.11
# 或（DSH profile）
dsh plugin --profile web add @furongjun1999/dsh-memory
```

**Linux / macOS 用户**：本版起解释器默认值**平台感知**（`python3`），首装不再需要手工改配置；仍可用 `MDCG_PYTHON` 指定自有解释器。

> 详情见 [README](https://github.com/FuRongJun-1999/dsh-memory) · 发布件口径见 [发布件回溯说明](../发布件回溯说明_v0.1.md)
