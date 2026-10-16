# -*- coding: utf-8 -*-
# 功能名：洞察 write 点的索引条目门控键子集守卫（issue #416，「手写键子集」族）
# 生效条件：python -X utf8 -m md_cg.test_issue416_entry_key_subset [--mutate]；被测面=md_cg/insight.py 的 verify 索引同步段 + mdcg.MdCG._node_entry 真源 + md_cg 内「索引条目直接键写入」枚举面
# 子功能：A=端到端（盘面 vs 判据面 vs 删除闸 + **新实例重扫后仍成立**）；B=真源子集与写点专有键；C=全仓「索引条目直接键写入点」枚举 + **双向登记**；E=枚举完备性自证（_guard_kit 骨架①）；R=回退即绿自证（_guard_kit 骨架②）
# 执行：--mutate 时先跑双向定点变异，再跑 _guard_kit 的回退即绿自证（实跑，不接受推演）
# 验证方式：全部 PASS 即通过（断言总数 >= FLOOR）；--mutate 下每条变异的指定命中须与预期一致、回退后红项集合须恰为 {"A02","A05","C02"}
# 不适用条件：不判「写点是否该覆盖全部真源键」（本守卫只钉门控标记子集与写点专有键）；不判 protect._fm 的回退策略本身（N213 面）；C 组枚举规则按「同一函数内经含 nodes 的取值取得的条目上的字符串常量下标赋值」——**不覆盖跨函数中转/别名**（该形态由 E 组合成样本显式钉住「必须命中」，故不是静默盲区）
"""issue #416 守卫：写「带门控标记的节点条目」的写点必须携带门控标记键集。

病象（修前实测，见 A 组读数）：insight.verify 写盘后**手写 3 键**同步索引条目
（importance/tags/insight_state），而 fm 刚写下的 protected=True /
protection_reason="insight_verified" **没有**同步 ⇒ protect._fm 对非受保护层不回退
读文件（N213 逐字）⇒ 条目里的 None 被当「未标记」采信 ⇒ 盘面写着 protected: true 的
节点被判 (False, '')，cg.forget **无需 override 即软删**（零前像、零保护审计行），
且跨重启存活。

修法（#192 同款）：**用真源重建整条 entry**（mdcg.MdCG._node_entry，自述唯一真源）
+ 叠加写点专有键（insight_state）→ cg._stage（索引写入单点）。手写子集无论 3 键还是
4 键都只是「下一次漏」的形态；真源加键则本写点自动跟上。
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile

_SB = tempfile.mkdtemp(prefix="i416_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SB
os.environ["MDCG_ROOT"] = os.path.join(_SB, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes as am, insight, nodefile, protect   # noqa: E402
os.environ[am.AUTONOMY_ENV_KEYS["mode"]] = "full"
from .mdcos import MdCGSecure                                    # noqa: E402
from .security import Principal                                  # noqa: E402
import md_cg._guard_kit as _kit                                  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 14
PASS, FAIL = 0, 0
FAILS = []
_KEK = os.urandom(32)

#: 门控标记键集：取自仓内**判据面单点** protect._GATE_UNKNOWN_KEYS（3 键）
#: ∪ 其配对的原因键。不另起一份字面量表。
_GATE_KEYS = set(protect._GATE_UNKNOWN_KEYS) | {"protection_reason"}


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:240])


def _mk(tag):
    return MdCGSecure(os.path.join(_SB, "lib_" + tag),
                      principal=Principal(tenant="t1", actor="alice",
                                          role="designer", clearance="secret",
                                          can_write=True, can_admin=True),
                      master_key=_KEK)


def _probe(tag, src):
    """跑一次 #416 链路：record → verify → 读盘面/索引 → forget（不传 override）。"""
    cg = _mk(tag)
    rec = insight.record(cg, statement="416 守卫探针 " + tag,
                         conditions={"device": "x"}, importance=0.9,
                         importance_source=src, actor="probe")
    nid = rec["node_id"]
    r = insight.verify(cg, nid, verdict="verified",
                       evidence=[{"type": "V3", "ref": "probe", "note": "x"}],
                       actor="probe")
    e = cg.index["nodes"].get(nid)
    fm = {}
    if e:
        with io.open(cg._node_disk_path(e), encoding="utf-8") as f:
            fm, _c = nodefile.loads(f.read())
    try:
        out = cg.forget(nid)
        forgotten = ("ok", out)
    except Exception as ex:                                      # noqa: BLE001
        forgotten = (type(ex).__name__, None)
    return cg, nid, r, e, fm, forgotten


