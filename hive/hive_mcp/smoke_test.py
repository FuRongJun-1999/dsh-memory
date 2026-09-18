# -*- coding: utf-8 -*-
"""hive MCP 面 + 端到端冒烟（纪律 15 形态：python subprocess，UTF-8）。

覆盖：
  1. MCP 协议面：initialize / tools/list / doctor
  2. spawn 结构：非法 spec 拒绝 / 合法 spec 产出 job 目录与 status
  3. 端到端（假执行器注入）：spawn → serve 自动拉起 → poll 到 done
  4. kill 通道：running 后写 kill 标志 → killed 终态

注意：执行器是 serve 级配置（HIVE_EXEC_PY），故全程用统一 env 的单一
Mcp 实例，首次 spawn 拉起的 serve 即带假执行器。假执行器与临时 jobs 目录经
**测试专用 config**（`HIVE_CONFIG`）注入——serve env 的权威来源是 config
（`{**os.environ, **cfg}`），靠宿主 env 覆盖既不符合部署语义、也会被 config 里的
真执行器压过（2026-09-16 实测：smoke 误走真 API）。

用法：python hive/hive_mcp/smoke_test.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=REPO)
EXE = os.path.join(REPO, "hive", "target", "release",
                   "hive.exe" if os.name == "nt" else "hive")

from hive.hive_mcp import mcp_server as HM  # noqa: E402 —— REPO 须先入 sys.path

PASS = 0
FAIL = 0


# 生效条件：cond 为真时 PASS 自增并打印 `  [PASS] {name}`（两个前导空格），cond 为假时 FAIL 自增并打印 `  [FAIL] {name}  {detail}`（两前导空格，detail 默认空串）。
def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# 生效条件：env_extra 为真值（非空 dict）时在 dict(ENV) 副本上 env.update(env_extra) 再以该 env 启动 mcp_server 子进程，env_extra 为 None 或空 dict 时只用 dict(ENV) 启动。
class Mcp:
    """stdio JSON-RPC 客户端（子进程形态，逐行协议）。"""

# 生效条件：env_extra 为真值（非空 dict）时在 dict(ENV) 副本上 env.update(env_extra) 后传给 subprocess.Popen 的 env，env_extra 为 None 或空 dict 时仅用 dict(ENV)。
    def __init__(self, env_extra: dict | None = None):
        env = dict(ENV)
        if env_extra:
            env.update(env_extra)
        self.p = subprocess.Popen(
            [sys.executable, "-m", "hive.hive_mcp.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, shell=False,
            cwd=REPO, text=True, encoding="utf-8",
        )

# 生效条件：params 不为 None 时请求体写入 req["params"]（为 None 时省略该键），写入 stdin 并 flush 后循环读 stdout，读到空串（EOF，not line）抛 RuntimeError("server 输出关闭")，某行经 json.loads 解析后 resp.get("id") == rid 时返回该 resp。
    def call(self, method: str, params: dict | None = None, rid: int = 1) -> dict:
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        self.p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("server 输出关闭")
            resp = json.loads(line)
            if resp.get("id") == rid:
                return resp

# 生效条件：把 name 与 args 组装为 {"name": name, "arguments": args} 以 tools/call 和 rid（默认 1）发出，返回对 resp["result"]["content"][0]["text"] 的 json.loads 结果（result/content/[0]/text 均按直接下标取值，缺键或越界本片段不回落默认）。
    def tool(self, name: str, args: dict, rid: int = 1) -> dict:
        resp = self.call("tools/call",
                         {"name": name, "arguments": args}, rid)
        return json.loads(resp["result"]["content"][0]["text"])

# 生效条件：先执行 self.p.stdin.close() 与 self.p.wait(timeout=5)，此两步中任一抛出 Exception 时改调 self.p.kill()，未抛出则不 kill。
    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.p.kill()


FAKE_EXEC = r"""
import sys, json, time, os
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
time.sleep(float(spec.get("user_prompt") or 0))
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": "fake-ok-content", "usage": {"total_tokens": 7}}, f, ensure_ascii=False)
"""


# 生效条件：以 tries（默认 80）为轮数逐轮按 jid 调用 hive_poll 取 view，轮内 st 为 (view.get("job") or {}).get("state") 且 st in states 时返回 (True, view)，否则睡 0.1s 再试，耗尽 tries 轮后返回 (False, view)（tries<=0 时不轮询，view 仍为 {}）。
def wait_state(m: Mcp, jid: str, states: set, rid: int, tries: int = 80):
    view = {}
    for _ in range(tries):
        view = m.tool("hive_poll", {"job_id": jid}, rid)
        st = (view.get("job") or {}).get("state")
        if st in states:
            return True, view
        time.sleep(0.1)
    return False, view


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="hive_smoke_")
    fake_py = os.path.join(tmp, "fake_exec.py")
    with open(fake_py, "w", encoding="utf-8") as f:
        f.write(FAKE_EXEC)
    jobs_dir = os.path.join(tmp, "jobs")
    # 隔离形态：假执行器 + 临时 jobs 走测试专用 config（HIVE_CONFIG）；
    # HIVE_API_BASE 指向丢弃端口，任何误走真 API 的路径都会立刻失败而非静默出网。
    cfg_path = os.path.join(tmp, "config.smoke.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "_note": "smoke_test 专用：假执行器 + 丢弃端口，勿用于部署",
            "HIVE_EXEC_PY": fake_py,
            "HIVE_API_KEY": "fake-key",
            "HIVE_API_BASE": "http://127.0.0.1:9",
            "HIVE_WORKERS": "2",
        }, f, ensure_ascii=False)
    env_extra = {"HIVE_CONFIG": cfg_path, "HIVE_JOBS_DIR": jobs_dir}

    print("== 1. MCP 协议面 ==")
    m = Mcp(env_extra)
    resp = m.call("initialize", {"protocolVersion": "2024-11-05"})
    si = resp.get("result", {}).get("serverInfo", {})
    check("initialize 返回 serverInfo", si.get("name") == "hive-mcp")
    resp = m.call("tools/list", {}, rid=2)
    names = [t["name"] for t in resp["result"]["tools"]]
    check("tools/list 四工具",
          set(names) == {"hive_spawn", "hive_poll", "hive_kill", "hive_doctor"})
    d = m.tool("hive_doctor", {}, rid=3)
    d_env = d.get("serve_env_source") or {}
    check("doctor 返回 env 检查（权威列 serve_env_source）",
          d.get("ok") is True and d_env.get("api_key_set") is True
          and "mcp_process_env" in d and d_env.get("path") == cfg_path)

    print("== 2. spawn 结构校验 ==")
    bad = m.tool("hive_spawn", {"model": "x"}, rid=4)
    check("缺 user_prompt 被拒", bad.get("ok") is False)
    bad2 = m.tool("hive_spawn",
                  {"model": "x", "user_prompt": "y", "context_files": ["no_such.txt"]},
                  rid=5)
    check("context 不存在被拒", bad2.get("ok") is False)
    good = m.tool("hive_spawn",
                  {"model": "fake", "user_prompt": "0.3", "timeout_s": 60},
                  rid=6)
    check("合法 spawn 返回 job_id",
          good.get("ok") is True and (good.get("job_id") or "").startswith("h"))
    st_path = os.path.join(jobs_dir, good["job_id"], "status.json")
    check("job 目录 status 落盘", os.path.isfile(st_path))

    print("== 2b. spawn 入参白名单（面差异显式拒绝）==")
    for i, (key, val) in enumerate((("command", "echo hi"),
                                    ("commands", ["echo hi"]),
                                    ("orchestrate", True),
                                    ("workdir", "/tmp"))):
        r = m.tool("hive_spawn", {"model": "fake", "user_prompt": "0.1", key: val},
                   rid=20 + i)
        check(f"{key} 被显式拒绝（不再静默丢弃）",
              r.get("ok") is False and key in (r.get("error") or ""),
              json.dumps(r, ensure_ascii=False)[:200])
    inside = m.tool("hive_spawn",
                    {"model": "fake", "user_prompt": "0.1", "timeout_s": 60,
                     "system_prompt": "s", "context_strict": False,
                     "tools": ["lingshu_cg"], "max_tool_rounds": 2,
                     "mdcg_root": jobs_dir, "web_search_backend": "duckduckgo",
                     "temperature": 0.2, "max_tokens": 128,
                     "thinking": {"type": "enabled"}}, rid=30)
    check("白名单内参数零回归（合法 spawn 不受新校验影响）",
          inside.get("ok") is True, json.dumps(inside, ensure_ascii=False)[:200])
    props = set(HM.TOOLS[0]["inputSchema"]["properties"])
    check("schema properties 与 SPAWN_ALLOWED_KEYS 同集（防两处漂移）",
          props == set(HM.SPAWN_ALLOWED_KEYS),
          f"schema-only={sorted(props - set(HM.SPAWN_ALLOWED_KEYS))} "
          f"whitelist-only={sorted(set(HM.SPAWN_ALLOWED_KEYS) - props)}")

    if not os.path.isfile(EXE):
        print(f"== 3/4. 跳过（未找到 {EXE}，先 cargo build --release）==")
        m.close()
        return 1 if FAIL else 0

    print("== 3. 端到端：serve 自动拉起 → done ==")
    g = m.tool("hive_spawn",
               {"model": "fake", "user_prompt": "0.3", "timeout_s": 60}, rid=10)
    jid = g["job_id"]
    ok, view = wait_state(m, jid, {"done"}, 11)
    check("端到端 done", ok, json.dumps(view, ensure_ascii=False)[:300])
    res = (view.get("job") or {}).get("result") or {}
    check("result 内容回读",
          res.get("content") == "fake-ok-content"
          and res.get("usage", {}).get("total_tokens") == 7)
    d2 = m.tool("hive_doctor", {}, rid=12)
    check("doctor serve_alive", d2.get("serve_alive") is True)
    dpoll = m.tool("hive_poll", {}, rid=17)
    check("poll 列表含摘要", dpoll.get("ok") is True
          and isinstance(dpoll.get("jobs"), list))

    print("== 4. kill 通道 ==")
    g2 = m.tool("hive_spawn",
                {"model": "fake", "user_prompt": "30", "timeout_s": 3600}, rid=13)
    jid2 = g2["job_id"]
    ran, _ = wait_state(m, jid2, {"running"}, 14, tries=50)
    k = m.tool("hive_kill", {"job_id": jid2}, rid=15)
    check("kill 写标志成功", k.get("ok") is True)
    killed, _ = wait_state(m, jid2, {"killed"}, 16, tries=100)
    check("任务达 killed 终态", killed and ran)
    m.close()

    print(f"\n结果: {PASS} pass / {FAIL} fail")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
