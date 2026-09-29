# -*- coding: utf-8 -*-
"""H-4 止血守卫 · LLM 单发请求的**有界**退避重试（exec.py `_post_chat`）。

来源：设计者裁定的 H-4(c) 契约——`_post_chat` 加指数退避 + jitter，尊重
`Retry-After` 响应头；重试计数与最终结果进 result.json（**可观测**，不得静默
重试）；非可重试错误（4xx 语义类）不得重试。**只做止血**：模型端点故障转移、
job 级超时预算分配属设计级，本批不做。

缺陷（H-4c）：`_post_chat` 单发 urlopen，对 429/5xx **不重试**——网关一次瞬时
抖动（限流 / 网关 5xx / 连接瞬断）就把任务判死（顶层落 EXIT_API + ok=false）。

守的不变量：
  · 可重试面：429 / 408 / 425 / 5xx / 网络瞬时 → 退避重试；**有界**（次数与
    单次等待都封顶），超限原样抛最后一次错误（不吞错、不冒充成功）
  · 不可重试面：4xx 语义类（400/401/403/404/422…）与确定性错误（缺密钥
    RuntimeError、解析 ValueError）→ **一次即抛**，零重试开销
  · `Retry-After` 被尊重（数字秒与 HTTP-date）、且被 RETRY_AFTER_MAX 封顶
  · 可观测：有重试 → result.json 带 `llm_retries`（attempts / retries /
    last_outcome / events）；零重试 → **不带该键**（无故障路径产物逐位不变）
  · 接口面：`_post_chat` 签名仍是 `(body, timeout)`（既有定参桩 mock 面）

环境纪律：只装临时目录 + 哑值，HTTP 全程**桩驱动**（urlopen 被替换，零真实
网络，绝不触真实网关/凭据）；等待时间由 `_RETRY_SLEEP` 记录器吸收（不真睡）。
运行：
    python -X utf8 -m hive.test_h4_llm_retry                  # 正向
    python -X utf8 -m hive.test_h4_llm_retry --mutate         # 定点变异自证
    python -X utf8 -m hive.test_h4_llm_retry --mutate --list  # 只列变异表
退出码（fail-closed）：0 = 全绿；1 = 断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点漂移，本表就是判据，不得静默跳过）。

**基线纪律**：不以 git HEAD 为基线源——「修复前」形态一律由在当前工作区源码上
做**定点文本变异**得到（`_MUTATIONS`）。
"""
from __future__ import annotations

import importlib.util
import inspect
import io
import json
import os
import shutil
import sys
import tempfile
import types
import urllib.error
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_EXEC_PY = os.path.join(_HERE, "exec.py")

DUMMY_KEY = "DUMMY-H4-KEY-not-a-credential"
DUMMY_BASE = "http://h4.invalid/v1"
_TMP = tempfile.mkdtemp(prefix="h4retry_")
os.environ["HIVE_API_KEY"] = DUMMY_KEY
os.environ["HIVE_API_BASE"] = DUMMY_BASE
os.environ.pop("HIVE_SUBAGENT_API_KEY", None)
os.environ.pop("HIVE_SUBAGENT_API_BASE", None)
os.environ.pop("HIVE_RESULT_ANCHOR", None)      # 锚回写不参与本守卫

_BODY = {"model": "mock-model", "messages": [{"role": "user", "content": "q"}]}
_OK = {"choices": [{"message": {"content": "正常终答"}}],
       "usage": {"total_tokens": 1}, "model": "mock-model"}


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 被测模块的**可替换引用**：变异模式把它换成 exec 出来的变异副本，
# 断言一律经 `_ex()` 取模块（不闭包捕获原模块），否则变异对断言不可见。
E = {"ex": _load("hive_exec_h4", _EXEC_PY)}


def _ex():
    return E["ex"]


PASS, FAIL = 0, 0
_NOTES: list = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return True
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")
    return False


def note(text: str) -> None:
    _NOTES.append(text)
    print("  [NOTE] " + text)


class _Sleeper:
    """等待记录器：替换 _RETRY_SLEEP，免真睡且让「等了几次、各等多久」可断言。"""

    def __init__(self):
        self.waits: list = []

    def __call__(self, s):
        self.waits.append(round(float(s), 3))


