# -*- coding: utf-8 -*-
"""蜂巢模型端点解析守卫（批次69 C3/C4：密钥解析与子任务开关）。

守的不变量（红→绿）：
  · 模型密钥与 base 的**唯一**取值口只读 serve 侧 env；spec 只提供布尔开关
    use_subagent_llm——spec 里塞密钥/base 一律无效（凭据外发面为零）
  · 开关为真且 env HIVE_SUBAGENT_API_KEY 非空 → 用子代理密钥；base 取
    HIVE_SUBAGENT_API_BASE，缺省回落主 base
  · 开关为真但子代理密钥缺失 → **整组安全回落主配置**（不炸 job、不半套错配）
  · 缺密钥的报错点名该配哪个 env，且**永不回显键值**
  · orch._spawn 只把布尔写进子 spec（不写值、不写 env 名、不写地址）

环境纪律：只用临时目录 + 哑值哨兵（*.invalid 地址），HTTP 全程桩驱动
（urlopen 被替换，零真实网络）；不触真实 serve / 令牌库 / 数据目录；退出清理。
运行：python -X utf8 -m hive.test_llm_key_resolution   （退出码 0 = 全绿）
红基线复跑：把 git HEAD 版 exec.py/orch.py 拷进临时目录后
    python -X utf8 -m hive.test_llm_key_resolution <临时目录>
（argv[1] 只在其中确实含 exec.py 时生效；run_tests.py 无额外 argv，恒走本目录）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
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


def _src_dir() -> str:
    """被测源码目录（默认本目录；红基线可传 argv[1]）。"""
    if len(sys.argv) > 1:
        cand = os.path.abspath(sys.argv[1])
        if os.path.isfile(os.path.join(cand, "exec.py")):
            return cand
    return _HERE


_SRC = _src_dir()


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ex = _load("hive_exec_keyres", os.path.join(_SRC, "exec.py"))
orc = _load("hive_orch_keyres", os.path.join(_SRC, "orch.py"))

PASS, FAIL = 0, 0
_TEXTS: list = []          # 需要参与「无明文泄漏」扫描的文案（排除出站请求本身）


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _note(tag: str, text: str) -> None:
    _TEXTS.append((tag, text or ""))


# ---------------------------------------------------------------- 哑值与环境
SENT_MAIN = "DUMMY-MAIN-KEY-not-a-credential"
SENT_SUB = "DUMMY-SUB-KEY-not-a-credential"
SENT_SPEC = "DUMMY-SPEC-KEY-must-be-ignored"
MAIN_BASE = "http://main.invalid/v1"
SUB_BASE = "http://sub.invalid/v1"
_ALL_SENT = (SENT_MAIN, SENT_SUB, SENT_SPEC)
_KEY_ENVS = ("HIVE_API_KEY", "HIVE_API_BASE",
             "HIVE_SUBAGENT_API_KEY", "HIVE_SUBAGENT_API_BASE")
OK_PAYLOAD = {"choices": [{"message": {"content": "正常终答"}}],
              "usage": {"total_tokens": 1}, "model": "mock-model"}
MSG = [{"role": "user", "content": "q"}]


class env_scope:
    """临时 env：四个端点键先清空再按哑值设置，退出逐键还原。"""

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in _KEY_ENVS}
        for k in _KEY_ENVS:
            os.environ.pop(k, None)
        for k, v in self.kw.items():
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


class _Resp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, n=None):
        return self._raw if n is None else self._raw[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_http(sink: list, error: Exception | None = None):
    """假 urlopen：记录出站请求（url/Authorization/body），返回 200 正常包或抛 error。"""
    def _urlopen(req, timeout=None):  # noqa: ARG001 —— 桩签名对齐 urllib
        sink.append({
            "url": getattr(req, "full_url", "") or "",
            "auth": (getattr(req, "headers", {}) or {}).get("Authorization"),
            "body": (getattr(req, "data", b"") or b"").decode("utf-8", "replace"),
        })
        if error is not None:
            raise error
        return _Resp(OK_PAYLOAD)
    return _urlopen


def _who(auth, labels: dict) -> str:
    """把 Authorization 头映射成类别标签——输出永不含键值本身。"""
    for label, val in labels.items():
        if auth == f"Bearer {val}":
            return label
    return "缺失" if not auth else "未知来源"


_LABELS = {"子代理键": SENT_SUB, "主键": SENT_MAIN}


# ------------------------------------------------------------- [A] 无密钥可诊断
print("[A] 无可用密钥 → RuntimeError 点名该配的 env（不冒充成功、不裸抛）")


def _call_err(spec: dict) -> Exception | None:
    try:
        ex.call_llm(dict(spec), [dict(m) for m in MSG])
        return None
    except Exception as e:  # noqa: BLE001 —— 本组断言的就是异常形态
        return e


with env_scope():
    a1 = _call_err({"model": "m"})
_note("A1", f"{type(a1).__name__}: {a1}")
check("A1 主路四键全空 → RuntimeError 且点名 HIVE_API_KEY",
      isinstance(a1, RuntimeError) and "HIVE_API_KEY" in str(a1),
      f"got {type(a1).__name__}: {'（点名缺失）' if 'HIVE_API_KEY' not in str(a1) else ''}")

with env_scope():
    a2 = _call_err({"model": "m", "use_subagent_llm": True})
_note("A2", f"{type(a2).__name__}: {a2}")
check("A2 开关为真且四键全空 → 文案同时点名 HIVE_SUBAGENT_API_KEY 与回落键",
      isinstance(a2, RuntimeError)
      and "HIVE_SUBAGENT_API_KEY" in str(a2) and "HIVE_API_KEY" in str(a2),
      f"got {type(a2).__name__}: {'（未点名子代理键）' if 'HIVE_SUBAGENT_API_KEY' not in str(a2) else ''}")

check("A3 缺密钥文案零明文（哑值哨兵零命中）",
      not any(s in str(a1) + str(a2) for s in _ALL_SENT))


# ---------------------------------------------------------- [B/C] 主键与子代理键
print("[B] 只有主密钥 → 用主密钥/主 base（历史行为零回归）")
_sink: list = []
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    _b = ex.call_llm({"model": "m"}, [dict(m) for m in MSG])
_b_req = _sink[-1] if _sink else {}
check("B1 主路 POST 用主密钥（Authorization 取自 env HIVE_API_KEY）",
      _who(_b_req.get("auth"), _LABELS) == "主键",
      f"实际来源={_who(_b_req.get('auth'), _LABELS)}")
check("B2 主路 POST 用主 base（HIVE_API_BASE + /chat/completions）",
      _b_req.get("url") == f"{MAIN_BASE}/chat/completions",
      f"got {_b_req.get('url')}")
check("B3 正常回包路径零回归（非空 content、无 _error）",
      "_error" not in _b and _b.get("content") == "正常终答")

print("[C] 开关为真 + 子代理 env 齐 → 子代理密钥与 base 生效")
_sink = []
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE,
               HIVE_SUBAGENT_API_KEY=SENT_SUB,
               HIVE_SUBAGENT_API_BASE=SUB_BASE), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    _c = ex.call_llm({"model": "m", "use_subagent_llm": True},
                     [dict(m) for m in MSG])
_c_req = _sink[-1] if _sink else {}
check("C1 开关为真 → Authorization 取自 env HIVE_SUBAGENT_API_KEY",
      _who(_c_req.get("auth"), _LABELS) == "子代理键",
      f"实际来源={_who(_c_req.get('auth'), _LABELS)}")
check("C2 子代理 base 覆盖生效（POST 目标 = HIVE_SUBAGENT_API_BASE）",
      _c_req.get("url") == f"{SUB_BASE}/chat/completions",
      f"got {_c_req.get('url')}")
check("C3 开关为真不影响返回契约（content 原样）", _c.get("content") == "正常终答")

print("[D] 开关为真但子代理 env 为空 → 安全回落主配置（不炸、不缺、不半套）")
_sink = []
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    _d = ex.call_llm({"model": "m", "use_subagent_llm": True},
                     [dict(m) for m in MSG])
_d_req = _sink[-1] if _sink else {}
check("D1 子代理键缺失 → 不抛且用主密钥（fail-safe 回落，不炸 job）",
      "_error" not in _d and _who(_d_req.get("auth"), _LABELS) == "主键",
      f"来源={_who(_d_req.get('auth'), _LABELS)}")
check("D2 子代理键缺失 → base 一并回落主 base（半套配置=跨网关错配）",
      _d_req.get("url") == f"{MAIN_BASE}/chat/completions",
      f"got {_d_req.get('url')}")

print("[E] base 覆盖/回落口径（含 model_base 单一取值口）")
_sink = []
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE,
               HIVE_SUBAGENT_API_KEY=SENT_SUB), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    ex.call_llm({"model": "m", "use_subagent_llm": True}, [dict(m) for m in MSG])
_e_req = _sink[-1] if _sink else {}
check("E1 子代理 base 缺省 → 回落主 base，密钥仍用子代理键",
      _e_req.get("url") == f"{MAIN_BASE}/chat/completions"
      and _who(_e_req.get("auth"), _LABELS) == "子代理键",
      f"url={_e_req.get('url')} 来源={_who(_e_req.get('auth'), _LABELS)}")
_mb = getattr(ex, "model_base", None)
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE,
               HIVE_SUBAGENT_API_KEY=SENT_SUB, HIVE_SUBAGENT_API_BASE=SUB_BASE):
    _e2_on = _mb({"use_subagent_llm": True}) if callable(_mb) else None
    _e2_off = _mb({"model": "m"}) if callable(_mb) else None
check("E2 model_base(spec) 与 POST 目标同源（开关真→子代理 base / 缺省→主 base）",
      callable(_mb) and _e2_on == SUB_BASE and _e2_off == MAIN_BASE,
      f"符号={'在' if callable(_mb) else '缺'} on={_e2_on} off={_e2_off}")

print("[F] spec 不得携带凭据/base（值只允许来自 env）")
_sink = []
_spec_polluted = {"model": "m", "api_key": SENT_SPEC, "api_base": "http://evil.invalid",
                  "HIVE_API_KEY": SENT_SPEC,
                  "use_subagent_llm": {"key": SENT_SPEC, "base": "http://evil.invalid"}}
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    ex.call_llm(_spec_polluted, [dict(m) for m in MSG])
_f_req = _sink[-1] if _sink else {}
_fdump = json.dumps(_f_req, ensure_ascii=False)
check("F1 spec 里的 api_key/api_base 一律被忽略（URL 仍取 env base）",
      _f_req.get("url") == f"{MAIN_BASE}/chat/completions",
      f"got {_f_req.get('url')}")
check("F2 开关键只作布尔判定（取 dict 形态也不外发其中的值）",
      _who(_f_req.get("auth"), _LABELS) == "主键" and SENT_SPEC not in _fdump,
      f"来源={_who(_f_req.get('auth'), _LABELS)} spec 哨兵={'命中' if SENT_SPEC in _fdump else '零命中'}")

print("[G] 工具路同源（run_with_tools 两处 _post_chat 走同一解析）")
_sink = []
with env_scope(HIVE_API_KEY=SENT_MAIN, HIVE_API_BASE=MAIN_BASE,
               HIVE_SUBAGENT_API_KEY=SENT_SUB,
               HIVE_SUBAGENT_API_BASE=SUB_BASE), \
        mock.patch.object(ex.urllib.request, "urlopen", side_effect=_stub_http(_sink)):
    _g = ex.run_with_tools({"model": "m", "use_subagent_llm": True,
                            "tools": ["read_file"], "max_tool_rounds": 1},
                           [dict(m) for m in MSG], "job_keyres", job_dir=None)
_g_req = _sink[-1] if _sink else {}
check("G1 工具路开关为真 → 同样用子代理密钥与 base",
      _who(_g_req.get("auth"), _LABELS) == "子代理键"
      and _g_req.get("url") == f"{SUB_BASE}/chat/completions",
      f"url={_g_req.get('url')} 来源={_who(_g_req.get('auth'), _LABELS)}")
check("G2 工具路正常终答零回归", _g.get("content") == "正常终答")

print("[H] orch._spawn：只把布尔开关写进子 spec（C4）")
_TMP = tempfile.mkdtemp(prefix="hive_keyres_")
_ORC_JOB = os.path.join(_TMP, "orchjob")
_ORC_POOL = os.path.join(_TMP, "jobs")
try:
    os.makedirs(_ORC_JOB)
    os.makedirs(_ORC_POOL)
    orc._CFG.update({"job_id": "orchjob", "job_dir": _ORC_JOB,
                     "jobs": _ORC_POOL, "model": "mock-model", "children": []})

    def _spawn_with(**env_kw):
        orc._CFG["children"] = []
        got: list = []

        def _fake_submit(jobs, sub):  # noqa: ARG001 —— 桩：只捕获子 spec
            got.append(dict(sub))
            return "hfake"

        with env_scope(**env_kw), \
                mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": _ORC_POOL}), \
                mock.patch.object(orc._hm, "_submit", side_effect=_fake_submit):
            res = orc._spawn({"user_prompt": "p"})
        return res, (got[-1] if got else {})

    _h1_r, _h1_sub = _spawn_with(HIVE_SUBAGENT_API_KEY=SENT_SUB,
                                 HIVE_API_KEY=SENT_MAIN)
    _h1_dump = json.dumps(_h1_sub, ensure_ascii=False)
    _note("H1", _h1_dump)
    check("H1 编排者 env 有子代理键 → sub.use_subagent_llm is True（布尔）",
          _h1_r.get("ok") is True and _h1_sub.get("use_subagent_llm") is True,
          f"ok={_h1_r.get('ok')} 键值类型={type(_h1_sub.get('use_subagent_llm')).__name__}")
    check("H2 子 spec 只带布尔：无键值/无 env 名/无 base 地址",
          not any(s in _h1_dump for s in (SENT_SUB, SENT_MAIN))
          and "HIVE_SUBAGENT_API_KEY" not in _h1_dump
          and "HIVE_SUBAGENT_API_BASE" not in _h1_dump
          and SUB_BASE not in _h1_dump and MAIN_BASE not in _h1_dump,
          "子 spec 出现凭据/env 名/地址")

    _h3_r, _h3_sub = _spawn_with(HIVE_API_KEY=SENT_MAIN)
    check("H3 编排者 env 无子代理键 → use_subagent_llm 不出现（继承主配置）",
          _h3_r.get("ok") is True and "use_subagent_llm" not in _h3_sub,
          f"ok={_h3_r.get('ok')} keys={sorted(_h3_sub)}")

    _h4_r, _h4_sub = _spawn_with(HIVE_SUBAGENT_API_KEY="   ")
    check("H4 空白值视同未配（与执行器/serve 侧去空白口径一致）",
          _h4_r.get("ok") is True and "use_subagent_llm" not in _h4_sub,
          f"ok={_h4_r.get('ok')} keys={sorted(_h4_sub)}")
finally:
    shutil.rmtree(_TMP, ignore_errors=True)

# ---------------------------------------------------------------- 无明文泄漏
_leak = sorted({tag for tag, txt in _TEXTS if any(s in txt for s in _ALL_SENT)})
check("L1 全部诊断/产物文案零明文（哑值哨兵零命中）", not _leak,
      f"命中来源 {_leak}")

print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
