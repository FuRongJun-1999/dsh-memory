# issue #43 默认策略加载 · 键类型闸补强 · 修复工程报告 v1.1

> 范围：v1.0 报告（`docs/eval/issue43_默认策略加载与凭据明文队列_v1.0.md`）把「策略键类型」列为
> 留池面，且其 §5.2 已取证该面**同时波及启动面与写入面**；本轮补强＝给列表型策略键加类型闸，
> 并收口三处策略调用面的异常。本文只写有机械证据的事。
> **本文不含任何明文凭据**：复现与探针所用凭据一律为合成哑值，正文中只以 `sk-…（23 字符哑值）`
> 之类掩码形态出现。

## 0. 阅读约定（先读这一段）

### 0.1 证据来源标签（全文只有这三种）

| 标签 | 含义 | 可复跑性 |
|---|---|---|
| **本报告亲跑** | 我在本次会话中用所列命令实测过，命令与输出见对应条目 | 可复跑；命令逐条给出 |
| **工作流采集** | 由本修复工作流采集、**本报告未重跑**（含其 **14** 条复现腿，见 §2） | 本报告内不可复跑；只给工作流给的字符串 |
| **工作流采集·独立复核** | 独立复核者的结论，来源、装置、命令均由工作流转述 | 本报告内**不可复跑**（装置 `%TEMP%\i43rev_a` 已删，无命令、无产物） |

### 0.2 三棵树与行号口径

| 简称 | 是什么 | 行号可否复核 |
|---|---|---|
| **HEAD 树** | 未提交前的代码（`git archive HEAD`，`md_cg/audit.py` 462 行，无 `resolve_rulebook`） | 可（`git show HEAD:<path>`） |
| **补强前中间态** | 首轮修复（v1.0）已落地、**本轮键类型闸未加**的那一版——即 14 条复现腿（§2）所跑的树 | **不可**：该状态磁盘上已不存在（本轮改动直接改在工作树上，未提交、无 stash；我在 `%TEMP%` 下找到的所有 `md_cg/audit.py` 同名副本经查全为 HEAD 形态：462 行、`resolve_rulebook` 缺席、`policy_bad_shape` 缺席）。故**其行号只原样转述工作流所报，本报告未重推导** |
| **现行树** | 修复后的工作树 `<仓根>`（首轮 + 本轮全部改动） | 可（本报告 Read 所见行号） |

**故全文行号一律标树**：`补强前:…`（工作流所报）／`现行:…`（本报告读码）。

### 0.3 rc 的参照对象（每条 rc 都写明是哪个进程）

- `rc=<N>`（server）：`python -X utf8 -m md_cg.mcp_server` **进程自身**的退出码（0 = 正常起停）。
- `rc=<N>`（probe）：探针脚本（`python -X utf8 -c <code>`）的退出码；**写链/读探针跑完即 0**，与写入被拒无关。
- `rc=<N>`（guard/suite）：`python -X utf8 -m md_cg.test_issue43_default_policy` / `python -X utf8 scripts/run_tests.py` 的**进程**退出码。
- `<N>`（自证返回码，v1.1-r1 补定义）：`_mutation_baseline()` 的**函数返回值**（0/1/2）。它与进程退出码是两回事，
  但**同一条路**：`md_cg/test_issue43_default_policy.py:843-845` 的 `main()` 里 `return _mutation_baseline()`、
  `:865` 的 `sys.exit(main())` 把它透传为进程退出码。**§4.1 #3/#4/#5 报的数都是函数返回值**（进程内
  `python -c` 探针直接 `print` 该返回值），故其量纲栏写「自证返回码」而非「退出码」。

---

| 项 | 值 |
|---|---|
| 缺陷 | 策略文件是**合法 JSON 对象**、但列表型键取值为标量（`int`/`bool`/`str`）时无类型闸 → `policy_report()` 抛 `TypeError`；启动面 server **rc=1**（记忆面整体不可用）；写入面 `TypeError` 被兜底 `except` 吞成 `DEFER` → 正文（含凭据）逐字入 `hippocampus/inbox.jsonl`；`str` 形态不抛但**按字符建规则**（计数失真 + 误判） |
| 修复面（本报告读码核对的落点） | `md_cg/audit.py` **8 条行区间**（`POLICY_LIST_KEYS` / `_policy_list` / `_policy_shape_error` / 读取面接闸 / `unavailable_report` / `policy_report` 取值与兜底 / `_rule_check` 取值 / `redact_forbidden` 取值）＋ `md_cg/mcp_server.py` 3 处（`_show_config` / `main()` 启动行 / `op=info`）＋ `README.md:131` ＋ 守卫新增 G8 组。<br>**计数口径（v1.1-r1 补齐）**：摘要此处此前写「audit.py 6 处」，那是按**命名单元**数（把「`policy_report`＋`_rule_check`＋`redact_forbidden` 的取值口径」算 1 个单元）；§3.2 表按**行区间**列，故 8 行。两个数都对，口径不同——本文此后一律用**行区间**口径，§3.2 表即其清单 |
| 验证结论（**本报告亲跑 13 项检查 + 1 组归属实验**：§4.1 #1–#6、§4.2 #7–#13、§4.3） | 守卫 **71/71 断言，rc=0**；10 处定点变异**恰好**命中声明数，自证返回 0；`ANCHOR-MISS`/`INJECT-MISS` 均 fail-closed 返回 **2**；删 G8 组 → M9/M10 判据归零且自证 **返回 1**；python 全量 **257/258 模块**、rc=1（唯一红项 `md_cg.test_p27_docindex` 已实测归属为**与本改动无关**）；真进程 `--show-config` 与常驻 server 在标量键策略下 **rc=0** 且报出 `policy_bad_shape`；另行复核 `md_cg.test_policy_required_ccg` **28 pass / 0 fail** |
| **总判定（工作流采集·独立复核）** | **ACCEPT** —— 装置在系统 temp 的合成库（`%TEMP%\i43rev_a`，跑完已删），工作区只读（收尾 `git status`/diffstat 与起始快照逐字一致：9 文件 345+/33−，`data/policy.json` sha256 与 HEAD 相同） |
| 容器两栈 | 退出码 **0 / 0**（工作流采集，**本报告未跑**，理由见 §6.2） |

---

## 1. 缺陷定义与真实站点

### 1.1 缺陷定义

策略文件的**顶层**是 JSON 对象（v1.0 已加的闸门只判到这一层），但**列表型键的取值**可以是标量：
`{"forbidden": 1}`、`{"required": true}`、`{"forbidden": "sk-…（23 字符哑值）"}`。这些是**合法 JSON**，
故顶层对象闸放行；而下游三处把「列表型键」当作可迭代对象直接消费，于是：

| 取值形态 | 机械后果 |
|---|---|
| `int` / `bool` | `policy_report()` 的列表推导抛 `TypeError`（`'int'/'bool' object is not iterable`）。**同一个异常在三个调用面各炸一次**：(a) 启动期策略来源行（`mcp_server.py:3927` 的 `_policy_stderr_note(_audit.policy_report())`，构造点在 `main()` 任何 `try` 之外）→ 未捕获 → **server rc=1**（记忆面整体不可用，stdin 一行未读）；(b) `--show-config` 的应答体（`mcp_server.py:3811`）→ **rc=1 且 stdout 空**，与其「恒退出 0」契约相反；(c) 写入面 `_rule_check`（`md_cg/audit.py:284-285`）同抛，被验证器兜底 `except`（`:561-562`）吞成 `DEFER` → `moved_to=review_queue` → 正文（含凭据）**逐字**落 `inbox.jsonl`（脱敏只在 `REJECT` 分支，故此处不发生） |
| `str` | **不抛**（字符串可迭代）但语义静默崩坏：`policy_report()` 报 `forbidden=<字符串长度>`（**把长度当规则数**）；写入面按**字符**建成 N 条单字符规则 → 无关正文被单字符规则命中而误杀（`REJECT`），整串禁表语义丢失且无任何「形状非法」提示 |

一句话根因：**列表型键没有类型闸**，而「没有闸」在下游被三种不同方式消费（抛异常 / 计长度 / 按字符迭代），
三种都**不报「策略写坏了」**。

### 1.2 真实站点（行号标树）