print("== A 组：端到端（盘面 vs 判据面 vs 删除闸 + 新实例重扫）==")

_CG, _NID, _R, _ENT, _FM, _FORG = _probe("heur", "heuristic")
_check("A01 前置：verify 回执 ok（链路真的跑到落盘）", _R.get("ok") is True, _R)
_check("A02 ★盘面与索引**逐位一致**：索引里的门控标记不再是 None"
       "（修前 盘面 protected=True / 索引 protected=None）",
       _ENT.get("protected") is True
       and _ENT.get("protection_reason") == _FM.get("protection_reason") == "insight_verified",
       {"盘面": (_FM.get("protected"), _FM.get("protection_reason")),
        "索引": (_ENT.get("protected"), _ENT.get("protection_reason"))})
_check("A03 ★判据面采信盘面：protect.is_protected 判为受保护（修前 (False, '')）",
       protect.is_protected(_CG, _NID)[0] is True, protect.is_protected(_CG, _NID))
_check("A04 ★删除闸收口：cg.forget 不传 override 必须**拒绝**（修前成功并生成墓碑）",
       _FORG[0] == "ProtectionError", _FORG)
_CG_D, _NID_D, _R_D, _ENT_D, _FM_D, _FORG_D = _probe("dflt", None)
_check("A04 对照组（importance_source=缺省）：同样受保护、同样拒绝删除"
       "（证明修复不是「把所有节点都判保护」的过度收紧）",
       _ENT_D.get("protected") is True and _FORG_D[0] == "ProtectionError",
       (_ENT_D.get("protected"), _FORG_D[0]))
_CG_D.close()

# ★「只在同一进程内成立的判据」样本（Lead 点名 / #417 教训同源）：
#   重新装载实例（走快照+日志、不 rebuild_index）后，索引里的门控标记必须**仍在**。
_CG.flush()
_CG2 = _mk("heur")                       # 同一 root 重新装载
_E2 = _CG2.index["nodes"].get(_NID)
_check("A05 ★新实例重扫后仍成立：重新装载的实例里门控标记仍在（不是同进程内存假绿）",
       bool(_E2) and _E2.get("protected") is True
       and protect.is_protected(_CG2, _NID)[0] is True,
       {"新实例索引": (_E2 or {}).get("protected"),
        "is_protected": protect.is_protected(_CG2, _NID)})
try:
    _CG2.forget(_NID)
    _F2 = ("ok", None)
except Exception as _ex:                                    # noqa: BLE001
    _F2 = (type(_ex).__name__, None)
_check("A05 反向：新实例的 forget 同样被拒（契约跨重启成立，不是同进程内存侥幸）",
       _F2[0] == "ProtectionError", _F2)
_CG.close()
_CG2.close()
# ---------------------------------------------------------------- B 组：真源子集与写点专有键
print("")
print("== B 组：真源子集 / 写点专有键 ==")

_check("B01 ★写点键集 ⊇ 门控标记键集（判据面单点 protect._GATE_UNKNOWN_KEYS + 原因键）",
       _GATE_KEYS <= set(_ENT), sorted(_GATE_KEYS - set(_ENT)))

_ISO = McdCGish = None
try:
    _REBUILT = _CG._node_entry(_CG._node_disk_path(_ENT),
                              _FM.get("layer"), _FM, _FM.get("__content__") or "")
except Exception:                                                # noqa: BLE001
    _REBUILT = None
_check("B02 前置：真源 _node_entry 可复算（判据有效）",
       isinstance(_REBUILT, dict) and _GATE_KEYS <= set(_REBUILT),
       type(_REBUILT).__name__)

# 写点专有键**双向**：写点条目 == 真源条目 ∪ 专有键集（多一个少一个都红）
_OWN = {"insight_state"}
_check("B02 ★写点条目 == 真源条目 ∪ 写点专有键（双向：多/少都红）",
       isinstance(_REBUILT, dict)
       and set(_ENT) == (set(_REBUILT) | _OWN)
       and (set(_ENT) - set(_REBUILT)) == _OWN,
       {"多出": sorted(set(_ENT) - set(_REBUILT) - _OWN),
        "缺失": sorted(set(_REBUILT) - set(_ENT))})

_INS_SRC = io.open(os.path.join(_REPO, "md_cg", "insight.py"),
                   encoding="utf-8", newline="").read()
