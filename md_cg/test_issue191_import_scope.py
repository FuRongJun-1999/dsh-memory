# -*- coding: utf-8 -*-
"""对端证据包导入不得自选保护级 / 旧包不得回滚新证据（issue #191）守卫。

【守什么】
  1. 导入对端包时，条目的 layer / importance **不能**由包内字段决定本根的保护级：
     落层只允许 IMPORT_LAYERS，重要度夹到 IMPORT_IMPORTANCE_MAX 以下；
  2. 同一对端的**旧包**不得覆写较新的已导入内容（含属主删除后重放复活）；
  3. 同 id 的**本地**节点不得被外来包覆写；
  4. 判定面本身不得被放宽（白名单/上限/阈值是标定值，不是随便填的数）。

病灶（修前，issue #191 声明，本席已在真 main 基线独立复现 3/3）：
  · `import_pack` 把条目自带的 layer/importance 原样交给 `identity.observe(...,
    override=True)` ⇒ 对端可让节点落进 anchor/self（`protect.PROTECTED_LAYERS`）
    或把 importance 顶到 >= 0.7（`protect.AUTO_PROTECT_IMPORTANCE`），落到本根
    即**不可遗忘**，属主 `mdcg_forget` 被 ProtectionError 拒绝，而返回体只说
    `imported: N`；
  · 导入全程不读包级 `created_at` ⇒ 同一对端较早签出的旧包可把较新证据覆写回旧
    内容，属主删掉导入节点后重放同一包又会写回；开 `require_peer_signature` +
    `on_verify_fail=reject` 也挡不住（旧包本来就合法）。

修法（本件，只改 `md_cg/evidence.py`）：
  · 常量 `IMPORT_LAYERS = ("knowledge", "contextual")`、
    `IMPORT_IMPORTANCE_MAX = 0.5`（严格小于 `AUTO_PROTECT_IMPORTANCE` 0.70）、
    `SEEN_FILE = "_xnode_seen.json"`；
  · `_import_importance(raw)`：bool/None/非数值/非有限 ⇒ 上限；否则按 float 夹到
    `[0, IMPORT_IMPORTANCE_MAX]`（bool 是 int 子类，`True == 1` 不特判就会顶到保护线）；
  · 包级 `created_at` 必须是可用的有限数值（缺省 0.0，非法值整包拒收并留痕）；
  · 本根 `<root>/_xnode_seen.json` 记每个 xnode 最后一次写入所用包的 created_at，
    `created <= 记录值` ⇒ 计入 `replayed` 并跳过（**包括属主删除之后**）；
  · 目标已存在且不带 `xnode:cross` 标签 ⇒ 计入 `foreign` 并跳过（`accept.py D7`）；
  · 返回体新增 `clamped` / `replayed` / `foreign` 三键（此前只有 `imported: N`）。

判据 S1…S10（共 30 条）：
  S1 常量与判定面标定（白名单/上限/阈值/单一权威）
  S2 ★ 落层白名单：anchor/self 一律改落 knowledge 并计入 clamped
  S3 ★ 重要度夹取：1.0 / 0.9 / True / "high" / 负数 / 非有限 ⇒ 全部 <= 0.5
  S4 ★ 端到端：导入后属主可遗忘（修前 ProtectionError）
  S5 ★ 旧包重放不得覆写新内容（正向）
  S6 ★ 属主删除后重放同一旧包不得复活（反面）
  S7 ★ created_at 非法/缺失的包不得覆写（fail-closed：只能新建）
  S8 同 id 本地节点不得被外来包覆写（foreign）
  S9 既有语义不破：新包正序仍可更新、正常包不含 clamped/replayed 噪音
  S10 判别力：从 HEAD 取修复前源原形（无本件标记）自证

运行：
  python -X utf8 -m md_cg.test_issue191_import_scope
  python -X utf8 -m md_cg.test_issue191_import_scope --mutate
"""
import base64 as _b64
import json
import os
import shutil
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i191g_")
for _k, _v in (("HOME", _TMP), ("MDCG_ROOT", os.path.join(_TMP, "root")),
               ("MDCG_AUX_ROOT", os.path.join(_TMP, "auxd")),
               ("MDCG_STATE_ROOT", os.path.join(_TMP, "state")),
               ("MDCG_DATA_ROOT", os.path.join(_TMP, "data")),
               ("MDCG_EXPORT_ROOT", os.path.join(_TMP, "export"))):
    os.environ[_k] = _v