| # | 站点 | 补强前（工作流所报） | 现行树（本报告读码） | 现行树证据 |
|---|---|---|---|---|
| S1 | `policy_report()` 计数用的列表推导（`int` 命中 `forbidden` 那行、`bool` 命中 `required` 那行） | `audit.py:157`（int）/ `:159`（bool） | `md_cg/audit.py:240` / `:241`（现均经 `_policy_list`） | Read `md_cg/audit.py:231-244` |
| S2 | `_rule_check()` 取 `forbidden` / `required`（写入面判定） | `audit.py:195` / `:196`（其**下游 `REJECT` 出口**＝同一函数的 `:199-202`，即 L12/L13 所报的「命中禁止规则」分支） | `md_cg/audit.py:284` / `:285`（`REJECT` 出口在 `:288-291`） | Read `md_cg/audit.py:284-297` |
| S3 | 病态出口：**`audit()` 内的验证器兜底 `except`** 把 `TypeError` 吞成 `DEFER` | `audit.py:467-470` | `md_cg/audit.py:561-562`（`return _verdict(DEFER, kind, f"验证器异常：…")`） | Read `md_cg/audit.py:550-564` |
| S4 | 启动期策略来源行（`main()`，**不在任何 try 内**） | `mcp_server.py:3907` → `audit.py:157` | `md_cg/mcp_server.py:3927`（本轮外层加 try） | Read `md_cg/mcp_server.py:3926-3930` |
| S5 | `--show-config` 的 `policy_report()` 调用 | `mcp_server.py:3799`（traceback 3808 → 3799 → audit.py:157/159） | `md_cg/mcp_server.py:3811`（try 在 `:3810`） | Read `md_cg/mcp_server.py:3796-3816` |
| S6 | `cg(op=info)` 的 `h["write_policy"]` 赋值 | `mcp_server.py:2143` → `audit.py:157` | `md_cg/mcp_server.py:2147`（try 在 `:2146`） | Read `md_cg/mcp_server.py:2136-2151` |
| S7 | 病态出口的落点（`DEFER` 走 `cg.propose`） | — | `md_cg/writepipe.py:252-256`（`moved_to="review_queue"`） | Read `md_cg/writepipe.py:252-258` |

**三个「兜底 `except`」叫法是同一物（v1.1-r1 澄清）**：§1.1 的「验证器兜底 `except`」、§3.2 的「`audit()` 兜底
`except`」、S3 的 `md_cg/audit.py:561-562` 指**同一个站点**——它位于公开函数 `audit()` 体内（`def audit` 在
`:550`），包住被分派的**验证器**调用（`:559-562`），把验证器抛出的异常收成 `DEFER`。即「验证器」是该结构
包住的对象、「`audit()`」是它所在的函数，**不是两处不同站点**。

**关于补强前行号的一处如实说明**：工作流所报的 S1 两条为 `:157`（int）与 `:159`（bool），二者相隔两行；
而现行树对应两行相隔一行（`:240`/`:241`），且我**无法**重推导补强前的行号（§0.2）。故此处只按「工作流原样」
转述，不宣称它的行距成因。

---

## 2. 修前现场（工作流采集的 14 条复现腿）

> 来源：本修复工作流采集。**全部为工作流采集，本报告未重跑**（补强前中间态磁盘上不可得，§0.2）。
> 合成凭据 `sk-…`（哑值）在表中一律不写全串。
>
> **腿数口径（v1.1-r1 改正）**：工作流交付的复现数组共 **14 条**条目，每条自带 `reproduced: true`；
> 本报告 §2.1 的 L1–L4 与 §2.2 的 L5–L14 即其**逐条**转写，**无一条被排除**——L9 是数组内标注为
> 「对照，不崩」的独立条目、L14 是同一条目内含 in-process 与真子进程两形态（仍是一行）。本报告初版
> 四处误记为「13 条」，已全部改正为 14。<br>（另注：v1.0 报告 §5.1 转述的复核侧「5 条分支腿 + valid 共
> 24 次运行」是**另一次装置**的计数，与这 14 条不是同一口径，勿混。）

### 2.1 构造期装载面（探针 `leg_policy_report.py` / `leg_write.py`，策略经 `MDCG_POLICY_FILE` 指向临时文件）

| 腿 | payload（策略文件内容） | 观察到的异常 / 崩溃点 | 站点（补强前） |
|---|---|---|---|
| L1 | `{"forbidden": 1, "required": ["要素一"]}`（合法 JSON 对象，`forbidden` 取标量 `1`） | `resolve_rulebook()` 判为**可用**（`source=env, err=None, rules={'forbidden': 1, …}`）；`policy_report()` 抛 `TypeError: 'int' object is not iterable`——契约「`policy_report` 恒不抛」不成立。同一 `rules` 下 `load_rulebook()` 正常返回 dict（不抛），`_rule_check('hello world', rules, 'text')` **同抛** | `audit.py:157` |
| L2 | `{"forbidden": ["zzz"], "required": true}`（`required` 取布尔） | `policy_report()` 抛 `TypeError: 'bool' object is not iterable`；`_rule_check` 同抛于 `required = [r for r in (rules.get("required") or []) if r]`。**注意 `required=false` 不触发**（假值回落 `[]`），只有 `true`/非空标量触发 | `audit.py:159` / `:196` |
| L3 | `{"forbidden": "sk-…（23 字符哑值）", "required": []}` | **不抛**。`policy_report()` 返回 `available=true, forbidden=23`（把字符串长度当规则数）；`_rule_check('hello world', rules, 'text')` = `REJECT`「命中禁止规则：d」——单字符规则 `d` 命中 `world`，即每个字符各成一条规则，整串禁表语义丢失且不报错 | `audit.py:157-160`（计数）/ `:195`（判定） |
| L4 | `{"forbidden": [], "required": "abcdef"}` | **不抛**；`policy_report()` 报 `required=6`；`_rule_check('hello world')` = `REJECT`「缺少必需要素：a、b、c、f（补齐后重写即可，本条未入库）」——六要素文案退化成「文本须含 a、b、c、f 四个字符」 | `audit.py:159` / `:196` |

### 2.2 启动面 / 诊断面（真子进程，cwd=临时目录，`PYTHONPATH=仓根`，`MDCG_ROOT/AUX_ROOT/TOKEN_FILE/MASTER_KEY/LEGACY_ENV_AUTH` 全指向 tmp）

| 腿 | payload / 命令 | 观察到的异常 / 崩溃点 | 站点（补强前） |
|---|---|---|---|
| L5 | `MDCG_POLICY_FILE=pol_int.json`；`python -X utf8 -m md_cg.mcp_server`，`stdin=EOF` | **rc=1，无 stdout**；stderr 先出「路径：记忆源 root=…·aux=…」再出未捕获 traceback：`main → mcp_server.py:3907 sys.stderr.write(_policy_stderr_note(_audit.policy_report()))` → `audit.py:157 TypeError: 'int' object is not iterable`。**策略来源行没有打印**（异常发生在入参求值处）——**记忆面整体不可用**（进程直接退出，stdin 一行未读） | `mcp_server.py:3907`（→`audit.py:157`） |
| L6 | `pol_bool.json`（`required=true`），同一启动命令 | **rc=1**，无 stdout；traceback `main:3907 → audit.py:159 TypeError: 'bool' object is not iterable`。**AST 复核**（`ast.walk` 找覆盖该行的 `Try`）：`mcp_server.py:3907` 的两个策略调用（`policy_report` / `_policy_stderr_note`）enclosing `Try` = **NONE**，证实「不在任何 try 内」 | `mcp_server.py:3907`（→`audit.py:159`） |
| L7 | `pol_int.json`；`python -X utf8 -m md_cg.mcp_server --show-config` | **rc=1**（契约要求恒退出 0），**stdout 为空串**；stderr traceback：`main:3808 return _show_config()` → `mcp_server.py:3799 "policy": audit.policy_report()}` → `audit.py:157 TypeError`。与 `_show_config` docstring「不判是否可用…退出码仍为 0」直接相反 | `mcp_server.py:3799`（→`audit.py:157`） |
| L8 | `pol_bool.json`；同上 | **rc=1**，stdout 为空；traceback `3808 → 3799 → audit.py:159 TypeError` | `mcp_server.py:3799`（→`audit.py:159`） |
| L9 | `pol_str.json`（`forbidden` 为 23 字符哑值）；同上（**对照腿，不崩**） | **rc=0**，stdout=`{"server": "mdcg-mcp", "version": "0.6.0", "policy": {"source": "env", …, "available": true, "forbidden": 23, "required": 0, "error": null}}`——退出码正常，但诊断面把「23 个字符」当「23 条禁表规则」**如实播报给用户**：静默失真（对照：同一面在 int/bool 下直接崩） | `audit.py:157` |
| L10 | `pol_int.json` + 临时库根；`python -X utf8 leg_write.py`（正文含合成哑凭据） | 写链返回 `moved_to=review_queue / committed=false`，`verdict.state=DEFER`、evidence「验证器异常：TypeError: 'int' object is not iterable」——即 `audit.py:467-470` 的兜底 `except` 把 `_rule_check` 的 `TypeError` 吞成 `DEFER`，再走非 ACCEPT/REJECT 出口 `cg.propose`；`inbox.jsonl` 长 375 字节、**含合成凭据与标记逐字**，全库字节面无 `[已过滤:禁表#` 占位符（脱敏只在 `REJECT` 分支，未发生） | `audit.py:195`（抛）→ `:467-470`（吞）→ `writepipe.py:253-256` |
| L11 | `pol_bool.json` + 同一含凭据内容 | 同路：`moved_to=review_queue / DEFER`、evidence「验证器异常：TypeError: 'bool' object is not iterable」；`inbox.jsonl` 375 字节、`mark_hit=true`、`secret_hit=true`、`all_has_placeholder=false` | `audit.py:196`（抛）→ `:467-470`（吞）→ `writepipe.py:253-256` |
| L12 | `{"forbidden": "sk-…（23 字符哑值）"}`；正文＝「I43CANARY 正文 无关字串 xyz」（不含整串凭据） | `moved_to=rejected`、`verdict=REJECT`、evidence「命中禁止规则：3」——单字符 `3` 被当成一条禁表规则命中；策略本意（禁整串）在无关文本上**误杀**，且全程无「形状非法」提示 | `audit.py:195` / `:199-202` |
| L13 | 同一 `str` 策略；正文＝「ok! I43CANARY」 | `moved_to=rejected`、evidence「命中禁止规则：k」——`k` 单字符即规则；`inbox` 0 字节（此路是 `REJECT`，不落队列） | `audit.py:195` / `:199-202` |
| L14 | `pol_int.json`；`call_tool(cg, "cg", {"op": "info"})`（in-process），另以真子进程喂一行 `tools/call op=info` | **in-process**：`TypeError`，站点 `mcp_server.py:2143 h["write_policy"] = audit.policy_report()` → `audit.py:157`（该行同样无 enclosing `Try`；由 `_serve_line` 的兜底 `except` 收成 `-32603`）。**真 server 形态下该调用面不可达**：进程在 `main:3907` 启动期即崩（rc=1），stdin 一行未读——畸形策略**先把整台 server 打死**，info 面无从谈起 | `mcp_server.py:2143`（→`audit.py:157`） |

