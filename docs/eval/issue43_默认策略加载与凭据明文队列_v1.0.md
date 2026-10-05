# issue #43 默认策略加载与凭据明文队列 · 修复工程报告 v1.0

> 修订：v1.0-r1（2026-09-29，按读者反馈逐条修订；改动记于 §8）。范围：写入策略来源（默认策略
> 加载）+ 其下游「非 ACCEPT/REJECT 出口」把正文（含凭据）明文落 `hippocampus/inbox.jsonl` 的链路。
> 本文只写有机械证据的事。**本文不含任何明文凭据/令牌**：复现所用凭据为合成哑值，一律以
> `mdcg1.<role>.<id>.<secret>` 掩码形态书写。

## 0. 阅读约定（先读这一段）

### 0.1 证据来源标签（全文只有这三种）

| 标签 | 含义 | 可复跑性 |
|---|---|---|
| **本报告亲跑** | 我在本次会话中用所列命令实测过，命令与输出见对应表格 | 可复跑；命令逐条给出 |
| **工作流采集** | 由本修复工作流采集、**本报告未重跑** | 本报告内不可复跑；只给工作流给的字符串 |
| **工作流采集·独立复核** | 独立复核者的结论，来源、装置、命令均由工作流转述 | 本报告内**不可复跑**（装置 `%TEMP%\i43rev` 已删，无命令、无产物） |

### 0.2 三棵树（全文所有行号都标明树）

| 简称 | 是什么 | 怎么得到 |
|---|---|---|
| **HEAD 树** | 修前代码（`git archive HEAD` 导出的整树，`%TEMP%\i43head2_*\tree`） | 只读导出；HEAD 无 `resolve_rulebook`（实测 `hasattr(audit,'resolve_rulebook')` → `False`） |
| **现行树** | 修复后的工作树 `<仓根>` | 本报告 §4.2 的实测均在其上 |
| **工作流树** | 工作流做复现时所用（未由本报告取得） | — |

### 0.3 两个计数单位（不混淆）

- **断言数**：单个测试模块内部 `ok(...)` 的条数。例：新守卫 `md_cg/test_issue43_default_policy.py` 一个模块内 **47 条断言**（`47 通过 / 0 失败`）。
- **模块数**：`scripts/run_tests.py` 的最小计入单位是**测试文件（模块）**，每个模块一条 `PASS/FAIL` 行；其汇总行代码为
  `print(f"\n===== SUMMARY {len(runnable) - len(bad)}/{len(runnable)} 通过，{len(skipped)} 跳过…")`（`scripts/run_tests.py` 汇总段）。
  故 `191/191` = md_cg 组 191 个模块通过；`258/258` = 全量 258 个模块通过（本报告实测该日志中 `PASS` 行 258 条、`SKIP` 5 条、`FAIL` 0 条）。
  **一个含 47 条断言的新文件对模块数只贡献 +1**（190→191，257→258），两个量纲不可直接比较。

### 0.4 rc 的参照对象（每条 rc 都写明是哪个进程）

- `rc=<N>`（server）：`python -X utf8 -m md_cg.mcp_server` **进程自身**的退出码。
- `rc=<N>`（probe）：探针脚本（`python -X utf8 -c <code>`）的退出码；写链探针**成功跑完即 0**，与写入被拒/入队无关。
- `rc=<N>`（guard/suite）：`python -X utf8 -m md_cg.test_issue43_default_policy` / `python -X utf8 scripts/run_tests.py` 的退出码（0 = 全绿）。

---

| 项 | 值 |
|---|---|
| 缺陷 | 策略「未配置」被静默折叠成空规则库 → `text` 恒 `DEFER` → 正文（含凭据）**明文**入审核队列且不脱敏 |
| 真实站点（修前＝HEAD 树行号） | `md_cg/audit.py:64-74`（`load_rulebook` 无默认回落）→ `:98-99`（空规则 → DEFER）→ `md_cg/writepipe.py:235`（DEFER 走 `cg.propose`）→ `md_cg/mdcos.py:1781-1792`（`rec["content"] = content` + `append_jsonl`） |
| 修复面 | 9 个既有文件（audit / writepipe / mcp_server / package.json / README + 4 个既有测试）+ 1 个新守卫模块 |
| 写入面判定（**本报告亲跑 3 项** + **工作流采集 2 项**） | 修复成立：合法输入逐位一致（工作流采集）、守卫 47/47（亲跑）、8 处定点变异恰好命中（亲跑）、python 全量 258/258 模块（亲跑）、容器两栈 rc=0（工作流采集，**本报告未跑**） |
| **总判定（工作流采集·独立复核）** | **DEFER** —— 本 issue 的写入面已修好，但本轮**引入**「策略键为标量时」的新缺陷：启动面崩（server rc=1）+ 写入面退回 `DEFER → review_queue` 明文入队（见 §5.2，**本报告亲跑**），故不判通过 |

---

## 1. 缺陷定义与真实站点

### 1.1 缺陷定义

修前 `MDCG_POLICY_FILE` 未设时，`load_rulebook()` 返回 `{}`（空规则库），**没有任何默认回落**。
空规则库在 `_rule_check` 里被判 `DEFER`（「无规则不能假装合规」——这个判断本身是对的），
但写入闸门把 `DEFER` 归入「非 ACCEPT/REJECT 出口」→ `cg.propose` → 正文**逐字**进
`hippocampus/inbox.jsonl`；而脱敏（`redact_forbidden`）**只在 REJECT 分支**执行。

于是后果不是「少一条规则」，而是**安全面翻转**：那些在**有规则时**会被禁表拦下的凭据没被拦，
原样进了审核队列落盘。措辞精确化（读者反馈）：修前**并不存在任何生效的规则表**——修前既没有
包内默认回落、`MDCG_POLICY_FILE` 也未设，所以「禁表命中」这一说法描述的是**修复后的默认策略
（包内 `data/policy.json` 的 11 条 forbidden，清单见 §4.3）本该拦下的形态**，不是修前已加载的规则。
修前的实证形态就是「凭据原样入 `inbox.jsonl`」（§2 腿3、§4.2）。

### 1.2 三条独立成因（任一成立即足以成病）

