#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hive serve 启动器：读本地配置文件注入 env，detached 拉起/停止/查看 serve。

用法（Windows 实测形态，Python 3 标准库零第三方依赖）：
    python hive/serve_start.py            # 拉起 serve（已在跑则拒绝，防双实例）
    python hive/serve_start.py --stop     # 停止 serve（读心跳 pid）
    python hive/serve_start.py --restart  # 重启 serve（stop→start 原子序；改配置/换执行器后使改动生效）
    python hive/serve_start.py --rebuild  # 重编译并重启（stop→cargo build→start；rust 改动一条命令生效）
    python hive/serve_start.py --status   # 查看心跳与任务统计

配置文件（默认与脚本同目录 config.local.json，--config 可指他处）：
    JSON 对象，键=环境变量名，值支持三形态：
      "字符串"                  直值
      {"env": "DEEPSEEK_API_KEY"}   读系统环境变量（key 明文不落盘）
      {"file": "/path/to/api_key.txt"}  读文本文件全部内容并 strip（key 放仓外私有目录）
    解析失败的键 fail fast 拒绝拉起，防止残缺 env 的 serve 上岗。

本模块同时是**库**：mcp_server 首次拉起 serve 时调用 start()，故三个路径常量都可由
环境变量覆盖（HIVE_CONFIG / HIVE_EXE / HIVE_JOBS_DIR），使同一套拉起逻辑同时服务
「真实部署」与「隔离测试」两种形态。start()/stop()/status() 只返回 dict 不打印——
stdio JSON-RPC 通道上多打一行即污染协议；打印只发生在 CLI 入口（emit）。
"""
import json
import os
import subprocess
import sys
import time

HIVE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.environ.get("HIVE_CONFIG") or os.path.join(HIVE_DIR, "config.local.json")
# 与 mcp_server.py 的 _exe_path / _jobs_dir 同一口径（同一环境变量），避免两条拉起路径漂移
EXE = os.environ.get("HIVE_EXE") or os.path.join(
    HIVE_DIR, "target", "release", "hive.exe" if os.name == "nt" else "hive")
JOBS = os.environ.get("HIVE_JOBS_DIR") or os.path.join(HIVE_DIR, "jobs")
SERVE_LOG = os.path.join(JOBS, "_serve.log")
HEARTBEAT = os.path.join(JOBS, "_serve.json")
FRESH_S = 15  # 心跳新鲜窗口（serve 每拍 <1s 刷）。**须与 src/main.rs 的 FRESH_MS=15000 同值**——两面判「serve 是否在跑」必须同口径，否则同一个 serve 得两个结论


# 生效条件：obj 为 dict（非 dict 时 obj.get 会抛 AttributeError）时打印其 ensure_ascii=False 的 JSON，并返回 0 当 obj.get("ok") 为真值，否则返回 1（ok 缺失或为 0/""/None/[] 等假值同样返回 1）。
def emit(obj):
    """打印 + 返回退出码。**只有 CLI 入口用它**；库层调用请直接取返回值。"""
    print(json.dumps(obj, ensure_ascii=False))
    return 0 if obj.get("ok") else 1


# 生效条件：v 为 str 时原样返回（空串也返回空串）；v 为含 "env" 键的 dict 时返回 os.environ.get(该名, "") 去空白后的值、空串则回落 None；v 为 dict 且无 "env" 键但有 "file" 键时读该路径去空白、空则 None、抛 OSError 则 None（非 UTF-8 内容抛出的 UnicodeDecodeError 未被捕获）；其余 dict 及非 str/dict 一律返回 None。
def resolve(v):
    """配置值三形态解析：str 直值 / {"env": name} / {"file": path}。失败返回 None。"""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if "env" in v:
            return os.environ.get(v["env"], "").strip() or None
        if "file" in v:
            try:
                with open(v["file"], "r", encoding="utf-8") as f:
                    return f.read().strip() or None
            except OSError:
                return None
    return None


# 生效条件：path 不存在时直接返回 (None, "配置文件不存在：{path}")；存在但 open/json.load 抛 OSError 或 ValueError 时返回解析失败；读入 JSON 对象后遍历其键，下划线开头键跳过，其余键经 resolve 得 None 即记入 bad 并返回 (None, 配置项解析失败…)，全部通过返回 (env, None)。
def load_config(path):
    if not os.path.exists(path):
        return None, f"配置文件不存在：{path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"配置文件解析失败：{e}"
    env, bad = {}, []
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        val = resolve(v)
        if val is None:
            bad.append(k)
        else:
            env[k] = val
    if bad:
        return None, f"配置项解析失败（来源 env 未设或文件不可读）：{', '.join(bad)}"
    return env, None


# 生效条件：jobs 为真值时读 os.path.join(jobs, "_serve.json")，jobs 为 None 或空串等假值时回落模块常量 HEARTBEAT，该路径能打开且 json.load 成功则返回其内容，抛 OSError/ValueError 则返回 None。
def heartbeat(jobs=None):
    """读 serve 心跳。jobs 给定时读该 jobs 目录的 `_serve.json`（MCP 面用于对齐自己的 jobs）。"""
    path = os.path.join(jobs, "_serve.json") if jobs else HEARTBEAT
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# 生效条件：对传入的 pid（未做类型与正负校验，比较用 str(pid)）执行 tasklist /FO CSV 后，在其 stdout 中遇到的第一个按 '","' 切分、列数≥2 且第 2 列 strip 再 strip('"') 后等于 str(pid) 的行即返回 [第 1 列映像名, pid 字符串]，无此行或 subprocess.run 抛 OSError 时返回 None。
def _tasklist_row(pid):
    """Windows：查该 pid 的 tasklist 行 → [映像名, pid 字符串]；查不到返回 None。

    用 `/FO CSV` 后按列精确比对，**不用子串包含**——旧实现 `pid 字符串 in 输出`
    会让 pid=441 被 4410 命中（假存活）。
    """
    try:
        # 显式 utf-8 + replace：只消费 ASCII 的 pid 列，但**不依赖 locale**——
        # 否则子进程后代按 cp936 解 UTF-8 诊断时读线程会崩（2026-09-20 取证，
        # 见 md_cg/test_subproc_encoding.py 头注）。
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in (r.stdout or "").splitlines():
        cols = line.split('","')
        if len(cols) >= 2 and cols[1].strip().strip('"') == str(pid):
            return [cols[0].strip().strip('"'), cols[1].strip().strip('"')]
    return None


# 生效条件：pid 为 int 且大于 0 时（否则直接返回 False），os.name 为 "nt" 时返回 _tasklist_row(pid) 是否非 None，非 "nt" 时 os.kill(pid, 0) 未抛 OSError 返回 True、抛 OSError 返回 False。
def pid_alive(pid):
    """该 pid **号**是否存在（Windows tasklist 精确列比对 / unix `kill -0`）。

    只回答「这个号有没有进程」——**不足以判定「serve 还在跑」**，见 `pid_is_self_program`。
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _tasklist_row(pid) is not None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# 生效条件：模块常量 EXE 的 basename 小写 want 非空且 pid 为 int 大于 0 时（否则 False），"nt" 下要求 _tasklist_row(pid) 非空且其映像名小写等于 want，非 "nt" 下要求 /proc/<pid>/cmdline 首个 b"\x00" 前 token 的 basename 小写等于 want（读取抛 OSError 则 False），相等返回 True，否则 False。
def pid_is_self_program(pid):
    """该 pid 是否**就是本程序**（同映像名）——pid 号会被无关进程复用。

    2026-09-17 第三方 v13 实测缺陷（新发现 A）：单实例守卫原判据只问「pid 号是否
    存在」，任何无关进程（如 sleep）复用该 pid 号都会让 serve 被「假存活」挡住拒绝
    启动，且文案引导运维去停一个并不存在的 serve。故加一层身份核对：
    Windows 取 tasklist 映像名列，unix 读 `/proc/<pid>/cmdline` 首个 token 的 basename。

    零依赖边界：拿不到映像名返回 False（宁可放行启动，也不误报「已有 serve 在跑」）
    ——存活与新鲜仍由另两层判据把守（`serve_alive` 三层全真才判活）。
    """
    want = os.path.basename(EXE).lower()
    if not want or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        row = _tasklist_row(pid)
        return bool(row) and row[0].lower() == want
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            first = f.read().split(b"\x00")[0]
    except OSError:
        return False
    return os.path.basename(first.decode("utf-8", "replace")).lower() == want


