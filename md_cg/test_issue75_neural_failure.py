# -*- coding: utf-8 -*-
"""issue #75 部位②守卫：neural_retrieve 降级路径的**结构化失败 + 可观测**。

病灶（issue #75 部位②）：neural_retrieve.py 的降级路径以裸 except Exception
静默吞异常——CSPMN 回退处甚至是裸 pass。D-005 降级契约（不可用返回空）本身
是**对的**，问题在**静默**：调用方无法区分「没有命中」与「神经层整个没跑起来」。

修复口径（本守卫要钉死的四件事）：
  ① 每次吞异常都落一条结构化记录 {stage, exc_type, message}（实例上），
     并有公开访问器 failures() / last_failure() / failures_dropped()；
  ② **降级契约不变**：失败仍返回原契约值（[] / None / False / 0.0），**绝不抛**；
  ③ CSPMN 回退处不再裸 pass，记录「为何回退」，且**回退行为本身不变**
     （仍继续走 numpy，结果与纯 numpy 路径逐位一致）；
  ④ 模块级 logger 记一条 WARNING，使失败在日志面可见。

运行：
  python -X utf8 -m md_cg.test_issue75_neural_failure            # 正向
  python -X utf8 -m md_cg.test_issue75_neural_failure --mutate A # 定点变异自证

退出码（fail-closed）：
  0 = 全绿 / 变异逐条**恰好**命中期望红项；1 = 有断言失败或变异未按预期转红；
  2 = ANCHOR-MISS（变异锚点在盘上源码里命中次数 != 1，或运行时挂点不可调用）。

环境无关性：本守卫**不依赖 bge 模型**（本机 sentence_transformers 与模型目录均
不可用，实测 available()=False）。凡需要「失败」的地方一律用**注入**制造
（假 sentence_transformers / 假 cspmn / 假 model / 缺键索引），不依赖真模型；
numpy 缺失时相关断言记 SKIP 而非冒充绿。

源码形态断言一律读**盘上文件**（io.open），**不用** inspect.getsource——
变异是把方法 monkeypatch 掉，getsource 在读盘型断言上会读到变异体（前车之鉴）。
"""
from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_WISDOM = os.path.join(_HERE, "whitebox_kb", "wisdom")
for _p in (_WISDOM, os.path.join(_HERE, "whitebox_kb")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import neural_retrieve as nr  # noqa: E402

_TARGET = os.path.join(_WISDOM, "neural_retrieve.py")

try:
    import numpy as _numpy
except Exception:                     # noqa: BLE001
    _numpy = None

PASS = 0
FAIL = 0
SKIP = 0
FAILS: list = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name + (("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] " + name + "  · " + str(detail))


def skip(name, detail=""):
    """不可判定项：不计 PASS 也不计 FAIL（不冒充绿）。"""
    global SKIP
    SKIP += 1
    print("  [SKIP] " + name + (("  · " + str(detail)) if detail else ""))


def check(name, fn):
    """跑一条断言：fn 返回 (cond, detail)；fn 抛异常 ⇒ 该断言计红
    （变异②「降级改成抛异常」正是靠这条被抓住）。"""
    try:
        rv = fn()
    except Exception as exc:                      # noqa: BLE001
        ok(name, False, "抛出 " + type(exc).__name__ + ": " + str(exc)[:160])
        return
    if rv is None:                                # 断言内部已记 SKIP（不计 PASS 也不计 FAIL）
        return
    cond, detail = rv
    ok(name, bool(cond), detail)


# ---------------------------------------------------------------- 隔离工具
def _fresh():
    """强制新建实例：__new__ 是单例，断言之间必须隔离；同时清空编码缓存。"""
    nr.NeuralRetriever._singleton = None
    nr.NeuralRetriever._embed_cache = {}
    return nr.NeuralRetriever()


def _vec(*vals):
    return _numpy.array(list(vals), dtype=float)


def _install_index(inst):
    """装索引：numpy 可用时装合成索引（可验证回退结果逐位一致）；
    numpy 不可用时装最小字典——只为让 search_index 走到 numpy 兜底路径
    （该路径会因 import numpy 失败而抛，正好落到外层兜底）。
    返回是否装了可算的合成索引。"""
    if _numpy is None:
        inst._index = {"names": ["a"]}
        return False
    _fake_index(inst)
    return True


def _fake_index(inst):
    """装一份合成索引：3 张卡，前两张正交、第三张 45 度。"""
    vecs = _numpy.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.7, 0.7, 0.0]], dtype=float)
    norm = _numpy.linalg.norm(vecs, axis=1, keepdims=True)
    inst._index = {"vectors": vecs, "names": ["a", "b", "c"],
                   "domains": ["d1", "d2", "d3"], "edus": ["e1", "e2", "e3"],
                   "norm": norm, "vectors_normed": vecs / _numpy.maximum(norm, 1e-9)}
    return vecs