1. **实现面无回落**：`load_rulebook` 只认 env，未设即 `{}`，且坏路径也静默 `{}`（不 fail-closed）。
   - HEAD 树 `md_cg/audit.py:66` `path = path or os.environ.get("MDCG_POLICY_FILE")`
   - HEAD 树 `md_cg/audit.py:67-68` `if not path or not os.path.exists(path): return {}`
   - HEAD 树 `md_cg/audit.py:72-73` `except (OSError, ValueError): return {}`（目录不可读、非法 JSON 一并吞掉）
   - HEAD 树 `md_cg/audit.py:74` `return rules if isinstance(rules, dict) else {}`
2. **发布面拿不到默认策略**：`package.json` 的 `files` 不含 `data`，`lingshu-init` 也不生成该 env
   ——「默认 `data/policy.json`」对默认安装的用户不成立。
3. **「未配置」与「不可用」同码**：两种完全不同的处境折叠成同一个 `{}`，坏路径静默降级、
   无任何可观测面报出「你的策略从哪来」。

### 1.3 病态出口的落点（现行树行号）

- 空规则 → `DEFER`：`md_cg/audit.py:197-198`
- 未知 `content_kind` → `BLINDSPOT`（同样走非 ACCEPT/REJECT 出口）：`md_cg/audit.py:462-463`
- 非 ACCEPT/REJECT 出口：`md_cg/writepipe.py:252-256`（`cg.propose(...)`，响应 `moved_to: "review_queue"`）
- 明文落点：`md_cg/mdcos.py:1781-1792`（`rec = {... "content": content ...}`；`:1792` `append_jsonl(self.inbox_log, rec)`）

---

## 2. 修前现场（复现腿）

> 来源：本修复工作流采集的 8 条复现腿（`reproduced: true`）。「本报告复跑」列写明**跑在哪棵树**、
> 用什么形态；`—` 表示本报告未重跑。
> **字节数不可跨树直接对比**（读者反馈第5条）：同一 TEXT 字面在 HEAD 树上重复跑两次即得
> 468 / 469 两种字节数——抖动来自 `t`（`time.time()` 浮点 repr）长度，实测 `t_repr` 为
> `1790649083.657689`（16 字符，468B）与 `1790649083.7671993`（17 字符，469B），其余字段相同。
> 故「字节数差」必须按**同树同字面**比较，§4.2 已按此口径重测。

| 腿 | payload | 观察 | 崩溃点 | 本报告复跑 |
|---|---|---|---|---|
| 腿1 构造期装载 | pop 掉 env 后调 `load_rulebook()` / `_rule_check(TEXT, {}, 'text')` / `audit.audit('text', …)`；另跑 cwd=仓库根做对照 | 无异常。`load_rulebook() == {}`；`_rule_check -> DEFER evidence='未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定'`；`audit()` 同。cwd 下就有 `data/policy.json`（exists=True）时仍为 `{}` —— 既无包根回落也无 cwd 相对默认 | 无异常（**静默**，病根） | ✅ **HEAD 树**：`load_rulebook {}`、`('DEFER', '未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定', None)`、`resolve_rulebook` 不存在 |
| 腿2 发布面 | `npm.cmd pack --dry-run --json --ignore-scripts`；另读 `package.json` 的 `files` | RC=0，清单 1457 条；`data/*` 条目 `[]`；`policy.json present = False`；`files` 不含 `'data'` | 无异常 | —（只读现行树 `package.json:19-30`：修后 `files` 含 `"data/policy.json"`@`:23`） |
| 腿3 默认写入链 | `install_default_gates(WritePipeline())` + `{'content_kind':'text','content':TEXT,'layer':'knowledge'}`；env 未设；随后**二进制**读 `inbox.jsonl` 反查 | 无异常。`committed=False` `ok=True` `moved_to='review_queue'` `state=DEFER`；`inbox.jsonl` **490 字节**，原始字节同时命中合成凭据与明文标记；`rec` 含 `content` 键、值为**原文逐字**，`sensitivity='internal'` | 无异常 | ✅ **HEAD 树**：`moved_to=review_queue / DEFER`，`inbox.jsonl` 468/469 字节（同字面重复跑两次），凭据与标记字节面**双命中**，`content` 与原文逐字相等 |
| 腿3b 对照（显式指向真源 policy） | 同一写入 + `MDCG_POLICY_FILE=<仓库>/data/policy.json`（只读引用） | `moved_to='rejected'`、`state=REJECT`（`命中禁止规则：mdcg1\.[A-Za-z0-9._\-]{20,}`）；`inbox.jsonl` 不存在；负记忆 `rejected/rej_*.md` 中凭据已被替换为占位符、非凭据标记保留 —— **脱敏只在 REJECT 分支** | 无异常 | ✅ **现行树 + env 未设**（等价档，因现行树未设 env 即加载包内默认）：`moved_to=rejected`、全库凭据字节命中 `0`、负记忆含 `[已过滤:` 占位符 |
| 腿4 显式坏路径 | env 依次指向 ① 不存在路径 ② 目录 ③ 非法 JSON ④ 合法 JSON 但顶层非对象 | 四形态全部 `load_rulebook() == {}`、`_rule_check -> DEFER`；**无异常、无 stderr、不 fail-closed**。不可读分支取证：`open(<目录>)` 抛 `PermissionError`（属 `OSError`），被 `except` 吞掉后仍 `{}` | 异常被吞（HEAD 树 `audit.py:72-73`） | ✅ 同四形态在**现行树**实测（§4.2）已转结构化不可用 |
| 腿4b 坏路径下的写入 | env 指向非法 JSON + 同一写入 | `moved_to='review_queue'` `state=DEFER`；`inbox.jsonl` **490 字节**，凭据与标记均命中 | 无异常 | ✅ **现行树**：`moved_to=policy_unavailable`、落盘仅 `_keys.json`/`.lock`、凭据字节命中 `0`（§4.2） |
| 腿5 `content_kind` 省略 | 同一写入，未传 `content_kind` | `moved_to='review_queue'` `state=BLINDSPOT`（`未知内容类型：''`）；`inbox.jsonl` **460 字节**，凭据与标记均命中 | 无异常 | ✅ **现行树 + 显式空策略 `{}`**（见 §6.3-1 的实验设计与依据）：`BLINDSPOT` → `review_queue`，468/469 字节、凭据字节命中 `True` |
| 腿6 三处不符 | 读 `package.json` / `src/init.ts` env 块 / `README.md`；`git grep` 全仓 `MDCG_POLICY_FILE` 与 `--show-config`；实跑 `python -m md_cg.mcp_server` 抓 stderr | ① `files` 无 `data`；② `src/init.ts:134-141` 只写 `MDCG_ROOT/MDCG_PYTHON/MDCG_MCP_SURFACE/MDCG_ACTOR/MDCG_TENANT/MDCG_CLEARANCE/MDCG_TOKEN`，全文件 `MDCG_POLICY_FILE` 零命中；③ `README.md:131-132`、`:159` 把「默认 `data/policy.json`」写成既成事实；④ **启动 stderr 全量共 3 行**（不是「前三行」也不是「相邻三行」，工作流原话即「stderr 全量三行」），`policy/POLICY/规则库/规则` 四个关键词在该次 **stdout+stderr 全体**中命中均为 `False`；全仓 `--show-config` 只在 `hive/serve_start.py:658` 与 hive 文档 | 无异常（**不可观测**） | ✅ **HEAD 树**（本报告亲跑复现该行，命令与输出见 §4.2 #6）：`server rc=0`、stderr 恰 3 行、`policy/POLICY/规则库/规则` 四关键词在所有输出中零命中 |
| 腿7 迁移面 | env 指向真源 policy 后复跑既有断言；另用临时空策略 `{}` 做保原口径对照 | 基线 7 模块全绿。翻转：`test_writepipe.py:97-105`「DEFER 入队」成立→**False**；`test_linkref.py:242-249` 同样 True→False；`test_mr_m2.py:350-358` C4b 测试体内 `pop` env 期望 `review_queue`，修复后 pop ≠ 空规则库，必须显式改指。保原口径可行：`{}` 时三场景仍 `review_queue/DEFER`（evidence 与 unset 档逐字一致） | 无崩溃（**断言翻转**） | ✅ **现行树**读码：`test_writepipe.py:97-108`、`test_linkref.py:48-54`、`test_mr_m2.py:351-361`、`test_p2_mcp.py:260-271` 四处已按语义迁移 |
| 腿8 自证 | 全部库根/策略文件建在 `tempfile.mkdtemp`；末了比对 `gettempdir()` 前缀、walk 落盘清单、`git status --porcelain`、`data/policy.json` 对 HEAD 的 sha256 | `UNDER_SYSTEM_TEMP = True`；6 个临时根均在系统 temp；`git status --porcelain` 与会话起始快照逐字一致；`data/policy.json` 磁盘 sha256 = HEAD sha256；未 `git add/commit/push`。**两处足迹**：① `npm pack --dry-run` 触发 `package.json:87` 的 `prepare` 脚本重建 gitignored 的 `lib/`（13 文件 mtime 刷新，随后改用 `--ignore-scripts`）；② 启动探针刷新本机默认 aux 根的 `sustain/heartbeat.md_cg.stamp`（无法剔除本机常驻 mcp 进程自刷的可能） | 无 | ✅ 本报告侧：所有探针根均在 `%TEMP%\i43*`，`MDCG_ROOT` 全程为临时目录 |

