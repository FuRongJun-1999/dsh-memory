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

**守卫面覆盖（v14 补格）**：存活判据有**四处**实现/消费——rust `serve_running`、
`serve_start.serve_alive`、`mcp_server._serve_alive`、`md_cg/units.serve_state`
（复制契约不 import hive，保持 md_cg 对 hive 零依赖）。前三处由 ①/②b 覆盖，
第 4 处（units）曾长期**在守卫之外**，并双漂移到「ts-only + 5s」——其后果
是**通道选择面**的假存活（提交的 job 永远无人处理），即 v13 病类换了个位置
复现。⑦ 节把 units 纳入守卫：常量同值 + 三层判据在位 + 同一份心跳两处实现同结论。
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
    # 批次 10（6658f0a）起心跳升级为 _ext 五参（+instance/role/fingerprint 身份三键）——
    # 旧四参断言成陈旧断言（v18 外评测试债①：产品行为自洽，测试字符串没跟上）
    check("scheduler 心跳带 exec_py/exec_mode（_ext 签名）",
          "job::write_serve_heartbeat_ext(" in sched_rs
          and "&cfg.exec_py," in sched_rs and "&cfg.exec_mode," in sched_rs)
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

    print("⑦ md_cg/units 通道选择面同口径（v14 缺陷 E：判活第 4 处实现）")
    # 报告 v14：`md_cg/units.py` 自持一份 serve 判活口径（**ts-only + 5s**），
    # 双漂移于权威三层 + 15s。后果不是「测试红」而是**通道选错**：serve 崩溃后
    # ≤5s 窗口内判「存活」→ probe() 选 hive 通道 → 提交的 job 永远无人处理。
    # 本节判据=「同一份心跳，两处实现同结论」——与 ①/②b 的常量/结构断言互补。
    import md_cg.units as units
    check("units.FRESH_S == serve_start.FRESH_S（单一常量源）",
          float(units.FRESH_S) == float(serve_start.FRESH_S),
          f"got {units.FRESH_S} vs {serve_start.FRESH_S}")
    units_py = _read("md_cg/units.py")
    check("units 有身份判据 pid_is_self_program",
          "def pid_is_self_program" in units_py)
    check("units.serve_state 三层判据在位（新鲜 ∧ pid 存活 ∧ pid 身份）",
          "pid_alive(pid)" in units_py and "pid_is_self_program(pid)" in units_py,
          "units 未调用三层判据函数")
    check("units 契约注释不再自称『同 _serve_alive』",
          "（同 _serve_alive）" not in units_py)
    tmp2 = tempfile.mkdtemp(prefix="hive_entry_units_")
    fake_exe = os.path.join(os.path.dirname(real_exe), "definitely_not_hive.exe")
    serve_start.EXE = fake_exe
    os.environ["HIVE_EXE"] = fake_exe          # units 侧经 env 注入同一「非本程序」
    try:
        cases = [("新鲜 + 本进程 + 非本程序映像", os.getpid(), 0),
                 ("同类心跳 age=8s（旧 5s 阈值会判假）", os.getpid(), 8000),
                 ("同类心跳 age=20s", os.getpid(), 20000),
                 ("pid 不存在", 999999, 0),
                 ("pid 不存在且陈旧", 999999, 60000)]
        for label, pid, age in cases:
            with open(os.path.join(tmp2, "_serve.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"ts": time.time() * 1000 - age, "pid": pid,
                           "workers": 1}, f)
            a = bool(units.serve_state(tmp2)["alive"])
            b = bool(serve_start.serve_alive(tmp2))
            check(f"⑦ {label}：units={a} / serve_start={b}（须同结论）", a == b)
        with open(os.path.join(tmp2, "_serve.json"), "w", encoding="utf-8") as f:
            f.write("{ 坏 json")
        check("⑦ 心跳损坏：units 亦不判活且不抛",
              bool(units.serve_state(tmp2)["alive"]) is False)
    finally:
        serve_start.EXE = real_exe
        os.environ.pop("HIVE_EXE", None)
        shutil.rmtree(tmp2, ignore_errors=True)

    # ⑧ D-1 能红（v18 外评，2026-09-23）：config 里的 HIVE_JOBS_DIR 必须真正参与
    # jobs 决策——patch Popen 捕获 `--jobs` 实参（不起真进程）。旧实现模块级
    # JOBS 在 import 时固化并被显式 `--jobs` 钉死，config 键被静默丢弃
    # （env_keys 自报含它、jobs_dir 却不变）：本测试在旧代码下必红。
    print("⑧ D-1：config 的 HIVE_JOBS_DIR 参与 jobs 决策（延迟解析）")
    tmp3 = tempfile.mkdtemp(prefix="hive_d1_")
    try:
        cfg_dir = os.path.join(tmp3, "alt_jobs")
        cfg_path = os.path.join(tmp3, "config.local.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"HIVE_JOBS_DIR": cfg_dir}, f)
        captured = {}

        def _fake_popen(cmd, **_kw):
            captured["cmd"] = cmd
            raise OSError("d1-sentinel")   # start 捕获 OSError → 返回拉起失败

        real_popen, real_alive = serve_start.subprocess.Popen, serve_start.serve_alive
        serve_start.subprocess.Popen = _fake_popen
        serve_start.serve_alive = lambda *_a, **_k: False
        try:
            r = serve_start.start(cfg_path)
        finally:
            serve_start.subprocess.Popen = real_popen
            serve_start.serve_alive = real_alive
        jobs_used = None
        if isinstance(captured.get("cmd"), list) and "--jobs" in captured["cmd"]:
            jobs_used = captured["cmd"][captured["cmd"].index("--jobs") + 1]
        check("⑧a start 把 --jobs 指向 config 指定目录（能红旧实现）",
              jobs_used == cfg_dir,
              f"used={jobs_used} want={cfg_dir} ret={str(r)[:90]}")
        check("⑧b 决策点单一（_jobs_from 缺省回落模块级 JOBS）",
              serve_start._jobs_from({}) == serve_start.JOBS)
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    # ⑨ D-1 续（2026-09-25 缺陷）：--stop/--status 也须经 _jobs_from 吃进
    # config 的 HIVE_JOBS_DIR——此前两条 CLI 生命周期路径用模块级 JOBS，
    # config-only 设该键时 serve 跑在池 B、--stop 永远盯着池 A 报「未在运行」。
    print("⑨ --stop/--status 目标池与 start 同口径（D-1 修复续）")
    tmp4 = tempfile.mkdtemp(prefix="hive_d1b_")
    try:
        alt_dir = os.path.join(tmp4, "alt_jobs")
        cfg_path = os.path.join(tmp4, "config.local.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"HIVE_JOBS_DIR": alt_dir}, f)
        check("⑨a _lifecycle_jobs 读到 config 的 HIVE_JOBS_DIR",
              serve_start._lifecycle_jobs(cfg_path) == alt_dir,
              f"got={serve_start._lifecycle_jobs(cfg_path)} want={alt_dir}")
        check("⑨b config 缺失时降级不抛（回落 env/模块级默认）",
              serve_start._lifecycle_jobs(
                  os.path.join(tmp4, "nope.json")) == serve_start.JOBS)
        # status(jobs) 以给定池为准（jobs_dir 如实透出实际生效目录）
        os.makedirs(alt_dir, exist_ok=True)
        with open(os.path.join(alt_dir, "_serve.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"ts": 1, "pid": 999999, "workers": 1}, f)
        st = serve_start.status(alt_dir)
        check("⑨c status(jobs) 盯指定池（jobs_dir/心跳均取自该池）",
              st.get("jobs_dir") == alt_dir and st.get("heartbeat", {}).get("pid") == 999999,
              f"jobs_dir={st.get('jobs_dir')}")
        # main() 接线守卫（源断言）：--stop/--status 均经 _lifecycle_jobs
        check("⑨d CLI main --stop/--status 经 _lifecycle_jobs（源接线）",
              "stop(_lifecycle_jobs(cfg))" in ss_py
              and "status(_lifecycle_jobs(cfg))" in ss_py)
    finally:
        shutil.rmtree(tmp4, ignore_errors=True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print("ALL OK: serve 入口口径守卫全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
