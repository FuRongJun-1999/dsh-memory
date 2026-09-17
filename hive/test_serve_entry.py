"""serve 入口口径守卫：MCP 面与 CLI 面的「推荐配置」必须同口径（防漂移）。

背景（2026-09-17 实测缺陷，使用者裁定 C）：hive 有两个启动入口——
`hive/serve_start.py`（读 config.local.json 注入完整 env）与裸 `hive.exe serve`
（**不读任何配置**，只认进程 env，执行器回退 exec.py → 确定性执行不可用）。
二者 env 口径不同，却长期存在三类漂移（同一约束、两种执行结果）：

1. **存活判定窗口三处不一致**：mcp_server 硬编码 5.0s / serve_start 15s /
   CLI doctor 5000ms。窗口偏小会把「心跳稍慢」误判为死，进而由 `_ensure_serve`
   重复拉起第二个 serve（双实例抢队列 / `_serve.json` pid 互覆 / `--stop` 杀不全）。
2. **CLI serve 无单实例守卫**（MCP 侧 `serve_start.start()` 有）。
3. **doctor 用「诊断进程 env」当资格判据**——而 serve 的 env 在启动时固化、
   子进程无法反查，据此判资格必得错位结论。

修法：窗口收敛到单一常量源（`serve_start.FRESH_S`，rust 侧同值）、执行器资格
由 **serve 自报的心跳**（`exec_py`/`exec_mode`）承载、两面 doctor 同口径。
本测试把上述口径固化为机械断言——任一漂移即红灯（脚本式，与仓内约定一致）。
"""
from __future__ import annotations

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def _read(rel: str) -> str:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    main_rs = _read("hive/src/main.rs")
    job_rs = _read("hive/src/job.rs")
    sched_rs = _read("hive/src/scheduler.rs")
    mcp_py = _read("hive/hive_mcp/mcp_server.py")
    readme = _read("hive/README.md")
    spec_rs = _read("hive/src/spec.rs")
    cfg_txt = _read("hive/config.local.json")

    import hive.serve_start as serve_start
    from hive.hive_mcp import mcp_server as ms

    print("① 存活判定窗口：单一常量源 + 跨语言同值")
    check("serve_start.FRESH_S == 15.0", float(serve_start.FRESH_S) == 15.0,
          f"got {serve_start.FRESH_S}")
    check("mcp_server._fresh_s() 复用 serve_start.FRESH_S",
          float(ms._fresh_s()) == float(serve_start.FRESH_S),
          f"got {ms._fresh_s()}")
    m = re.search(r"const FRESH_MS: f64 = ([\d_]+)\.0;", main_rs)
    check("rust 侧 const FRESH_MS 存在", bool(m), "未找到 const FRESH_MS")
    if m:
        check("rust FRESH_MS == serve_start.FRESH_S*1000（同口径）",
              int(m.group(1).replace("_", "")) == int(float(serve_start.FRESH_S) * 1000),
              f"got {m.group(1)} vs {serve_start.FRESH_S}")
    check("mcp_server 无硬编码 5.0s 窗口（已收敛到常量源）",
          "< 5.0" not in mcp_py)

    print("② 单实例守卫：CLI serve 与 serve_start.start 同约束")
    check("CLI cmd_serve 有单实例守卫", "serve_running(&jobs)" in main_rs)
    check("CLI 守卫可 --force 显式豁免", '"--force"' in main_rs)
    check("serve_start.start 有守卫", "def serve_alive" in _read("hive/serve_start.py"))

    print("③ 执行器资格：serve 自报心跳（权威），两面同源读")
    check("job.rs 心跳写 exec_py", '"exec_py"' in job_rs)
    check("job.rs 心跳写 exec_mode", '"exec_mode"' in job_rs)
    check("scheduler 心跳带 exec_py/exec_mode",
          "write_serve_heartbeat(&cfg.jobs, cfg.workers, &cfg.exec_py, &cfg.exec_mode)"
          in sched_rs)
    check("scheduler 有 exec_mode_of 判据", "pub fn exec_mode_of" in sched_rs)
    check("CLI doctor 采信 serve_heartbeat", '"serve_heartbeat"' in main_rs)
    check("MCP doctor 读心跳 exec_py", 'hb.get("exec_py")' in mcp_py)

    print("④ 推荐入口唯一：两面 start_cmd 都指向 serve_start.py")
    check("CLI start_cmd 指向 serve_start.py",
          "python hive/serve_start.py（唯一推荐" in main_rs)
    check("MCP start_cmd 指向 serve_start.py",
          "python hive/serve_start.py（唯一推荐" in mcp_py)

    print("⑤ 文档/注释不得回退到错口径")
    check("README 无『两条拉起路径口径一致』错述", "两条拉起路径口径一致" not in readme)
    check("README 明示裸 serve 不读配置", "不读 config.local.json" in readme)
    check("README env 表标注 llm_only 回退", "llm_only" in readme)
    check("spec.rs 注释无写死模型名（防与部署 base 漂移）", "glm-4.7" not in spec_rs)
    check("config 注释与 resolve() 同口径（非『首行』）", "首行" not in cfg_txt)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print("ALL OK: serve 入口口径守卫全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