_check("B03 机械证据：insight.py 的 verify 段调用真源 _node_entry 与索引写入单点 _stage",
       "_node_entry(" in _INS_SRC and "cg._stage(" in _INS_SRC,
       "未见 _node_entry/_stage ⇒ 可能又退回手写键子集")


# ---------------------------------------------------------------- C 组：枚举 + 双向登记
print("")
print("== C 组：全仓「索引条目直接键写入点」枚举 + 双向登记 ==")

_GATE_FM_ASSIGN = tuple(_GATE_KEYS)


def _violations(texts):
    """枚举逻辑：**同一函数内「fm 新落门控标记」却只对索引条目补非门控键**的写点。

    判据（#416 的不变量）：凡在函数内把门控标记写进 fm（`fm["protected"] = ...` 一类）、
    又对索引条目做字符串常量键赋值的写点，必须**携带该门控标记**——要么由真源
    `_node_entry` 重建整条条目，要么把标记键一并写进条目。只补非门控键 ⇒ 命中
    （这正是 insight.verify 修前的形态：盘面 protected=True、条目 None）。
    """
    bad = []
    for rel, src in texts.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            sets_gate = False
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if (isinstance(t, ast.Subscript)
                                and isinstance(t.slice, ast.Constant)
                                and t.slice.value in _GATE_FM_ASSIGN):
                            sets_gate = True
            if not sets_gate:
                continue
            entry_names = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and _has_nodes(n.value):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            entry_names.add(t.id)
            if not entry_names:
                continue
            if "_node_entry(" in ast.unparse(fn):
                continue                       # 由真源重建 ⇒ 门控键随真源走
            wrote = []
            opaque = 0
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if (isinstance(t, ast.Subscript)
                                and isinstance(t.value, ast.Name)
                                and t.value.id in entry_names):
                            if (isinstance(t.slice, ast.Constant)
                                    and isinstance(t.slice.value, str)):
                                wrote.append(t.slice.value)
                            else:
                                opaque += 1      # 键非常量 ⇒ 枚举不到，不得静默放行
            # 键非常量**且**该函数也没写门控键 ⇒ 不可枚举，必须命中；
            # 写了门控键的（如 forgetting.reinforce）不属本类，不判。
            if opaque and not (_GATE_KEYS & set(wrote)):
                bad.append((rel, fn.name, "条目键非常量（不可枚举）×%d" % opaque))
                continue
            if wrote and not (_GATE_KEYS & set(wrote)):
                bad.append((rel, fn.name, sorted(set(wrote))[:6]))
    return bad


def _has_nodes(node):
    """该表达式是否取自「节点索引」——**两种取值形态都要认**：
    `cg.index["nodes"]`（下标）与 `....get("nodes", {})`（.get）。
    只认下标会漏掉 insight 修前的形态（它用的正是 .get("nodes")）——
    E 组样本①就是钉这一点的。"""
    for n in ast.walk(node):
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and n.slice.value == "nodes"):
            return True
        if isinstance(n, ast.Call) and any(
                isinstance(a, ast.Constant) and a.value == "nodes" for a in n.args):
            return True
    return False


def _md_cg_sources():
    out = {}
    for root, dirs, names in os.walk(os.path.join(_REPO, "md_cg")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "jobs", "target")]
        for n in names:
            if n.endswith(".py") and not n.startswith("test_"):
                p = os.path.join(root, n)
                out[os.path.relpath(p, _REPO).replace(os.sep, "/")] = io.open(
                    p, encoding="utf-8").read()
    return out


_VIOL = _violations(_md_cg_sources())
_check("C01 ★全仓枚举：无「新落门控标记却只补非门控键」的写点（insight 修后为 0）",
       not _VIOL, _VIOL)

