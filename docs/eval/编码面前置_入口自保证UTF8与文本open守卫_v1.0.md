# 编码面前置批：入口自保证 UTF-8 与文本模式 open 守卫（工程报告 v1.0）

| 项 | 值 |
|---|---|
| 批次 | 编码面前置批 = A 入口自保证 UTF-8 ＋ B 文本模式 `open` 守卫与存量订正 |
| 基线 HEAD | `174cd25f1e07eb873924b867dc1b14d7d758ab0b`（feat/opt(batch3)） |
| 工作树 | 未提交：14 个 `M` ＋ 6 个 `??`（本批新件 4 个：`utf8_boot.py`、`scripts/test_utf8_boot_guard.py`、`scripts/verify_open_encoding.py`、`scripts/test_verify_open_encoding.py`；另 `.zcode/` 与本报告文件本身）。本批未 `git add` / `commit` / `push` |
| 纪律依据 | 工作纪律第 15 条（全仓文本与路径一律 UTF-8；裸 `open` 走 locale 即 cp936） |
| 行号口径 | **正文行号一律为本报告作者本次读码所见的工作树当前态**；凡与批内早期回报不一致处均点名漂移（如 kill 标志行由 `:653` 漂到 `:673`；批内另出现的中间读数 `:671` 的来源处置见 §2.2 B9）。§2 的 `观察` 列保留读数原文（含当时行号） |
| 读数来源标记 | `【采集】`= 工作流采集/批内实跑记录；`【复核】`= 两项独立复核的读数；`【本次】`= 本报告作者本次实跑/读码所得 |
| 凭据 | 本报告不含任何凭据明文（本会话环境存在一个已失效的 `MDCG_TOKEN`，值一律不抄录） |
| 修订 | **第 2 版（读者反馈处置轮）**。相对第 1 版的改动：新增 §1.3（两套编号对照）、§4.4 的 clean env 全量读数、§4.5 第 9–15 条（本轮新增实跑）、§7（读者待决问题 10 条的判定与建议）；订正 §2.2 B1 的 HEAD 计数（437/407→427/397）、§4.3 的结论措辞、§6.1 的论证结构（删去不成立的算术旁证）；补 §2.1 A13/A13′ 的令牌闸前置、§4.1 的物化面口径与 M1 红项集成因、§6.3/§6.4 的实测后果；附清单补齐 14 个 `M` 的逐件归属。逐条处置对照见 §7 |

> **本件与同路径上一版的关系**：本路径此前是一份**设计稿**。该稿把 F2（fail-fast 指引不可照抄）、
> F3（三流显式传递无判据）、F6（被 import 时重启的静默危害）记为**未修**，与现树不一致
> （三条均已修且已被守卫覆盖，见 §3.1）。本工程报告据现树与本次实跑**覆盖该稿**，读者以本件为准。
> **披露（第 2 版补）**：该设计稿当时是 `??` 未追踪件（无 git 历史），被本件首版覆盖后**已无留存副本**
> （`docs/eval/` 下无第二份「编码面…」文件，`git log -- <本路径>` 无输出）；如需保留设计稿内容，
> 只能从会话记录/批内采集文本重建，处置建议见 §7-Q8。

---

## 0. 摘要与结论

本批把「Python 侧文本 I/O 与进程入口的 UTF-8 正确性」从**环境约定**（`PYTHONUTF8=1` 挂在
使用者 profile 与「每个入口记得设」上）改成**进程自保证 ＋ 机械守卫**：

- **A · 入口自保证 UTF-8**：新增仓根助手 `utf8_boot.py`（纯 stdlib、零 `md_cg` 依赖），
  七个进程入口在任何文件/库 I/O **之前**调用 `ensure_utf8(__file__)`；解释器未开 UTF-8 模式时
  由助手以 `[exe, -X, utf8, ...]` **重启自身**（保留 `-m` 语义、显式传递三条标准流），
  或用显式退出通道 fail-fast。守卫 `scripts/test_utf8_boot_guard.py`。
- **B · 文本模式 `open` 守卫与存量订正**：新增 AST 守卫 `scripts/verify_open_encoding.py`
  （**只认内建 `open`**）与回放断言 `scripts/test_verify_open_encoding.py`；三目录内
  **9 处**真实文本模式裸 `open` 逐点订正为显式 `encoding="utf-8"`，基线清零。

**结论（全部为本次实跑读数，命令与输出见 §4.5）**

| 面 | 读数 | 来源 |
|---|---|---|
| A 守卫 `scripts/test_utf8_boot_guard.py` | **24/24 通过**（正向 11/11 ＋ 定点变异 13/13）、rc=0、耗时 21.8s | 【本次】 |
| A 守卫 `--no-mutations` | 11/11 通过、rc=0、1.3s | 【本次】 |
| B 守卫 `scripts/verify_open_encoding.py` | rc=0：扫描面 489 文件 / 文本 `open` 844 / 二进制 `open` 92 / Attribute `.open` 66 | 【本次】 |
| B 守卫 `--self-test` | rc=0：判据锚 22/22、Attribute 对照 5 文件、**契约点名假阳性点位 5/5**、定点变异 3 目标 × 4 变体 | 【本次】 |
| B 回放断言 `scripts/test_verify_open_encoding.py` | **ALL PASS**（26 条 `assert`）、rc=0 | 【本次】 |
| B 守卫**自身**在 clean env（无 `PYTHONUTF8`、无 `-X utf8`） | **rc=1 ＋ 打印 `✔` 时 `UnicodeEncodeError` 崩溃 ＋ stdout 落 GBK 字节**（第 2 版新增实测；`rc=1` 与「存在违例」同码 ⇒ 会误导） | 【本次】§6.3/§7-Q7 |
| python 全量（clean env 重跑） | **269/269 通过**、5 跳过、rc=0、100.7s，且 runner 自身输出**合法 UTF-8** | 【本次】§4.4 |
| 独立 AST 复核（本报告作者自写扫描器） | 工作树 489 文件 / 二进制 92 / 文本裸 `open` **0**；HEAD 物化树 486 文件 / 二进制 **89** / 文本裸 `open` **9** | 【本次】 |
| python 全量 `python scripts/run_tests.py` | **269/269 通过**，5 跳过（依赖缺失/平台不符），rc=0，101.7s | 【本次】 |
| 容器两栈 | 退出码 **127 / 127**（两栈均未取得有效读数） | 【采集】——本轮**未复跑**，且本机 Docker daemon 未运行（§4.4） |
| 独立复核判定 | A **ACCEPT** ／ B **ACCEPT** | 【复核】 |

**三句结论**
1. 两项守卫在本次实跑中全绿（A 24/24、B 26 assert ALL PASS），A 的 13 项定点变异**逐项**命中预期红项集与退出码
   ——**这些绿读数都在「已开 UTF-8 模式的现场」取得**；B 守卫**自身**在未设 env 的现场会崩并吐 GBK 字节
   （上表倒数第 6 行、§6.3），那是**守卫自身**的缺陷，不影响「存量缺口已清 0」的结论。
2. 文本裸 `open` 真缺口数经逐点读码由契约的「11」收敛为「9」并已 100% 订正；另 2 处是**误分类**
   （模块内自建 `write_text` 函数的调用，编码早已显式；机械照做会 `TypeError` 打断脚本）。
3. 旧口径 `224` **出处不闭环且不可复现**（无命令/口径留存，§6.1），`103` 可精确复现但**混入 5 处非内建 `open` 语义**
   （`os.open` / `io.open` / `gzip.open` / `tarfile.open`×2）故不可作缺口判据；唯一能同时对上源码、
   且能逐点对到行号的是「**89 处内建二进制 ＋ 9 处文本真缺口**（＋5 处 Attribute 假阳性 = 103）」。

---

## 1. 两项各自的定义与真实站点

### 1.1 A · 入口自保证 UTF-8

**定义**：每个进程入口在其自身进程内、且在**任何文件/库 I/O 之前**调用
`utf8_boot.ensure_utf8(__file__)`；当解释器未开 UTF-8 模式时，由助手以 `-X utf8` 重启自身
（保留 `-m` 模块语义、显式传递 stdin/stdout/stderr），或按显式退出通道 fail-fast 退出。
正确性不再挂在「环境变量 ＋ 每个入口记得设」上。

**助手站点**（[utf8_boot.py](../../utf8_boot.py)，238 行 / 15 356 B / 无 BOM【本次】）：

| 落点 | 行 | 语义 |
|---|---|---|
| `ensure_utf8()` 定义（唯一调用点） | `utf8_boot.py:201` | 三分支见下 |
| 置子进程继承面 `_set_child_env()` | `:101-104`，调用点 `:218` | `PYTHONUTF8=1` ＋ `PYTHONIOENCODING=utf-8` 写入 `os.environ`（**先置再判**，与契约④字面优先） |
| ② utf8 已开 ⇒ 立即返回 | `:219-220` | 不重启、不打日志 |
| F6 被 import ⇒ 只置 env 即返回 | `:221-222`＋`_caller_is_process_entry()` `:136-149` | 用「调用帧 `f_globals` is `sys.modules['__main__'].__dict__`」的**同一性**判定；`-m` 与直跑文件同判 |
| ③ fail-fast | `:224-226`（`LINGSHU_UTF8_NO_REEXEC` 真值 ⇒ 指引＋`SystemExit(2)`）；常量 `NO_REEXEC_ENV :83`、`EXIT_UTF8_REQUIRED=2 :85` | 指引文案见 `_guidance() :164-181` |
| 重启 | `:227-237`：`reexec_argv() :153-160` → `subprocess.run(argv, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)` → `raise SystemExit(proc.returncode)` | `-m` 形态重建为 `[exe,"-X","utf8","-m",<模块名>,*sys.argv[1:]]`；`-c`/`-` 不重启，`SystemExit(3)`（`_EXIT_UNREBUILDABLE :91`） |
| 指引写 stderr | `_emit() :185-197` | 优先 `sys.stderr.buffer.write(text.encode("utf-8"))`，不随控制台代码页漂移 |
| 单点判别 `-m` 形态 | `_m_module_name() :108-119`，被 `launch_hint() :123-132` 与 `reexec_argv()` **共用** | F2 的修法本体：两处各写一份必然漂移 |
| 禁用 `os.exec*` | 模块 docstring `:55-58` | MCP 是字节组帧协议，重启必须显式传三流 |

> **本表的分支标号（②/③/F6）按代码执行顺序排**：`:218` 先置 env → `:219` 判 utf8 模式 → `:221` 判调用方是否进程入口 → `:224` fail-fast → `:227` 重启。
> §3.1 另用一套「路 0 / 1 / 2 / 3 / 3′」编号（取自助手模块 docstring `:25-36` 的既有编号，**不是**代码顺序）。
> 两套编号的**逐项对照表见 §1.3**，读者不必自行猜对应关系。

**七个入口的真实站点**（本报告作者逐文件读出【本次】；`_UTF8_ROOT` = 仓库根，形态照
`hive/exec.py::_md_cg_import` 的最小写法）：

| 入口 | 注释锚 | `_UTF8_ROOT` | `sys.path.insert` | `from utf8_boot import …` | `ensure_utf8(__file__)` | `def main` / `__main__` guard |
|---|---|---|---|---|---|---|
| `hive/hive_mcp/mcp_server.py`（ZCode/DSH 直连 stdio MCP） | `:50-58` | `:59-60` | `:61-62` | `:63` | `:65` | `:942` / `:964` |
| `md_cg/mcp_server.py`（认知图 stdio MCP） | `:46` | `:54` | `:55-56` | `:57` | `:59` | `:3837` / `:4038` |
| `hive/exec.py`（执行器子进程） | `:98` | `:106` | `:107-108` | `:109` | `:111` | `:1900` / `:2041` |
| `hive/orch.py`（编排器 worker） | `:56` | `:64` | `:65-66` | `:67` | `:69` | `:705` / `:800` |
| `hive/serve_start.py`（serve 拉起） | `:47` | `:55` | `:56-57` | `:58` | `:60` | `:668` / `:691` |
| `md_cg/run_tests.py`（包内全量入口） | `:42` | `:50` | `:51-52` | `:53` | `:55` | `:166` / `:227` |
| `scripts/run_tests.py`（源码树全量入口） | `:34` | `:41` | `:42-43` | `:44` | `:46` | `:177` / `:240` |

