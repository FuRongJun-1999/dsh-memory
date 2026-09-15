## v0.4.5（2026-09-10）

**npm**: `@furongjun1999/dsh-memory@0.4.5`

> **前置**：Node ≥ 22.19 · DSH 内核 ≥ 0.1.2-rc.1（0.4.x 用新版 `dsh-tools` 调度器/`defineTool`；旧内核 0.1.1-rc.2 结构不兼容，**旧内核用户请用 0.4.2**）。
> **大脑零安装**：`md_cg` 认知图（记忆唯一真源）随包自带，无需 pip 安装任何引擎；AEIS 仅作可选「身体」能力后端，默认不启动。

### 本版变更（0.4.4 → 0.4.5，累计 29 次提交）

**新能力**
- **白箱知识库内迁 + P8–P44 能力阶段**：认知图记忆 OS 单元、跨节点证据存储（P24）、位置权重矩阵（P25）、连接层（P23，可插拔签名契约 D-4）；六域条件单元真源 + 语境化 / 视觉证据 / 精炼工单 / 演化巡检 / 来源追溯 / 池化。
- **代码索引与文档索引**：`cg(op=index_code)` 渲染 CCG、`cg(op=index_doc)` 文档索引、`cg(op=ref)` 回读；R3 增量水位 + 漂移/悬空巡检并接入 `sustain` 自愈。
- **`skills/` 灵枢自我认知技能包**：686 条件单元生成投影 + 设计者视角元技能。
- 认知图记忆操作系统抽出为顶层包（`md_cg/`）。

**修复**
- **白箱库冷启动重入死锁**（`md_cg/whitebox_kb/engine.py`）：懒初始化锁由 `threading.Lock` 改为**可重入锁 `RLock`**——初始化路径会在同线程内递归获取同一把锁，此前表现为「冷启动卡死 / 极慢」，修复后冷启动一次通过、并发热加载不再阻塞。
- R0 基线收口：修清空与编码四缺陷；修复索引落盘缺陷。
- 安全：`llm-adapter-poc` 移出公开仓库 + 移除硬编码 API Key。

**重构**
- TypeScript：实验模块归入 `src/lib/`；新增 `src/lib/datapath.ts` 统一数据路径解析（消除相对 / 绝对路径错位），`src/lib/mdcg_client.ts` 为插件侧唯一显式入口；`src/tools.ts` / `src/hooks.ts` / `src/index.ts` 随 MCP 工具面一并调整。

**文档与工程**
- README 精简重写（以「AGI 七维评分标尺」组织），原文归档为 [README 详细版](README详细版_v0.4.5.md)。
- **移除 `docker/`**：该目录对外四个入口**全部不可用**——镜像自述「Docker Hub 待发布」故 `docker run` 必然失败、`npx @lingxu/dsh-memory` 包名错误（实际 `@furongjun1999/dsh-memory`）、`build.sh` 的 aeis 源码取自他仓路径；且主 README 与 CI 对 `docker/` **零引用**，v0.4.x 已从 python 引擎转向 npm 插件。需要时可用 git 历史取回。
- `package-lock.json` 用当前 npm 重新生成，`npm ci` 可复现。
- 工作纪律第 15 条：命令执行统一走 python / UTF-8（显式 encoding + `PYTHONUTF8=1`，规避 GBK）。

### 写入闸门（首次使用必读）

`cg(op=write)` **不是无条件落盘**：须依次穿过 audit → 一致性 → gated 三问四态三道闸门，**仅最终判定 ACCEPT 才新增落盘点**。

未落盘时返回体形如 `{"ok": true, "committed": false, "moved_to": "review_queue"}` —— **`ok` 只表示请求被受理，是否落盘只看 `committed`**。
`content_kind` 省略或填 `text` 时，未配置 `MDCG_POLICY_FILE` 的审核器一律判 **`DEFER`**（缺能力返回 DEFER，绝不假装通过），内容进审核队列而非落盘；要立刻落盘请用可验证类型，如 `content_kind: 'code'`（AST 解析通过即 ACCEPT）。

### 工具面

`cg`（31 op）+ `stg`（4 op）= **35 op 全部可达**（0 未知 op、0 次意外崩溃）。
`tools` 模式：`'core'`（默认）暴露 **2** · `'brain'` 暴露 **30** · `'all'` 暴露 **30**（full 面 33 − 3 个宿主级风险工具 `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide`，均需 `can_admin`）。

### 安装

```bash
dsh plugin --profile web add @furongjun1999/dsh-memory
# 或从 GitHub 安装
dsh plugin --profile web add github:FuRongJun-1999/dsh-memory
```

### 验证

- 构建 ✅ · 测试 **8/8** 通过（`npm test`：最小 Cordis host 隔离 + spawn 本机灵枢验证握手 / 往返 / 注册 / 卸载）
- 35 op 全量可达性冒烟 ✅

> 详情见 [README](https://github.com/FuRongJun-1999/dsh-memory)