# —— 双向登记：把**枚举到的全部**索引条目直接键写入点登记在案 ——
#: （文案见下方 _REG_WHY：本批**只枚举不改**——它们的键都不是门控标记，
#:   且条目在创建时已由真源带上门控键；本次登记只保证「新增/删除点会被看见」。）
_REGISTERED = {
    # 本批**只枚举不改**：这些写点写的键都不是门控标记（或像 forgetting.reinforce
    # 那样自己就带门控键），且条目在创建时已由真源 _node_entry 带上门控键。
    # 登记的目的是「新增/删除点必须被看见」——双向核对见 C02 两条。
    ("md_cg/bench_bm25_blockmax.py", "first"),
    ("md_cg/forgetting.py", "importance"),
    ("md_cg/forgetting.py", "merge_source_ids"),
    ("md_cg/forgetting.py", "merge_sources"),
    ("md_cg/forgetting.py", "protected"),
    ("md_cg/forgetting.py", "protection_reason"),
    ("md_cg/mdcg.py", "_fingerprint"),
    ("md_cg/mdcg.py", "bucket_scope"),
    ("md_cg/mdcg.py", "buckets"),
    ("md_cg/mdcg.py", "ccg_by_layer"),
    ("md_cg/mdcg.py", "content_hash"),
    ("md_cg/mdcg.py", "edges"),
    ("md_cg/mdcg.py", "evidence_count"),
    ("md_cg/mdcg.py", "neg_memory_counts"),
    ("md_cg/mdcg.py", "quarantined"),
    ("md_cg/mdcg.py", "skipped_unreadable"),
    ("md_cg/mdcg.py", "subgraph"),
    ("md_cg/mdcg.py", "tags"),
    ("md_cg/mdcg.py", "total_nodes"),
    ("md_cg/mdcos.py", "duty"),
    ("md_cg/mdcos.py", "forbidden"),
    ("md_cg/mdcos.py", "role"),
    ("md_cg/mdcos.py", "role_label"),
    ("md_cg/mdcos.py", "sensitivity"),
    ("md_cg/mdcos.py", "session"),
    ("md_cg/writelimit.py", "merge_sources"),
}
_observed = set()
for rel, src in _md_cg_sources().items():
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and _has_nodes(n.value):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
        if not names:
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.value, ast.Name)
                            and t.value.id in names
                            and isinstance(t.slice, ast.Constant)
                            and isinstance(t.slice.value, str)):
                        _observed.add((rel, t.slice.value))
print("  【枚举到】%s" % sorted(_observed))
_check("C02 ★双向登记（一）：枚举到的写点 ⊆ 登记表（新增点未登记即红）",
       _observed <= _REGISTERED, sorted(_observed - _REGISTERED))
_check("C02 ★双向登记（二）：登记表 ⊆ 枚举到的写点（点被删/改名后不撤登记即红）",
       _REGISTERED <= _observed, sorted(_REGISTERED - _observed))
# ---------------------------------------------------------------- E 组：枚举完备性自证
print("")
print("== E 组：枚举完备性自证（_guard_kit 骨架①）==")