接线不变式：调用锚均**早于该文件首个模块级 `def`**，故也早于一切文件/库 I/O
（`hive/hive_mcp/mcp_server.py:54-55` 的注释点名了本文件模块级读 `package.json` 的
`_package_version()` 就在锚之后）。「注释锚」列的区间＝该入口的分隔注释行 ＋ 8 行 `约束` 注释块；
以 `hive/hive_mcp/mcp_server.py`（本报告作者逐行读出的原文）为例：
`:50` `# ---------------------------------------------------------------- 入口自保证 UTF-8`，
`:51` `# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8`。
其余六个入口的「注释锚」列只给该 `约束` 块的首行（分隔注释行即其上一行）。

**与既有的进程内守卫并存（两层各守一段）**：两个 MCP 入口 issue #39 的 `_force_utf8_stdio`
**原样保留**，仍是 `main()` 首行调用——`hive/hive_mcp/mcp_server.py:921` 定义 / `:942 def main()` /
`:943 _force_utf8_stdio()`；`md_cg/mcp_server.py:3694` 定义 / `:3837 def main()` / `:3838` 调用。
助手另加**进程级**保证（未开 utf8 模式则重启）与**后代继承面**（env），且助手内**不做**
stdio reconfigure（避免被 import 时产生进程级 stdio 副作用）。

### 1.2 B · 文本模式 `open` 的机械守卫与订正

**定义**：`md_cg/` `hive/` `scripts/` 下**全部** `.py`（含 `test_`/`bench_` 面）里，凡**文本模式**
的文件读写一律显式声明 `encoding=`；判据由 **AST** 承担，只认**内建 `open`**。

**守卫站点**（[scripts/verify_open_encoding.py](../../scripts/verify_open_encoding.py)，482 行 / 24 253 B / 无 BOM【本次】）：

| 落点 | 行 | 内容 |
|---|---|---|
| 判据 ①–④（docstring） | `:14-23` | ①只认 `ast.Name` 且 `id=='open'`；②字面 mode 含 `b` ⇒ 不计；③mode 缺失/非字面量/`**kwargs` ⇒ **计入**（保守：无法确认即不合格）；④`Path.read_text`/`write_text` 无 `encoding` ⇒ 计入，且点名 `write_text(p,text)` 形态的模块内自建同名函数**不是**本判据对象 |
| 扫描面 | `SCAN_DIRS = ("md_cg","hive","scripts")` `:59` | 三目录 |
| 白名单 | `WHITELIST: dict[str,str] = {}` `:63` | **空**；将来填入须双向报出，不留静默豁免 |
| ANCHOR 三类 | docstring `:25-35` | 判据锚（`_ANCHOR_CORPUS` 22 片段×预期违例数，`:99-…`）／扫描面锚（`_FLOORS` 下限 `:69-75`）／对照点位锚（`_ATTR_CONTROL_FILES` 5 文件 `:78-84` ＋ `_ATTR_CONTROL_POINTS` 5 点位 `:90-96`） |
| 退出码 | `:40` | 0 全绿／1 有违例（含白名单不吻合）／2 ANCHOR-MISS |

**存量订正的 9 处真实站点**（本报告作者逐行读出，现树全部已带 `encoding="utf-8"`【本次】；
括号内为 HEAD 行号，`hive/hive_mcp/mcp_server.py` 因 A 路插入锚块下移 20 行）：

| # | 现树站点 | HEAD 行号 | 形态 |
|---|---|---|---|
| 1 | `md_cg/test_n199_tokens_concurrent_write.py:157` | `:157` | `open(barrier, "w", encoding="utf-8").close()   # 对齐放行` |
| 2 | `md_cg/test_security_audit_v21.py:227` | `:227` | `open(p, "w", encoding="utf-8").close()`（上下文 `:226 p = os.path.join(base, fn)`） |
| 3 | `md_cg/test_security_audit_v21.py:231` | `:231` | 同上（`:232` 断言「不误伤」） |
| 4 | `hive/test_n144_exec_cmd_terminal_race.py:71`（折行至 `:72`） | `:71` | `hold = open(os.path.join(d1, "result.json.tmp"), "w", encoding="utf-8")` |
| 5 | `hive/test_n144_exec_cmd_terminal_race.py:117` | `:116` | `hold3 = open(os.path.join(d3, "result.json.tmp"), "w", encoding="utf-8")` |
| 6 | `hive/test_stop_tree_kill.py:127` | `:127` | `with open(cp, encoding="utf-8") as f:`（mode 缺失，默认 `'r'`） |
| 7 | `md_cg/test_lock.py:22` | `:22` | `with open(TARGET, encoding="utf-8") as f:`（mode 缺失） |
| 8 | `md_cg/test_lock.py:38` | `:38` | `with open(TARGET, encoding="utf-8") as f:`（mode 缺失） |
| 9 | `hive/hive_mcp/mcp_server.py:673` | `:653` | `open(flag, "w", encoding="utf-8").close()`（kill 标志文件；注释 `:662-663` 明写「仍显式声明 encoding —— 判据『凡文本模式一律显式』（B 项，零例外）」） |

即 6 处「字面 mode 文本 open」＋ 3 处「mode 缺失」，与契约清单的 **8＋3** 相比，
差额 2 处见 §6.1（判为误分类，未改）。

### 1.3 助手分支的编号对照（§1.1 的 ②/③/F6 ↔ §3.1 的路 0–3′）

**为什么加这一节**：同一段 `ensure_utf8` 体在两处用了两套编号、两种排序——
§1.1 的表按**代码执行顺序**标注（②＝utf8 模式已开早退，③＝fail-fast），
§3.1 的表按助手**模块 docstring `:25-36` 的既有编号**（路 0＝被 import、路 1＝utf8 已真…），
而 docstring 把「被 import」列为第 0 路，与代码里「被 import」判断排在 utf8 判断**之后**相反。
下表把两套编号与代码行一次对齐（行号＝`utf8_boot.py` 当前态，本报告作者读码所见）：

| 代码位置（按执行顺序） | 代码内容 | §1.1 表的标号 | §3.1 表的「路」 | 契约条款编号 |
|---|---|---|---|---|
| `:218` | `_set_child_env()`——**最先执行**，无分支 | 「置子进程继承面」行 | 「全部」行 | 契约④前半 |
| `:219-220` | `if sys.flags.utf8_mode: return` | ② | **路 1** | 契约②前半（＋同族「已开不重启」） |
| `:221-222` | `if not _caller_is_process_entry(): return` | F6 | **路 0** | 非契约原文（第一轮复核实测新增） |
| `:224-226` | `NO_REEXEC` 真 ⇒ 指引 ＋ `SystemExit(2)` | ③ | **路 3** | 契约③ |
| `:227`＋`:231-237` | `reexec_argv()` → `subprocess.run(三流)` → `SystemExit(rc)` | 「重启」行 | **路 2** | 契约②后半 ＋「必须显式传三流」的 must |
| `:228-230` | `argv is None`（`-c`/`-`）⇒ 指引 ＋ `SystemExit(3)` | 「重启」行末 | **路 3′** | 契约外偏离（已在回报中声明） |

一句话记法：**§1.1 按代码从上到下数；§3.1 按 docstring 的路号数；两套只差「被 import」与「utf8 已开」的先后。**

---

## 2. 修前现场（逐条 payload / 观察 / 站点）

> 标记：`【采集】`= 工作流采集的批内实跑读数（可直接引用）；`【本次】`= 本报告作者本次亲自
> 复现（命令与输出见 §4.5）。两列都有的条目表示同一事实被两条独立路径取到。

### 2.1 A 侧修前现场

