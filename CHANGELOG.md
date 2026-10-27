# 变更日志（CHANGELOG）

本文件自 **0.9.15** 起维护。更早版本见 git tag（`v0.9.6` … `v0.9.14`）与 GitHub Releases。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

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
- `package.json` 的 `files` 白名单加入 `ui`，**随 npm 包分发**安装器与 payload。

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