---

## 3. 修法契约与落点

### 3.1 契约分层（回应读者反馈第1条）

先定义术语：**「生效条件注释」= 本仓公开函数上方那一行 `# 生效条件：…` 注释**，是这个代码库
既有的**函数级契约声明**惯例（每个公开函数一条，写在 `def` 行**上一行**；例：现行树
`md_cg/audit.py:55`、`:81`、`:87`、`:93`、`:112`、`:142`、`:164` 各一条）。它声明的是**该函数在
任何输入下都成立的行为**（含「恒不抛异常」这类总括断言），不是「只在某个前置成立时才成立」的
条件式描述。本文 §3.1 因此把契约分两层，两层**都**是「本轮修复声明成立」的东西：

| 层 | 内容 | 本轮状态 |
|---|---|---|
| **C1-C4（本次修复的核心契约，硬契约）** | 来源单点 / 未设回落包内默认 / 显式坏路径不掩蔽 / 不可用则在提案前 fail-closed | **成立**（§4.2 实测） |
| **补充契约（生效条件注释已声明的既有行为）** | `resolve_rulebook` 恒不抛、`load_rulebook` 不可用仍返 `{}` 不抛、`policy_report()` 六键恒不抛 | **C1-C4 成立，但「恒不抛」被本轮新缺陷打破**：标量键策略下 `policy_report()` 抛 `TypeError`（§5.2），违反其生效条件注释（现行树 `md_cg/audit.py:142` 明文写「恒不抛异常」）。故 §5.2 属**违约**（生效条件注释被违反），不是「边界内的正常降级」。 |

因此读者反馈里「两种读法结论相反」的问题有确定答案：**§3.1 的补充契约是本轮修复自身声明成立的行为，
`policy_report()` 的崩是违约**。§6.1 原先写的「应先定契约再落码」措辞不当（契约已在
`audit.py:142` 声明），已改为「先补齐声明契约的行为，再谈收口」，见 §6.1。

### 3.2 核心契约（硬契约）

| # | 契约 | 落点 |
|---|---|---|
| C1 **来源单点** | 来源判定（env / 包内默认 / 不可用）只有一处实现——闸门、自描述面、守卫读同一个函数 | `md_cg/audit.py:113-139` `resolve_rulebook()` |
| C2 **未设/空串 → 回落包内默认** | 包根由 `__file__` 反推，**不依赖 cwd**；env 为空串与未设同路 | `md_cg/audit.py:82-90`、`:125-139` |
| C3 **显式坏路径不得被默认掩蔽** | env（或显式 path）给了就按它算；不可用即返回结构化 error，**不回落包内默认** | `md_cg/audit.py:127-132` |
| C4 **不可用 → 提案入队前 fail-closed** | 返回 `ok=False / moved_to="policy_unavailable"` + 结构化 error，**不进 audit、不 propose、不落任何节点，响应体不含正文** | `md_cg/writepipe.py:210-217`；错误码枚举 `md_cg/audit.py:94-109`（`policy_not_found / policy_unreadable / policy_invalid_json / policy_not_object`） |

### 3.3 落点清单（现行树行号）