| # | payload（怎么取） | 观察（读数） | 站点 | 标记 |
|---|---|---|---|---|
| A1 | 本机解释器直调 `locale.getlocale()`（读 Windows locale，不受 utf8 模式污染） | `('Chinese (Simplified)_China', '936')`；`sys.flags.utf8_mode=1`。clean-env 子进程（清 `PYTHONUTF8`/`PYTHONIOENCODING`、无 `-X utf8`）：`utf8_mode=0`、`getpreferredencoding_False="cp936"`、`stdout/stdin/stderr="gbk"`、`stdin_errors="surrogateescape"`；**两种情形 `sys.getdefaultencoding()` 恒为 `'utf-8'`** ⇒ 裸奔面是文本 I/O 层而非 str↔bytes 层 | Python 3.12.10（MSC v.1943 64bit）；本机解释器 | 【采集】【本次】读数逐字一致 |
| A2 | clean env 子进程里 `open(path,"w").write("中文復原テスト 😀")` | 缺省编码取 locale：`getpreferredencoding(False)="cp936"`，写盘抛 `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f600' …`；**另一形态（纯中文、无 emoji）静默落 GBK 字节且 rc=0**——本次复现：裸 `open(p,"w").write("中文标题")` 落 `b'\xd6\xd0\xce\xc4\xb1\xea\xcc\xe2'`，rc=0、无异常，再用 utf-8 读回 `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd6 in position 0`；加 `-X utf8` 则落 `b'\xe4\xb8\xad\xe6\x96\x87\xe6\xa0\x87\xe9\xa2\x98'`、读回 OK | Python stdlib 语义（探针在 `%TEMP%`） | 【采集】【本次】 |
| A3 | `os.environ` 直读 | `PYTHONUTF8='1'`、`PYTHONIOENCODING='utf-8'`、`PYTHONLEGACYWINDOWSSTDIO=None`、`LANG='C.UTF-8'`；本进程 `utf8_mode=1` ⇒ **本机没炸的第一层原因是环境变量**，正确性挂在环境上 | 会话环境 | 【采集】【本次】 |
| A4 | 修前树（`git archive HEAD` 导出）逐站点定位「三处入口自己钉的站点」 | ① `scripts/run_tests.py:88` `env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")`——**只对子进程生效**（`:81-82` 子进程 argv 另带 `-X utf8`）；② `scripts/linux_verify.sh:9` `export PYTHONUTF8=1`；③ `src/lib/mdcg_client.ts:117-118` `PYTHONIOENCODING:'utf-8'` / `PYTHONUTF8:'1'`（`:98-102` 注释明写各自作用面）。三处**都是给别人的**，入口自身无保证 | `scripts/run_tests.py:88` · `scripts/linux_verify.sh:9` · `src/lib/mdcg_client.ts:117-118` | 【采集】 |
| A5 | clean env 启动修前树的 stdio MCP 入口 `python -m hive.hive_mcp.mcp_server`，喂 UTF-8 的 initialize＋tools/list | rc=0；stdout 4 893 B 合法 UTF-8（含「灵枢」三字节 `\xe7\x81\xb5\xe6\x9e\xa2`），`as gbk: NO`；stderr 0 B ⇒ **修前树上这两个 MCP 入口的 stdio 面确已绿**（原因＝issue #39 的进程内守卫），本批要补的是**进程级保证与后代传播**，不是这两条的 stdio 面 | `hive/hive_mcp/mcp_server.py`（修前树 `:901` 定义 / `:923 main()` 首行调用） | 【采集】 |
| A6 | 对照：停用进程内守卫（`M._force_utf8_stdio = lambda: None; M.main()`），其余不变 | rc=0（**不抛异常**）；stdout 4 151 B，中文 description 落 `\xc1\xe9\xca\xe0\xb7\xe4\xb3\xb2…`＝「灵枢」的 GBK；`as utf-8: NO ('utf-8' codec can't decode byte 0xc1 in position 249)`、`as gbk: YES`。⇒ 后果形态 = **静默产出非 UTF-8 字节**（rc=0、无错误帧、宿主按 UTF-8 读即乱码） | `hive/hive_mcp/mcp_server.py:922 main()`（对照态） | 【采集】 |
| A7 | clean env 子进程从管道读一行 UTF-8 中文，按 `sys.stdin` 缺省解码并回读 | `stdin_encoding="gbk"`、`stdin_errors="surrogateescape"`；解码得含孤立代理串 `'\udcad文復原テスト'`，该串再 `encode('utf-8')` 抛 `UnicodeEncodeError: … 'udcad' … surrogates not allowed`。`surrogateescape` 使坏数据**不报错**进入内存 ⇒ 读侧静默面；这正是 `_force_utf8_stdio` docstring 描述的崩溃机制（读侧解出 `\udcXX` → 写侧 `ensure_ascii=False` 编码炸） | Python stdio 缺省 | 【采集】 |
| A8 | 修前树 clean env 跑**五个无守卫入口** | ① `python -m md_cg.run_tests --list` rc=0、stdout 10 446 B、`as utf-8: NO (byte 0xb9 @10435)` / `as gbk: YES`；② `python scripts/run_tests.py --list` 逐字节相同；③ `python -m hive.serve_start --show-config` rc=1、stdout 1 930 B 含 `\xa3\xa8`（GBK 的「（」）；④ `python -m hive.exec --help`、⑤ `python -m hive.orch --help` rc=1，走 `read_spec` 抛 `FileNotFoundError`（无 `job_dir`，只读无副作用），二者模块内 UTF-8 关键词命中数 0 ⇒ **五个入口自身零自保证，直接走 GBK** | `md_cg/run_tests.py` · `scripts/run_tests.py` · `hive/serve_start.py` · `hive/exec.py` · `hive/orch.py` | 【采集】 |
| A9 | 七个入口逐个机械审计（UTF-8 关键词命中 ＋ `def main`/`__main__` guard 定位，修前树） | ① `hive/hive_mcp/mcp_server.py` 命中 8 ⇒ **有**（`:901`/`:923`）；② `md_cg/mcp_server.py` 命中 8 ⇒ **有**（`:3677`/`:3821`）；③ `hive/exec.py` 命中 **0** ⇒ 无；④ `hive/orch.py` **0** ⇒ 无；⑤ `hive/serve_start.py` **0** ⇒ 无；⑥ `md_cg/run_tests.py` 命中 1（`:81` 的 `env=dict(...)`，**只给子进程**）⇒ 自身无；⑦ `scripts/run_tests.py` 命中 2（`:88` 同形）⇒ 自身无 | 修前树七入口 | 【采集】 |
| A10 | clean env 子进程 `importlib.import_module(目标)` 后对 `sys.modules` 做差集 | `import md_cg` → 新增 `md_cg` ＋ 15 个 `md_cg.*` = **16 个模块**（源于 `md_cg/__init__.py:2` 的 `from .mdcg import …` 重包）；`import hive.hive_mcp.mcp_server` → 总数 71、**md_cg 不在 `sys.modules`**；`import hive.exec` → 139，亦无 md_cg（延迟 import）⇒ 「为一次 UTF-8 检查去 import md_cg」的代价成立，助手必须放仓根 | `md_cg/__init__.py:2` | 【采集】 |
| A11 | 读修前树 `hive/exec.py::_md_cg_import` 全 body（sys.path 插入先例） | `:854 def _md_cg_import():`；`:856` 读 `MDCG_HOME`；`:857-858` 空则取 `dirname(dirname(abspath(__file__)))`（＝仓库根）；`:859-860 if home not in sys.path: sys.path.insert(0, home)`；`:861-863` 再 import；调用点 `:911`。`hive/orch.py:374-375`、`:764` 同为延迟 import ⇒ 最小形态 = 「取 home → 不在 `sys.path` 则 `insert(0)`」 | `hive/exec.py:854-864` · `hive/orch.py:374-375,764` | 【采集】 |
| A12 | 父进程 clean env ＋ `sys.stdout.reconfigure(encoding='utf-8')`，分两态派生子进程 | 仅 reconfigure：父 `stdout.encoding=utf-8` 但子进程 `utf8_mode=0 / getpreferredencoding=cp936 / stdout=gbk / env 两个皆 None`；再加 `os.environ['PYTHONUTF8']='1'`＋`['PYTHONIOENCODING']='utf-8'`：子进程 `utf8_mode=1 / utf-8 / utf-8` ⇒ **reconfigure 只覆盖本进程三条流、不传播到后代；env 才传播** —— 这就是契约④与助手「无论走哪条路都置 env」的实测依据 | Python stdio/env 语义 | 【采集】 |
| A13 | 清空两 env、`MDCG_ROOT=临时库根`，`python -m md_cg.mcp_server` 喂 initialize/tools/list | rc=3、stdout 0 B；stderr 451 B **令牌闸 fail-closed**（`[mdcg-mcp] 令牌校验失败：令牌不存在… 拒绝启动（fail-closed）`）⇒ 该入口的 stdio E2E 在临时根上**未取得本人实跑读数**（诚实缺失）；其守卫存在性由 A9 与 `--show-config` 代跑支撑。带 `-X utf8` 对照同样 rc=3、stderr 逐字节相同（非编码差异） | `md_cg/mcp_server.py` main() 起的令牌闸 | 【采集】（复现=false） |
| A13′ | **前置更正（第 2 版新增）**：同一入口为什么在别处是 rc=0——用伪造字面量 `MDCG_TOKEN=<dummy>`（不抄录任何真实凭据）＋同一临时根实跑；再把 `MDCG_*` 一并清空重跑同一命令 | 带失效 `MDCG_TOKEN`：rc=3、stdout 0 B、stderr 同形（`令牌校验失败：令牌格式非法（应为 mdcg1.<role>.<token_id>.<secret>）…拒绝启动（fail-closed）`）；`MDCG_*` 清空后：rc=0、`serverInfo.name=mdcg-mcp` ⇒ **A13 的失败根因是「会话 env 里带着失效 `MDCG_TOKEN` 而那次只清了两 env」**，三个读数（A13 / E2E-MDCG / 复核）是**三种前置**而非同一前置下的矛盾（完整对照见 §5.1 前置对齐） | `md_cg/mcp_server.py` main() 起的令牌闸 | 【本次】 |
| A14 | 全部实验树来自 `git archive HEAD` 解包到系统临时目录；探针写在 `%TEMP%` | 临时根 `%TEMP%\lingshu_repro_A`（2 076 件、`utf8_boot.py present? False` 证明是修前树）；实验前后 `git status --porcelain` 逐字一致（批内读数 14 M ＋ 5 ??；**注**：本报告作者本次读为 14 M ＋ 6 ??，差额即本报告文件本身）⇒ 未编辑工作区、未触碰在役数据根、未重建/重启 hive serve、未 `git add/commit/push` | `D:\program\dsh-memory-main` @ `174cd25f…` | 【采集】【本次】我另建的 HEAD 物化树同判（`utf8_boot.py` 不在） |

### 2.2 B 侧修前现场

| # | payload（怎么取） | 观察（读数） | 站点 | 标记 |
|---|---|---|---|---|
| B1 | 自写 AST 扫描器重算「文本模式裸 `open`」（只读；脚本落 `%TEMP%`） | `builtin open total: 913`；`by class: {'text_missing_mode': 397, 'text_literal': 427, 'binary': 89}`；`GAPS (text-mode builtin open w/o encoding): 9`；`read_text/write_text w/o encoding: 0`。扫描面 486 个 `.py`，0 个读失败。清单核对（**第 2 版已改措辞**）：在**已声明** `encoding` 的文本字面 mode 调用里，`encoding` 取值集合**只有** `{'utf-8'}`（无第二种编码值）⇒ 本仓文本面不存在「用别的编码」这第二类问题；但**缺口数 9 本身仍由 AST 逐点判定**，此句只是清单核对，**不构成对 9 的独立证明**（未声明 `encoding` 的那 6 处字面 mode 调用不进这个集合——它们恰恰就是缺口）。`text_nonliteral` = 0 | 修前树（HEAD 物化） | 【采集】【本次】我自写的扫描器复现（同一 HEAD 物化树）：486 文件 / `text_literal` **427** ＋ `mode_missing` **397** = 文本 **824** / `binary` **89** / 缺口 **9**（427+397+89 = **913**，与左列 `builtin open total: 913` 同数）。**工作树侧另为** 489 文件 / `text_literal` **437** ＋ `mode_missing` **407** = 文本 **844** / `binary` **92** / 缺口 **0**（437+407+92 = 936）。行号见 §1.2 表 |
| B2 | 逐点读源码行——6 处「字面 mode 文本 open」 | 全部为文本模式且无 `encoding`（现场原文见 §1.2 对照）：`md_cg/test_n199_tokens_concurrent_write.py:157`、`md_cg/test_security_audit_v21.py:227/:231`、`hive/test_n144_exec_cmd_terminal_race.py:71/:116`、`hive/hive_mcp/mcp_server.py:653`。六处均为「空标记文件」语义（无正文写出），但按「凡文本模式一律显式」的统一规则确应订正 | 见左列（HEAD 行号） | 【采集】【本次】读现树行：均已带 `encoding="utf-8"` |
| B3 | 逐行读 `scripts/_mdcg_reindex_dshlogs.py:148-151` 与两处调用点 `:365/:411` | `:148 def write_text(p: str, text: str) -> None:`、`:150 with open(p, "w", encoding="utf-8", newline="\n") as f:` —— **编码早已显式且额外锁 LF**；`grep -n write_text` 该文件仅 3 行（148 def、365、411）。**后果级铁证**：把 helper 源码逐字复制到临时面实测 `write_text(tgt,'x',encoding='utf-8')` → `TypeError: write_text() got an unexpected keyword argument 'encoding'` ⇒ 机械照做契约①会**直接打断该脚本**。故这两点**不是缺口**，正确订正点数是 **9** | `scripts/_mdcg_reindex_dshlogs.py:148-151`（helper）、`:365`、`:411` | 【采集】【本次】我读出 `:147` 的生效条件注释与 `:150` 的 `encoding="utf-8", newline="\n"` 逐字一致 |
| B4 | 同一文件的「下游闭环」核查 | 写完的三处读点**全是显式 utf-8**：同文件 `:178-180 def _lines(p): with open(p, "r", encoding="utf-8")`、`md_cg/docindex.py:472`、`md_cg/refindex.py:170/:495`。**反事实实测**（`PYTHONUTF8=0`，`getpreferredencoding(False)=cp936`）：裸 `open(p,'w').write('中文…')` 落 `b'# \xbb\xe1\xbb\xb0 abc \xa1\xa4 …\r'`（GBK ＋ `\r\n` 翻译），用 utf-8 读回 `UnicodeDecodeError`；换成 `:150` 的写法则落 `b'\xe4\xbc\x9a\xe8\xaf\x9d…'` 读回正常 ⇒ 若这两点走默认编码，后果**不是静默乱码而是 `_lines(tpath)`/docindex 硬失败**，且字节不稳定会连带打破对账的逐字节幂等 | 同上 ＋ `md_cg/docindex.py:472` · `md_cg/refindex.py:170,495` | 【采集】 |
| B5 | 3 处「mode 缺失」需判定点 | `md_cg/test_lock.py:22`（`:17-23`：`FileLock(TARGET)` 内 `int(f.read().strip() or 0)`）、`:38`（`:33-39`：6 子进程 `wait()` 后 `int(f.read().strip())`）、`hive/test_stop_tree_kill.py:127`（`:125 cp = os.path.join(TMP,"childpid.txt")`、`:128 child_pid = int(f.read().strip())`）——三处都是纯 ASCII 数字读，**无实际风险**，但契约②的保守判据（mode 缺失即计入）要求显式化 | `md_cg/test_lock.py:22,38` · `hive/test_stop_tree_kill.py:127` | 【采集】【本次】 |
| B6 | 89 处二进制为什么**不该**加 encoding | 计数复现：AST 扫描独立得出 `binary count: 89`。对照实测（真跑）：`open(p,'wb'/'ab'/'rb',encoding='utf-8')` 三个模式**全部**抛 `ValueError: binary mode doesn't take an encoding argument` ⇒ 给这 89 处加 `encoding=` 不是「遗漏」而是**非法**。仓库内实例：`hive/exec.py:350 with open(path, "rb") as f:`（`:351` 读 32 字节做 PNG/JPEG/GIF/BMP/WEBP 魔数嗅探，纯字节比较）；`hive/serve_start.py:474 logf = open(os.path.join(jobs,"_serve.log"), "ab")` | `hive/exec.py:350` · `hive/serve_start.py:474`（＋扫描器 SUMMARY） | 【采集】【本次】我实测计数 89（HEAD） |
| B7 | Attribute 形态假阳性——按 `attr == 'open'` 匹配会误报哪些点 | 三目录内 Attribute 形 `*.open` 共 **66** 处 = `io.open` 62 / `tarfile.open` 2 / `os.open` 1 / `gzip.open` 1。未排除 Attribute 时多报 3 处（连二进制豁免也不加时 5 处）。逐点读源码确认：① `md_cg/fsutil.py:204 fd = os.open(path, os.O_CREAT|os.O_WRONLY|os.O_APPEND, 0o600)`（`:206 os.write(fd, line.encode("utf-8"))`）——第二实参是 int 标志位，`os.open` **没有 encoding 参数**；② `scripts/check_publish_artifact.py:696 with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")`——mode `r:gz` 不含 `'b'`，会落进「文本模式」分支；③ `scripts/criteria_fingerprint.py:45 with tarfile.open(fileobj=io.BytesIO(r.stdout))`（无 mode）；④ `md_cg/lexicon/build_cedict_en_zh.py:60/:62` 为 `io.open(RAW_GZ,"wb")` / `gzip.open(RAW_GZ,"rb")` 二进制流 ⇒ **只有 `ast.Name` 且 `id=='open'` 才安全**，Attribute 排除不是可选项 | `md_cg/fsutil.py:204` · `scripts/check_publish_artifact.py:696` · `scripts/criteria_fingerprint.py:45` · `md_cg/lexicon/build_cedict_en_zh.py:60,62` | 【采集】【本次】我自写 AST 扫描：工作树 `Attribute .open` = 66；其中**无 `encoding` 关键字**的恰好这 **5** 处；HEAD 树同为 66 |
| B8 | 守卫作用域充分性（额外查证） | 同一 AST 口径扩到**仓根全量**（跳过 `.git/__pycache__/node_modules/.venv/_md_cg_p0/.zcode`，去掉已单扫的三目录）：`OUT-OF-SCOPE strict bare text opens: 0` ⇒ 三目录覆盖面**充分**。另查 `open` 名遮蔽：三目录内对 `open` 的赋值/海象/形参/`def`/`import from` 绑定共 **0** 处 ⇒ `ast.Name + id=='open'` 无遮蔽风险 | 全仓扫描输出；遮蔽统计 | 【采集】 |
| B9 | 「同一 AST 口径下逐点核对现树」 | 工作树：`binary=0 / text=9 / gap=0`（单文件复核口径，针对本批改动/复核的文件）；`hive/hive_mcp/mcp_server.py` 的 kill 标志行由 `:671` 漂到 `:673`。**三个行号的归属（第 2 版补）**：`:653` ＝ **HEAD 行号**（本报告作者在 HEAD 物化树上实测，正是 B1/§4.3 缺口清单里的那一行）；`:673` ＝ **工作树当前行号**（本报告作者读码所见，`A 路` 锚块插在该文件 `:50-65` 所致）；`:671` ＝ **批内记录里的一处中间读数**（原文只有这一句，无其时点说明）——本报告**未能取证**它对应哪个时刻（该文件未提交、无中间快照），因此**不为它背书**，也不把它当作第三个独立读数：可核的两个端点是 `:653`→`:673` | 见 §1.2 表 | 【采集】【本次】 |
| B10 | 并发写者与快照边界 | 会话期间另有并发写者（mtime 21:25–21:26 命中 A 路七个入口；`hive/jobs/_serve.json` 21:28），故计数在会话内漂移（文本 840→844、二进制 89→91）；全部读数为**对应时刻快照**。我改动/复核的文件均 UTF-8 无 BOM | 工作区 | 【采集】（B 路现状计数以本次读数 844/92 为准，见 §6.1） |