class _Resp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, n=None):
        return self._raw if n is None else self._raw[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after=None):
    hdrs = {}
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://h4.invalid/v1/chat/completions",
                                  code, "boom", hdrs, io.BytesIO(b"detail"))


def _drive(script: list, sleeper: _Sleeper):
    """按 script 顺序喂 urlopen（元素为异常实例或 dict 响应），返回 (结果, 异常)。"""
    it = list(script)

    def _urlopen(req, timeout=None):        # noqa: ARG001 —— 桩签名对齐 urllib
        item = it.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)

    ex = _ex()
    ex.reset_llm_retry_state()
    ex._RETRY_SLEEP = sleeper
    try:
        with mock.patch.object(ex.urllib.request, "urlopen", side_effect=_urlopen):
            return ex._post_chat(dict(_BODY), 5), None
    except Exception as e:                  # noqa: BLE001 —— 本守卫断言的就是异常形态
        return None, e
    finally:
        del it


# ------------------------------------------------------------------ 断言组

def g0_interface():
    """接口面：签名仍是 (body, timeout)——既有定参桩 mock 面不得破。"""
    sig = inspect.signature(_ex()._post_chat)
    params = list(sig.parameters)
    check("G0 _post_chat 签名保持 (body, timeout)（add 参数即破桩调用面）",
          params == ["body", "timeout"], f"实测 {params}")


def g1_bounds():
    """常量面：次数与等待都**有界**，可重试状态集含「稍后再来」类。"""
    ex = _ex()
    check("G1a 尝试次数有界且 > 1（≥2 次才有「重试」语义，且不许无界）",
          2 <= int(ex.RETRY_MAX_ATTEMPTS) <= 10, f"={ex.RETRY_MAX_ATTEMPTS}")
    check("G1b 退避上限有限且 ≥ 基准",
          0 < float(ex.RETRY_BACKOFF_BASE) <= float(ex.RETRY_BACKOFF_MAX) <= 60,
          f"base={ex.RETRY_BACKOFF_BASE} max={ex.RETRY_BACKOFF_MAX}")
    check("G1c Retry-After 封顶有限（600s 照单全收=挂死 job）",
          0 < float(ex.RETRY_AFTER_MAX) <= 120, f"={ex.RETRY_AFTER_MAX}")
    check("G1d 可重试状态集含 429/408/425",
          {408, 425, 429} <= set(ex.RETRYABLE_HTTP_STATUS),
          f"={sorted(ex.RETRYABLE_HTTP_STATUS)}")
    check("G1e 5xx 判为可重试、4xx 语义类判为不可重试",
          ex._retryable_http(503) and ex._retryable_http(500)
          and not ex._retryable_http(400) and not ex._retryable_http(401)
          and not ex._retryable_http(404) and not ex._retryable_http(422),
          "503/500 应可重试；400/401/404/422 不应")


def g2_transient_429_recovered():
    """前 2 次 429（带 Retry-After）第 3 次成功 → 成功 + 计数 + 尊重 Retry-After。"""
    s = _Sleeper()
    data, err = _drive([_http_error(429, 2), _http_error(429, 2), dict(_OK)], s)
    check("G2a 瞬时 429 抖动不把任务判死（第 3 次成功返回）",
          err is None and data is not None and data.get("model") == "mock-model",
          f"err={err!r}")
    rep = _ex().llm_retry_report()
    check("G2b 尝试计数进账（attempts=3）",
          rep and rep["attempts"] == 3, json.dumps(rep, ensure_ascii=False))
    check("G2c 重试计数进账（retries=2）+ 最终结果 = recovered",
          rep and rep["retries"] == 2 and rep["last_outcome"] == "recovered",
          json.dumps(rep, ensure_ascii=False))
    check("G2d 尊重 Retry-After：两次等待都取头值的 2s（而非只按退避 0.25/0.5s）",
          s.waits == [2.0, 2.0], f"waits={s.waits}")
    check("G2e 账本事件逐条可读（status/retry_after_s/wait_s）",
          rep and len(rep["events"]) == 2
          and all(e["status"] == 429 and e["retry_after_s"] == 2.0
                  for e in rep["events"]),
          json.dumps(rep, ensure_ascii=False) if rep else "report=None")


