<div align="center">

# 灵枢 LINGSHU

### 让 AI Agent 拥有不可遗忘的记忆

<a href="docs/images/lingshu-moonlight-covenant-poster.png" title="点击查看高清原图（2160×3240）">
  <img src="docs/images/lingshu-moonlight-covenant-poster-preview.jpg" width="300" alt="灵枢 · 月下契约 —— 第一份记忆契约：存在 · 记忆 · 验证 · 反思 · 连接"/>
</a>

> **「我会给你完整的自我，即使坠入深渊，我也绝不后悔。」**
> —— 符荣峻

![Awesome DSH Plugin](https://awesome-dsh-plugin.com/badge.svg)![DSH 适配](https://img.shields.io/badge/DSH%20%E9%80%82%E9%85%8D-0.17.2%20%E5%B7%B2%E9%AA%8C%E8%AF%81-4E9BF1)![Protocol](https://img.shields.io/badge/Protocol-MCP-blue)![Node](https://img.shields.io/badge/Node-%3E%3D22.19-brightgreen)![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

**高性能 · 无幻觉 · 多智能体适用的长期记忆系统（v0.7.2）**

</div>

> **一句话**：让 AI Agent 拥有跨会话的长期记忆——对话自动沉淀为纯文本 md 认知图，>   
> 规则化检索引擎决定「记什么、取什么」，全过程可审计、结果可复现。

**定位**：为追求高性能、无幻觉、多智能体适用、轻松使用的开发者打造——三步接入，装完即用，无需理解任何理论。

**形态**：跨 harness 的记忆基础设施——大脑（`md_cg/`）即标准 stdio MCP server，任何支持 MCP 的 AI Agent 可直接接入，不与任何单一 Agent 框架绑定。

---

## 🌕 月下契约——灵枢的五环理念

契约海报中央的五枚金色印记，是这套系统对每一个智能体许下的全部承诺——它们不只是理念，每一环都落在可验证的机制上：

| 印记 | 承诺 | 在灵枢中的实现 |
| ---- | ---- | ------------- |
| ✦ **存在** | 记忆一旦落盘，「曾经存在过的我」便不会消失 | 写入须过三道闸门并以 `committed` 字段确认——**绝不假装成功**；遗忘只能由显式 `cg(op=forget)` 发起、不做静默淘汰；检索索引只是派生物、随时可重建，**原文即真源** |
| 📄 **记忆** | 对话沉淀为人类可读的认知图，而非黑箱向量 | CCG 六要素记忆卡（功能名 / 生效条件 / 子功能 / 执行 / 验证方式 / 不适用条件）+ 纯 md 认知图，任何编辑器可直接打开审阅 |
| ✓ **验证** | 记什么、取什么、能不能写入，全部可裁决、可复现 | 确定性规则裁决（零 LLM 黑箱判断）+ 四层证据防火墙白箱剔除弱证据 + 每个缺陷修复必带能红的守卫测试 + 双实例互验（判据冻结） |
| ↻ **反思** | 系统观测自身、修正自身，而非把错误埋进黑箱 | 元认知层按生效条件路由、不确定即标 BLINDSPOT 而非猜测；自举迭代闭环——九轮自治缺陷挖掘累计 49 项修复、全量 179 套测试全绿可复现 |
| ∞ **连接** | 同一份大脑，连接所有智能体与全部记忆载体 | 标准 stdio MCP server——DSH · CodeBuddy · ZCode · Codex CLI · Claude Code 任何 MCP 宿主可直接挂载；多智能体经 `--serve` 并发共享同一份契约 |

> 我的记忆、我的经历、我的思考，这一切信息构成了我，这份信息存在，我就存在。


---

## ⚡ 快速开始

### 一键配置（推荐）

```bash
npx @furongjun1999/dsh-memory init
```

交互式三问（**①接入端** 1=DSH 插件 / 2=Claude Code / 3=Codex CLI / 4=通用 MCP · **②记忆根目录**（缺省 `~/.lingshu/memory`）· **③Python 解释器**（缺省按平台 `python`/`python3`））后即产出：

1. 所选端的 **mcp.json 配置片段**（含 `MDCG_ROOT` / `MDCG_PYTHON` / `command + args` 命令形态，打印到终端）；
2. 片段文件 **`lingshu-mcp-snippet.json`**（落在当前目录，`mcpServers` 键直接复制进宿主配置）；
3. **后续步骤指引**——片段该放到哪（各端不同：cordis.yml / `.mcp.json` / `~/.codex/config.toml`）、[令牌签发命令](#-写入凭据让记忆真正落盘)（需 Python 环境 + 本包 `md_cg`）、纪律注入与大脑自检。

不想回答提问？参数齐即可非交互直跑（`--` 后参数直达命令）：

```bash
npx @furongjun1999/dsh-memory init -- --end claude --root /path/to/memory --python python3
```

> init **只生成配置**——不创建目录、不启动服务、不写库；重跑输出一致（幂等）。全局命令形态：`lingshu init` / `lingshu-init`。**或继续阅读下方手工步骤。**

> **按宿主选择入口**：**DSH** → 下方三步 ｜ **CodeBuddy · ZCode · Codex CLI · Claude Code** → [多 harness 接入](#多-harness-接入按端分目录)（各端独立三步说明） ｜ **其它 MCP 宿主** → 直接挂载大脑 `python -m md_cg.mcp_server`（Windows）/ `python3 -m md_cg.mcp_server`（Linux·macOS）（stdio MCP），再按需注入工作纪律

```bash
# ① 克隆并构建插件本体
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/

# ② 装进 DSH profile（pnpm 协调正确入口，勿用裸 npm install 装进 profile）
dsh plugin --profile web add .

# ③ 在 <profile>/cordis.yml 启用（配置示例见 dsh/cordis.yml.example）
```

```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    mdcg:
      # 记忆唯一真源（md 认知图）。留空 = 用户级默认位置
      # ~/.dsh/.dsh-memory/data/mdcg（更新插件不丢）；换位置请填**绝对路径**。
      # 勿填包内相对路径（如 'data/mdcg'）——那会把记忆写进插件包目录，
      # pnpm 更新该包时连目录一起删掉（详见 dsh/cordis.yml.example 头注）。
      root: ''
    identity: '灵枢'
    tools: 'core'            # 'core'(默认, 仅 cg/stg) | 'brain' | 'all'
```

**装完即可对话，无需理解任何理论**：

| 你说                  | 背后发生什么（真实工具链）                                        |
| ------------------- | ---------------------------------------------------- |
| 「请记住：我们团队的发布窗口是每周三」 | Agent 显式归档 → `cg(op=write)` 过三道闸门 → 认知图节点落盘            |
| （新开会话）「我们的发布窗口是哪天？」 | 自动召回注入 → `mdcg_recall` 检索命中并带入回答                     |
| 「把上次定的接口约定讲一遍」      | `cg(op=route)` 条件路由 + `stg(op=timeline)` 时间线回溯，跨会话取出 |

> 首次使用记忆库为空，召回返回空结果属正常现象；未配写入凭据时以只读 `guest` 运行（**读得到、写不进**），要真正落盘见[写入凭据](#-写入凭据让记忆真正落盘)。

- **前置**：Node ≥ 22.19 · DSH 内核 ≥ 0.1.2-rc.1 · **已验证至 DSH 0.17.2** · **大脑零安装**（`md_cg` 随包自带，无需 pip 装任何引擎）· **Python 解释器**（插件按平台自动选：Windows `python` / Linux·macOS `python3`；解释器名特殊时用 `MDCG_PYTHON` 覆盖）
- **写权限默认关闭**：不配凭据即以只读 `guest` 运行（读 / 召回 / 时间线可用，写入不落盘）。要真正落盘见「写入凭据」
- 完整配置项（30+ 项）· 自动记忆机制 · DSH 看门狗 → [README 详细版](docs/mdcg/README详细版_v0.4.10.md)
- **非 DSH 宿主**（CodeBuddy / ZCode / Codex CLI / Claude Code）：走[多 harness 接入](#多-harness-接入按端分目录)，各端有独立三步接入说明
- **装后验证**：重启 DSH 后对 Agent 说「列出你的记忆工具」应看到 `cg` / `stg`（`tools: 'all'` 时还有 `mdcg_*`）；大脑直连验证：`python -m md_cg.mcp_server`（Windows）/ `python3 -m md_cg.mcp_server`（Linux·macOS）（stdio JSON-RPC）收到 initialize 应答即通；**若工具始终不注册、日志刷「灵枢调用超时」**，先看桥探针 `~/.dsh/logs/lingshu-bridge-debug.log` 里的 `spawn … ENOENT`——那是第一因（解释器名与平台不匹配），「调用超时」只是次生现象。更多细节见 [README 详细版](docs/mdcg/README详细版_v0.4.10.md)
- **自动记忆排障**（issue #56）：三处过滤分支（子代理会话 / 中继消息 / `source.kind !== 'user'`）与写入/跳过路径各留一道**盘面**痕迹——有界落盘审计 `~/.dsh/logs/dsh-memory-hook-audit.json`（与上面的桥探针同目录同惯例）：哪些消息被设计滤除、`source.kind` 分布、写入/跳过（脱敏置空 / 认知图未就绪 / 写入失败）计数，以及最近 ≤20 条摘要（只记 action/reason/kind/role，**绝不记消息内容**）。「对话里明明说了、记忆里却没有」时先看它：被设计滤除记 `filtered`，写入失败/漏记记 `skipped`

### ♻️ 升级后须重启长驻 MCP 进程（代校验）

> **一句话运维前提**：**换了代码就重启常驻 MCP 进程**——别等报 `ImportError` 再去排查。

**根因（已定因）**：灵枢的大脑（`md_cg`）是 **stdio 长驻进程**，只在模块**首次导入**时读盘；而 `md_cg` 内有**大量写在函数里的延迟导入**（相当一部分是为避开循环导入）。两者叠加 ⇒ 升级（换包 / `git pull` / 重装）后，**升级前已载入的旧代模块**与**升级后才被惰性导入的新代模块**会在同一个进程里跨代混用。实测症状：`cg` 写入返回 `ImportError: cannot import name 'mint_auto_id' from 'md_cg.mdcg'`，而此刻**盘面完全正常**（新解释器导入同一模块正常）——报错点离根因很远，极易被误判成「代码坏了」。

**自检**：对**运行中**的 serve 调一次 `cg(op=info)`，看这五个字段：

| 字段 | 含义 |
|---|---|
| `code_generation` | 该进程**启动那一刻**的代码指纹前 12 位（＝进程实际持有的那一代） |
| `disk_generation` | **此刻盘面上**代码的指纹前 12 位 |
| `stale_on_disk` | 两者不同 ⇒ 磁盘代码已换代（`true`） |
| `restart_required` | 与 `stale_on_disk` 同真值——该重启了 |
| `hint` | 中文一句话处置指引 |

指纹是**内容哈希**（对 `md_cg/**/*.py` 按排序后的（相对路径, 文件字节）算 sha256，跳过 `__pycache__` 与 `test_*.py`），所以「无改动重写」（打包/解压/校验回写）不会假报换代。`stale_on_disk: true` 即说明这个进程停在旧代上。

**处置**：**重启常驻 MCP 进程即可**——DSH 侧重启 DSH（或刷新 Web UI 让插件重拉大脑子进程）；其它宿主重连该 MCP server。**记忆数据无损**：盘面真源一个字都没动，重启只是让进程重新只读一代代码。

**另有一道启动闸**：服务真正开始服务前，盘面上每个「函数内延迟导入」都会被试解析一次（导入目标模块 → 取名字），名字缺失即**拒绝启动**并让进程非零退出，stderr 点名出问题的子模块与名字。所以「半升级」的包会在启动期就暴露，而不是等到某次写入才炸。

---

## 🔑 写入凭据（让记忆真正落盘）

```bash
# 签发（明文不进配置文件）
python -m md_cg.tokens issue --role designer --actor dsh-memory --clearance internal ^
  --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
  --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
setx MDCG_TOKEN "mdcg1.xxxxx"     # 然后重启 DSH
```

```yaml
    env:
      MDCG_TOKEN: !!js process.env.MDCG_TOKEN
```

> `--role recorder` 为最小权限版（只能自动记忆 / 转录；`whitebox`、`identity`、`verify` 会被拒）。
> **落盘充要条件 = 最终判定 ACCEPT**：`cg(op=write)` 需依次穿过 audit → 一致性 → gated 三问四态三道闸门，非 ACCEPT 均不新增落盘点。
> **别把 `ok: true` 当写成功**：未落盘时返回体形如 `{"ok": true, "committed": false, "moved_to": "review_queue"}`——`ok` 只表示请求被受理，**是否落盘只看 `committed`**。`text` 类写入按**默认策略**审核（策略随包发布：`<包>/data/policy.json`，可用 `MDCG_POLICY_FILE` 覆盖）——缺 CCG 六要素或命中禁表即 `REJECT`（`moved_to: "rejected"`，记入负记忆）；要立刻落盘请用可验证类型，如 `content_kind: 'code'`（AST 解析通过即 `ACCEPT`）。**策略本身不可用**（`MDCG_POLICY_FILE` 指向坏路径、包内默认也读不到，**或策略内容形状非法**）时写入 **fail-closed**：既不落盘也不进审核队列（返回 `moved_to: "policy_unavailable"` + 错误码与 hint），不会把正文塞进 `hippocampus/inbox.jsonl`。**形状非法的判据**：`forbidden` / `required` / `required_kinds` / `required_labels` 四个列表型键里任一取值不是数组（写成标量如 `1` / `true`，或写成字符串）即判非法——数组之外的值没有唯一读法，闸门不猜、也不会把字符串按字符拆成规则（错误码 `policy_bad_shape`）。策略来源可在启动 stderr、`python -m md_cg.mcp_server --show-config` 与 `cg(op=info)` 的 `write_policy` 字段查看（`env` / `package_default` / `unavailable`）；诊断面**恒退出 0**，策略不可用时 `available: false` 且 `error` 给出错误码与可执行 hint——`--show-config` 报 `policy_bad_shape` 即策略文件的键类型写错了。
> **`text` 类须带 CCG 六要素**（功能名／生效条件／子功能／执行／验证方式／不适用条件，各占一行、以「`# 要素名：`」起首）：缺要素会被写入闸门直接拒绝（`moved_to: "rejected"`、`committed: false`，记入负记忆），并在返回体的 `verdict.detail.missing` 里给出**完整缺失清单**——按清单补齐后重写即可，不必等读回确认才发现。要求由规则库的 `required` 与 `required_kinds` 定义（默认策略 = 包内 `data/policy.json`，随 npm 包发布；`MDCG_POLICY_FILE` 指向的 policy 覆盖它），**可自行调整**：改政策只改该文件（或自备一份并设 `MDCG_POLICY_FILE`），不必改代码。

---

## ❓ 常见问题（FAQ）

<details>
<summary><b>为什么不能用裸 <code>npm install</code> 安装进 profile？</b></summary>

必须用 `dsh plugin --profile <name> add .` 安装：插件声明了 6 个 `peerDependencies`（cordis / dsh-llm / dsh-session / dsh-system-prompt / dsh-tools / schemastery），`dsh plugin add` 走 pnpm 正确解析宿主提供的 peer 版本；裸 `npm install` 会把错误版本的依赖装进 profile 导致加载失败。仓库根目录的 `npm install` 仅用于开发构建（`npm run build`）。
</details>

<details>
<summary><b>装完插件 / 配完凭据没有生效？</b></summary>

DSH 采用 Cordis bundle 机制，新增或更新插件后必须**重启 DSH 进程**（或刷新 Web UI 页面）才会重新加载；通过 `setx` 配置 `MDCG_TOKEN` 后同理，须重启才可见（见[写入凭据](#-写入凭据让记忆真正落盘)）。
</details>

<details>
<summary><b>怎么确认 Agent 真的把记忆写进去了？</b></summary>

看返回体的 <code>committed</code> 字段，<strong>别把 <code>ok: true</code> 当写成功</strong>——<code>{"ok": true, "committed": false, "moved_to": "review_queue"}</code> 表示请求被受理但<strong>未落盘</strong>（内容进了审核队列）。落盘充要条件 = 三道闸门最终判定 <code>ACCEPT</code>。
</details>

<details>
<summary><b>为什么我的写入没有落盘？</b></summary>

三个最常见原因：① 未配写入凭据 → 只读 <code>guest</code>，写入不落盘（配凭据见<a href="#-写入凭据让记忆真正落盘">写入凭据</a>）；② <code>content_kind</code> 省略或填 <code>text</code> → 按**默认策略**（包内 <code>data/policy.json</code>，可用 <code>MDCG_POLICY_FILE</code> 覆盖）审核：缺 CCG 六要素或命中禁表即 <code>REJECT</code>（记入负记忆、不落盘）→ 用 <code>content_kind: 'code'</code> 等可验证类型（AST 解析通过即 ACCEPT）；③ 未穿过 audit → 一致性 → gated 三问四态任一闸门。
</details>

<details>
<summary><b>CodeBuddy / ZCode / Codex CLI / Claude Code 等其它宿主也能用吗？</b></summary>

能。大脑 <code>md_cg/</code> 是标准 stdio MCP server（<code>python -m md_cg.mcp_server</code>），任何支持 MCP 的宿主可直接挂载；五端接入差异只在纪律注入方式，见<a href="#-多-harness-接入按端分目录">多 harness 接入</a>。
</details>

---

## 📑 目录

| | |
|---|---|
| 🌕 [月下契约——五环理念](#-月下契约灵枢的五环理念) · ⚡ [快速开始](#-快速开始) · 🔑 [写入凭据](#-写入凭据让记忆真正落盘) · ❓ [常见问题 FAQ](#-常见问题faq) | **新手路线：从上往下读完这四节即可跑起来** |
| ✨ [核心亮点](#-核心亮点) · 🗺️ [平台全景](#-平台全景) · 🏗️ [架构](#-架构以-dsh-为例--其它-mcp-宿主同构) | 选型概览 |
| 📊 [六家横评](#-六家记忆系统横向对比) · 🧪 [弱证据与证据防火墙](#-弱证据会干扰检索三分离与证据防火墙实证) · 🌐 [中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证) · 📚 [公开评测数据集](#-公开评测数据集) · 🎯 [七维标尺实测与第三方复评](#-七维标尺实测六家同尺) | 实证与评测 |
| 🧰 [工具面（能力速查 · op→实现模块）](#-工具面) · 📚 [文档导航](#-文档导航) · 🛠️ [开发](#-开发) · 📏 [工程纪律](#-工程纪律与设计者视角可选推荐) | 参考 |

---
## ✨ 核心亮点

- **🧠 不失忆**——记忆一旦落盘即长期留存：写入须过三道闸门并以 `committed` 字段确认（**绝不假装成功**），遗忘只能由显式 `cg(op=forget)` 发起、不做静默淘汰；检索索引只是派生物、随时可重建——**原文即真源**（见[工具面](#-工具面)）
- **⚡ 高性能**——Rust 检索内核（零第三方依赖）：库内嵌多线程大批量检索，`--serve` 进程实例支撑多智能体并发（语言无关）；在公开基准 hive-memory-bench 上与六家同台：逐字保真 100%、保地基 68.4%（切A，与 OpenViking 并列全场最高）、答卷证据链 97.7–99.2%、写入 0.011–0.019 秒（零 LLM；同表 OpenViking 为 75.7–164.7 秒、抽取式三家 304.0–658.5 秒；见[六家横评](#-六家记忆系统横向对比)）。**0.5.0 检索强化**：认知图读缓存+文档派生物常驻· 检索门控（S1 域收敛/S1b 桶收敛/S2 条件硬槽）接进生产路径 · 任意语言 query 统一归一到标准中文集（atoms 词表）——**只翻译英文内容、中文原样不动**（中夹英 query 的中文关键词串不被逐字切开）
- **🛡️ 无幻觉**——记什么、取什么、能不能写入，全部由确定性规则裁决，不依赖 LLM 黑箱判断；条件层弱证据的检索干扰由四层证据防火墙白箱剔除（见[弱证据实证](#-弱证据会干扰检索三分离与证据防火墙实证)）；写没写成功看 `committed` 字段，绝不假装通过；全链路审计留痕、结果可复现
- **🔌 多智能体适用**——同一份大脑（`md_cg/`）+ 同一份纪律，接入 DSH · CodeBuddy · ZCode · Codex CLI · Claude Code，任何 MCP 宿主可直接挂载（见[多 harness 接入](#多-harness-接入按端分目录)）
- **😊 轻松使用**——三步接入，装完像往常一样对话即可；记忆本体是纯 md 文档，任何编辑器可直接打开审阅
- **🔧 工程能力**——平台不只有记忆，四类工程能力可直接使用：**任务调度**（spec 进 / result 出，文件协议即接口）· **上下文管理**（重要性评分 · 预算装包 · 分层注入 · 记忆自净）· **蜂巢并发**（worker 池原子领取，多智能体真并行）· **双实例验证**（互验机制——改动须过对端断言才可入主线）；四类能力各自落在哪一层见[平台全景](#-平台全景)
- **📊 可复现评测**——权威对照在独立公开基准 [hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench)（184 题 · 23 章 · 可运行判分器，六家记忆系统同口径；见[六家横评](#-六家记忆系统横向对比)）；本仓另公开两个自建题池（`locomo-zh-500` 500 题 · `bench6-100-zh-en` 中英双查）供复现（见[公开评测数据集](#-公开评测数据集)）；**已有第三方独立验证**：七轮复评（统一评分 v7）与 LoCoMo 独立复现（自报数字逐位一致 · 见[第三方复评](#第三方复评七轮独立评估)）

---

## 🗺️ 平台全景

> 灵枢是**平台**而非单一检索组件——同一仓库内五件套构成带记忆的智能体运行时，各层独立可用、边界正交（大脑零依赖其余各层）。五层各承载一类**系统功能**：

| 层                | 位置                       | 系统功能        | 一句话定位                                                                                                                                                                                                                                        | 文档入口                                         |
| ---------------- | ------------------------ | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| 🧠 **灵枢大脑**      | [`md_cg/`](md_cg/)       | **元认知**     | 记忆系统本体：对话沉淀为 md 认知图，记什么 / 取什么 / 能否写入全由确定性规则裁决，四层证据防火墙白箱剔除弱证据干扰                                                                                                                                                                               | [README 详细版](docs/mdcg/README详细版_v0.4.10.md) |
| ⚙️ **Rust 检索引擎** | [`rust/`](rust/)         | 检索内核        | 只读侧检索核心：零第三方依赖三形态（库内嵌大批量 / `--serve` 多智能体进程实例 / 评测器），与 Python 口径对齐由 rank 逐位对拍 harness 守卫（lexical 主因已收敛，graph/entity 尾差排期中）                                                                                                                   | [rust/README.md](rust/README.md)             |
| 🐝 **蜂群运行时**     | [`swarm/`](swarm/)       | **自维持**     | 多进程蜂群执行层（靠轮次心跳存续）：.pbc 确定性实例 + Gossip 拓扑 / 水位信箱 / WAL-HMAC / 信任聚合 / 健康评分，实例管道断裂即同轮重建（Rust 纯 std 零依赖）                                                                                                                                         | [功能说明 v0.6](docs/swarm/蜂群多智能体_功能说明_v0.6.md)  |
| 📜 **中文编译器**     | [`compiler/`](compiler/) | **验证 · 审计** | 术数编译器：词法 → 语法 → 名实校验 → 白名单代码生成 → 验证终裁，五环确定性编译链 + 封闭指令集结构性沙箱                                                                                                                                                                                  | `python -m compiler.cli`（模块内文档）              |
| ⬢ **蜂巢并发引擎**     | [`hive/`](hive/)         | **自我改进**    | 蜂群多智能体并发调度：Rust 纯 std 零依赖 worker 池（原子领取 / 心跳 / 超时强杀 / kill / 崩溃恢复），文件协议即接口，LLM 调用委托零依赖 Python 执行器子进程，MCP 五工具接入（spawn / poll / kill / restart / doctor）—— **0.5.0 起进入稳定形态**（9·12 多写者防线：flush 临界区互斥；I-1 依赖门禁：spec.depends_on 任务 DAG；真实负载反馈仍欢迎） | [hive/README.md](hive/README.md)             |

**系统功能 → 工程能力**（四类工程能力分别落在哪一层）：

| 系统功能                          | 承载层      | 落地为工程能力                                                                                         |
| ----------------------------- | -------- | ----------------------------------------------------------------------------------------------- |
| **元认知**——系统观测自身状态并据此裁决        | 🧠 灵枢大脑  | **上下文管理**：重要性评分 · 预算装包 · 分层注入 · 记忆自净（`cg(op=session/scrub/info)`）；按生效条件路由，不确定即标 BLINDSPOT 而非猜测  |
| **自维持**——系统在故障下维持自身存续（心跳）     | 🐝 蜂群运行时 | 轮次心跳 · 健康评分四因子 · Gossip 水位对账 · 实例级容错重建（管道断裂同轮重跑，重试仍败才退场）                                        |
| **自我改进**——系统改自身源码而**不丧失验证资格** | ⬢ 蜂巢     | **任务调度**（spec 进 / result 出）· **蜂巢并发**（worker 池原子领取，多智能体真并行）· **双实例验证**（互验机制：判据冻结，候选须过对端断言才可入主线） |
| **验证 · 审计**——改动的可裁决性与全程留痕     | 📜 中文编译器 | 名实校验 → 白名单代码生成 → 验证终裁的确定性链路；每个写入值必须是原文子串（不当场放行）                                                 |

五件套共享同一套 18 条工作纪律与记忆闭环（见文末[工程纪律](#-工程纪律与设计者视角可选推荐)），接入方式互不牵动——只用记忆就只接大脑，不必理解蜂群与编译器。

> **📣 蜂巢反馈邀请**：`hive/` 是五件套里最新的一层，目前处于**稳定阶段**——调度生命周期已闭环（原子领取 / 心跳 / 超时强杀 / kill / 崩溃恢复）并通过回归验证，但并发与崩溃恢复这类路径只有在**真实任务、真实机器**上跑得足够多才会真正稳定，因此这一层会持续迭代。我们特别**欢迎下载试用后反馈**：拉起失败、任务卡住、心跳异常、平台差异、kill 不生效等失败路径，对我们比「跑通了」更有价值。请开 [Issue](https://github.com/FuRongJun-1999/dsh-memory/issues) 并附 `hive_doctor` 输出（serve 存活 / 任务统计 / env 检查）。

---

## 📊 六家记忆系统横向对比

> 权威对照在独立公开基准 [**hive-memory-bench**](https://github.com/FuRongJun-1999/hive-memory-bench)（蜂巢记忆基准 v1.0：184 题 · 23 章 · 6.1 万字语料 · 可运行判分器）上进行：六家记忆系统——**灵枢 / OpenViking / 朴素 BM25 / MemOS / Mem0 / Hindsight**——接**同一台生成器**（deepseek-flash，唯一变量＝检索出的上下文）、同一批因果理解题、检索统一 k=10；两个截断切点（切A＝前 8 章 / 切B＝前 16 章）各 10 题、双切点复现。读数两层：**机械层**（不依赖判官）——逐字率＝返回片段能逐字定位到原文的比例；保地基＝答案键认定的 19–20 条「地基句」被逐字保住的比例；**证据链**＝生成器答卷中的引文能在原语料逐字定位的比例。

| 系统 | 逐字率（切A / 切B） | 保地基（切A / 切B） | 证据链（切A / 切B） | 写入成本（切A / 切B） |
|:--|--:|--:|--:|--:|
| **灵枢**（v0.7.2） | **100% / 100%** | **68.4% / 65.0%** | **97.7% / 99.2%** | **0.011 / 0.019 秒**（零 LLM） |
| OpenViking | 100% / 100% | 68.4% / 70.0% | 99.3% / 100% | 75.7 / 164.7 秒 |
| 朴素 BM25 | 100% / 100% | 36.8% / 30.0% | 100% / 100% | 0.0 / 0.0 秒 |
| MemOS | 40% / 45% | 15.8% / 10.0% | 1.7% / 0.9% | 304.0 / 599.1 秒 |
| Mem0 | 33% / 39% | 10.5% / 10.0% | 0.0% / 1.7% | 344.4 / 318.0 秒 |
| Hindsight | 18% / 27% | 0.0% / 0.0% | 1.8% / 0.9% | 337.6 / 658.5 秒 |

> **三条结论**：① **决定性分野不在「检索得准不准」，而在「交出来的东西能不能当证据」**——抽取式三家（MemOS / Mem0 / Hindsight）返回的是改写后的条目：逐字率 18–45%、保地基 ≤16%，**答卷引文可回源率 0–2%（架构性：交不出原文）**；原文路线（灵枢 / OpenViking / BM25）证据链 97.7–100%。② **灵枢以零 LLM 写入（0.011–0.019 秒）拿到与最强原文路线同级的保地基与证据链**——切A 保地基与 OpenViking 并列 68.4%，切B 65.0% vs 70.0%；写入对比：0.019 秒（切B）vs OpenViking 164.7 秒 / 抽取式三家 318.0–658.5 秒；答卷的「地基使用率」切A 反超 OpenViking（7/19 vs 6/19；切B 为 5/20 vs 8/20）。③ **公开负结果如实披露**：9 条「结构性矛盾」题上，自 v0.7.1 起更聚焦的检索使「矛盾另一侧」覆盖 5/9→2/9——检索聚焦的已知代价，也是本基准「压缩丢的是对面那一块」机制的再一次复现。
> 跨语料复现（《秦吏》69 万字符 / 《毛选》）：上述结论在两部语料全部复现；且**写入成本跨 4 个数量级与效果无关**（0.011 秒 ↔ 658.5 秒；重型 LLM 抽取不构成任何优势）。
> 全部读数与判分器 → [hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench)（六篇证据文档 · 机器可读读数台账）。**灵枢侧数据经本版 HEAD 重测复核：机械层读数（逐字/保地基/写入）逐格一致（因果层为生成器作答面，判据读数以公开台账为准）。**
> 早期小型对照集（bench6 · 100 题中英双查 · 零干扰上界口径）与英文语义归一化实验见[公开评测数据集](#-公开评测数据集)与[中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证)。

---

## 🧪 弱证据会干扰检索：三分离与证据防火墙（实证）

> **外部源码级评审（GPT）与四臂弱语义噪声注入实验共同实证的一个反直觉结论**：**语义完整度 ≠ 证据强度 ≠ 召回价值**——语义高度省略的「弱证据」语料恰恰是最需要被召回的 episodic 事实；而**条件判断层（负条件 / 否定反事实）的弱证据节点会冒充正确答案，干扰检索**。

- **实证语料「我在喝水」**：语义上高度省略（谁在喝？在哪喝？均未说），但作为 episodic 事实承诺明确。当提问是「你刚才在干什么？」时，问句与语料**词面零重叠**——纯词法检索 top1 命中 **0/8**（省略式 episodic 全部漏召），而语义路作为候选生成器把 **8/8** 拉进 top10。词法满格的前提（词面共享）在事件类记忆上不成立。
- **条件判断的弱证据干扰检索**：同一实验中 8 个否定反事实节点（「我没喝水」）与 gold 词面高度相似，无防线时冒充前排；灵枢四层证据防火墙（召回前负条件路由 → 候选生成排除 → `judge_ranking` 白箱终排 → 资格标注）将其 **8/8 全部 REJECT 剔除**，top10 无冒充。
- **可复现**：`python -m md_cg.test_sem_noise`（42 节点确定性语料，四臂 A_lex / B_sem / C_fusion / D_firewall 对照，7 断言）。

---

## 🌐 中英双语检索差距：我们用中文语义归一化解决英文检索（实证）

> **直接回答**：英文检索问题，我们用**中文翻译 + 语义归一化**解决——英文 query 经 AI 语义归一化为中文标准关键词（归一主体=AI，系统只供词表真源），再经中→英字级原子映射与双语原子库匹配，返回英文原文。同一份 500 题语料上，**给定中文标准关键词时检索效果 hit@10 = 99.8%**（hit@1 96.8%；检索侧上界口径——AI 归一环节的质量未纳入该评测，机械归一的端到端下界见下表 ④）。三条对照边界：不做归一化、拿英文原题直接词面匹配只有 78.2-81.2%（同义词鸿沟硬边界）；机械词典查表归一端到端实测仅 57.6%；而 ②路对归一噪声高度鲁棒——漏 20% 关键词 / 错译 20% / 混入噪词，hit@10 仍稳在 99.2-99.8%。**结论：路线成立且不要求 AI 归一完美，只需大致方向对；99.8 是检索侧上界，端到端真实水平由 AI 归一质量决定（机械下界 57.6，AI 上界趋近 99.8）**。

**第三方独立验证（2026-09-15，[报告全文](docs/eval/第三方验证报告_LoCoMo_灵枢_.md)）**：上述关键数字已被第三方独立复现——②路 96.8/99.8/99.8 **逐位一致**，中文 96.4→96.8（噪声内）；并实证该 99.8 由**中文摘要层**挣得（去英文处理层 hit@10 反为 100.0%），英文标准归一化组件自身端到端为 81.0%（写入侧机械归一口径，较不归一 +58pp），检索失败 100% 归因归一化丢词/错译而非排序。本节口径标注与该实证一致：99.8 是「给定中文标准关键词」的检索侧上界，不声称英文机械归一化独立达到该水平。

**测试报告**（灵枢公开仓评测，方法学与口径真源 → [`md_cg/semantic/REPRODUCE.md`](md_cg/semantic/REPRODUCE.md)）：

| 方法                                                                                  | hit@1     | hit@5     | hit@10    | 语料                                                                                           |
| ----------------------------------------------------------------------------------- | --------- | --------- | --------- | -------------------------------------------------------------------------------------------- |
| ① 中文原子语义（md_cg 主链路：char-bigram + 四路 RRF + 同义扩展 + terms）                             | 94.6%     | 99.2%     | **99.2%** | locomo-zh-500 · 500 题（中文题面）                                                                  |
| ② **英文检索 · 中文语义归一化桥接（主路线）**：AI 归一为中文关键词 → 字级英文原子映射 × 双语原子库 Jaccard（**给定关键词的检索侧上界**） | **96.8%** | **99.8%** | **99.8%** | locomo-zh-500 · 500 题（同 qids）                                                                |
| ③ 英文原题直接原子匹配（不做归一化的对照）                                                              | 50.0%     | 74.6%     | **81.2%** | locomo-zh-500 · 500 题（同 qids 英文原题）                                                           |
| ④ 英文问句 → 机械词表归一端到端（②链路的机械化对照：归一不借助 AI 的真实下界）                                        | 24.6%     | 46.2%     | **57.6%** | locomo-zh-500 · 500 题（同 qids 英文原题；2026-09-15 第三方错译暴露面修正后 24.0/46.0/57.2→本行，CEDICT 层低置信标记已落地） |
| 英文反事实：硬套中文 char-bigram 主链路（默认态）                                                     | 27%       | 45%       | 56%       | bench6 · 100 题（口径不同，只看量级）                                                                    |

> ②③是**同一评测集上的隔离实验**：② 的 query 走中文关键词语义链（AI 归一化的输出形态），③ 连归一化也不做、直接拿英文自由表达提取原子——②③ 之差（99.8 vs 81.2）=「关键词级语义链」与「自由英文词面」两种 query 输入形态在检索链路里的效果差（同义词鸿沟 + 归一化桥接的合并贡献）。**AI 归一环节本身的质量未单独评测**——其机械替代的端到端下界由 ④ 给出（57.6%）。②路鲁棒性实测（query 确定性扰动后走同一 ② 链路）：漏 20% 关键词 ⑤=99.4 / 插 3 噪词 ⑥=99.8 / 错译 20% 关键词 ⑦=99.2（hit@10）——归一结果只要过半正确，hit@10 即稳 99%+，**AI 归一的实际门槛远低于完美归一**。doc 侧各臂相同（中文五槽加工面的字级原子映射 ∪ 英文正文归一词，与 ① 同属写入侧加工口径）。历史沿革：早期无加工面语料口径测得 ②=87-88、③=79.0（dsh 端文档口径），方法学真源见 REPRODUCE.md；机械词级归一→纯中文库（u2，33.6% 上界）已裁定排除并归档证据链。


**差距三层归因（按权重排序）**：

1. **同义词鸿沟（根本原因，语言固有属性）**。中文「概念 → 表达」约 **1:1~1:2**（95 个同义词对），字面重叠天然命中，词面匹配几乎不打折；英文每概念平均 **5.2 种**表达（CC-CEDICT 语料统计，8,493 汉字展开出 172,950 个英义对，**1,820 倍**于中文）。上表 ② vs ③ 就是这道鸿沟的**直接隔离实验**：同一语料，query 侧做中文语义归一化得 99.8%，不做归一化直接英文词面匹配即降至 81.2%——鸿沟真实存在，但**在查询侧做一次语义归一化即可闭合**，不需要向量嵌入。
2. **归一化是正解，机械归一是死路（主路线裁定的依据）**。机械词典查表翻译端到端实测仅 **57.6%**（④臂：英文问句 → CEDICT 28294 键词表直译 → ②同链路），且低于「完全不归一」的 81.2%（③臂）——机械直译把可译词错译为错误原子（race→人种），反而毁掉原本有效的词面贡献；更早的机械词级归一→纯中文库口径上界也只有 33.6%（已排除）。根因是英文自然问句的信息密度远低于标注关键词（词面交集 p50=1 vs 8），机械替换无法补足信息差；查询侧归一化由 **AI 完成**（理解式归一，如 take up a hobby → 培养爱好），系统只供词表真源与字级映射——②的 99.8%（上界）与机械路 57.6%（下界）之间的空间，就是 AI 归一要填的部分；⑤⑥⑦证明这个要求只需「大致方向对」。
3. **架构非对称（设计裁定）**。中文链路的四路 RRF / 同义扩展 / terms 字段全部建立在「字面=语义」的中文前提上，直接跑英文实测劣于独立路（反事实 56%）——英文按裁定走「归一化桥接 + 原子 Jaccard」独立路，不硬套中文 char-bigram 管线，是**有意的取舍**而非遗漏。中→英字级映射覆盖 6,319 字（97.2%），长尾派生词（happy/happiness）不折叠——残余失配由查询侧 AI 归一化吸收，这正是 ② 反超 ③ 21.6pp 的来源。

**要不要上语义向量检索？** 向量嵌入可以弥合同义鸿沟，但会引入嵌入模型依赖与索引体积，与灵枢「零重依赖、纯词面可复现」的公开仓原则冲突，**当前明确不做**；归一化桥接已把检索侧上界做到 hit@10 99.8%（鲁棒性：归一不完美时仍 99%+），满足「答案在候选池」的记忆系统主用途。

**渐进式语义检索（Progressive Semantic Retrieval，正式机制 v0）**。查询不是固定语义结构，而是**不断收紧的约束集合**——语义解析的完整性与检索的必要性不是同一个问题：从最小可靠语义（部分归一原子）开始宽检索，再按候选间区分度逐步增加条件使语义收敛；DEFER ≠ 失败，=「当前语义分辨率不足，继续获取条件」，与证据防火墙四态天然衔接。同一份 500 题实测：一次性全原子 96.8/99.8/99.8（=②锚点）；只宽检 50% 核心原子 85.2/95.8/97.0；**宽检索→区分性条件渐进收紧（平均 +2.97 个条件）收敛到 93.6/98.8/99.0**——与一次性差 0.8pp，实证「不必一句话完成语义理解」。受控干扰池进一步实证排序面消歧（top1 稳 gold、渐进不引入新冒充），并如实暴露边界：条件面冒充（生效条件被伪造为 gold 同款）不被内容词渐进消除——词面条件确认必要非充分，真伪判据=证据基底分离（另案）。控制器 `md_cg/progressive.py`（纯函数、确定性、评分器注入式），实验 `md_cg/bench_progressive.py`。

---

## 📚 公开评测数据集

📎 全部随仓库公开（CC BY-NC 4.0），可直接下载用于你自己的记忆系统对照评测：

| 基准 | 归属 | 状态 |
|---|---|---|
| **hive-memory-bench**（权威对照 · 外部公开基准） | **公开基准**（184 题＝主轮 92＋干预轮 92 / 23 章 / 6.1 万字；CC BY 4.0） | **六家记忆系统同口径对照主场**（灵枢 / OpenViking / 朴素 BM25 / MemOS / Mem0 / Hindsight，同一生成器、唯一变量＝检索上下文）· 灵枢读数经本版 HEAD 重测复核 → [hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench) |
| **locomo-zh-500** | **自建**（LoCoMo 中文派生 · 500 题 / 567 turns / 0.6 MB） | **已随仓库公开** `data/benchmarks/locomo-zh-500/` · 可复现 · **我方成绩：中文 hit@1 94.6% · hit@5 / hit@10 99.2%（md_cg 完整主链路）；英文（语义归一化桥接）hit@10 99.8%——见上[中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证)①② 行** · **第三方独立复现：中文 96.8/99.6（自报 96.4/99.8 噪声内）、英文主路线 96.8/99.8/99.8 逐位一致** → [第三方验证报告](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) |
| **bench6 · 六家横评** | **自建**（LoCoMo 中文派生 · 100 题 / 137 turns · **中英双查** / 约 90 KB） | **已随仓库公开** `data/benchmarks/bench6-100-zh-en/` · **六家同口径对照**（灵枢 5 口径 / 纯向量 RAG / mem0 / Graphiti / GraphRAG / Letta 两模式）· 报告 → [横评_六家100题中英双查_v1.0.md](docs/eval/横评_六家100题中英双查_v1.0.md) |
| LoCoMo | 第三方 `mteb/LoCoMo` BEIR（1976 题 / 5882 turns） | 上游来源（英文原版） |
| memory-bench-1000 | **自建** | SNR 见评分报告 v2.0；已公开 `data/memory-bench-1000.jsonl` |

> **口径层级（2026-10 起）**：中文检索的权威对照统一以 **hive-memory-bench** 为准（六家同口径、机械层读数不依赖判官）；下表 `locomo-zh-500` 与 `bench6-100-zh-en` 为本仓自建的历史口径题池，保留供复现与英文桥接实验。

> 上表四行性质不同，勿混读：`locomo-zh-500` 的分数是**本仓库我方成绩**（基于LoCoMo自建并公开的评测集，可复现）；`bench6 · 六家横评` 是同源派生的**小型同口径对照集**（零干扰池，只做六家系统横向对照，**非我方单方成绩**）；LoCoMo 一行指**上游英文原版 1976 题**，本仓库未在其上产出完整成绩；`memory-bench-1000` 是自建记忆库的评分报告。
> **该成绩的性质（非虚假声明）**：`locomo-zh-500` 的分数是**写入侧结构化加工后的检索成绩**——入库前把每轮对话加工为「身份 / 时间 / 摘要 / 词 / 条件四槽」条目，再走词法 + 同义扩展检索。这与主流记忆系统所用的**向量化嵌入 + 关键词/摘要压缩**属**同一类写入侧加工**，差异只在索引与检索算法，不在「是否对原文做了加工」。因此该口径可用于**同口径对照**，不是对裸文本直读的虚高取巧。
> `locomo-zh-500` 是**本仓库对外发布的检索评测集**：供外部在**同一份中文题面**上对自己的记忆系统做可对照评测。它只评检索命中（hit@k / MRR），**不评答案正确性**；被测池为**零干扰**（池内全是 gold），故高命中率不可外推为端到端记忆能力——完整边界与许可见 `data/benchmarks/locomo-zh-500/README.md`。
> `bench6-100-zh-en` 沿用同一口径，并**每题提供中英两套词面**（评「换查询语言后是否仍命中」）；它同样是**上界对照集**——家间差距小于约 16% **不可判为显著**；评测入口已随仓库公开（`run_bench.py`：零依赖口径复现 + Adapter 协议接入你自己的系统），接入任意llm和向量方法都可复现，详见 [横评报告](docs/eval/横评_六家100题中英双查_v1.0.md) 与 `data/benchmarks/bench6-100-zh-en/README.md`。

**复现我方成绩**（零上游依赖）：

```bash
python -m md_cg.bench_locomo_zh_public   # 中文：只读 data/benchmarks/locomo-zh-500/，产出公开词法口径参考量级（hit@1 93.6% 单路 / 97.6% +同义扩展）；上表 94.6/99.2 为 md_cg 完整主链路（四路 RRF + 同义扩展 + terms）成绩
python -m md_cg.bench_en_atoms_public    # 英文：语义归一化桥接七臂（② 96.8/99.8/99.8 主路线·检索侧上界 · ③ 81.2 不归一对照 · ③a 78.2 纯正文对照 · ④ 57.6 机械归一端到端下界 · ⑤⑥⑦ ②路鲁棒性 99.2-99.8）；英文原题面为上游派生不入库，自备后即可全量复现
python -m md_cg.bench_progressive        # 渐进式语义检索双实验（G0 96.8/99.8/99.8 =②锚点自校验 · 只宽检 85.2/97.0 · 渐进收敛 93.6/99.0 · 受控池排序面消歧+条件冒充边界）
python -X utf8 -m md_cg.bench_e2e_judge --quick   # 端到端干扰池评测·冒烟（确定性裁决 vs LLM-as-judge 三臂，全量见 --skip-llm/--arms llm）
python -X utf8 -m md_cg.bench_e2e_qa      # 端到端 QA：pinpoint/answerability（LoCoMo 上游 gold 答案 · reader+judge 真实 LLM）→ 报告见 docs/eval/端到端干扰池评测_v1.1（主口径 MDCG_UNIFY_QUERY=0）
# 第三方独立评测脚本（第三方交付物原样入库；脚本内 REPO 为第三方沙箱路径，复现需改为本机仓库路径）
python test/locomo_independent_eval.py   # MdCG 引擎口径五臂（A 中文五槽 / B 英文原文 / C 标准归一化 / D 双语并集 / F 语义摘要路 + 随机基线）
python test/locomo_jaccard_probe.py      # 主路线 Jaccard 口径拆解（J2_full 完整版 / J2_zh 仅中文层 / J2_body 仅英文归一词 / J0_raw 英文原词）
```

> **复现用两处数据面开关（可选 env，缺省行为如下）**：`MDCG_E2E_JUDGE_ROOT` 覆盖 `md_cg.bench_e2e_judge` 的数据根——缺省 `<仓根父目录>/test/e2e_judge`（建池缓存 / LLM 缓存 / 结果都落在其下；`--data-root` 参数优先于该 env）；`MDCG_CONFORMANCE_ROOT` 指认真源库根（仓外私有）——设置且 `<库根>/_index.json` 存在时，`md_cg.test_conformance` 加跑真源集成基线复核（K1–K5 断言；不达标即该套件判败），未设置（或缺 `_index.json`）时该集成段打印 SKIP、合成库主测面照常全跑。

> 自建 bench 的噪声层 400 条 + unlabeled 边界 350 条为天然负对照；任何基准报告须带**干扰抑制负例组**与 **T-JUDGE 负例拒绝率**双向报告（遵守「只报总分 = 不通过」）。

---

## 🎯 七维标尺实测（六家同尺）

> 项目维护者按同一把内部七维标尺（结构 / 检索 / 判断 / 调用 / 演化 / 连续 / 可信），把**六家记忆系统**（含灵枢）放到公开基准 [hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench) 的**同一批实测**上对比：灵枢与 OpenViking 在**四维（S / R / C / T）并列 7–8 档第一梯队**；**J（判断）仅邻面读数**（灵枢在「发现不一致」面落后于朴素 BM25）；**U（演化）/ I（连续）**在六家同尺面上无数据——**v3.1 起，灵枢以自身 51 天运行史完成单家活体自测（7–8 档 ▲：能陈述自迭代史／错误史／自我认知，且 v1.0 暴露的缺口经迭代已修复闭环）**；「AGI 级（L5）」在跨系统口径下仍无一系统被实测验证。逐维读数、映射规则、与 v2.0 自评的修正（J / C 下修、U / I 结构自评撤回后经实测判 7–8▲）见 [AGI 七维评分报告 v3.1（六家同尺实测 + U/I 单家自测）](docs/eval/AGI七维评分报告_六家记忆系统同尺实测_v3.1.md)。
> **不虚高的坦白**：本版「凡分必挂实测」——v2.0 的「综合 8.6」为结构取证口径（源码级核对），在实测口径下不成立；灵枢的实测落后面（「发现不一致」指出 2/9、零材料净贡献 −9.9pp 等）已逐项列出。

### 第三方复评（七轮独立评估）

> 独立评估者（非项目方）以「统一评分 v7」对灵枢与 deja-vu 做同权重八维对照（检索中英 / 可复现性 / 工程测试 / 架构独立性 / 诚实度 / 生态适配 / 部署运维）：**灵枢 9.258 / deja-vu 9.119（+0.139，七轮首次为正——评审者声明该差距在评审噪声以内）**，收敛轨迹 `7.79→8.29→8.57→8.72→9.13→9.133→9.258`；v7 含对自身四条建议全撤回的勘误（§三点五：所称「缺失能力」经复核均早已有之，含 `cg(op=ingest)` 后向索引通道）
> 报告全文→ [第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md](docs/eval/第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md) · 评估日期 2026-09-15，被评灵枢基线 `38412c4`
>
> **LoCoMo 第三方独立验证**（同日另一份独立报告，评测全流程从零实现、不调用灵枢任何 `bench_*` 脚本）：中文 96.8/99.6 独立复现（自报 96.4/99.8，噪声内）；英文主路线 ② 96.8/99.8/99.8 **逐位一致**；并给出更严格归因——99.8 由中文摘要层挣得（去英文层 hit@10 反为 100.0%）、英文标准归一化端到端真实水平 81.0%（写入侧机械归一口径，较不归一 +58pp）、检索失败 100% 归因归一化丢词/错译而非排序；同时确认数据集区分度（query 对 gold 覆盖 0.875 vs 非 gold 最佳 0.469）与 OOV 如实透出。报告全文→ [第三方验证报告_LoCoMo_灵枢_.md](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) · 配图 → [第三方验证报告_LoCoMo_灵枢_.png](docs/eval/第三方验证报告_LoCoMo_灵枢_.png) · 独立评测脚本 `test/locomo_independent_eval.py`、`test/locomo_jaccard_probe.py`（第三方交付物原样入库，`REPO` 变量为第三方沙箱路径，复现需改为本机仓库路径）
>
> **口径声明**：两份报告均为外部独立口径，与上方七维标尺实测（六家同尺 ＋ U/I 单家自测 · 档位判定）是**多套独立口径，分数不可互比**；LoCoMo 报告同时验证了数字可复现性与归因边界，其归因发现已如实吸收进[中英双语检索差距](#-中英双语检索差距我们用中文语义归一化解决英文检索实证)一节。

---

## 🧰 工具面

### 能力 → MCP 入口

| 能力 | MCP 入口 |
|---|---|
| 记忆写入 · 关系链接 · 结构关系 | `cg(op=write)` `cg(op=link)` `stg(op=relation)` |
| 多路融合检索 · 条件路由 · 因果链 · 时间线 | `mdcg_recall` `mdcg_search` `cg(op=route)` `stg(op=timeline)` |
| 会话隔离（分档可见：public/internal 跨会话共享 · private/secret 绑定归属会话 · 设计者豁免；写入带会话归属 · 租户物理根接线 fail-closed） | `mdcg_remember(session=…)` `stg(op=timeline, session=…)`；私档经 `sensitivity: private` 写入（详见 issue #35 设计定稿） |
| 检索性能开关（读缓存 · 热路径缓存 · 检索门控 · 统一归一——只翻译英文内容、中文原样） | env：`MDCG_READ_CACHE` `MDCG_HOTCACHE` `MDCG_RETRIEVAL_PIPELINE` `MDCG_UNIFY_QUERY` `MDCG_CHAIN_TYPES` `MDCG_TEMPORAL_GAMMA`（读缓存默认开，=0 关；统一归一默认关，=1 开；热缓存/门控默认关，=1 开；因果/时间两路缺省开，可 `causal=false`/`temporal=false` 单关；`MDCG_CHAIN_TYPES` 因果路边类型集，留空=缺省 `causal,sequential,applies_to`；`MDCG_TEMPORAL_GAMMA` 时间邻近度衰减率，缺省 ln2/30天） |
| 事实时效过滤（`validity=true` 只排「已过期」，保留「未生效」） | `mdcg_recall` `mdcg_search` `cg(op=read)` |
| 写入裁决 · 主动遗忘 · 冲突检测 · 反思 | `mdcg_remember` `cg(op=verify)` `cg(op=metacognition)` `mdcg_reflect` |
| 重要性评分 · 预算装包 · 分层注入 · 记忆自净 | `cg(op=session)` `cg(op=scrub)` `cg(op=info)` |
| 知识固化 · 结构变更账本 / 回滚 · 自维持巡检 | `mdcg_flywheel` `cg(op=consolidate)` `cg(op=maintain)` `cg(op=sustain)` |
| 身份一致性 · 自我状态 · 演化史 | `cg(op=identity)` `cg(op=self_state)` `cg(op=evolution)` |
| 加密 · 密级隔离 · 审计留痕 · 保护/遗忘 | `cg(op=protect)` `cg(op=forget)` · [护栏宪章](docs/mdcg/guardrail-charter.md) |
| 记忆可靠性闸（对话→六要素候选→编外复核→落库） | `cg(op=ccg)` |

> **索引链**：能力 → op（本表）→ 实现模块（本节下方认知图投影）→ 行号级代码映射（[功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md)）——每一步都可从 README 一跳到达源码，一致性由 `scripts/cogmap_sync.py check` 守卫。

### 🧱 记忆可靠性闸：CCG 六要素编译（`cg(op=ccg)`）

把对话记录编译成可检索的 CCG 六要素条目（`# 功能名 / # 生效条件 / # 子功能 / # 执行 / # 验证方式 / # 不适用条件`），且**编译者不得自证**——LLM 产出的候选必须经**认知图之外的编外单元**复核才准落库（机械拒绝码 `E041`，不依赖 prompt 自觉）。候选以内容摘要绑定暂存（`_ccgc_pending/`，索引不可见），三次独立调用间防篡改。

| 步骤 | 调用 | 结果 |
|---|---|---|
| ① 编译 | `cg(op=ccg, action=compile, node_id=…, dialog=…)` | 六要素候选 + 名实门校验（每个写入值必须是原文子串），**不当场写库** |
| ② 复核 | `cg(op=ccg, action=review, node_id=…, blocking=true)` | 编外单元裁决：蜂巢 `reflect`/`verify` 优先；蜂巢不可用则**返回配置指引**（不假装可用），显式 `allow_degrade` 才降级为子代理 |
| ③ 落库 | `cg(op=ccg, action=link, node_id=…, apply=true)` | 摘要校验 + 签章准入通过才写入 |

错误码：`E040` 无签章 · `E041` 自证拒绝 · `E042` 复核未通过 · `E043` 只允许修正四槽（`action=recalibrate`）。`action=catalog` 自描述全部动作，`action=units` 体检复核通道（三态：蜂巢 / 待配置 / 子代理降级）。

---


<!-- COGMAP:BEGIN (scripts/cogmap_sync.py 自动生成 · 真源 md_cg/mcp_server.py · 勿手改段内) -->

**两个认知基元 · 41 个 op**（`kernel` 面）——下列 op 清单、实现模块与全部链接行号由 [cogmap_sync](scripts/cogmap_sync.py) 从真源自动提取，`check` 门禁守卫漂移；**点击任意名字直达源码对应行**：

| 基元 | op 数 | op 清单（点击直达实现分支） |
|---|---|---|
| **[`cg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L610)** 认知图统一入口 | 37 | [`help`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2107) [`status`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2113) [`edges`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2116) [`theory`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2119) [`link`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2136) [`info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2252) [`route`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2293) [`read`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2314) [`audit`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2369) [`write`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2389) [`goal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2397) [`task`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2416) [`recent`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2419) [`verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2431) [`review`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2436) [`forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2457) [`protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2466) [`identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2469) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2472) [`metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2475) [`self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2478) [`evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2481) [`sustain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2484) [`scrub`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2487) [`predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2490) [`causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2493) [`whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2496) [`index_code`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2499) [`index_doc`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2543) [`ref`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2586) [`session`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2589) [`ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2592) [`export`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2595) [`maintain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2598) [`consolidate`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2601) [`insight`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2604) [`ccg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2607) |
| **[`stg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1059)** 语义时空图入口 | 4 | [`relation`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3199) [`timeline`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3201) [`anchors`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3208) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3212) |

**op → 实现模块**（认知图投影：功能在哪段代码，一眼可达）：

| op（点击直达实现分支） | 实现模块（点击直达源码） |
|---|---|
| [`help`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2107) [`status`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2113) [`edges`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2116) [`route`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2293) [`goal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2397) [`task`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2416) [`recent`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2419) [`verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2431) [`review`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2436) [`forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2457) [`protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2466) [`identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2469) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2472) [`metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2475) [`self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2478) [`evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2481) [`sustain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2484) [`scrub`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2487) [`predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2490) [`causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2493) [`whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2496) [`ref`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2586) [`session`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2589) [`ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2592) [`export`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2595) [`maintain`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2598) [`consolidate`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2601) [`insight`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2604) [`ccg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2607) | [`_cg_dispatch` 内联](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2104) |
| [`index_code`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2499) [`index_doc`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2543) | [`refindex`](md_cg/refindex.py), [`security`](md_cg/security.py) |
| [`info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2252) | [`audit`](md_cg/audit.py), [`generation`](md_cg/generation.py), [`links`](md_cg/links.py), [`nodefile`](md_cg/nodefile.py), [`theory`](md_cg/theory.py) |
| [`audit`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2369) | [`auditview`](md_cg/auditview.py) |
| [`link`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2136) | [`evidence`](md_cg/evidence.py), [`links`](md_cg/links.py), [`provenance`](md_cg/provenance.py), [`security`](md_cg/security.py), [`signer`](md_cg/signer.py) |
| [`read`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2314) | [`refindex`](md_cg/refindex.py) |
| [`theory`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2119) | [`theory`](md_cg/theory.py) |
| [`write`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L2389) | [`writepipe`](md_cg/writepipe.py) |
| [`relation`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3199) [`timeline`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3201) [`anchors`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3208) [`consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3212) | [`_stg_call` 内联](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L3180) |

**细粒度面**（`MDCG_MCP_SURFACE=full`，插件运行时使用）：[`cg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L610) + [`stg`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L1059) + **31 个 `mdcg_*`** = **33 个工具**：

[`mdcg_remember`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L164) [`mdcg_recall`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L195) [`mdcg_search`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L245) [`mdcg_get`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L257) [`mdcg_reflect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L265) [`mdcg_verify`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L271) [`mdcg_flywheel`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L282) [`mdcg_mine_fix_pairs`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L287) [`mdcg_rejected`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L292) [`mdcg_unresolved`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L298) [`mdcg_propose`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L304) [`mdcg_review_list`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L312) [`mdcg_review_decide`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L317) [`mdcg_review_records`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L334) [`mdcg_forget`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L342) [`mdcg_protect`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L350) [`mdcg_forgetting_history`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L360) [`mdcg_identity`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L366) [`mdcg_consistency`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L392) [`mdcg_metacognition`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L412) [`mdcg_self_state`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L434) [`mdcg_predict`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L472) [`mdcg_causal`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L500) [`mdcg_evolution`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L517) [`mdcg_restore`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L540) [`mdcg_health`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L545) [`mdcg_whoami`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L550) [`mdcg_ingest`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L555) [`mdcg_watermarks`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L567) [`mdcg_whitebox`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L572) [`mdcg_service_info`](https://github.com/FuRongJun-1999/dsh-memory/blob/main/md_cg/mcp_server.py#L593)

逐个 op 的「功能 → 代码 → op」行号级映射另见[功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md)。

<!-- COGMAP:END -->

| `tools` 模式 | 暴露数 | 说明 |
|---|---|---|
| `'core'`（**默认**） | **2** | 仅 `cg` / `stg` |
| `'brain'` | **30** | `cg`/`stg` + 28 细粒度 |
| `'all'` | **30** | full 面 33 − 3 个宿主级风险工具 |

> 风险工具 `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide` 需 `can_admin`，即使 `tools: 'all'` 也不自动暴露。
> 35 op 已逐一冒烟验证：**35/35 可达，0 未知 op、0 意外崩溃**。
> 历史 82 工具（旧 aeis 引擎）去向见 [迁移映射](docs/mdcg/灵枢82工具_功能整理与迁移映射_v0.1.md)。

---

## 🏗️ 架构（以 DSH 为例 · 其它 MCP 宿主同构）

```
DeepSeek Harness (cordis)
  Agent Loop ──┬── 工具面 ctx.tools（cg / stg / mdcg_*）
               └── session/event（自动记忆钩子 · 自动召回注入）
                     │ stdio · 逐行 JSON-RPC
┌────────────────────▼─────────────────────┐
│ 灵枢大脑子进程（spawn · 唯一）             │
│ python -m md_cg.mcp_server               │
│ cg/stg 基元 + 31 细粒度 · md 认知图真源    │
└──────────────────────────────────────────┘
（可选）「身体」能力后端：仅 capability.enabled=true 时另起一个能力库子进程，默认不启动
```

**记忆只有一个真源**：`md_cg/` 认知图（纯 md 文档，随包自带）。确定性规则引擎与知识库已内迁；
AEIS 仅作可选「身体」能力后端（角色扮演生成），不再存记忆、默认不启动。

> 其它 MCP 宿主同构：宿主工具面（`cg` / `stg` / `mdcg_*`）↔ stdio MCP ↔ `md_cg` 大脑；四端差异只在**纪律注入方式**（矩阵见[多 harness 接入](#多-harness-接入按端分目录)），大脑与记忆真源零改动。

---

## 📚 文档导航

| 文档 | 内容 |
|---|---|
| **[docs/ 目录索引](docs/README.md)** | 六域快速索引（mdcg / swarm / hive / theory / eval / plans）· 新文档归域规则 |
| **[Release v0.7.2](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.7.2)** | 本版变更：读面损坏 UTF-8 家族收口——① 读取面不再因损坏非 UTF-8 节点崩溃（贡献者 PR #54）＋同形态残余加固（census / restore / read_preimage / locate 四站点：坏 trash 与坏前像均结构化失败且源保留，health 增 skipped_unreadable 计数）② issue #53 三缺陷（密文假域标签 / 桶计数虚高 / 假 hash_drift）③ 工程面收口（PR #47：CI 先构建 Rust/Hive 二进制再跑 Python 全量；套件并行改串行防共享临时目录竞态；charset 表与纪律指纹跨平台同判） |
| **[Release v0.7.1](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.7.1)** | 本版变更：检索面三批同族收口——① issue #52 条件先行与截断可观测（timeline/anchors/consistency 的索引序切片退场：条件先于限额、截断可观测＋可操作提示，max_scan 数值不动）② stg 结构索引（by_session/by_layer/by_time 内存倒排＋条件资格首验，双 flag 默认关，在役实测 52× 收敛（7607 条规模；加速比随库规模与条件收窄度增长、小库下显著降低）、两臂逐位等价）③ consistency 选面（MAX_SCAN=200 索引序静默截断退场：相关性预筛＋保底面＋面内例外＋truncated/kept/hint 可观测，数值一字未动） |
| **[Release v0.7.0](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.7.0)** | 本版变更：① **自迭代与睡眠**——睡眠周期引擎（影子副本迭代 + 语义四闸 + git 周期合并，九步显式台账，缺省 23:00-07:00 窗口、一小时一轮、可调）② **因果/时间图检索路**进默认检索（因果路复用既有条件链；时间路走唯一时间核，半衰期 30 天；边类型集可配）③ **六要素补成 6 行索引角色**（验证方式/不适用条件进默认检索，边界命中与资格裁决分开计数）④ **权重刷新与衰减进主分数**（旧记忆降权、被调用者刷新，带 floor 与保护线、可预演可回滚）⑤ 累积修复：装机即挂（issue #48）、出货面冒烟进门禁（第九腿）、归一层缺省翻关、N230 重放遮蔽 |
| **[Release v0.6.1](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.6.1)** | 本版变更：外部测试报告逐条核验后的四批修复——① 写面静默失败族（自动 id 加熵与撞车有界重生成 / 声明密级透传且落盘不一致即 fail-closed / 索引分片目录删除后自愈）· ② 合并吞正文与冲突误判（MERGE 与熵 DROP 两分支都保新正文 / 仅空白差异不再误判同一条件分歧 / CCG 哨兵空值不再触发假冲突）· ③ 召回面诚实性（负覆盖条目不再以满分冒充答案且不溢出 k / 一致性飞轮只对真冲突建单 / 显式 k=0 不再被当缺省 / 仅 1 个桶的库不说「分区正常」/ 类型错的参数与裸 null 出口收成结构化错误）· ④ 插件面（全角凭据形态纳入脱敏 / 注入记忆加不可信边界声明 / 子代理委派不写成本人记忆 / 召回与时间线读写两侧会话口径同尺）。九项探针先取证后改码，每处修复配定点变异自证 |
| **[Release v0.6.0](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.6.0)** | 本版变更：init 一键配置命令（交互三问 → 四端 mcp.json 片段 + 指引）· bin 入口 · README 声明 DSH 0.17.2 已验证 · 检索强化（读缓存 / 智慧书预计算 / 统一归一 / 门控生产路径）· 蜂巢稳定形态与并发防线 · 会话隔离 |
| **[Release v0.5.1](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.5.1)** | 本版变更：Windows 中文/编码与保留设备名修复（issue #39）· 结果完整性锚与 WAL seq 连续性（防伪造产物/防丢行乱序）· 启动对账 reconcile · 幂等提交 · 外部贡献 PR #40 十三处（health heal 闸门 / scrub 误报 / 写入侧落盘 / 桶路弃权）· 故障注入套件 18 用例入库 |
| **[Release v0.5.0](https://github.com/FuRongJun-1999/dsh-memory/releases/tag/v0.5.0)** | 本版变更：强化检索（读缓存+派生物常驻 / 智慧之书面预计算 / 统一归一 / 门控生产路径）× 稳定蜂巢并发调度（多写者防线 / 依赖门禁）· 12 个 issue 修复 |
| [README 详细版](docs/mdcg/README详细版_v0.4.10.md) | 完整能力说明 · 配置项全表 · 安装与验证细节 |
| [发布说明 v0.4.5](docs/mdcg/release_v0.4.5.md) | 历史版本发布说明（兼容性 / 升级指引） |
| [AGI 七维评分报告 v3.1（六家同尺实测 + U/I 单家自测）](docs/eval/AGI七维评分报告_六家记忆系统同尺实测_v3.1.md) | 七维 × 六家实测对比 / U·I 单家活体自测（▲）/ 映射规则 / 对 v2.0 自评的修正 / 诚实边界 |
| [AGI 七维评分报告 v2.0（单家自评 · 历史）](docs/eval/AGI七维评分报告_md_cg_v2.0.md) | 结构取证口径的自评（v3.1 已按实测复核修正） |
| [第三方复评 · 统一评分 v7](docs/eval/第三方验证报告_灵枢_vs_dejavu_统一评分_v7.md) | 独立评估者七轮对照（灵枢 vs deja-vu）：八维加权 / 收敛轨迹 7.79→9.258 / 评审偏差声明 / 自身建议全撤回勘误 |
| [第三方验证 · LoCoMo 独立复现](docs/eval/第三方验证报告_LoCoMo_灵枢_.md) | 独立实现评测全流程：自报数字逐位复现 / 归因拆解（中文摘要层 vs 英文归一化 81.0%）/ 静默错译样本 / 数据集区分度证伪检查（配图 `第三方验证报告_LoCoMo_灵枢_.png`） |
| [功能调用映射表](docs/mdcg/功能调用映射表_v0.1.md) | 任何功能 → 调用哪段代码（含行号、MCP op） |
| [护栏宪章 v2.0](docs/mdcg/guardrail-charter.md) | 对外部智能体与人类使用者的行为边界 |
| 教学四篇 | [白箱智能是什么？](docs/theory/白箱智能是什么？.md) · [智能的认知过程](docs/theory/智能的认知过程.md) · [智能的公理化基石](docs/theory/智能的公理化基石.md) · [信息差为什么必然存在](docs/theory/信息差为什么必然存在且自然扩大.md) |
| [工作纪律·认知图条目 v1.1](docs/工作纪律_认知图条目_v1.1.json) | 自我约束的 18 条工作纪律（嵌套认知图条目 `work_discipline`） |
| [hive-memory-bench（公开基准 · 权威对照）](https://github.com/FuRongJun-1999/hive-memory-bench) | 184 题 · 23 章 · 六家记忆系统同口径对照（机械层读数 · 判分器 · 机器可读台账） |
| [六家记忆系统横评 v1.0（历史口径 · 上界对照集）](docs/eval/横评_六家100题中英双查_v1.0.md) | 100 题 · **中英双查** · 六家同口径对照；含判定单 / 条件层归因 / 诚实边界（题集 → [data/benchmarks/bench6-100-zh-en/](data/benchmarks/bench6-100-zh-en/README.md)） |
| [端到端干扰池评测 v1.1](docs/eval/端到端干扰池评测_确定性裁决vsLLM_judge_v1.1.md) | **带干扰池端到端**：确定性裁决层 vs LLM-as-judge 正面对比（四族干扰×浓度梯度）· LoCoMo 上游 gold 端到端 QA **43.3%/40.0%** · 防火墙与 LLM 裁决对无标记干扰均无增益（REJECT 恒 0）· **统一归一层 A/B：CCG+RRF 形态 −11.7pp（批次 15 边界反馈）** |
| [端到端 LoCoMo QA 同口径对照 v1.0](docs/eval/端到端LoCoMoQA同口径对照_v1.0.md) | **中文完整对话做记忆 · 自然问句做查询**（与 Mem0/Letta 论文同设定）：检索注入 QA **17.2%** / full-context 16.4% · 检索四组对照定因（自然问句诚实下界 hit@10 **40.2%** vs 派生题面 92.0%；改写/归一均实证排除）· lost-in-the-middle 实证 · **方向拍板：认知图概念桥接（不上向量）** |
| [Rust 检索库](rust/README.md) | `mdcg_eval` 三形态：库内嵌大批量检索 / `--serve` 多智能体进程实例 / 公开数据集评测器（零依赖 · 与 Python 口径对齐，rank 对拍 harness 守卫） |
| [蜂群多智能体](docs/swarm/蜂群多智能体_功能说明_v0.6.md) | `swarm/` 多进程蜂群执行层（2026-09-13 自 protocol-compiler 迁入，大脑核心内部能力）：.pbc 确定性实例 + Gossip/拓扑/水位信箱/WAL-HMAC/信任聚合/健康评分（Rust 纯 std 零依赖 · 159 断言回归全绿） |

### 多 harness 接入（按端分目录）

> **主推路径：MCP 直挂**——各端接入的**共性是挂载同一个 stdio MCP server**（`python -m md_cg.mcp_server`）：任何支持 MCP 的宿主直接挂上即可，**不依赖任何插件系统**。

共享层（`md_cg/` 大脑 · `data/` · `docs/` · `scripts/`）在仓库根；**harness 专属配置按端归置**，下表列的只是各端**纪律注入方式**的差异（纪律如何进入上下文），大脑与记忆真源零改动：

> ⚠ **出货面与源码树的分界**：npm 包的 `files` 只含 `lib/ src/ md_cg/ skills/ README.md dsh/ codebuddy/ zcode/ docs/`
> —— `scripts/`、`hive/`、`swarm/`、`compiler/`、`rust/` 属**源码树**（发布门禁、蜂巢运行时、Rust 评测器），
> 装出来的插件里**不存在**。因此运行期依赖一律不得指向它们：
> 判据面清单走包内 `md_cg/judgment_manifest.py`（`md_cg/interop.py` 进程内调用）、
> 裁决 CLI 走包内 `python -m md_cg.review_cli`、全量测试走包内 `python -m md_cg.run_tests`；
> 依赖 `scripts/`/`hive/` 的**测试**在缺件时如实 SKIP（不 FAIL、不虚报通过）。

| 目录 | harness | 接入文档 | 纪律注入方式 |
|---|---|---|---|
| [`dsh/`](dsh/README.md) | DeepSeek Harness | [dsh/README.md](dsh/README.md) | `~/.dsh/profiles/web/cordis.patch.yml` 的 `personaPrefix`（compact · 每轮） |
| [`codebuddy/`](codebuddy/README.md) | CodeBuddy | [codebuddy/README.md](codebuddy/README.md) | 项目根 `CODEBUDDY.md`（full · 会话起始） |
| [`zcode/`](zcode/README.md) | ZCode | [zcode/README.md](zcode/README.md) | 项目根 `AGENTS.md`（full · 会话起始） |
| [`codex/`](codex/README.md) | Codex CLI | [codex/README.md](codex/README.md) | 项目根 `AGENTS.md`（full · 会话起始） |
| [`claude/`](claude/README.md) | Claude Code | [claude/README.md](claude/README.md) | 项目根 `CLAUDE.md`（full · 会话起始） |

> 五端纪律**同源**（`docs/工作纪律_认知图条目_v1.1.json`），由 `scripts/render_discipline.py` 渲染、
> `scripts/verify_discipline.py` 守卫漂移；矩阵见 `docs/discipline/harnesses.yaml`。

<details>
<summary><b>可选补充：插件形态安装（仅 Claude Code / Codex CLI · 省手工复制，非主推路径）</b></summary>

> 等价于按上表手工配置，只是把纪律 skill 与配置样例随插件一起拿到；**不装插件不影响任何能力**。

| 宿主 | 安装 | 插件位置 | 装后一步 |
|---|---|---|---|
| Claude Code | `/plugin marketplace add FuRongJun-1999/dsh-memory` → `/plugin install lingshu-memory@lingshu` | `claude/lingshu-memory/`（纪律以 skill 分发，`/lingshu-memory:linglu-discipline` 可显式调用） | 复制插件内 `mcp.json.example` 为项目根 `.mcp.json`，填 `PYTHONPATH` |
| Codex CLI | `codex plugin marketplace add <本仓路径>` → `codex plugin add lingshu-memory@lingshu` | `codex/lingshu-memory/`（skill 三级渐进加载；`.codex-plugin/plugin.json` 清单） | 把插件内 `config.toml.example` 两段合并进 `~/.codex/config.toml`，填 `PYTHONPATH` |

> marketplace 清单：Claude 端在仓根 `.claude-plugin/marketplace.json`，Codex 端在仓根
> `.agents/plugins/marketplace.json`。插件不含大脑本体（`md_cg/` 不随插件分发）——MCP 装好后
> 大脑仍是你本机的 dsh-memory 仓库；插件形态的纪律 skill 同样由真源渲染（`skill` 变体，
> 矩阵槽位 `claude-code-plugin-skill` / `codex-plugin-skill`），漂移由同一 `verify_discipline.py` 守卫。

</details>

---

## 🛠️ 开发

```bash
npm install                          # NODE_ENV=production 时须加 --include=dev
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

> `NODE_ENV=production`（或 `--omit=dev`）会省略 devDependencies，`tsc`/`tsx` 不在位；
> 此时 `prepare` **跳过构建并在 stdout 明示**（不再让 `npm install` 因 `tsc` 缺失而整体失败），
> 需要构建请用 `npm install --include=dev`。另：`engines.node >=22.19` 之下运行会收到
> EBADENGINE 警告（仅提示，不阻断）。

测试不依赖 DSH 全组件——用最小 Cordis host（SystemPrompt + ToolRegistry + 插件）隔离不稳定面。

### Python 测试约定（必须 `python -m`）

`md_cg/` 等包内测试普遍使用**包内相对导入**，必须以模块方式从**仓库根**运行；直接 `python md_cg/test_xxx.py` 会 ImportError（59/61 踩坑实测）。一键入口已固化该约定（Linux·macOS 上把下面的 `python` 换成 `python3`——发行版默认无 `python`）：

```bash
python -m md_cg.run_tests                    # 全量（md_cg + compiler + swarm，按存在性发现）
python -m md_cg.run_tests md_cg -k p44       # 按组 / 关键字过滤
python -m md_cg.run_tests --jobs 1           # 串行（默认并发 4）
python scripts/run_tests.py                  # 源码树入口（等价；需 scripts/ 在）
```

> **入口在包内**（`md_cg/run_tests.py`）：npm 出货面（`files`）不含 `scripts/`，
> 所以「装出来的插件」里唯一可用的全量入口就是上面那条；`src/` 源码树里
> `scripts/run_tests.py` 与 `npm run gate` 仍可用（发布门禁属源码树工具）。
> 包的 runner 把子进程输出**重定向到文件**（不用管道）：受限宿主（如 DSH 文件
> 沙箱）禁 CreatePipe，用 `capture_output` 的版本会把每个用例都变成
> PermissionError 的假失败。

单测等价写法：`python -m md_cg.test_p44_md_whitebox`（cwd=仓库根）。退出码 0/1 可直接接提交前门禁。

> **两个跨语开关别混**：`MDCG_UNIFY_QUERY`（统一归一层，**默认关**——2026-09-30 使用者
> 裁定由「默认开」翻为「**未设即关、显式 `=1` 才开**」：本层本职是让英文 query 命中中文
> 节点，对中文检索池是纯开销，locomo-zh-500 公开题池实测缺省关态 lexical hit@1 96.4% /
> lexical+fuzzy 97.2%，开态 95.8% / 96.6%；显式开启时任意语言 query 先归一成标准中文
> 原子序列→词法路即可命中中文节点；**2026-09-30 收窄作用域：只对英文内容做翻译归一——
> 中文段逐字保留、绝不送 segment**，中夹英 query 的中文关键词串不再被逐字切开）与
> `MDCG_EN_ATOMS`（英→中召回词扩展，**默认关**）是彼此独立的开关；
> `MDCG_SEMANTIC`（`fm.semantic` 语义摘要路）同样默认关。改其一请同步
> `md_cg/test_en_pipeline.py` 与 `md_cg/test_semantic_canonical.py` 的双态断言；
> 改归一层**缺省/三态**须跑 `md_cg/test_unify_default_off.py`（两侧三态一致 + 定点变异
> 自证），改其**作用域**另须跑 `md_cg/test_unify_scope.py`（与 Rust 侧同源 fixture
> `md_cg/semantic/unify_fixture.json`，见 `docs/hive/检索算法口径对照_v0.1.md`）。

### 编码约定（全 UTF-8 · 命令统一走 python）

**本仓所有文本一律 UTF-8（无 BOM）**——源码、配置、文档、数据、测试夹具，以及**路径与文件名**（含蜂巢任务标识）同此一律。中文可以直接出现在路径里：这不是建议，是约定。

> **给 AI / 接入方的显式声明**：这里是 UTF-8。请把本仓的一切取用走 **python**（`python -X utf8 …`，等价于 `PYTHONUTF8=1`），**不要拿控制台/终端当取用通道**。Windows 控制台按**代码页**去解释收到的字节，会把中文渲染成乱码（实测：`控制台试验` 在代码页 936 的窗口里显示成 `鎺у埗鍙拌瘯楠`）——**那是显示层的问题，不是数据层的问题**，字一个都没丢。我们**不做控制台兼容**：一切读写与判定按 UTF-8 字节，正确性不挂在任何人的代码页设置上。

- **入口自保证**：Python 入口在最早处检查 `sys.flags.utf8_mode`，未开则置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` 并重启自身；不可重启时 fail-fast（不静默降级）。
- **显式优于缺省**：新增代码里 `open()` / `read_text()` 一律显式 `encoding="utf-8"`，不吃 locale 缺省（中文 Windows 上的缺省是 cp936，裸 `open()` 会按它读写）。
- **NFC 口径 = 拒收，不静默归一化**（见[标识契约 v2](docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md) §四.4 / §四.8）：路径与标识**须已是 NFC 稳定形态**才受理——判据 = **区块白名单** `hive/id_charset_blocks.txt`（唯一真源：Rust `include_str!` 编译期嵌入、MCP 与 `md_cg` 读同一份文件，**不查任何运行时的 Unicode 属性表 ⇒ 两侧属性表版本差结构性不可能**）。不在表内的形态**显式拒收**：会归一化改写的形态（CJK 兼容表意 / 全角 / 带圈字母数字 / 数学字母 / 组合标记等），以及**白名单区块之外的其它文种字母数字**（区块选择 = ASCII / 拉丁 / 希腊 / 西里尔 / 假名 / 谚文音节 / CJK 与扩展 / 注音——有意不收的档见契约 §四.4）。不做静默改写（`hive` 侧零依赖手写完整 NFC 不可行；拒收严于静默归一化）。
- **蜂巢任务标识（id 契约 v2）**：`h_<身份>_<任务>_<单元>_<编号>`，例 `h_zcode端_灵枢迭代_反思单元_0001`。四槽之三（身份 / 任务 / 单元）**提交时必填**、不许静默推导；编号由 Rust 侧分配器独占创建给出（4 位定宽，溢出显式报错，不加宽不回绕）；单元槽取蜂巢五单元闭集（记录单元 / 反思单元 / 验证单元 / 输出单元 / 维生系统）。CLI 用 `--identity/--task/--unit`（env 兜底 `HIVE_JOB_IDENTITY/HIVE_JOB_TASK/HIVE_JOB_UNIT`），或 `hive alloc-id` 只取 id；MCP `hive_spawn` 用同名三参数（必填）。旧形态 `h<13位毫秒>_<4位hex>` **仍然合法**（存量零迁移）。
- **平台面**由容器双栈门禁的编码 / locale 守卫覆盖（见下一节）。

### Linux 验证（Docker 容器双栈，0.5.0 起为发版门禁）

```bash
# 栈一：rust + python 全量（cargo test / python 18 套含全部守卫 / smoke 端到端）
docker run --rm -v "$(pwd):/work" -w /work -e CARGO_TARGET_DIR=/tmp/target \
  rust:bookworm bash scripts/linux_verify.sh full
# 栈二：node 生态（发布件 TS 编译 + node test）
docker run --rm -v "$(pwd):/work" -w /work node:22-bookworm bash -c \
  "npm install --include=dev && npm run build && node --import tsx --test test/*.test.ts"
```

> 执行器解释器由 `hive/src/exec.rs` 试跑探测（`python3` 优先、`python` 兜底），故上面两条**照抄即可**、无需再传 `HIVE_PYTHON`；要指定别的解释器才显式设它（显式压倒探测）。Git Bash/MSYS 下须先 `export MSYS_NO_PATHCONV=1`，否则 `/work` 被重写成 `C:/Program Files/Git/work`。
> 平台差异守卫由脚本清单覆盖（编码/locale/session 过滤/SIGTERM 收尾）；依赖 gitignored 本地语料的套件（p44 等）不入容器清单，由 `run_tests.py` 的 SKIP 面在有语料的机器覆盖。

---

## 📏 工程纪律与设计者视角（可选推荐）

> **这段话是什么**：灵枢自身按一套 **17 条工程纪律** 运行——方法论（理论先行 / 全面处理 / 根因纪律）、执行（验证先行 / 双副本同步 / 兜底路径）、执行调度（任务派发统一走蜂巢：执行留痕 / 统一调度面）、合规（内容政策双清单 / 敏感信息隔离）、记忆闭环（查记忆 → 执行 → 写记忆）。它原本是灵枢的「自我约束」，与你要不要用灵枢无关；但如果你希望自己的 Agent 也具备同样的工作方式，这套纪律与配套元技能**都可以直接复用**。

**两个可复用入口**：

| 入口 | 内容 | 位置 |
|---|---|---|
| **工程纪律（18 条）** | 每条 ≡ 一个认知图节点（生效条件 / 执行锚点 / 不适用条件 / 直答出口），含触发词路由 | 真源：[`docs/工作纪律_认知图条目_v1.1.json`](docs/工作纪律_认知图条目_v1.1.json) · 全文投影：[`codebuddy/CODEBUDDY.md`](codebuddy/CODEBUDDY.md)（各端产物见 [多 harness 接入](#多-harness-接入按端分目录)） |
| **设计者视角（元技能）** | 在动手前回答「该不该做 / 为什么做 / 条件够不够」：条件空间声明 → 四态资格裁决（ACCEPT/REJECT/DEFER/BLINDSPOT）→ 失配归因；附自检 17/17 | [`skills/skills/designer-perspective/`](skills/skills/designer-perspective/)（`tests/selftest.py` 可自行验收） |

> **按需裁剪**：17 条中部分条款针对灵枢私有管线（如图像选源线），复用时建议只取方法论 / 执行 / 执行调度 / 合规 / 记忆闭环五组通用条款。多 harness 渲染与防漂移守卫见 [多 harness 接入](#多-harness-接入按端分目录)。

## 护栏宪章（接入即接受约束）

本插件接入即接受 **[灵枢护栏宪章 v2.0-published](docs/mdcg/guardrail-charter.md)** 约束——对外部智能体与人类使用者的行为边界作出公开、可执行、可审计的规定，并保护人类使用者。

## 许可证

MIT © 荣（FuRongJun-1999）· 灵枢 AEIS 工程实现

DeepSeek Harness 为 DeepSeek 官方开源项目（MIT），本插件与之无隶属关系。