---

## 3. 修法契约与落点

### 3.1 A 路

**助手三路语义**（`utf8_boot.py` 模块 docstring `:25-36` ＋ `ensure_utf8` docstring `:202-216`）：
下表的「路 0–3′」是助手 docstring 的既有编号（**不是**代码执行顺序——代码里「被 import」排在
「utf8 已开」之后）；**与 §1.1 表（按代码顺序标注）的逐项对照见 §1.3**。

| 路 | 条件 | 行为 | 落点 |
|---|---|---|---|
| 0 | 调用方**不是**进程入口（被 import） | 只置 env，立即返回——**绝不重启/退出/打日志** | `:221-222` |
| 1 | `sys.flags.utf8_mode` 真 | 立即返回（不重启、不打日志） | `:219-220` |
| 2 | 未开 且 `LINGSHU_UTF8_NO_REEXEC` 非真 | `reexec_argv()` → `subprocess.run(..., stdin/stdout/stderr=sys.std*)` → `SystemExit(proc.returncode)`；重启后子进程 `utf8_mode` 已开 ⇒ 结构上**不可能二次重启** | `:227-237` |
| 3 | 未开 且 `NO_REEXEC` 真 | 打印**可执行指引**以 `2` 退出（不能接受子进程的场景：嵌入式宿主/CI 调试/进程树审计） | `:224-226` |
| 3′ | `-c`/`-` 形态（源码不可重放） | 不重启，指引 ＋ `3` 退出 | `:228-230` |
| 全部 | — | 先 `_set_child_env()` 置 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`，供随后派生的子进程继承 | `:218` |

**第一轮三缺口的修法**（契约外的复核发现，均已修并纳入守卫）：

- **F2（指引必须可照抄）**：新增单点判别 `_m_module_name()`，`reexec_argv()` 与 `launch_hint()` **共用**；
  `-m` 入口的指引印 `python -X utf8 -m md_cg.mcp_server` / `-m hive.hive_mcp.mcp_server`，
  其余形态印入口路径。反例：`python -X utf8 md_cg/mcp_server.py` → rc=1
  `ImportError: attempted relative import with no known parent package`（`md_cg/mcp_server.py:4038` 一带的相对 import）。
- **F6（被 import 不得重启）**：新增 `_caller_is_process_entry()`（`f_globals` 与 `__main__.__dict__`
  **同一性**判定）。实现上**不改调用点**——七入口仍是 `ensure_utf8(__file__)`，故守卫的调用锚一字不动。
  复核实测（未加判据前）：单会话解释器启动 2 次、第 3 条请求被吞、**无错误帧、rc=0**。
- **F3（三流显式传递必须有判据）**：契约字面要求「在『助手不传三流』的临时副本上跑同一条 E2E，
  组帧必须转红」**按字面做不到**——宿主 `Popen(stdin=PIPE, stdout=PIPE, stderr=PIPE)` 时，
  子进程即使漏传三流也会**直接继承父进程的 fd 0/1/2**（同一条管道），组帧照样成立（实测：单独剥离任一条流，
  E2E-HIVE/E2E-MDCG/ONCE/NOOP 四项全绿）。故判据拓扑换成**继承无法掩盖**的那一种：父进程先把三条流
  换成**普通文件对象**（非 fd 0/1/2），并置 env 标记 `UTF8GUARD_STREAMS_ONCE` 供重启出的子进程继承，
  堵死「子进程自己重开文件」的自愈路径；此时「显式传递 ⇒ 写回显式传入的流」与「漏传 ⇒ 写进宿主管道」
  可观测、可定点变异，且判据反证宿主管道零痕迹。

**探针熔断（额外加固）**：`GUIDE` 的「采指引」在变异态下会**真跑**入口（实测
`scripts/run_tests.py` 会真跑整个套件并拉起守卫自身，递归跑套件、孤儿进程堆积，一次跑挂 10 分钟以上）；
「探针」在幂等被破坏时会无限自重启。修法：采指引与探针各挂**独立计数熔断**
（`sitecustomize` 在第 N 次解释器启动 `os._exit(97)`；`FUSE_LIMIT=6` `:158`），各用独立计数文件，
采指引超时收到 60s。

**与既有层的关系**：两个 MCP 入口的 `_force_utf8_stdio`（issue #39）**并存**，`main()` 首行仍调
（`hive/hive_mcp/mcp_server.py:943`、`md_cg/mcp_server.py:3838`）；两层判据分属
`md_cg/test_issue39_utf8_stdio.py` 与本守卫。助手内**不做** stdio reconfigure（契约里那是「可选」）。

**未触碰**：未改任一入口的业务语义与参数面；未动 `scripts/run_tests.py` 既有的「给子进程覆盖 env」那段。

### 3.2 B 路

- **守卫判据**＝ §1.2 的 ①–④（AST 只认内建 `open`；二进制豁免；mode 缺失/非字面量/`**kwargs` 计入；
  `read_text`/`write_text` 计入且不误伤模块内自建同名函数）。
- **ANCHOR 三层 fail-closed**（漂移即 `2`，不当假绿）：判据锚（22 片段×预期违例数）、扫描面下限
  （`_FLOORS`：文件 420 / 文本 700 / 二进制 76 / Attribute 56 / `read_text-write_text` 4，
  取实测基线 ~85%）、对照点位锚（5 文件 ＋ **5 点位**：`check_publish_artifact.py/tarfile.open`、
  `criteria_fingerprint.py/tarfile.open`、`fsutil.py/os.open`、`build_cedict_en_zh.py/io.open`、
  `build_cedict_en_zh.py/gzip.open`——文件级锚只保证「文件里还有某个 Attribute `.open`」，
  **点位级锚才保证「被误报的那一类形态仍在对照面上」**）。
- **白名单为空**（`WHITELIST={}` `:63`），双向报出逻辑未改，不留静默豁免通道。
- **存量订正**：9 处（§1.2 表），全部仅加 `encoding="utf-8"`；未加白名单、未改任何 assert、
  未动任何二进制模式 `open`。
- **本批对守卫自身的两处改动**：① 修 `docstring` 文档漂移（判据锚片段数「20 个」→「22 个」，
  与 `_ANCHOR_CORPUS` 22 片段实测一致）；② 新增点位级假阳性对照锚 `_ATTR_CONTROL_POINTS` ＋
  `attr_open_callees()`，`--self-test` 增报「契约点名 Attribute 假阳性点位 5/5 逐个仍在位」；
  ③ `scripts/test_verify_open_encoding.py` 新增 ④e 反证（给点位锚补一个 ghost 形态必须 rc=2 且
  stdout 含「对照点位漂移」），`assert` 数 24→26。

**已知未接**：守卫**未接** `utf8_boot.ensure_utf8`（设计稿 §7.3 D2 的已知项）——B 契约未要求，
且 `scripts/test_verify_open_encoding.py` 会 import 该模块，模块级重启语义有副作用。
**第 2 版补实测后果（【本次】）**：clean env（清 `PYTHONUTF8`/`PYTHONIOENCODING`、不带 `-X utf8`）
下直接跑该守卫 → **rc=1**、stdout 72 B **非 UTF-8**（GBK 字节），stderr 为
`UnicodeEncodeError: 'gbk' codec can't encode character '\u2714'`，崩点在 `:476` 的 `print("✔ …")`
（`--self-test` 同因，崩点 `:444`）；`scripts/test_verify_open_encoding.py` 在同 env 下 **rc=0、
但 stdout 同样非 UTF-8**（1166 B，首字节 `0xa2`）。即 `rc=1` 与守卫自己的「1 ＝ 存在违例」**同码**，
在没设 env 的机器上会把「崩溃」读成「有违例」。是否接 `ensure_utf8` 属下一批判定（建议见 §7-Q7）。

---

## 4. 验证数字

### 4.1 A 守卫 `scripts/test_utf8_boot_guard.py`（1 254 行 / 66 870 B / 无 BOM）

判据面常量：`ENTRIES` 七入口 `:92-100`（顺序即报告顺序）、`ANCHOR_*` 四常量 `:102-105`、
`ENTRY_LAUNCH` 真实接入形态 `:110-132`、`IMPORT_CASES` `:136-144`、`_CHECKS` 11 条 `:862-874`、
`_MUTATIONS` 13 条 `:1030-1057`。

**断言数 = 11 条正向判据 ＋ 13 项定点变异 = 24；通过 24；rc=0；耗时 21.8s**【本次】。
`--no-mutations` → 11/11、rc=0、1.3s【本次】。21.8s 远在 `scripts/run_tests.py` / `md_cg/run_tests.py`
的 `--timeout` 默认 900s 之内。

**正向判据逐条（本次实跑输出摘录）**

| id | 判据 | 读数 |
|---|---|---|
| E2E-HIVE | ① stdio MCP 端到端组帧（hive，清空 env 无 `-X utf8`） | rc=0、帧数 3、中文入参往返成功 |
| E2E-MDCG | ① 同上（md_cg） | rc=0、帧数 2、中文 `write` 被受理（ok） |
| ONCE | ② 只重启一次 | 启动计数恰 2（首启未开 → 重启一次后已开） |
| FAILFAST | ③ `LINGSHU_UTF8_NO_REEXEC` | rc=2 ＋ 指引含 `-X utf8`/`PYTHONUTF8`/`LINGSHU_UTF8_NO_REEXEC`，启动 1 次（未重启） |
| NOOP | ④ `-X utf8` ⇒ 不重启 | 启动 1 次 |
| ENV-CHILD | ④ env 供后代继承 | 本进程 `utf8_mode=1` 且 env 已置；孙进程 `GRAND 1 utf-8` |
| ANCHOR | ⑤ 七入口锚点 | 7 个入口注释锚 ＋ import 锚 ＋ 调用锚齐备，且调用**早于首个 `def`** |
| DEPDIR | ⑥ 依赖方向 | 助手 import 面 = `['__future__','locale','os','subprocess','sys']`（纯 stdlib）；import 后 `md_cg`/`hive`/`scripts` 均不在 `sys.modules` |
| GUIDE | ⑦ 指引可照抄（F2） | 七入口指引逐个**真跑通**：两 MCP 入口 `-m` 形态握手 `hive-mcp`/`mdcg-mcp`；`exec.py`/`orch.py` 见 usage（rc=2）；`serve_start.py --show-config` stdout 见 `"keys"`（rc=1、2 349 B）；两个 run_tests `--list` rc=0 且产物 10 531 B |
| IMPORT | ⑧ 被 import 不重启（F6） | 启动 1 次；七入口全部 import 成功（7 个标记齐备） |
| STREAMS | ⑨ 三流显式传递（F3） | 非 fd 0/1/2 拓扑下组帧往返成功：`echo='中文标题：编码守卫'`、`stderr` 标记落显式流、**宿主管道零痕迹** |