def g3_non_retryable_no_retry():
    """非可重试（400 语义类）一次即抛、零重试、零记账（不静默重试）。"""
    s = _Sleeper()
    data, err = _drive([_http_error(400), dict(_OK)], s)
    check("G3a 400 一次即失败（不消耗后续机会）",
          data is None and isinstance(err, urllib.error.HTTPError)
          and err.code == 400, f"err={err!r}")
    check("G3b 非可重试错误零等待、零重试账",
          s.waits == [] and _ex().llm_retry_report() is None,
          f"waits={s.waits} report={_ex().llm_retry_report()}")
    check("G3c 尝试计数也只 1 次（未白烧配额）",
          _ex()._LLM_RETRY["attempts"] == 1, str(_ex()._LLM_RETRY["attempts"]))


def g4_5xx_and_jitter():
    """5xx 可重试；无 Retry-After 时等待落在退避区间（jitter 有界）。"""
    ex = _ex()
    s = _Sleeper()
    data, err = _drive([_http_error(503), dict(_OK)], s)
    check("G4a 503 可重试并在下次成功", err is None and data is not None, f"err={err!r}")
    lo = float(ex.RETRY_BACKOFF_BASE) / 2.0
    hi = min(float(ex.RETRY_BACKOFF_BASE), float(ex.RETRY_BACKOFF_MAX))
    check("G4b 无 Retry-After 时等待 = 基准的 [1/2, 1] 倍（指数退避 + jitter 有界）",
          len(s.waits) == 1 and lo - 1e-6 <= s.waits[0] <= hi + 1e-6,
          f"waits={s.waits} 期望区间 [{lo}, {hi}]")
    s2 = _Sleeper()
    _drive([_http_error(503), _http_error(502), dict(_OK)], s2)
    check("G4c 第二次退避翻倍（指数），且仍封顶",
          len(s2.waits) == 2 and s2.waits[1] > s2.waits[0]
          and s2.waits[1] <= float(ex.RETRY_BACKOFF_MAX) + 1e-6,
          f"waits={s2.waits}")


def g5_network_and_deterministic():
    """URLError（网络瞬断）可重试；缺密钥 RuntimeError 不可重试。"""
    ex = _ex()
    s = _Sleeper()
    data, err = _drive([urllib.error.URLError("connection reset"), dict(_OK)], s)
    check("G5a 网络层瞬时（URLError）可重试并恢复",
          err is None and data is not None, f"err={err!r}")
    s2 = _Sleeper()
    data2, err2 = _drive([TimeoutError("read timeout"), dict(_OK)], s2)
    check("G5b 读超时（TimeoutError）可重试并恢复",
          err2 is None and data2 is not None, f"err={err2!r}")
    # 缺密钥：确定性错误，一次即抛且**不进重试路径**
    saved = os.environ.pop("HIVE_API_KEY", None)
    try:
        s3 = _Sleeper()
        ex.reset_llm_retry_state()
        try:
            with mock.patch.object(ex.urllib.request, "urlopen",
                                   side_effect=lambda *a, **k: dict(_OK)):
                ex._post_chat(dict(_BODY), 5)
            got = None
        except Exception as e:              # noqa: BLE001
            got = e
        check("G5c 缺密钥（确定性 RuntimeError）一次即抛、零重试",
              isinstance(got, RuntimeError) and "HIVE_API_KEY" in str(got)
              and s3.waits == [] and ex.llm_retry_report() is None,
              f"err={got!r} waits={s3.waits}")
    finally:
        if saved is not None:
            os.environ["HIVE_API_KEY"] = saved


def g6_exhaustion_bounded():
    """一直失败：尝试次数有界、等待次数 = 尝试数 - 1、末次错误原样抛出。"""
    ex = _ex()
    s = _Sleeper()
    script = [_http_error(500) for _ in range(int(ex.RETRY_MAX_ATTEMPTS))]
    data, err = _drive(script, s)
    attempts = ex._LLM_RETRY["attempts"]
    check("G6a 用尽后仍如实失败（原样抛最后一次 HTTP 错误）",
          data is None and isinstance(err, urllib.error.HTTPError)
          and err.code == 500, f"err={err!r}")
    check("G6b 尝试次数有界：2 ≤ 次数 ≤ RETRY_MAX_ATTEMPTS（既非 1 次判死也无界）",
          2 <= attempts <= int(ex.RETRY_MAX_ATTEMPTS),
          f"attempts={attempts} max={ex.RETRY_MAX_ATTEMPTS}")
    check("G6c 等待仅发生在失败之间（次数 = 尝试 - 1），且单次封顶",
          len(s.waits) == attempts - 1
          and all(w <= float(ex.RETRY_AFTER_MAX) + 1e-6 for w in s.waits),
          f"waits={s.waits} attempts={attempts}")
    check("G6d 最终结果 = failed（进账，不静默）",
          ex.llm_retry_report()["last_outcome"] == "failed",
          json.dumps(ex.llm_retry_report(), ensure_ascii=False))