# 生效条件：heartbeat(jobs) 为假值、或其 ts 键缺省记 0 使 age ≥ FRESH_S*1000 毫秒时返回 False；否则以 hb.get("pid")（缺键为 None）同时满足 pid_alive 与 pid_is_self_program 才返回 True。
def serve_alive(jobs=None):
    """serve 存活三层判据：心跳新鲜 **且** pid 存活 **且** 该 pid 是本程序。

    三层缺一不可：只看新鲜度 → 崩溃后残留心跳冒充存活；只看 pid 号 → 无关进程
    复用的 pid 冒充 serve（v13 实测）。与 rust `serve_running` / `cmd_doctor`、
    MCP `_serve_alive` 同一口径（跨语言靠常量注释约定 + `hive/test_serve_entry.py` 守卫）。
    """
    hb = heartbeat(jobs)
    if not hb:
        return False
    if (time.time() * 1000 - hb.get("ts", 0)) >= FRESH_S * 1000:
        return False
    pid = hb.get("pid")
    return pid_alive(pid) and pid_is_self_program(pid)


# 生效条件：heartbeat() 为假值时返回 {ok:True, stopped:False, note:"serve 未在运行"}；心跳为真而 serve_alive() 为假时按 not pid_alive(pid) 分别给出"该 pid 已不存在"或"该 pid 不属于本程序"的陈旧心跳 note 并返回 stopped:False；两者皆真时按 os.name 用 taskkill /PID … /F（check=True）或 os.kill(pid, 15)，抛 CalledProcessError/OSError 返回 {ok:False, error:"停止失败 pid=…"}，否则最多轮询 30 次×0.5s serve_alive（未转假也照常退出循环）后一律返回 {ok:True, stopped:True, pid}。
def stop():
    hb = heartbeat()
    if not hb or not serve_alive():
        # 陈旧心跳要如实说明原因——否则「--stop 说没在跑 / 启动又被挡住」会成为
        # 两个同时失效的逃生口（v13 实测：守卫与 stop 判据不一致时正是如此）。
        if hb:
            pid = hb.get("pid")
            why = "该 pid 已不存在" if not pid_alive(pid) else "该 pid 不属于本程序"
            return {"ok": True, "stopped": False,
                    "note": f"serve 未在运行（存在陈旧心跳：pid={pid}，{why}）——可直接启动，无需 --stop"}
        return {"ok": True, "stopped": False, "note": "serve 未在运行"}
    pid = hb.get("pid")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=True)
        else:
            os.kill(pid, 15)
    except (subprocess.CalledProcessError, OSError) as e:
        return {"ok": False, "error": f"停止失败 pid={pid}: {e}"}
    # 等心跳过期确认真停了
    for _ in range(30):
        if not serve_alive():
            break
        time.sleep(0.5)
    return {"ok": True, "stopped": True, "pid": pid}