**修前现场的一句话**：`int`/`bool` 让**诊断面崩、启动面崩、写入面失守**（凭据明文入队）；`str` 让**诊断面说谎、写入面误杀**。
三类形态**都不报「策略写坏了」**。

---

## 3. 修法契约与落点

### 3.1 契约（承 v1.0 的 ①–④，本轮新增 ⑤–⑨）

**编号不是从 ⑤ 起算的空号（v1.1-r1 补）：①–④ 是 v1.0 报告 §3.2 表的四条硬契约 C1–C4**，出处
`docs/eval/issue43_默认策略加载与凭据明文队列_v1.0.md` §3.2（该表由本报告读码核对，段落内容一致）：

| v1.0 编号 | 契约（v1.0 原文标题） | v1.0 声明的落点（**该报告的「现行树」＝本报告的补强前中间态**） |
|---|---|---|
| ①（＝C1） | **来源单点** | v1.0 §3.2「`md_cg/audit.py:113-139` `resolve_rulebook()`」 |
| ②（＝C2） | **未设/空串 → 回落包内默认**（包根由 `__file__` 反推，不依赖 cwd） | v1.0 §3.2「`md_cg/audit.py:82-90`、`:125-139`」 |
| ③（＝C3） | **显式坏路径不得被默认掩蔽** | v1.0 §3.2「`md_cg/audit.py:127-132`」 |
| ④（＝C4） | **不可用 → 提案入队前 fail-closed** | v1.0 §3.2「`md_cg/writepipe.py:210-217`」；本报告 §4.2 #11 在**现行树**复核了该闸（`md_cg/writepipe.py:210-217`，读码所见） |

下表的 ⑤–⑨ 是**本轮（键类型闸补强）新声明成立**的五条，编号接续上表。二者共同构成本 issue 的契约全集；
①–④ 的**保持性**由 §4.1 #2 的定点变异与 §4.1 #1 的 71 条断言共同看住（G1–G5 打红即 ①–④ 被破坏）。

| # | 契约 | 落点（现行树行号，本报告读码） |
|---|---|---|
| ⑤ | **列表型键的取值必须是数组**，否则**判形状非法**（不替调用方猜、不按字符拆、不当空值静默放行）。二选一的另一支「整串作单条规则」**不取**——理由写在 `_policy_shape_error` docstring：数组之外的值没有唯一读法，替调用方猜即替它决定安全边界；且与 `int`/`bool` 的 `TypeError` 同根因，须同出口 | `md_cg/audit.py:105-134`（判据）、`:84`（键白名单） |
| ⑥ | **`policy_report()` 恒不抛**（它在**启动路径**上，畸形恰是最需要被诊断出来的情形）：形状闸是第一道，`try/except → unavailable_report` 是第二道 | `md_cg/audit.py:217-244`（`:243-244` 兜底） |
| ⑦ | **诊断面恒退出 0**：`--show-config` 的策略探测异常收成同形状的不可用自描述，退出码只表达「诊断器自己是否跑完」 | `md_cg/mcp_server.py:3796-3816`（try 在 `:3810-3813`） |
| ⑧ | **启动期不得因策略畸形而死**（N225 教训：启动期崩＝记忆面整体不可用）：来源行异常只写一行 stderr，启动继续——写入侧另有 fail-closed | `md_cg/mcp_server.py:3926-3930` |
| ⑨ | **畸形策略在提案入队之前 fail-closed**，与「不可用」**同码同出口**：`_read_policy_file` 把形状非法并进既有错误码面（`policy_bad_shape`），闸门与诊断面无需各自再判一次 | `md_cg/audit.py:165-167`；`md_cg/writepipe.py:210-217` |

### 3.2 落点清单（本报告逐条读码核对）

| 文件:行（现行树） | 改动 |
|---|---|
| `md_cg/audit.py:84` | 新增 `POLICY_LIST_KEYS = ("forbidden","required","required_kinds","required_labels")`——**白名单式**判据面：默认策略里 `_comment`/`_note` 本就是字符串，泛化类型闸会把**合法默认策略**判死；其余键（含未知键）不参与形状判定 |
| `md_cg/audit.py:88-101` | 新增 `_policy_list(rules,key)`：`list`/`tuple` 原样浅拷贝，其余（标量/对象/`None`/缺键/非 dict）一律 `[]`——**恒不抛、不把一个字符串按字符拆成规则**（消费面纵深防御） |
| `md_cg/audit.py:105-134` | 新增 `_policy_shape_error(rules)`：形状闸单点，返回 `("policy_bad_shape", 含键名与实得类型的原因串)` 或 `None` |
| `md_cg/audit.py:165-167` | `_read_policy_file` 在 `isinstance(dict)` 之后接入形状闸：env 显式面 → `code=policy_bad_shape`（**不回落包内默认**），包内默认面并入既有 `policy_unavailable` |
| `md_cg/audit.py:201-213` | 新增 `unavailable_report(exc)`：策略自描述的不可用形状单点（`source=unavailable / available=false / code=policy_report_failed / hint`），`policy_report` 内部兜底与 `mcp_server` 三处调用面共用（避免兜底文案两套口径） |
| `md_cg/audit.py:231-244` | `policy_report()` 计数改经 `_policy_list`（标量键计 0，**不再把字符串长度当规则数**）+ `try/except` ⇒ 恒不抛；docstring 同步「为什么恒不抛」 |
| `md_cg/audit.py:284-297` | `_rule_check` 的 `forbidden`/`required`/`required_kinds`/`required_labels` 四键改经 `_policy_list`：直喂畸形 `rules` 时不再抛 `TypeError`（旧路径会被 `audit()` 兜底 `except` 吞成 `DEFER`→`review_queue`，即病态出口），也不按字符建规则 |
| `md_cg/audit.py:345` | `redact_forbidden` 的 `forbidden` 同口径改经 `_policy_list` |
| `md_cg/mcp_server.py:3810-3813` | `_show_config` 的策略探测加 `try` → `audit.unavailable_report` ⇒ **恒退出 0** |
| `md_cg/mcp_server.py:3926-3930` | `main()` 启动期策略来源行加 `try/except`：异常只写一行 stderr，**启动继续** |
| `md_cg/mcp_server.py:2146-2149` | `cg(op=info)` 的 `write_policy` 赋值加 `try` + 同形状兜底 ⇒ 诊断面异常不再把整个 info 拖成 `-32603` |
| `README.md:131` | 文档补齐：形状非法判据（四键任一取值非数组，标量/字符串同判）、错误码 `policy_bad_shape`、诊断面恒退出 0 且可用 `--show-config` 自测 |
| `md_cg/test_issue43_default_policy.py:476-481, 613-706` | 新增 **G8 键类型闸组 24 断言**。**24 的组成（v1.1-r1 补算式）**：三种标量形态（`int`/`bool`/`str`，表在 `:476-481`）× 每形态 **7** 条（`g8()` 的循环体 `:617-683` 内依次 `ok(...)`：**A** 诊断面恒不抛+结构化（`:622`）/ **B** 解析面判不可用（`:628`）/ **C** 同进程 `--show-config` 恒 rc=0（`:633`）/ **D** **真进程** server 启动 rc=0 且来源行报 code+fail-closed（`:640`）/ **C2** **真进程** `--show-config` rc=0 且 `available=false`+code（`:646`）/ **E** 写入 fail-closed 且 inbox 与全库字节面零正文+未落节点+响应体无凭据（`:659`）/ **F** `op=info` 不拖崩且 `write_policy` 报不可用（`:676`））＝ **3×7 = 21**；另加循环外 3 条 **G** 计数非长度（`:686`）/ **H** 消费面纵深不按字符建规则（`:691`）/ **I** 形状闸不误伤合法默认策略（`:699`）⇒ **21 + 3 = 24**。判据面：§4.1 #1 的运行输出逐行列出这 24 条 PASS |
| `md_cg/test_issue43_default_policy.py:518-568` | 跨进程注入通道（`sitecustomize`，N225 同款）：audit 面变异注入真子进程，注入标记缺失即抛 `_InjectFailed`（`INJECT-MISS` → 退出码 2）；`_spawn_env` 剔净 `MDCG_*` 并只注入指向临时目录的覆盖键（零令牌、不触在役数据根） |
| `md_cg/test_issue43_default_policy.py:779-791` | 变异表新增 M9（`_policy_shape_error` 恒 `None`）、M10（`_policy_list` 接受 `str` 即按字符拆）；并同步 M3 6→9、M4 9→31、M7 5→8、M8 1→4 的计数与理由 |