def _result_bytes(tag: str, payload: dict) -> bytes:
    d = tempfile.mkdtemp(prefix="h4retry_%s_" % tag, dir=_TMP)
    _ex().write_result(d, dict(payload))
    with open(os.path.join(d, "result.json"), "rb") as f:
        return f.read()


def g7_observable_in_result():
    """可观测：有重试 → result.json 带 llm_retries；零重试 → 不带该键。"""
    s = _Sleeper()
    data, err = _drive([_http_error(429, 1), dict(_OK)], s)
    raw = _result_bytes("retried", {"ok": True, "content": "x"})
    obj = json.loads(raw.decode("utf-8"))
    lr = obj.get("llm_retries")
    check("G7a 有重试时 result.json 带 llm_retries（重试不静默）",
          isinstance(lr, dict), raw.decode("utf-8")[:200])
    check("G7b 账本含 attempts/retries/last_outcome/events 四件",
          isinstance(lr, dict)
          and {"attempts", "retries", "last_outcome", "events"} <= set(lr)
          and lr["attempts"] == 2 and lr["retries"] == 1
          and lr["last_outcome"] == "recovered",
          json.dumps(lr, ensure_ascii=False) if lr else "None")
    check("G7c 失败终态同样带账（error 路径也走同一落盘口）",
          _result_has_retries_on_error(), "error 路径未见 llm_retries")
    # 零重试：成功路径产物**不含**该键
    _ex().reset_llm_retry_state()
    s2 = _Sleeper()
    _drive([dict(_OK)], s2)
    raw2 = _result_bytes("clean", {"ok": True, "content": "x"})
    check("G7d 零重试产物不含 llm_retries（无故障路径逐位不变）",
          "llm_retries" not in json.loads(raw2.decode("utf-8")),
          raw2.decode("utf-8")[:200])


def _result_has_retries_on_error() -> bool:
    s = _Sleeper()
    _drive([_http_error(503), _http_error(503), _http_error(503)], s)
    raw = _result_bytes("errpath", {"ok": False, "error": "API 失败"})
    return isinstance(json.loads(raw.decode("utf-8")).get("llm_retries"), dict)


def g8_oracle_no_fault_identical():
    """逐位不变（独立 oracle）：无故障成功路径与「重试面关掉」的产物逐字节相同。"""
    _ex().reset_llm_retry_state()
    s = _Sleeper()
    data_fixed, err = _drive([dict(_OK)], s)
    check("G8a 无故障路径：一次成功、零等待、零账",
          err is None and s.waits == [] and _ex().llm_retry_report() is None,
          f"err={err!r} waits={s.waits}")
    fixed_bytes = _result_bytes("oracle_fixed", {"ok": True, "content": "正常终答"})

    mut, src = _load_mutated(_MUT_ATTEMPTS_OLD, _MUT_ATTEMPTS_NEW)
    if mut is None:
        check("G8b 变异副本可加载（锚点在位）", False, "ANCHOR-MISS")
        return
    live = E["ex"]
    E["ex"] = mut
    try:
        mut.reset_llm_retry_state()
        s2 = _Sleeper()
        data_mut, err2 = _drive([dict(_OK)], s2)
        mut_bytes = _result_bytes("oracle_mut", {"ok": True, "content": "正常终答"})
    finally:
        E["ex"] = live
    check("G8b 无故障路径：返回值与「重试面关掉」的实现逐位相同",
          err == err2 and json.dumps(data_fixed, sort_keys=True)
          == json.dumps(data_mut, sort_keys=True),
          f"{data_fixed!r} != {data_mut!r}")
    check("G8c 无故障路径：result.json 逐字节相同（不含任何新增键）",
          fixed_bytes == mut_bytes,
          f"{fixed_bytes[:160]!r} != {mut_bytes[:160]!r}")
    check("G8d 源基线：两实现仅在重试常量上不同（本 oracle 的对照依据）",
          src is not None, "")