# 生效条件：serve_alive() 为真时返回 ok:False 的「已在运行（pid=hb.get('pid')）」；否则 load_config(config_path) 报错时原样返回该 error；配置通过则建 JOBS 目录、以合并环境 Popen([EXE, "serve", "--jobs", JOBS])，Popen 抛 OSError 返回「拉起失败」，否则最多 20 次 ×0.5s 轮询 serve_alive()，出现心跳即返回 ok:True（含 pid/workers/jobs_dir/env_keys/config=config_path），20 轮仍无则返回 SERVE_LOG 末尾 400 字符的「心跳未出现」。
def start(config_path):
    """拉起 serve（已在跑则拒绝）。返回 dict；调用方决定是否打印。"""
    if serve_alive():
        hb = heartbeat()
        return {"ok": False, "error": f"serve 已在运行（pid={hb.get('pid')}），先 --stop 再启动"}
    env, err = load_config(config_path)
    if err:
        return {"ok": False, "error": err}
    os.makedirs(JOBS, exist_ok=True)
    merged = {**os.environ, **env}
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    logf = open(SERVE_LOG, "ab")
    try:
        # close_fds=True 必须显式指定（含 Windows）：detached 的 serve 是长命进程，
        # 若关掉 close_fds 关闭语义，它会继承调用进程的可继承句柄——包括 IDE/终端
        # 用于捕获输出的管道。调用方随后读不到 EOF，表现为「命令跑着永不返回」
        # （2026-09-16 实测：后台脚本挂死 26 分钟，根因即此处）。
        # Python 3.7+ 在 Windows 上 close_fds=True 仍能正确传递显式 std 句柄。
        subprocess.Popen(
            [EXE, "serve", "--jobs", JOBS],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=merged, cwd=HIVE_DIR, creationflags=flags,
            start_new_session=(os.name != "nt"), close_fds=True)
    except OSError as e:
        logf.close()
        return {"ok": False, "error": f"拉起失败（先 cargo build --release？）: {e}"}
    for _ in range(20):  # 等首个心跳
        if serve_alive():
            hb = heartbeat()
            return {"ok": True, "pid": hb.get("pid"), "workers": hb.get("workers"),
                    "jobs_dir": JOBS,
                    "env_keys": sorted(env.keys()),
                    "config": config_path}
        time.sleep(0.5)
    tail = ""
    try:
        with open(SERVE_LOG, "r", encoding="utf-8", errors="replace") as f:
            tail = f.read()[-400:]
    except OSError:
        pass
    return {"ok": False, "error": f"serve 心跳未出现，日志尾部：{tail}"}