**一处如实标注（v1.1-r1）：`unavailable_report` 的形状是「源码所写」，本报告**未能**在实测中让它产出。**
`md_cg/audit.py:201-213` 声明的形状（顶层 `source=unavailable`、`available=false`，`code=policy_report_failed`
**嵌在 `error` 下**——即顶层没有 `code` 键）在本文所有实测中一次都没出现：正常路径下第一道形状闸先返回
`policy_bad_shape`（§4.2 #7 实测），把形状闸关掉后第二道防线 `_policy_list` 仍使 `policy_report()` **不抛**
（§4.2 #12 实测）。故它当前是一个**未观测到的兜底分支**——`mcp_server` 三处 `except` 同理。它**不是死代码**
的结论我无法给出（我构造不出触发它的输入）；能给出的只有：**它的形状声明未经实测**、`code` 在 `error` 下
而非顶层，契约⑦⑧⑨的「三处调用面共用同一兜底形状」是**代码结构上**成立（三处都调 `audit.unavailable_report`、
`md_cg/mcp_server.py:3812-3813`、`:2148-2149`），不是「三处都实测过」。

### 3.3 迁移面（本轮**未改任何既有测试文件**）

默认策略生效面已在首轮处置（`test_linkref`/`test_mr_m2`/`test_p2_mcp`/`test_writepipe` 四处保持首轮迁移状态）。
键类型面与既有断言的唯一交点是 `test_policy_required_ccg` G4c（`required_labels="ABCDEF"` 非列表、手搓 rules
直喂 `_rule_check`，期望回落正则串且不抛）——新口径下 `_policy_list` 兼容该场景，**断言一字未改即通过**。
该断言的**实测**（v1.1-r1 补，本报告亲跑）：`python -X utf8 -m md_cg.test_policy_required_ccg` →
`结果：28 pass / 0 fail（红项：无）`、末行 `ALL OK：text 类必需要素缺失即拒并给出可读补齐清单；work_wip 不受
required 约束；accept 旁路未受影响`、**rc=0**；G4c 本体在 `md_cg/test_policy_required_ccg.py:256-257`（该模块
确实含该用例，非推测）。

### 3.4 纪律降级声明（工作流采集，须声明）

工作纪律 0.1 的 `cg(op=route)` **未执行**。**卡在哪一层（v1.1-r1 写清，此前 L14 与本节并读会矛盾）**——
`cg` 在本仓是**工具名/入口名**，不是模块级函数，三层各自独立：

| 层 | 事实 | 证据 |
|---|---|---|
| ① 工具面 | 工作流会话的工具面**没有 mdcg 工具** | 工作流采集的自述 |
| ② 模块面 | 兜底路径「进程内直调 `md_cg.mcp_server`」——该模块**没有**名为 `cg` 的属性，`md_cg.mcp_server.cg` 不是一个函数 | 本报告亲跑 `python -X utf8 -c "import md_cg.mcp_server as m; print(hasattr(m,'cg'))"` → **`False`**；模块的入口是 `call_tool(cg, name, args)`（签名实测），`cg` 是**它的第一个参数** |
| ③ 实例面 | 于是唯一等价路径是构造一个认知图实例再 `call_tool(<实例>, "cg", {"op":"route", …})`——而构造 `MdCGSecure` 需要数据根，`close`/`compact` 会写索引（在役数据根） | 守卫里的同款用法：`md_cg/test_issue43_default_policy.py:140-143` 的 `_cg(root)` 返回 `MdCGSecure(root, principal=…)`；`:676` `mcp_server.call_tool(cg, "cg", {"op": "info"})` |

故 §2.2 L14 的 `call_tool(cg, "cg", {"op": "info"})` 里，**第一个 `cg` 是认知图实例（守卫在临时根上构造的
`MdCGSecure`；工作流那条腿同理，跑在临时库根上）**、第二个 `"cg"` 才是**工具名**。降级理由落在第 ③ 层：
在**临时**根上构造实例是可做的，但把 `cg(op=route)` 跑成「与在役部署等价的记忆查询」需要在**在役数据根**上
构造实例，与本任务硬边界「不动任何在役数据根」冲突——故按第 7 条降级并声明，未静默跳过。第 16 条归档同样
受该硬边界阻断，未写灵枢记忆。

### 3.5 策略装载的三个函数名（v1.1-r1 补：L1 的 `resolve_rulebook` 出自这里）

全文出现的三个名字是**三个不同函数**（都在现行树 `md_cg/audit.py`），形状闸的落点是**第一个**：

| 名字 | 现行树行号 | 职责 | HEAD 树是否有 |
|---|---|---|---|
| `_read_policy_file(path)` | `:150-168`（**形状闸在 `:165-167`**） | 读**单个**文件 → `(rules|None, (错误码, 原因)|None)`；顶层非对象、形状非法都在这里判掉 | 无 |
| `resolve_rulebook(path=None)` | `:172-198` | **来源解析单点**（env / 包内默认 / 不可用），内部调 `_read_policy_file`；恒不抛 | **无**（§0.2 已记：HEAD 树 `hasattr(audit,'resolve_rulebook')` 为假） |
| `load_rulebook(path=None)` | `:248-256` | 兼容包装：委托 `resolve_rulebook`，不可用时返回 `{}`（旧契约） | 有（HEAD `:64`，但**只认 env、无回落**） |

故 §2.1 L1 的「`resolve_rulebook()` 判为可用」**不是笔误**：判「可用/不可用」的对外单点是 `resolve_rulebook`，
而形状闸在它调用的 `_read_policy_file` 里（补强前这一层没有闸，所以标量键被它判成**可用**）。两者**不是**
同一函数的两个叫法。

---

## 4. 验证数字

### 4.1 本报告亲跑的检查（本文第 1–6 项；本报告亲跑合计＝本节 6 项 + §4.2 的 7–13 ＝ **13 项**，另加 §4.3 的 1 组归属实验）

| # | 命令 | 结果 | 量纲 |
|---|---|---|---|
| 1 | `python -X utf8 -m md_cg.test_issue43_default_policy` | **71 通过 / 0 失败，rc=0**；分组 G1=6 G2=3 G3=6 G4=9 G5=6 G6=8 G7=9 **G8=24** | 断言数（单模块内） |
| 2 | 同命令加 `--mutation-baseline` | 未变异基线红项=0；**M1 13/13、M2 3/3、M3 9/9、M4 31/31、M5 12/12、M6 2/2、M7 8/8、M8 4/4、M9 23/23、M10 1/1**，全部与声明**恰合**，`变异自证：PASS`，**rc=0** | 每处变异打红的断言条数 |
| 3 | 锚点漂移探针（仅内存把 `_MUTATIONS` 换成含假锚点的一项） | 打印 `ANCHOR-MISS MX 假锚点探针`，**`_mutation_baseline()` 返回 2** | 自证返回码（§0.3） |
| 4 | 注入失效探针（仅内存把 `_SITE_SRC` 换成不写注入标记的版本，再跑一条 audit 面变异） | 打印 `INJECT-MISS MX 注入失效探针 —— sitecustomize 注入未生效`，**返回 2** | 自证返回码（§0.3） |
| 5 | 判别力探针（仅内存从 `_GROUPS` 摘掉 `g8`，只跑 M9/M10） | **M9 红 0/23、M10 红 0/1**（判据归零），`变异自证：FAIL`，**返回 1** | 断言数 / 自证返回码 |
| 6 | `python -X utf8 scripts/run_tests.py --jobs 4` | `SUMMARY 257/258 通过，5 跳过（依赖缺失/平台不符）`，失败：`md_cg.test_p27_docindex`，**rc=1** | 模块数 |

**M1–M10 各自变异的是什么（v1.1-r1 补，逐条读码 `md_cg/test_issue43_default_policy.py:736-792`）**——每处变异是
「把<b>靶函数</b>的<b>一行源码</b>换成另一行」（`inspect.getsource` + `str.replace`，内存 patch，不写盘）：