class _Capture(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records = []

    def emit(self, record):
        self.records.append(record)


# ---------------------------------------------------------------- 断言组 A
def a1():
    """初始态：无失败记录。"""
    inst = _fresh()
    return (inst.failures() == [] and inst.last_failure() is None
            and inst.failures_dropped() == 0,
            (inst.failures(), inst.last_failure()))


def a2():
    """load_index 失败：契约 False + 结构化记录 stage=load_index。"""
    inst = _fresh()
    nope = os.path.join(tempfile.gettempdir(), "i75_no_such_index.npz")
    rv = inst.load_index(npz_path=nope, meta_path=nope)
    fs = inst.failures()
    return (rv is False and len(fs) == 1 and fs[0]["stage"] == "load_index", (rv, fs))


def a3():
    """embed 失败：契约 None + 结构化记录 stage=embed。"""
    inst = _fresh()

    class _BadModel:
        def encode(self, text):
            raise RuntimeError("encode boom")

    inst._model = _BadModel()
    rv = inst.embed("任意文本")
    fs = inst.failures()
    return (rv is None and len(fs) == 1 and fs[0]["stage"] == "embed", (rv, fs))


def a4():
    """ensure_model 失败：stage=ensure_model，且 _fail_reason 保留。"""
    inst = _fresh()
    inst._model = None
    inst._fail_reason = None
    fake = types.ModuleType("sentence_transformers")

    def _boom(path):
        raise RuntimeError("model dir missing")

    fake.SentenceTransformer = _boom
    sys.modules["sentence_transformers"] = fake
    try:
        rv = inst.available()
    finally:
        sys.modules.pop("sentence_transformers", None)
    fs = inst.failures()
    return (rv is False and bool(inst.fail_reason())
            and len(fs) == 1 and fs[0]["stage"] == "ensure_model",
            (rv, fs, str(inst.fail_reason())[:60]))


def a5():
    """CSPMN 抛异常 → 记录 stage=cspmn_backend，且**回退行为不变**
    （结果与纯 numpy 路径逐位一致）。"""
    has_np = _numpy is not None
    base = None
    if has_np:
        inst0 = _fresh()
        _install_index(inst0)
        inst0.embed = lambda text: _vec(1.0, 0.0, 0.0)
        sys.modules["cspmn"] = None        # 逼 import cspmn 抛 ImportError ⇒ 纯 numpy 基线
        try:
            base = inst0.search_index("q", limit=3, threshold=0.0)
        finally:
            sys.modules.pop("cspmn", None)
    inst = _fresh()
    _install_index(inst)
    inst.embed = ((lambda text: _vec(1.0, 0.0, 0.0)) if has_np
                  else (lambda text: "fake-vec"))
    fake = types.ModuleType("cspmn")
    fake.GPU_THRESHOLD = 0                 # 任意 n 都触发 GPU 分支

    class _BoomCSPMN:
        def __init__(self, backend="auto"):
            raise RuntimeError("GPU lost")

    fake.CSPMN = _BoomCSPMN
    sys.modules["cspmn"] = fake
    if not has_np:
        # 本机 numpy 不可用 ⇒ search_index 会在 CSPMN 之前就 import numpy 失败，
        # 该分支**根本不可达**。为使断言真正覆盖「CSPMN 回退」，注入最小假 numpy：
        # 它只需让 import 成功，linalg.norm 故意抛 ⇒ 走到 CSPMN 分支并留痕后，
        # 由外层兜底收口（两条记录：cspmn_backend → search_index）。
        fake_np = types.ModuleType("numpy")

        class _Linalg:
            @staticmethod
            def norm(x):
                raise RuntimeError("fake numpy：仅为到达 CSPMN 分支")

        fake_np.linalg = _Linalg
        fake_np.maximum = lambda a, b: a
        fake_np.argsort = lambda x: []
        sys.modules["numpy"] = fake_np
    try:
        got = inst.search_index("q", limit=3, threshold=0.0)
    finally:
        sys.modules.pop("cspmn", None)
        if not has_np:
            sys.modules.pop("numpy", None)
    stages = [r["stage"] for r in inst.failures()]
    ok_cspmn = bool(stages) and stages[0] == "cspmn_backend"
    # 回退行为不变：numpy 在 → 与纯 numpy 结果逐位一致；numpy 不在 → 守住契约（[]）且不抛。
    ok_fb = (got == base and len(base) == 3) if has_np else (got == [])
    return (ok_cspmn and ok_fb,
            ("numpy=" + str(has_np), stages, "base=" + str(base), "got=" + str(got)))


def a6():
    """search_index 外层兜底：契约 [] + 记录 stage=search_index（末条）。"""
    inst = _fresh()
    # numpy 在 → 缺 vectors_normed 抛 KeyError；numpy 不在 → import numpy 抛 ImportError。
    # 两条都落在同一个外层兜底 except 上，故本断言对两种环境都成立（不 skip）。
    inst._index = {"names": ["a"]}
    inst.embed = lambda text: (_vec(1.0, 0.0) if _numpy is not None else "fake-vec")
    got = inst.search_index("q")
    fs = inst.failures()
    stages = [r["stage"] for r in fs]
    return (got == [] and stages and stages[-1] == "search_index", (got, stages))


def a7():
    """记录结构：三键齐备、类型正确、exc_type 为异常类名。"""
    inst = _fresh()
    inst._record_failure("probe", ValueError("结构检查"))
    r = inst.last_failure()
    fs = inst.failures()
    return (r is not None and set(r.keys()) == {"stage", "exc_type", "message"}
            and isinstance(r["stage"], str) and isinstance(r["exc_type"], str)
            and isinstance(r["message"], str) and r["exc_type"] == "ValueError"
            and len(fs) == 1, (r,))


def a8():
    """上限口径：只留最近 FAILURE_LIMIT 条、最旧先丢、淘汰数递增。"""
    inst = _fresh()
    limit = nr.FAILURE_LIMIT
    n = limit + 10
    for i in range(n):
        inst._record_failure("probe", ValueError("e" + str(i)))
    fs = inst.failures()
    return (len(fs) == limit and inst.failures_dropped() == n - limit
            and fs[0]["message"] == "e" + str(n - limit)
            and fs[-1]["message"] == "e" + str(n - 1)
            and isinstance(limit, int) and 10 <= limit <= 1000,
            (len(fs), inst.failures_dropped(), fs[0]["message"], fs[-1]["message"], limit))


def a9():
    """访问器返回**副本**：改返回值不影响内部状态。"""
    inst = _fresh()
    inst._record_failure("probe", ValueError("副本"))
    f1 = inst.failures()
    f1[0]["stage"] = "TAMPERED"
    f1.append({"stage": "T"})
    l1 = inst.last_failure()
    l1["stage"] = "TAMPERED"
    return (inst.failures()[0]["stage"] == "probe" and len(inst.failures()) == 1
            and inst.last_failure()["stage"] == "probe", (inst.failures(),))


def a10():
    """日志面：降级时模块 logger 恰好记一条 WARNING，logger 名 = 模块名。"""
    inst = _fresh()
    lg = logging.getLogger(nr.__name__)
    h = _Capture()
    old_level = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)
    try:
        inst._degrade("probe", ValueError("日志面探针"), None)
    finally:
        lg.removeHandler(h)
        lg.setLevel(old_level)
    warns = [r for r in h.records if r.levelno == logging.WARNING]
    return (len(warns) == 1 and warns[0].name == nr.__name__
            and "probe" in warns[0].getMessage(),
            (len(warns), warns[0].getMessage() if warns else None))