| 文件:行 | 改动 |
|---|---|
| `md_cg/audit.py:63-78` | 新增 `POLICY_ENV` / `DEFAULT_POLICY_REL=("data","policy.json")` / `POLICY_HINT` |
| `md_cg/audit.py:82-90` | 新增 `package_root()` / `default_policy_path()` |
| `md_cg/audit.py:94-109` | 新增 `_read_policy_file()`：读单文件 → `(rules\|None, (错误码, 原因)\|None)` |
| `md_cg/audit.py:113-139` | 新增 `resolve_rulebook()`：来源解析单点，恒不抛 |
| `md_cg/audit.py:143-161` | 新增 `policy_report()`：来源自描述单点（`source/path/available/forbidden/required/error`） |
| `md_cg/audit.py:165-173` | `load_rulebook()` 改为委托 `resolve_rulebook`（不再自行读 env） |
| `md_cg/writepipe.py:197-217` | `_gate_audit` 前置策略可用性闸（C4）；规则经 `ctx["rules"]` 下传验证器（`:226-232`） |
| `md_cg/mcp_server.py:3771-3786` | 新增 `_policy_stderr_note(rep)`：启动 stderr 策略来源单行（内容单点，便于定点变异） |
| `md_cg/mcp_server.py:3790-3801` | 新增 `_show_config()`：只读诊断面，不解析 root、不建 cg、不落盘 |
| `md_cg/mcp_server.py:3807-3808`、`:3907` | `--show-config` 分派（先于 root 解析）；`main()` 启动写策略 stderr 行 |
| `md_cg/mcp_server.py:2143` | `cg(op=info)` 返回体新增 `write_policy` |
| `package.json:23` | `files` 新增 `"data/policy.json"` |
| `README.md:131`、`:132`、`:159` | 三处文档对齐：默认策略随包发布、env 覆盖、不可用 fail-closed 不进队列、来源三处可查 |
| `md_cg/test_linkref.py:48-54`、`:249`；`md_cg/test_writepipe.py:97-108`；`md_cg/test_p2_mcp.py:260-271` | 三处「DEFER 出口」用例改为**显式设空规则库**，保持原断言口径（断言一字未改） |
| `md_cg/test_mr_m2.py:351-361` | C4b 按语义更新为「策略不可用 → fail-closed」，并 monkeypatch 包内默认路径使其真触发 |
| `md_cg/test_issue43_default_policy.py`（571 行） | 新守卫 G1-G7 共 47 条断言 + 8 处定点变异自证；锚点漂移报 `ANCHOR-MISS`、退出码 2 |

**本轮未触及的面（明确排除）**：§3.3 无一条改动 `DEFER`/`BLINDSPOT` 出口的脱敏或落盘行为——
即「非 ACCEPT/REJECT 出口仍原样 `cg.propose` → 明文入 `inbox.jsonl`」这一事实**未被本轮修改**，
只被**收窄了触发面**（策略不可用时不再走该出口）。见 §6.1。

### 3.4 可观测面（契约④「不得静默」）

三处共用同一个 `policy_report()`，无第二套口径：启动 stderr（`mcp_server.py:3907`）、
`python -m md_cg.mcp_server --show-config`（`:3790-3801`）、`cg(op=info).write_policy`（`:2143`）。

---

## 4. 验证数字

### 4.1 门禁数字（含来源标注与量纲）

| 项 | 命令 | 结果 | 量纲 | 来源 |
|---|---|---|---|---|
| 守卫正向 | `python -X utf8 -m md_cg.test_issue43_default_policy` | 47 通过 / 0 失败，rc=0（G1=6 G2=3 G3=6 G4=9 G5=6 G6=8 G7=9） | **断言数**（单模块内） | **本报告亲跑** |
| 变异自证 | 同命令加 `--mutation-baseline` | 未变异基线红项 0；M1 13/13、M2 3/3、M3 6/6、M4 9/9、M5 12/12、M6 2/2、M7 5/5、M8 1/1，rc=0 | 断言数 | **本报告亲跑** |
| 删断言探针 | `probe_drop_group.py`（仅内存改 `T._GROUPS`，文件未动） | 摘掉 g1 → M1 红 7/13、M5 红 7/12 与声明不符、返回 1；摘掉 g5 → M1 红 10/13、M5 红 6/12、返回 1 | 断言数 | 工作流采集（**未重跑**） |
| python 全量 | `python -X utf8 scripts/run_tests.py --jobs 4` | `SUMMARY 258/258 通过，5 跳过`，进程 exit code **0**（日志内 `PASS` 258 行、`SKIP` 5 行、`FAIL` 0 行） | **模块数** | **本报告亲跑** |
| 目标套件 | `python -X utf8 scripts/run_tests.py md_cg --jobs 4` | 191/191 通过，3 跳过，rc=0（改动前基线 190/190，**+1 个模块** = 新守卫） | **模块数** | 工作流采集（**未重跑**） |
| 只读门禁 | `check_unreachable.py` / `workspace_index.py --check` / `link_check.py` | 475 文件命中 0 rc=0 / OK rc=0 / OK=228 BROKEN=0 rc=0 | — | 工作流采集（**未重跑**） |
| 容器栈一 | `docker … scripts/linux_verify.sh`（含 `smoke_test (linux)`） | 退出码 **0**；`结果: 21 pass / 0 fail`；`[PASS] smoke_test (linux)`；`汇总: 38 pass / 0 fail` | 脚本内记录项数 | 工作流采集（**本报告未跑**） |
| 容器栈二 | node 侧容器测试栈 | 退出码 **0**；`# cancelled 0`、`# skipped 3`、`# todo 0`、`# duration_ms 5308.138373` | node 测试项数 | 工作流采集（**本报告未跑**） |

**未跑原因（容器两栈）**：本机存在 `python:3.12` / `rust:bookworm` / `node:22-*` 镜像（`docker images` 列表实测），
但重跑 `scripts/linux_verify.sh`、`scripts/newuser_sim.sh` 会向仓库写入构建产物（`target/`、`lib/`、`node_modules`），
超出本次「只改报告文件，不得动源码」的硬边界，故只转述工作流数字。

### 4.2 本报告亲跑的复现（每条含命令与 rc 参照对象）