| 变异 | 靶（模块.函数） | 变异内容（原样 → 替换） | 声明红项 | 本报告实测 |
|---|---|---|---|---|
| M1 删掉包内默认回落 | `audit.resolve_rulebook` | `dflt = default_policy_path()` → 指向一个不存在的文件 | 13 | **13/13** |
| M2 定位改为依赖 cwd | `audit.package_root` | `return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` → `return os.getcwd()` | 3 | **3/3** |
| M3 闸门取消策略前置 | `writepipe._gate_audit` | `if perr is not None:` → `if False:` | 9 | **9/9** |
| M4 显式坏路径回落包内默认 | `audit.resolve_rulebook` | 坏路径分支里插入「先读包内默认，成功即返回」 | 31 | **31/31** |
| M5 策略读取返回空规则 | `audit._read_policy_file` | `return rules, None` → `return {}, None` | 12 | **12/12** |
| M6 启动 stderr 行置空 | `mcp_server._policy_stderr_note` | 函数体开头插入 `return ""` | 2 | **2/2** |
| M7 `--show-config` 不输出 | `mcp_server._show_config` | `sys.stdout.write(json.dumps(...))` → `pass` | 8 | **8/8** |
| M8 info 不报策略 | `mcp_server._cg_dispatch` | `h["write_policy"] = audit.policy_report()` → `pass` | 4 | **4/4** |
| M9 形状闸失效 | `audit._policy_shape_error` | `if key in rules and not isinstance(rules[key], (list, tuple)):` → `if False:` | 23 | **23/23** |
| M10 列表取值不做类型闸 | `audit._policy_list` | `isinstance(v, (list, tuple))` → `isinstance(v, (list, tuple, str))` | 1 | **1/1** |

即「M1/M2/M5/M6 变异的是什么」有出处的答案就是上表：M1 拆掉**包内默认回落**、M2 把**包根定位改成 cwd 依赖**、
M5 让**策略读取返回空规则**、M6 让**启动 stderr 行渲染成空串**。四者各自只动一处，故「恰好命中声明条数」
这一判据是**可自查**的：上表 + §4.1 #2 的实测列。

### 4.2 本报告亲跑的真进程面（独立于守卫断言；行号续 §4.1 的 7–13）

| # | 命令要点 | 结果 |
|---|---|---|
| 7 | 临时 cwd + `PYTHONPATH=仓根` + `MDCG_POLICY_FILE=<{"forbidden":1,"required":["要素一"]}>` → `python -X utf8 -m md_cg.mcp_server --show-config` | **rc=0**；stdout 单行 JSON：`"policy": {"source":"env", …, "available": false, "forbidden": 0, "required": 0, "error": {"code": "policy_bad_shape", …}}`；stderr 空 |
| 8 | 同上但 `{"forbidden":["zzz"],"required":true}`，且以真启动环境（临时 root/state/data/aux/token/master-key/`MDCG_SUSTAIN=0`/`LEGACY_ENV_AUTH=1`）跑常驻 `python -X utf8 -m md_cg.mcp_server`，`stdin=EOF` | **rc=0**，stdout 0 字节，stderr 4 行、**无 `Traceback`/`TypeError`**；策略行＝`[mdcg-mcp] ⚠ 写入策略不可用（来源=env code=policy_bad_shape）：策略键 required 须为列表（实得 bool）……写入将 fail-closed（不落盘、不入审核队列）。` |
| 9 | 进程内 `audit._rule_check('hello world', {"forbidden":1,"required":[]}, 'text')` | `('DEFER', '未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定')`——**不抛**（修前为 `TypeError`，见 L1） |
| 10 | 进程内 `audit._rule_check(…, {"forbidden": "<23 字符哑值>", "required": []})` 与 `audit.redact_forbidden('hello world <同一哑值>', 同 rules)` | 前者 `DEFER`（**不按字符建规则**，修前为单字符 `REJECT`，见 L3）；后者原样返回输入（**未掩成筛子**） |
| 11 | 进程内 `audit._policy_shape_error({'forbidden':1})` / `({'required':'abcdef'})` / `({'unknown':5})` | `('policy_bad_shape', '策略键 forbidden 须为列表（实得 int）——数组之外的值没有唯一读法，不猜、不按字符拆开')` / `…（实得 str）` / **`None`**（未知键不参与形状判定） |
| 12 | 进程内把第一道闸关掉（仅内存 `audit._policy_shape_error = lambda r: None`）后，对同一标量键策略调 `audit.policy_report()` | **不抛**，返回 `{"source":"env", …, "available": true, "forbidden": 0, "required": 1, "error": null}`——即「第二道防线 `_policy_list`」仍在，兜底 `unavailable_report` **仍未产出**（见 §3.2 末的如实标注） |
| 13 | 进程内默认部署（env 未设、走包内默认策略）下的两次写入：`content_kind` 省略 vs `content_kind='text'` | 省略 → `moved_to=review_queue`、`state=BLINDSPOT`、`inbox.jsonl` **342 字节且含合成凭据与标记**（**默认部署下仍明文入队**）；`text` → `moved_to=rejected`、`state=REJECT`、`inbox` 0 字节、全库字节面**不含**凭据（回答 §8-Q3） |

**§4.2 #7 里 `required: 0` 不是又一次计数失真（v1.1-r1 补解释）**：该腿的策略是
`{"forbidden": 1, "required": ["要素一"]}`——`required` 本身是**合法数组**，但形状闸判整个策略**不可用**，
`resolve_rulebook()` 于是返回 `rules=None`（§4.2 #12 的 `available=false` 即此），而 `policy_report()` 的计数写作
`len([r for r in _policy_list(rules, "required") if r])`（`md_cg/audit.py:240-241`），`_policy_list(None, …)`
按定义返回 `[]` ⇒ **计 0**。口径是「**实际生效**的规则条数」：策略不可用时没有任何规则生效，故一律 0——
不是「把一个合法列表报成 0」的失真。同一口径也在 `unavailable_report` 的声明形状里（`:209-210` 固定
`forbidden: 0, required: 0`）。

### 4.3 python 全量唯一红项的归属实验（本报告亲跑）

`md_cg.test_p27_docindex` 在现行树失败，**与本改动无关**——实验（HEAD 纯导出树，两次）：

| 条件 | 结果 |
|---|---|
| A：`git archive HEAD` 纯导出树（**无**首轮/本轮任何改动、无未跟踪文档） | **通过 98 / 失败 0，rc=0**；prune 节点面 `scanned=1994/1995, truncated=False, max_nodes=2000`；§12 回放**取样 1993 卡**，一致 1993 / 键未命中 0 / 源已移出 0 / 读不了 0 |
| B：**同一导出树** + 仅放入未跟踪的 `docs/eval/issue43_默认策略加载与凭据明文队列_v1.0.md` | **通过 91 / 失败 7**（`scanned=2026, candidates=0, truncated=True, max_nodes=2000`；回放取样 2026 卡、源已移出 2）。失败项逐条：`docs/ 全部 md 被索引（无静默跳过）`、`prune_dry_run 列出待清退但不删`、`prune 清退悬空节点`、`清退后悬空归零`、`清退后重开不复活幽灵条目`、`清幽灵后悬空仍为零`、`零键未命中 / 零源已移出 / 零读不了` |

即：**该失败由「工作区新增一份 docs 报告文档」把语料卡数推过 `max_nodes=2000` 的扫描窗引起**，
与键类型闸无因果关系（导出树里没有本轮改动，照样 7 红；没有那份文档，照样全绿）。
v1.0 报告 §4.1 报的 258/258 与本轮的 257/258 同源，系同一份未跟踪文档进入工作区所致。

**现行树（含本报告 v1.1 落盘后）的实测数字（本报告亲跑）**：`python -X utf8 -m md_cg.test_p27_docindex`
（cwd＝仓库根）→ `通过 91 / 失败 7`，`scanned=2055/2056`、`truncated=True`、`max_nodes=2000`；§12 回放
**取样 2055 卡**（一致 2053、键未命中 0、源已移出 2、读不了 0）。即该扫描窗在现行树**已被越过**，
p27 会继续红，直到卡数回落或窗口/归档方式调整（见 §8-Q6；该决定不在本报告）。

### 4.4 工作流采集的数字（**本报告未跑**）

| 项 | 结果 | 量纲 |
|---|---|---|
| 目标套件 | `python -X utf8 scripts/run_tests.py md_cg --jobs 4` → `SUMMARY 190/191 模块通过、3 跳过、rc=1`；新守卫在套件内 `第 42 行 PASS md_cg.test_issue43_default_policy` | 模块数 |
| 容器栈一 | 退出码 **0**；`结果: 21 pass / 0 fail`；`[PASS] smoke_test (linux)`；`=== 汇总: 38 pass / 0 fail ===` | 脚本内记录项数 |
| 容器栈二（node 侧） | 退出码 **0**；`# cancelled 0`、`# skipped 3`、`# todo 0`、`# duration_ms 5287.061385` | node 测试项数 |
| 删断言探针 | 工作流原话逐句拆解（v1.1-r1 改，此前一句读不出）：**不摘组时**（＝§4.1 #2 的同一口径）M2 红 3/3、M9 红 23/23、M10 红 1/1，即这三条**正常**；**摘掉 `g8` 后** M9 → 红 **0/23**、M10 → 红 **0/1**（这两条的判据面全在 G8 组内 ⇒ 判别力归零），而 M2 **仍 3/3**（证明摘组只废掉键类型面、没有全局误伤）；此状态下整跑 `_mutation_baseline()` → **返回 1**，FAIL 列 M3/M4/M7/M8/M9/M10 | 断言数 / 自证返回码 |