**定点变异 13 项：每处红项集与退出码**（本次实跑，逐项与预期**恰好**一致）

| 变异 | 做了什么 | 红项集 | 退出码 |
|---|---|---|---|
| M1-no-m-form | 重启 argv 丢掉 `-m` 模块语义（直跑文件） | `{E2E-MDCG}` | 1 |
| M2-early-return-inverted | utf8 已开也不早退（幂等被破坏） | `{ENV-CHILD, FAILFAST, GUIDE, NOOP, ONCE, STREAMS}` | 1 |
| M3-env-not-set | 第四项失效：不置两 env | `{ENV-CHILD}` | 1 |
| M4-no-reexec-ignored | 显式退出通道失效（`NO_REEXEC` 被忽略） | `{FAILFAST, GUIDE}` | 1 |
| M5-anchor-call-removed | 入口不再调用助手 | `{ANCHOR, GUIDE}` | **2**（ANCHOR-MISS） |
| M6-anchor-order-drift | 调用锚挪到首个 `def` 之后 | `{ANCHOR, GUIDE}` | 1 |
| M7-dep-direction | 助手反向 import `md_cg` | `{DEPDIR}` | 1 |
| **M8-green-control** | **无关改名（假阳性对照）** | **∅** | **0**（必须全绿） |
| M9-stream-stdin-dropped | 重启不传 `stdin=` | `{STREAMS}` | 1 |
| M10-stream-stdout-dropped | 重启不传 `stdout=` | `{STREAMS}` | 1 |
| M11-stream-stderr-dropped | 重启不传 `stderr=` | `{STREAMS}` | 1 |
| M12-guide-no-m-reuse | 指引不复用 `-m` 判别 | `{GUIDE}` | 1 |
| M13-import-gate-off | 被 import 也重启（F6 前行为） | `{IMPORT}` | 1 |

> 全套 13/13 ＝「红项集与退出码**恰好**等于各自预期」（对照项预期即 `∅`/`0`）。批内记录显示：
> 首轮 M6 实测多出 `GUIDE`、M9–M11 实测 `∅`（暴露 STREAMS 探针「子进程自愈」盲区），
> 两处都按现场改实现/改预期后才钉死——即预期值是**逐项实测写死**而非猜的。

**M1 为什么只红 `E2E-MDCG`（第 2 版补实测，回应 §5.1 uncovered 3）**：M1 关掉助手 `reexec_argv()` 的 `-m`
分支后，重启退化为「直跑文件」。本报告作者实测两种入口在该形态下的存活差异：
`python -X utf8 hive/hive_mcp/mcp_server.py` → **rc=0、initialize 握手 `hive-mcp` 成功**（该入口的锚点自带
`sys.path` 插入，且入口执行路径上没有相对 import）；`python -X utf8 md_cg/mcp_server.py` → **rc=1**，
`File "md_cg/mcp_server.py", line 3850, in main / from .datapath import mdcg_root as _probe_root /
ImportError: attempted relative import with no known parent package`。⇒ **单点变异打不红 `E2E-HIVE`**：
hive 入口对「直跑文件」是免疫的；要把它打红必须**同时**破坏 hive 入口自身的某一层（例如同时停用
`ensure_utf8` 与 `_force_utf8_stdio`，即复核者的场外变体 B），而守卫的变异表当前是**单点注入**
（`_sub()` 要求目标片段恰出现一次，`scripts/test_utf8_boot_guard.py:905-907`）。补法建议见 §7-Q3。

**变异自证所跑的「临时物化面」规模**（第 2 版补，用于对上 §5.1 里的「1 158 文件」）：守卫在注入变异前
把仓面物化到临时目录，其自跑输出原样为 `⑦ 定点变异自证（临时物化仓面 1158 文件，绝不改工作树）`。
1158 的口径 = `git ls-files -z --cached --others --exclude-standard`（追踪面 ＋ 未追踪面）扣掉
`_MATERIALIZE_SKIP` 的 10 个前缀（`docs/`、`skills/`、`node_modules/`、`hive/target/`、`hive/jobs/`、
`hive/interop/`、`.git/`、`.zcode/`、`_md_cg_`、`rust/target/`，`scripts/test_utf8_boot_guard.py:177-179`；
清单构造见 `_materialize_list() :1062-1080`），**含全部文件类型**；本报告作者按同一口径复算 = **1158**（【本次】）。
它与 §4.3 的 486 / 489（只数 `md_cg/`＋`hive/`＋`scripts/` 三目录的 `*.py`）**不是同一口径**，两者不可互比。

### 4.2 B 守卫与回放断言

| 命令（本次实跑） | rc | 读数 |
|---|---|---|
| `python scripts/verify_open_encoding.py` | 0 | `扫描面：489 文件 / 文本 open 844 / 二进制 open 92 / Attribute .open 66`；`✔ 全部文本模式调用点均显式声明 encoding=` |
| `python scripts/verify_open_encoding.py --self-test` | 0 | 判据锚 **22/22** 片段预期成立；扫描面 **文件 489 ／ 文本 open 844（其中 mode 不可判定 407）／ 二进制 open 92 ／ Attribute `.open` 66 ／ `read_text`-`write_text` 6**（第 2 版已逐项加键：`--self-test` 比正跑多报末一项，故是五项；正跑的印字在 `:454-455`，只印前四项）；真实仓裸文本违例 **0**；Attribute 对照 **5 个文件**全部核对；**契约点名 Attribute 假阳性点位 5/5 逐个仍在位**；定点变异 3 目标 × 4 变体 |
| `python scripts/test_verify_open_encoding.py` | 0 | **ALL PASS**；`assert` 计数 **26**（`docstring` 同步）；③ 逐变体命中数：裸文本无 mode→1、`mode='w'`→1、mode 非字面量→1、`read_text` 无 encoding→1、二进制→0、`Attribute io.open`→0、`Attribute tarfile.open`→0、带 encoding→0；**③c 完整扫描面注入一处裸文本 open → exit 1 且恰好 1 处（行号 47）**；④a–④e 五条 ANCHOR-MISS 反证**全 rc=2**；⑤ 白名单双向 **rc=1**；⑥ `WHITELIST=={}` |

### 4.3 本报告作者自写的独立 AST 复核（两条独立路径交叉印证）

| 树 | 文件数 | 内建二进制 `open` | 文本模式 `open` | 文本裸 `open`（缺口） | Attribute `.open` 总数 / 其中无 `encoding` |
|---|---|---|---|---|---|
| HEAD 物化树（`git archive HEAD` → `%TEMP%\rpt_head_tree`，`utf8_boot.py` 不在） | 486 | **89** | 824（字面 427 ＋ mode 缺失 397） | **9**（行号 = §1.2 表，逐点对得上） | 66 / **5**（＝契约点名的 5 处） |
| 工作树 | 489 | 92（89 ＋ 新增未追踪件 `scripts/test_utf8_boot_guard.py` 的 3 处） | 844（字面 437 ＋ mode 缺失 407） | **0** | 66 / 5 |

⇒ **可比性说明（第 2 版订正，原句「两侧均与守卫自报一致」不成立）**：**只有工作树侧**能与「守卫自报」比——
守卫自报（489 文件 / 文本 844 / 二进制 92 / Attribute 66）与本报告作者的工作树扫描**逐项一致**；
**HEAD 侧没有守卫读数可比**（守卫只扫当前工作树，全文没有它在任何修前树上的输出），它的可比对象是
**批内另一路扫描器**（§2.2 B1 的 `【采集】` 读数：`builtin open total: 913`、`mode_missing 397`、
`text_literal 427`、`binary 89`、`GAPS 9`）——我的 HEAD 扫描与之**逐项一致**（427＋397＋89 = 913，
缺口 9 处且行号逐点对上）。`89 + 9 + 5 = 103` 的口径分解见 §6.1（并见其中「103 的两套分解不能互证」一段）。

### 4.4 python 全量 与 容器

| 面 | 命令 / 来源 | 读数 |
|---|---|---|
| python 全量【本次】 | `python scripts/run_tests.py`（清空被测面之外的默认 env、`PYTHONUTF8=1`） | **269/269 通过，5 跳过（依赖缺失/平台不符）**，rc=0，耗时 **101.7s**；含 `PASS scripts.test_utf8_boot_guard` 与 `PASS scripts.test_verify_open_encoding`（两条本批守卫在套件内可见可跑） |
| python 全量【本次·**clean env 复跑**】 | 同一命令，但 env 清空 `PYTHONUTF8`/`PYTHONIOENCODING`/`PYTHONLEGACYWINDOWSSTDIO`（不带 `-X utf8`） | **269/269 通过，5 跳过，rc=0，100.7s**；stdout 10 260 B **合法 UTF-8**（`decodes as utf-8: YES`）——runner 自身的 `ensure_utf8` 重启了自己，故整套在 cp936 locale 下仍全绿、且输出不是 GBK |
| 批内两失败模块 ×3（clean env） | `python -m md_cg.test_n212_n213_n224_generation_gates` 与 `python -m md_cg.test_p28_refcheck` 各 3 次 | 6/6 全 **rc=0**（n212 每次 `PASS=42 FAIL=0 LIVE=26`、0.3s；p28 3 次 rc=0、0.3–0.4s）⇒ 本机此刻**不复现**批内那两处失败 |
| python 全量【采集】 | 批内实跑记录 | 267/269 通过、5 跳过，**失败 2**：`md_cg.test_n212_n213_n224_generation_gates`、`md_cg.test_p28_refcheck` |
| 容器两栈【采集】 | 批内记录 | 退出码 **127 / 127**（未取得任何有效读数） |

**关于两处差异的如实标注**：① 批内的 2 个失败在本次**两次**全量（UTF-8 env 与 clean env）中**均 PASS**，
且在 clean env 下单独重跑 3+3 次也全 rc=0——本报告作者仍**不为其成因背书**：要判定它们是 flaky
还是并发写者所致，需要更多轮次与并发复现实验（见 §7-Q5）；本次读数亦只是**该时刻快照**。② 容器：本机 Docker CLI 在位（`docker --version` → 28.4.0、
`docker compose version` → v2.39.4），但 **daemon 未运行**——`docker ps` rc=1，
`error during connect: … open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`；
`docker images rust:bookworm` rc=1。故 `scripts/linux_verify.sh` 的两栈（其容器形态见该脚本头注
`docker run --rm -v <repo>:/work -w /work rust:bookworm bash scripts/linux_verify.sh [full|core]`）
**本轮无法复跑，记为未验证**；本报告不为 `127` 的具体成因背书（127 是 shell 的「命令未找到」类退出码，
但 daemon 未运行时 docker CLI 自身返回 1，两者不等价）。

### 4.5 本报告作者本次实跑命令清单（可复现）

1. `python -c` 探针：本机 locale/env ＋ clean-env 子进程 ＋ `-X utf8` 对照（§2 A1）
2. `python -c` 探针：clean env 裸 `open(p,"w").write("中文标题")` → 落盘字节 ＋ utf-8 读回（§2 A2）
3. 自写 AST 扫描器（`python - <<PY` 内联，不落文件）：HEAD 物化树 ＋ 工作树全扫（§4.3）
4. `python scripts/verify_open_encoding.py` / `… --self-test`（§4.2）
5. `python scripts/test_verify_open_encoding.py`（§4.2）
6. `python scripts/test_utf8_boot_guard.py --no-mutations` / `python scripts/test_utf8_boot_guard.py`（§4.1）
7. `docker --version` / `docker compose version` / `docker ps` / `docker images rust:bookworm`（§4.4）
8. `git status --porcelain` / `git rev-parse HEAD` / `git archive --format=tar HEAD`（只读）

