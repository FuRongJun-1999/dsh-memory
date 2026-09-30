# -*- coding: utf-8 -*-
"""统一归一层「缺省关」守卫（2026-09-30 使用者裁定：MDCG_UNIFY_QUERY 缺省由开翻关）

口径（契约 = 使用者裁定，判据落点两侧各一）：

    MDCG_UNIFY_QUERY   Python `semantic/unify.py::unify_on()`   Rust `rust/src/atoms.rs::Atoms::from_env()`
    未设                False（缺省 "0"）                        None（不载入）
    "0"                 False                                   None（不载入）
    "1"                 True                                    Some(Atoms)（载入）

即**唯一开态 = 显式 "1"**；未设与 "0" 同语义（两侧同判）。定因：本层本职是让
**英文** query 命中中文节点，对中文检索池是**纯开销**——locomo-zh-500 公开题池
（池 567 / 题 500）缺省关态 lexical hit@1 96.4% / lexical+fuzzy 97.2%，开态
95.8% / 96.6%（各跑两遍逐位相同；本件不跑该池，该读数由
`python -X utf8 -m md_cg.bench_locomo_zh_public` 产出，见 §五 use 面）。

覆盖与判据（每条对应契约的一项）：

  G0 隔离与基线自证——辅助/库根全落守卫临时目录；口径类 env 干净（本件在**缺省
     态**上验证）；**基线源 = 当前工作区源码**（本件不含任何提交快照读取面，
     结构上自证：源码里无 git 调用字面量）——本仓已有两次「基线绑提交即失效」教训。

  G1 三态（契约①）——Python 侧三态断言：`unify_on()` 三态 + `unify_query` 三态
     返回值（含英文 query 未设/`0`/`1` 各一读数、中文与中夹英 query 三态恒等），
     外加「未设产物 == `0` 产物」逐位相同（缺省真的等同于关）。

  G2 检索读数（契约②）——**同一池**上跑未设/`0`/`1` 三态：未设读数与 `0` 读数
     逐位相同；并断言 `1` 态读数与之**不同**（否则池对开关不敏感、该判据空转），
     且 `1` 态 top-1 = 中文节点、未设态 top-1 ≠ 该节点（方向断言，非仅相等）。

  G3 两侧一致（契约③）——用**真 rust release 二进制**（`--serve` 协议）在同一池上
     跑同一三态：Rust 未设读数 == Rust `0` 读数、`1` 态与之不同且 top-1 = 中文节点；
     末了做**跨侧同判**断言（Python 判据与 Rust 判据对每一态的判定一致）。

  G4 结构面（防回退）——两侧判据落点的字面锚点（Python 缺省 "0" + `== "1"`；
     Rust `!= Ok("1")`）、三处 search 入口接线仍在、`MDCG_UNIFY_QUERY` 仍在
     `hotcache._ENV_SWITCHES`（开关不得删）、Python 侧无「缺省 "1"」残留。

  M 定点变异自证（契约④）——把修复点逐一改回缺陷形态，套件必须按**预期条数**
     恰好转红（多红=判据越界、少红=判据空转，两种都判失败）：
     M1 Python 缺省 "0"→"1"（改回缺省开）→ 预期红 **13** 项；
     M2 Rust 三态改回 `map(|v| v == "0").unwrap_or(false)`（未设=开）——**源码定点
        变异 + 临时 CARGO_TARGET_DIR 重建真二进制**（零第三方依赖，冷构建本机实测
        ~7s），再以该二进制跑 G3 → 预期红 **8** 项。
     锚点在当前源码里逐字找不到 → ANCHOR-MISS → **退出码 2（fail-closed）**。
     变异锚点一律取**代码行**（含行首缩进）而非裸表达式：裸串在注释里可能同形，
     只替换注释那处会让代码不动、断言仍绿（2026-09-30 实测踩过此坑）。
     文书/接线类锚点（G4c/G4f/G4g/G4h/G4i）**不被这两条变异弄红**——它们钉的是注释
     文本与接线，效力由「实现漂移即红」保证，不由变异证明（如实标注，不假装覆盖）。

运行：
    python -X utf8 -m md_cg.test_unify_default_off              # 正向
    python -X utf8 -m md_cg.test_unify_default_off --mutate     # 定点变异自证
    python -X utf8 -m md_cg.test_unify_default_off --mutate --list

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红 / 前置缺失；
2 = ANCHOR-MISS（变异锚点漂移——实现改了却没同步本表，本表就是判据）。

依赖：`rust/target/release/mdcg-eval`（两侧一致性要用真二进制）与 `cargo`（M2 重建）。
二进制缺失时 `main()` **前置判红**并给出可执行重编命令（同
`md_cg/test_rank_parity_score_mode.py` 的口径：跑不起来 ≠ 通过，不采用静默 SKIP）。
G3 依赖缺失即逐条 `SKIP(未跑)` **不计入通过数**，并补一条 fail-closed 红项。

硬边界：不动任何在役数据根（辅助根/库根一律 `tempfile.mkdtemp`）；不 git
add/commit/push；不改 `data/policy.json`；不改归一层算法本体与作用域收窄逻辑；
不改 `rust/src/atoms.rs` 的 CJK 判据、不动 `md_cg/semantic/unify_fixture.json`
（被 `atoms.rs` 以 `include_str!` 编译期嵌入，改它会破编译）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（沿用
# md_cg/test_rank_parity_score_mode.py 同款前置：部分模块在导入期把 aux_root()
# 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="unify_default_off_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           # 口径面：本件在**缺省态**上验证，故这三个开关必须干净
           "MDCG_SCORE_MODE", "MDCG_UNIFY_QUERY", "MDCG_EN_ATOMS", "MDCG_SEMANTIC"):
    os.environ.pop(_k, None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:                                  # pragma: no cover
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_UNIFY_PY = os.path.join(_HERE, "semantic", "unify.py")
_ATOMS_RS = os.path.join(_REPO, "rust", "src", "atoms.rs")
_MDCG_PY = os.path.join(_HERE, "mdcg.py")
_MDCOS_PY = os.path.join(_HERE, "mdcos.py")
_HOTCACHE_PY = os.path.join(_HERE, "hotcache.py")
_EN_ZH_MAP = os.path.join(_HERE, "semantic", "en_zh_map.json")
_RUST_DIR = os.path.join(_REPO, "rust")
_EXE = os.path.join(_RUST_DIR, "target", "release",
                    "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")

# 被测面**可替换**落点（变异模式换副本）：断言组一律经本表取路径，不闭包捕获原值，
# 否则变异对断言不可见。
U = {"unify": _UNIFY_PY}      # Python 判据落点（unify.py 路径）
R = {"exe": _EXE}             # Rust 判据落点（release 二进制路径）
RS = {"src": _ATOMS_RS}       # Rust 判据**源码**落点（结构锚点读它；变异模式=副本）

# 三态判据里唯一的开态字面量（两侧共用同一开态 = "1"）
_ON = "1"

_PASS: list = []
_FAIL: list = []
_SKIP: list = []


# 生效条件：cond 为真值判定、msg 为说明串、extra 为失败附加读数；恒把 msg 记入 _PASS 或 _FAIL（收集式，**不中断**）——使「定点变异红了几项」可数（首条即停的 assert 风格数不出红项数）。
def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


# 生效条件：单参 msg 为说明串；把该条记入 _SKIP 并打印——依赖缺失时的**显式跳过**（不计入通过数），与「静默照绿」区分。
def skip(msg):
    _SKIP.append(msg)
    print("  SKIP(未跑·不计通过) " + msg)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.2)
    return not os.path.exists(path)


# --------------------------------------------------------------- Python 判据装载
def install_unify(path):
    """把 path 处的 unify.py 装成**进程内唯一** `md_cg.semantic.unify` 并返回它。

    装进 `sys.modules` 是关键：`mdcos.search` / `search_rrf` / `mdcg.search` 三处
    入口都是**方法内** `from .semantic.unify import unify_query`（调用期解析），
    故替换该键即让变异对**检索读数**同样可见——否则变异只打红单元断言，
    读数类断言（G2）会对变异无感（假守卫形态）。
    """
    import md_cg.semantic                              # 父包（相对导入解析用）
    spec = importlib.util.spec_from_file_location("md_cg.semantic.unify", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["md_cg.semantic.unify"] = mod
    spec.loader.exec_module(mod)
    return mod


# 生效条件：无参；返回当前装载的 `md_cg.semantic.unify` 模块（由 install_unify 装入，缺省即工作区源）。
def UU():
    return sys.modules["md_cg.semantic.unify"]


# 生效条件：无参；返回 [未设, "0", "1"] 三态快照的可调用迭代器——每态进入时把 os.environ 拨到该态，退出后**恢复原状**（含原本未设的情形）。
@contextlib.contextmanager
def env_state(value):
    """把 MDCG_UNIFY_QUERY 拨到 value（None = 未设），退出时恢复原状。"""
    had = "MDCG_UNIFY_QUERY" in os.environ
    old = os.environ.get("MDCG_UNIFY_QUERY")
    if value is None:
        os.environ.pop("MDCG_UNIFY_QUERY", None)
    else:
        os.environ["MDCG_UNIFY_QUERY"] = value
    try:
        yield
    finally:
        if had:
            os.environ["MDCG_UNIFY_QUERY"] = old
        else:
            os.environ.pop("MDCG_UNIFY_QUERY", None)


# ================================================================ 池与读数
EN_Q = "I eat beef yesterday"          # 英文 query：唯一通路 = 归一层（beef→牛肉）
ZH_Q = "自我接纳"                       # 纯中文：三态恒等
MIX_Q = "领养 LGBTQ 群体"               # 中夹英：三态恒等（收窄后）
NUM_Q = "2024 报告"                     # 无字母：三态恒等
GOLD = "n_gold"                        # 中文节点（含「牛肉」），只在归一层开时被英文 query 命中

# 池：**噪声节点在前、gold 在最后**（4 条全中文正文）。这样「无词面命中」的兜底
# 序里 gold 不在 top-1，而开态只留下 gold——两侧 top-1 才是**有方向**的判据。
# 池里**无英文正文**：英文 query 与池的词面交集**只能**由归一层产生。
_POOL_NODES = (
    ("n_a", "# 功能名：雨天 爱好\n# 正文：我喜欢在雨天听爵士乐。"),
    ("n_b", "# 功能名：通勤 记录\n# 正文：早高峰地铁很挤，只能站着。"),
    ("n_c", "# 功能名：种花 笔记\n# 正文：阳台上的绿萝长势不错，顺手浇了水。"),
    (GOLD, "# 功能名：午饭 记录\n# 正文：昨天中午我在家里吃了牛肉面，配了可乐。"),
)


# 生效条件：root 为存在的目录时，在其 graph/ 子目录以 MdCGSecure(designer/test principal) 建两节点池并 flush，返回 (节点数, graph 目录)；重复调用幂等（同 id 覆盖写）。
def build_pool(root):
    """建两节点池（与 rank_parity 同款 MdCGSecure 形态——rust serve 能读同一 graph 目录）。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    graph = os.path.join(root, "graph")
    cg = MdCGSecure(graph, principal=Principal(
        actor="unifyoff", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    for nid, body in _POOL_NODES:
        cg.add(nid, body, layer="knowledge")
    cg.flush()
    cg.close()
    return len(_POOL_NODES), graph


# 生效条件：graph 为池目录、q 为查询串、k 为正整数；以 MdCGSecure 打开该池对 q 做 search(judge=False, record=False)，返回 [(id, round(score,12)), ...] 保序列表。
def py_reading(graph, q, k=5):
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(graph, principal=Principal(
        actor="unifyoff", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    try:
        res, _meta = cg.search(q, k=k, judge=False, record=False)
        return [(r[0].get("id") or r[0].get("path") or "", round(float(r[1]), 12))
                for r in res]
    finally:
        cg.close()


# 生效条件：exe 为可执行的 rust release 二进制、graph 为池目录、state 为三态取值（None=未设 / "0" / "1"）；以 `--serve --score jaccard` 拉起新进程（env 显式带 MDCG_EN_ZH_MAP 指向仓库词表）、对 EN_Q 查询后关进程，返回 [(id, round(score,12)), ...]；进程无输出即抛 RuntimeError。
def rust_reading(exe, graph, state, q=EN_Q, k=5):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["MDCG_EN_ZH_MAP"] = _EN_ZH_MAP
    env.pop("MDCG_TOKEN", None)
    if state is None:
        env.pop("MDCG_UNIFY_QUERY", None)
    else:
        env["MDCG_UNIFY_QUERY"] = state
    p = subprocess.Popen([exe, "--root", graph, "--serve", "--score", "jaccard"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", env=env)
    try:
        p.stdin.write(json.dumps({"op": "search", "query": q, "k": k}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        if not line:
            err = p.stderr.read() if p.stderr else ""
            raise RuntimeError(f"rust serve 输出关闭：{err[:400]}")
        resp = json.loads(line)
        hits = resp.get("hits") or resp.get("results") or []
        out = []
        for h in hits:
            if isinstance(h, dict):
                out.append((h.get("id") or h.get("node") or "",
                            round(float(h.get("score") or 0.0), 12)))
            else:
                out.append((str(h), 0.0))
        return out
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=5)
        except Exception:                              # noqa: BLE001 —— 清理面不抛
            try:
                p.kill()
            except Exception:                          # noqa: BLE001
                pass


# 生效条件：reading 为 [(id, score), ...] 列表；返回其 top-1 的 id（空列表返回 None）。
def top1(reading):
    return reading[0][0] if reading else None


# 生效条件：reading 为 [(id, score), ...] 列表、nid 为目标节点 id；返回该节点的分值（不在读数里返回 None）。
def score_of(reading, nid):
    return dict(reading).get(nid)


# ================================================================ G0 前置自证
def g0():
    print("== G0 隔离、缺省态前提与基线源自证 ==")
    ok(os.path.abspath(os.environ["MDCG_AUX_ROOT"]).lower().startswith(_TMP.lower()),
       "G0a 辅助根落在守卫临时目录（绝不触真实凭据/密钥面）",
       os.environ["MDCG_AUX_ROOT"])
    ok("MDCG_UNIFY_QUERY" not in os.environ
       and "MDCG_EN_ATOMS" not in os.environ and "MDCG_SEMANTIC" not in os.environ,
       "G0b 口径类 env 干净：本守卫确实在**缺省态**上验证",
       os.environ.get("MDCG_UNIFY_QUERY"))
    src = _read(_SELF)
    ok(re.search(r'["\']git["\']', src) is None,
       "G0c 基线自证：本守卫源码里没有任何 git/提交快照读取面（argv 级）"
       "——基线 = 当前工作区源码，绑定提交即失效")
    ok(UU().__file__ == U["unify"],
       "G0d 被测 Python 判据装载自 U 表当前指向的源（正向=工作区源；变异=临时副本）",
       UU().__file__)
    ok(old_default(_read(_UNIFY_PY)) is False,
       "G0e 前置：**工作区** unify.py 的缺省已是 \"0\"（本件的前提；落点在工作区"
       "文件而非变异副本，故变异不会把它弄红）")
    print("      被测面：%s" % U["unify"])
    print("      Rust 判据：%s" % R["exe"])


# 生效条件：src 为 unify.py 源码文本；返回 True 表示仍含「缺省 "1"」的**旧形态**（os.environ.get("MDCG_UNIFY_QUERY", "1")），否则 False。
def old_default(src):
    return 'os.environ.get("MDCG_UNIFY_QUERY", "1")' in src


# ================================================================ G1 Python 三态
def g1():
    print("== G1 契约①：Python 三态（未设=关 / \"0\"=关 / \"1\"=开）==")
    with env_state(None):
        on_unset = UU().unify_on()
        q_unset = UU().unify_query(EN_Q)
    with env_state("0"):
        on_zero = UU().unify_on()
        q_zero = UU().unify_query(EN_Q)
    with env_state("1"):
        on_one = UU().unify_on()
        q_one = UU().unify_query(EN_Q)
    ok(on_unset is False, "G1a 未设 → unify_on() is False（缺省关）", on_unset)
    ok(on_zero is False, "G1b \"0\" → unify_on() is False", on_zero)
    ok(on_one is True, "G1c \"1\" → unify_on() is True（唯一开态）", on_one)
    ok(q_unset == EN_Q, "G1d 未设 → 英文 query 原样返回（未归一）%r" % q_unset)
    ok(q_zero == EN_Q, "G1e \"0\" → 英文 query 原样返回（未归一）%r" % q_zero)
    ok(q_one == "我 吃 牛肉 昨天",
       "G1f \"1\" → 英文 query 归一为中文原子序列 %r" % q_one)
    ok(q_unset == q_zero,
       "G1g 未设产物 == \"0\" 产物（逐位相同）——缺省确实等同于关",
       "%r vs %r" % (q_unset, q_zero))
    ok(q_one != q_unset, "G1h 判别力：\"1\" 产物 != 未设产物（判据对开关敏感）",
       "%r vs %r" % (q_one, q_unset))
    # 非英文 query：三态恒等（本层只译英文内容；缺省翻转不得改变这三类）
    for name, t in (("纯中文", ZH_Q), ("中夹英", MIX_Q), ("无字母", NUM_Q)):
        vals = []
        for st in (None, "0", "1"):
            with env_state(st):
                vals.append(UU().unify_query(t))
        ok(vals[0] == vals[1] == vals[2] == t,
           "G1i %s query 三态恒等且原样（%r）" % (name, t), vals)


# ================================================================ G2 检索读数（同一池）
def g2():
    print("== G2 契约②：同一池上，未设态读数 == \"0\" 态读数（逐位）==")
    root = tempfile.mkdtemp(prefix="unifyoff_pool_")
    try:
        n, graph = build_pool(root)
        ok(n == len(_POOL_NODES), "G2a 池建成 %d 节点（正对照：夹具不空转）" % n, n)
        with env_state(None):
            r_unset = py_reading(graph, EN_Q)
        with env_state("0"):
            r_zero = py_reading(graph, EN_Q)
        with env_state("1"):
            r_one = py_reading(graph, EN_Q)
        ok(r_unset == r_zero,
           "G2b 未设态读数 == \"0\" 态读数（逐位：id+分值）",
           "%r vs %r" % (r_unset, r_zero))
        ok(r_one != r_unset,
           "G2c 判别力：\"1\" 态读数 != 未设态读数（否则该池对开关不敏感=空转）",
           "%r vs %r" % (r_one, r_unset))
        ok(top1(r_one) == GOLD,
           "G2d \"1\" 态 top-1 = 中文节点 %s（归一路真的生效）" % GOLD, r_one[:2])
        ok((score_of(r_one, GOLD) or 0.0) > (score_of(r_unset, GOLD) or 0.0),
           "G2e 方向：\"1\" 态 gold 分值 > 未设态 gold 分值（归一路抬升了 gold）",
           "on=%r off=%r" % (score_of(r_one, GOLD), score_of(r_unset, GOLD)))
        ok(top1(r_unset) != GOLD,
           "G2f 未设态 top-1 != %s（缺省确实关：无词面交集 → 兜底序里 gold 不居首）"
           % GOLD, r_unset[:3])
        ok(r_zero == r_unset and top1(r_zero) != GOLD,
           "G2g \"0\" 态与未设态同判（读数逐位相同且 gold 不居首）", r_zero[:3])
    finally:
        _cleanup(root)


# ================================================================ G3 两侧一致
def g3():
    print("== G3 契约③：Rust 侧同一三态（真二进制 serve）+ 跨侧同判 ==")
    if not os.path.isfile(R["exe"]):
        skip("G3 两侧一致性（rust 二进制缺失）—— 修复：cd rust && cargo build --release")
        ok(False, "G3 前置：rust release 二进制在位（fail-closed：跑不起来≠通过）",
           R["exe"])
        return
    root = tempfile.mkdtemp(prefix="unifyoff_rustpool_")
    try:
        n, graph = build_pool(root)
        ok(n == len(_POOL_NODES), "G3a 池建成 %d 节点（两侧同一池）" % n, n)
        try:
            rs_unset = rust_reading(R["exe"], graph, None)
            rs_zero = rust_reading(R["exe"], graph, "0")
            rs_one = rust_reading(R["exe"], graph, "1")
        except RuntimeError as exc:
            skip("G3 Rust 三态（serve 拉起失败：%s）" % exc)
            ok(False, "G3 前置：rust serve 可应答（fail-closed）", exc)
            return
        ok(rs_unset == rs_zero,
           "G3b Rust 未设读数 == Rust \"0\" 读数（逐位）",
           "%r vs %r" % (rs_unset, rs_zero))
        ok(rs_one != rs_unset,
           "G3c 判别力：Rust \"1\" 态读数 != 未设态读数", "%r vs %r" % (rs_one, rs_unset))
        ok(top1(rs_one) == GOLD,
           "G3d Rust \"1\" 态 top-1 = 中文节点 %s" % GOLD, rs_one[:2])
        ok((score_of(rs_one, GOLD) or 0.0) > (score_of(rs_unset, GOLD) or 0.0),
           "G3e 方向：Rust \"1\" 态 gold 分值 > 未设态 gold 分值",
           "on=%r off=%r" % (score_of(rs_one, GOLD), score_of(rs_unset, GOLD)))
        ok(top1(rs_unset) != GOLD and top1(rs_zero) != GOLD,
           "G3f Rust 未设/\"0\" 态 top-1 != %s（缺省确实关）" % GOLD,
           "unset=%r zero=%r" % (top1(rs_unset), top1(rs_zero)))
        # 跨侧同判（可比口径）：每一态上「该态读数是否等价于本侧开态读数」
        # 必须两侧一致——把两侧各自的判据归到同一布尔面再比，避免拿不同量纲硬比。
        with env_state(None):
            py_unset = py_reading(graph, EN_Q)
        with env_state("0"):
            py_zero = py_reading(graph, EN_Q)
        with env_state("1"):
            py_one = py_reading(graph, EN_Q)
        for label, pr, rr in (("未设", py_unset, rs_unset),
                              ("\"0\"", py_zero, rs_zero),
                              ("\"1\"", py_one, rs_one)):
            py_eq_on = (pr == py_one)
            rs_eq_on = (rr == rs_one)
            ok(py_eq_on == rs_eq_on,
               "G3g 跨侧同判[%s]：Python 等价于开态=%s == Rust 等价于开态=%s"
               % (label, py_eq_on, rs_eq_on),
               "py=%r rs=%r" % (pr, rr))
        # 跨侧同判（判据面）：Python 开关判据的三态 == Rust 开态等价的补
        with env_state(None):
            py_on_unset = UU().unify_on()
        with env_state("0"):
            py_on_zero = UU().unify_on()
        with env_state("1"):
            py_on_one = UU().unify_on()
        ok((py_on_unset, py_on_zero, py_on_one) == (False, False, True),
           "G3h Python 判据三态 = (未设 False, \"0\" False, \"1\" True)",
           (py_on_unset, py_on_zero, py_on_one))
        ok(py_on_one is True and rs_one != rs_unset,
           "G3i 两侧对「显式 \"1\" 即开」同判（Python 判据 True / Rust 读数与未设态不同）",
           "rs one=%r unset=%r" % (rs_one, rs_unset))
    finally:
        _cleanup(root)


# ================================================================ G4 结构面
def g4():
    print("== G4 结构面：两侧判据落点锚点、接线三处、开关未删 ==")
    usrc = _read(U["unify"])
    # 锚点取**代码行**（行首缩进 + return）而非裸表达式：后者在 unify.py 的 CCG
    # 注释里同样出现过一次，裸串锚点会被注释「掩护」——定点变异若只替换注释那处，
    # 代码不动、本断言仍绿（假红/假绿都由此而来，2026-09-30 实测踩过）。
    ok('\n    return os.environ.get("MDCG_UNIFY_QUERY", "0") == "1"' in usrc,
       "G4a Python 判据落点锚点在位（代码行级）：缺省 \"0\" 且仅 \"1\" 为真")
    ok(old_default(usrc) is False,
       "G4b Python 侧无「缺省 \"1\"」残留（防回退）")
    ok("默认关" in usrc,
       "G4c unify.py 头注写明缺省关（文书锚点——M1/M2 不变红：它钉的是注释文本）")
    rsrc = _read(RS["src"])
    ok('.as_deref() != Ok("1")' in rsrc,
       "G4d Rust 判据落点锚点在位：未设/非 \"1\" → 不载入（唯一开态 \"1\"）")
    ok('unwrap_or(false)' not in rsrc.split("pub fn from_env")[1].split("pub fn")[0],
       "G4e Rust from_env 内无「未设=开」旧形态（unwrap_or(false) 已移除）")
    ok("缺省由「未设=开」翻为「未设=关」" in rsrc,
       "G4f atoms.rs 头注写明缺省翻转与三态表（文书锚点——M2 不变红：钉的是注释）")
    # 三处 search 入口接线仍在（接线缺失 → 开关形同虚设；同理为防回退锚点）
    mdcg_src = _read(_MDCG_PY)
    ok(mdcg_src.count("q = unify_query(q)") >= 1,
       "G4g md_cg/mdcg.py search 入口仍接线 unify_query（防回退锚点）",
       mdcg_src.count("q = unify_query(q)"))
    mdcos_src = _read(_MDCOS_PY)
    ok(mdcos_src.count("q = unify_query(q)") >= 2,
       "G4h md_cg/mdcos.py search/search_rrf 两入口仍接线 unify_query（防回退锚点）",
       mdcos_src.count("q = unify_query(q)"))
    hc = _read(_HOTCACHE_PY)
    ok('"MDCG_UNIFY_QUERY"' in hc and re.search(
        r"_ENV_SWITCHES = \([^)]*\"MDCG_UNIFY_QUERY\"", hc) is not None,
       "G4i 开关仍登记在 hotcache._ENV_SWITCHES（跨口径缓存键不得漏登；防回退锚点）")


# ================================================================ 变异表
# 每条 = (名称, 目标, 源码锚点, 替换文本, **预期转红条数**, 是否重建 Rust 二进制)。
# 锚点必须逐字命中当前源码（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）；
# 红项数必须**恰好**等于预期（多红=判据越界、少红=判据空转，两种都判失败）。
# 预期值的由来：本机实测（2026-09-30），红项名录见 --mutate 输出。
#
# 覆盖映射（哪条变异打红哪一面）：
#   M1 → G0？否（G0d/G0e 是**工作区**前置，刻意不被变异弄红）
#        G1a/G1d/G1g/G1h（Python 三态与产物）、G2b/G2c/G2e/G2f/G2g（检索读数）、
#        G3g[未设]（跨侧同判）、G3h（Python 判据三态）、G4a/G4b（Python 判据锚点）
#   M2 → G3b/G3c/G3e/G3f/G3g[未设]/G3i（Rust 读数与跨侧同判）、
#        G4d/G4e（Rust 判据锚点，读**变异副本**源码）
# **文书/接线类锚点不被这两条变异弄红**（它们钉的是注释文本与接线，不是开关判据
# 本身）：G4c（头注「默认关」）、G4f（atoms.rs 头注三态表）、G4g/G4h（三处接线）、
# G4i（hotcache 环境开关登记）。它们是**防回退锚点**，钉错即 G4 直接红——
# 其效力由「实现漂移即红」保证，不由变异证明。
_MUTATIONS = (
    ("M1 Python 缺省改回 \"1\"（缺陷形态：未设=开）",
     "py",
     '\n    return os.environ.get("MDCG_UNIFY_QUERY", "0") == "1"',
     '\n    return os.environ.get("MDCG_UNIFY_QUERY", "1") == "1"',
     13,
     False),
    ("M2 Rust 三态改回「未设=开」（缺陷形态）",
     "rs",
     'if std::env::var("MDCG_UNIFY_QUERY").as_deref() != Ok("1") {\n'
     '            return None; // 未设（缺省关）/ 显式 "0" / 非 "1"：归一层不生效\n'
     '        }',
     'if std::env::var("MDCG_UNIFY_QUERY").map(|v| v == "0").unwrap_or(false) {\n'
     '            return None; // 未设=开（缺陷形态）\n'
     '        }',
     8,
     True),
)


def _write_mutated(src, old, new, tag):
    """把 src 做定点文本替换后写入**守卫临时目录**；锚点未命中返回 (None, src)。"""
    if old not in src:
        return None, src
    path = os.path.join(_TMP, "mut_%s.py" % tag)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))
    return path, src


def _rust_mutation_exe(mut_rs_src):
    """把变异后的 atoms.rs 写进**rust 目录的临时副本**、以临时 CARGO_TARGET_DIR
    重建 release 二进制，返回 (exe | None, 说明)。副本与构建产物全在临时目录，
    **不碰仓库工作区与仓库 target/**。"""
    cargo = shutil.which("cargo")
    if not cargo:
        return None, "cargo 不在 PATH"
    d = tempfile.mkdtemp(prefix="unifyoff_rust_")
    dst = os.path.join(d, "rust")
    shutil.copytree(_RUST_DIR, dst, ignore=shutil.ignore_patterns("target"))
    with open(os.path.join(dst, "src", "atoms.rs"), "w", encoding="utf-8") as f:
        f.write(mut_rs_src)
    tgt = os.path.join(d, "target")
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = tgt
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([cargo, "build", "--release", "--offline"], cwd=dst,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=900)
    exe = os.path.join(tgt, "release", "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")
    if p.returncode != 0 or not os.path.isfile(exe):
        return None, "cargo build rc=%s：%s" % (p.returncode, (p.stderr or "")[-400:])
    return exe, "临时副本重建 rc=0"


# 生效条件：无参；按当前 U 表**重新装载** Python 判据（变异模式 = 临时副本，
# 正向 = 工作区源），随后跑全部断言组（G0–G4），清空并重填 _PASS/_FAIL/_SKIP，
# 返回失败条数。装载必须在组内**每次**重做：否则变异只对 g0 的结构断言可见，
# 行为类断言仍吃旧模块 = 假自证。
def _run_groups():
    install_unify(U["unify"])
    _PASS.clear()
    _FAIL.clear()
    _SKIP.clear()
    for g in (g0, g1, g2, g3, g4):
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%r" % (g.__name__, exc))
    return len(_FAIL)


def _mutate_mode(list_only=False):
    print("!! 定点变异自证：把修复点改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, _kind, old, new, exp, rebuild in _MUTATIONS:
            print("  %-46s expect_red=%s rebuild_rust=%s" % (name, exp or "自校准", rebuild))
        return 0

    anchor_miss = []
    bad = []

    # ---- 基线（未变异）：必须全绿，且以此校准每条变异的预期红项数 ----
    U["unify"] = _UNIFY_PY
    R["exe"] = _EXE
    install_unify(_UNIFY_PY)
    with contextlib.redirect_stdout(buf := io.StringIO()):
        clean = _run_groups()
    clean_detail = buf.getvalue()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败：%s"
                   % [l for l in clean_detail.splitlines() if "FAIL" in l][:4])

    for name, kind, old, new, expect, rebuild in _MUTATIONS:
        if kind == "py":
            live_src = _read(_UNIFY_PY)
            path, _ = _write_mutated(live_src, old, new, "unify_default")
            if path is None:
                print("  ANCHOR-MISS %s —— 锚点在 md_cg/semantic/unify.py 当前源码里"
                      "找不到（实现改了却没同步本表；基线不得静默漂移）" % name)
                anchor_miss.append(name)
                continue
            U["unify"] = path
            try:
                with contextlib.redirect_stdout(buf := io.StringIO()):
                    fails = _run_groups()
                detail = buf.getvalue()
            finally:
                U["unify"] = _UNIFY_PY
                install_unify(_UNIFY_PY)
        else:
            live_src = _read(_ATOMS_RS)
            if old not in live_src:
                print("  ANCHOR-MISS %s —— 锚点在 rust/src/atoms.rs 当前源码里找不到"
                      "（实现改了却没同步本表；基线不得静默漂移）" % name)
                anchor_miss.append(name)
                continue
            exe, note = _rust_mutation_exe(live_src.replace(old, new, 1))
            if exe is None:
                print("  重建失败 %s：%s" % (name, note))
                bad.append("%s（Rust 变异二进制重建失败：%s）" % (name, note))
                continue
            # 结构锚点（G4d/G4e）读**实际生效的源**：变异模式下指向本副本，
            # 否则「Rust 判据锚点」类断言对变异永久无感（假守卫形态）。
            mut_rs = os.path.join(_TMP, "mut_atoms.rs")
            with open(mut_rs, "w", encoding="utf-8") as f:
                f.write(live_src.replace(old, new, 1))
            R["exe"] = exe
            RS["src"] = mut_rs
            try:
                with contextlib.redirect_stdout(buf := io.StringIO()):
                    fails = _run_groups()
                detail = buf.getvalue()
            finally:
                R["exe"] = _EXE
                RS["src"] = _ATOMS_RS
            print("  （%s：%s）" % (name, note))
        red = [l.strip()[5:] for l in detail.splitlines() if l.strip().startswith("FAIL ")]
        verdict = ("红（恰好命中预期）" if fails == expect
                   else ("**仍全绿 = 该判据空转**" if fails == 0
                         else "**红项数不符**（多红=判据越界 / 少红=判据空转）"))
        mark = "OK  " if fails == expect else "MISMATCH"
        print("  %s %-46s 红项=%d 预期=%d  %s" % (mark, name, fails, expect, verdict))
        for l in red:
            print("        " + l)
        if fails != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, fails, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红）" if not bad
                                   else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup(_TMP)
    if not os.path.isfile(_EXE):
        print("!! rust release 二进制缺失：%s" % _EXE)
        print("   修复：cd rust && cargo build --release")
        print("   处置：**fail-closed**（本守卫不计通过、直接退出 1；"
              "不采用静默 SKIP 而返回 0——跑不起来永远不等于通过）")
        return 1
    try:
        install_unify(_UNIFY_PY)
        n_fail = _run_groups()
        print("\nUNIFY-DEFAULT-OFF 守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n_fail, len(_SKIP)))
        return 0 if not n_fail else 1
    finally:
        _cleanup(_TMP)


if __name__ == "__main__":
    sys.exit(main())