def a11():
    """源码形态（读**盘上文件**，非 getsource）：机制在位、裸 pass 已除、except 数未变。"""
    src = io.open(_TARGET, encoding="utf-8", newline="").read()
    checks = {
        "module logger": src.count("logger = logging.getLogger(__name__)") == 1,
        "_record_failure def": src.count("def _record_failure(self, stage, exc):") == 1,
        "_degrade def": src.count("def _degrade(self, stage, exc, degrade_value):") == 1,
        "failures def": src.count("def failures(self):") == 1,
        "last_failure def": src.count("def last_failure(self):") == 1,
        "failures_dropped def": src.count("def failures_dropped(self):") == 1,
        "no bare pass": ("except Exception:" + chr(10) + "                pass") not in src,
        "cspmn stage": src.count(chr(34) + "cspmn_backend" + chr(34)) == 1,
        "search_index degrade": src.count(
            "self._degrade(" + chr(34) + "search_index" + chr(34) + ", e, [])") == 1,
        "except count 7": src.count("except Exception") == 7,
        "cosine 保持 staticmethod": src.count(
            "@staticmethod" + chr(10) + "    def _cosine(a, b):") == 1,
        "cosine 不进实例记录": "self._degrade(" + chr(34) + "cosine" + chr(34) + ", e, 0.0)" not in src,
    }
    bad = [k for k, v in checks.items() if not v]
    return (not bad, "未过项=" + str(bad))


