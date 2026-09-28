"""serve 配置展示面守卫（C5，批次69）：掩码单点 / 角色与到达面 / 启动前置校验。

背景（本批契约 C1-C6）：密钥面在批次69 被划成**三角色**——
  模型（网关）密钥 `HIVE_API_KEY`：普通配置，随 serve env **默认继承给执行器**；
  身份锚 / 身份令牌 `HIVE_ORCH_TOKEN(_FILE)`：**不进执行器**（serve 派发时剥离，
  唯一例外是 `spec.orchestrate` 真值任务条件重注，见 hive/src/exec.rs 的
  ORCH_SECRET_ENV_KEYS）；
  子代理覆盖 `HIVE_SUBAGENT_API_KEY(_BASE)`：可选，只切换子任务凭据。
角色划清后暴露出两个**没有守卫**的失效面，本文件即为其机械断言：

1. **展示面泄密 / 无展示面**：运维要回答「这个键的值从哪来、执行器拿不拿得到、
   缺哪一环会让 LLM 任务全灭」此前只能靠人读 README + 猜；而任何一处自己拼
   「掩码」字符串就等于把明文送进终端/日志/JSON-RPC 通道。故掩码收敛为**单点
   函数** `mask_secret`，本文件用哑值反查「输出里不含明文子串」。
2. **残缺 serve 静默上岗**：serve 的 env 在启动时固化、子进程无法反查；少了模型
   密钥时旧行为是照样拉起，然后该池**每个** LLM 任务在任务级 result.json 里报
   「HIVE_API_KEY 未设置」——症状是「任务全失败」而不是「配置缺一键」。故
   `start()` 加启动前置校验（缺模型密钥且未声明 `HIVE_LLM_DISABLED` 真值 → 拒绝），
   本文件正面覆盖「拒绝 + 可诊断」与「声明后放行 + 回带提示」两侧。

实验纪律：全程**哑值 + 系统临时目录**，不触真实令牌库 / 在役数据目录 / 真 serve；
`start()` 一律在假 Popen / 假 serve_alive 下调用（绝不真进程、绝无网络）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS: list[str] = []

# 哑值（**非真凭据**，与任何真实令牌库无关）。刻意只用大写字母、且与键名/环境变量名
# 无共同 3 字窗——反查明文的断言因此没有假阳性：
#   * hashlib 的 hexdigest 是小写十六进制 → 大写哑值的任意窗都不可能出现在指纹里；
#   * 若哑值里嵌了 MODEL/KEY/WEB/SEARCH 这类词，键名本身（HIVE_API_KEY…）就会「命中」——
#     那是**键名**而非泄漏，故哑值取与键名无关的字母串。
MODEL_DUMMY = "ZKQXJVBWMPLRTNFHGDWY"
TOKEN_DUMMY = "QVBNZKXRTLMHWGDSJCPF"
WEB_DUMMY = "JWZQXNVBRTLKHGDSMPFC"
SRC_ENV_NAME = "C5_MODEL_SRC"      # config 里 {"env": ...} 引用的名字（非秘密，可出现在 source）
SHORT_DUMMY = "ABCD"               # len<=4：掩码必须**不取前缀**（否则掩码即明文）


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def _read(rel: str) -> str:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


@contextmanager
def _env_without_hive(extra: dict | None = None):
    """临时清空进程 env 里的 HIVE_* 键（守卫自身跑在被污染 env 下也不得假绿）。"""
    saved = {k: v for k, v in os.environ.items() if k.startswith("HIVE_")}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(extra or {})
    try:
        yield
    finally:
        for k in extra or {}:
            os.environ.pop(k, None)
        os.environ.update(saved)


def _no_plaintext_windows(secret: str, text: str) -> str:
    """返回 secret 在 text 中出现的明文片段（空串 = 干净）。判据 = 全部 ≥3 字窗 + 全值。"""
    hits = []
    if secret and secret in text:
        hits.append(secret)
    for i in range(len(secret) - 2):
        w = secret[i:i + 3]
        if w in text:
            hits.append(w)
    return ",".join(sorted(set(hits)))


def main() -> int:  # noqa: C901
    import hive.serve_start as serve_start
    ss_py = _read("hive/serve_start.py")

    print("① 掩码单点函数：前缀少量 + 长度 + sha256 前 8 位指纹（绝不输出完整值）")
    check("掩码实现单点（全文件仅一处 hexdigest）",
          ss_py.count("hexdigest()") == 1 and "import hashlib" in ss_py,
          f"hexdigest 出现 {ss_py.count('hexdigest()')} 次")
    check("展示面走单点函数（show_config 调 mask_secret）",
          "mask_secret(val)" in ss_py, "show_config 未接线 mask_secret")
    m = serve_start.mask_secret(MODEL_DUMMY)
    check("掩码含长度与指纹", f"len={len(MODEL_DUMMY)}" in m and "sha256:" in m, m)
    check("掩码不等于原值且只取 2 字前缀",
          m != MODEL_DUMMY and m.startswith(MODEL_DUMMY[:2])
          and MODEL_DUMMY[2] not in m.split("***")[0], m)
    check("短值（len<=4）不取前缀（否则掩码即明文）",
          serve_start.mask_secret(SHORT_DUMMY).startswith("***")
          and serve_start.mask_secret(SHORT_DUMMY) != SHORT_DUMMY,
          serve_start.mask_secret(SHORT_DUMMY))
    check("空值掩码为空串（单独标注由 empty 承担）",
          serve_start.mask_secret("") == "" and serve_start.mask_secret(None) == "")
    check("掩码确定性（同值同掩码，便于比对「改没改」）",
          serve_start.mask_secret(MODEL_DUMMY) == m)

    print("② 角色表与到达执行器判定（与 C1 剥离面同源）")
    check("模型密钥角色", serve_start.role_of("HIVE_API_KEY") == "模型密钥")
    check("身份令牌角色", serve_start.role_of("HIVE_ORCH_TOKEN") == "身份令牌")
    check("身份锚角色", serve_start.role_of("HIVE_ORCH_TOKEN_FILE") == "身份锚")
    check("子代理覆盖角色",
          serve_start.role_of("HIVE_SUBAGENT_API_KEY") == "子代理覆盖"
          and serve_start.role_of("HIVE_SUBAGENT_API_BASE") == "子代理覆盖")
    check("其余键角色为「其他」",
          serve_start.role_of("HIVE_API_BASE") == "其他"
          and serve_start.role_of("HIVE_JOBS_DIR") == "其他")
    check("身份两键**不到达**执行器（C1 剥离面）",
          serve_start.reaches_executor("HIVE_ORCH_TOKEN") is False
          and serve_start.reaches_executor("HIVE_ORCH_TOKEN_FILE") is False)
    check("模型密钥/子代理/base 到达执行器（N190 收窄后仅身份面剥离）",
          serve_start.reaches_executor("HIVE_API_KEY") is True
          and serve_start.reaches_executor("HIVE_SUBAGENT_API_KEY") is True
          and serve_start.reaches_executor("HIVE_API_BASE") is True)
    check("展示面的剥离面与 rust 常量同源（2 键、无 HIVE_API_KEY）",
          'const ORCH_SECRET_ENV_KEYS: [&str; 2] = ["HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE"]'
          in _read("hive/src/exec.rs"),
          "exec.rs 剥离面与展示面角色表分叉")

    tmp = tempfile.mkdtemp(prefix="hive_c5_")
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs, exist_ok=True)
    cfg_keyless = os.path.join(tmp, "cfg_keyless.json")
    with open(cfg_keyless, "w", encoding="utf-8") as f:
        json.dump({"HIVE_JOBS_DIR": jobs}, f)

    try:
        print("③ 启动前置校验：缺模型密钥 → ok:False 且 error 可诊断（且未拉起）")
        calls = {"popen": 0}

        def _fake_popen(cmd, **_kw):
            calls["popen"] += 1
            return None

        real_popen = serve_start.subprocess.Popen
        try:
            with _env_without_hive():
                r = serve_start.start(cfg_keyless)
                check("③a 缺模型密钥拒绝拉起（ok=False）", r.get("ok") is False, str(r)[:120])
                err = r.get("error") or ""
                check("③b error 点明缺的是哪个键（HIVE_API_KEY）", "HIVE_API_KEY" in err, err[:120])
                check("③c error 给出逃生键（HIVE_LLM_DISABLED）", "HIVE_LLM_DISABLED" in err, err[:120])
                check("③d error 自报是前置校验阶段", "启动前置校验" in err, err[:120])
                # 前置 = 拒绝发生在 Popen 之前（否则残缺 serve 已上岗，校验就成了马后炮）
                serve_start.subprocess.Popen = _fake_popen
                try:
                    r2 = serve_start.start(cfg_keyless)
                finally:
                    serve_start.subprocess.Popen = real_popen
                check("③e 前置：被拒时一次 Popen 都未发生",
                      r2.get("ok") is False and calls["popen"] == 0,
                      f"popen={calls['popen']} ret={str(r2)[:90]}")
                # config 里配了密钥（config 胜出进程 env）必须放行——否则「配了却判缺」是假红
                cfg_ok = os.path.join(tmp, "cfg_ok.json")
                with open(cfg_ok, "w", encoding="utf-8") as f:
                    json.dump({"HIVE_JOBS_DIR": jobs, "HIVE_API_KEY": MODEL_DUMMY}, f)
                with open(os.path.join(jobs, "_serve.json"), "w", encoding="utf-8") as f:
                    json.dump({"ts": time.time() * 1000, "pid": os.getpid(), "workers": 1}, f)
                alive = {"n": 0}
                real_alive = serve_start.serve_alive
                serve_start.serve_alive = lambda *_a, **_k: alive.__setitem__("n", alive["n"] + 1) or alive["n"] > 1
                serve_start.subprocess.Popen = _fake_popen
                alive["n"] = 0      # 首问「已在跑？」须为假，其后轮询判真（= 拉起来了）
                try:
                    r3 = serve_start.start(cfg_ok)
                finally:
                    serve_start.serve_alive = real_alive
                    serve_start.subprocess.Popen = real_popen
                check("③f config 里配了密钥即放行（合并环境口径，config 胜出 env）",
                      r3.get("ok") is True and calls["popen"] == 1,
                      str(r3)[:120])

                print("④ HIVE_LLM_DISABLED 真值 → 放行，并在结果里回带提示")
                for v, want in (("1", True), ("TRUE", True), ("yes", True),
                                ("0", False), ("false", False), ("no", False),
                                (" No ", False), ("", False), ("  ", False)):
                    got = serve_start.llm_disabled({"HIVE_LLM_DISABLED": v})
                    check(f"④a 真值判定 {v!r} → {want}", got is want, f"got={got}")
                calls["popen"] = 0
                alive["n"] = 0      # 同上：本轮的「已在跑？」须从假开始
                serve_start.serve_alive = lambda *_a, **_k: alive.__setitem__("n", alive["n"] + 1) or alive["n"] > 1
                serve_start.subprocess.Popen = _fake_popen
                try:
                    with _env_without_hive({"HIVE_LLM_DISABLED": "1"}):
                        r4 = serve_start.start(cfg_keyless)   # 无密钥 + 声明关闭
                    with _env_without_hive({"HIVE_LLM_DISABLED": "no"}):
                        r5 = serve_start.start(cfg_keyless)   # 假值 ≠ 声明 → 仍拒
                finally:
                    serve_start.serve_alive = real_alive
                    serve_start.subprocess.Popen = real_popen
                check("④b 声明 HIVE_LLM_DISABLED 后放行（ok=True）", r4.get("ok") is True, str(r4)[:120])
                check("④c 结果回带提示（llm_disabled + note 点名该键）",
                      r4.get("llm_disabled") is True and "HIVE_LLM_DISABLED" in (r4.get("note") or ""),
                      str(r4)[:160])
                check("④d 假值不算声明（'0'/'false'/'no'/空 一律不豁免，行为面亦如此）",
                      serve_start.llm_disabled({"HIVE_LLM_DISABLED": "no"}) is False
                      and r5.get("ok") is False and "启动前置校验" in (r5.get("error") or ""),
                      str(r5)[:140])
        finally:
            serve_start.subprocess.Popen = real_popen

        print("⑤ 只读展示面：--show-config 逐键来源/掩码/角色/到达面 + problems + 结论")
        tok_path = os.path.join(tmp, "orch.token")
        with open(tok_path, "w", encoding="utf-8") as f:
            f.write(TOKEN_DUMMY + "\n")
        cfg_show = os.path.join(tmp, "cfg_show.json")
        with open(cfg_show, "w", encoding="utf-8") as f:
            json.dump({
                "HIVE_API_KEY": {"env": SRC_ENV_NAME},           # 引用形态
                "HIVE_ORCH_TOKEN_FILE": {"file": tok_path},      # 文件形态
                "HIVE_WEB_SEARCH_KEY": WEB_DUMMY,                # 直值形态
                "HIVE_JOBS_DIR": jobs,
            }, f, ensure_ascii=False)
        scrubbed = {k: v for k, v in os.environ.items() if not k.startswith("HIVE_")}
        scrubbed[SRC_ENV_NAME] = MODEL_DUMMY
        p = subprocess.run([sys.executable, "-X", "utf8", os.path.join(_REPO, "hive", "serve_start.py"),
                            "--config", cfg_show, "--show-config"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=scrubbed)
        check("⑤a --show-config 退出码 0（配置可拉起）", p.returncode == 0, (p.stderr or "")[-200:])
        out = json.loads(p.stdout)
        check("⑤b 输出结构：ok/keys/problems/conclusion 齐备",
              all(k in out for k in ("ok", "keys", "problems", "conclusion")) and out["ok"] is True,
              str(out)[:160])
        by_key = {e["key"]: e for e in out["keys"]}
        check("⑤c 三来源形态逐键如实（env:名 / file:路径 / 直值）",
              by_key["HIVE_API_KEY"]["source"] == f"env:{SRC_ENV_NAME}"
              and by_key["HIVE_ORCH_TOKEN_FILE"]["source"] == f"file:{tok_path}"
              and by_key["HIVE_WEB_SEARCH_KEY"]["source"] == "直值",
              str([(k, v["source"]) for k, v in by_key.items()])[:200])
        check("⑤d 角色与到达面逐键正确",
              by_key["HIVE_API_KEY"]["role"] == "模型密钥"
              and by_key["HIVE_API_KEY"]["reaches_executor"] is True
              and by_key["HIVE_ORCH_TOKEN_FILE"]["role"] == "身份锚"
              and by_key["HIVE_ORCH_TOKEN_FILE"]["reaches_executor"] is False
              and "条件重注" in (by_key["HIVE_ORCH_TOKEN_FILE"].get("note") or ""),
              str(by_key["HIVE_ORCH_TOKEN_FILE"])[:200])
        check("⑤e 未设置的身份键也逐键列出（缺哪一环正是要回答的问题）",
              "HIVE_ORCH_TOKEN" in by_key and by_key["HIVE_ORCH_TOKEN"].get("empty") is True,
              str(by_key.get("HIVE_ORCH_TOKEN"))[:160])
        # 明文反查两层：①每个 masked 字段自身（最直接的出口）②整份 stdout（防别处漏印）
        leak_fields = {k: w for k, sec in (("HIVE_API_KEY", MODEL_DUMMY),
                                           ("HIVE_ORCH_TOKEN_FILE", TOKEN_DUMMY),
                                           ("HIVE_WEB_SEARCH_KEY", WEB_DUMMY))
                       for w in [_no_plaintext_windows(sec, by_key[k]["masked"])] if w}
        check("⑤f masked 字段不含任何明文子串（哑值反查：全值 + 全部 ≥3 字窗）",
              not leak_fields, str(leak_fields)[:200])
        leaked = {k: w for k, sec in (("model", MODEL_DUMMY), ("token", TOKEN_DUMMY),
                                      ("web", WEB_DUMMY))
                  for w in [_no_plaintext_windows(sec, p.stdout)] if w}
        check("⑤f2 整份输出不含任何明文子串（含 source/note/结论各处）",
              not leaked, str(leaked)[:200])
        check("⑤g 掩码值携带长度与指纹（能核对面）",
              "sha256:" in by_key["HIVE_API_KEY"]["masked"]
              and f"len={len(MODEL_DUMMY)}" in by_key["HIVE_API_KEY"]["masked"],
              by_key["HIVE_API_KEY"]["masked"])

        print("⑤h 缺密钥时 --show-config 仍照出诊断（只读面不拒答、不触发门槛）")
        p2 = subprocess.run([sys.executable, "-X", "utf8", os.path.join(_REPO, "hive", "serve_start.py"),
                             "--config", cfg_keyless, "--show-config"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=scrubbed)
        out2 = json.loads(p2.stdout)
        check("⑤i 缺密钥仍返回完整 JSON（keys/problems/结论不被拒）",
              isinstance(out2.get("keys"), list) and out2["keys"] and out2.get("problems"),
              str(out2)[:160])
        check("⑤j ok=False 且结论点名该配哪个键 / 该声明哪个键",
              out2["ok"] is False and "HIVE_API_KEY" in out2["conclusion"]
              and "HIVE_LLM_DISABLED" in out2["conclusion"], out2.get("conclusion", ""))
        check("⑤k problems 含缺模型密钥 + 身份面未配置两条提示",
              any("无可用模型密钥" in x for x in out2["problems"])
              and any("身份面未配置" in x for x in out2["problems"]),
              str(out2["problems"])[:200])

        print("⑤l CLI 默认（拉起）路径与库层共用同一道门槛")
        p3 = subprocess.run([sys.executable, "-X", "utf8", os.path.join(_REPO, "hive", "serve_start.py"),
                             "--config", cfg_keyless],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=scrubbed)
        out3 = json.loads(p3.stdout)
        check("⑤m CLI 拉起缺密钥配置 → ok=False + 前置校验文案（同一门槛、非第二套判据）",
              out3.get("ok") is False and "启动前置校验未通过" in (out3.get("error") or ""),
              str(out3)[:160])

        print("⑤n --status 附同一份配置摘要（复用 show_config，不复制判据）")
        p4 = subprocess.run([sys.executable, "-X", "utf8", os.path.join(_REPO, "hive", "serve_start.py"),
                             "--config", cfg_show, "--status"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=scrubbed)
        out4 = json.loads(p4.stdout)
        cs = out4.get("config_summary") or {}
        check("⑤o --status 带 config_summary 且与 --show-config 同源同值",
              cs.get("config") == cfg_show
              and {e["key"] for e in cs.get("keys", [])} == set(by_key)
              and cs.get("conclusion") == out["conclusion"],
              str(cs)[:200])
        check("⑤p --status 心跳/任务统计等既有字段未被摘要挤掉",
              "jobs_dir" in out4 and "heartbeat" in out4 and "alive" in out4,
              str(out4)[:160])

        print("⑥ 既有 start/stop/restart/rebuild 语义未被改动（test_serve_entry 口径）")
        check("⑥a CLI 生命周期接线逐条在位（--stop/--status 经 _lifecycle_jobs）",
              "stop(_lifecycle_jobs(cfg))" in ss_py
              and "status(_lifecycle_jobs(cfg))" in ss_py
              and 'if "--restart" in args:' in ss_py
              and 'if "--rebuild" in args:' in ss_py
              and "def restart(config_path)" in ss_py
              and "def rebuild(config_path)" in ss_py)
        check("⑥b restart 仍 stop→start 且 stop 失败绝不 start",
              "if not stop_res.get(\"ok\"):" in ss_py and "stage\": \"stop\"" in ss_py)
        check("⑥c 单实例守卫仍在前置校验之后（守住「已在跑」文案不变）",
              ss_py.index("_model_key_problem(merged)")
              < ss_py.index("serve 已在运行（pid="),
              "前置校验与单实例守卫顺序异常")
        empty_jobs = os.path.join(tmp, "empty_jobs")
        os.makedirs(empty_jobs, exist_ok=True)
        s = serve_start.stop(empty_jobs)
        check("⑥d stop 在无心跳池仍返回 ok=True/stopped=False（不误报失败）",
              s.get("ok") is True and s.get("stopped") is False, str(s)[:120])
        st = serve_start.status(empty_jobs)
        check("⑥e status(jobs) 仍以给定池为准（jobs_dir 如实透出）",
              st.get("jobs_dir") == empty_jobs and st.get("alive") is False, str(st)[:120])
        conf_ok = os.path.join(tmp, "cfg_conf.json")
        with open(conf_ok, "w", encoding="utf-8") as f:
            json.dump({"HIVE_JOBS_DIR": empty_jobs, "HIVE_API_KEY": MODEL_DUMMY}, f)
        seen = {}
        real_stop, real_start = serve_start.stop, serve_start.start
        serve_start.stop = lambda j=None: (seen.__setitem__("stop_jobs", j)
                                          or {"ok": True, "stopped": True, "pid": 4242})
        serve_start.start = lambda c: (seen.__setitem__("start_cfg", c) or {"ok": True, "pid": 1})
        try:
            rr = serve_start.restart(conf_ok)
        finally:
            serve_start.stop, serve_start.start = real_stop, real_start
        check("⑥f restart 仍 stop→start（目标池取自 config）并附 restart 段",
              seen.get("start_cfg") == conf_ok and seen.get("stop_jobs") == empty_jobs
              and rr.get("restart", {}).get("old_pid") == 4242,
              f"seen={seen} rr={str(rr)[:120]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print("ALL OK: serve 配置展示面与启动前置校验守卫全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