**§4.1 #5 与本节这一行是同口径还是另一口径（v1.1-r1 明确）**：#5 是**我**在**同一装置**上跑的**窄版**——
只保留 M9/M10 两条变异 + 摘掉 `g8`，验证「判据归零 → 自证转红（返回 1）」这一因果；本节这一行是**工作流**跑的
**全量版**——10 条变异全在、摘掉 `g8`，给出的额外信息是「FAIL 列恰好是 M3/M4/M7/M8/M9/M10 这六条」（即哪些
变异依赖 G8 组）。两者结论一致（M9/M10 归零、自证转红），口径差在**变异条数**。

---

## 5. 独立复核判定与它列出的 uncovered

### 5.1 判定与来源

**独立复核结论 = ACCEPT。** 来源标签：**工作流采集·独立复核**——本报告只拿到工作流转述的装置描述：
全部实验在**系统 temp 的合成库**（`%TEMP%\i43rev_a`，跑完已删；含 `git archive HEAD` 导出树与源码级还原副本）；
工作区**只读**：结束时 `git status`/diffstat 与起始快照逐字一致（9 文件 345+/33−——**「9」的出处见 §6.3**）、
`data/policy.json` sha256 `3d41a52fca3bddeb` == HEAD；未 `git add/commit/push`。

**本报告能亲验的两项**：`data/policy.json` 的 sha256 我重算＝`3d41a52fca3bddeb`（与 HEAD 相同）；`git diff --stat`
我重跑＝`9 files changed, 345 insertions(+), 33 deletions(-)`。**其余（装置、命令、产物）本报告无法复跑**。

复核认可的实据（**逐条标标签**，v1.1-r1 补——此前四条混排在同一节，读者要自己回填）：

1. **修前各腿输入 vs 现行树**（`probe_legs.py`，判据＝`os.walk` 独立**字节扫描**落盘面，不是「没抛异常」；含正对照证明扫描器有判别力）——**标签：工作流采集·独立复核（本报告未跑）**：
   - HEAD 树（真修前）：env 未设 → `load_rulebook()=={}`、`_rule_check→DEFER`、写入 `moved_to=review_queue` 且 `inbox.jsonl` 字节面命中合成凭据+标记；坏路径四形态（不存在/目录/非法 JSON/顶层数组）同样 `review_queue`+明文；标量键 `{"forbidden":1}`/`{"required":true}` → evidence「验证器异常：TypeError…」+`review_queue`+明文；`{"forbidden":"sk-Zz9…"}` → evidence「命中禁止规则：s」（按字符建规则）。
   - 现行树同输入：坏路径四形态与 `int`/`bool`/`str` 标量键一律 `moved_to=policy_unavailable`（code＝`policy_not_found`/`policy_unreadable`/`policy_invalid_json`/`policy_not_object`/`policy_bad_shape`×3），落盘仅 `_keys.json`+lock（2 文件）、secret/mark 字节命中 False、无 `knowledge/<id>.md`、响应体不含凭据；env 未设 → 包内默认生效 → `rejected`/`REJECT`。
   - **补强前中间态**（在 temp 副本上 7 处源码级定点还原）：真子进程 `--show-config` 对 `{"forbidden":1}`/`{"required":true}` **rc=1、stdout 0 字节、stderr 末行 TypeError**；无参启动 rc=1；写入面退回 `review_queue`+明文；`str` 形态不抛（rc=0）。
2. **合法输入逐位一致**（**标签：工作流采集·独立复核（本报告未跑）**）：同策略（仓库 `data/policy.json`）两侧对照——`audit.audit` / `_rule_check` / `redact_forbidden` 对 11 文本×4 kind + rules 结构：HEAD（显式指向）vs 现行 → 输出 **10811 字节 IDENTICAL**（逐字节 diff）；写入链落盘文件集同集、evidence 与 `moved_to`/`state` 相同，`_audit.jsonl`/`_index.json`/`rejected/rej_<ID>.md` 归一化后逐字节一致；**残留差异仅** session id（`sess_df77…` vs `sess_0ddf…`）与 `_keys.json` 的随机密钥材料/nonce。
3. **守卫本体与变异自证**（**标签：工作流采集·独立复核；其判据面已由本报告亲跑同口径复现**——与 §4.1 #1/#2 同口径，
   我独立跑得同一结果）。
4. **不得静默可观测面**（**标签：工作流采集·独立复核（本报告未跑）**；其中 `ANCHOR-MISS`/`INJECT-MISS` 的
   fail-closed 语义我已用**内存探针**在现行树独立验证，见 §4.1 #3/#4）：`ANCHOR-MISS` → 返回 2；`INJECT-MISS` → 返回 2；来源三面（真子进程 8 种策略形态：`unset`/`missing`/`badjson`/`notobj`/`empty`/`kint`/`kbool`/`kstr`）：启动 stderr 报来源行或 `⚠ 写入策略不可用（来源=env code=policy_bad_shape）…写入将 fail-closed`；`--show-config` 全部 rc=0 且 stdout 209–558 字节含 `policy{source,available,error.code}`；`op=info` 的 `write_policy` 全部给出 `source`/`available`/`code` 且 `surface=True`。

### 5.2 它列出的 uncovered（复核显式标出的面）

复核的 ACCEPT **未附「残余缺陷」清单**；它显式标出的是**守卫自身未单列、由复核另测**的成形面与两处归属：

| # | uncovered | 复核结果 |
|---|---|---|
| (a) | 形状闸的**其余成形面**（守卫断言未单列）：`required_kinds` 标量、**一列表一键标量**的混合策略、`required_labels` 对象 | 均 `policy_bad_shape` + 写入 `policy_unavailable`，且**字节面零正文** |
| (b) | **未知键**（`{"unknown":5}`）是否参与形状判定 | **不参与**（`available=True`，正常写入）——白名单式口径，与 `POLICY_LIST_KEYS` 注释一致 |
| (c) | G8-H（消费面纵深）的判别力**只由 M10 单独承担**，正常路径不经该面（形状闸在前） | 与 M10 声明 1/1 相符；即该条是**纵深防御**的判据，不是主路径判据 |
| (d) | `md_cg.test_p27_docindex` 的失败归属（**非本改动**） | 复核用 `git HEAD` 纯导出树实验归属：纯树 p27 通过 98/失败 0；仅放入未跟踪的 v1.0 报告文档 → 同样 7 条失败（`max_nodes=2000` 扫描窗被语料卡数推过）——**与 §4.3 我亲跑的同口径实验结论一致** |
| (e) | 易变字段残差 | 逐位一致对照中**仅** session id 与 `_keys.json` 随机密钥材料/nonce 不同（其余逐字节一致） |

---

## 6. 边界与未覆盖

### 6.1 本轮明确不修、留池的面

| 留池面 | 现状（读码 / 实测） | 为何留池 |
|---|---|---|
| **非 ACCEPT/REJECT 出口的脱敏与落盘**（issue #43 的病态出口本体） | `md_cg/writepipe.py:252-256` 仍原样 `cg.propose`；`md_cg/mdcos.py` 仍逐字落 `inbox.jsonl`。本轮**未改**该出口，只把**畸形/不可用策略**这一支的触发面收窄（fail-closed） | 是否给 `inbox.jsonl` 也做脱敏是**新的语义决策**（会削弱审核者看到原文的能力），须单独立项 |
| **显式空策略 `{}` 的残留通路** | 空 dict 是**可用**策略（`md_cg/audit.py:149` 生效条件注释），`text` 仍 `→ DEFER → review_queue → inbox.jsonl` 逐字明文 | 「无规则不能假装合规」是既有契约；空策略是**部署方的显式选择**，本轮不改其语义 |
| `src/init.ts` 不生成 `MDCG_POLICY_FILE` | 工作流 v1.0 报告已读码确认缺席；**本轮未动** | 是否补该 env 属发布决策（本报告无证据判断是否「有意缺席」） |
| `hive/serve_start.py:658` 的同名 `--show-config` 与 `md_cg.mcp_server --show-config` 口径统一 | 本轮未动（两处各自存在） | 跨模块命名/语义统一不在本 issue 范围 |
| **历史 `inbox.jsonl` 中已落的明文凭据** | 本轮未处置，工作流亦未发现任何处置动作 | 属运行方/发布决策；本报告只能指出这一支**未处置** |
| `md_cg.test_p27_docindex` 的现存红项 | 现行树唯一失败模块；归属已实测（§4.3）：工作区文档语料卡数越过 `max_nodes=2000` 扫描窗——本报告落盘后实测 `scanned=2055`、`取样 2055 卡`、`通过 91 / 失败 7` | 与键类型闸**无因果**；是否调扫描窗或另择归档位置属独立课题，**本轮不修**（该红项会持续，见 §8-Q6） |