def a12():
    """降级**不抛**：三重失败路径下 search_index 仍返回 [] 而非抛异常。"""
    inst = _fresh()

    class _Boom:
        def encode(self, text):
            raise RuntimeError("boom")

    inst._model = _Boom()
    inst._index = {"names": ["a"]}
    got1 = inst.search_index("q")                    # embed 失败 → 早退 []
    inst2 = _fresh()
    inst2._index = {"names": ["a"]}
    inst2.embed = lambda text: (_vec(1.0) if _numpy is not None else "fake-vec")
    got2 = inst2.search_index("q")                   # 走到 numpy 兜底 → 外层 except → []
    return (got1 == [] and got2 == [] and len(inst2.failures()) >= 1, (got1, got2))


def a13():
    """_cosine **保持 staticmethod 签名**：类级调用形态不抛、实例调用形态同值，
    且不进实例结构化记录（它不在 search_index 调用链上——Lead 判定，理由见源码注释）。"""
    raw = nr.NeuralRetriever.__dict__.get("_cosine")
    static_ok = isinstance(raw, staticmethod)
    cls_rv = nr.NeuralRetriever._cosine("a", "b")     # 类级静态调用形态（签名契约）
    inst = _fresh()
    inst_rv = inst._cosine("a", "b")                  # 实例调用形态（既有唯一调用点形态）
    stages = [x["stage"] for x in inst.failures()]
    return (static_ok and cls_rv == 0.0 and inst_rv == 0.0 and "cosine" not in stages,
            ("staticmethod=" + str(static_ok), cls_rv, inst_rv, stages))


_ITEMS = [("A1 初始：无失败记录", a1),
          ("A2 load_index 失败 → False + stage=load_index", a2),
          ("A3 embed 失败 → None + stage=embed", a3),
          ("A4 ensure_model 失败 → stage=ensure_model（_fail_reason 保留）", a4),
          ("A5 CSPMN 抛异常 → 记录 cspmn_backend 且回退 numpy 结果不变", a5),
          ("A6 search_index 外层兜底 → [] + stage=search_index", a6),
          ("A7 记录结构三键齐备且类型正确", a7),
          ("A8 上限口径：留最近 FAILURE_LIMIT 条、最旧先丢", a8),
          ("A9 failures()/last_failure() 返回副本", a9),
          ("A10 日志面：模块 logger 记一条 WARNING", a10),
          ("A11 源码形态（读盘上文件）", a11),
          ("A12 降级不抛（三重失败仍返回 []）", a12),
          ("A13 _cosine 保持 staticmethod（类级调用不抛、不进实例记录）", a13)]