# 生效条件：config_path 给定；先调 stop()（serve 未在跑时其 stopped=False 且如实 note，不算失败），stop() 返回 ok 为假（taskkill/kill 失败）即返回 ok:False 的 stage=stop 错误并附 stop 段；否则调 start(config_path)，其结果 dict 原样返回并附 restart 段（stopped=本次是否真的停了旧实例 / old_pid / note=stop 的说明）。
def restart(config_path):
    """重启 serve：stop（如在跑）→ start。改 config.local.json 或换执行器后用它使改动生效。

    为什么存在：serve 级配置（env/执行器/worker 数）在启动时固化，改动必须重启
    serve 才生效；此前唯一的重启方式是「--stop 再手动启动」两步人肉——步骤断档时
    会出现「以为重启了、实际旧 serve 还带着旧配置在跑」。本函数把两步合成原子序：
    stop 失败（杀不掉）则**绝不 start**（防双实例抢队列）；stop 报「未在运行」
    （含陈旧心跳）不算失败，直接进入 start。
    """
    stop_res = stop()
    if not stop_res.get("ok"):
        return {"ok": False, "stage": "stop",
                "error": stop_res.get("error") or "stop 失败", "stop": stop_res}
    start_res = start(config_path)
    start_res["restart"] = {
        "stopped": stop_res.get("stopped", False),
        "old_pid": stop_res.get("pid"),
        "note": stop_res.get("note"),
    }
    return start_res


# 生效条件：无必需形参；HIVE_CARGO 指向存在的文件时返回该值，否则 ~/.cargo/bin/cargo(.exe) 存在时返回它，再否则 shutil.which("cargo") 的结果（可能为 None）。
def find_cargo():
    """定位 cargo：HIVE_CARGO env > ~/.cargo/bin > PATH。

    为什么不能只靠 PATH：serve 常由 detached/受限 env 的进程拉起，cargo 常不在
    PATH（2026-09-22 实测：宿主终端 `where cargo` 都找不到，cargo 只在
    ~/.cargo/bin）。找不到返回 None——调用方 fail-closed，不猜。
    """
    p = os.environ.get("HIVE_CARGO")
    if p and os.path.isfile(p):
        return p
    name = "cargo.exe" if os.name == "nt" else "cargo"
    home = os.path.join(os.path.expanduser("~"), ".cargo", "bin", name)
    if os.path.isfile(home):
        return home
    from shutil import which
    return which("cargo")