### 6.2 未覆盖 / 未验证（如实）

- **容器两栈**：`docker … scripts/linux_verify.sh`（21 pass/0 fail、38 pass/0 fail）与 node 侧容器栈（rc=0、3 skipped）**本报告未跑**，只转述工作流数字。理由：跑它们会向仓库写入构建产物（`target/`、`lib/`、`node_modules` 等），超出本次「只写报告文件、不改工作区」的硬边界（上一份报告对同一限制的处置相同）。
- **补强前中间态本体**：磁盘上不可得（§0.2），14 条复现腿与 `--show-config` rc=1 / 启动 rc=1 的「修前」形态均为**工作流采集**，本报告未重跑。（能否用 stash/反向 patch 重建＝**不能**，见 §8-Q8。）
- **独立复核的装置与命令**：不可复跑（`%TEMP%\i43rev_a` 已删）；§5.1 的 1/2/4 三条与 §5.2 全部条目均为转述。本报告只亲验了它的两项收尾数字（policy.json sha256、diffstat）。
- **`probe_legs.py` / `probe_oracle.py` / `probe_bytes.py` 等探针脚本**：未随工作流留下，未重跑。

### 6.3 足迹披露

- 本报告亲跑的探针与套件：全部临时根在系统 temp（`%TEMP%\i43v11_*`）；`git archive` 导出树亦在 temp。
- 跑 `python -X utf8 scripts/run_tests.py --jobs 4` 与 `-m md_cg.test_p27_docindex` 会在仓根留下**测试暂存目录
  `_md_cg_p27/`**——已由 `.gitignore:33`（`/_md_cg_p*/`）忽略（`git check-ignore -v` 实测命中）。
- `git status --short` 的**两个时刻**（v1.1-r1 澄清，此前两句自相矛盾）：**本报告落盘前**＝10 个 `M` + 3 个 `??`
  （3 个未跟踪项＝`.zcode/`、v1.0 报告文档、新守卫文件），与起始快照**逐字一致**；**落盘后**＝10 个 `M` + 4 个
  `??`，**唯一新增项＝本报告文件本身**。即「与起始快照逐字一致」是对**落盘前**说的，不是对落盘后。
- **「9 文件 345+/33−」与「10 个 `M`」的差（v1.1-r1 补解释，此前未交代）**：`git status` 标记 10 个已跟踪文件为
  `M`，而 `git diff --numstat` 只计入 **9** 行——`package-lock.json` 是**stat 脏**（mtime/索引元数据变动，内容零差异），
  故 `--numstat`/`--stat` 不列它。本报告亲跑 `git diff --numstat` 的逐文件输出为
  `README.md 3/3`、`md_cg/audit.py 206/15`、`md_cg/mcp_server.py 67/1`、`md_cg/test_linkref.py 10/3`、
  `md_cg/test_mr_m2.py 15/3`、`md_cg/test_p2_mcp.py 12/1`、`md_cg/test_writepipe.py 10/4`、
  `md_cg/writepipe.py 21/3`、`package.json 1/0`（合计 345/33），`package-lock.json` **不在其中**。
- 本报告只新增 `docs/eval/issue43_默认策略与键类型闸_v1.1.md` 一个文件；**未改任何源码、未 `git add/commit/push`、未写入任何在役记忆数据根**。

---

## 7. 结论

1. **缺陷成立且已收口**：策略文件「合法 JSON 对象 + 列表型键取标量」这一形态，修前让**诊断面崩**（`--show-config` rc=1、stdout 空）、**启动面崩**（server rc=1、记忆面整体不可用）、**写入面失守**（`TypeError` 被兜底吞成 `DEFER` → 正文含凭据逐字入 `inbox.jsonl`）、`str` 形态**静默误判**（长度当计数、单字符规则误杀）。本轮以「形状非法 ⇒ 策略不可用 ⇒ 提案入队前 fail-closed」一个出口覆盖三面，并把三处调用面异常收成同形状的自描述（**该兜底分支本身在本轮未被实测触发**——`unavailable_report` 的产出条件与 `code` 的嵌套位置见 §3.2 末的如实标注与 §4.2 #12）。
2. **验证**：守卫 **71/71**（含新增 G8 24 条）、10 处定点变异**恰好**命中声明数、`ANCHOR-MISS`/`INJECT-MISS` 均 fail-closed 返回 2、删 G8 组后判据归零且自证转红——**均为本报告亲跑**（共 **13 项检查 + 1 组归属实验**，清单见 §4.1/§4.2/§4.3）。python 全量 **257/258**，唯一红项经亲跑实验归属为**与本改动无关**（工作区文档语料越 `max_nodes=2000` 扫描窗）。
3. **独立复核 ACCEPT**（工作流采集·独立复核），其列出的 uncovered 均为「守卫未单列、由复核另测」的成形面与两处归属，未附残余缺陷清单。
4. **留池面共 6 支（v1.1-r1 改正：此前只总结「三支」而 §6.1 列了 6 支，属结论漏项）**，按性质分两类：
   - **本 issue 的风险面，仍未闭合（3 支）**：① 非 ACCEPT/REJECT 出口本身（`cg.propose → inbox.jsonl` 明文）未做脱敏/改落盘；② 显式空策略 `{}` 仍 `DEFER → review_queue` 明文入队；③ 历史 `inbox.jsonl` 中已落的明文凭据未见任何盘点/清理/轮换动作。
   - **范围外或运行方决策（3 支）**：④ `src/init.ts` 不生成 `MDCG_POLICY_FILE`；⑤ `hive/serve_start.py` 的同名 `--show-config` 口径未与 `md_cg.mcp_server` 统一；⑥ `md_cg.test_p27_docindex` 的现存红项（语料越窗，与键类型闸无因果）。
   ⑥ 之所以不并入「风险面」，是因为它不涉及凭据外泄；④⑤ 属发布/跨模块决策，本报告只陈述事实，不断言动机。逐支现状见 §6.1。

---

## 8. 读者问答（逐条回应读者反馈的 nextQuestions，v1.1-r1 新增）