| # | 命令（要点） | 树 | 结果 |
|---|---|---|---|
| 1 | `python -X utf8 -c "from md_cg import audit; print(audit.load_rulebook(), audit._rule_check('正文',{}, 'text'), hasattr(audit,'resolve_rulebook'))"`（cwd=HEAD 树，env 未设） | **HEAD** | `{}` / `('DEFER','未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定',None)` / `False`；**无异常** |
| 2 | 写链探针（`MdCGSecure(<临时root>)` + `install_default_gates(WritePipeline())` + `{'content_kind':'text', content:TEXT}`），随后二进制读 `inbox.jsonl` | **HEAD** | probe rc=0；`moved_to=review_queue`、`state=DEFER`；`inbox.jsonl` 468 与 469 字节（同字面跑两次）；凭据与标记**字节面双命中**；`content` 与原文逐字相等 |
| 3 | 同 #2，**env 未设** | 现行 | probe rc=0；`moved_to=rejected`、`state=REJECT`；`inbox.jsonl` 不存在；全库扫描凭据字节命中 `0`；负记忆含 `[已过滤:` 占位符 |
| 4 | 同 #2，`MDCG_POLICY_FILE=<非法 JSON 文件>` | 现行 | probe rc=0；`moved_to=policy_unavailable`、`state=None`；落盘文件仅 `_keys.json` / `_keys.json.lock`；凭据字节命中 `0` |
| 5 | `python -X utf8 -m md_cg.mcp_server`（临时 root + 临时 aux + 真签发令牌，stdin 送 EOF） | 现行，env 未设 | **server rc=0**；stderr `[mdcg-mcp] 写入策略：来源=package_default path=<仓根>\data\policy.json（forbidden=11 required=6）` |
| 6 | 同 #5 | **HEAD**，env 未设 | **server rc=0**；**stderr 恰 3 行**（路径 / 自报 / 自报文件）；`policy`、`POLICY`、`规则库`、`规则`、`策略` 五关键词在 stdout+stderr 全体中命中均 `False` |
| 7 | 同 #5 + `MDCG_POLICY_FILE={"forbidden": 1}` | 现行 | **server rc=1**；stderr 末行 `TypeError: 'int' object is not iterable`（`mcp_server.py:3907` → `audit.py:157`）；策略行**未打印** |
| 8 | 同 #7 换 `{"required": true}` 走 `python -X utf8 -m md_cg.mcp_server --show-config` | 现行 | **rc=1**、stdout 空；traceback `mcp_server.py:3799 → audit.py:159`（`'bool' object is not iterable`） |
| 9 | 同 #2 + `MDCG_POLICY_FILE={"forbidden": 1}` / `{"required": true}`（各一次） | 现行 | probe rc=0（两次）；`moved_to=review_queue`、`state=DEFER`、`evidence='验证器异常：TypeError: 'int'/'bool' object is not iterable'`；`inbox.jsonl` 均 469 字节、`content` 与原文**逐字相等**、凭据与标记字节面双命中 |
| 10 | 同 #2 + `MDCG_POLICY_FILE={"forbidden": "sk-…（哑值，23 字符）"}` | 现行 | probe rc=0；`policy_report()` **不抛**，但报 `forbidden=23`（把字符串长度当规则数）；写入侧以**单字符规则**判定，`evidence='命中禁止规则：s'` → `REJECT`、`inbox` 不存在（详见 §5.2 末） |
| 11 | 读 `data/policy.json` 计数 | 现行 | `forbidden` 11 条、`required` 6 条、`required_kinds=['text']`（清单见 §4.3） |

### 4.3 包内默认策略的实际内容（回应读者反馈第8条）

`data/policy.json` 顶层键：`_comment`、`_note`、`forbidden`、`required`、`required_kinds`、`required_labels`。
下表逐条列出**文件内实际存在的**模式（本报告用 `json.load` 读出后原样转写），故读者判断
「默认策略上线后会不会拒掉自己的正文」**不必再打开该文件**；模式之外的设计口径随记在 `_note` 里
（该文件自述：只放高精度模式、宁可漏报不误伤；`tk_[0-9a-f]{8,}` 是灵枢令牌 id 形态，
且该模式不误伤 `tk_fake`/`tk_zzzz` 一类非 hex 哑值）：

**forbidden（11 条，任意 `content_kind`，命中即 REJECT）**

| # | 模式 |
|---|---|
| 1 | `-----BEGIN [A-Z ]*PRIVATE KEY-----` |
| 2 | `\bsk-[A-Za-z0-9_\-]{20,}` |
| 3 | `\bAKIA[0-9A-Z]{16}\b` |
| 4 | `\bgh[pousr]_[A-Za-z0-9]{20,}\b` |
| 5 | `(?i)\bapi[_-]?key\s*[:=]\s*[A-Za-z0-9_\-]{16,}` |
| 6 | `(?i)\b(app[_-]?secret|appsecret|client[_-]?secret|secret[_-]?key|access[_-]?key)\s*[:=]?\s*[A-Za-z0-9]{16,}` |
| 7 | `(?i)\b(password|passwd|pwd|密码|口令)\s*[:=：]\s*\S{6,}` |
| 8 | `(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}` |
| 9 | `[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@` |
| 10 | `\btk_[0-9a-f]{8,}\b` |
| 11 | `mdcg1\.[A-Za-z0-9._\-]{20,}` |

**required（6 条，`required_kinds=['text']` 收窄，缺失即 REJECT；`required_labels` 为报错展示名）**

| # | 模式 | label |
|---|---|---|
| 1 | `(?m)^#\s*功能名` | 功能名 |
| 2 | `(?m)^#\s*生效条件` | 生效条件 |
| 3 | `(?m)^#\s*子功能` | 子功能 |
| 4 | `(?m)^#\s*执行` | 执行 |
| 5 | `(?m)^#\s*验证方式` | 验证方式 |
| 6 | `(?m)^#\s*不适用条件` | 不适用条件 |

即**「CCG 六要素」= 上表 6 个 `# 要素名` 行**（形态口径：`^#\s*<要素名>` 不要求冒号；
二级标题 `## <要素名>` 与缩进形态同判不认——`_note` 已声明该边界）。工程含义：
`text` 类写入若不带这 6 行，默认策略上线后会由修前的「DEFER 入队」变为 **REJECT**（记入负记忆）。
部署影响见 §7-Q3。

---

## 5. 独立复核判定与它列出的 uncovered

### 5.1 判定与来源（回应读者反馈第5条 unsupported）

**独立复核结论 = DEFER。** 来源标签：**工作流采集·独立复核**——本报告只拿到工作流转述的装置描述
（全部在 `%TEMP%\i43rev`，跑完已删；修前 = `git archive HEAD` 整树 2058 文件；现行 = 工作树；
隔离：`MDCG_AUX_ROOT/STATE/DATA` 指向临时目录；跑前后对在役 aux 根 `本机 aux 根（~/.mdcg）` 快照，
9 文件零增/零删/零改）。**本报告无法复跑该复核**：没有可执行的复核命令、没有留下产物、装置目录已删；
仅有转述文字。故 §5.1 的「PASS/PASS/PASS」三条与 §5.2 的判定归属均按此标签计——**未由本报告验证**。