_GROUPS = {"A": _ITEMS}


# ---------------------------------------------------------------- 变异
def _mut_no_record():
    """变异①：去掉结构化记录（_record_failure 变 no-op）⇒ 可观测断言必须转红。"""
    orig = nr.NeuralRetriever._record_failure
    nr.NeuralRetriever._record_failure = lambda self, stage, exc: None
    return lambda: setattr(nr.NeuralRetriever, "_record_failure", orig)


def _mut_degrade_raises():
    """变异②：把降级改成抛异常 ⇒ 契约断言必须转红。"""
    orig = nr.NeuralRetriever._degrade

    def _boom(self, stage, exc, degrade_value):
        raise exc

    nr.NeuralRetriever._degrade = _boom
    return lambda: setattr(nr.NeuralRetriever, "_degrade", orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]——期望集合按**实测**填
_MUTATIONS = {
    "A": [("去掉结构化记录（可观测性归零）", _mut_no_record,
           {"A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A12"}),
          ("降级改成抛异常（破坏 D-005 契约）", _mut_degrade_raises,
           {"A2", "A3", "A5", "A6", "A10", "A12"})],
}


def _anchor_preflight():
    """变异锚点自检：读**盘上文件**（不用 inspect.getsource——变异后它会读到变异体）。"""
    src = io.open(_TARGET, encoding="utf-8", newline="").read()
    bad = []
    for label, anchor in (("_record_failure def", "def _record_failure(self, stage, exc):"),
                          ("_degrade def", "def _degrade(self, stage, exc, degrade_value):")):
        n = src.count(anchor)
        if n != 1:
            bad.append((label, "命中 " + str(n) + " 次(期望 1)"))
    for label, attr in (("_record_failure 挂点", "_record_failure"),
                        ("_degrade 挂点", "_degrade")):
        if not callable(getattr(nr.NeuralRetriever, attr, None)):
            bad.append((label, "运行时不可调用"))
    if not bad:
        return 0
    for label, why in bad:
        print("  ANCHOR-MISS " + label + "：" + why)
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_group(name):
    global PASS, FAIL, SKIP
    PASS = FAIL = SKIP = 0
    del FAILS[:]
    for label, fn in _GROUPS[name]:
        check(label, fn)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 " + repr(name) + "（可选 " + str(sorted(_MUTATIONS)) + "）")
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #75② 定点变异自证 · 组 " + name + "：内存注入退化，逐条要求恰好命中期望红项")
    base_red, _, _ = _run_group(name)
    print("  未变异基线：红项 " + str(len(base_red))
          + ("（应为 0）" if not base_red else " " + str(sorted(base_red))))
    bad = []
    if base_red:
        bad.append("基线即转红：" + str(sorted(base_red)))
    for i, (mname, apply, expect) in enumerate(_MUTATIONS[name]):
        restore = apply()
        try:
            red, _, _ = _run_group(name)
        except Exception as exc:                          # noqa: BLE001
            red = {"<变异体异常:" + type(exc).__name__ + ">"}
        finally:
            restore()
        hit = red == expect
        if not hit:
            bad.append("变异" + str(i + 1) + " " + mname + "：红项 " + str(sorted(red))
                       + " != 期望 " + str(sorted(expect)))
        print("  变异" + str(i + 1) + " " + mname + "  红项 " + str(len(red))
              + "（期望 " + str(len(expect)) + "）"
              + ("PASS" if hit else "**FAIL** 实=" + str(sorted(red)) + " 期=" + str(sorted(expect))))
    print("变异自证：" + ("PASS（逐条恰好命中期望红项）" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        return _mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
    print("#75 部位②守卫 · neural_retrieve 降级路径的结构化失败与可观测")
    print("=" * 72)
    _run_group("A")
    print("=" * 72)
    print("通过 " + str(PASS) + " / 失败 " + str(FAIL) + " / 不可判定(SKIP) " + str(SKIP))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
