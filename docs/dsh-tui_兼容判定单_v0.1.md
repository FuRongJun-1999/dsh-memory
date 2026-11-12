# 灵枢 × dsh-TUI 兼容判定单 v0.1

> **状态**：第一次尝试已落地——「装得上 + 纪律注入」在真机跑通；「工具面可见性」待实测。
> **取证时间**：2026-10-27 ｜ **环境**：Windows · Node 24.18.0 · pnpm 12.6.0 · DSH `0.2.1-rc.2`（`<DSH_HOME>\dsh-0.2.1-rc.2`）· dsh-TUI `0.17.0`（npm）· 灵枢 `@furongjun1999/dsh-memory` `0.9.14`
> **上游**：https://github.com/ccch1mneyyy/dsh-TUI （外部项目，本次**未改一行**，只读参照）

## 一、结论速览

| # | 接缝 | 上游事实 | 灵枢侧判定 | 落地状态 |
|---|---|---|---|---|
| 1 | **装配层**：profile 组合 | TUI 是独立 profile（`dsh --profile dsh-tui`），层序 = dsh-base → 已装 bundle → TUI 包内 `cordis.patch.yml` → 用户补丁（最后应用） | 灵枢是标准 cordis 插件（`export const name` / `inject=['tools']`），装成 bundle 即自动挂行 | ✅ 已装、已挂行 |
| 2 | **纪律注入点冲突** | TUI 包内 `cordis.patch.yml` 用 `system-prompt.config.personaPrefix`（`DSH_TUI_PERSONA` 兜底）占同一行；用户补丁对 config 是**整块替换** | 灵枢纪律也注入 `system-prompt.personaPrefix` | ✅ 已合成（代价：该 profile 下 `DSH_TUI_PERSONA` 失效） |
| 3 | **工具面** | TUI 把 dsh-base 的 host 工具行大量 `disabled: true`，改由 agent-preset 接管（`dsh-tui-agent-presets` 行），避免宿主层工具泄漏 | 灵枢 `cg`/`stg` 是**插件注册**进 `ctx.tools` 的工具，不经 preset 声明 | ⚠️ **未实测**：preset 是否把插件工具挡在模型面外 |
| 4 | **数据/归因** | TUI 会话落 `~/.dsh/sessions`（JSONL，与 dsh web 同一后端，TUI patch 原文明写） | 灵枢 `MDCG_DSH_SESSIONS_ROOT` + `MDCG_ROOT` 指向同一根即共享记忆与会话归因 | ✅ 配置已对齐（`MDCG_HARNESS=dsh-tui` 区分归因） |
| 5 | **插件准入（生态）** | `tui-profile/` 是 TUI 自有准入体系（`dsh-plugin.json`、权限声明、`tui.dsh/v1alpha1` 贡献族、conformance） | 灵枢当前无 `dsh-plugin.json`、无权限声明 | ❌ 未做（属路径 B，非安装前提） |

**关键口径**（上游原文）：`tui-profile/docs/plugin-admission-and-development.md`「**准入与安装都不要求 claim**」——路径 A（装起来用）不需要过准入；准入是「进市场/生态收录」的前置。

## 二、取证

### 2.1 灵枢侧（本仓）

- 插件入口 `src/index.ts`：`export const name='dsh-memory'`、`export const inject=['tools']`、`export const Config`（schemastery）。
- 工具面 `src/tools.ts`：从 `md_cg.mcp_server` 拉 `tools/list` 再 `defineTool` 注册；`CORE_TOOLS = ['cg','stg']`（`tools: core`），`tools: all` 含 `mdcg_*` 全家。
- 提示词接缝 `src/init.ts:156`：已挂 `ctx.on('system-prompt/assemble', …)`（自动召回 / 近期对话块）——**纪律本体不在这里注入**，一直走 profile 补丁的 `personaPrefix`。
- 数据根：`.dsh-memory`（家目录级状态根）+ `MDCG_ROOT` 认知图根；本机分别落 `~/.dsh\.dsh-memory` 与 `<WORKSPACE>/AEIS/data/mdcg`。

### 2.2 dsh-TUI 侧（外部只读取证）

- `docs/configuration.md`「Profile 与补丁层」：用户配置 = `DSH_HOME/profiles/dsh-tui/cordis.patch.yml`；四层叠加顺序如上；`config` 整块替换。
- 包内 `cordis.patch.yml`：`system-prompt` 行返回 `{personaPrefix: process.env.DSH_TUI_PERSONA ?? 'You are a coding agent.'}`；`tool-bash`/`tool-fs`/`tool-pwsh`/… 一律 `disabled: true` 交 agent-preset；`sandbox-policy` 在 win32 取 `danger-full-access`、`approval.policy='never'`。
- `tui-profile/`：`PLUGIN-ADMISSION-CHECKLIST.md`（指向 `docs/plugin-admission-and-development.md`，61KB）、`registry/registry-0.15.json`（profileHash 钉 + 私有坐标）、`registry/permissions-0.1.json`、`protocols/tui-contributions.js`、`conformance/`。
- `README_ZH.md`「插件生态」：`/plugin install <包名|路径|git URL>`；后端插件按**包根 `dsh-plugin.json`**校验准入。

## 三、已落地的适配件（可复现）

产物（本仓）：