复核认可的部分（三条 PASS，本报告在 §4.2 对**写入面与守卫面**做了同口径复跑，结论一致）：

1. **各腿不崩 + 退化/容错路径真的发生**（修前 5 条分支腿 + valid 共 24 次运行无异常；判据用独立
   `os.walk` 文件系统扫描而非只看响应；含正对照 `unset+code → ACCEPT` 证明扫描有判别力）。
2. **合法输入逐位一致**（HEAD vs 现行，4 条腿响应体逐字段一致、落盘文件集同集且逐字节一致，
   仅掩码时间戳/session/pid/iid/密钥 nonce 等易变字段）。
3. **守卫本体与变异自证**（47/47、8 处变异恰好命中、删断言探针返回 1）。

### 5.2 它列出的 uncovered（本轮修复**新引入**的缺陷；本报告已逐条亲跑确认）

前提：策略文件是**合法 JSON 对象**，但 `forbidden`/`required` 的值是标量（`1` / `true`）。

| # | uncovered | 本报告亲跑结果（命令见 §4.2 #7/#8/#9） |
|---|---|---|
| (a) | `audit.policy_report()` 抛 `TypeError`（`md_cg/audit.py:156-161` 对取值无类型闸） | ✅ `{"forbidden": 1}` → `audit.py:157` `TypeError: 'int' object is not iterable`；`{"required": true}` → `audit.py:159` `'bool' object is not iterable` |
| (b) | 启动面崩：`mcp_server.py:3907` 的 `policy_report()` 调用不在任何 try 内 | ✅ **server rc=1**（真进程、临时 root/aux + 真签发令牌），stderr 末行 `TypeError`，策略行未打印 |
| (c) | `--show-config` rc=1、无 JSON 输出，与其 docstring「恒退出 0、不可用时 `available=false`」（`mcp_server.py:3789`）相反 | ✅ rc=1、stdout 空、traceback |
| (d) | 守卫盲区：G4 只测「顶层非对象」，**未测键类型为标量** | ✅ 读码确认：`md_cg/test_issue43_default_policy.py:242-272`（G4 组）覆盖 `policy_not_found/invalid_json/not_object/unreadable/空 dict`，**无键类型用例**；故该缺陷对 47 条断言全绿无感 |

### 5.3 对复核「边界说明」的一处纠正（本报告实测）

复核原文：**「写入路径不受该缺陷影响——两侧同为 DEFER→inbox，且修前根本不调用 `policy_report`，
故属启动/诊断面回归，不是写入语义回归。」**

结论方向（本轮新引入的缺陷）成立，但「写入路径不受影响」的措辞会掩盖事实：
**标量键策略下的写入侧也已退化，且退化的正是本 issue §1 的病态出口。**
机制：`_rule_check` 对 `(rules.get("forbidden") or [])` 的标量取值迭代时抛 `TypeError`，
被 `md_cg/audit.py:467-470` 的验证器兜底 `except Exception → DEFER` 吞掉（`_verdict(DEFER, kind,
f"验证器异常：…")`），于是 `moved_to=review_queue`、正文逐字（含凭据）落 `inbox.jsonl`。
本报告实测（§4.2 #9）：`{"forbidden": 1}` 与 `{"required": true}` 各 469 字节、`content` 与原文
逐字相等、凭据与标记字节面双命中。即**部署方只要写出一个「合法 JSON 对象但键为标量」的策略文件，
启动面与写入面同时失去防护**，而不是仅丢诊断面。

**字符串键不是同一回事（本报告实测，回应读者反馈 unsupported 第4条）**：
`{"forbidden": "sk-…（23 字符哑值）"}` 因可迭代**不抛** `TypeError`，但静默退化为「按字符逐条建规则」：
`policy_report()` 报 `forbidden=23`（把字符串长度当规则数），写入侧以单字符规则判定，
实测 `evidence='命中禁止规则：s'` → `REJECT`（即误伤式判定，而非「不触发本缺陷」的豁免）。
故该形态的问题从「抛异常」变成「静默错判 + 计数失真」，同样需要键类型闸。

---

## 6. 边界与未覆盖

### 6.1 本轮明确不修、留池的面

| 留池面 | 现状（本报告实测/读码） | 为何留池 |
|---|---|---|
| **策略键类型闸**（`forbidden`/`required` 非列表） | `md_cg/audit.py:157-160` 列表推导对取值无类型闸 → §5.2 (a)(b)(c)；写入侧 `_rule_check` 同抛 `TypeError` 被 `audit.py:467-470` 吞成 `DEFER` → 明文入队（§4.2 #9）；字符串键 → 计数失真 + 单字符误判（§5.3） | 属独立面（键类型校验），与「默认策略加载」根因不同。**因它同时波及启动面与写入面，修它时应同时覆盖 `policy_report()` 与 `_rule_check()` 两处键类型闸，并补守卫（G4 现无此用例）**——即先补齐 §3.1 已声明契约（「恒不抛」）的实际行为，再谈本 issue 收口 |
| **非 ACCEPT/REJECT 出口的脱敏**（本 issue 的病态出口本体） | `md_cg/writepipe.py:252-256` 仍原样 `cg.propose`；`md_cg/mdcos.py:1781-1792` 仍逐字落 `inbox.jsonl`。本轮**未改**该出口的落盘/脱敏逻辑（§3.3 无一条落点触及），只**收窄了触发面** | 收窄触发面（不可用 → fail-closed）已消除本 issue 的**默认**触发路径；是否给 `inbox.jsonl` 也做脱敏（或改为密文/封套）是**新的语义决策**（脱敏会削弱审核者看到原文的能力），须单独立项 |
| **显式空策略 `{}` 的残留通路** | 空 dict 是**可用**策略（`audit.py:93`/`:105` 契约），此时 `text` → `DEFER`、省略 `content_kind` → `BLINDSPOT`，两者仍 → `review_queue` → `inbox.jsonl` 逐字明文（§4.2 #9 同形；§6.3-1 实测设计） | 「无规则不能假装合规」是既有契约，空策略是**部署方的显式选择**（与修前「静默空白」不同），本轮不改其语义；但它是明文入队的残留通路，须在文档/运维面提示（见 §7-Q1） |
| `policy_report()` 三处调用无 try 包裹 | `mcp_server.py:3907`（启动，不在 try 内）、`:3799`（`_show_config`）、`:2143`（`op=info`，标量键下被 `_serve_line` 宽 except 兜成 `-32603`，但该场景下 server 已在启动期崩，实际到不了） | 随类型闸一并收口；「诊断面不得因策略畸形而拒绝启动/应答」的先定契约已在 §3.1 建立 |
| `_show_config` docstring 与实现的落差 | `mcp_server.py:3789` 写「恒退出 0」，标量键下实测 rc=1 | 随类型闸一并收口 |
| 守卫 G4 的键类型盲区 | `test_issue43_default_policy.py:242-272` 无键类型用例 | 随类型闸补断言 |
| `hive/serve_start.py:658` 的同名 `--show-config` 与 `md_cg.mcp_server --show-config` 是否需统一口径 | 全仓 `--show-config` 现出现在 hive 与其文档、`md_cg/mcp_server.py:3807`、`README.md:131` | 跨模块命名/语义统一不是本 issue 范围 |
| `src/init.ts:134-141` 不生成 `MDCG_POLICY_FILE` | 读码确认该 env 块无此项；README/init 文案未就此对齐 | **本报告无证据判断是否有意**（读码只能证明「缺席」，不能证明「有意」；未找到设计说明/注释/提交记录支撑）。故按事实陈述为「缺席且未在文档对齐」，**不断言动机**；是否补 env 由发布决策定 |

