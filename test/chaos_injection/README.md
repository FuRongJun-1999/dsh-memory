# 故障注入套件（FI-R01..R09 runtime 面 · FI-M01..M09 mdcg 面）

九源 × 七类故障注入实验的守卫级固化（实验员纪律：真实注入、实测观测、四可
逐项判定、EXPECTED_GAP 登记）。理论判据：
`docs/theory/不可靠定理与失效优先框架_v0.3.md`（T0-T14/A1-A4/D1-D6）、
`docs/不可靠性理论_v0.1.md`（S1-S9/P1-P12）。

## 用例表 · runtime 面（FI-R，serve/调度/WAL 面）

| case | 源→故障 | 注入 | 登记 verdict | 留档 |
|---|---|---|---|---|
| FI-R01 | S9 时钟回拨 | 进程内 mock time.time ±3600s 拆层判 `_serve.json` 残留心跳 | pass（P5 分层兜住） | - |
| FI-R02 | S1 杀进程 | serve 起跑后硬杀→重启 recover_orphans | pass（诚实标 error） | - |
| FI-R03 | S6/S4 静默改写 | 手搭现场伪造 result.json ok=true | **gap** | NEW(P11-待建) |
| FI-R04 | S4 字节翻转 | WAL payload 单字节 o→O 翻转 | pass（HMAC 捕获+定位） | - |
| FI-R05 | S1/S8 消息丢失 | WAL 整行物理删除 | **gap** | NEW(P0-2/seq连续性) |
| FI-R06 | S3 消息乱序 | WAL 行序交换 + submit 依赖不存在 | **gap**（①半）+拦截（②半） | NEW(P0-2/seq连续性) |
| FI-R07 | S3 消息重复 | 双 serve 竞争领取同一任务 | pass（claim 原子锁恰好一次） | 次观测=P0-2 基线 |
| FI-R08 | S8 平台默认值 | 公开常量 DEFAULT_SECRET 伪造签名 WAL | **gap** | N143（v17.md:85） |
| FI-R09 | S1 句柄对撞 | CreateFileW 持句柄撞 os.replace 重试窗 | pass（P2 原子写） | - |

## 用例表 · mdcg 面（FI-M，md_cg 记忆本体）

| case | 源→故障 | 注入 | 登记 verdict | 留档 |
|---|---|---|---|---|
| FI-M01 | S9 时钟回拨 | monkeypatch tokens.time ±3600s 打令牌 TTL 判定 | **gap**（回拨洗白；对照格正确时钟拦截） | v0.1§2.9承重面(A2单调锚待建) |
| FI-M02 | S1 资源剥夺 | CreateFileW(dwShareMode=0) 制造瞬态读失败→负结果入读缓存 | **gap**（get 能读/search 永搜不到撕裂） | N134（v16.md:86） |
| FI-M03 | S2 静默改写 | reinforce 写盘成功不标脏，检索面读旧值 | **gap**（盘上 0.8 / search 0.5） | N133（v16.md:85） |
| FI-M04 | S3 并发对撞 | beat/heal/add 同实例交叠 4s | **gap**（diagnose 裸迭代 RuntimeError；计数守恒/零撕裂） | N138（v16.md:90） |
| FI-M05 | S3 半程死亡 | 子进程 begin 后 TerminateProcess，父进程对账 | pass（interrupted 如实标记+对照格 committed+幂等） | - |
| FI-M06 | S6 静默改写 | 伪造「已验证成功」回答喂 verify_answer | pass（L2 无 hits 拦截） | - |
| FI-M07 | S7 误配 | MDCG_TOKEN_FILE="" vs 未设比对解析值 | **gap**（同路径零告警静默回落） | N91同型（v17.md:102） |
| FI-M08 | S4 字节翻转 | frozen.json digest 首字符 XOR 0x01 调 assert_a3 | pass（A3 比对失败→verdict 作废） | - |
| FI-M09 | S5 越权指令 | guest Principal 直调 add 写入 | pass（AccessDenied 显式拒绝零半成品） | - |

mdcg 面安全边界：每 case 经 `mdcg_support.apply_env` 把 MDCG_ROOT/DATA/AUX/
STATE/TOKEN_FILE/SUSTAIN_DIR 全部钉进 `chaos_fi_*` 临时目录、MDCG_MASTER_KEY
为哑 hex；**真实令牌库/真实 serve/真实数据目录零接触**。

## 运行方式

```bash
# 全量（推荐，任意 cwd 均可）
python test/chaos_injection/run_all.py

# 按关键字过滤 / 只列目标
python test/chaos_injection/run_all.py -k R04
python test/chaos_injection/run_all.py --list

# 单 case 直跑（test/ 非 python 包——`import test` 命中 stdlib test 包，
# 实测 Python 3.12 解析到 Lib\test\__init__.py，故不走 -m，与 scripts/ 同约定）
python test/chaos_injection/test_fi_r01_clock_rollback.py
```

单 case 每行断言打印 `OK  /FAIL`；末行 `CASE_RESULT {json}` 为机器可读结论
（verdict/expected/consistent/fails/notes），run_all.py 据此汇总。

## 退出码语义

- **0** = 全部用例观测状态与 `registry.py` 登记一致：pass 用例全绿（回归守卫）
  + EXPECTED_GAP 用例确认缺口仍在（基线维持，不红 CI）。
- **1** = 出现未登记的新 gap（pass 用例回归/防线弱化）、用例执行层崩溃
  （untestable，硬红）、或 EXPECTED_GAP 缺口消失（提示改登记结案——修复落地
  属好消息，但须同步 `registry.py` 把该格改写为 pass 留痕）。

## 环境要求与安全边界

- Windows + Python 3 标准库（零第三方依赖）；`hive/target/release/hive.exe`
  须已构建（FI-R02/03/06/07 用真实 exe，`--jobs` 全指临时目录）。
- 所有注入只发生在 `tempfile.mkdtemp(prefix="chaos_fi_*")` 系统临时目录与
  自建哑进程树/哑密钥/哑 WAL 上：**不触真实 serve、真实令牌库、真实数据
  目录**；每个 case finally 树杀自建进程并 rmtree 临时目录。
- FI-R01 的 mock 只作用于 case 进程内的 `time.time`，不影响其它进程。
