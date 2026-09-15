#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hive serve 启动器：读本地配置文件注入 env，detached 拉起/停止/查看 serve。

用法（Windows 实测形态，Python 3 标准库零第三方依赖）：
    python hive/serve_start.py            # 拉起 serve（已在跑则拒绝，防双实例）
    python hive/serve_start.py --stop     # 停止 serve（读心跳 pid）
    python hive/serve_start.py --status   # 查看心跳与任务统计

配置文件（默认与脚本同目录 config.local.json，--config 可指他处）：
    JSON 对象，键=环境变量名，值支持三形态：
      "字符串"                  直值
      {"env": "DEEPSEEK_API_KEY"}   读系统环境变量（key 明文不落盘）
      {"file": "E:/个人数据/智谱api.txt"}  读文本文件全部内容并 strip（key 放个人数据目录）
    解析失败的键 fail fast 拒绝拉起，防止残缺 env 的 serve 上岗。
"""
import json
import os
import subprocess
import sys
import time

HIVE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HIVE_DIR, "config.local.json")
EXE = os.path.join(HIVE_DIR, "target", "release", "hive.exe")
JOBS = os.path.join(HIVE_DIR, "jobs")
SERVE_LOG = os.path.join(JOBS, "_serve.log")
HEARTBEAT = os.path.join(JOBS, "_serve.json")
FRESH_S = 15  # 心跳新鲜窗口（serve 每拍 <1s 刷）


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    return 0 if obj.get("ok") else 1


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


def heartbeat():
    try:
        with open(HEARTBEAT, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def serve_alive():
    hb = heartbeat()
    return bool(hb and (time.time() * 1000 - hb.get("ts", 0)) < FRESH_S * 1000)


def stop():
    hb = heartbeat()
    if not hb or not serve_alive():
        return out({"ok": True, "stopped": False, "note": "serve 未在运行"})
    pid = hb.get("pid")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, check=True)
        else:
            os.kill(pid, 15)
    except (subprocess.CalledProcessError, OSError) as e:
        return out({"ok": False, "error": f"停止失败 pid={pid}: {e}"})
    # 等心跳过期确认真停了
    for _ in range(30):
        if not serve_alive():
            break
        time.sleep(0.5)
    return out({"ok": True, "stopped": True, "pid": pid})


def start(config_path):
    if serve_alive():
        hb = heartbeat()
        return out({"ok": False, "error": f"serve 已在运行（pid={hb.get('pid')}），先 --stop 再启动"})
    env, err = load_config(config_path)
    if err:
        return out({"ok": False, "error": err})
    os.makedirs(JOBS, exist_ok=True)
    merged = {**os.environ, **env}
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    logf = open(SERVE_LOG, "ab")
    try:
        subprocess.Popen(
            [EXE, "serve", "--jobs", JOBS],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=merged, cwd=HIVE_DIR, creationflags=flags,
            start_new_session=(os.name != "nt"), close_fds=(os.name != "nt"))
    except OSError as e:
        logf.close()
        return out({"ok": False, "error": f"拉起失败（先 cargo build --release？）: {e}"})
    for _ in range(20):  # 等首个心跳
        if serve_alive():
            hb = heartbeat()
            return out({"ok": True, "pid": hb.get("pid"), "workers": hb.get("workers"),
                        "jobs_dir": JOBS,
                        "env_keys": sorted(env.keys()),
                        "config": config_path})
        time.sleep(0.5)
    tail = ""
    try:
        with open(SERVE_LOG, "r", encoding="utf-8", errors="replace") as f:
            tail = f.read()[-400:]
    except OSError:
        pass
    return out({"ok": False, "error": f"serve 心跳未出现，日志尾部：{tail}"})


def status():
    hb = heartbeat()
    alive = serve_alive()
    info = {"ok": True, "alive": alive, "heartbeat": hb, "jobs_dir": JOBS}
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
    return out(info)


def main():
    args = sys.argv[1:]
    cfg = DEFAULT_CONFIG
    if "--config" in args:
        i = args.index("--config")
        cfg = args[i + 1]
        args = args[:i] + args[i + 2:]
    if "--stop" in args:
        return stop()
    if "--status" in args:
        return status()
    return start(cfg)


if __name__ == "__main__":
    sys.exit(main())