### 6.2 本报告未覆盖 / 未验证

- **容器两栈、目标套件 191/191、只读门禁三件、删断言探针**：均未由本报告重跑（§4.1 已逐行标注来源与未跑原因）。
- **`npm pack` 发布面**未由本报告重跑；只读 `package.json:19-30` 确认 `files` 含 `"data/policy.json"`@`:23`。
- **独立复核**（§5.1）：无可复跑命令与产物，未由本报告验证。
- **HEAD 树的 `-m md_cg` 探针**：本报告的 HEAD 探针均以 `cwd=导出树` + `PYTHONPATH=导出树` 运行；
  早期一次误将 cwd 留在仓库根，导致导入到现行树（已作废重跑，结论表内数字均来自 cwd=导出树 的运行）。
- **工作流腿3/腿5 的 490/460 字节**：其 TEXT 字面未由本报告取得，**两者差 30 字节的归因（是否同字面）
  本报告无法核对**，故不采信「仅因 TEXT 字面差异」的因果说法（见 §6.3-3）。

### 6.3 语义边界（真源驱动）

1. **显式空策略 `{}` 是「可用」策略**（`audit.py:93`/`:105`）。实验设计（回答读者反馈第3条）：
   **两次独立实验、均跑在现行树**——① `MDCG_POLICY_FILE=<内容 '{}'`> + `content_kind='text'`；
   ② 同一策略文件 + **省略** `content_kind`。结果：① `moved_to=review_queue`、`state=DEFER`；
   ② `moved_to=review_queue`、`state=BLINDSPOT`；两次 `inbox.jsonl` 均为 468/469 字节
   （同字面抖动，§2 注），合成凭据**字节命中 `True`**。**不是**「未设 env 之外的同一写入」——
   原文措辞有误，已改正。
   **限定口径（改正）**：「凭据不明文入队」只对**有合法规则列表的策略**成立——`forbidden`/`required`
   为空列表（本项）、为标量（§4.2 #9）、为字符串（§5.3）三种形态都不在此列。
2. `REJECT` 的脱敏只作用于正文与 `tags`（`writepipe.py:238-244`），截断在脱敏之后（`:245`）——**本轮未改该口径**。
3. 字节数的可比性：本报告内所有字节数均在**同树同 TEXT 字面**下测得，且已实测 ±1 字节的同树抖动
   来自 `t` 浮点 repr 长度（§2 注）。**TEXT 全文不在此给出**（本文硬边界：不得出现明文凭据），
   故「工作流 490/460 与本报告 468/469 的差值是否全部来自 TEXT 字面」**只能标为推断、未核对**。

### 6.4 足迹披露（如实）

- 工作流侧：首次 `npm pack --dry-run` 触发 `package.json:87` 的 `prepare` 脚本重建 gitignored 的 `lib/`
  （13 文件 mtime 刷新，随后改用 `--ignore-scripts`）；启动面探针刷新了本机默认 aux 根的
  `sustain/heartbeat.md_cg.stamp`（无法剔除本机常驻 mcp 进程自刷的可能）。
- 本报告侧：`git status --porcelain` 中 `package-lock.json` 显示为 `M`，但 `git diff --raw` /
  `--numstat` 对它输出**零内容差异**（stat 脏，非内容改动）。本报告只改了
  `docs/eval/issue43_默认策略加载与凭据明文队列_v1.0.md` 一个文件；**未改任何源码、未
  `git add/commit/push`、未写入任何在役记忆数据根**（全部复现库根在 `%TEMP%\i43*`）。

---

## 7. 读者问答（逐条回应 nextQuestions）

