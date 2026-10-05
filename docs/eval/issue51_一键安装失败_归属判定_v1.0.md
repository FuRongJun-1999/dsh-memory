# issue #51 一键安装失败 · 归属判定（v1.0）

日期：2026-10-03 ｜ 状态：判定成立，**待报告者日志确认其环境侧的具体根因**
结论：**不是插件包体／元数据／DSH 兼容性的问题**。失败发生在 hub→dsh→pnpm→registry 链条的**环境层**（pnpm 可用性／PATH、registry 可达性、TLS 拦截），报告所贴的「[exit 1]」不含根因。

---

## 一、问题陈述

- 来源：dsh-plugin-hub（第三方插件市场）**安装失败自动报告**，自动提交至本仓库（作者 Weizuo-84，2026-10-02）。
- 命令：`dsh plugin --profile web add @furongjun1999/dsh-memory`（另试 `--profile desktop`，同样失败）。
- 环境读数（报告自带）：DSH v0.2.0-rc.2 · Hub v1.4.13 · Node v24.18.1 · **pnpm: unknown** · **npm: unknown** · git 2.55 · win32 x64 (10.0.22000) · Profile `desktop` · DSH Home `~/.dsh`。
- 错误正文：仅两行 `[exit 1]`。报告模板自述「Full log: `~/.dsh/profiles/desktop/hub.log` (paste or attach for the full output)」——**报告者未附日志**。

## 二、一手证据（本判定全部由编排侧亲跑，读数如下）

| # | 实验 | 读数 | 结论指向 |
|---|---|---|---|
| E1 | 干净容器（Debian / Node 24 / pnpm 12.8.1）`pnpm add @furongjun1999/dsh-memory` | 成功，10.6s；`main: lib/index.js` 存在，`lib/`、`utf8_boot.py`、`dsh/cordis.patch.yml` 全在 | 包体装配完整、registry 可正常服务该包 |
| E2 | 用 DSH 0.2.0-rc.2 **自带**的 `evaluatePluginCompatibility` 对本插件 manifest 求解（与报告者同版本） | 返回 `undefined`（＝通过）；4 个 `@deepseek-ai/dsh-*` peer 全部 satisfies | 兼容性预检**不是**拒绝原因 |
| E3 | Windows 本机隔离 DSH_HOME（不碰在役环境）+ DSH 0.2.0-rc.2 + Node 24.18 + pnpm 12.6，跑实际命令 `dsh plugin --profile web add @furongjun1999/dsh-memory --registry http://registry.npmmirror.com` | **RC=0，2.2s 安装成功**；profile `package.json` 登记 `dependencies: {"@furongjun1999/dsh-memory": "^0.7.0"}`、`dsh.profile.bundles` 已含本插件；三个关键入口文件实存 | **Windows 全链可装**（与报告者同 OS 同 DSH 版） |
| E4 | 同 E3 但用默认 https registry（本机存在 TLS 拦截层） | RC=1，`Error: ERR_PNPM_PACKAGE_MANAGER_ADD_RESOLVE_LATEST … Failed to fetch metadata from https://registry.npmjs.org/ … invalid peer certificate: UnknownIssuer` | 同形态失败在环境层的完整复现：**pnpm 网络层（rustls）不读系统证书库** ⇒ 拦截层下必然失败；与包无关 |
| E5 | 读 hub 源码（`task-queue.ts:566`） | `pushLine(task, '[exit ${result.exitCode ?? "?"}]')` —— `[exit N]` 是 hub 的**任务尾行标记**；pnpm/dsh 的完整输出原生透传在其上方 | 报告所贴「[exit 1]」是尾行，不含根因 |

## 三、链条拆解（hub → dsh → pnpm → registry）

1. hub 每个安装任务 spawn 一次 `dsh plugin --profile <profile> add <target>` 子进程（`src/server/services/install/task-queue.ts`）；失败时自动生成报告（即本 issue）。
2. `dsh plugin` 的本质＝**在 profile 目录里把参数转发给 pnpm**（DSH CLI 自述）；**DSH 不自带 pnpm**，由安装侧／PATH 提供（DSH 文档：`pnpm was not found; install pnpm and make it available on PATH`，对应 exit 127 专有提示）。
3. DSH 对安装失败有分类表（`LOG_KINDS`：build-blocked / not-found / no-matching-version / disk-full / permission / integrity / network …），完整 pnpm 输出落 `<profile>/.plugin-manager/logs/operation-*/pnpm.log`。
4. hub 报告模板自己指明全日志位置：`<DSH_HOME>/profiles/desktop/hub.log`。
5. 报告者形态为 `[exit 1]`（而非 127 提示）⇒ pnpm 被找到并执行后失败（或其 PATH 层面 Windows shell 返回 1）；**其 `pnpm -v`、`npm -v` 均探测为 unknown**，指向 PATH／工具可用性面。

## 四、归属判定（三段式）

- **本插件包（我们）＝不成立**：包体装配、入口文件、bundle 元数据（`dsh.bundle.patch`）、peer 声明、官方兼容预检——E1/E2/E3 四项独立实证全部通过；profile 安装登记成功。
- **报告者环境＝最可能面**：pnpm 可用性／PATH（两个版本探测均 unknown）、registry 可达性、TLS／代理拦截。**需日志定**；E4 证明该链条在环境层会以完全相同形态失败（同 OS、同 DSH 版本）。
- **hub（第三方）＝非缺陷、但 UX 可改进**：自动报告只收集 `[exit 1]` 尾行，并将 Cause 预填为「plugin-side install failure」——**在插件侧无证据时已把归因指向插件**；建议其自动报告附 `hub.log` 尾部若干行。

## 五、给报告者的自查清单（回帖候稿，外发待批准）

1. **贴日志**（决定性）：`%USERPROFILE%\.dsh\profiles\desktop\hub.log` 中 `[exit 1]` 附近若干行；或 `profiles\desktop\.plugin-manager\logs\operation-*\pnpm.log` 全文。
2. **环境读数**：`node -v`、`pnpm -v`、`npm -v`、`npm config get registry`、是否设置 `HTTP_PROXY`/`HTTPS_PROXY`、是否有公司网络／杀软的 TLS 拦截。
3. **绕过测试**（我们实测有效）：`dsh plugin --profile web add @furongjun1999/dsh-memory --registry http://registry.npmmirror.com`。
4. **前置检查**：确保 pnpm 在 PATH（`corepack enable pnpm` 或 `npm i -g pnpm`）后重启 DSH 再试。
5. 我方对照证据（透明给出）：E1–E3 三条读数可以公开引用。

## 六、未决与边界

1. 报告者日志未取得前，其具体根因（网络／TLS／pnpm 版本／PATH）不能定——本判定**只证「不是包的问题」**，不断言其必为某一具体环境因素。
2. 未在报告者机器上做过任何远程操作；全部读数来自本机与容器。
3. hub 侧建议（第四条第三点）属第三方项目，仅作建议，不代其决定。

## 七、留池（若后续需要）

- README 补一条「插件安装失败自查」FAQ（pnpm 日志位置 + 镜像 registry 解法 + pnpm 前置要求）。
- 若同类报告再次出现，考虑把上述 FAQ 前移进 README 的 DSH 安装段。

*不适用条件：判定范围不含对报告者主机的远程取证。*