**第 2 版（读者反馈处置轮）追加的实跑**：

9. `python scripts/run_tests.py`，env 清空 `PYTHONUTF8`/`PYTHONIOENCODING`/`PYTHONLEGACYWINDOWSSTDIO`（§4.4）
10. 同 clean env 下 `python scripts/verify_open_encoding.py` / `… --self-test` / `python scripts/test_verify_open_encoding.py`（§3.2 末、§6.3）
11. 令牌闸前置对照：`python -m md_cg.mcp_server` —— 带伪造失效 `MDCG_TOKEN`（rc=3）与清空 `MDCG_*`（rc=0）（§2.1 A13′、§5.1）
12. 直跑文件形态对照：`python -X utf8 hive/hive_mcp/mcp_server.py`（rc=0、握手 `hive-mcp`）与 `python -X utf8 md_cg/mcp_server.py`（rc=1、`ImportError: attempted relative import`）（§4.1 注、§7-Q3）
13. `python -m md_cg.test_n212_n213_n224_generation_gates` / `python -m md_cg.test_p28_refcheck` 各 3 次（clean env）（§4.4）
14. `python scripts/workspace_index.py --check`（rc=1、陈化 2 处，均点名 `utf8_boot.py`）（§6.4 第 10 条、§7-Q9）
15. `git diff --numstat`（`WORKSPACE_INDEX.md` 7/6、`scripts/workspace_index.py` 2/0）（附清单）

`L1 直跑留痕：以上均为只读判定（产物落点为临时目录与 stdout，不改仓库/外部状态；唯一写动作＝本报告文件本身）— 风险低 / 本任务内多次 / 可逆`。

---

## 5. 两项独立复核判定与 uncovered

> 「独立复核」在本报告**仅指**下列两项第三方复核（复核者各自自写扫描器/探针、只读只跑、
> 实验面自建在系统临时目录、不依赖执行者日志）。判定原文＝**ACCEPT / ACCEPT**。

### 5.1 A · 入口自保证 UTF-8 —— **ACCEPT**

**basis（复核者自述要点）**：清空两 env 的裸解释器上独立复现 `locale.getlocale()=('Chinese (Simplified)_China','936')`、
`getpreferredencoding(False)=cp936`、`utf8_mode=0`、`stdout.encoding=gbk`；异常路 `UnicodeDecodeError 'gbk' codec can't decode byte 0xad in position 2`、
静默路 `b'\xd6\xd0\xce\xc4\xb1\xea\xcc\xe2'`。**自建 E2E 组帧**（非守卫代码）：两 MCP 入口 rc=0、
解释器启动计数=2、stdout 严格 UTF-8 逐行 JSON、`serverInfo` 正确。**修前对照（临时物化 1 158 文件）**：
变体 A（只删两入口的 `ensure_utf8` 调用、保留 `_force_utf8_stdio`）→ E2E 仍绿；变体 B（再删
`_force_utf8_stdio()`）→ rc=0 但 stdout 非法 UTF-8（byte 0xc1 @241/249）⇒ 判定两层关系为**并存**、
契约(c) 的真后果是「静默产出非 UTF-8 字节」。自建 sitecustomize 启动计数含熔断：E2E 计数恰 2、
`-X utf8` 时 1、fail-fast 时 1。fail-fast 指引**逐个真跑**（两个 `-m` 握手成功、两个 usage、
`--show-config` 出 `"keys"`、两个 `--list` rc=0），反例 `python -X utf8 md_cg/mcp_server.py` → rc=1 ImportError。
F3 三流差分用**非 fd 0/1/2 拓扑探针**：删 `stdin=`/删 `stdout=`/`stderr=None` 三项**各自转红**。
F6：单进程 import 七入口启动计数=1、七个标记齐备；被 import 路径 `utf8_mode=0` 而 env 已置，
其孙进程 `utf8_mode=1 enc=utf-8` ⇒ 「无论走哪条路」在被 import 路上同样成立；对照复刻「仅 reconfigure」
者的孙进程 `utf8_mode=0 enc=gbk env=None/None`。依赖方向 AST 审计：助手 import 面 5 个纯 stdlib、无
`os.exec*`；import 后 `MODS=[]`。七入口锚点 AST 审计：调用锚之前只有 `__future__`/docstring/stdlib import
＋ `_UTF8_ROOT` ＋ `sys.path.insert`，无任何文件/库 I/O。**守卫与自证复核者独立跑**：24/24、rc=0、
M1..M13 红项集与退出码逐项与其复算一致；另自建 driver 在副本上把 `check_streams`/`check_e2e_mdcg`
架空成恒 `True` → `run_mutations` 报 miss、rc=2 ⇒ 自证机制有判别力。边界：临时
`MDCG_ROOT`/`STATE`/`DATA`/`AUX`/`TENANT_REGISTRY` 与 `HIVE_JOBS_DIR`，`HIVE_EXE` 指向不存在路径
（绝不拉真 serve）；未重建/重启在役 serve；未 `git add/commit/push`；复核前后 `git status --porcelain`
均为 20 条。

**前置对齐（第 2 版补，【本次】；回应「同一个 md_cg 入口有三个互斥读数」）**

| 读数 | 前置（关键差异在**凭据 env** 与**身份面**） | 结果 |
|---|---|---|
| A13（批内那次） | 只清 `PYTHONUTF8`/`PYTHONIOENCODING`，**未清 `MDCG_*`**——会话 env 里带着一个失效 `MDCG_TOKEN` | rc=3、stdout 0 B（令牌闸 fail-closed） |
| 守卫 `E2E-MDCG` | `_env_clean() :197` 按 `_DIRTY_KEYS :162-174` **清空整个 `MDCG_*`/`PYTHON*`/`HIVE_*` 面（含 `MDCG_TOKEN`）**，再 `_mdcg_extra() :354-369` 置临时 `MDCG_ROOT`/`MDCG_AUX_ROOT`/`STATE`/`DATA` ＋ `MDCG_TENANT_REGISTRY` 指向不存在文件 ＋ **身份豁免面**（`MDCG_LEGACY_ENV_AUTH=1`/`MDCG_CAN_ADMIN=1`/`MDCG_LEGACY_ENV_ADMIN=1`/`MDCG_ACTOR=utf8-guard`/`MDCG_SUSTAIN=0`）；另 `:210-211` 在宿主本身已开 UTF-8 模式时**追加 `PYTHONUTF8=0`** 以构造「未开」态 | rc=0、帧数 2、`serverInfo.name=mdcg-mcp`、中文 `write` 回 `ok` |
| 复核者的自建 E2E | 自述口径＝临时 `MDCG_ROOT`/`STATE`/`DATA`/`AUX`/`TENANT_REGISTRY` ＋ 清 env（原文未逐字列是否清 `MDCG_TOKEN`） | rc=0、启动计数 2、逐行 JSON |

本报告作者按**守卫口径**复跑该前置：`initialize` ＋ `tools/call cg{op:write,content:"中文探针"}` →
**rc=0、stdout 900 B（2 帧）、`serverInfo.name=mdcg-mcp`、`write` 回 `ok`**；把同一命令改回
**只清两 env、留着失效令牌**（伪造字面量）→ **rc=3**（§2.1 A13′）。⇒ 三个读数**不是同一前置下的矛盾，
而是三种前置**：批内那次被令牌闸挡下，守卫与复核在「清凭据 env ＋ 身份豁免面」下跑通。
（另：本节 basis 里的「临时物化 1 158 文件」的口径见 §4.1 末——那是 A 守卫变异自证的物化面**文件总数**，
含全部文件类型，与 B 的 486/489 不是同一口径。）

**uncovered（原文要点，逐条保留）**

1. **Linux / C-locale、容器与 `scripts/linux_verify.sh` 未跑**——全部结论只来自本机 Windows/CP936 现场。
2. **真宿主端到端未测**：未连 DSH/Claude/code CLI 的真 `mcp.json`、未起真 serve；「换台没设 env 的机器上真宿主是否通」只有进程级 `-m` 证据。
3. **E2E 判据对「助手」本身无判别力（实测）**：副本上只删两个 MCP 入口的 `ensure_utf8` 调用（保留 issue #39 防线）→ E2E 仍绿（计数 1）；删掉两条防线才转红（stdout 0xc1）。故契约⑦「每处判据都要有定点变异打红」**在 check 粒度仍有一处未满足**：守卫变异表中 **E2E-HIVE 无任何变异能把它打红**（M1 只红 E2E-MDCG）；其可打红性由复核者自查的变体 B 证明，但**该变异不在守卫定点表内**。
   - 另两项**需设计者裁决的非阻断观察**：(a) `_set_child_env` 覆盖式写 `PYTHONIOENCODING`，使 `md_cg/test_issue39_utf8_stdio.py` 的 `gbk:strict` 模拟面前提在重启后变化（未跑该守卫复验，仅记录）；(b) 契约②「`utf8_mode` 为真即立即返回（不做事）」与④「无论哪条路都置 env」字面冲突，实现取④优先（先置 env 再早退）——措辞张力，非缺陷。
   - **(3b) 设计稿的处置（第 2 版更新）**：本路径下的设计稿**已不存在**——工程报告（本件）首版即覆盖了同路径文件（见文首说明），而该设计稿当时是 `??` 未追踪件、**无 git 历史**（`git log -- docs/eval/编码面前置_入口自保证UTF8与文本open守卫_v1.0.md` 无输出）⇒ 其正文**无留存副本**，只能从会话记录/批内采集文本重建。读者不会再读到「F2/F3/F6 三条未修」的旧表述；是否为设计稿另存副本或加墓碑，见 §7-Q8。
4. **`hive/exec_cmd.py`（serve 以 `HIVE_EXEC_PY` 拉起的多态转发层）未接线**——读码确认其全部 `open` 显式 `encoding='utf-8'` 且 `:258` 给派生命令 `setdefault PYTHONUTF8='1'`，但其自身 stdout/stderr 仍随 serve 继承的 locale（未实测，未判定为必须加）。
5. **「其余约 60 个带 `__main__` 的一次性工具」未逐一评估**（抽样确认 env 由调用方继承）。
6. **未实测「`md_cg.mcp_server` 被当库 import 后由第三方调 `main()`」形态**（该形态下助手按 F6 不重启，仅靠 `_force_utf8_stdio` 兜底）。

### 5.2 B · 文本模式 `open` 的守卫与存量订正 —— **ACCEPT**

**basis（复核者自述要点）**：自写扫描器（`%TEMP%\open_review\scan_open.py`）：`files=489 / 文本模式内建 open=844（mode 缺失 407、非字面量 0）/ 二进制=92 / Attribute .open=66 / read_text-write_text=6`，
**文本模式缺 encoding 违例=0**；489 与文件系统实际 `.py` 数相等（无欠扫）。守卫 `verify_open_encoding.py` rc=0；
`--self-test` 判据锚 22/22；`test_verify_open_encoding.py` ALL PASS（含测试⑥ `WHITELIST=={}`）。
**逐点核 11 处**：`md_cg/test_n199_tokens_concurrent_write.py:157`、`md_cg/test_security_audit_v21.py:227/231`、
`hive/test_n144_exec_cmd_terminal_race.py:71` 与 `:117`（契约写 `:116`，**行号漂移**）、
`md_cg/test_lock.py:22/38`、`hive/test_stop_tree_kill.py:127`、`hive/hive_mcp/mcp_server.py:673`
（契约写 `:653`，漂移）**均已带 `encoding='utf-8'`**。**自建变异台**（temp 物化 489 文件＋守卫副本）：
注入裸文本 open → rc=1 且全域恰好 1 项；四文件各注一处 → 恰好 4 项；`open(p,'w',encoding='utf-8')` /
`open(p,'rb')` / `os.open` / `tarfile.open` / `io.open` 五类 → **全部 rc=0（不误报）**。删断言探针：
削掉 `md_cg/fsutil.py` 的 `os.open` → 自证 rc=2 并报「对照点位漂移」；抽掉 `md_cg/` 扫描面 → rc=2
ANCHOR-MISS（首次「抽空 `scripts/`」探针是**假通过**，rc=2 源于守卫文件本身不存在，已重做）。
`git diff`：全 diff 中 open 相关增/删各 9 行，**全部仅加 `encoding='utf-8'`**；无一条二进制 open 被改；
断言/期望类增删行=0；`scripts/_mdcg_reindex_dshlogs.py` 与 `md_cg/fsutil.py` diff 为空。
官方 runner 下 `md_cg -k security_audit_v21` / `-k test_lock` / `hive -k stop_tree` / `-k n144` /
`scripts -k verify_open_encoding` 全部 PASS。**清单订正**：契约第 7/8 点
（`scripts/_mdcg_reindex_dshlogs.py:365/:411`）**不是缺口**（`:148` 自建 `write_text`，`:150` 早已显式
`encoding` ＋ `newline`，加 `encoding=` 会 `TypeError`）⇒ 实为 **9 处订正 ＋ 2 处契约误判**；
契约「89 处二进制」实测 92，差额＝新增未追踪件 `scripts/test_utf8_boot_guard.py` 的 3 处（扣掉即 89）；
契约「103」＝ 当前 92 处「内建 open 无 encoding 关键字」＋ 已订正 11 处，口径自洽。契约点名的
**5 个 Attribute 假阳性点位**逐个 AST 定位仍在位且不报。全程未编辑工作区任何文件，
复核前后 `git status --porcelain` 逐字一致。

