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
4. **存活判据只问「pid 号是否存在」**（v13 新发现 A，2026-09-17）：无关进程复用该
   pid 号即让 serve 被「假存活」挡住拒绝启动；且 mcp_server 只判 ts 新鲜度、rust 判
   新鲜 + pid —— 同一份心跳两面得两个结论，守卫与 `--stop` 两条逃生口同时失效。
5. **本测试硬读被 .gitignore 排除的 `config.local.json`**（v13 新发现 B）：
   新克隆仓里该文件不存在 → 崩在第一条断言之前，22 条断言一条跑不到。

修法：窗口收敛到单一常量源（`serve_start.FRESH_S`，rust 侧同值）、执行器资格
由 **serve 自报的心跳**（`exec_py`/`exec_mode`）承载、两面 doctor 同口径；
存活判据统一为**三层**（新鲜 + pid 存活 + 该 pid 是本程序），
`serve_start.serve_alive()` 是唯一实现、MCP 面复用不再自持一份；
配置载体 local 优先、缺失退回**入户模板** config.local.example.json。
本测试把上述口径固化为机械断言——任一漂移即红灯（脚本式，与仓内约定一致）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time

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


def _read_optional(rel: str) -> "str | None":
    try:
        return _read(rel)
    except OSError:
        return None


def main() -> int:
    main_rs = _read("hive/src/main.rs")
    job_rs = _read("hive/src/job.rs")
    sched_rs = _read("hive/src/scheduler.rs")
    mcp_py = _read("hive/hive_mcp/mcp_server.py")
    readme = _read("hive/README.md")
    spec_rs = _read("hive/src/spec.rs")
    # 配置载体（2026-09-17 v13 新发现 B）：本测试曾硬读 `config.local.json`——该名被
    # .gitignore 排除，新克隆仓里不存在，于是**第一条断言之前就 FileNotFoundError**，
    # 22 条断言一条跑不到（「守卫的绿灯来自没接电」）。修法：local 优先（部署实态），
    # 缺失则退回**入库模板** config.local.example.json；模板本身必须入库（硬断言）。
    cfg_local = _read_optional("hive/config.local.json")
    cfg_example = _read_optional("hive/config.local.example.json")
    cfg_txt = cfg_local if cfg_local is not None else cfg_example

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
    ss_py = _read("hive/serve_start.py")
    check("CLI cmd_serve 有单实例守卫", "serve_running(&jobs)" in main_rs)
    check("CLI 守卫可 --force 显式豁免", '"--force"' in main_rs)
    check("serve_start.start 有守卫", "def serve_alive" in ss_py)

    print("②b 存活判据三层（v13 新发现 A）：新鲜 + pid 存活 + pid 身份")
    # 根因：守卫原判据只问「pid 号是否存在」，无关进程（如 sleep）复用该 pid 号即让
    # serve 被「假存活」挡住拒绝启动，且文案引导运维去停一个并不存在的 serve。
    # 三层须在 rust / serve_start / mcp_server 三处同口径，且第三层只此一处实现逻辑。
    check("rust 有身份判据 pid_is_self_program", "fn pid_is_self_program" in main_rs)
    check("rust 单实例守卫含身份层",
          "pid_alive(*p) && pid_is_self_program(*p)" in main_rs)
    check("rust pid_alive 改精确列比对（无子串包含）",
          "s.contains(&pid.to_string())" not in main_rs)
    check("rust doctor 透出三层明细",
          '"pid_is_self_program"' in main_rs and '"pid_alive".to_string()' in main_rs)
    check("python 有身份判据 pid_is_self_program", "def pid_is_self_program" in ss_py)
    check("python serve_alive 含身份层",
          "pid_alive(pid) and pid_is_self_program(pid)" in ss_py)
    check("MCP _serve_alive 复用 serve_start（不再自持 ts-only 判据）",
          "serve_start.serve_alive(jobs)" in mcp_py)

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
    check("配置模板 config.local.example.json 已入库（干净克隆可跑）",
          cfg_example is not None, "缺失 → 新克隆必崩在首条断言之前")
    check("config 注释与 resolve() 同口径（非『首行』）",
          cfg_txt is not None and "首行" not in cfg_txt, "无任何 config 载体可评")
    check("本地 config.local.json 注释同口径（若存在）",
          cfg_local is None or "首行" not in cfg_local)

    print("⑥ 假存活端到端复现：pid 号存活但非 serve → 不得判活")
    # 把 v13 实测的四种心跳形态灌进临时 jobs 目录，断言判活为假——修复前情形 1
    # （无关进程复用 pid 号）会被判成「serve 在跑」而拒绝启动，且 `--stop` 又说没在跑。
    tmp = tempfile.mkdtemp(prefix="hive_entry_hb_")
    real_exe = serve_start.EXE

    def _write_hb(pid: int, age_ms: float) -> None:
        with open(os.path.join(tmp, "_serve.json"), "w", encoding="utf-8") as f:
            json.dump({"ts": time.time() * 1000 - age_ms, "pid": pid, "workers": 1}, f)

    try:
        # EXE 指向一个不存在的程序名：本进程（python）必然与之不同名 → 身份层判假。
        serve_start.EXE = os.path.join(os.path.dirname(real_exe), "definitely_not_hive.exe")
        _write_hb(os.getpid(), 0)
        check("存活层：本进程 pid 判存活", serve_start.pid_alive(os.getpid()) is True)
        check("身份层：本进程映像名非 hive → 判假",
              serve_start.pid_is_self_program(os.getpid()) is False)
        check("情形1 假存活心跳不判活（修复前会误挡启动）",
              serve_start.serve_alive(tmp) is False)
        _write_hb(999999, 0)
        check("情形2 pid 不存在 → 不判活", serve_start.serve_alive(tmp) is False)
        check("pid_alive(不存在) 判假", serve_start.pid_alive(999999) is False)
        _write_hb(os.getpid(), 60_000)
        check("情形3 心跳过期 → 不判活", serve_start.serve_alive(tmp) is False)
        with open(os.path.join(tmp, "_serve.json"), "w", encoding="utf-8") as f:
            f.write("{ 坏 json")
        check("心跳损坏 → 不判活且不抛异常", serve_start.serve_alive(tmp) is False)
    finally:
        serve_start.EXE = real_exe
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print("ALL OK: serve 入口口径守卫全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