_S_PREFIX = "def verify(cg, node_id, fm, node):\n"
_S_GATE = '    fm["protected"] = True\n    fm["protection_reason"] = "insight_verified"\n'
_S_ENT = '    ent = (cg.index or {}).get("nodes", {}).get(node_id)\n'
_SAMPLES = [
    ("①修前 insight 形态（落门控标记后只补非门控键、无真源重建）",
     _S_PREFIX + _S_GATE + '    cg._write_node(node_id, node["path"], fm, "c")\n'
     + _S_ENT + '    if isinstance(ent, dict):\n'
     '        ent["importance"] = fm.get("importance")\n'
     '        ent["tags"] = []\n        ent["insight_state"] = "verified"\n',
     True, "synthetic/old_insight.py"),
    ("②修后形态（真源重建整条条目）——不得误判",
     _S_PREFIX + _S_GATE + '    cg._write_node(node_id, node["path"], fm, "c")\n'
     '    ent = cg._node_entry(node["path"], fm.get("layer"), fm, "c")\n'
     '    ent["insight_state"] = "verified"\n',
     False, "synthetic/new_insight.py"),
    ("③只落 fm 门控标记、根本不碰索引（不是条目写点）——不得误判",
     _S_PREFIX + _S_GATE + "    return fm\n", False, "synthetic/no_entry.py"),
    ("④索引写入**带**门控键（合法）——不得误判",
     _S_PREFIX + _S_GATE + _S_ENT + '    if isinstance(ent, dict):\n'
     '        ent["protected"] = True\n        ent["protection_reason"] = "x"\n'
     '        ent["tags"] = []\n',
     False, "synthetic/ok_gate.py"),
    ("⑤无门控标记的普通条目补丁（合法）——不得误判",
     "def patch(cg, node_id):\n"
     '    ent = (cg.index or {}).get("nodes", {}).get(node_id)\n'
     '    ent["tags"] = []\n',
     False, "synthetic/plain.py"),
    ("⑥条目键**非常量**（枚举不到 ⇒ 必须命中，不得静默放行）",
     _S_PREFIX + _S_GATE + _S_ENT + '    if isinstance(ent, dict):\n'
     "        ent[_K] = 1\n",
     True, "synthetic/opaque_key.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_violations, _SAMPLES)
_check("E01 ★枚举完备性自证：%d 类形态（修前形态/修后形态/非写点/带门控键/普通补丁/不可枚举键）"
       "喂同一条枚举逻辑，命中与否须全符预期" % len(_SAMPLES), _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR —— 探针面疑似失效（防假绿）")
if FAILS:
    print("issue #416 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #416 结果：全部通过")


# ---------------------------------------------------------------- 镜像树 / 变异 / 回退
_MIRROR_DIRS = ("md_cg", "data", "scripts")
_MIRROR_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                                      "node_modules")
_TARGET = "md_cg/insight.py"

_MUTATIONS = (
    ("V1 覆盖方向：写点退回手写 3 键（#416 形态回归）",
     '    _ent = cg._node_entry(_disk, fm.get("layer"), fm, _content)',
     '    _ent = cg.index["nodes"].get(node_id) or {}'),
    ("V2 过度收紧方向：把门控键集判据放宽成「任何键都算」（写点空转）",
     '       _GATE_KEYS <= set(_ENT), sorted(_GATE_KEYS - set(_ENT)))',
     '       bool(set(_ENT)), "")'),
    ("V3 登记方向：撤掉一条已登记的写点（双向核对失守）",
     '    ("md_cg/writelimit.py", "merge_sources"),',
     '    ("md_cg/writelimit.py", "merge_sources_UNREGISTERED"),'),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i416_mut_")
    for name in _MIRROR_DIRS:
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=_MIRROR_SKIP)
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _fold(text, eol):
    return text.replace("\r\n", "\n").replace("\n", eol)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue416_entry_key_subset"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


def _apply(tree, rel, old, new):
    p = os.path.join(tree, rel.replace("/", os.sep))
    with io.open(p, encoding="utf-8", newline="") as f:
        t = f.read()
    eol = "\r\n" if "\r\n" in t else "\n"
    o, n = _fold(old, eol), _fold(new, eol)
    if t.count(o) != 1:
        return None, "锚点命中 %d 次" % t.count(o)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t.replace(o, n, 1))
    return t, ""


def _mutate():
    print("!! 双向定点变异自证（镜像树）")
    tree = _mirror_build()
    bad = 0
    try:
        rc0, reds0, out0 = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc0, len(reds0)))
        if rc0 != 0 or reds0:
            bad += 1
            print("\n".join(out0.splitlines()[-20:]))
        for desc, old, new, exp in _MUTATIONS:
            bak, why = _apply(tree, _TARGET, old, new)
            if bak is None:
                bad += 1
                print("  ANCHOR-MISS %s —— %s" % (desc, why))
                continue
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(os.path.join(tree, _TARGET.replace("/", os.sep)),
                         "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and all(e in hit for e in exp):
                print("  OK   %s  红项=%d 命中=%s" % (desc, len(reds2), hit))
            else:
                bad += 1
                print("  MISMATCH %s  实际红项=%s  期望含=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    return bad


#: **回退即绿自证**（_guard_kit 骨架②）：把 #416 的修复**整批**回退一次（写点退回
#: 手写 3 键同步），实跑守卫看红项集合 —— **不接受推演**。回退必须是**本批全部**改动
#: （Lead 口径）：这里只有一处实现改动，故一条即整批。
_REVERT = [
    ("md_cg/insight.py",
     '    _ent = cg._node_entry(_disk, fm.get("layer"), fm, _content)\n'
     '    # 写点专有键：真源不含它，重建后叠加（不是「凭记忆补几键」）。\n'
     '    _ent["insight_state"] = final',
     '    _ent = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)\n'
     '    if isinstance(_ent, dict):\n'
     '        _ent["importance"] = fm.get("importance")\n'
     '        _ent["tags"] = list(tg)\n'
     '        _ent["insight_state"] = final'),
]


def _revert_proof():
    print("!! 回退即绿自证（_guard_kit.assert_revert_reddens，实跑）")
    _ok, _det = _kit.assert_revert_reddens(
        _mirror_build, _REVERT, _run_in,
        tuple(["A02", "A03", "A04", "A05", "B01", "B02"]), "?")
    print("  %s 红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
    if not _ok:
        print("  不合格：" + str(_det)[:600])
    return 0 if _ok else 1


def main():
    bad = 0
    if "--mutate" in sys.argv:
        bad += _mutate()
        if bad == 0:
            bad += _revert_proof()
    return 1 if (FAILS or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