**uncovered（原文要点，逐条保留）**

1. **全量 python 套件未跑**：ask 末行明示「不要重复跑全量与容器」，与该 ask 的「验证⑤ python 全量套件不因订正转红」存在张力；复核者只用官方 runner 跑了 11 处改动直接触及的 5 个模块 ＋ 守卫测试（结果全 PASS），**未跑全量 ⇒ 该条按「未执行」计，不按通过计**。（**本报告作者已补跑**：269/269、rc=0，见 §4.4。）
2. **契约的「11 处逐点订正」**：复核者只确认 9 处属真订正，另 2 处（`scripts/_mdcg_reindex_dshlogs.py:365/:411`）经独立取证判定为契约误分类、**本就不该改**；若验收方按字面要求「11 处全部出现 `encoding=`」，则该字面条件**不可满足**，且复核者不认为应满足。
3. **守卫是否已接入 CI 门禁**（`.github/workflows` 或 `scripts/run_tests.py` 之外的闸口）未核查——契约未提出该要求。
4. **契约所称「真实仓 89 处二进制对照」**：复核者按当前实测 92 处做对照，并给出 89 的口径复现（扣除新增未追踪件的 3 处），**未在 HEAD 快照上单独复现 89**。（**本报告作者已补**：HEAD 物化树实测 89，见 §4.3。）

---

## 6. 边界与未覆盖

### 6.1 口径更正（本批最需要写清的一件事）

| 轮次 | 口径 | 复现情况 | 判定 |
|---|---|---|---|
| 早期（编排会话先说） | **224 处裸 `open`** | **出处不闭环，且不可复现**（第 2 版写明）。224 的**原始命令与口径**在批内采集文本、本报告可取证范围内**均无留存**——本报告与批内记录都取不到它的来源 ⇒ 只能判为**来源不明的历史口径，无依据可核**。为逼近它试过的三个**文本/正则代理口径**也都不吻合，且三者互不相等：`open(` 文本出现次数 = 1 015（`md_cg` 707 / `hive` 211 / `scripts` 97）；「含 `open(` 且同行无 `encoding` 字样」= 198（其中同行无二进制字面量者 108）；正则数二进制字面量 open = 58。三者与 224 的关系＝**都不等于 224**，也不是 224 的分解 | **不可作判据**；本报告**未复跑**这三种代理口径，且任何 AST 口径（913 / 936 / 844 / 824）都得不出 224 |
| 中期（编排会话改口） | **103 处「裸 open」** | **可精确复现**（放宽为「`Name` open ｜ `Attribute` `.open`」且不做二进制豁免、也不区分内建/Attribute 时，三目录「无 encoding」恰为 103） | 数字本身自洽，但**混入两类非缺口**，故不可作缺口判据 |
| 最终（本批结论） | **89 处内建二进制 ＋ 9 处文本模式真缺口**（＋ 5 处 Attribute 假阳性 = 103） | **两侧独立复现**：批内扫描器与【本次】本报告作者自写扫描器、HEAD 物化树与工作树四条路径一致（§4.3） | **唯一能同时对上源码的口径** |

**103 的精确分解（HEAD 时点）**：`89` 内建二进制（**加了 encoding 是非法**，见 B6）＋
`9` 内建文本缺口（＝§1.2 的 9 行，现树已 0）＋ `5` 处 Attribute 形态无 `encoding`
（`md_cg/fsutil.py:204 os.open`、`md_cg/lexicon/build_cedict_en_zh.py:60 io.open "wb"`、`:62 gzip.open "rb"`、
`scripts/check_publish_artifact.py:696 tarfile.open r:gz`、`scripts/criteria_fingerprint.py:45 tarfile.open`）
＝ **103**。即「103 里 89 处是二进制」这句话**只对内建子集成立**；按 open-类调用整体算是
**91 处二进制形态**（89 内建 ＋ 2 Attribute 二进制）。

**103 的两套分解（第 2 版补，回应「同一个 103 给出两套自称精确的分解」）**：§5.2 复核 basis 里引的是复核者的
「`103` ＝ 当前 **92** 处『内建 open 无 encoding 关键字』＋ 已订正 **11** 处，口径自洽」；本节给的是
「HEAD 时点 **89 ＋ 9 ＋ 5**」。**两式数值相等（都是 103），但成分不同、不是同一次扫描的分解，不能互相印证**：
`92 = 89 + 3`（那 3 处是**新增未追踪件** `scripts/test_utf8_boot_guard.py` 的二进制 open），
`11 = 9 + 2`（那 2 处正是本节判为误分类的 `write_text` 调用）——等式只靠 `5 = 3 + 2` 这个**数值巧合**成立。
以**能逐点对到源码行**的「89 ＋ 9 ＋ 5（全为 HEAD 时点）」为准；复核者那式是其**口径自述**（本轮未按点复核其 11 的真伪）。

**一处必须点名的偏差**：任务书把最终真值表述为「**89 处二进制 ＋ 11 处文本模式真缺口**」。
本报告作者据**两项独立复核 ＋ 自身读码与扫描**认定：**11 是订正前的契约清单点数，其中 2 处
（`scripts/_mdcg_reindex_dshlogs.py:365/:411`）经实读为模块内自建 `write_text` 的**普通函数调用**
（该文件 `:148-151` 已显式 `encoding="utf-8", newline="\n"`），机械加参会 `TypeError` 打断脚本**
⇒ **真缺口为 9**，`89 + 9 = 98`。**排除「11」的依据是这两处点位的第一手实读**（helper 源码 ＋ `TypeError` 实测），
**不是算术**——第 1 版曾用「`89 + 11 = 100` 不等于任何一轮总数」作旁证，该论证**不成立**
（各轮总数 913 / 936 / 844 / 824 与 100 本来就不会相等，故排除不了 11），本版**删除该句**；
同理 `89 + 9 + 5 = 103` 只是与放宽口径的**同源复算**，也不构成独立印证。
（两类原始读数见 §2.2 B3/B4、§4.3。）

### 6.2 守卫的假阳性教训（判据只认内建 `open`）

- **外形匹配必误报**：按 `attr == 'open'` 匹配会把 `os.open` / `io.open` / `tarfile.open` / `gzip.open` /
  `zipfile.ZipFile.open` 一并算作裸 `open`；三目录内 Attribute `.open` 共 **66** 处，其中无 `encoding` 的
  **5** 处全是这类（§2.2 B7），**加 `encoding=` 到这些点位上是错的**：
  `os.open` 第二实参是 int 标志位、`os.open` **没有 encoding 参数**；`tarfile.open(mode="r:gz")` 的 mode
  不含 `'b'` 时会落进「文本模式」分支而被误判（`check_publish_artifact.py:696`、`criteria_fingerprint.py:45`）；
  `io.open("wb")`/`gzip.open("rb")` 本就是二进制流。⇒ 判据必须落在**语法意义**（`ast.Name` 且
  `id=='open'`，再看 mode/encoding 关键字），不落在外形上。
- **二进制模式必须显式豁免**：`open(p,'wb'|'ab'|'rb', encoding='utf-8')` 三种模式全部抛
  `ValueError: binary mode doesn't take an encoding argument` ⇒ 89/92 处二进制不在「缺 encoding」的统计面内。
- **同名函数的第二类假阳性**：`write_text(p, text)` 形态的**模块内自建同名函数**不是 `Path.write_text`；
  全仓裸名 `write_text` 调用恰为 `scripts/_mdcg_reindex_dshlogs.py:365/:411` 两处 ⇒ 把它们当成缺口是误分类。
- **两类教训已固化为锚**（守卫因此「陈化即报」）：`_ANCHOR_CORPUS` 的 22 片段含 `attr_os_open`/`attr_io_open`/
  `attr_tarfile_open`/`attr_gzip_open`/`attr_zipfile_open` 预期 0；`_ATTR_CONTROL_FILES`（5 文件）＋
  `_ATTR_CONTROL_POINTS`（5 点位级）把「被误报的那一类形态仍在对照面上」钉死，漂移即 rc=2。
- **口径工具本身的教训**：正则口径数二进制字面量只得 **58**（AST 得 89/92），说明文本/正则口径会**漏数**；
  守卫与复核都改用 AST。

### 6.3 覆盖边界（守卫**不**覆盖什么）

| 面 | 覆盖 | 依据 |
|---|---|---|
| 三目录 `.py` 的**内建** `open` 文本模式调用 | ✅ | `scripts/verify_open_encoding.py:59` `SCAN_DIRS`；`:144` 只认 `ast.Name`＋`id=='open'` |
| 三目录 `Path.read_text`/`write_text` 缺 `encoding` | ✅ | 判据④（本次实测 `read_text/write_text` 面 **6 处、缺 encoding 0**） |
| 三目录**二进制**模式内建 `open` | ✅（判为**不必**加） | 判据② |
| 七个进程入口的进程级 UTF-8 自保证 | ✅ | `utf8_boot.ensure_utf8` ＋ 守卫 `ANCHOR`/`GUIDE`/`IMPORT`/`STREAMS` |
| **非 Python 文本面**（`.ts`/`.rs`/`.md`/`.json`/`.sh` 的读写） | ❌ 不覆盖 | 守卫只 walk `*.py`；TS/Rust 侧仍靠既有 `PYTHONUTF8` 注入面（`src/lib/mdcg_client.ts:117-118`）与「全 UTF-8」约定 |
| Python **间接文本 I/O**：`os.fdopen` / `tempfile.*` / `codecs.open` / `subprocess(..., text=True)` / 经别名或变量调用的 `open` | ❌ 不覆盖（多数**不计入**） | 判据只认 `ast.Name`＋`id=='open'`；非本形态既不判违例也不计数 |
| **A 路守卫自身**的控制台自保证 | ✅（`scripts/test_utf8_boot_guard.py` 顶部调 `ensure_utf8`） | — |
| **B 路守卫自身**的控制台自保证 | ❌ **无**（已知未接项；第 2 版补实测后果） | `scripts/verify_open_encoding.py` 未接 `ensure_utf8`（§3.2 末）。clean env 下实测：正跑 **rc=1**、stdout 72 B **GBK 字节**、崩于 `:476` 的 `print("✔ …")`；`--self-test` 同因崩于 `:444`；`scripts/test_verify_open_encoding.py` rc=0 但 stdout 亦非 UTF-8 |
| 除此之外的仓根其余 `.py`（三目录之外） | 不计（**额外查证**：本轮扩扫全仓，三目录之外文本裸 `open` = **0**） | §2.2 B8 |

### 6.4 未覆盖 / 未验证清单（据本批两项复核的 uncovered ＋ 本次核查）

1. **Linux / C-locale / 容器**：全部结论只来自本机 Windows/CP936 现场；**容器两栈退出码 127/127，本次未复跑**
   （本机 docker daemon 未运行，§4.4）⇒ 容器面**未验证**。
2. **真宿主端到端未测**：未连 DSH/Claude/code CLI 的真 `mcp.json`、未起真 serve。
3. **check 粒度的一处定点变异缺口**：`E2E-HIVE` 在守卫变异表中**没有任何变异能把它打红**（M1 只红 `E2E-MDCG`）；
   其可打红性由复核者的场外变体 B 证明，但**该变异不在守卫定点表内** ⇒ 契约⑦「每处判据都要有定点变异打红」
   在此粒度未完全满足。