- `docs/dsh-tui/build_patch.py` —— 生成器（纯 stdlib，显式 UTF-8）。纪律正文**只搬运**：从 `<DSH_HOME>/profiles/web/cordis.patch.yml` 的受管块取，不改写纪律本体。
- `docs/dsh-tui/cordis.patch.yml` —— 仓内产物（**凭据一律 `MDCG_TOKEN: !!js process.env.MDCG_TOKEN`**，符合纪律第 9 条）。
- `docs/dsh-tui/README.md` —— 接线步骤、验证判据、回退。

生成命令（仓根）：

```powershell
python docs/dsh-tui/build_patch.py --dry-run   # 先看字节数
python docs/dsh-tui/build_patch.py             # 落盘：live + 仓内产物
```

本例 live 目标 = `<DSH_HOME>\profiles\dsh-tui\cordis.patch.yml`（`DSH_HOME` 解析：env → `~/.dsh`）。

## 四、实测证据（本机）

1. **profile 建立**：`dsh plugin --profile dsh-tui add @deepseek-harness-tui/dsh-tui` → `Done in 30.5s`；`dsh plugin --profile dsh-tui add link:<WORKSPACE>/dsh-memory-main` → 依赖与 `dsh.profile.bundles` 双落位（含 `@furongjun1999/dsh-memory`）。
2. **装配树**：`dsh --profile dsh-tui --dump-config` 退出码 **0**，783 行；其中
   - `- id: furongjun1999-dsh-memory`（插件行存在，config 已生效）
   - `MDCG_ROOT: <WORKSPACE>/AEIS/data/mdcg`、`MDCG_HARNESS: dsh-tui`
   - personaPrefix 内 `【本端补充：dsh-tui（2026-10-27）】` 落位
3. **真启动**：`dsh --profile dsh-tui`（后台 20s）→ 灵枢桥日志逐条出现：
   `[lingshu-bridge] [mdcg-mcp] 路径：记忆真源 root=<WORKSPACE>/AEIS/data/mdcg …`、
   `写入策略：来源=env path=…/data/policy.json（forbidden=13 required=6）`、
   `外部验证器: loaded=['md_cg.condaccept']`；
   `md_cg.mcp_server` 子进程真实存在（pid 21972）；
   **未新增** `~/.dsh/logs/dsh-memory-apply-error.log` 记录（大小/时间停在 10-21）。
4. **未取证**：TUI 里模型面能否看到 `cg`/`stg`（见下）。

## 五、未验证 / 风险（诚实边界）

1. **preset 工具面**（最高优先级未决）：TUI 把 host 工具行整体 disable 交给 preset；插件注册的工具是否同样被 preset 收窄，**只能用 TUI 内的真实调用证伪/证实**，静态读码不足以定论。
2. **版本线错配**：TUI `0.17.0` 主适配 **DSH 0.2.1-rc.3**（README_ZH「主适配目标」），本机 `0.2.1-rc.2` 走兼容路径；本判定单的适用边界据此写明。
3. **`DSH_TUI_PERSONA` 失效**：用户补丁整块替换 `system-prompt.config`，该 profile 下环境变量不再生效。若要保留，需改成 `!!js` 表达式内联拼接（未做）。
4. **纪律渲染未进矩阵**：TUI 纪律正文由生成器搬运 + 尾部追加「本端补充」段，**尚未**成为 `docs/discipline/harnesses.yaml` 的 target，因此 `verify_discipline.py` 暂时不守这段漂移。
5. **未碰上游**：所有适配落在本仓 + 本机 profile；dsh-TUI 仓零改动。

## 六、下一步（按优先级）

1. **工具面实测**：在该 profile 里启动 TUI，让模型调 `cg(op="info")`；若不可见 → 兜底 (a) 用户补丁补 preset 行；(b) 把 `cg`/`stg` 包成 preset 认的声明式工具行（本机缺 `@deepseek-ai/dsh-agent-presets` 包，属待查）。
2. **纪律进矩阵**：`harnesses.yaml` 加 `dsh-tui` target（`transport: config-key`、`entry_id: system-prompt`、`marker: lingshu:discipline`、独立 preamble），`verify_discipline.py` 同步；并给 `expand()` 补 `DSH_HOME` 环境变量展开（当前只认 `~` 与仓内相对路径）。
3. **纪律注入与 profile 解耦**（结构优化）：把纪律段挪进插件 `system-prompt/assemble` 钩子，则 web / dsh-tui / headless 一次到位；代价是纪律与插件版本绑定，需先裁定。
4. **路径 B（准入）**：`dsh-plugin.json` + 权限声明 + `tui.dsh/v1alpha1` 贡献族 + conformance；TUI 侧面板/命令贡献（记忆侧栏、`/记忆` 命令）在这一步做。

## 七、不适用条件与回退

- **不适用**：DSH < 0.2.0 或 dsh-TUI < 0.15（未取证，层序与行 id 可能不同）；非 Windows 上 `sandbox-policy` 走 `workspace-write`，与本文 `danger-full-access` 判据无关。
- **回退**（可逆）：删 `<DSH_HOME>/profiles/dsh-tui/` 即整 profile 消失；只撤灵枢 = 把该 profile 的 `cordis.patch.yml` 恢复成 `[]`（TUI 自带 persona 立即复原）。
- **验证方式**：`--dump-config` + 真启动日志（第四节）；两处任一缺失即「未验证」，不得当兼容成立。
