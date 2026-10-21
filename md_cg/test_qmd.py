# -*- coding: utf-8 -*-
"""QMD 多维汇流检索 + 统一系统提示词守卫（md_cg/qmd.py、md_cg/qmd_llm.py）。

判据面（合成小库，确定性，零模型，零网络；网关用内存桩 opener，缓存建在系统临时目录）：
  P1  缺省关：MDCG_QMD_SYS 未设 / "0" / "true" / "" 时 extract、query、answer 的 messages 只有一条 user
  P2  打开态：MDCG_QMD_SYS="1" 时 extract、query、answer 首条为 system，文本 = SYSTEM（sha256 钉死）
  P3  判官隔离：judge 在开/关两态都不带 system；实际发出的请求体里也没有 system
  P4  缓存隔离：同一 prompt 在开态与关态的缓存身份不同；关态写入后开态读不到（干净 miss），反之亦然
      另：max_tokens 不同 ⇒ 干净 miss；不同 key 同 base+model ⇒ 干净 miss；缓存文件不含 key 明文（身份只存 sha256）
  P5  缓存身份校验：条目里存的身份被改动 ⇒ 读出抛 CacheIdentityError（不静默复用）
  P6  无配置显式边界：缺 BASE / MODEL / KEY 任一 ⇒ LLMUnavailable 且点名；网关调用 0 次
  P7  不回落其它厂商密钥：只设 MDCG_LLM_KEY / DEEPSEEK_API_KEY ⇒ 仍是 LLMUnavailable
  P8  坏响应显式报错：无 choices / 空 content / finish_reason=length ⇒ RuntimeError；{"data":{...}} 外包可解
  P9  枢纽抑制：出处超过 2% 文本的实体进 hubs、不进 prov；缺省参数下前 10 不含枢纽噪声文本（答句在前 4），
      hub=0 时枢纽噪声文本涌入前 10
  P10 源图缺块：triples 含 None 或与 texts 不等长 ⇒ PartialGraph；[] 合法
  P11 缺 hint：QMD.rank 抛 MissingHint；只有 require_hints=False 才退回，且与 MultiDim 逐位相同
  P12 题面扩展生效：零词面交集、源图里也不连题面的答句，有 hint 时排第 1，无 hint（显式退回）时不在前 10
  P13 关闭态逐位不变（结构）：import md_cg、md_cg.mdcg、md_cg.mdcos 后 md_cg.qmd / md_cg.qmd_llm 不在
      sys.modules；md_cg/ 里除本模块与守卫外无源码 import 它们（AST）
  P14 与原型逐位相同：夹具三问的完整排序 = 原型（LingShu-prime TanPowasd/agm/confluence）金标
  P15 抽取批处理：整批失败先重试、再拆半；单条仍失败记入 missing 而非静默丢弃；提示词与原型逐字相同（sha256）

运行：
  python -X utf8 -m md_cg.test_qmd             # 正向（P1–P15）
  python -X utf8 -m md_cg.test_qmd --mutate    # 定点变异自证（每条变异恰好点红其目标判据）
  python -X utf8 -m md_cg.test_qmd --mutate --list

退出码（fail-closed）：0 全绿；1 有断言失败 / 变异未恰好点红；2 变异锚点在源码里不唯一（锚点漂移）。
变异不写工作区：子进程在内存里把被测模块源码做一次替换后 exec 成同名模块（sys.modules 注入），再跑全部判据；
子进程崩溃（无红单）一律判变异失败。
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

PASS = 0
FAIL = 0
FAILS = []
_ENV_KEYS = ("MDCG_QMD_SYS", "MDCG_QMD_LLM_BASE", "MDCG_QMD_LLM_MODEL", "MDCG_QMD_LLM_KEY", "MDCG_LLM_KEY",
             "MDCG_LLM_BASE", "MDCG_LLM_MODEL", "DEEPSEEK_API_KEY")
FAKE = {"MDCG_QMD_LLM_BASE": "http://gateway.invalid/v1", "MDCG_QMD_LLM_MODEL": "fake-model",
        "MDCG_QMD_LLM_KEY": "GOV-IMPL-DUMMY-KEY"}
#: 统一系统提示词的 sha256（与原型 TanPowasd/agm/bench/hive_official.py SYSTEM 逐字相同时的值）
SYSTEM_SHA = "d5b55ccc587b5485"
#: 提示词模板 sha256 前 16 位（与原型 qx.P_ZH / qx.P_EN / hive_extract.PROMPT / extract.PROMPT 逐字相同时的值）
PROMPT_SHA = {"Q_ZH": "4cae3fdfd60a089f", "Q_EN": "2ba961f37580c624", "G_ZH": "eacec206ee74873f", "G_EN": "02e5705aa538e0ba"}


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def guarded(name, fn):
    """判据体抛异常 ⇒ 该判据红（不让一条判据的崩溃吞掉其余判据）。"""
    try:
        fn()
    except Exception as e:  # noqa: BLE001 —— 守卫面：异常即红并打印，不吞
        check(name, False, f"异常 {type(e).__name__}: {e}")


class _Env:
    def __init__(self, **kv):
        self.kv = kv

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.kv)

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _Gateway:
    """内存网关桩：记录每次请求体，按 reply(body) 生成返回体。"""

    def __init__(self, reply=None):
        self.bodies = []
        self.reply = reply or (lambda body: {"choices": [{"message": {"content": '{"ok": 1}'}, "finish_reason": "stop"}]})

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        self.bodies.append(body)
        out = json.dumps(self.reply(body)).encode("utf-8")

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(out)


def _sha16(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 检索夹具
def fixture():
    """(texts, sessions, triples, 问题表)。英文口径；每条文本一个会话（无时序边）。"""
    import random
    rnd = random.Random(20261015)
    letters = "bcdfghjklmnpqrstvwxyz"
    vow = "aeiou"

    def word():
        return "".join(rnd.choice(letters) + rnd.choice(vow) for _ in range(3))
    texts, triples = [], []

    def filler(n):                                   # 抽过、无事实；隔开关键文本，免得 TriCue 写入邻接边把它们连起来
        for _ in range(n):
            texts.append(" ".join(word() for _ in range(6)) + ".")
            triples.append([])
    S = len(texts); texts.append("Mira found the brass key in her coat pocket.")
    triples.append([["Mira", "found", "brass key"], ["Mira", "lives in", "Old Harbor"]])
    filler(10)
    A = len(texts); texts.append("Captain Rhee handed it over before dawn.")
    triples.append([["Captain Rhee", "gave", "brass key"]])
    filler(10)
    Bt = len(texts); texts.append("Tomas fixed it with copper gears last spring.")
    triples.append([["Tomas", "fixed", "clock tower"]])
    filler(10)
    H0 = len(texts)
    for k in range(20):                              # 枢纽：Old Harbor 出现在 20 条文本的三元组里（文本不含其字面）
        nm = word()
        texts.append(f"{word()} {word()} {nm} {word()}.")
        triples.append([["Old Harbor", "has", nm]])
    filler(50)
    sessions = [f"s{i}" for i in range(len(texts))]
    qs = {"hub": "Who gave Mira the brass key at Old Harbor?", "hint": "Who mended our town's timepiece?",
          "plain": "Where was the brass key found?"}
    hints = {qs["hint"]: {"ents": ["clock tower"], "preds": ["fixed", "repaired"], "time": None,
                          "kw": ["clock", "gears"], "hyde": "Tomas fixed the clock tower."},
             qs["hub"]: {"ents": ["Mira", "brass key"], "preds": ["gave", "handed"], "time": None,
                         "kw": ["key"], "hyde": "Rhee gave Mira the key."},
             qs["plain"]: {"ents": ["brass key"], "preds": ["found"], "time": None, "kw": ["pocket"],
                           "hyde": "She found the key in her coat."}}
    return texts, sessions, triples, qs, hints, {"S": S, "A": A, "B": Bt, "hubs": set(range(H0, H0 + 20))}


#: 原型金标：LingShu-prime TanPowasd/agm/confluence 的 MultiDim/QMD（en 口径，FROZEN）对 fixture() 三问的完整排序前 12
GOLDEN = {"hub": [0, 11, 1, 2, 12, 10], "hint": [22, 0, 23, 21, 1, 24], "plain": [0, 1, 2, 11], "md_hub": [0, 1, 2, 11], "md_hint": [], "md_plain": [0, 1, 2, 11], "v3_hub": [0, 1, 2]}


def run():
    from md_cg import qmd as Q
    from md_cg import qmd_llm as L
    texts, sess, tri, qs, hints, ix = fixture()

    # ---------------- P1 / P2 / P3
    def p123():
        for v in (None, "0", "true", ""):
            kv = {} if v is None else {"MDCG_QMD_SYS": v}
            with _Env(**kv):
                ok = all([m["role"] for m in L.messages(r, "p")] == ["user"] for r in ("extract", "query", "answer"))
                check(f"P1 关闭态只有 user（MDCG_QMD_SYS={v!r}）", ok)
        with _Env(MDCG_QMD_SYS="1"):
            ms = [L.messages(r, "p") for r in ("extract", "query", "answer")]
            check("P2 打开态 extract/query/answer 首条 system = SYSTEM",
                  all([m["role"] for m in x] == ["system", "user"] and x[0]["content"] == L.SYSTEM for x in ms))
        check("P2 SYSTEM 与原型逐字相同（sha256）", _sha16(L.SYSTEM) == SYSTEM_SHA, _sha16(L.SYSTEM))
        sent = []
        for v in ("1", None):
            kv = dict(FAKE, **({"MDCG_QMD_SYS": v} if v else {}))
            with _Env(**kv):
                gw = _Gateway()
                L.chat("judge", "判这题", opener=gw)
                sent.append(([m["role"] for m in L.messages("judge", "x")], [m["role"] for m in gw.bodies[0]["messages"]]))
        check("P3 判官开/关两态都不带 system（含实际请求体）", all(a == ["user"] and b == ["user"] for a, b in sent), str(sent))
    guarded("P1-P3", p123)

    # ---------------- P4 / P5
    def p45():
        with tempfile.TemporaryDirectory() as td:
            c = L.Cache(td)
            with _Env(**FAKE):
                cfg = L.config()
                i_off = L.Cache.identity("query", "同一个 prompt", cfg)
                c.put("query", "同一个 prompt", cfg, "关态结果")
            with _Env(MDCG_QMD_SYS="1", **FAKE):
                i_on = L.Cache.identity("query", "同一个 prompt", cfg)
                miss_on = c.get("query", "同一个 prompt", cfg)
                c.put("query", "同一个 prompt", cfg, "开态结果")
                hit_on = c.get("query", "同一个 prompt", cfg)
            with _Env(**FAKE):
                hit_off = c.get("query", "同一个 prompt", cfg)
            check("P4 开/关态缓存身份不同", L.Cache.key(i_on) != L.Cache.key(i_off))
            check("P4 关态写入后开态干净 miss、各自命中各自", miss_on is None and hit_on == "开态结果" and hit_off == "关态结果",
                  f"{miss_on!r} {hit_on!r} {hit_off!r}")
            with _Env(**FAKE):
                gw = _Gateway(); cnt = {}
                L.call("judge", "判", cfg=dict(cfg), cache=c, counter=cnt, opener=gw)
                L.call("judge", "判", cfg=dict(cfg), cache=c, counter=cnt, opener=gw)
                check("P4 同身份第二次命中缓存（调用 1 次）", cnt.get("calls") == 1 and len(gw.bodies) == 1, str(cnt))
                p = os.path.join(td, L.Cache.key(L.Cache.identity("judge", "判", cfg)) + ".json")
                d = json.load(open(p, encoding="utf-8"))
                d["identity"]["model"] = "另一个模型"
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
                try:
                    c.get("judge", "判", cfg); red = False
                except L.CacheIdentityError:
                    red = True
                check("P5 条目身份被改 ⇒ CacheIdentityError", red)
            with _Env(**FAKE):                       # PR #395 对抗复核补：max_tokens 与密钥摘要进身份
                gw = _Gateway(); cnt = {}
                L.call("extract", "抽", cfg=dict(cfg), cache=c, counter=cnt, opener=gw, max_tokens=100)
                d_miss = c.get("extract", "抽", cfg, 200)
                L.call("extract", "抽", cfg=dict(cfg), cache=c, counter=cnt, opener=gw, max_tokens=200)
                d_hit = c.get("extract", "抽", cfg, 100)
                check("P4 max_tokens 不同 ⇒ 干净 miss",
                      d_miss is None and d_hit is not None and cnt.get("calls") == 2
                      and [b.get("max_tokens") for b in gw.bodies] == [100, 200],
                      f"{d_miss!r} {cnt} {[b.get('max_tokens') for b in gw.bodies]}")
                cfg2 = dict(cfg, key="GOV-IMPL-DUMMY-KEY-2")
                L.call("judge", "钥", cfg=dict(cfg), cache=c, opener=gw)   # 先用第一把 key 写入（另取 prompt，避开 P5 篡改过的条目）
                k_miss = c.get("judge", "钥", cfg2)      # 同 base+model、另一把 key
                gw2 = _Gateway(); cnt2 = {}
                L.call("judge", "钥", cfg=dict(cfg2), cache=c, counter=cnt2, opener=gw2)
                check("P4 不同 key 同 base+model ⇒ 干净 miss", k_miss is None and cnt2.get("calls") == 1,
                      f"{k_miss!r} {cnt2}")
                blobs = "".join(open(os.path.join(td, f), encoding="utf-8").read() for f in os.listdir(td))
                check("P4 缓存文件不含 key 明文", bool(blobs) and cfg["key"] not in blobs and cfg2["key"] not in blobs,
                      "缓存文件里出现了密钥明文")
    guarded("P4-P5", p45)

    # ---------------- P6 / P7 / P8
    def p678():
        for drop in ("MDCG_QMD_LLM_BASE", "MDCG_QMD_LLM_MODEL", "MDCG_QMD_LLM_KEY"):
            kv = {k: v for k, v in FAKE.items() if k != drop}
            with _Env(**kv):
                gw = _Gateway()
                try:
                    L.chat("answer", "p", opener=gw); red, msg = False, ""
                except L.LLMUnavailable as e:
                    red, msg = True, str(e)
                except Exception as e:  # noqa: BLE001 —— 其它异常＝没有显式边界，判红并记下
                    red, msg = False, f"{type(e).__name__}: {e}"
                check(f"P6 缺 {drop} ⇒ LLMUnavailable 点名且 0 调用", red and drop in msg and not gw.bodies, msg)
        with _Env(MDCG_LLM_KEY="GOV-IMPL-DUMMY-KEY", DEEPSEEK_API_KEY="GOV-IMPL-DUMMY-KEY",
                  MDCG_QMD_LLM_BASE=FAKE["MDCG_QMD_LLM_BASE"], MDCG_QMD_LLM_MODEL="fake-model"):
            try:
                L.config(); red = False
            except L.LLMUnavailable:
                red = True
            check("P7 不回落 MDCG_LLM_KEY / DEEPSEEK_API_KEY", red)
        bad = {"无 choices": {"error": "x"}, "空 content": {"choices": [{"message": {"content": "  "}}]},
               "截断": {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}}
        with _Env(**FAKE):
            for name, body in bad.items():
                try:
                    L.chat("answer", "p", opener=_Gateway(lambda b, body=body: body)); red = False
                except RuntimeError:
                    red = True
                check(f"P8 坏响应（{name}）⇒ RuntimeError", red)
            txt = L.chat("answer", "p", opener=_Gateway(lambda b: {"data": {"choices": [{"message": {"content": "包"}}]}}))
            check("P8 {\"data\":{...}} 外包可解", txt == "包")
    guarded("P6-P8", p678)

    # ---------------- P9
    def p9():
        g = Q.MultiDim(texts, sess, tri, lang="en", w_v3=3.0)
        hub = [e for e, ws in enumerate(g.cw) if ws == {"old", "harbor"}]
        check("P9 枢纽实体进 hubs、不进 prov", len(hub) == 1 and hub[0] in g.hubs and hub[0] not in g.prov, str(hub))
        r = g.rank(qs["hub"])
        check("P9 缺省（hub=.02）前 10 不含枢纽噪声文本、答句在前 4", not (set(r[:10]) & ix["hubs"]) and ix["A"] in r[:4], str(r[:10]))
        r0 = Q.MultiDim(texts, sess, tri, lang="en", w_v3=3.0, hub=0).rank(qs["hub"])
        check("P9 hub=0 时枢纽噪声文本涌入前 10（≥5 条）", len(set(r0[:10]) & ix["hubs"]) >= 5, str(r0[:10]))
    guarded("P9", p9)

    # ---------------- P10
    def p10():
        bad = list(tri); bad[5] = None
        for name, t in (("含 None", bad), ("不等长", tri[:-1])):
            try:
                Q.MultiDim(texts, sess, t, lang="en"); red = False
            except Q.PartialGraph:
                red = True
            except Exception:  # noqa: BLE001 —— 崩在别处＝没有显式边界，判红
                red = False
            check(f"P10 源图{name} ⇒ PartialGraph", red)
        Q.MultiDim(texts, sess, [[] for _ in texts], lang="en")
        check("P10 全 [] 源图合法", True)
    guarded("P10", p10)

    # ---------------- P11 / P12
    def p1112():
        g = Q.QMD(texts, sess, tri, {}, lang="en", **Q.FROZEN)
        try:
            g.rank(qs["plain"]); red = False
        except Q.MissingHint:
            red = True
        check("P11 缺 hint ⇒ MissingHint", red)
        g2 = Q.QMD(texts, sess, tri, {}, lang="en", require_hints=False, **Q.FROZEN)
        md = Q.MultiDim(texts, sess, tri, lang="en", **Q.FROZEN)
        check("P11 显式 require_hints=False 退回且与 MultiDim 逐位相同", g2.rank(qs["plain"]) == md.rank(qs["plain"]))
        gh = Q.QMD(texts, sess, tri, hints, lang="en", **Q.FROZEN)
        r0 = g2.rank(qs["hint"])
        try:
            r1 = gh.rank(qs["hint"])
        except Q.MissingHint as e:                 # hint 没被读到 ⇒ 判红
            r1 = [f"MissingHint {e}"]
        check("P12 有 hint 时零交集答句排第 1", r1[:1] == [ix["B"]], str(r1[:5]))
        check("P12 无 hint（显式退回）时答句不在前 10", ix["B"] not in r0[:10], str(r0[:10]))
    guarded("P11-P12", p1112)

    # ---------------- P13
    def p13():
        code = ("import sys; sys.path.insert(0, %r); import md_cg, md_cg.mdcg, md_cg.mdcos; "
                "print(sorted(m for m in sys.modules if m.startswith('md_cg.qmd')))" % _REPO)
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=_REPO, capture_output=True, text=True,
                           encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"))
        check("P13 既有入口不加载 qmd / qmd_llm", r.returncode == 0 and r.stdout.strip() == "[]", (r.stdout + r.stderr)[-300:])
        import ast
        import warnings
        refs = []
        for dp, dn, fs in os.walk(os.path.join(_REPO, "md_cg")):
            dn[:] = [d for d in dn if d not in ("__pycache__", "whitebox_kb")]
            for fn in fs:
                if not fn.endswith(".py") or fn in ("qmd.py", "qmd_llm.py", "test_qmd.py"):
                    continue
                try:
                    with warnings.catch_warnings():  # 别的文件里的无效转义告警与本判据无关
                        warnings.simplefilter("ignore")
                        tree = ast.parse(open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read())
                except SyntaxError:
                    continue
                for nd in ast.walk(tree):          # 只认 import 语句（登记表里的锚点字符串不算引用）
                    names = ([a.name for a in nd.names] if isinstance(nd, ast.Import) else
                             [(nd.module or "")] + [a.name for a in nd.names] if isinstance(nd, ast.ImportFrom) else [])
                    if any(x.split(".")[-1] in ("qmd", "qmd_llm") for x in names):
                        refs.append(fn)
        check("P13 md_cg/ 无其它源码 import qmd / qmd_llm", not refs, str(refs))
    guarded("P13", p13)

    # ---------------- P14
    def p14():
        g = Q.QMD(texts, sess, tri, hints, lang="en", **Q.FROZEN)
        md = Q.MultiDim(texts, sess, tri, lang="en", w_v3=3.0)
        got = {}
        for k, q in qs.items():
            try:
                got[k] = g.rank(q)[:12]
            except Q.MissingHint as e:
                got[k] = f"MissingHint {e}"
        got.update({"md_" + k: md.rank(q)[:12] for k, q in qs.items()})
        got["v3_hub"] = g.base.rank(qs["hub"])[:12]
        check("P14 夹具排序与原型金标逐位相同", got == GOLDEN, json.dumps(got))
    guarded("P14", p14)

    # ---------------- P15
    def p15():
        for k in PROMPT_SHA:
            check(f"P15 提示词 {k} 与原型逐字相同（sha256）", _sha16(getattr(L, k)) == PROMPT_SHA[k], _sha16(getattr(L, k)))
        items = [(f"q{i}", f"问题{i}") for i in range(4)]
        seen = []

        def reply(body):
            p = body["messages"][-1]["content"]
            ids = [i for i, _ in items if f"[{i}]" in p]
            seen.append(ids)
            if len(ids) > 1:                       # 多题批一律坏 JSON ⇒ 逼出重试与拆半
                return {"choices": [{"message": {"content": "不是 JSON"}}]}
            if ids == ["q3"]:                      # q3 单题也失败 ⇒ 必须进 missing
                return {"choices": [{"message": {"content": '{"q": {}}'}}]}
            return {"choices": [{"message": {"content": json.dumps({"q": {ids[0]: {"ents": ["甲"], "preds": ["是"]}}})}}]}
        with _Env(**FAKE):
            gw = _Gateway(reply); cnt = {}
            orig = L.chat
            L.chat = lambda role, prompt, cfg=None, **kw: orig(role, prompt, cfg=cfg, opener=gw, **kw)
            try:
                got, missing = L.extract_hints(items, "zh", batch=4, counter=cnt)
            finally:
                L.chat = orig
        check("P15 拆半补抽：q0–q2 抽到，q3 进 missing", sorted(got) == ["q0", "q1", "q2"] and [m[0] for m in missing] == ["q3"],
              f"{sorted(got)} {missing}")
        check("P15 整批失败先原样重试一次再拆半", seen[:2] == [["q0", "q1", "q2", "q3"]] * 2, str(seen[:3]))
    guarded("P15", p15)


MUTATIONS = [
    ("M1 判官带 system（关掉判官隔离）", "md_cg.qmd_llm", '    if role == "judge":\n        return None\n', "",
     {"P3 判官开/关两态都不带 system（含实际请求体）"}),
    ("M2 缓存身份不含 system（缓存不隔离）", "md_cg.qmd_llm", '"system_sha": _sha(s) if s else None, ', "",
     {"P4 开/关态缓存身份不同", "P4 关态写入后开态干净 miss、各自命中各自"}),
    ("M3 关掉枢纽抑制（hub 缺省 0）", "md_cg.qmd", "DEF = dict(seeds=8, hub=.02,", "DEF = dict(seeds=8, hub=0,",
     {"P9 枢纽实体进 hubs、不进 prov", "P9 缺省（hub=.02）前 10 不含枢纽噪声文本、答句在前 4", "P14 夹具排序与原型金标逐位相同"}),
    ("M4 开关判真放宽", "md_cg.qmd_llm", 'return os.environ.get(SYS_ENV) == "1"',
     'return (os.environ.get(SYS_ENV) or "").lower() in ("1", "true")',
     {"P1 关闭态只有 user（MDCG_QMD_SYS='true'）"}),
    ("M5 缺配置静默放行", "md_cg.qmd_llm", "    if miss:\n        raise LLMUnavailable(", "    if False:\n        raise LLMUnavailable(",
     {"P6 缺 MDCG_QMD_LLM_BASE ⇒ LLMUnavailable 点名且 0 调用", "P6 缺 MDCG_QMD_LLM_MODEL ⇒ LLMUnavailable 点名且 0 调用",
      "P6 缺 MDCG_QMD_LLM_KEY ⇒ LLMUnavailable 点名且 0 调用", "P7 不回落 MDCG_LLM_KEY / DEEPSEEK_API_KEY"}),
    ("M6 回落通用密钥", "md_cg.qmd_llm", '"key": os.environ.get(KEY_ENV)}',
     '"key": os.environ.get(KEY_ENV) or os.environ.get("MDCG_LLM_KEY")}', {"P7 不回落 MDCG_LLM_KEY / DEEPSEEK_API_KEY"}),
    ("M7 缓存身份不校验", "md_cg.qmd_llm", 'if d.get("identity") != ident:', "if False:",
     {"P5 条目身份被改 ⇒ CacheIdentityError"}),
    ("M8 源图缺块不报错", "md_cg.qmd", "        if miss:\n            raise PartialGraph(", "        if False:\n            raise PartialGraph(",
     {"P10 源图含 None ⇒ PartialGraph"}),
    ("M9 缺 hint 静默退回多维", "md_cg.qmd", "            if self.require_hints:\n                raise MissingHint(q)\n", "",
     {"P11 缺 hint ⇒ MissingHint"}),
    ("M10 不读题面扩展", "md_cg.qmd", "h = h or self.hints.get(q)", "h = h or None",
     {"P12 有 hint 时零交集答句排第 1", "P14 夹具排序与原型金标逐位相同"}),
    ("M11 单条失败静默丢弃", "md_cg.qmd_llm", '            missing.append((miss[0][0], repr(err) if err else "输出缺该条"))', "            pass",
     {"P15 拆半补抽：q0–q2 抽到，q3 进 missing"}),
    ("M12 缓存身份不含 max_tokens", "md_cg.qmd_llm", '"max_tokens": max_tokens or None, ', "",
     {"P4 max_tokens 不同 ⇒ 干净 miss"}),
    ("M13 缓存身份不含密钥摘要", "md_cg.qmd_llm", '"key_sha": _sha(cfg["key"]),', "",
     {"P4 不同 key 同 base+model ⇒ 干净 miss"}),
    ("M14 缓存身份存密钥明文", "md_cg.qmd_llm", '"key_sha": _sha(cfg["key"])', '"key_sha": cfg["key"]',
     {"P4 缓存文件不含 key 明文"}),
]


def _src_path(mod):
    return os.path.join(_REPO, *mod.split(".")) + ".py"


def _child(i):
    """子进程：在内存里装入变异后的模块，再跑全部判据（不落盘）。"""
    _, mod, anchor, repl, _ = MUTATIONS[i]
    import md_cg  # 先装包（__init__ 不引入 qmd / qmd_llm）
    path = _src_path(mod)
    src = open(path, encoding="utf-8").read()
    m = types.ModuleType(mod)
    m.__file__ = path
    m.__package__ = "md_cg"
    sys.modules[mod] = m
    setattr(md_cg, mod.split(".")[-1], m)
    exec(compile(src.replace(anchor, repl), path, "exec"), m.__dict__)
    run()


def mutate(list_only=False):
    if list_only:
        for name, mod, *_, want in MUTATIONS:
            print(f"{name}（{mod}） ⇒ 期望点红：{sorted(want)}")
        return 0
    for name, mod, anchor, _, _ in MUTATIONS:
        n = open(_src_path(mod), encoding="utf-8").read().count(anchor)
        if n != 1:
            print(f"ANCHOR-MISS {name}: 锚点在 {mod} 命中 {n} 次")
            return 2
    bad = 0
    for i, (name, _, _, _, want) in enumerate(MUTATIONS):
        env = dict(os.environ, PYTHONUTF8="1")
        for k in _ENV_KEYS:
            env.pop(k, None)
        p = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.test_qmd", "--child", str(i)],
                           cwd=_REPO, capture_output=True, text=True, encoding="utf-8", env=env)
        reds = {ln[len("REDLIST "):] for ln in p.stdout.splitlines() if ln.startswith("REDLIST ")}
        ok = bool(reds) and reds == want
        bad += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: 红 {sorted(reds)}" + ("" if ok else f"  期望 {sorted(want)}"
              + ("" if reds else f"  子进程 rc={p.returncode} stderr 尾：{p.stderr[-300:]}")))
    print(f"变异 {len(MUTATIONS)} 条，未恰好点红 {bad} 条")
    return 1 if bad else 0


def _finish():
    if "--json-fails" in sys.argv or "--child" in sys.argv:
        for f in FAILS:
            print("REDLIST " + f)
    print(f"通过 {PASS} / 失败 {FAIL}")
    return 1 if FAIL else 0


def main():
    if "--mutate" in sys.argv:
        return mutate("--list" in sys.argv)
    if "--child" in sys.argv:
        _child(int(sys.argv[sys.argv.index("--child") + 1]))
        return _finish()
    run()
    return _finish()


if __name__ == "__main__":
    sys.exit(main())