os.environ["MDCG_SWARM_DIR"] = os.path.join(_TMP, "swarm")
os.environ["MDCG_WRITELIMIT"] = "0"
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_SLEEP"] = "0"

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from md_cg import evidence as ev            # noqa: E402
from md_cg import protect as _protect       # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402

_MARK = "issue #191"
_REL = "md_cg/evidence.py"
_OK = []
_BAD = []


def _check(name, cond, detail=""):
    (_OK if cond else _BAD).append(name)
    print("  %s %s  %s" % ("ok  " if cond else "FAIL", name, detail))


def _fresh(tag):
    d = os.path.join(_TMP, "r_" + tag)
    os.makedirs(d, exist_ok=True)
    return MdCGOS(d)


def _pack(from_node, items, *, created_at=1000.0, pack_id="pack-aaaaaaaaaaaa"):
    return {"kind": ev.KIND, "schema": ev.SCHEMA, "pack_id": pack_id,
            "from_node": from_node, "created_at": created_at,
            "items": items, "sig": {"signer": "null", "signature": ""}}


def _item(node_id, text, *, layer=None, importance=None, sens="internal"):
    it = {"node_id": node_id, "subject": "bob", "text": text,
          "sensitivity": sens}
    if layer is not None:
        it["layer"] = layer
    if importance is not None:
        it["importance"] = importance
    return it


def _imp(cg, path):
    return ev.import_pack(cg, path, swarm=os.environ["MDCG_SWARM_DIR"], archive=False)


def _write(pack):
    p = os.path.join(_TMP, "packs", "%s.json" % pack["pack_id"][5:])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False)
    return p


def _fm(cg, xid):
    """节点元数据在 frontmatter 里（cg.get 返回 {id, path, content, frontmatter}）。"""
    n = cg.get(xid) or {}
    return n.get("frontmatter") or {}


def _src_text(cg, xid):
    node = cg.get(xid) or {}
    return (node.get("content") or node.get("text") or "")


def _owner_forget(cg, xid, reason="owner cleanup"):
    """属主遗忘走 cg.forget（identity 模块没有 forget）。"""
    return cg.forget(xid, reason=reason)


def s1():
    src = open(os.path.join(_REPO, _REL), encoding="utf-8").read()
    _check("S1.1 ★ 落层白名单是标定值（knowledge/contextual）",
           ev.IMPORT_LAYERS == ("knowledge", "contextual"), repr(ev.IMPORT_LAYERS))
    _check("S1.2 ★ 重要度上限低于保护线 AUTO_PROTECT_IMPORTANCE",
           0.0 <= ev.IMPORT_IMPORTANCE_MAX < _protect.AUTO_PROTECT_IMPORTANCE,
           "上限=%r 保护线=%r" % (ev.IMPORT_IMPORTANCE_MAX,
                                 _protect.AUTO_PROTECT_IMPORTANCE))
    _check("S1.3 已见记录文件名是标定值",
           ev.SEEN_FILE == "_xnode_seen.json", ev.SEEN_FILE)
    _check("S1.4 ★ 单一权威：白名单不另立 protect.PROTECTED_LAYERS 之外的第二份判据",
           "self" not in ev.IMPORT_LAYERS and "anchor" not in ev.IMPORT_LAYERS,
           "PROTECTED_LAYERS=%r" % (_protect.PROTECTED_LAYERS,))
    _check("S1.5 返回体三键在源码中在位",
           all(k in src for k in ('"clamped"', '"replayed"', '"foreign"')))