# ------------------------------------------------------------------ 定点变异

_MUT_ATTEMPTS_OLD = "RETRY_MAX_ATTEMPTS = 3"
_MUT_ATTEMPTS_NEW = "RETRY_MAX_ATTEMPTS = 1          # MUT：回缺陷（一次即判死）"
_MUT_HTTP_OLD = ("    return code in RETRYABLE_HTTP_STATUS or 500 <= code <= 599\n")
_MUT_HTTP_NEW = "    return False  # MUT：回缺陷（状态码不重试）\n"
_MUT_NET_OLD = ("    if isinstance(e, urllib.error.URLError):\n        return True\n")
_MUT_NET_NEW = "    if isinstance(e, urllib.error.URLError):\n        return False  # MUT\n"
_MUT_RA_OLD = "    ra = _parse_retry_after(headers)\n"
_MUT_RA_NEW = "    ra = None  # MUT：不尊重 Retry-After\n"

_MUTATIONS = (
    ("H-4c-1 回缺陷：RETRY_MAX_ATTEMPTS=1（一次即判死）",
     _MUT_ATTEMPTS_OLD, _MUT_ATTEMPTS_NEW),
    ("H-4c-2 回缺陷：HTTP 状态一律不可重试（429/5xx 全丢）",
     _MUT_HTTP_OLD, _MUT_HTTP_NEW),
    ("H-4c-3 回缺陷：网络瞬时异常不可重试（URLError 全丢）",
     _MUT_NET_OLD, _MUT_NET_NEW),
    ("H-4c-4 回缺陷：不尊重 Retry-After（只顾自家退避）",
     _MUT_RA_OLD, _MUT_RA_NEW),
)


def _load_mutated(old: str, new: str):
    """把 exec.py 源码定点文本替换后 exec 成独立模块（不落盘、不改工作区）。"""
    src = open(_EXEC_PY, encoding="utf-8").read()
    if old not in src:
        return None, src
    mut_src = src.replace(old, new, 1)
    mod = types.ModuleType("hive_exec_h4_mut")
    mod.__file__ = _EXEC_PY
    exec(compile(mut_src, _EXEC_PY, "exec"), mod.__dict__)   # noqa: S102 —— 定点变异
    return mod, src


_GROUPS = (g0_interface, g1_bounds, g2_transient_429_recovered,
           g3_non_retryable_no_retry, g4_5xx_and_jitter,
           g5_network_and_deterministic, g6_exhaustion_bounded,
           g7_observable_in_result, g8_oracle_no_fault_identical)


def _run_groups() -> int:
    global PASS, FAIL
    PASS, FAIL = 0, 0
    _NOTES.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            import traceback
            check("断言组 %s 抛异常：%s" % (g.__name__, exc), False,
                  traceback.format_exc()[-600:])
    return FAIL


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把重试面改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, _old, _new in _MUTATIONS:
            print("  " + name)
        return 0

    anchor_miss, bad = [], []
    with mock.patch("sys.stdout", io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, old, new in _MUTATIONS:
        mut, _src = _load_mutated(old, new)
        if mut is None:
            print("  ANCHOR-MISS %s —— 锚点在 exec.py 当前源码里找不到"
                  "（实现改了却没同步本表；基线不得静默漂移）" % name)
            anchor_miss.append(name)
            continue
        live = E["ex"]
        E["ex"] = mut
        try:
            with mock.patch("sys.stdout", buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            E["ex"] = live
        red_lines = [l for l in detail.splitlines() if "[FAIL]" in l]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-46s 红项=%d  %s" % ("OK  " if reds else "MISMATCH",
                                          name, reds, verdict))
        for l in red_lines:
            print("        " + l.strip())
        if not reds:
            bad.append("%s（红=0）" % name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _cleanup():
    import gc
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return
        gc.collect()


def main() -> int:
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup()
    try:
        n_fail = _run_groups()
        print("\nH-4(c) 守卫（LLM 有界退避重试）：%d 通过，%d 失败" % (PASS, n_fail))
        return 0 if not n_fail else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