| # | 问题 | 回答 | 证据/状态 |
|---|---|---|---|
| Q1 | 空策略 `{}` 的残留算不算收口？总判定与结论为何不算它？ | **不算本 issue 的违约，但算「明文入队」的残留通路**，已列入 §6.1 留池表。理由：修前的问题是「**静默**空白」（用户不知道策略为空），修后空策略是部署方**显式**写出 `{}` 的选择，且 `audit.py:197-198` 的「无规则不能假装合规 → DEFER」是既有契约；本轮收窄的是「策略不可用」这一支。结论句已限定为「已被取代」针对默认链路（未设 env / 坏路径），并在 §6.1 明确 `{}` 仍明文入队 | §4.2 #9、§6.3-1（本报告亲跑） |
| Q2 | 非 ACCEPT/REJECT 出口的脱敏本轮到底改没改？「DEFER 出口明文入库」是留池还是收口？ | **没改**：§3.3 落点清单无一条触及 DEFER/BLINDSPOT 出口的落盘与脱敏；`writepipe.py:252-256` 仍原样 `cg.propose`。它是**留池面**，现已明确列入 §6.1（此前漏列，已补） | 读码（现行树）+ §6.1 |
| Q3 | 升级影响面：未设 env 的部署会不会突然被 REJECT？有无迁移/公告？历史明文凭据怎么办？ | 会。未设 env 的部署从「恒 DEFER → 全部入审核队列」变为「按包内默认策略判定」：`text` 缺六要素 → `REJECT`；命中 11 条 forbidden 之一 → `REJECT`；其余（如 `code`）不变。规则清单与形态见 §4.3，可据此自测。**迁移/公告与历史 `inbox.jsonl` 里已落明文凭据的处置，本报告无法决定、也未发现任何相关动作**——按发布决策留给运行方；本报告只能指出这一支属未处置 | §4.2 #3、§4.3、§6.1；迁移动作=**未验证/未发现** |
| Q4 | 「独立复核」是谁、什么口径？能给出可复跑记录吗？ | **不能**。本报告只有工作流转述的装置描述（`%TEMP%\i43rev`，跑完已删），无命令、无产物、无记录。已按 §0.1 建立「工作流采集·独立复核」标签并标注不可复跑（§5.1） | §5.1；**不可复跑** |
| Q5 | `47/47`、`191/191`、`258/258` 的计数单位？ | 47/47 = **断言数**（单模块内）；191/191、258/258 = **模块（测试文件）数**；新守卫含 47 条断言但只贡献 **+1 模块**（190→191）。判据：`scripts/run_tests.py` 汇总行按 `runnable` 模块计数，本报告实测日志 `PASS` 258 行 | §0.3；**本报告亲跑** |
| Q6 | 标量键缺陷的修复排期与发布影响？有临时防护/回滚建议吗？ | **排期不在本报告可及范围**（本报告只做取证与归档，不做发布决策）；当前发布版本是否已带上该缺陷，本报告**未验证**。可自测的临时防护：升级/配置后用 `python -X utf8 -m md_cg.mcp_server --show-config` 验证策略文件（正常路径 rc=0 并输出 JSON；标量键会 rc=1），或先跑 `python -X utf8 -m md_cg.test_issue43_default_policy`。注意：这两项都**未覆盖**标量键面（守卫按 §5.2(d) 是盲区），故「临时防护」的可靠口径目前只能是人工检查策略文件的 `forbidden`/`required` 是否为数组 | 建议=**未验证的运维建议**，非本报告实测结论；排期=**未定** |

---

## 8. 本次修订记录（v1.0 → v1.0-r1）

| 反馈 | 处置 |
|---|---|
| §3.1「生效条件注释」未定义；补充契约与 §5.2 的关系不明 | 新增 §0.1/§3.1：定义该注释为函数级契约声明惯例并给出行号例证；**明确 §5.2 属违约**（违反 `audit.py:142` 的「恒不抛」）；§6.1 相关措辞由「先定契约再落码」改为「先补齐已声明契约的行为」 |
| 计数单位不明 | 新增 §0.3（断言数 vs 模块数，给 `scripts/run_tests.py` 汇总行代码为判据），§4.1 增「量纲」列 |
| §6.3「空策略」实验句法不成立 | 重写 §6.3-1 为「两次实验、均现行树」并给各自结果 |
| §1.1「禁表命中」指代不明 | 改为「**修复后的**默认策略本该拦下的形态」，并指向 §4.3 清单 |
| §2「亲跑」列混树 | 列名改「本报告复跑」，逐行标注树与形态；新增 §0.2 三棵树定义；§2 表头新增字节数不可跨树对比的说明与实测依据 |
| rc 参照对象不明 / §4.2 行缺命令 | 新增 §0.4（rc 参照对象）；§4.2 改为「命令 + 树 + 结果」逐行给命令 |
| §2 腿6「三行内」歧义 | 改为「启动 stderr **全量共 3 行**」，并由本报告在 HEAD 树复现（§4.2 #6：rc=0、3 行、五关键词零命中） |
| 缺六要素与 forbidden 清单 | 新增 §4.3 全量清单（11 + 6 + labels + kinds） |
| 「有规则的策略」被反例排除 | §6.3-1 补回限定口径并改正措辞为「有**合法规则列表**的策略」，并列出三种反例形态（空列表 / 标量 / 字符串）；§6.1 空策略行同步指向该口径 |
| `init.ts` 动机归因无支撑 | §6.1 该行改为「本报告无证据判断是否有意」，只陈述缺席事实 |
| TEXT 字面未给出 → 字节差归因 | §6.3-3 明确 TEXT 因硬边界不载，归因降级为**推断/未核对**；并实测同树抖动来源（`t` 浮点 repr） |
| 字符串键「不触发」无实测 | §5.3 新增实测：不抛但退化为按字符建规则（`forbidden=23`、`命中禁止规则：s` → REJECT） |
| §1 判定行混入未亲跑数字 | 判定行改为逐项标注「本报告亲跑 / 工作流采集」，并注明容器两栈未跑及原因 |
| 独立复核来源无标签、不可追溯 | 新增 §0.1 第三档标签；§5.1 明写不可复跑；§4.1/§2 逐行标注 |
| nextQuestions 6 条 | 新增 §7 逐条回答（含 3 条标注为「未验证/未发现/未定」） |

---

## 9. 结论

- **写入面修复成立**：修前的「未设 env → 空规则 → 恒 DEFER → 正文（含凭据）明文入
  `hippocampus/inbox.jsonl` 且不脱敏」链路已被「包内默认回落 + 显式坏路径不掩蔽 +
  不可用则在提案前 fail-closed」取代；证据：修前/修后写入链字节面（§4.2 #2/#3/#4，亲跑）、
  合法输入逐位一致（§5.1-2，工作流采集·独立复核）、守卫 47/47 与 8 处定点变异恰好命中（§4.1，亲跑）。
- **总判定为 DEFER**（来源：工作流采集·独立复核；本报告以亲跑复现其依据）：本轮**新引入**
  「策略键为标量时」的缺陷，且**不止于诊断面**——启动面 server rc=1 + `TypeError`，
  **写入面**退化为 `DEFER → review_queue → inbox.jsonl` 逐字明文（含凭据），守卫该面为盲区。
  修好键类型闸（`policy_report` + `_rule_check` 两处）与三处调用兜底、补上相应断言后方可转通过。
- **未收口的三支**（如实列出，见 §6.1）：① 非 ACCEPT/REJECT 出口本身未改脱敏（只收窄了触发面）；
  ② 显式空策略 `{}` 仍明文入队；③ 键类型闸与启动/诊断面兜底留池。