def s2():
    cg = _fresh("s2")
    p = _write(_pack("peer-a", [_item("o1", "对端说 A", layer="anchor"),
                                   _item("o2", "对端说 B", layer="self")]))
    out = _imp(cg, p)
    l1 = _fm(cg, "xnode_peer-a_o1").get("layer")
    l2 = _fm(cg, "xnode_peer-a_o2").get("layer")
    _check("S2.1 ★ anchor 落层被改判为 knowledge", l1 == "knowledge", str(l1))
    _check("S2.2 ★ self 落层被改判为 knowledge", l2 == "knowledge", str(l2))
    _check("S2.3 改判计入 clamped（两条落层 + 两条重要度）",
           out.get("clamped") == 4, "clamped=%r" % (out.get("clamped"),))
    _check("S2.4 两类条目都真落盘（imported=2）",
           out.get("imported") == 2 and out.get("ok") is True, str(out))


def s3():
    cg = _fresh("s3")
    items = [_item("a", "x1", importance=1.0),
             _item("b", "x2", importance=0.9),
             _item("c", "x3", importance=True),
             _item("d", "x4", importance="high"),
             _item("e", "x5", importance=-3.0)]
    p = _write(_pack("peer-b", items, pack_id="pack-bbbbbbbbbbbb"))
    out = _imp(cg, p)
    got = {k: ev._import_importance(v) for k, v in
           (("1.0", 1.0), ("0.9", 0.9), ("True", True),
            ("high", "high"), ("-3.0", -3.0), ("nan", float("nan")),
            ("None", None))}
    _check("S3.1 ★ 声明 1.0 ⇒ 夹到上限", got["1.0"] == ev.IMPORT_IMPORTANCE_MAX,
           str(got["1.0"]))
    _check("S3.2 ★ 声明 0.9 ⇒ 夹到上限", got["0.9"] == ev.IMPORT_IMPORTANCE_MAX,
           str(got["0.9"]))
    _check("S3.3 ★ 声明 True（bool 是 int 子类）⇒ 夹到上限",
           got["True"] == ev.IMPORT_IMPORTANCE_MAX, str(got["True"]))
    _check("S3.4 ★ 声明非数值字符串 ⇒ 上限（fail-closed）",
           got["high"] == ev.IMPORT_IMPORTANCE_MAX, str(got["high"]))
    _check("S3.5 ★ 声明负数 ⇒ 夹到 0.0", got["-3.0"] == 0.0, str(got["-3.0"]))
    _check("S3.6 ★ 声明 NaN ⇒ 上限（非有限值不得穿透）",
           got["nan"] == ev.IMPORT_IMPORTANCE_MAX, str(got["nan"]))
    _check("S3.7 声明 None ⇒ 上限", got["None"] == ev.IMPORT_IMPORTANCE_MAX,
           str(got["None"]))
    vals = [_fm(cg, "xnode_peer-b_" + k).get("importance")
            for k in ("a", "b", "c", "d", "e")]
    _check("S3.8 ★ 落盘后无一超过保护线",
           all(isinstance(v, (int, float)) and v < _protect.AUTO_PROTECT_IMPORTANCE
               for v in vals), str(vals))


def s4():
    cg = _fresh("s4")
    p = _write(_pack("peer-c", [_item("o1", "对端说 A", layer="anchor",
                                       importance=1.0)],
                     pack_id="pack-cccccccccccc"))
    _imp(cg, p)
    fm = _fm(cg, "xnode_peer-c_o1")
    _check("S4.1 ★ 导入节点落在 knowledge 层", fm.get("layer") == "knowledge",
           str(fm.get("layer")))
    _check("S4.2 ★ 落盘重要度低于自动保护线",
           isinstance(fm.get("importance"), (int, float))
           and fm["importance"] < _protect.AUTO_PROTECT_IMPORTANCE,
           str(fm.get("importance")))
    try:
        _owner_forget(cg, "xnode_peer-c_o1")
        ok = True
        det = "遗忘成功"
    except Exception as e:  # ProtectionError 或其他
        ok = False
        det = "%s: %s" % (type(e).__name__, e)
    _check("S4.3 ★ 属主可遗忘（修前 ProtectionError 拒删）", ok, det)