4. **`hive/exec_cmd.py` 未接线**（其自身 stdout/stderr 仍随 serve 继承的 locale；未实测，未判定为必须加）。
5. **「其余约 60 个带 `__main__` 的一次性工具」未逐一评估**。
6. **未实测**「`md_cg.mcp_server` 被当库 import 后由第三方调 `main()`」形态（该形态按 F6 不重启，仅靠
   `_force_utf8_stdio` 兜底）。
7. **B 路的「11 处逐点订正」字面不可满足**（9 真 ＋ 2 误分类），见 §6.1；守卫是否接入 CI 门禁未核查。
8. **两条非阻断的设计张力**（交设计者裁决）：(a) `_set_child_env` 覆盖式写 `PYTHONIOENCODING`，
   使 `md_cg/test_issue39_utf8_stdio.py` 的 `gbk:strict` 模拟面前提在重启后变化（未跑该守卫复验）；
   (b) 契约②与④的字面冲突（实现取「先置 env 再早退」）。
9. **本报告自身的边界**：作者只读跑码 ＋ 只写本文件一件；未改任何源码；未 `git add/commit/push`；
   未重启在役 hive serve；未触碰在役数据根（探针与 HEAD 物化面全在 `%TEMP%`）。所有读数为**对应时刻快照**
   （批内已记录会话期间有并发写者改动七入口，计数在会话内漂移：文本 840→844、二进制 89→92）。
10. **B 路守卫自身在未设 `PYTHONUTF8` 的机器上不可用**（第 2 版实测新增）：`verify_open_encoding.py`
   会以 `rc=1`（与守卫自己「存在违例」的退出码**同码**）崩在「✔」的打印上（`UnicodeEncodeError`），
   其 stdout 落 GBK 字节（§3.2 末、§6.3）⇒ 该守卫的绿/红结论**只在已开 UTF-8 模式的现场成立**；
   换机器需调用方注入 env、或给守卫补接 `ensure_utf8`（建议与裁决归属见 §7-Q7）。
11. **工作区索引当前陈化 2 处**（第 2 版实测新增）：`python scripts/workspace_index.py --check` → **rc=1**，
   两条 DRIFT 均点名 `utf8_boot.py`「登记但不存在」——根因是索引从 **git 追踪面**（`git ls-files`）生成，
   而 `utf8_boot.py` 尚未追踪（`??`）。`scripts/workspace_index.py` 已把该件登记进 `ROOT_FILES`
   （`git diff` 2 行），`WORKSPACE_INDEX.md` 已随之重生成（HEAD 快照 `d7c6e347`→`174cd25f`、追踪件 1998→2076）。
   **随批 `git add` 即自动消失**（详见附清单与 §7-Q9）。
12. **224 的出处不闭环**：无命令/口径留存、不可复现（§6.1），本报告无法回溯它曾否有过依据。

---

## 7. 读者待决问题：本报告的判定、建议与新增证据

> 本节逐条回应读者反馈里的 `nextQuestions`（10 条）。**属裁决权的事项一律只给建议、标明归属，
> 本报告不代为决定**；本轮能补的证据已补（标注【本次】，命令见 §4.5 第 9–15 条）。

| Q | 问题 | 本报告能给的判定 / 新证据 | 归属与建议 |
|---|---|---|---|
| Q1 | 9 与 11 的偏差由谁裁决、契约文本是否回改 | 依据＝两处点位的**第一手实读**（helper `:148-151` 已显式 ＋ 机械加参 `TypeError`，§6.1）；`11` 是订正前清单点数，`9` 是真缺口（§4.3 两侧扫描一致）。**契约原文不在本报告读取面内，本报告无法回改它** | **验收方裁决**：建议按「9 真缺口 ＋ 2 处误分类」记通过，并在提交说明与契约文本中把 11→9 回改（§7-Q9） |
| Q2 | 容器两栈与 Linux/C-locale 面何时补跑、走本机 Docker 还是 CI | 本轮取证：本机 docker CLI 在位（28.4.0）但 **daemon 未运行**（`docker ps` rc=1，`//./pipe/dockerDesktopLinuxEngine` 不存在），故本机复跑**当前不可行**；容器形态在该脚本头注：`docker run --rm -v <repo>:/work -w /work rust:bookworm bash scripts/linux_verify.sh [full\|core]` | **裁决/排期归使用者**：建议启动 Docker Desktop 后跑 `core`，或落 CI；在跑通前，容器面与 Linux/C-locale 面在本批**记为未验证** |
| Q3 | 要不要给 `E2E-HIVE` 补一个能打红它的定点变异 | 新证据（【本次】）：**单点变异不可能打红它**——M1 只让 md_cg 入口死（`md_cg/mcp_server.py:3850` 相对 import ImportError），hive 入口直跑仍 rc=0 握手成功（§4.1 末）。能打红它的只有**双点**变异（同时停用 `ensure_utf8` 与 `_force_utf8_stdio`），而变异表是单点注入（`_sub :905-907`） | **裁决归使用者**：建议下一批给 `_MUTATIONS` 增一条**双点注入**的 M14（或把 E2E 判据拆出「仅 `_force_utf8_stdio` 生效」的子断言）；在此之前，契约⑦在该 check 粒度**按字面未满足**，本报告按「未满足」记而不按通过记 |
| Q4 | 全量套件是在 `PYTHONUTF8=1` 下跑的，clean env 下再跑是否同样绿 | **已补跑**（【本次】）：clean env（清 `PYTHONUTF8`/`PYTHONIOENCODING`/`PYTHONLEGACYWINDOWSSTDIO`、不带 `-X utf8`）下 `python scripts/run_tests.py` → **269/269 通过、5 跳过、rc=0、100.7s**，且 stdout 合法 UTF-8（runner 自身 `ensure_utf8` 重启了自己）。**套件层面验证到的层**＝「入口自保证 ＋ 后代 env 继承」两层：runner 自己重启 → 给子进程注入 env → 各入口再自保证 | 已闭环，无需裁决；若要更强的「逐入口在未开模式下自证」，那是 §4.1 A 守卫的 `ONCE/FAILFAST/NOOP/GUIDE` 面（已在守卫内跑） |
| Q5 | 批内失败的两个模块要定成 flaky 还是并发写者 | **已补**（【本次】）：clean env 下各跑 3 次 → **6/6 全 rc=0**（n212 每次 `PASS=42 FAIL=0`）；两次全量（UTF-8 env 与 clean env）里这两个模块也都 **PASS** | **已闭环（本机此刻不复现）**；本报告**不判定**其历史成因（要区分 flaky 与并发写者需更多轮次/并发复现实验），也不为其背书 |
| Q6 | `hive/exec_cmd.py` 与「其余约 60 个带 `__main__` 的一次性工具」是否纳入下一批、判据是什么 | 现状读码（复核口径）：`exec_cmd.py` 全部 `open` 显式 `encoding='utf-8'`，且 `:258` 给派生命令 `setdefault PYTHONUTF8='1'`；其**自身** stdout/stderr 仍随 serve 继承的 locale（未实测是否有害） | **裁决归使用者**：建议判据取「**其 stdout/stderr 会被宿主或调用方按 UTF-8 解析**的进程入口」＋「**会派生后代且后代默认编码随 locale** 的入口（后者用 env 传递即可）」；按此判据 `exec_cmd.py` 属「诊断输出会被读」一类，宜接 `ensure_utf8`（成本＝一次 `sys.path` 插入 ＋ 一行调用） |
| Q7 | B 路守卫自身未接 `ensure_utf8`，在没设 env 的机器上会不会落 GBK | **已实测（【本次】）且比读者设想的更严重**：clean env 下 `verify_open_encoding.py` **rc=1 ＋ 崩在 `:476` 的 `✔` 打印（`UnicodeEncodeError: 'gbk' codec can't encode '\u2714'`）＋ stdout 72 B 全 GBK**；`--self-test` 同因崩于 `:444`；`scripts/test_verify_open_encoding.py` rc=0 但 stdout 亦非 UTF-8。**`rc=1` 与「存在违例」同码**⇒ 未设 env 的机器上「崩溃」会被读成「有违例」 | **裁决归使用者**：建议与 A 路守卫对齐（该文件顶部加 `sys.path` 插入 ＋ `ensure_utf8(__file__)`）；若担心「守卫被 import 时重启」的副作用，助手的 F6 分支已保证被 import 时只置 env 不重启 |
| Q8 | 同路径的旧设计稿怎么处置（删/改名/加墓碑） | 现状（【本次】）：**该路径下已无独立设计稿**——工程报告首版覆盖了它；`docs/eval/` 下无第二份「编码面」文件；`git log -- docs/eval/编码面前置_…md` 无输出，即**设计稿正文无 git 留存副本**（当时是 `??`） | **裁决归使用者**：若要保留设计稿，只能从会话记录重写并另存名（如 `…_设计_v1.0.md`）或加墓碑；现状不再有「读者先读到三条未修」的问题（§5.1 uncovered 3b 已更新） |
| Q9 | 14 `M` ＋ 6 `??` 是否现在提交、提交说明是否写「11→9」 | 未提交是**硬边界**（本批与本次修订都不得 `git add/commit/push`）。**新证据（【本次】）**：`python scripts/workspace_index.py --check` → rc=1、陈化 2 处，均点名 `utf8_boot.py`「登记但不存在」，根因＝索引取 **git 追踪面**而该件未追踪 ⇒ **提交后自动消失**（§6.4 第 11 条） | **裁决归使用者**：建议提交时在说明里写明「契约 11 处 → 实为 9 处真缺口 ＋ 2 处误分类（`_mdcg_reindex_dshlogs.py:365/:411` 为模块内 helper 调用，加 `encoding=` 会 `TypeError`）」，并附 `--check` 由红转绿的验证 |
| Q10 | 真宿主端到端（真 `mcp.json`、真 serve）何时验、由谁验 | 现状：只有进程级 `-m` 证据（两 MCP 入口 initialize 握手成功），未连真宿主、未起真 serve（§5.1 uncovered 2） | **裁决归使用者**：建议由持有真宿主（DSH/Claude/code CLI）环境的一方在下一批验；本报告不把进程级证据冒充宿主级证据 |

---

### 附：本批新增/改动件清单（本报告作者读码所见）

| 件 | 状态 | 规模 |
|---|---|---|
| `utf8_boot.py` | `??` 新增 | 238 行 / 15 356 B / 无 BOM |
| `scripts/test_utf8_boot_guard.py` | `??` 新增 | 1 254 行 / 66 870 B / 无 BOM（11 判据 ＋ 13 变异） |
| `scripts/verify_open_encoding.py` | `??` 新增 | 482 行 / 24 253 B / 无 BOM |
| `scripts/test_verify_open_encoding.py` | `??` 新增 | 215 行 / 10 647 B / 无 BOM（26 条 `assert`） |
| 七个入口（各插锚块，零业务语义改动） | `M` | `hive/hive_mcp/mcp_server.py`、`md_cg/mcp_server.py`、`hive/exec.py`、`hive/orch.py`、`hive/serve_start.py`、`md_cg/run_tests.py`、`scripts/run_tests.py` |
| 5 个测试文件共 9 处 `open` 加 `encoding` | `M` | `md_cg/test_n199_tokens_concurrent_write.py`、`md_cg/test_security_audit_v21.py`、`hive/test_n144_exec_cmd_terminal_race.py`、`hive/test_stop_tree_kill.py`、`md_cg/test_lock.py` |
| `scripts/workspace_index.py` | `M` | **本批的第 18 条（工作区索引）收尾件**：把 `utf8_boot.py` 登记进 `ROOT_FILES`（`git diff` 2 行，新增该件的职责文案），本报告作者读 diff 确认 |
| `WORKSPACE_INDEX.md` | `M` | 随上条**重生成**的产物：快照 `HEAD d7c6e347 → 174cd25f`、追踪件 1998→2076，`md_cg/` 776→813、`hive/` 134→142、`scripts/` 45→57、`test/` 50→54、`docs/` 131→148（`git diff --numstat` 7/6 行） |

**合计**：`M` **14 个**（七入口 ＋ 五个测试文件 ＋ 两个索引件）＋ `??` **6 个**（本批新件 4 个 ＋ `.zcode/` ＋ 本报告文件本身）
——与文首「工作树」行的计数**同口径**；第 1 版附录少列了后两个索引件（第 2 版补齐）。
`python scripts/workspace_index.py --check` 当前 rc=1 的 2 处陈化即因 `utf8_boot.py` 尚未追踪所致（§6.4 第 11 条）。