| # | 问题 | 回答 | 证据 / 状态 |
|---|---|---|---|
| Q1 | 「13 条腿」是 13 还是 14？多出来/被排除的是哪一条？ | **14 条**。工作流交付的复现数组共 14 条条目、每条自带 `reproduced: true`；§2.1 的 L1–L4 与 §2.2 的 L5–L14 即其**逐条**转写，**无一条被排除**（L9 是数组内标注「对照，不崩」的独立条目；L14 是一条目内含 in-process + 真子进程两形态，仍是一行）。本报告四处写「13 条」是**我的计数错误** | 工作流交付的复现数组原文；§2 表；**已改正** |
| Q2 | §6.1 列 6 个留池面、§7 只总结「三支」——`init.ts` 与 `hive --show-config` 口径是有意不算还是结论漏了？`init.ts` 是否意味着默认部署根本没加载策略？ | 前半：**是结论漏项，已改为 6 支并分类**（§7-4）。后半：**不意味**。`init.ts` 只影响「部署方能否一键覆盖策略」——现行树 env 未设即回落**包内默认** `data/policy.json`（`md_cg/audit.py:192-198`），§4.2 #13 亲跑显示 env 未设时 `text` 写入按默认策略判 `REJECT` | 读码 `md_cg/audit.py:171-198`；亲跑 §4.2 #13；v1.0 报告 §6.1 |
| Q3 | 默认部署（env 未设、走包内默认）下含凭据正文还会不会明文进 `inbox.jsonl`？原始危害还剩多少？ | **会，但只在非 ACCEPT/REJECT 出口**。亲跑（§4.2 #13，临时库根、默认策略、合成哑凭据）：`content_kind='text'` → 命中禁表 → `REJECT`、`inbox` **0 字节**、全库字节面零凭据；**省略 `content_kind`** → `BLINDSPOT` → `review_queue`，`inbox.jsonl` **342 字节且含凭据与标记**。故原文危害由「默认链路恒命中」缩小为「`BLINDSPOT`/`DEFER` 支路命中」（空/未知 `content_kind`、未注入验证器的类型、显式空策略 `{}`） | 亲跑 §4.2 #13；读码 `md_cg/writepipe.py:252-256` |
| Q4 | 历史 `inbox.jsonl` 的明文凭据：有无盘点/清理/轮换计划？会不会随工作区扩散？ | ① **未见任何针对 `inbox.jsonl` 明文凭据的盘点/清理/轮换动作**：本报告亲跑 `git grep -n -i "轮换\|rotate\|凭据清理\|清理凭据\|inbox.*清理"`（域：`*.py *.md *.ts`），命中项全属**其它课题**（`md_cg` 审计日志轮转、`scripts/bootstrap_loop.py` 日志轮转、DEK `rotate_dek`、蜂巢身份轮换），无一条涉及该队列；也没有任何清单。② 「会不会扩散」**本报告无法回答**——硬边界是**不读任何在役数据根**，故既无在役 `inbox.jsonl` 的清单、也无其字节面证据 | 亲跑 `git grep`（命令与结论如上）；**在役面=未验证/未读**（v1.0 报告 §7-Q3 同结论） |
| Q5 | `unavailable_report` 的形状在所有实测里都没出现——是死代码吗？契约⑦⑧⑨的「同形状」是否名不副实？ | ① **未观测到产出**：正常路径第一道形状闸先返回 `policy_bad_shape`（§4.2 #7）；把第一道闸关掉后，第二道防线 `_policy_list` 仍让 `policy_report()` 不抛（§4.2 #12）⇒ **我构造不出触发它的输入**，故既不能说它死、也无实测形状可给。② 「同形状」在**代码结构上**成立（三处调用面都调 `audit.unavailable_report`：`md_cg/mcp_server.py:3812-3813`、`:2148-2149`），但它**未经实测**；其形状（读 `md_cg/audit.py:201-213`）＝顶层 `source=unavailable`/`available=false`，`code=policy_report_failed` **嵌在 `error` 下**（顶层无 `code` 键） | 亲跑 §4.2 #7/#12；读码；§3.2 末「如实标注」 |
| Q6 | p27 会长期红吗？该不该本轮就调窗或换归档位置？ | **会**。现行树（含本报告）亲跑实测：`scanned=2055 > max_nodes=2000`、`truncated=True`、`通过 91 / 失败 7`（§4.3）。**本轮不调**——调 `max_nodes` 或改归档位置会动**源码/部署约定**（超出「只改报告文件」的边界），且该红项与键类型闸无因果。可选动作两类（**均非本报告决定**）：调 `prune` 的 `max_nodes`；或把评测报告归档到 `docs/` 之外 | 亲跑 §4.3；读码 `md_cg/test_p27_docindex.py:54-57`（`_BASE`/`ROOT`/`DOCS` 取自仓内 `docs/`） |
| Q7 | 容器两栈能否改用只读挂载 + 临时输出目录跑一次？ | **本轮未跑**。我没有改造 `scripts/linux_verify.sh` / node 侧容器栈的产物落点（改造＝改脚本，越出边界），故「只读挂载 + 临时输出」是一个**我未验证可行性的建议**，不是实测结论；§6.2 仍只转述工作流的 0/0 | **未跑**；可行性**未验证** |
| Q8 | 能否用 stash / 反向 patch 重建补强前中间态，让那批行号可复核？ | **不能（本轮）**：亲跑 `git stash list` → **空输出**（无 stash），且首轮与本轮的改动**混在同一份未提交 diff** 里——本报告没有「本轮变更」的 patch（只有按行区间写的清单），反向撤销得到的是**近似副本**，其行号不能等价于工作流当时的行号。故 §1.2 的补强前行号继续标「工作流所报，未重推导」 | 亲跑 `git stash list`（空）；§0.2 |
| Q9 | `resolve_rulebook()` 与 `_read_policy_file` 是同一函数的两个叫法吗？形状闸接在哪一层、哪一行？ | **不是同一函数**。形状闸在 `_read_policy_file`（现行树 `md_cg/audit.py:165-167`）；`resolve_rulebook`（`:172-198`）是**来源解析单点**（内部调前者）；`load_rulebook`（`:248-256`）是兼容包装。故 L1 说「`resolve_rulebook()` 判为可用」正确——补强前它调用的 `_read_policy_file` **没有闸**，标量键就被判成可用。分工表见 §3.5 | 读码 §3.5；亲跑 §4.1 #11 |

---

## 9. 本次修订记录（v1.1 → v1.1-r1）

| 读者反馈 | 处置 |
|---|---|
| §3.1 契约编号从 ⑤ 起、①–④ 无交代 | §3.1 新增前表：①–④ ＝ v1.0 报告 §3.2 的 C1–C4（逐条给 v1.0 的契约名与落点），并说明 ⑤–⑨ 为接续编号 |
| §1.1「同行」指代不明 | 该格改写：把同一 `TypeError` 在**三个调用面**各炸一次逐面写清（含 `mcp_server.py:3927`/`:3811`/`audit.py:284-285`、`:561-562`） |
| §4.4「不删时 M2/M9/M10 正常」读不出 | 该行逐句拆解（不摘组时 M2 3/3、M9 23/23、M10 1/1；摘 g8 后 M9 0/23、M10 0/1、M2 仍 3/3），并新增一段说明它与 §4.1 #5 的**同口径/不同范围**关系 |
| L14 的 `cg` 对象未交代、与 §3.4 的降级理由并读矛盾 | §3.4 改写为三层链路（工具面缺工具 / 模块无 `cg` 属性 / 等价路径需在役数据根），并给 `cg` 的出处：`call_tool(cg, "cg", …)` 的第一参＝认知图实例（守卫里由 `md_cg/test_issue43_default_policy.py:140-143` 的 `_cg(root)` 返回 `MdCGSecure`；模块签名实测 `call_tool(cg, name, args)`） |
| M1/M2/M5/M6 变异内容未给 | §4.1 新增 **M1–M10 变异定义表**（靶函数 / 原始行 / 替换行 / 声明红项 / 实测），逐条出自 `md_cg/test_issue43_default_policy.py:736-792` |
| 修复面「6 处 vs 8 行」口径不一 | 摘要表与 §3.2 统一为**行区间**口径并给出对照说明（命名单元 6 ＝ 行区间 8 的折叠） |
| §4.2 #7 的 `required: 0` 未解释 | 新增解释段：不可用 ⇒ `rules=None` ⇒ `_policy_list(None,…)=[]` ⇒ 计 0；口径＝「实际生效的规则条数」（引 `md_cg/audit.py:240-241`、`:209-210`） |
| §0.3 只定义进程 rc、量纲栏却写「退出码」 | §0.3 新增第 4 条定义「自证返回码」（函数返回值，经 `:843-845`→`:865` 透传为进程退出码）；§4.1 #3/#4/#5 的量纲栏同步改为「自证返回码」 |
| 兜底 `except` 三处叫法不一 | §1.2 新增澄清段：§1.1「验证器兜底 `except`」＝§3.2「`audit()` 兜底 `except`」＝`md_cg/audit.py:561-562`，**同一站点** |
| L12/L13 的 `audit.py:199-202` 未在站点表出现 | S2 行补「其下游 `REJECT` 出口＝`:199-202`（L12/L13 所报分支）」；现行树对应处为 `:288-291` |
| 「13 条腿」与 14 行矛盾 | 四处「13 条」→**14 条**，并在 §2 开头新增腿数口径说明（含「无一条被排除」与 L9/L14 的性质） |
| 摘要「亲跑 6 项」与 §4.2 排到 11、§4.3 又是一组不符 | 摘要表改为「**13 项检查 + 1 组归属实验**」，并写明构成（§4.1 #1–#6、§4.2 #7–#13、§4.3）；§4.2 标题标出行号续 7–12 |
| 「9 文件」与「10 个 `M`」并存无解释 | §5.1 指向 §6.3；§6.3 新增说明：`package-lock.json` 是 **stat 脏**（`git diff --numstat` 不列），并给出 9 个文件的逐文件 numstat（合计 345/33） |
| §6.3「逐字一致」与「唯一新增项」自相矛盾 | §6.3 改为**两个时刻**口径：落盘前＝10 `M` + 3 `??`（与起始快照逐字一致）；落盘后＝10 `M` + 4 `??`（唯一新增＝本报告） |
| G8 的 24 条不可推导 | §3.2 该行给出算式与行号：3 形态 ×（A/B/C/C2/D/E/F = 7）= 21，加 G/H/I = 24（逐条给 `g8()` 内的行号） |
| `unavailable_report` 形状无实测支撑 | §3.2 末新增「如实标注」（未观测到产出、`code` 嵌在 `error` 下、三处共用是结构事实非实测）；§4.2 新增 #12 亲跑（关闸后仍不抛）；§8-Q5 汇总 |
| 三个装载函数名并存无出处 | 新增 §3.5 分工表（`_read_policy_file`/`resolve_rulebook`/`load_rulebook` 的现行树行号与 HEAD 有无），并点明 L1 的说法成立 |
| §7 结论「三支」与 §6.1 六支不符；G4c 无实测 | §7-4 改为 6 支并分类（风险面 3 支 / 范围外 3 支）；§3.3 补 G4c 实测（`python -X utf8 -m md_cg.test_policy_required_ccg` → 28 pass / 0 fail，rc=0，用例在 `md_cg/test_policy_required_ccg.py:256-257`） |
| §5.1 四条的标签要读者自行回填 | §5.1 逐条加「标签：工作流采集·独立复核」；第 3 条另标「其判据面已由本报告亲跑同口径复现」 |
| nextQuestions 9 条 | 新增 §8 逐条回答（含 Q3 亲跑新增 13 号检查、Q8 亲跑 `git stash list`、Q6 亲跑现行树 p27 数字） |