def s5():
    cg = _fresh("s5")
    v1 = _write(_pack("peer-d", [_item("o1", "bob 可信，开通生产权限")],
                      created_at=1000.0, pack_id="pack-dddddddddddd"))
    v2 = _write(_pack("peer-d", [_item("o1", "bob 账号已失陷，撤销生产权限")],
                      created_at=2000.0, pack_id="pack-eeeeeeeeeeee"))
    _imp(cg, v1)
    first = _src_text(cg, "xnode_peer-d_o1")
    _imp(cg, v2)
    second = _src_text(cg, "xnode_peer-d_o1")
    out3 = _imp(cg, v1)
    third = _src_text(cg, "xnode_peer-d_o1")
    _check("S5.1 新包正序导入生效", "失陷" in second, second.strip())
    _check("S5.2 ★ 旧包重放被拒（replayed=1）", out3.get("replayed") == 1,
           str(out3))
    _check("S5.3 ★ 旧包重放不改内容（仍是新内容）", "失陷" in third,
           third.strip())
    _check("S5.4 旧包重放 imported=0", out3.get("imported") == 0, str(out3))


def s6():
    cg = _fresh("s6")
    v1 = _write(_pack("peer-e", [_item("o1", "bob 可信，开通生产权限")],
                      created_at=1000.0, pack_id="pack-ffffffffffff"))
    _imp(cg, v1)
    before = _src_text(cg, "xnode_peer-e_o1")
    try:
        _owner_forget(cg, "xnode_peer-e_o1")
        forgot = True
    except Exception as e:
        forgot = False
        print("    （遗忘失败：%s: %s）" % (type(e).__name__, e))
    out = _imp(cg, v1)
    after = _src_text(cg, "xnode_peer-e_o1")
    _check("S6.1 属主遗忘动作本身成功", forgot)
    _check("S6.2 ★ 删除后重放同一旧包不得复活", out.get("replayed") == 1,
           str(out))
    _check("S6.3 ★ 删除后仍是墓碑态（不复活）",
           ("bob 可信" not in after), repr(after[:40]))


def s7():
    cg = _fresh("s7")
    good = _write(_pack("peer-f", [_item("o1", "第一版内容")],
                        created_at=5000.0, pack_id="pack-gggggggggggg"))
    _imp(cg, good)
    _check("S7.1 前置：第一版已落盘", "第一版" in _src_text(cg, "xnode_peer-f_o1"))
    no_ts = _write(_pack("peer-f", [_item("o1", "无时间戳的覆写")],
                         created_at=None, pack_id="pack-hhhhhhhhhhhh"))
    out = _imp(cg, no_ts)
    _check("S7.2 ★ 缺 created_at 的包不得覆写（replayed=1）",
           out.get("replayed") == 1, str(out))
    _check("S7.3 ★ 内容仍是第一版", "第一版" in _src_text(cg, "xnode_peer-f_o1"),
           _src_text(cg, "xnode_peer-f_o1").strip())
    bad = _write(_pack("peer-f", [_item("o1", "非法时间戳的覆写")],
                       created_at="昨天", pack_id="pack-iiiiiiiiiiii"))
    out2 = _imp(cg, bad)
    _check("S7.4 ★ created_at 非法 ⇒ 整包拒收且留痕",
           out2.get("ok") is False and "created_at" in (out2.get("reason") or ""),
           str(out2)[:160])
    _check("S7.5 ★ 拒收后内容未被改动",
           "第一版" in _src_text(cg, "xnode_peer-f_o1"))


def s8():
    cg = _fresh("s8")
    cg.add("xnode_peer-g_local", "本根自己写的内容", layer="knowledge")
    p = _write(_pack("peer-g", [_item("local", "外来覆写尝试")],
                     pack_id="pack-jjjjjjjjjjjj"))
    out = _imp(cg, p)
    txt = (cg.get("xnode_peer-g_local") or {}).get("content") or ""
    _check("S8.1 ★ 同名本地节点未被覆写", "本根自己写的内容" in txt, txt.strip())
    _check("S8.2 ★ 计入 foreign 并跳过", out.get("foreign") == 1,
           "foreign=%r" % (out.get("foreign"),))
    _check("S8.3 拒写理由可见",
           any("非跨节点证据" in r for r in (out.get("skipped_reasons") or [])),
           str(out.get("skipped_reasons")))