# 生效条件：config_path 给定；先调 stop()（ok 为假即返回 stage=stop 错误），随后 find_cargo() 为 None 时返回 stage=build 错误（serve 保持停止态），cargo build --release（cwd=HIVE_DIR）返回码非 0 时返回 stage=build 错误并附 stderr/stderr 尾 800 字符（serve 保持停止态），成功则调 start(config_path) 并在结果 dict 附 rebuild 段（stopped/old_pid/cargo）。
def rebuild(config_path):
    """重编译并重启：stop → cargo build --release → start。rust 改动一条命令生效。

    为什么 --restart 不够（2026-09-22 实测缺陷）：Windows 锁定运行中的可执行文件，
    serve 在跑时 `cargo build --release` 报 os error 5（拒绝访问）写不进 hive.exe；
    --restart 的 stop→start 中间插不进 build，等于「重启了个旧二进制」还以为改动了
    生效。本函数把三步合成原子序，且 **build 失败保持停止态**（fail-closed：宁可
    serve 停着，也不让旧二进制假活）——错误信息注明用 --restart 恢复。
    """
    stop_res = stop()
    if not stop_res.get("ok"):
        return {"ok": False, "stage": "stop",
                "error": stop_res.get("error") or "stop 失败", "stop": stop_res}
    cargo = find_cargo()
    if not cargo:
        return {"ok": False, "stage": "build",
                "error": ("未找到 cargo（设 HIVE_CARGO 指向 cargo.exe，或安装 Rust 工具链）"
                          "——serve 已停；修复后用 --restart 或 --rebuild 拉起"),
                "stop": stop_res}
    try:
        r = subprocess.run([cargo, "build", "--release"], cwd=HIVE_DIR,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "stage": "build",
                "error": f"cargo 启动失败（serve 已停）：{e}", "stop": stop_res}
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or ""))[-800:]
        return {"ok": False, "stage": "build",
                "error": f"cargo build --release 失败（serve 已停；修复后 --restart 拉起）：\n{tail}",
                "stop": stop_res}
    start_res = start(config_path)
    start_res["rebuild"] = {"stopped": stop_res.get("stopped", False),
                            "old_pid": stop_res.get("pid"), "cargo": cargo}
    return start_res


# 生效条件：始终返回 {ok:True, alive, heartbeat, jobs_dir:JOBS}；hb 为真而 serve_alive() 为假时额外附 stale_heartbeat（pid、pid_alive(pid)、pid_is_self_program(pid)、以及按 hb.get("ts", 0) 缺失记 0 算出的 age_s）；alive 为真且 JOBS 路径存在时额外遍历其中各子目录的 status.json，把 json.load(f).get("state", "?")（缺 state 键记 "?"，抛 OSError/ValueError 的条目跳过）按值计数写入 job_states。
def status():
    hb = heartbeat()
    alive = serve_alive()
    info = {"ok": True, "alive": alive, "heartbeat": hb, "jobs_dir": JOBS}
    if hb and not alive:
        # 判死时给出三层判据明细——运维一眼看出是「心跳过期」还是「pid 假存活」，
        # 而不是只拿到一个 false 去猜。
        pid = hb.get("pid")
        info["stale_heartbeat"] = {
            "pid": pid,
            "pid_alive": pid_alive(pid),
            "pid_is_self_program": pid_is_self_program(pid),
            "age_s": round((time.time() * 1000 - hb.get("ts", 0)) / 1000.0, 1),
        }
    if alive and os.path.exists(JOBS):
        states = {}
        for jid in os.listdir(JOBS):
            sp = os.path.join(JOBS, jid, "status.json")
            if not os.path.isfile(sp):
                continue
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    st = json.load(f).get("state", "?")
                states[st] = states.get(st, 0) + 1
            except (OSError, ValueError):
                pass
        info["job_states"] = states
    return info


# 生效条件：参数取自 sys.argv[1:]（"--config" 存在时取其紧随的一项作为 cfg，缺该项会在 args[i+1] 抛未捕获的 IndexError，否则用模块常量 DEFAULT_CONFIG）；处理后 args 仍含 "--stop" 时返回 emit(stop())，否则含 "--status" 时返回 emit(status())，两者都不含时返回 emit(start(cfg))。
def main():
    args = sys.argv[1:]
    cfg = DEFAULT_CONFIG
    if "--config" in args:
        i = args.index("--config")
        cfg = args[i + 1]
        args = args[:i] + args[i + 2:]
    if "--rebuild" in args:
        return emit(rebuild(cfg))
    if "--restart" in args:
        return emit(restart(cfg))
    if "--stop" in args:
        return emit(stop())
    if "--status" in args:
        return emit(status())
    return emit(start(cfg))


if __name__ == "__main__":
    sys.exit(main())