# -*- coding: utf-8 -*-
"""故障注入 harness · 公共层（九源 × 七类故障 · runtime 面）。

理论判据：docs/theory/不可靠定理与失效优先框架_v0.3.md（T0-T14 / A1-A4 / D1-D6）
        + docs/不可靠性理论_v0.1.md（九源分类学 S1-S9 / 防线原语 P1-P12）。

工程纪律（对齐实验员守则）：
  * 一切注入只在系统临时目录（tempfile.mkdtemp 前缀 chaos_fi_）+ 哑数据上进行，
    绝不触真实 serve / 真实令牌库 / 真实数据目录；case 结束 finally 清理。
  * 四可判据（D4）：可发现 detectable / 可隔离 isolatable / 可恢复 recoverable /
    可追溯 traceable——每个 case 模块按实测逐项给证据。
  * verdict 三态：pass=防线按预期拦截；gap=防线缺口（须在 registry 登记
    EXPECTED_GAP）；untestable=无法注入（如实报告，不伪造）。
  * 退出码语义由 run_all.py 裁：全部用例观测状态与 registry 登记一致=0；
    未登记的新 gap 或 pass 用例回归=1。

运行方式（test/ 非 python 包——`import test` 会命中 stdlib test 包，实测
Python 3.12 下 `python -c "import test"` 解析到
Lib\\test\\__init__.py，故本目录测试与 scripts/test_*.py 同约定：直跑）：
    python test/chaos_injection/test_fi_r01_clock_rollback.py   # 单 case
    python test/chaos_injection/run_all.py                      # 全量 + 退出码裁决
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# 本目录入 sys.path：case 模块以 `import harness` 复用（直跑形态无包语义）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

HIVE_EXE = os.path.join(_REPO, "hive", "target",
                        "release", "hive.exe" if os.name == "nt" else "hive")
EXEC_CMD_PY = os.path.join(_REPO, "hive", "exec_cmd.py")


class Case:
    """单 case 断言收集器：check 记 OK/FAIL，verdict 由 case 模块按语义判定。"""

    def __init__(self, case_id: str, title: str):
        self.case_id = case_id
        self.title = title
        self.fails: list[str] = []
        self.notes: list[str] = []
        self._tmpdirs: list[str] = []
        self._procs: list = []
        self.evidence: list[str] = []

    # ---- 断言 ----
    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        tag = "OK  " if cond else "FAIL"
        print(f"  {tag} {name}" + (f"  [{detail}]" if detail and not cond else ""))
        if not cond:
            self.fails.append(f"{name}: {detail}")
        else:
            self.evidence.append(f"{name} :: {detail}" if detail else name)
        return cond

    def note(self, msg: str) -> None:
        """观测记录（不计成败）：矛盾态现场 / 基线记录等。"""
        print(f"  NOTE {msg}")
        self.notes.append(msg)

    # ---- 资源管理 ----
    def tmpdir(self, tag: str) -> str:
        d = tempfile.mkdtemp(prefix=f"chaos_fi_{tag}_")
        self._tmpdirs.append(d)
        return d

    def track_proc(self, p) -> None:
        self._procs.append(p)

    def cleanup(self) -> None:
        for p in self._procs:
            try:
                if p.poll() is None:
                    if os.name == "nt":
                        # encoding/errors 显式给定：taskkill 输出是 GBK（控制台
                        # 代码页），PYTHONUTF8=1 下 text=True 默认 strict utf-8
                        # 会打崩 reader 线程（UnicodeDecodeError 实测）；只消费
                        # 退出码，字节替换解码即可。
                        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                       capture_output=True, text=True,
                                       encoding="utf-8", errors="replace")
                    else:
                        p.kill()
            except OSError:
                pass
            finally:
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass
        for d in reversed(self._tmpdirs):
            shutil.rmtree(d, ignore_errors=True)

    # ---- 收尾 ----
    def finish(self, verdict: str, expected: str) -> int:
        """打印机器可读结论行（run_all.py 解析）并返回本 case 退出码。

        退出码口径：观测与登记一致（pass==pass / gap==gap）→ 0；
        不一致（回归或缺口消失）→ 1（run_all 汇总裁 1）。
        """
        ok = (self.fails == [])
        self.check("★verdict 判定成立", ok, "; ".join(self.fails)[:400])
        consistent = (verdict == expected)
        print(f"CASE_RESULT {json.dumps({
            'case_id': self.case_id, 'verdict': verdict, 'expected': expected,
            'consistent': consistent, 'fails': self.fails, 'notes': self.notes,
        }, ensure_ascii=False)}")
        return 0 if consistent else 1


# ---------------------------------------------------------------- hive 辅助

def read_status(job_dir: str):
    with open(os.path.join(job_dir, "status.json"), encoding="utf-8") as f:
        return json.load(f)


def wait_state(job_dir: str, want, timeout_s: float, poll_s: float = 0.2):
    """轮询 status.json 直到 state ∈ want，返回 (最终state, status dict)；超时返回当前态。"""
    if isinstance(want, str):
        want = {want}
    t0 = time.time()
    st = {}
    while time.time() - t0 < timeout_s:
        try:
            st = read_status(job_dir)
            if st.get("state") in want:
                return st.get("state"), st
        except (OSError, ValueError):
            pass
        time.sleep(poll_s)
    try:
        st = read_status(job_dir)
    except (OSError, ValueError):
        pass
    return st.get("state"), st


def write_spec(path: str, spec: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)


def hive_submit(jobs_dir: str, spec: dict):
    """经真实 hive.exe submit 提交（fail-fast 面）。返回 (rc, stdout)。
    spec 临时目录用完即清（不留残渣）。"""
    spec_dir = tempfile.mkdtemp(prefix="chaos_fi_spec_")
    try:
        spec_path = os.path.join(spec_dir, "spec.json")
        write_spec(spec_path, spec)
        r = subprocess.run([HIVE_EXE, "submit", "--spec", spec_path,
                            "--jobs", jobs_dir],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30, cwd=_REPO)
        return r.returncode, r.stdout + r.stderr
    finally:
        shutil.rmtree(spec_dir, ignore_errors=True)


def hive_spawn_serve(jobs_dir: str, workers: int = 1, force: bool = False):
    """拉起真实 serve（--jobs 指临时池；env HIVE_EXEC_PY=exec_cmd.py）。"""
    env = {**os.environ, "HIVE_EXEC_PY": EXEC_CMD_PY, "PYTHONUTF8": "1"}
    args = [HIVE_EXE, "serve", "--jobs", jobs_dir, "--workers", str(workers)]
    if force:
        args.append("--force")
    logf = open(os.path.join(jobs_dir, "_chaos_serve.log"), "ab")
    p = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=env, cwd=_REPO)
    logf.close()  # 句柄归子进程；父侧不留
    return p


def hive_poll(jobs_dir: str, job_id: str = ""):
    args = [HIVE_EXE, "poll"]
    if job_id:
        args.append(job_id)
    args += ["--jobs", jobs_dir]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=30, cwd=_REPO)
    return r.returncode, r.stdout


# ---------------------------------------------------------------- WAL 辅助

def wal_sign(secret: str, seq: int, ts: int, frm: str, to: str,
             etype: str, round_no: int, payload_text: str) -> str:
    """v0.7.1 签名串 seq|type|from|to|round|ts|payload（与
    swarm/rust_runtime/src/swarm.rs:376-386 sign_event、
    swarm/rust_swarm.py:126-131 verify_wal_signatures 约定一致）。"""
    msg = "%s|%s|%s|%s|%s|%s|%s" % (seq, etype, frm, to, round_no, ts,
                                    payload_text)
    return _hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def wal_line(secret: str, seq: int, ts: int, frm: str, to: str, etype: str,
             round_no: int, payload_obj) -> str:
    """按 Rust 写序构造整行（swarm.rs:1107 格式串：
    {"seq":..,"ts":..,"from":..,"to":..,"type":..,"round":..,"level":..,
     "hmac":..,"payload":<内嵌原文>}）。payload 文本用紧凑分隔符（与
    serde_json_like 序列化形态对齐），签名用同一文本保真。"""
    payload_text = json.dumps(payload_obj, separators=(",", ":"),
                              ensure_ascii=False)
    sig = wal_sign(secret, seq, ts, frm, to, etype, round_no, payload_text)
    return ('{"seq":%d,"ts":%d,"from":"%s","to":"%s","type":"%s",'
            '"round":%d,"level":0,"hmac":"%s","payload":%s}\n'
            % (seq, ts, frm, to, etype, round_no, sig, payload_text))


def make_wal_fixture(path: str, secret: str) -> list[str]:
    """3 条合法签名事件行（queen→w1 任务 / w1→queen 报告 / queen→w2 任务）。"""
    now = int(time.time() * 1000)
    lines = [
        wal_line(secret, 1, now - 20, "queen", "w1", "任务", 1,
                 {"task": "demo-a"}),
        wal_line(secret, 2, now - 10, "w1", "queen", "报告", 1,
                 {"msg": "hello"}),
        wal_line(secret, 3, now, "queen", "w2", "任务", 1,
                 {"task": "demo-b"}),
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    return lines


# ---------------------------------------------------------------- 源码断言

def src(rel: str) -> str:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()