def s9():
    cg = _fresh("s9")
    v1 = _write(_pack("peer-h", [_item("o1", "第一版")], created_at=1000.0,
                      pack_id="pack-kkkkkkkkkkkk"))
    v2 = _write(_pack("peer-h", [_item("o1", "第二版")], created_at=2000.0,
                      pack_id="pack-llllllllllll"))
    _imp(cg, v1)
    out = _imp(cg, v2)
    _check("S9.1 新包仍可正常更新既有 xnode",
           "第二版" in _src_text(cg, "xnode_peer-h_o1"),
           _src_text(cg, "xnode_peer-h_o1").strip())
    _check("S9.2 正常包不产生 replayed/foreign 噪音",
           out.get("replayed") == 0 and out.get("foreign") == 0, str(out))
    # 条目未声明 importance 时 raw 是 None，落到上限 ⇒ 计一次 clamped（返回体口径：
    # clamped 统计「本根改写了对端声明的保护级」，缺声明也算改写）
    _check("S9.3 未声明 importance 的条目计入 clamped=1", out.get("clamped") == 1,
           "clamped=%r" % (out.get("clamped"),))
    _check("S9.4 归档面未被本件改动（archive=False 时不写收件箱）",
           out.get("archived") == "", repr(out.get("archived")))


def _before_source():
    try:
        out = subprocess.run(["git", "show", "HEAD:" + _REL], cwd=_REPO,
                             capture_output=True, timeout=30)
        if out.returncode == 0:
            src = out.stdout.decode("utf-8", "replace")
            if _MARK not in src:
                return src, "HEAD（本改动尚未提交）"
    except Exception:
        pass
    return None, "HEAD 取不到修复前源（浅克隆？）"


def s10():
    src, how = _before_source()
    if src is None:
        _check("S10a 修复前源可得", False, how)
        _check("S10b 修复前无落层白名单", False, how)
        _check("S10c 修复前条目层原样落盘（可落 anchor）", False, how)
        return
    print("    （修复前源取自 %s）" % how)
    _check("S10a ★ 修复前无 IMPORT_LAYERS 白名单", "IMPORT_LAYERS" not in src)
    _check("S10b ★ 修复前无 created_at 版本闸", "replayed" not in src
           and "_xnode_seen" not in src)
    _check("S10c ★ 修复前的落层写法确是「原样透传」（layer=it.get(...)）",
           "layer=it.get(\"layer\") or \"knowledge\"" in src,
           "锚点缺失")
    _check("S10d ★ 修复前的 observe 默认 override=True 且无夹取",
           "override=True" in src and "_import_importance" not in src)


_GROUPS = (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4), ("S5", s5),
           ("S6", s6), ("S7", s7), ("S8", s8), ("S9", s9), ("S10", s10))


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    print("== 对端证据包导入范围守卫（issue #191）==")
    for gid, fn in _GROUPS:
        if want and gid not in want:
            continue
        print("[%s]" % gid)
        try:
            fn()
        except Exception as e:
            _check("%s 组内异常：%s: %s" % (gid, type(e).__name__, e), False)
    total = len(_OK) + len(_BAD)
    print("对端证据包导入范围守卫（issue #191）：通过 %d / 失败 %d"
          % (len(_OK), len(_BAD)))
    return 1 if _BAD else 0


# ---------------------------------------------------------------------------
# 定点变异自证（仓内体例：每条变异必须打红它该打红的判据）
# ---------------------------------------------------------------------------
_MUTATIONS = (
    # (标签, 锚点, 替换, 期望命中的判据组)
    ("V1 落层白名单去掉（anchor/self 原样透传）",
     "        if layer not in IMPORT_LAYERS:\n            layer = \"knowledge\"\n            clamped += 1\n",
     "",
     "S2"),
    ("V2 重要度不再夹取（原样透传）",
     "        imp = _import_importance(it.get(\"importance\"))\n",
     "        imp = it.get(\"importance\") or 0.5\n",
     "S3"),
    ("V3 created_at 版本闸去掉（旧包可覆写）",
     "        last = seen.get(xid)\n        if isinstance(last, (int, float)) and not isinstance(last, bool) \\\n                and created <= float(last):\n            replayed += 1\n            continue\n",
     "",
     "S5"),
    ("V4 版本闸比较方向反转（新包被拒、旧包放行）",
     "                and created <= float(last):\n",
     "                and created >= float(last):\n",
     "S5"),
    ("V5 本地节点覆写闸去掉（foreign 不拦）",
     "        cur = nodes.get(xid)\n        if cur is not None and TAG_XNODE not in (cur.get(\"tags\") or []):\n",
     "        cur = nodes.get(xid)\n        if False:\n",
     "S8"),
    ("V6 seen 落盘被跳过（跨进程/跨实例记忆失效）",
     "    _seen_save(cg, seen)\n",
     "    pass\n",
     "S5"),
)


def _live_ok():
    """自检：盘上的源确实是被加载的源（防 .pyc 陈旧复用）。"""
    import importlib as _il
    _il.invalidate_caches()
    try:
        mod = _il.reload(ev)
    except Exception as e:
        print("    （reload 失败：%s: %s）" % (type(e).__name__, e))
        return False
    srcp = os.path.join(_REPO, _REL)
    disk = open(srcp, encoding="utf-8").read()
    ns = {"__name__": "md_cg.evidence", "__file__": srcp}
    try:
        exec(compile(disk, srcp, "exec"), ns)
    except Exception as e:
        print("    （盘上源 exec 失败：%s: %s）" % (type(e).__name__, e))
        return False
    same = True
    for name in ("_import_importance", "_seen_load", "_seen_save", "_seen_path"):
        a, b = getattr(mod, name, None), ns.get(name)
        if a is None or b is None:
            continue
        if getattr(a, "__code__", None).co_code != getattr(b, "__code__", None).co_code:
            same = False
    return same


def _run_guard(groups):
    out = subprocess.run([sys.executable, "-X", "utf8", "-m",
                          "md_cg.test_issue191_import_scope"] + list(groups),
                         cwd=_REPO, capture_output=True, timeout=300)
    return out.returncode, out.stdout.decode("utf-8", "replace")


def mutate():
    srcp = os.path.join(_REPO, _REL)
    orig = open(srcp, encoding="utf-8", newline="").read()
    if _MARK not in orig:
        print("SOURCE-ALREADY-MUTATED：%s 不含本件标记，先恢复到修复版再跑" % _REL)
        return 2
    NL = "\r\n" if "\r\n" in orig else "\n"
    bad = 0
    restore_failed = False
    try:
        for label, anchor, repl, want in _MUTATIONS:
            a_ = anchor.replace("\n", NL)
            if a_ not in orig:
                print("ANCHOR-MISS  %s" % label)
                bad += 1
                continue
            if orig.count(a_) != 1:
                print("ANCHOR-AMBIGUOUS(%d)  %s" % (orig.count(a_), label))
                bad += 1
                continue
            mut = orig.replace(a_, repl.replace("\n", NL), 1)
            with open(srcp, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            if not _live_ok():
                print("STALE-BYTE-CODE（盘上源未生效）  %s" % label)
                bad += 1
                continue
            rc, out = _run_guard((want,))
            reds = [ln.strip() for ln in out.splitlines() if "FAIL" in ln]
            hit = any(want in ln for ln in reds)
            flag = "OK  " if (rc != 0 and hit and reds) else "BAD "
            if flag.strip() == "BAD":
                bad += 1
            print("%s %-38s 红项=%d 命中%s=%s" % (flag, label, len(reds), want,
                                                  "是" if hit else "否"))
            if reds:
                print("      首个红项：%s" % reds[0])
    finally:
        with open(srcp, "w", encoding="utf-8", newline="") as f:
            f.write(orig)
        after = open(srcp, encoding="utf-8", newline="").read()
        if after != orig:
            print("RESTORE-FAILED：%s 未能复原" % _REL)
            restore_failed = True
    if restore_failed:
        return 2
    if bad:
        print("定点变异自证：FAIL（%d 条未命中）" % bad)
        return 1
    print("定点变异自证：PASS（每条变异都打红并点名）")
    return 0


def cli():
    if "--mutate" in sys.argv:
        return mutate()
    return main()


if __name__ == "__main__":
    sys.exit(cli())
