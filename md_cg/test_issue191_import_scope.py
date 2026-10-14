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
  S10 判别力：取修复前源原形（无本件标记）自证——git 历史不可用时回落内嵌夹具

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


# 修复前源（md_cg/evidence.py @ 0950295，无本件标记）。
# 为什么内嵌：CI 的 pull/<n>/merge 提交已含本件修复，git show HEAD 取到的是
# 修复后源 —— 历史锚在 CI 上必然落空，且浅克隆下更取不到祖先提交。
# 内嵌后 S10 判据不放松：仍要求「修复前源无本件标记、无白名单、落层为原样透传」。
_BEFORE_B64 = (
    "IyAtKi0gY29kaW5nOiB1dGYtOCAtKi0KIiIi6Leo6IqC54K56K+B5o2u5a2Y5YKo77yI6JyC576k5LqS6IGUIHYwLjPvvInjgIIKCuaUuyDCpzkuMSDnm7Ll" 
    "jLrvvJpgaWRlbnRpdHkuaW5mZXJfcG9zaXRpb25gIOWPque7n+iuoSoq5pys5qC5KirluKYgYHN1YmplY3Q6PGlkPmAg5qCH562+55qECuivgeaNruiKgueC" 
    "ue+8jOi3qOiKgueCueaXtuWvueerr+ingua1i+WvueacrOiKgueCueS4jeWPr+ingeOAguacrOaooeWdl+e7meWHuuacgOWwj+WPr+a1i+eahOS6pOaNouac" 
    "uuWItu+8mgoKICDikaAgKiroioLngrnlkI3niYcqKu+8iGNhcmTvvInigJTigJRgbm9kZV9pZGAgLyDmoLnot6/lvoQgLyDniYjmnKznirbmgIEgLyDnrb7l" 
    "kI3lmajlhazlvIDkv6Hmga/vvJsKICDikaEgKiror4Hmja7ljIUqKu+8iHBhY2vvvInigJTigJTku47mnKzmoLnlr7zlh7rjgIzmiJHlr7nmn5DkuLvkvZPn" 
    "moTop4LmtYvjgI3vvIwqKueUseacrOiKgueCueetvuWQjSoq77ybCiAg4pGiICoq5a+85YWlKirvvIhpbXBvcnTvvInigJTigJTpqoznrb4g4oaSIOiQveac" 
    "rOague+8iOW4piBgc291cmNlOjxub2RlPmAg5qCH562+77yJ4oaSIOWPr+WuoeiuoeOAgeWPr+aLkuaUtuOAggoK6K6+6K6h6L6555WM77yI5om/IEQtMSAv" 
    "IEQtNO+8ie+8mgoKICDCtyDlhoXmoLgqKuS4jeWBmuWvhueggeWtpioq77ya562+5ZCNL+mqjOetvuS4gOW+i+e7jyBgc2lnbmVyLnNpZ25fZm9yIC8gdmVy" 
    "aWZ5X2ZvcmDvvIwKICAgIOi3qOiKgueCueivgeaNruimgeaxguWtkOezu+e7n+etlueVpSBgc2lnbl9vbmAg5ZCrIGBldmlkZW5jZWDvvIjnlLHmmbrog73k" 
    "vZPoh6rlhrPvvInvvJsKICDCtyDlhoXmoLgqKuS4jeS/neivgeWFqOWxgOWFseivhioq77yIMC4wLjMg5bGA6YOo5LiN5Y+v55+l77yJ77ya5Y+q5L+d6K+B" 
    "44CM5p2l5rqQ5Y+v5rqvICsg5Y+v5ouS5pS2ICsg55WZ55eV44CN77ybCiAgwrcg6K+B5o2u5pivKirku5bor4EqKu+8iOadpea6kOiKgueCueWvueS4u+S9" 
    "k+eahOingua1i++8ie+8jOS4jeaYr+S4u+S9k+iHquivge+8m+iHquivgei1sCBgaWRlbnRpdHkuYW5jaG9yYO+8mwogIMK3ICoq56aB5q2i6L2s5omLKirv" 
    "vJrlt7Llr7zlhaXnmoTot6joioLngrnor4Hmja7vvIjluKYgYHhub2RlOmNyb3NzYO+8ieS4jeWPguS4juWGjeasoeWvvOWHuu+8jAogICAg5ZCm5YiZIEEg" 
    "5Y+v5Lul5oqK44CMQyDor7QgQiDmgI7moLfjgI3mtJfmiJDjgIxBIOivtCBCIOaAjuagt+OAje+8jOadpea6kOmTvuaWreijguOAggoK6K+a5a6e6L6555WM" 
    "77ya5pys5bGC6aqM6K+B55qE5piv44CMKirov5nmnaHor4Hmja7noa7lrp7mnaXoh6ror6XoioLngrkqKuOAje+8jAoqKuS4jeaYryoq44CM6L+Z5p2h6K+B" 
    "5o2u5Li655yf44CN4oCU4oCU5ZCO6ICF6ZyA6IqC54K55L6n55qE5Y+v5L+h5omn6KGM77yM5bGe5bel56iL5L6n6LSj5Lu744CCCgrpm7bnrKzkuInmlrnk" 
    "vp3otZbjgIIKIiIiCmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKCmltcG9ydCBhcmdwYXJzZQppbXBvcnQgaGFzaGxpYgppbXBvcnQganNv" 
    "bgppbXBvcnQgb3MKaW1wb3J0IHN5cwppbXBvcnQgdGltZQoKZnJvbSAuIGltcG9ydCBjcnlwdG8gYXMgX2NyeXB0bwpmcm9tIC4gaW1wb3J0IGlkZW50aXR5" 
    "IGFzIF9pZGVudGl0eQpmcm9tIC4gaW1wb3J0IHNlY3VyaXR5IGFzIF9zZWMKZnJvbSAuIGltcG9ydCBzaWduZXIgYXMgX3NpZ25lcgpmcm9tIC5kYXRhcGF0" 
    "aCBpbXBvcnQgYXV4X3Jvb3QKZnJvbSAuZnN1dGlsIGltcG9ydCBwdWJsaXNoCgpOT0RFX0lEX0VOViA9ICJNRENHX05PREVfSUQiClNXQVJNX0RJUl9FTlYg" 
    "PSAiTURDR19TV0FSTV9ESVIiClJPT1RfRU5WID0gIk1EQ0dfUk9PVCIKCkRFRkFVTFRfRElSID0gYXV4X3Jvb3QoKQpERUZBVUxUX1NXQVJNX0RJUiA9IG9z" 
    "LnBhdGguam9pbihERUZBVUxUX0RJUiwgInN3YXJtIikKClNVQlNZU1RFTSA9ICJzd2FybSIgICAgICAgICAgIyDlrZDns7vnu5/lkI3vvJrmmbrog73kvZPl" 
    "j6/lr7nlroPlo7DmmI7nrb7lkI3nrZbnlaXvvIhELTTvvIkKU0lHTl9BQ1RJT04gPSAiZXZpZGVuY2UiClNDSEVNQSA9IDEKS0lORCA9ICJtZGNnLmV2aWRl" 
    "bmNlLnBhY2siCkNBUkRfS0lORCA9ICJtZGNnLm5vZGUuY2FyZCIKClRBR19YTk9ERSA9ICJ4bm9kZTpjcm9zcyIKU09VUkNFX1BSRUZJWCA9ICJzb3VyY2U6" 
    "IgoKTUFYX0lURU1TID0gNTAwICAgICAgICAgICAgICAjIOWNleWMheadoeebruS4iumZkO+8iOmYsueBjOWMhe+8iQpNQVhfVEVYVCA9IDQwMDAgICAgICAg" 
    "ICAgICAgICMg5Y2V5p2h5q2j5paH5LiK6ZmQCgojIC0tLS0gaXNzdWUgIzI1OO+8muWvhue6p+mdoueahCoq5Y2V5LiA5p2D5aiBKirvvIjkuI3lj6bnq4vl" 
    "iKTmja7vvIznm7TmjqXlvJXml6LmnInluLjph4/vvIkgLS0tLQpfU0VOU0lUSVZJVFlfT1JERVIgPSBfc2VjLlNFTlNJVElWSVRZX09SREVSCl9FTkNSWVBU" 
    "RURfTEVWRUxTID0gc2V0KF9jcnlwdG8uRU5DUllQVEVEX0xFVkVMUykKX0FjY2Vzc0RlbmllZCA9IF9zZWMuQWNjZXNzRGVuaWVkCgojIC0tLS0gaXNzdWUg" 
    "IzE0N++8iDIwMjYtMTAtMTHvvInvvJpwYWNrX2lkIOeZveWQjeWNlSAtLS0tCiMg55eF6LGh77yacGFja19pZCDmnKrmuIXmtJfljbPmi7zov5vlvZLmoaPo" 
    "t6/lvoTvvIjop4Egd3JpdGVfcGFjayDnvLrnnIHliIbmlK/vvInih5Ig6Lev5b6E56m/6LaK77ybCiMg6Z2e566h55CG5ZGY5Luk54mMKirkuIDmrKEgaW1w" 
    "b3J0IOWNs+WPr+imhuWGmSoqIF9rZXlzLmpzb24gLyBfdG9rZW5zLmpzb27vvIjlrp7mtYsgaz01IOautSAuLi8g5ZG95Lit77yJ44CCCiMg5ZCI5rOV55Sf" 
    "5Lqn6ICF5Y+q5LqnICJwYWNrLTwxMmhleD4i77yI6KeBIGV4cG9ydF9wYWNr44CMcGFja1sicGFja19pZCJdID0gInBhY2stIiArIHBpZOOAje+8ie+8jAoj" 
    "IOaVheeZveWQjeWNleWPliBBU0NJSSDlrZfmr43mlbDlrZfkuI4gLiBfIC3vvIzlubbmmL7lvI/mi5IgLi4g5LiO5YmN5a+854K544CCClBBQ0tfSURfTUFY" 
    "ID0gMTI4ClBBQ0tfSURfT0sgPSBmcm96ZW5zZXQoCiAgICAiYWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXpBQkNERUZHSElKS0xNTk9QUVJTVFVWV1hZWjAx" 
    "MjM0NTY3ODkuXy0iKQoKCmNsYXNzIEV2aWRlbmNlRXJyb3IoRXhjZXB0aW9uKToKICAgICIiIui3qOiKgueCueivgeaNruWxgumUmeivr++8iGZhaWwtY2xv" 
    "c2Vk77yJ44CCIiIiCgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LQojIOi3r+W+hOS4jui6q+S7vQojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBwYXRoIOS4uuecn+WAvOaXtui/lOWbniBwYXRo77yb5ZCm5YiZ6Iul546v5aKD5Y+Y6YePIFNX" 
    "QVJNX0RJUl9FTlYg5Li655yf5YC85YiZ6L+U5Zue5YW25YC877yb5ZCm5YiZ6L+U5Zue5qih5Z2X57qn5bi46YePIERFRkFVTFRfU1dBUk1fRElS44CCCmRl" 
    "ZiBzd2FybV9kaXIocGF0aDogc3RyID0gTm9uZSkgLT4gc3RyOgogICAgcmV0dXJuIHBhdGggb3Igb3MuZW52aXJvbi5nZXQoU1dBUk1fRElSX0VOVikgb3Ig" 
    "REVGQVVMVF9TV0FSTV9ESVIKCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBzd2FybSDlj4LmlbDvvIjlgYflgLzlm57okL3liLAgc3dhcm1fZGlyIOea" 
    "hOm7mOiupOmAu+i+ke+8ieaXtu+8jOi/lOWbniBvcy5wYXRoLmpvaW4oc3dhcm1fZGlyKHN3YXJtKSwgInBlZXJzIinjgIIKZGVmIHBlZXJzX2Rpcihzd2Fy" 
    "bTogc3RyID0gTm9uZSkgLT4gc3RyOgogICAgcmV0dXJuIG9zLnBhdGguam9pbihzd2FybV9kaXIoc3dhcm0pLCAicGVlcnMiKQoKCiMg55Sf5pWI5p2h5Lu2" 
    "77ya5b2T5Lyg5YWlIHN3YXJtIOWPguaVsO+8iOWBh+WAvOWbnuiQveWIsCBzd2FybV9kaXIg55qE6buY6K6k6YC76L6R77yJ5pe277yM6L+U5ZueIG9zLnBh" 
    "dGguam9pbihzd2FybV9kaXIoc3dhcm0pLCAiaW5ib3giKeOAggpkZWYgaW5ib3hfZGlyKHN3YXJtOiBzdHIgPSBOb25lKSAtPiBzdHI6CiAgICByZXR1cm4g" 
    "b3MucGF0aC5qb2luKHN3YXJtX2Rpcihzd2FybSksICJpbmJveCIpCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgcm9vdCDkuLrnnJ/lgLzml7bov5Tl" 
    "m54gcm9vdO+8m+WQpuWImei/lOWbnueOr+Wig+WPmOmHjyBST09UX0VOViDnmoTlgLzvvIjlj6/og73kuLogTm9uZe+8ieOAggpkZWYgX3Jvb3Rfb2Yocm9v" 
    "dDogc3RyID0gTm9uZSkgLT4gc3RyOgogICAgcmV0dXJuIHJvb3Qgb3Igb3MuZW52aXJvbi5nZXQoUk9PVF9FTlYpCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZMg" 
    "ZXhwbGljaXQg5oiW546v5aKD5Y+Y6YePIE5PREVfSURfRU5WIHN0cmlwIOWQjumdnuepuuaXtui/lOWbnuivpeWAvO+8m+WQpuWImeiLpSBfcm9vdF9vZihy" 
    "b290KSDov5Tlm57nnJ/lgLzvvIzov5Tlm57ln7rkuo7op4TojIPnu53lr7not6/lvoTnmoQgJ25vZGUtPDEyaGV4PifvvJvlkKbliJnmipvlh7ogRXZpZGVu" 
    "Y2VFcnJvcuOAggpkZWYgbm9kZV9pZChyb290OiBzdHIgPSBOb25lLCBleHBsaWNpdDogc3RyID0gTm9uZSkgLT4gc3RyOgogICAgIiIi5pys6IqC54K56Lqr" 
    "5Lu944CCCgogICAg5LyY5YWIIGBNRENHX05PREVfSURg77yI55Sf5Lqn546v5aKD5bqU5pi+5byP6K6+572u77yM5L+d6K+B6Leo5py65Zmo56iz5a6a77yJ" 
    "77ybCiAgICDnvLrnnIHku47moLnot6/lvoTmtL7nlJ8gYG5vZGUtPDEyaGV4PmDvvIjlkIzmnLrlj6/lpI3njrDvvIzot6jmnLrlmajkuI3kv53or4HllK/k" 
    "uIDvvInjgIIKICAgICIiIgogICAgIyBpc3N1ZSAjMjc3IOexu+Wei+mXuCoq5YWI5LqOIC5zdHJpcCgpKirvvJrml6flhpnms5UgKGV4cGxpY2l0IG9yIGVu" 
    "diBvciAiIikuc3RyaXAoKQogICAgIyDlnKggZXhwbGljaXQ9MTIzIOi/meexu+mdnuWtl+espuS4suS4iuS8mua8j+aIkCBBdHRyaWJ1dGVFcnJvcu+8iGlu" 
    "dCDmsqHmnIkgc3RyaXDvvInvvIwKICAgICMg5pei5LiN5pivIGZhaWwtY2xvc2VkIOeahOmUmeivr+exu+OAgeiwg+eUqOaWueS5n+aXoOazleaMieexu+We" 
    "i+WIpOepuuOAggogICAgIyDor63kuYnkv53mjIHvvJrlgYflgLwgZXhwbGljaXQg5LuN5Zue6JC9546v5aKD5Y+Y6YeP77yb56m65Liy5LuN5piv44CM5pyq" 
    "5o+Q5L6b44CN4oeSIOi1sOa0vueUn+OAggogICAgcmF3ID0gZXhwbGljaXQgb3Igb3MuZW52aXJvbi5nZXQoTk9ERV9JRF9FTlYpCiAgICBpZiByYXcgaXMg" 
    "bm90IE5vbmUgYW5kIG5vdCBpc2luc3RhbmNlKHJhdywgc3RyKToKICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9yKAogICAgICAgICAgICBmIuivgeaNruiK" 
    "gueCuSBpZCDlv4XpobvmmK/lrZfnrKbkuLLvvJp7cmF3IXJ977yIe3R5cGUocmF3KS5fX25hbWVfX33vvIkiKQogICAgbmlkID0gKHJhdyBvciAiIikuc3Ry" 
    "aXAoKQogICAgaWYgbmlkOgogICAgICAgICMgaXNzdWUgIzI3N++8muacrOWAvOaYryoq5qih5Z6LL+eOr+Wig+WPr+aOp+i+k+WFpSoq77yM6ICMIHB1Ymxp" 
    "c2hfY2FyZCDkvJrmiorlroPnm7TmjqUKICAgICAgICAjIOaLvOi/myBvcy5wYXRoLmpvaW4ocGVlcnNfZGlyKHN3YXJtKSwgbmlkICsgIi5qc29uIinigJTi" 
    "gJQiLi4vIiDlj6/nqb/otorlh7oKICAgICAgICAjIHN3YXJtIOebruW9le+8iOWunua1iyBNRENHX05PREVfSUQ9Ii4uLy4uLy4uL2V2aWxfcHduZWQiIOWc" 
    "qCBzd2FybSDlpJbokL3nm5jvvInjgIIKICAgICAgICAjIOaXp+WunueOsOWPqiBzdHJpcOOAgembtuagoemqjCDih5Ig5Lu75oSP5paH5Lu25YaZ44CC5q2k" 
    "5aSEKirlhYjmi6blkI7mi7wqKu+8iOWQjCAjMTQ3IOeahAogICAgICAgICMg44CM5rGH54K55YWc5bqV44CN5LiOIG1kY29zLl9yZXN0b3JlX2lkX29rIOea" 
    "hOOAjOWFiOaLpuWQjuivu+OAjee6quW+i++8ie+8mgogICAgICAgICMg5Yik5o2u5LiO5YaZ6Z2iIGFkZCgpIOeahCBQMC0xIOeZveWQjeWNlSoq5ZCM5rqQ" 
    "KirvvIzkuI3mmK/nrKzkuozku73liKTmja7jgIIKICAgICAgICBlcnIgPSBfbm9kZV9pZF9lcnJvcihuaWQpCiAgICAgICAgaWYgZXJyOgogICAgICAgICAg" 
    "ICByYWlzZSBFdmlkZW5jZUVycm9yKGVycikKICAgICAgICByZXR1cm4gbmlkCiAgICByID0gX3Jvb3Rfb2Yocm9vdCkKICAgIGlmIG5vdCByOgogICAgICAg" 
    "IHJhaXNlIEV2aWRlbmNlRXJyb3IoCiAgICAgICAgICAgICLml6Dms5Xnoa7lrproioLngrnouqvku73vvJror7forr4gTURDR19OT0RFX0lE77yI5o6o6I2Q" 
    "77yJ5oiWIE1EQ0dfUk9PVCIpCiAgICBrZXkgPSBvcy5wYXRoLm5vcm1jYXNlKG9zLnBhdGguYWJzcGF0aChyKSkKICAgIHJldHVybiAibm9kZS0iICsgaGFz" 
    "aGxpYi5zaGEyNTYoa2V5LmVuY29kZSgidXRmLTgiKSkuaGV4ZGlnZXN0KClbOjEyXQoKCiMg55Sf5pWI5p2h5Lu277ya5YyF5YaFIG1kX2NnLnRoZW9yeSDl" 
    "j6/lr7zlhaXkuJQgX3RoLmNoZWNrKCkg5oiQ5Yqf5pe26L+U5ZueIHt2ZXJzaW9uLCBhY2NlcHRlZCwgdGhlb3J5X29rfe+8m+S7u+S9leW8guW4uO+8iOeJ" 
    "iOacrOWxgue8uuWkseaIluagoemqjOWksei0pe+8ieS4gOW+i+WQnuaOiei/lOWbniB7fe+8jOS4jemYu+aWreivgeaNruWxguS4u+a1geeoi++8mwpkZWYg" 
    "X3RoZW9yeV9zdGF0ZSgpIC0+IGRpY3Q6CiAgICB0cnk6CiAgICAgICAgZnJvbSAuIGltcG9ydCB0aGVvcnkgYXMgX3RoCiAgICAgICAgc3QgPSBfdGguY2hl" 
    "Y2soKQogICAgICAgIHJldHVybiB7InZlcnNpb24iOiBzdC5nZXQoInZlcnNpb24iKSwKICAgICAgICAgICAgICAgICJhY2NlcHRlZCI6IGxpc3Qoc3QuZ2V0" 
    "KCJhY2NlcHRlZF92ZXJzaW9ucyIpIG9yIFtdKSwKICAgICAgICAgICAgICAgICJ0aGVvcnlfb2siOiBib29sKHN0LmdldCgidGhlb3J5X29rIikpfQogICAg" 
    "ZXhjZXB0IEV4Y2VwdGlvbjogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIOeJiOacrOWxgue8uuWkseS4jemYu+aWreivgeaNruWxggogICAgICAg" 
    "IHJldHVybiB7fQoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIG9iaiDml7bvvIzov5Tlm57lhbYganNvbi5kdW1wcyhvYmosIGVuc3VyZV9hc2NpaT1G" 
    "YWxzZSwgc29ydF9rZXlzPVRydWUsIHNlcGFyYXRvcnM9KCcsJywnOicpKS5lbmNvZGUoInV0Zi04Iikg5a2X6IqC44CCCmRlZiBfY2Fub24ob2JqKSAtPiBi" 
    "eXRlczoKICAgIHJldHVybiBqc29uLmR1bXBzKG9iaiwgZW5zdXJlX2FzY2lpPUZhbHNlLCBzb3J0X2tleXM9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICAg" 
    "IHNlcGFyYXRvcnM9KCIsIiwgIjoiKSkuZW5jb2RlKCJ1dGYtOCIpCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgcyDml7bvvIzov5Tlm54gc3RyKHMp" 
    "IOS4reavj+S4quWtl+espuiLpeS4uuWtl+avjeaVsOWtl+aIliAnXycgJy0nIOWImeS/neeVme+8jOWQpuWImeabv+aNouS4uiAnXycg55qE5a2X56ym5Liy" 
    "44CCCmRlZiBfc2x1ZyhzKSAtPiBzdHI6CiAgICByZXR1cm4gIiIuam9pbihjaCBpZiAoY2guaXNhbG51bSgpIG9yIGNoIGluICJfLSIpIGVsc2UgIl8iIGZv" 
    "ciBjaCBpbiBzdHIocykpCgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLQojIOiKgueCueWQjeeJh++8iOWPkeeOsO+8iQojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSByb29044CBc3Vic3lzdGVt77yI6buY6K6k5bi46YePIFNVQlNZU1RFTe+8" 
    "ieOAgXNpZ25lcnNfZmlsZSDml7bvvIzln7rkuo4gX3NpZ25lci5wb2xpY3lfZm9yIOWSjCBfc2lnbmVyLmdldF9zaWduZXIg6L+U5Zue5ZCN54mH5a2X5YW4" 
    "77yM5YW25LitIHJvb3Qg5Li6IG9zLnBhdGguYWJzcGF0aChfcm9vdF9vZihyb290KSkg6IulIF9yb290X29mKHJvb3QpIOecn+WAvOWQpuWImSBOb25l44CC" 
    "CmRlZiBjYXJkKHJvb3Q6IHN0ciA9IE5vbmUsICosIHN1YnN5c3RlbTogc3RyID0gU1VCU1lTVEVNLAogICAgICAgICBzaWduZXJzX2ZpbGU6IHN0ciA9IE5v" 
    "bmUpIC0+IGRpY3Q6CiAgICAiIiLmnKzoioLngrnlkI3niYfvvJrouqvku70gKyDniYjmnKwgKyDnrb7lkI3lmajlhazlvIDkv6Hmga/vvIgqKuS4jeWQq+Wv" 
    "humSpSoq77yJ44CCIiIiCiAgICBwb2wgPSBfc2lnbmVyLnBvbGljeV9mb3Ioc3Vic3lzdGVtLCBzaWduZXJzX2ZpbGUpCiAgICBzID0gX3NpZ25lci5nZXRf" 
    "c2lnbmVyKHBvbC5nZXQoInNpZ25lciIpKQogICAgciA9IF9yb290X29mKHJvb3QpCiAgICByZXR1cm4gewogICAgICAgICJzY2hlbWEiOiBTQ0hFTUEsICJr" 
    "aW5kIjogQ0FSRF9LSU5ELAogICAgICAgICJub2RlX2lkIjogbm9kZV9pZChyb290KSwKICAgICAgICAicm9vdCI6IG9zLnBhdGguYWJzcGF0aChyKSBpZiBy" 
    "IGVsc2UgTm9uZSwKICAgICAgICAidGhlb3J5IjogX3RoZW9yeV9zdGF0ZSgpLAogICAgICAgICJzaWduZXIiOiBzLnB1YmxpYygpLAogICAgICAgICJzdWJz" 
    "eXN0ZW0iOiBzdWJzeXN0ZW0sCiAgICAgICAgInBvbGljeSI6IHsic2lnbl9vbiI6IGxpc3QocG9sLmdldCgic2lnbl9vbiIpIG9yIFtdKSwKICAgICAgICAg" 
    "ICAgICAgICAgICJyZXF1aXJlX3BlZXJfc2lnbmF0dXJlIjogYm9vbChwb2wuZ2V0KCJyZXF1aXJlX3BlZXJfc2lnbmF0dXJlIikpLAogICAgICAgICAgICAg" 
    "ICAgICAgIm9uX3ZlcmlmeV9mYWlsIjogcG9sLmdldCgib25fdmVyaWZ5X2ZhaWwiKX0sCiAgICAgICAgImNyZWF0ZWRfYXQiOiB0aW1lLnRpbWUoKSwKICAg" 
    "IH0KCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSByb29044CBc3dhcm3jgIFzdWJzeXN0ZW3vvIjpu5jorqTluLjph48gU1VCU1lTVEVN77yJ44CBc2ln" 
    "bmVyc19maWxlIOaXtu+8jOiwg+eUqCBjYXJkIOW+l+WIsCBj77yM5bCGIGMg5LulIEpTT04g5YaZ5YWlIHBlZXJzX2Rpcihzd2FybSkvPGNbIm5vZGVfaWQi" 
    "XT4uanNvbu+8jOi/lOWbniB7Im9rIjogVHJ1ZSwgImZpbGUiOiBwLCAiY2FyZCI6IGN944CCCmRlZiBwdWJsaXNoX2NhcmQocm9vdDogc3RyID0gTm9uZSwg" 
    "Kiwgc3dhcm06IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgc3Vic3lzdGVtOiBzdHIgPSBTVUJTWVNURU0sIHNpZ25lcnNfZmlsZTogc3RyID0gTm9u" 
    "ZSkgLT4gZGljdDoKICAgICIiIuaKiuacrOiKgueCueWQjeeJh+WGmeWFpeWFseS6q+ebruW9lSBgcGVlcnMvPG5vZGVfaWQ+Lmpzb25g77yIMDYwMO+8ieOA" 
    "giIiIgogICAgYyA9IGNhcmQocm9vdCwgc3Vic3lzdGVtPXN1YnN5c3RlbSwgc2lnbmVyc19maWxlPXNpZ25lcnNfZmlsZSkKICAgICMgaXNzdWUgIzI3NyAq" 
    "Kuaxh+eCueWFnOW6lSoq77yI5ZCMICMxNDcg55qEIHdyaXRlX3BhY2sg57qq5b6L77yJ77ya5Y2z5L2/6LCD55So5pa557uV6L+HCiAgICAjIG5vZGVfaWQo" 
    "KSDnm7TmjqXmnoTpgKAgY2FyZO+8jOaBtuaEjyBub2RlX2lkIOS5n+S4gOW+iyBmYWlsLWNsb3NlZOKAlOKAlOS4jemdmem7mOiQveebmOOAggogICAgZXJy" 
    "ID0gX25vZGVfaWRfZXJyb3IoYy5nZXQoIm5vZGVfaWQiKSkKICAgIGlmIGVycjoKICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9yKGVycikKICAgIGJhc2Ug" 
    "PSBvcy5wYXRoLnJlYWxwYXRoKHBlZXJzX2Rpcihzd2FybSkpCiAgICBwID0gb3MucGF0aC5qb2luKHBlZXJzX2Rpcihzd2FybSksIGNbIm5vZGVfaWQiXSAr" 
    "ICIuanNvbiIpCiAgICAjIHJlYWxwYXRoIOW9kuS4gOWQjuWIpOWMheWQq+aAp++8muaLkiAuLi8g56m/6LaK44CB57ud5a+56Lev5b6E44CB55uY56ym44CB" 
    "VU5D44CB56m65a2X6IqCCiAgICAjIO+8iOeZveWQjeWNleW3suaMoeS9j+i/meS6m+W9ouaAge+8jOatpOWkhOaYryoq56ys5LqM6YGTKirvvIzpmLLnmb3l" 
    "kI3ljZXlsIbmnaXooqvmlL7lrr3vvInjgIIKICAgIHRyeToKICAgICAgICByZWFsID0gb3MucGF0aC5yZWFscGF0aChwKQogICAgZXhjZXB0IFZhbHVlRXJy" 
    "b3IgYXMgZXhjOiAgICAgICAgICAgICAgICAgICAgIyDnqbrlrZfoioLnrYnpnZ7ms5XlrZfnrKYKICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9yKGYi5ZCN" 
    "54mH5b2S5qGj6Lev5b6E6Z2e5rOV77yae2V4Y30iKQogICAgaWYgcmVhbCAhPSBiYXNlIGFuZCBub3QgcmVhbC5zdGFydHN3aXRoKGJhc2UgKyBvcy5zZXAp" 
    "OgogICAgICAgIHJhaXNlIEV2aWRlbmNlRXJyb3IoCiAgICAgICAgICAgIGYi5ZCN54mH5b2S5qGj6Lev5b6E6LaK55WM77yI5b+F6aG76JC95ZyoIHBlZXJz" 
    "IOebruW9leWGhe+8ie+8mntwIXJ9IikKICAgIF93cml0ZV9qc29uKHAsIGMpCiAgICByZXR1cm4geyJvayI6IFRydWUsICJmaWxlIjogcCwgImNhcmQiOiBj" 
    "fQoKCiMg55Sf5pWI5p2h5Lu277ya5b2TIHBlZXJzX2Rpcihzd2FybSkg5piv55uu5b2V5pe277yM6YGN5Y6G5YW25LitIC5qc29uIOaWh+S7tu+8jOWKoOi9" 
    "veS4uiBkaWN0IOS4lCBraW5kIOetieS6juW4uOmHjyBDQVJEX0tJTkQg55qE5ZCN54mH77yM6IulIGV4Y2x1ZGVfc2VsZiDkuLrnnJ/liJnmjpLpmaQgbm9k" 
    "ZV9pZCDnrYnkuo4gbm9kZV9pZChyb290KSDnmoTlkI3niYfvvIhub2RlX2lkKHJvb3QpIOaKmyBFdmlkZW5jZUVycm9yIOaXtiBzZWxmX2lkIOS4uiBOb25l" 
    "IOS4jeaOkumZpO+8ie+8jOi/lOWbnuaMieaWh+S7tuWQjeaOkuW6j+eahOWIl+ihqOWPiuiuoeaVsO+8m+ebruW9leS4jeWtmOWcqOWImei/lOWbnuepuuWI" 
    "l+ihqOOAggpkZWYgcGVlcnMoc3dhcm06IHN0ciA9IE5vbmUsICosIGV4Y2x1ZGVfc2VsZjogYm9vbCA9IFRydWUsCiAgICAgICAgICByb290OiBzdHIgPSBO" 
    "b25lKSAtPiBkaWN0OgogICAgIiIi5Y+R546w5YWx5Lqr55uu5b2V6YeM55qE5a+556uv5ZCN54mH77yI5oyJIG5vZGVfaWQg5o6S5bqP77yJ44CCIiIiCiAg" 
    "ICBkID0gcGVlcnNfZGlyKHN3YXJtKQogICAgb3V0LCBzZWxmX2lkID0gW10sIE5vbmUKICAgIGlmIGV4Y2x1ZGVfc2VsZjoKICAgICAgICB0cnk6CiAgICAg" 
    "ICAgICAgIHNlbGZfaWQgPSBub2RlX2lkKHJvb3QpCiAgICAgICAgZXhjZXB0IEV2aWRlbmNlRXJyb3I6CiAgICAgICAgICAgIHNlbGZfaWQgPSBOb25lCiAg" 
    "ICBpZiBvcy5wYXRoLmlzZGlyKGQpOgogICAgICAgIGZvciBmbiBpbiBzb3J0ZWQob3MubGlzdGRpcihkKSk6CiAgICAgICAgICAgIGlmIG5vdCBmbi5lbmRz" 
    "d2l0aCgiLmpzb24iKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHdpdGggb3Blbihvcy5wYXRo" 
    "LmpvaW4oZCwgZm4pLCAiciIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICAgICAgYyA9IGpzb24ubG9hZChmKQogICAgICAgICAg" 
    "ICBleGNlcHQgKE9TRXJyb3IsIFZhbHVlRXJyb3IpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UoYywg" 
    "ZGljdCkgb3IgYy5nZXQoImtpbmQiKSAhPSBDQVJEX0tJTkQ6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBzZWxmX2lkIGFuZCBj" 
    "LmdldCgibm9kZV9pZCIpID09IHNlbGZfaWQ6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBvdXQuYXBwZW5kKGMpCiAgICByZXR1cm4g" 
    "eyJkaXIiOiBkLCAiY291bnQiOiBsZW4ob3V0KSwgInBlZXJzIjogb3V0fQoKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDor4Hmja7ljIXvvJrlr7zlh7oKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoKX1BBQ0tfRklFTERTID0gKCJzY2hlbWEiLCAia2luZCIsICJwYWNrX2lkIiwgImZy" 
    "b21fbm9kZSIsICJmcm9tX3Jvb3QiLAogICAgICAgICAgICAgICAgInRoZW9yeSIsICJjcmVhdGVkX2F0IiwgInN1YmplY3RzIiwgIml0ZW1zIikKCgojIOeU" 
    "n+aViOadoeS7tu+8muW9k+S8oOWFpSBwYWNrIOWtl+WFuOaXtu+8jOi/lOWbnuS7heWQq+aooeWdl+e6p+W4uOmHjyBfUEFDS19GSUVMRFMg5Lit5a2X5q61" 
    "77yI57y65aSx5a2X5q615Y+WIHBhY2suZ2V0KGspIOW+l+WIsCBOb25l77yJ55qE6KeE6IyD5YyWIEpTT04g5a2X6IqC44CCCmRlZiBfcGFja19wYXlsb2Fk" 
    "KHBhY2s6IGRpY3QpIC0+IGJ5dGVzOgogICAgIiIi562+5ZCN6L296I2377ya5Zu65a6a5a2X5q61ICsg5o6S5bqP5bqP5YiX5YyW77yM5ZCM5Y+C5pWw5b+F" 
    "5ZCM5a2X6IqC44CCIiIiCiAgICBib2R5ID0ge30KICAgIGZvciBrIGluIF9QQUNLX0ZJRUxEUzoKICAgICAgICBib2R5W2tdID0gcGFjay5nZXQoaykKICAg" 
    "IHJldHVybiBfY2Fub24oYm9keSkKCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBjZ+OAgXN1YmplY3Rz44CBc2luY2Ug5pe277yM6YGN5Y6GIGNnLmlu" 
    "ZGV4WyJub2RlcyJdIOS4reaMiSBub2RlX2lkIOaOkuW6j+eahOiKgueCue+8jOS7heaUtumbhuagh+etvuWQq+W4uOmHjyBUQUdfT0JT44CB5LiN5ZCrIFRB" 
    "R19BTkNIT1IvVEFHX1RSQUlU44CB5LiN5ZCrIFRBR19YTk9EReOAgeiDveaPkOWPliBzdWJqZWN0OiDmoIfnrb7kuJTor6Ugc3ViamVjdCDlnKggc3ViamVj" 
    "dHPvvIhzdWJqZWN0cyDkuLrnnJ/ml7bvvInmiJbkuI3pmZDliLbvvIhzdWJqZWN0cyDlgYflgLzml7bvvInjgIHkuJToi6Ugc2luY2Ug5Li655yf5LiUIHRz" 
    "IOS4uuecn+WImeimgeaxgiBmbG9hdCh0cykgPj0gZmxvYXQoc2luY2UpIOeahOiKgueCue+8jOi/lOWbnuWQqyBub2RlX2lk44CBc3ViamVjdOOAgXRleHTv" 
    "vIjmiKrmlq0gTUFYX1RFWFTvvInjgIFraW5k44CBcm9sZeOAgWxheWVy44CB6L+H5ruk5ZCO55qEIHRhZ3PjgIFpbXBvcnRhbmNl44CBdmVyaWZpY2F0aW9u" 
    "X2Jhc2lz44CBdHMg55qE5YiX6KGo44CCCiMgLS0tLSBpc3N1ZSAjMjU477yIMjAyNi0xMC0xNO+8ie+8mui3qOiKgueCueivgeaNruWMhemAmui3r+S4ouWv" 
    "hue6pyAtLS0tCiMg55eF6LGh77yaYF9jb2xsZWN0YCDkuqflh7rnmoTmnaHnm64qKuS4jeW4piBzZW5zaXRpdml0eSoq77yMYGltcG9ydF9wYWNrYCDlj4jn" 
    "u48KIyBgaWRlbnRpdHkub2JzZXJ2ZWDvvIjnrb7lkI3ml6Dor6XlvaLlj4LvvInokL3nm5gg4oeSIOi1sCBgTWRDR1NlY3VyZS5hZGRgIOeahOe8uuecgQoj" 
    "IGBERUZBVUxUX1NFTlNJVElWSVRZPSJpbnRlcm5hbCJg44CC6ICMIGBjcnlwdG8uRU5DUllQVEVEX0xFVkVMUyA9CiMgKCJwcml2YXRlIiwic2VjcmV0Iilg" 
    "IOKHkiDlj5HpgIHmlrnnm5jkuIrmmK/lr4bmlofjgIHmjqXmlLbmlrnnm5jkuIrmmK8qKuaYjuaWhyoq77yM5LiUCiMgYGltcG9ydF9wYWNrYCDpu5jorqQg" 
    "YGFyY2hpdmU9VHJ1ZWAg5oqK5pW05YyF5piO5paHIEpTT04g5YaN6JC95LiA5Lu95Yiw5pS25Lu2566x44CCCiMg5a6e5rWL77yaQSDkvqcgcHJpdmF0Ze+8" 
    "iOebmOS4iuaXoOaYjuaWh++8ieKGkiBCIOS+pyBpbnRlcm5hbO+8iOebmOS4iuaYjuaWh++8iSsg5pS25Lu2566x5piO5paH44CCCiMKIyDmlLblj6PkuInl" 
    "pITvvJrikaAg5pys5p2h6K+75pWw6L+b5YyF77yb4pGhIOWvvOWFpeS+pyBmYWlsLWNsb3NlZCDmoKHpqozvvIjnvLrlrZfmrrUv6Z2e5a2X56ym5LiyLwoj" 
    "IOacquefpeaho+S4gOW+i+S4jeaUtu+8jOS4jemZjee6p++8ie+8m+KRoiDljIXlhoXlkKvliqDlr4bmoaMg4oeSIOS4jeW9kuaho++8iOW9kuaho+aYr+aY" 
    "juaWhyBKU09O77yJ44CCCmRlZiBfbm9kZV9zZW5zaXRpdml0eShjZywgbmlkKToKICAgICIiIuivu+iKgueCueWvhue6p+OAgioq5LiOICMxNjQg5ZCM5rqQ" 
    "KirvvIhgc3ViZ3JhcGgubm9kZV9zZW5zaXRpdml0eWDvvInvvIzkuI3lj6bnq4vliKTmja7jgIIiIiIKICAgIGZyb20gLiBpbXBvcnQgc3ViZ3JhcGggYXMg" 
    "X3NnCiAgICB0cnk6CiAgICAgICAgcmV0dXJuIF9zZy5ub2RlX3NlbnNpdGl2aXR5KGNnLCBuaWQpCiAgICBleGNlcHQgRXhjZXB0aW9uOiAgICAgICAgICAg" 
    "ICAgICAgICAgICAgICAgICAgICMgbm9xYTogQkxFMDAxCiAgICAgICAgcmV0dXJuIE5vbmUKCgpkZWYgX2NvbGxlY3QoY2csIHN1YmplY3RzPU5vbmUsIHNp" 
    "bmNlPU5vbmUpIC0+IGxpc3Q6CiAgICAiIiLmlLbpm4bmnKzmoLkqKuacrOWcsOWOn+Wniyoq6KeC5rWL6K+B5o2u77yI5o6S6Zmk5qGj5qGI6IqC54K55LiO" 
    "5bey5a+85YWl55qE6Leo6IqC54K56K+B5o2u77yJ44CCIiIiCiAgICB3YW50ID0gc2V0KHN1YmplY3RzIG9yIFtdKQogICAgaXRlbXMgPSBbXQogICAgbm9k" 
    "ZXMgPSBjZy5pbmRleC5nZXQoIm5vZGVzIikgb3Ige30KICAgIGZvciBuaWQgaW4gc29ydGVkKG5vZGVzKToKICAgICAgICBlID0gbm9kZXNbbmlkXQogICAg" 
    "ICAgIHRnID0gc2V0KGUuZ2V0KCJ0YWdzIikgb3IgW10pCiAgICAgICAgaWYgX2lkZW50aXR5LlRBR19PQlMgbm90IGluIHRnOgogICAgICAgICAgICBjb250" 
    "aW51ZQogICAgICAgIGlmIHRnICYge19pZGVudGl0eS5UQUdfQU5DSE9SLCBfaWRlbnRpdHkuVEFHX1RSQUlUfToKICAgICAgICAgICAgY29udGludWUKICAg" 
    "ICAgICBpZiBUQUdfWE5PREUgaW4gdGc6ICAgICAgICAgICAgICAgICAgICAgICAgIyDnpoHmraLovazmiYvvvIjpmLLmtJfor4Hmja7vvIkKICAgICAgICAg" 
    "ICAgY29udGludWUKICAgICAgICBzdWJqID0gIiIKICAgICAgICBmb3IgdCBpbiB0ZzoKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh0LCBzdHIpIGFuZCB0" 
    "LnN0YXJ0c3dpdGgoInN1YmplY3Q6Iik6CiAgICAgICAgICAgICAgICBzdWJqID0gdFtsZW4oInN1YmplY3Q6Iik6XQogICAgICAgICAgICAgICAgYnJlYWsK" 
    "ICAgICAgICBpZiBub3Qgc3ViaiBvciAod2FudCBhbmQgc3ViaiBub3QgaW4gd2FudCk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgbm9kZSA9IGNn" 
    "LmdldChuaWQpIG9yIHt9CiAgICAgICAgZm0gPSBub2RlLmdldCgiZnJvbnRtYXR0ZXIiKSBvciB7fQogICAgICAgIHRzID0gZm0uZ2V0KCJ0cyIpIG9yIGZt" 
    "LmdldCgiY3JlYXRlZF9hdCIpIG9yIGUuZ2V0KCJ0cyIpIG9yIDAKICAgICAgICBpZiBzaW5jZSBhbmQgdHMgYW5kIGZsb2F0KHRzKSA8IGZsb2F0KHNpbmNl" 
    "KToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpdGVtcy5hcHBlbmQoewogICAgICAgICAgICAibm9kZV9pZCI6IG5pZCwKICAgICAgICAgICAgInN1" 
    "YmplY3QiOiBzdWJqLAogICAgICAgICAgICAidGV4dCI6IChub2RlLmdldCgiY29udGVudCIpIG9yICIiKVs6TUFYX1RFWFRdLAogICAgICAgICAgICAia2lu" 
    "ZCI6IGZtLmdldCgia2luZCIpLAogICAgICAgICAgICAicm9sZSI6IGZtLmdldCgicm9sZSIpLAogICAgICAgICAgICAibGF5ZXIiOiBlLmdldCgibGF5ZXIi" 
    "KSwKICAgICAgICAgICAgInRhZ3MiOiBzb3J0ZWQodCBmb3IgdCBpbiB0ZwogICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKHQsIHN0" 
    "cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgYW5kIG5vdCB0LnN0YXJ0c3dpdGgoInN1YmplY3Q6IikKICAgICAgICAgICAgICAgICAgICAgICAgICAg" 
    "YW5kIG5vdCB0LnN0YXJ0c3dpdGgoU09VUkNFX1BSRUZJWCkKICAgICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHQgIT0gVEFHX1hOT0RFKSwKICAgICAg" 
    "ICAgICAgImltcG9ydGFuY2UiOiBmbS5nZXQoImltcG9ydGFuY2UiKSwKICAgICAgICAgICAgInZlcmlmaWNhdGlvbl9iYXNpcyI6IChlLmdldCgidmVyaWZp" 
    "Y2F0aW9uX2Jhc2lzIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciBmbS5nZXQoInZlcmlmaWNhdGlvbl9iYXNpcyIpKSwKICAgICAg" 
    "ICAgICAgIyBpc3N1ZSAjMjU477ya5a+G57qn6ZqP5p2h55uu5Ye65qC577yI5q2k5YmN5pW05p2h6YCa6Lev5LiN5bim6K+l5a2X5q6177yJCiAgICAgICAg" 
    "ICAgICJzZW5zaXRpdml0eSI6IF9ub2RlX3NlbnNpdGl2aXR5KGNnLCBuaWQpLAogICAgICAgICAgICAidHMiOiB0cywKICAgICAgICB9KQogICAgcmV0dXJu" 
    "IGl0ZW1zCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgY2fjgIFzdWJqZWN0c+OAgXNpbmNl44CBc3dhcm3jgIFzdWJzeXN0ZW3vvIjpu5jorqQgU1VC" 
    "U1lTVEVN77yJ44CBc2lnbmVyc19maWxl44CBcmVxdWlyZV9zaWduYXR1cmXvvIjpu5jorqQgVHJ1Ze+8ieaXtu+8jOaUtumbhuivgeaNruW5tuaIquaWreiH" 
    "s+W4uOmHjyBNQVhfSVRFTVPvvIznlKggX3NpZ25lci5zaWduX2ZvciDku6XluLjph48gU0lHTl9BQ1RJT04g562+5ZCN77yM6IulIHJlcXVpcmVfc2lnbmF0" 
    "dXJlIOS4uuecn+S4lOetvuWQjeacquaIkOWKn+WImeaKm+WHuiBFdmlkZW5jZUVycm9y77yM5ZCm5YiZ6L+U5Zue5ZCrIHBhY2vjgIFjb3VudOOAgXRydW5j" 
    "YXRlZOOAgXNpZ25lZCDnmoTlrZflhbjjgIIKZGVmIGV4cG9ydF9wYWNrKGNnLCAqLCBzdWJqZWN0cz1Ob25lLCBzaW5jZT1Ob25lLCBzd2FybTogc3RyID0g" 
    "Tm9uZSwKICAgICAgICAgICAgICAgIHN1YnN5c3RlbTogc3RyID0gU1VCU1lTVEVNLCBzaWduZXJzX2ZpbGU6IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAg" 
    "ICByZXF1aXJlX3NpZ25hdHVyZTogYm9vbCA9IFRydWUpIC0+IGRpY3Q6CiAgICAiIiLlr7zlh7rmnKzoioLngrnlr7nvvIjmjIflrprvvInkuLvkvZPnmoTo" 
    "p4LmtYvor4Hmja7ljIXvvIzlubbnrb7lkI3jgIIKCiAgICBgcmVxdWlyZV9zaWduYXR1cmU9VHJ1ZWDvvIjpu5jorqTvvInvvJrnrZbnlaXmnKrlr7kgYGV2" 
    "aWRlbmNlYCDnrb7lkI3ljbPmipvplJnigJTigJQKICAgIOi3qOiKgueCueivgeaNruayoeacieetvuWQjeWwseS4jeWPr+a6r+a6kO+8jOWugeWPr+S4jeS6" 
    "p+WHuuOAggogICAgIiIiCiAgICBpdGVtcyA9IF9jb2xsZWN0KGNnLCBzdWJqZWN0cz1zdWJqZWN0cywgc2luY2U9c2luY2UpCiAgICB0cnVuY2F0ZWQgPSBs" 
    "ZW4oaXRlbXMpID4gTUFYX0lURU1TCiAgICBpdGVtcyA9IGl0ZW1zWzpNQVhfSVRFTVNdCiAgICBuaWQgPSBub2RlX2lkKGdldGF0dHIoY2csICJyb290Iiwg" 
    "Tm9uZSkpCiAgICBwYWNrID0gewogICAgICAgICJzY2hlbWEiOiBTQ0hFTUEsICJraW5kIjogS0lORCwKICAgICAgICAiZnJvbV9ub2RlIjogbmlkLAogICAg" 
    "ICAgICJmcm9tX3Jvb3QiOiBvcy5wYXRoLmFic3BhdGgoZ2V0YXR0cihjZywgInJvb3QiLCAiIikgb3IgIiIpLAogICAgICAgICJ0aGVvcnkiOiBfdGhlb3J5" 
    "X3N0YXRlKCksCiAgICAgICAgImNyZWF0ZWRfYXQiOiB0aW1lLnRpbWUoKSwKICAgICAgICAic3ViamVjdHMiOiBzb3J0ZWQoc2V0KHN1YmplY3RzIG9yIFtd" 
    "KSksCiAgICAgICAgIml0ZW1zIjogaXRlbXMsCiAgICB9CiAgICBwaWQgPSBoYXNobGliLnNoYTI1NihfY2Fub24oeyJuIjogbmlkLCAidCI6IHBhY2tbImNy" 
    "ZWF0ZWRfYXQiXSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgImMiOiBsZW4oaXRlbXMpfSkpLmhleGRpZ2VzdCgpWzoxMl0KICAgIHBhY2tb" 
    "InBhY2tfaWQiXSA9ICJwYWNrLSIgKyBwaWQKCiAgICBzaWdyZXMgPSBfc2lnbmVyLnNpZ25fZm9yKHN1YnN5c3RlbSwgX3BhY2tfcGF5bG9hZChwYWNrKSwK" 
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYWN0aW9uPVNJR05fQUNUSU9OLCBwYXRoPXNpZ25lcnNfZmlsZSkKICAgIHBhY2tbInNpZyJdID0geyJz" 
    "aWduZXIiOiBzaWdyZXMuZ2V0KCJzaWduZXIiKSwKICAgICAgICAgICAgICAgICAgICJzaWduYXR1cmUiOiBzaWdyZXMuZ2V0KCJzaWduYXR1cmUiKSBvciAi" 
    "IiwKICAgICAgICAgICAgICAgICAgICJzaWduZWQiOiBib29sKHNpZ3Jlcy5nZXQoInNpZ25lZCIpKX0KICAgIGlmIHJlcXVpcmVfc2lnbmF0dXJlIGFuZCBu" 
    "b3QgcGFja1sic2lnIl1bInNpZ25lZCJdOgogICAgICAgIHJhaXNlIEV2aWRlbmNlRXJyb3IoCiAgICAgICAgICAgIGYi5a2Q57O757ufIHtzdWJzeXN0ZW19" 
    "IOetlueVpeacquWvuSB7U0lHTl9BQ1RJT059IOetvuWQje+8jOivgeaNruWMheS4jeWPr+a6r+a6kOOAgiIKICAgICAgICAgICAgZiLor7flhYjlo7DmmI7v" 
    "vJpzZXRfcG9saWN5KHtzdWJzeXN0ZW0hcn0sIHNpZ25fb249WydoYW5kc2hha2UnLCd7U0lHTl9BQ1RJT059J10pIikKICAgIHJldHVybiB7Im9rIjogVHJ1" 
    "ZSwgInBhY2siOiBwYWNrLCAiY291bnQiOiBsZW4oaXRlbXMpLAogICAgICAgICAgICAidHJ1bmNhdGVkIjogdHJ1bmNhdGVkLCAic2lnbmVkIjogcGFja1si" 
    "c2lnIl1bInNpZ25lZCJdfQoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHBhY2vjgIFwYXRo44CBc3dhcm0g5pe277yM6IulIHBhdGgg5Li65YGH5YC8" 
    "5YiZ55SoIG9zLnBhdGguam9pbihpbmJveF9kaXIoc3dhcm0pLCBmIntfc2x1ZyhwYWNrLmdldCgnZnJvbV9ub2RlJykpfV9fe3BhY2suZ2V0KCdwYWNrX2lk" 
    "Jyl9Lmpzb24iKSDnlJ/miJDot6/lvoTvvIzlsIYgcGFjayDku6UgSlNPTiDlhpnlhaXor6Xot6/lvoTlubbov5Tlm54geyJvayI6IFRydWUsICJmaWxlIjog" 
    "cGF0aH3jgIIKZGVmIHdyaXRlX3BhY2socGFjazogZGljdCwgcGF0aDogc3RyID0gTm9uZSwgc3dhcm06IHN0ciA9IE5vbmUpIC0+IGRpY3Q6CiAgICAiIiLm" 
    "ioror4Hmja7ljIXokL3nm5jliLDmlLbku7bnrrHvvIjmiJbmjIflrprot6/lvoTvvInjgIIiIiIKICAgIGlmIG5vdCBwYXRoOgogICAgICAgICMgaXNzdWUg" 
    "IzE0NyAqKuaxh+eCueWFnOW6lSoq77ya5LiOIF92YWxpZGF0ZSDlkIzmupDnmoTnmb3lkI3ljZXigJTigJTljbPkvb/osIPnlKjmlrnnu5Xov4cKICAgICAg" 
    "ICAjIGltcG9ydF9wYWNr77yI55u05o6l6LCD5pys5Ye95pWw77yJ77yM5oG25oSPIHBhY2tfaWQg5Lmf5LiA5b6LIGZhaWwtY2xvc2Vk77yMCiAgICAgICAg" 
    "IyDkuJTlvILluLjnsbvlnovnu5/kuIDkuLogRXZpZGVuY2VFcnJvcu+8iOS4jeWGjea8j+aIkCBPU0Vycm9yL1ZhbHVlRXJyb3LvvInjgIIKICAgICAgICBw" 
    "ZXJyID0gX3BhY2tfaWRfZXJyb3IocGFjay5nZXQoInBhY2tfaWQiKSkKICAgICAgICBpZiBwZXJyOgogICAgICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9y" 
    "KHBlcnIpCiAgICAgICAgYmFzZSA9IG9zLnBhdGgucmVhbHBhdGgoaW5ib3hfZGlyKHN3YXJtKSkKICAgICAgICBwYXRoID0gb3MucGF0aC5qb2luKGluYm94" 
    "X2Rpcihzd2FybSksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIntfc2x1ZyhwYWNrLmdldCgnZnJvbV9ub2RlJykpfV9fe3BhY2suZ2V0KCdwYWNr" 
    "X2lkJyl9Lmpzb24iKQogICAgICAgICMgaXNzdWUgIzE0N++8iDIwMjYtMTAtMTHvvInvvJrlvZLmoaPnm67moIflv4XpobvokL3lnKjmlLbku7bnrrHmoLnl" 
    "hoXigJTigJRyZWFscGF0aCDlvZLkuIDlkI7liKQKICAgICAgICAjIOWMheWQq+aAp++8jOi2iueVjOWNsyBmYWlsLWNsb3NlZO+8iOaLkiAuLi8g56m/6LaK" 
    "44CB57ud5a+56Lev5b6E44CB55uY56ym44CBVU5D44CB56m65a2X6IqC77yJ44CCCiAgICAgICAgIyDlj6rnuqbmnZ8qKueUsSBwYWNrIOaVsOaNrua0vueU" 
    "nyoq55qE57y655yB6Lev5b6E77yb5pi+5byPIHBhdGgg5piv6LCD55So5pa577yIQ0xJIC0tb3V0IC8KICAgICAgICAjIE1DUCBvdXTvvInoh6rpgInokL3n" 
    "grnvvIzlsZ4gQVBJIOWxguiwg+eUqOiAheadg+mZkO+8jOS4jeWcqOatpOaUtueqhO+8iOaXouacieiwg+eUqOmdouS4pOWkhO+8ieOAggogICAgICAgIHRy" 
    "eToKICAgICAgICAgICAgcmVhbCA9IG9zLnBhdGgucmVhbHBhdGgocGF0aCkKICAgICAgICBleGNlcHQgVmFsdWVFcnJvciBhcyBleGM6ICAgICAgICAgICAg" 
    "ICAgICAgICAjIOepuuWtl+iKguetiemdnuazleWtl+espgogICAgICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9yKGYi6K+B5o2u5YyF5b2S5qGj6Lev5b6E" 
    "6Z2e5rOV77yae2V4Y30iKQogICAgICAgIGlmIHJlYWwgIT0gYmFzZSBhbmQgbm90IHJlYWwuc3RhcnRzd2l0aChiYXNlICsgb3Muc2VwKToKICAgICAgICAg" 
    "ICAgcmFpc2UgRXZpZGVuY2VFcnJvcigKICAgICAgICAgICAgICAgIGYi6K+B5o2u5YyF5b2S5qGj6Lev5b6E6LaK55WM77yI5b+F6aG76JC95Zyo5pS25Lu2" 
    "566x5YaF77yJ77yae3BhdGghcn0iKQogICAgX3dyaXRlX2pzb24ocGF0aCwgcGFjaykKICAgIHJldHVybiB7Im9rIjogVHJ1ZSwgImZpbGUiOiBwYXRofQoK" 
    "CiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDor4Hmja7ljIXv" 
    "vJrlr7zlhaUKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoKIyDn" 
    "lJ/mlYjmnaHku7bvvJrlvZMgc3JjIOaYryBkaWN0IOaXtuebtOaOpei/lOWbniBzcmPvvJvlkKbliJnku6Ugc3JjIOS4uui3r+W+hOaJk+W8gCBKU09OIOaW" 
    "h+S7tuW5tui/lOWbniBqc29uLmxvYWQoZinjgIIKZGVmIF9yZWFkX3BhY2soc3JjKSAtPiBkaWN0OgogICAgaWYgaXNpbnN0YW5jZShzcmMsIGRpY3QpOgog" 
    "ICAgICAgIHJldHVybiBzcmMKICAgIHdpdGggb3BlbihzcmMsICJyIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICByZXR1cm4ganNvbi5sb2Fk" 
    "KGYpCgoKIyDnlJ/mlYjmnaHku7bvvJpwaWQg5Li6IHBhY2tbInBhY2tfaWQiXe+8iOS7u+aEj+exu+Wei++8ie+8m+WQiOinhOi/lOWbnuepuuWtl+espuS4" 
    "su+8jOWQpuWImei/lOWbnuS4reaWh+eQhueUseKAlOKAlOmdniBzdHIv56m644CB6LaFIFBBQ0tfSURfTUFY44CB5ZCrIFBBQ0tfSURfT0sg5LmL5aSW5a2X" 
    "56ym44CB5Lul54K55byA5aS05oiW5ZCr6L+e57ut5Lik54K55ZCE5LiA5p2h44CCKirljZXkuIDnnJ/mupAqKu+8ml92YWxpZGF0ZSDkuI4gd3JpdGVfcGFj" 
    "ayDmsYfngrnlhbHnlKjmnKzlh73mlbDvvIzop4TliJnlj6rmnInkuIDku73jgIIKZGVmIF9ub2RlX2lkX2Vycm9yKG5pZCkgLT4gc3RyOgogICAgIiIibm9k" 
    "ZV9pZCDnmb3lkI3ljZXliKTmja7vvIhpc3N1ZSAjMjc377yJ44CCCgogICAg5Yik5o2u5LiO5YaZ6Z2iIE1kQ0cuYWRkKCkg55qEIFAwLTEg55m95ZCN5Y2V" 
    "KirlkIzmupAqKu+8iOWQjOS4gCBfTk9ERV9JRF9SReOAgeWQjOS4gAogICAgIi4uIiDnpoHku6TjgIHlkIzkuIAgX05PREVfSURfRk9SQklEREVO77yJ77yM" 
    "5LiN5piv56ys5LqM5Lu95Yik5o2u4oCU4oCU6YG/5YWN5Lik5aWX5Y+j5b6E5ryC56e744CCCiAgICDnqbrkuLLov5Tlm57plJnor6/mlofmoYjvvIjosIPn" 
    "lKjmlrnlt7Igc3RyaXAg6L+H77yM56m65Liy5Y2z44CM5pyq5o+Q5L6b44CN77yJ44CCCiAgICAiIiIKICAgIGZyb20gLm1kY2cgaW1wb3J0IF9OT0RFX0lE" 
    "X1JFLCBfTk9ERV9JRF9GT1JCSURERU4KICAgIGlmIG5vdCBpc2luc3RhbmNlKG5pZCwgc3RyKSBvciBub3QgbmlkOgogICAgICAgIHJldHVybiBmIuivgeaN" 
    "ruiKgueCuSBpZCDlv4XpobvmmK/pnZ7nqbrlrZfnrKbkuLLvvJp7bmlkIXJ9IgogICAgaWYgbGVuKG5pZCkgPiAxMjg6CiAgICAgICAgcmV0dXJuIGYi6K+B" 
    "5o2u6IqC54K5IGlkIOi/h+mVv++8mntsZW4obmlkKX0gPiAxMjgiCiAgICBpZiAiLi4iIGluIG5pZDoKICAgICAgICByZXR1cm4gZiLor4Hmja7oioLngrkg" 
    "aWQg5b2i5Ly86Lev5b6E56m/6LaK77yI5ouSIC4u77yJ77yae25pZCFyfSIKICAgIGlmIG5pZCBpbiBfTk9ERV9JRF9GT1JCSURERU46CiAgICAgICAgcmV0" 
    "dXJuIGYi6K+B5o2u6IqC54K5IGlkIOaYr+S/neeVmeWtl++8mntuaWQhcn0iCiAgICBpZiBub3QgX05PREVfSURfUkUubWF0Y2gobmlkKToKICAgICAgICBy" 
    "ZXR1cm4gKGYi6K+B5o2u6IqC54K5IGlkIOWQq+mdnuazleWtl+espu+8iOmhu+WMuemFjSB7X05PREVfSURfUkUucGF0dGVybn3vvInvvJp7bmlkIXJ9IikK" 
    "ICAgIHJldHVybiAiIgoKCmRlZiBfcGFja19pZF9lcnJvcihwaWQpIC0+IHN0cjoKICAgICIiInBhY2tfaWQg55m95ZCN5Y2V5Yik5o2u77yIaXNzdWUgIzE0" 
    "N++8ieOAgiIiIgogICAgaWYgbm90IGlzaW5zdGFuY2UocGlkLCBzdHIpIG9yIG5vdCBwaWQ6CiAgICAgICAgcmV0dXJuICLor4Hmja7ljIXnvLrlsJEgcGFj" 
    "a19pZO+8iOW9kuaho+S4jeWPr+WRveWQje+8iSIKICAgIGlmIGxlbihwaWQpID4gUEFDS19JRF9NQVg6CiAgICAgICAgcmV0dXJuIGYi6K+B5o2u5YyFIHBh" 
    "Y2tfaWQg6L+H6ZW/77yae2xlbihwaWQpfSA+IHtQQUNLX0lEX01BWH0iCiAgICBiYWRfY2ggPSBzb3J0ZWQoe2NoIGZvciBjaCBpbiBwaWQgaWYgY2ggbm90" 
    "IGluIFBBQ0tfSURfT0t9KQogICAgaWYgYmFkX2NoOgogICAgICAgIHJldHVybiAoZiLor4Hmja7ljIUgcGFja19pZCDlkKvpnZ7ms5XlrZfnrKYge2JhZF9j" 
    "aH0iCiAgICAgICAgICAgICAgICBmIu+8iOWPquWFgeiuuOWtl+avjeaVsOWtl+S4jiAuIF8gLe+8ie+8mntwaWQhcn0iKQogICAgaWYgcGlkLnN0YXJ0c3dp" 
    "dGgoIi4iKSBvciAiLi4iIGluIHBpZDoKICAgICAgICByZXR1cm4gZiLor4Hmja7ljIUgcGFja19pZCDlvaLkvLzot6/lvoTvvIjmi5IgLi4g5LiO5YmN5a+8" 
    "54K577yJ77yae3BpZCFyfSIKICAgIHJldHVybiAiIgoKCiMg55Sf5pWI5p2h5Lu277ya5b2TIHBhY2sg5Li6IGRpY3Qg5LiUIGtpbmQg562J5LqO5bi46YeP" 
    "IEtJTkTjgIFpbnQocGFjay5nZXQoInNjaGVtYSIpIG9yIDApIOS4jeWkp+S6juW4uOmHjyBTQ0hFTUHjgIFmcm9tX25vZGUgc3RyaXAg5ZCO6Z2e56m644CB" 
    "aXRlbXMg5Li6IGxpc3TjgIHkuJQgX3BhY2tfaWRfZXJyb3IocGFjay5nZXQoInBhY2tfaWQiKSkg5Li656m65pe26L+U5Zue56m65a2X56ym5Liy77yb5ZCm" 
    "5YiZ5oyJ5bqP6L+U5Zue5a+55bqU6ZSZ6K+v5a2X56ym5Liy77yI6Z2eIGRpY3TjgIFraW5kIOS4jeespuOAgXNjaGVtYSDov4fmlrDjgIHnvLogZnJvbV9u" 
    "b2Rl44CB57y6IGl0ZW1z44CBcGFja19pZCDkuI3lkIjms5XvvInjgIIKZGVmIF92YWxpZGF0ZShwYWNrOiBkaWN0KSAtPiBzdHI6CiAgICBpZiBub3QgaXNp" 
    "bnN0YW5jZShwYWNrLCBkaWN0KToKICAgICAgICByZXR1cm4gIuivgeaNruWMheS4jeaYryBKU09OIOWvueixoSIKICAgIGlmIHBhY2suZ2V0KCJraW5kIikg" 
    "IT0gS0lORDoKICAgICAgICByZXR1cm4gZiLkuI3mmK/or4Hmja7ljIXvvIhraW5kPXtwYWNrLmdldCgna2luZCcpIXJ977yJIgogICAgaWYgaW50KHBhY2su" 
    "Z2V0KCJzY2hlbWEiKSBvciAwKSA+IFNDSEVNQToKICAgICAgICByZXR1cm4gZiLor4Hmja7ljIUgc2NoZW1hIOi/h+aWsO+8mntwYWNrLmdldCgnc2NoZW1h" 
    "Jyl9ID4ge1NDSEVNQX0iCiAgICBpZiBub3QgKHBhY2suZ2V0KCJmcm9tX25vZGUiKSBvciAiIikuc3RyaXAoKToKICAgICAgICByZXR1cm4gIuivgeaNruWM" 
    "hee8uuWwkSBmcm9tX25vZGXvvIjmnaXmupDkuI3lj6/muq/vvIkiCiAgICBpZiBub3QgaXNpbnN0YW5jZShwYWNrLmdldCgiaXRlbXMiKSwgbGlzdCk6CiAg" 
    "ICAgICAgcmV0dXJuICLor4Hmja7ljIXnvLrlsJEgaXRlbXMiCiAgICAjIGlzc3VlICMxNDfvvJpwYWNrX2lkIOi/m+W9kuaho+aWh+S7tuWQjSDih5Ig5b+F" 
    "6aG76L+H55m95ZCN5Y2V77yI5ouS56m/6LaKL+e7neWvuei3r+W+hC/nm5jnrKYvVU5DL+epuuWtl+iKgu+8ieOAggogICAgcmV0dXJuIF9wYWNrX2lkX2Vy" 
    "cm9yKHBhY2suZ2V0KCJwYWNrX2lkIikpCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgZnJvbV9ub2RlIOWSjCBvcmlnIOaXtu+8jOi/lOWbniBmInhu" 
    "b2RlX3tfc2x1Zyhmcm9tX25vZGUpfV97X3NsdWcob3JpZyl9IuOAggpkZWYgX3hub2RlX2lkKGZyb21fbm9kZTogc3RyLCBvcmlnOiBzdHIpIC0+IHN0cjoK" 
    "ICAgIHJldHVybiBmInhub2RlX3tfc2x1Zyhmcm9tX25vZGUpfV97X3NsdWcob3JpZyl9IgoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHBhY2vjgIFy" 
    "ZWFzb27jgIFzd2FybeOAgSoqa3cg5pe277yM5p6E5bu65ZCrIGF044CBcmVhc29u44CBZnJvbV9ub2Rl44CBcGFja19pZCDlj4oga3cg5Lit6Z2eIE5vbmUg" 
    "6aG555qE5ouS57ud6K6w5b2V77yM5bCd6K+V6L+95Yqg5YiwIGluYm94X2Rpcihzd2FybSkvX3JlamVjdGVkLmpzb25s77yIT1NFcnJvciDlv73nlaXvvInv" 
    "vIzov5Tlm54geyJvayI6IEZhbHNlLCAicmVqZWN0ZWQiOiBUcnVlLCAicmVhc29uIjogcmVhc29uLCAiZnJvbV9ub2RlIjogLi4ufSDlubblkIjlubYga3cg" 
    "5Lit6Z2eIE5vbmUg6aG544CCCmRlZiBfaXRlbV9zZW5zaXRpdml0eShpdDogZGljdCk6CiAgICAiIiLmoKHpqozljIXlhoXmnaHnm67nmoTlr4bnuqcg4oaS" 
    "ICjlr4bnuqcsIOaLkuaUtueQhueUsSnjgIIqKmZhaWwtY2xvc2VkKirjgIIKCiAgICBpc3N1ZSAjMjU477ya57y65a2X5q61L+mdnuWtl+espuS4si/mnKrn" 
    "n6XmoaPkuIDlvovov5Tlm57nkIbnlLHvvIjosIPnlKjmlrnot7Pov4fvvIzkuI3lhpnnm5jvvInjgIIKICAgIOaXp+agvOW8j+WMhe+8iOaXoCBzZW5zaXRp" 
    "dml0ee+8ieWboOatpOS4gOW+i+aLkuaUtuKAlOKAlOacieaEj+eahOihjOS4uuWPmOabtOOAggogICAgIiIiCiAgICByYXcgPSBpdC5nZXQoInNlbnNpdGl2" 
    "aXR5IikKICAgIGlmIHJhdyBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lLCAi5p2h55uu57y6IHNlbnNpdGl2aXR5IOWtl+aute+8iOaXp+agvOW8j+WM" 
    "heS4gOW+i+aLkuaUtu+8iSIKICAgIGlmIG5vdCBpc2luc3RhbmNlKHJhdywgc3RyKToKICAgICAgICByZXR1cm4gTm9uZSwgIuadoeebriBzZW5zaXRpdml0" 
    "eSDpnZ7lrZfnrKbkuLLvvJolciIgJSAocmF3LCkKICAgIHMgPSByYXcuc3RyaXAoKS5sb3dlcigpCiAgICBpZiBzIG5vdCBpbiBfU0VOU0lUSVZJVFlfT1JE" 
    "RVI6CiAgICAgICAgcmV0dXJuIE5vbmUsICLmnaHnm64gc2Vuc2l0aXZpdHkg5pyq55+l5qGj77yaJXLvvIjlkIjms5XmoaMgJXPvvIkiICUgKAogICAgICAg" 
    "ICAgICByYXcsICIvIi5qb2luKF9TRU5TSVRJVklUWV9PUkRFUikpCiAgICByZXR1cm4gcywgIiIKCgpkZWYgX25vdGVfcmVqZWN0KHBhY2s6IGRpY3QsIHJl" 
    "YXNvbjogc3RyLCBzd2FybTogc3RyID0gTm9uZSwgKiprdykgLT4gZGljdDoKICAgIHJlYyA9IHsiYXQiOiB0aW1lLnRpbWUoKSwgInJlYXNvbiI6IHJlYXNv" 
    "biwKICAgICAgICAgICAiZnJvbV9ub2RlIjogKHBhY2sgb3Ige30pLmdldCgiZnJvbV9ub2RlIiksCiAgICAgICAgICAgInBhY2tfaWQiOiAocGFjayBvciB7" 
    "fSkuZ2V0KCJwYWNrX2lkIil9CiAgICByZWMudXBkYXRlKHtrOiB2IGZvciBrLCB2IGluIGt3Lml0ZW1zKCkgaWYgdiBpcyBub3QgTm9uZX0pCiAgICB0cnk6" 
    "CiAgICAgICAgZnJvbSAuZnN1dGlsIGltcG9ydCBhcHBlbmRfanNvbmwKICAgICAgICBvcy5tYWtlZGlycyhpbmJveF9kaXIoc3dhcm0pLCBleGlzdF9vaz1U" 
    "cnVlKQogICAgICAgIGFwcGVuZF9qc29ubChvcy5wYXRoLmpvaW4oaW5ib3hfZGlyKHN3YXJtKSwgIl9yZWplY3RlZC5qc29ubCIpLCByZWMpCiAgICBleGNl" 
    "cHQgT1NFcnJvcjoKICAgICAgICBwYXNzCiAgICBvdXQgPSB7Im9rIjogRmFsc2UsICJyZWplY3RlZCI6IFRydWUsICJyZWFzb24iOiByZWFzb24sCiAgICAg" 
    "ICAgICAgImZyb21fbm9kZSI6IHJlYy5nZXQoImZyb21fbm9kZSIpfQogICAgb3V0LnVwZGF0ZSh7azogdiBmb3IgaywgdiBpbiBrdy5pdGVtcygpIGlmIHYg" 
    "aXMgbm90IE5vbmV9KQogICAgcmV0dXJuIG91dAoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIGNn44CBc3Jj44CBc3Vic3lzdGVt77yI6buY6K6kIFNV" 
    "QlNZU1RFTe+8ieOAgXN3YXJt44CBc2lnbmVyc19maWxl44CBYXJjaGl2Ze+8iOm7mOiupCBUcnVl77yJ5pe277yM5L6d5qyh6K+75Y+WIHNyYyDkuLogcGFj" 
    "a+OAgV92YWxpZGF0ZSDmoKHpqozjgIHmnaXmupAgbm9kZV9pZCDkuI3nrYnkuo7mnKzoioLngrnjgIFfc2lnbmVyLnZlcmlmeV9mb3Ig6aqM562+5oiQ5Yqf" 
    "44CB5LiU5pyJ562+5ZCN5oiWIHNpZ25lciDnrYnkuo4gIm51bGwiIOaWueWPr+mAmui/h++8m+mAmui/h+WImeWvuSBwYWNrWyJpdGVtcyJdIOWJjeW4uOmH" 
    "jyBNQVhfSVRFTVMg6aG55LitIHN1YmplY3QvdGV4dCDpnZ7nqbrogIXku6UgX2lkZW50aXR5Lm9ic2VydmUg5YaZ5YWl77yI5bim5bi46YePIFRBR19YTk9E" 
    "RSDlkowgU09VUkNFX1BSRUZJWCDmoIfnrb7vvIxpbXBvcnRhbmNlIOm7mOiupCAwLjXvvIx2ZXJpZmljYXRpb25fYmFzaXMg6buY6K6kICJkYXRhIu+8ie+8" 
    "jOe7n+iuoSB3cml0dGVuL3NraXBwZWTvvIzoi6UgYXJjaGl2ZSDkuLrnnJ/liJnlhpnljIXliLDmlLbku7bnrrHvvIzov5Tlm57lkKsgb2vjgIFmcm9tX25v" 
    "ZGXjgIFwYWNrX2lk44CBaW1wb3J0ZWTjgIFza2lwcGVk44CBdHJ1bmNhdGVk44CBbm9kZV9pZHPjgIFhcmNoaXZlZCDnmoTlrZflhbjvvJvku7vkuIDmi5Ln" 
    "u53liIbmlK/osIPnlKggX25vdGVfcmVqZWN0IOi/lOWbnuaLkue7nee7k+aenOOAggpkZWYgaW1wb3J0X3BhY2soY2csIHNyYywgKiwgc3Vic3lzdGVtOiBz" 
    "dHIgPSBTVUJTWVNURU0sIHN3YXJtOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgc2lnbmVyc19maWxlOiBzdHIgPSBOb25lLCBhcmNoaXZlOiBib29s" 
    "ID0gVHJ1ZSkgLT4gZGljdDoKICAgICIiIuWvvOWFpeWvueerr+ivgeaNruWMhe+8mumqjOetviDihpIg6JC95pys5qC577yI5bimIGBzb3VyY2U6PG5vZGU+" 
    "YCDmoIfnrb7vvInjgIIKCiAgICBmYWlsLWNsb3NlZO+8mue7k+aehOS4jeWQiOazleOAgeadpea6kOWNs+acrOiKgueCueOAgemqjOetvuWksei0peOAgee8" 
    "uuetvuWQjSDihpIg5LiA5b6L5ouS5pS25bm255WZ55eV44CCCiAgICAiIiIKICAgIHRyeToKICAgICAgICBwYWNrID0gX3JlYWRfcGFjayhzcmMpCiAgICBl" 
    "eGNlcHQgKE9TRXJyb3IsIFZhbHVlRXJyb3IpIGFzIGU6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVjdCh7fSwgZiLor4Hmja7ljIXor7vlj5blpLHotKXv" 
    "vJp7ZX0iLCBzd2FybT1zd2FybSkKCiAgICBlcnIgPSBfdmFsaWRhdGUocGFjaykKICAgIGlmIGVycjoKICAgICAgICByZXR1cm4gX25vdGVfcmVqZWN0KHBh" 
    "Y2ssIGVyciwgc3dhcm09c3dhcm0pCgogICAgZnJvbV9ub2RlID0gcGFja1siZnJvbV9ub2RlIl0uc3RyaXAoKQogICAgaWYgZnJvbV9ub2RlID09IG5vZGVf" 
    "aWQoZ2V0YXR0cihjZywgInJvb3QiLCBOb25lKSk6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVjdChwYWNrLCAi6K+B5o2u5YyF5p2l5rqQ5Y2z5pys6IqC" 
    "54K577yI5ouS57ud6Ieq5a+85YWl77yJIiwgc3dhcm09c3dhcm0pCgogICAgc2lnbmF0dXJlID0gKChwYWNrLmdldCgic2lnIikgb3Ige30pLmdldCgic2ln" 
    "bmF0dXJlIikgb3IgIiIpLnN0cmlwKCkKICAgIHZyZXMgPSBfc2lnbmVyLnZlcmlmeV9mb3Ioc3Vic3lzdGVtLCBfcGFja19wYXlsb2FkKHBhY2spLCBzaWdu" 
    "YXR1cmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGFjdGlvbj1TSUdOX0FDVElPTiwgcGF0aD1zaWduZXJzX2ZpbGUpCiAgICBpZiBub3QgdnJl" 
    "cy5nZXQoIm9rIik6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVjdChwYWNrLCBmIumqjOetvuWksei0pe+8mnt2cmVzLmdldCgncmVhc29uJykgb3IgJ+ac" 
    "quefpSd9IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHN3YXJtPXN3YXJtLCBvbl9mYWlsPXZyZXMuZ2V0KCJvbl9mYWlsIikpCiAgICBpZiBub3Qg" 
    "c2lnbmF0dXJlIGFuZCAocGFjay5nZXQoInNpZyIpIG9yIHt9KS5nZXQoInNpZ25lciIpICE9ICJudWxsIjoKICAgICAgICByZXR1cm4gX25vdGVfcmVqZWN0" 
    "KHBhY2ssICLor4Hmja7ljIXnvLrlsJHnrb7lkI3vvIjot6joioLngrnor4Hmja7lv4Xpobvlj6/muq/mupDvvIkiLAogICAgICAgICAgICAgICAgICAgICAg" 
    "ICAgICAgc3dhcm09c3dhcm0pCgogICAgaXRlbXMgPSBwYWNrWyJpdGVtcyJdWzpNQVhfSVRFTVNdCiAgICB3cml0dGVuLCBza2lwcGVkID0gW10sIDAKICAg" 
    "ICM6IGlzc3VlICMyNTjvvJrmi5LmlLbnkIbnlLHnlZnnl5XvvIjmraTliY3pmY3nuqcqKuS4jeWPr+ingSoq4oCU4oCU6L+U5Zue5L2T5Y+q6K+0IGltcG9y" 
    "dGVkOiBO77yJCiAgICByZWFzb25zID0gW10KICAgIGZvciBpdCBpbiBpdGVtczoKICAgICAgICBpZiBub3QgaXNpbnN0YW5jZShpdCwgZGljdCk6CiAgICAg" 
    "ICAgICAgIHNraXBwZWQgKz0gMQogICAgICAgICAgICByZWFzb25zLmFwcGVuZCgi5p2h55uu6Z2e5a2X5YW4IikKICAgICAgICAgICAgY29udGludWUKICAg" 
    "ICAgICBzdWJqID0gKGl0LmdldCgic3ViamVjdCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgdGV4dCA9IChpdC5nZXQoInRleHQiKSBvciAiIikuc3RyaXAo" 
    "KQogICAgICAgIGlmIG5vdCBzdWJqIG9yIG5vdCB0ZXh0OgogICAgICAgICAgICBza2lwcGVkICs9IDEKICAgICAgICAgICAgcmVhc29ucy5hcHBlbmQoIuad" 
    "oeebrue8uiBzdWJqZWN0L3RleHQiKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgICMgaXNzdWUgIzI1OO+8muWvhue6pyBmYWlsLWNsb3NlZOOAgue8" 
    "uuWtl+autS/pnZ7lrZfnrKbkuLIv5pyq55+l5qGj5LiA5b6LKirkuI3lhpnnm5gqKu+8jAogICAgICAgICMg57ud5LiN5Zue6JC95YiwIERFRkFVTFRfU0VO" 
    "U0lUSVZJVFnvvIjpgqPmraPmmK/mnKzku7bnmoTnl4XosaHvvInjgILml6fmoLzlvI/ljIXvvIjml6AKICAgICAgICAjIHNlbnNpdGl2aXR577yJ5Zug5q2k" 
    "5LiA5b6L5LiN5pS24oCU4oCUKirmnInmhI/nmoTooYzkuLrlj5jmm7QqKu+8jOS4juOAjOi3qOiKgueCueivgeaNruayoeaciQogICAgICAgICMg562+5ZCN" 
    "5bCx5LiN5Y+v5rqv5rqQ77yM5a6B5Y+v5LiN5Lqn5Ye644CN5ZCM5Y+j5b6E44CCCiAgICAgICAgc2Vucywgd2h5ID0gX2l0ZW1fc2Vuc2l0aXZpdHkoaXQp" 
    "CiAgICAgICAgaWYgd2h5OgogICAgICAgICAgICBza2lwcGVkICs9IDEKICAgICAgICAgICAgcmVhc29ucy5hcHBlbmQod2h5KQogICAgICAgICAgICBjb250" 
    "aW51ZQogICAgICAgIHRhZ3MgPSBbVEFHX1hOT0RFLCBmIntTT1VSQ0VfUFJFRklYfXtmcm9tX25vZGV9Il0KICAgICAgICB0YWdzICs9IFt0IGZvciB0IGlu" 
    "IChpdC5nZXQoInRhZ3MiKSBvciBbXSkKICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKHQsIHN0cikgYW5kIHQKICAgICAgICAgICAgICAgICBhbmQg" 
    "bm90IHQuc3RhcnRzd2l0aCgic3ViamVjdDoiKQogICAgICAgICAgICAgICAgIGFuZCBub3QgdC5zdGFydHN3aXRoKFNPVVJDRV9QUkVGSVgpCiAgICAgICAg" 
    "ICAgICAgICAgYW5kIHQgbm90IGluIChUQUdfWE5PREUsIF9pZGVudGl0eS5UQUdfQU5DSE9SLCBfaWRlbnRpdHkuVEFHX1RSQUlUKV0KICAgICAgICBpbXAg" 
    "PSBpdC5nZXQoImltcG9ydGFuY2UiKQogICAgICAgIHRyeToKICAgICAgICAgICAgX2lkZW50aXR5Lm9ic2VydmUoCiAgICAgICAgICAgICAgICBjZywgc3Vi" 
    "aiwgdGV4dCwKICAgICAgICAgICAgICAgIGtpbmQ9aXQuZ2V0KCJraW5kIiksIHJvbGU9aXQuZ2V0KCJyb2xlIiksCiAgICAgICAgICAgICAgICBsYXllcj1p" 
    "dC5nZXQoImxheWVyIikgb3IgImtub3dsZWRnZSIsCiAgICAgICAgICAgICAgICB0YWdzPXRhZ3MsCiAgICAgICAgICAgICAgICBpbXBvcnRhbmNlPTAuNSBp" 
    "ZiBpbXAgaXMgTm9uZSBlbHNlIGltcCwKICAgICAgICAgICAgICAgIHZlcmlmaWNhdGlvbl9iYXNpcz1pdC5nZXQoInZlcmlmaWNhdGlvbl9iYXNpcyIpIG9y" 
    "ICJkYXRhIiwKICAgICAgICAgICAgICAgIG5vZGVfaWQ9X3hub2RlX2lkKGZyb21fbm9kZSwgaXQuZ2V0KCJub2RlX2lkIikgb3Igc3ViaiksCiAgICAgICAg" 
    "ICAgICAgICBzZW5zaXRpdml0eT1zZW5zLAogICAgICAgICAgICAgICAgb3ZlcnJpZGU9VHJ1ZSkKICAgICAgICBleGNlcHQgX0FjY2Vzc0RlbmllZDoKICAg" 
    "ICAgICAgICAgIyBpc3N1ZSAjMjU477ya5a+85YWl5pa55a+G57qn5LiN6LazIOKHkiAqKui3s+i/h++8jOS4jemZjee6p+iQveebmCoq77yI5q2k5YmN5Lya" 
    "6JC95YiwCiAgICAgICAgICAgICMg57y655yBIGludGVybmFs77yM562J5LqO5oqK5a+556uv55qEIHByaXZhdGUg5rSX5oiQIGludGVybmFs77yJ44CCCiAg" 
    "ICAgICAgICAgIHNraXBwZWQgKz0gMQogICAgICAgICAgICByZWFzb25zLmFwcGVuZCgi5pys6IqC54K55a+G57qn5LiN6Laz77yIc2Vuc2l0aXZpdHk9JXPv" 
    "vIkiICUgc2VucykKICAgICAgICAgICAgY29udGludWUKICAgICAgICB3cml0dGVuLmFwcGVuZChfeG5vZGVfaWQoZnJvbV9ub2RlLCBpdC5nZXQoIm5vZGVf" 
    "aWQiKSBvciBzdWJqKSkKCiAgICBhcmNoaXZlZCA9ICIiCiAgICBhcmNoaXZlX3NraXBwZWQgPSAiIgogICAgaWYgYXJjaGl2ZToKICAgICAgICAjIGlzc3Vl" 
    "ICMyNTjvvJrlvZLmoaPmmK8qKuaYjuaWhyBKU09OKirvvIzljIXlhoXlkKvliqDlr4bmoaPvvIhwcml2YXRlL3NlY3JldO+8ieaXtgogICAgICAgICMg5YaN" 
    "6JC95LiA5Lu95Yiw5pS25Lu2566x562J5LqO57uV6L+HIEVOQ1JZUFRFRF9MRVZFTFMg4oeSIOS4jeW9kuaho+W5tue7meWHuueQhueUseOAggogICAgICAg" 
    "IHNlYWxlZCA9IHNvcnRlZCh7aXQuZ2V0KCJzZW5zaXRpdml0eSIpIGZvciBpdCBpbiBpdGVtcwogICAgICAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0" 
    "YW5jZShpdCwgZGljdCkKICAgICAgICAgICAgICAgICAgICAgICAgIGFuZCBzdHIoaXQuZ2V0KCJzZW5zaXRpdml0eSIpIG9yICIiKS5zdHJpcCgpLmxvd2Vy" 
    "KCkKICAgICAgICAgICAgICAgICAgICAgICAgIGluIF9FTkNSWVBURURfTEVWRUxTfSkKICAgICAgICBpZiBzZWFsZWQ6CiAgICAgICAgICAgIGFyY2hpdmVf" 
    "c2tpcHBlZCA9ICgi5YyF5YaF5ZCr5Yqg5a+G5qGjICVz77ya5b2S5qGj5Li65piO5paHIEpTT07vvIwiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg" 
    "ICAi6Lez6L+H5Lul5YWN57uV6L+H6JC955uY5Yqg5a+GIiAlICLjgIEiLmpvaW4oc2VhbGVkKSkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0cnk6CiAg" 
    "ICAgICAgICAgICAgICBhcmNoaXZlZCA9IHdyaXRlX3BhY2socGFjaywgc3dhcm09c3dhcm0pWyJmaWxlIl0KICAgICAgICAgICAgZXhjZXB0IChPU0Vycm9y" 
    "LCBFdmlkZW5jZUVycm9yKToKICAgICAgICAgICAgICAgICMgaXNzdWUgIzE0N++8muW9kuaho+i2iueVjO+8iEV2aWRlbmNlRXJyb3LvvIxyZWFscGF0aCDl" 
    "hZzlupXvvInkuI7lhpnnm5gKICAgICAgICAgICAgICAgICMg5aSx6LSl5ZCM562J5aSE55CG4oCU4oCUKirkuI3pgIPpgLgqKuOAguS/ruWJjeWPquaNlSBP" 
    "U0Vycm9y77yacGFja19pZCDluKbnqboKICAgICAgICAgICAgICAgICMg5a2X6IqC5pe2IG9wZW4oKS9yZWFscGF0aCDmipvnmoQgVmFsdWVFcnJvciDkvJoq" 
    "KumAuOWHugogICAgICAgICAgICAgICAgIyBpbXBvcnRfcGFjayoq77yI5a6e5rWL77yJ77yM6LCD55So5pa55Y+q6KeB5bSp5rqD5LiU5peg55WZ55eV77yb" 
    "546w5LiA5bm25pS25Y+j44CCCiAgICAgICAgICAgICAgICBhcmNoaXZlZCA9ICIiCiAgICByZXR1cm4geyJvayI6IFRydWUsICJmcm9tX25vZGUiOiBmcm9t" 
    "X25vZGUsICJwYWNrX2lkIjogcGFjay5nZXQoInBhY2tfaWQiKSwKICAgICAgICAgICAgImltcG9ydGVkIjogbGVuKHdyaXR0ZW4pLCAic2tpcHBlZCI6IHNr" 
    "aXBwZWQsCiAgICAgICAgICAgICJ0cnVuY2F0ZWQiOiBsZW4ocGFja1siaXRlbXMiXSkgPiBNQVhfSVRFTVMsCiAgICAgICAgICAgICJub2RlX2lkcyI6IHdy" 
    "aXR0ZW4sICJhcmNoaXZlZCI6IGFyY2hpdmVkLAogICAgICAgICAgICAjIGlzc3VlICMyNTjvvJrmi5LmlLbnkIbnlLHvvIjlsIHpobYgMjAg5p2h77yM6Ziy" 
    "54GM5YyF5Yi35bGP77yJKyDlvZLmoaPot7Pov4fnkIbnlLEKICAgICAgICAgICAgInNraXBwZWRfcmVhc29ucyI6IHJlYXNvbnNbOjIwXSwKICAgICAgICAg" 
    "ICAgImFyY2hpdmVfc2tpcHBlZCI6IGFyY2hpdmVfc2tpcHBlZH0KCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMg5p+l6K+iCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIGNn44CBc3ViamVjdOOAgXNvdXJjZeOAgWxpbWl077yI6buY6K6k" 
    "IDEwMO+8ieaXtu+8jOaUtumbhuagh+etvuWQq+W4uOmHjyBUQUdfWE5PREUg55qE6IqC54K577yM6IulIHN1YmplY3Qg5Li655yf5YiZ5LuF5L+d55WZIHN1" 
    "YmplY3Qg5qCH562+562J5LqOIHN1YmplY3Qg55qE6IqC54K577yM6IulIHNvdXJjZSDkuLrnnJ/liJnku4Xkv53nlZkgc291cmNlIOagh+etvuetieS6jiBz" 
    "b3VyY2Ug55qE6IqC54K577yM6L+U5Zue5pyA5ZCOIGludChsaW1pdCBvciAxMDApIOadoeiusOW9le+8iGxpbWl0IOS4uuWBh+WAvOWmgiAwIOaXtuWPliAx" 
    "MDDvvInnmoQgY291bnQg5LiO5YiX6KGo44CCCmRlZiBldmlkZW5jZShjZywgKiwgc3ViamVjdDogc3RyID0gTm9uZSwgc291cmNlOiBzdHIgPSBOb25lLAog" 
    "ICAgICAgICAgICAgbGltaXQ6IGludCA9IDEwMCkgLT4gZGljdDoKICAgICIiIuWIl+acrOagueW3suWvvOWFpeeahOi3qOiKgueCueivgeaNru+8iOaMiead" 
    "pea6kC/kuLvkvZPov4fmu6TvvInjgIIiIiIKICAgIG91dCA9IFtdCiAgICBub2RlcyA9IGNnLmluZGV4LmdldCgibm9kZXMiKSBvciB7fQogICAgZm9yIG5p" 
    "ZCBpbiBzb3J0ZWQobm9kZXMpOgogICAgICAgIGUgPSBub2Rlc1tuaWRdCiAgICAgICAgdGcgPSBzZXQoZS5nZXQoInRhZ3MiKSBvciBbXSkKICAgICAgICBp" 
    "ZiBUQUdfWE5PREUgbm90IGluIHRnOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHN1YmosIHNyYyA9ICIiLCAiIgogICAgICAgIGZvciB0IGluIHRn" 
    "OgogICAgICAgICAgICBpZiBpc2luc3RhbmNlKHQsIHN0cikgYW5kIHQuc3RhcnRzd2l0aCgic3ViamVjdDoiKToKICAgICAgICAgICAgICAgIHN1YmogPSB0" 
    "W2xlbigic3ViamVjdDoiKTpdCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZSh0LCBzdHIpIGFuZCB0LnN0YXJ0c3dpdGgoU09VUkNFX1BSRUZJWCk6CiAg" 
    "ICAgICAgICAgICAgICBzcmMgPSB0W2xlbihTT1VSQ0VfUFJFRklYKTpdCiAgICAgICAgaWYgc3ViamVjdCBhbmQgc3ViaiAhPSBzdWJqZWN0OgogICAgICAg" 
    "ICAgICBjb250aW51ZQogICAgICAgIGlmIHNvdXJjZSBhbmQgc3JjICE9IHNvdXJjZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBub2RlID0gY2cu" 
    "Z2V0KG5pZCkgb3Ige30KICAgICAgICBvdXQuYXBwZW5kKHsibm9kZV9pZCI6IG5pZCwgInN1YmplY3QiOiBzdWJqLCAic291cmNlIjogc3JjLAogICAgICAg" 
    "ICAgICAgICAgICAgICJsYXllciI6IGUuZ2V0KCJsYXllciIpLAogICAgICAgICAgICAgICAgICAgICJjb250ZW50IjogKG5vZGUuZ2V0KCJjb250ZW50Iikg" 
    "b3IgIiIpWzo0MDBdfSkKICAgIG91dCA9IG91dFstaW50KGxpbWl0IG9yIDEwMCk6XQogICAgcmV0dXJuIHsiY291bnQiOiBsZW4ob3V0KSwgImV2aWRlbmNl" 
    "Ijogb3V0fQoKCiMg55Sf5pWI5p2h5Lu277ya5peg5Y+C5pWw6LCD55So5pe26L+U5Zue5YyF5ZCr5qih5Z2X57qn5bi46YePIFNVQlNZU1RFTeOAgVNJR05f" 
    "QUNUSU9O44CBU1dBUk1fRElSX0VOVuOAgU5PREVfSURfRU5W44CBUk9PVF9FTlbjgIFNQVhfSVRFTVPjgIFNQVhfVEVYVCDlj4ogc3dhcm1fZGlyKCkg562J" 
    "5a2X5q6155qE6Ieq5o+P6L+w5a2X5YW444CCCmRlZiBjYXRhbG9nKCkgLT4gZGljdDoKICAgIHJldHVybiB7CiAgICAgICAgImxheWVyIjogIui3qOiKgueC" 
    "ueivgeaNruWtmOWCqO+8iOicgue+pOS6kuiBlCB2MC4z77yJIiwKICAgICAgICAicXVlc3Rpb24iOiAi6Leo6IqC54K577ya5L2g5Yet5LuA5LmI6L+Z5LmI" 
    "6K+0IiwKICAgICAgICAiYmxpbmRzcG90IjogIsKnOS4xIOWNleagueWBh+iuvuKAlOKAlOWvueerr+ingua1i+WvueacrOiKgueCueS4jeWPr+ingSIsCiAg" 
    "ICAgICAgImludmFyaWFudHMiOiBbIuadpea6kOWPr+a6ryIsICLlj6/mi5LmlLYiLCAi5YWo56iL55WZ55eVIiwgIuemgeatoui9rOaJiyJdLAogICAgICAg" 
    "ICJzdWJzeXN0ZW0iOiBTVUJTWVNURU0sCiAgICAgICAgInNpZ25fYWN0aW9uIjogU0lHTl9BQ1RJT04sCiAgICAgICAgInN3YXJtX2RpciI6IHN3YXJtX2Rp" 
    "cigpLAogICAgICAgICJwYWNrX2ZpZWxkcyI6IGxpc3QoX1BBQ0tfRklFTERTKSwKICAgICAgICAibGltaXRzIjogeyJtYXhfaXRlbXMiOiBNQVhfSVRFTVMs" 
    "ICJtYXhfdGV4dCI6IE1BWF9URVhUfSwKICAgICAgICAiZW52IjogeyJub2RlX2lkIjogTk9ERV9JRF9FTlYsICJzd2FybV9kaXIiOiBTV0FSTV9ESVJfRU5W" 
    "LAogICAgICAgICAgICAgICAgInJvb3QiOiBST09UX0VOVn0sCiAgICAgICAgImhvbmVzdF9ib3VuZGFyeSI6ICLpqozor4HnmoTmmK/jgIzor4Hmja7mnaXo" 
    "h6ror6XoioLngrnjgI3vvIzkuI3mmK/jgIzor4Hmja7kuLrnnJ/jgI0iLAogICAgfQoKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDlt6XlhbcKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t" 
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgcGF0aCDlkowgb2JqIOaXtu+8jOWcqCBwYXRo" 
    "IOaJgOWcqOebruW9le+8iOiLpSBkaXJuYW1lIOS4uuepuuWImSAiLiLvvInliJvlu7rnm67lvZXvvIzlsIYgb2JqIOS7pSBKU09OIOWGmeWFpSBwYXRoKyIu" 
    "dG1wIu+8iGVuc3VyZV9hc2NpaT1GYWxzZSwgaW5kZW50PTEsIHNvcnRfa2V5cz1UcnVl77yJ77yM5bCd6K+VIGNobW9kIDA2MDDvvIzmm7/mjaLliLAgcGF0" 
    "aO+8jOi/lOWbniBwYXRo44CCCmRlZiBfd3JpdGVfanNvbihwYXRoOiBzdHIsIG9iaikgLT4gc3RyOgogICAgb3MubWFrZWRpcnMob3MucGF0aC5kaXJuYW1l" 
    "KHBhdGgpIG9yICIuIiwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHRtcCA9IHBhdGggKyAiLnRtcCIKICAgIHdpdGggb3Blbih0bXAsICJ3IiwgZW5jb2Rpbmc9InV0" 
    "Zi04IikgYXMgZjoKICAgICAgICBqc29uLmR1bXAob2JqLCBmLCBlbnN1cmVfYXNjaWk9RmFsc2UsIGluZGVudD0xLCBzb3J0X2tleXM9VHJ1ZSkKICAgIHRy" 
    "eToKICAgICAgICBvcy5jaG1vZCh0bXAsIDBvNjAwKQogICAgZXhjZXB0IE9TRXJyb3I6CiAgICAgICAgcGFzcwogICAgcHVibGlzaCh0bXAsIHBhdGgpCiAg" 
    "ICByZXR1cm4gcGF0aAoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHJvb3Qg5LiUIF9yb290X29mKHJvb3QpIOi/lOWbnuecn+WAvOaXtu+8jOS7pSBk" 
    "ZXNpZ25lciDop5LoibIgUHJpbmNpcGFs77yIdGVuYW50IOWPliBvcy5lbnZpcm9uLmdldCgiTURDR19URU5BTlQiLCAiZGVmYXVsdCIpIOeahOWunumZheWA" 
    "vO+8jGFjdG9yIOWPliBvcy5lbnZpcm9uLmdldCgiTURDR19BQ1RPUiIsICJzd2FybS1jbGkiKSDnmoTlrp7pmYXlgLzvvInmiZPlvIAgTWRDR1NlY3VyZe+8" 
    "m+WQpuWImeaKm+WHuiBFdmlkZW5jZUVycm9y44CCCmRlZiBfb3Blbl9jZyhyb290OiBzdHIgPSBOb25lKToKICAgICIiIkNMSSDnlKjvvJrku6UgZGVzaWdu" 
    "ZXIg6Lqr5Lu95omT5byA5qC577yI5Luk54mM6Lev5b6E5LuN5o6o6I2Q6LWwIE1DUO+8ieOAgiIiIgogICAgZnJvbSAubWRjb3MgaW1wb3J0IE1kQ0dTZWN1" 
    "cmUKICAgIGZyb20gLnNlY3VyaXR5IGltcG9ydCBQcmluY2lwYWwKICAgIGZyb20gLnRva2VucyBpbXBvcnQgcm9sZV9zcGVjCiAgICByID0gX3Jvb3Rfb2Yo" 
    "cm9vdCkKICAgIGlmIG5vdCByOgogICAgICAgIHJhaXNlIEV2aWRlbmNlRXJyb3IoIue8uuWwkeagueebruW9le+8muivt+iuviBNRENHX1JPT1Qg5oiW5Lyg" 
    "IC0tcm9vdCIpCiAgICBzcGVjID0gcm9sZV9zcGVjKCJkZXNpZ25lciIpCiAgICBwID0gUHJpbmNpcGFsKHRlbmFudD1vcy5lbnZpcm9uLmdldCgiTURDR19U" 
    "RU5BTlQiLCAiZGVmYXVsdCIpLAogICAgICAgICAgICAgICAgICBhY3Rvcj1vcy5lbnZpcm9uLmdldCgiTURDR19BQ1RPUiIsICJzd2FybS1jbGkiKSwKICAg" 
    "ICAgICAgICAgICAgICAgY2xlYXJhbmNlPSJwcml2YXRlIiwgY2FuX3dyaXRlPVRydWUsIGNhbl9hZG1pbj1UcnVlLAogICAgICAgICAgICAgICAgICByb2xl" 
    "PSJkZXNpZ25lciIsIGxheWVyc19hbGxvdz1zcGVjWyJsYXllcnNfYWxsb3ciXSwKICAgICAgICAgICAgICAgICAgb3BzX2FsbG93PXNwZWNbIm9wc19hbGxv" 
    "dyJdLCBhdXRoX21vZGU9ImxlZ2FjeV9lbnYiKQogICAgIyBhdXRvZmx1c2g9Me+8iFAxYu+8jDIwMjYtMDktMjbvvIzkuI4gbWNwX3NlcnZlci5weTozNjk1" 
    "LTM3MDIgLyByZXZpZXdfY2xpLl9jZwogICAgIyDlkIzmrL7vvInvvJrnn63lkb3lt6Xlhbfov5vnqIvooqsga2lsbCDml7YgY2xvc2UvYXRleGl0IOWFnOW6" 
    "leS4jeaJp+ihjO+8jOe8uuecgSA2NCDkvJrorqkKICAgICMg5YaZ5YWl5YGc5Zyo5YaF5a2YIF9kaXJ0eeOAgeWIhueJh+aXpeW/l+S7juacquiQveKAlOKA" 
    "lOmAkOadoeiQveaXpeW/l+S/neS7u+aEj+mAgOWHuuW9ouaAgei3qOi/m+eoi+WPr+ingeOAggogICAgcmV0dXJuIE1kQ0dTZWN1cmUociwgcHJpbmNpcGFs" 
    "PXAsIGF1dG9mbHVzaD0xKQoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIG9iaiDml7bvvIzmiZPljbAganNvbi5kdW1wcyhvYmosIGVuc3VyZV9hc2Np" 
    "aT1GYWxzZSwgaW5kZW50PTEsIGRlZmF1bHQ9c3RyKeOAggpkZWYgX3ByaW50KG9iaik6CiAgICBwcmludChqc29uLmR1bXBzKG9iaiwgZW5zdXJlX2FzY2lp" 
    "PUZhbHNlLCBpbmRlbnQ9MSwgZGVmYXVsdD1zdHIpKQoKCiMg55Sf5pWI5p2h5Lu277yaYXJndiDkuLogTm9uZSDml7blj5Ygc3lzLmFyZ3ZbMTpd77yb57uP" 
    "IGFyZ3BhcnNlIOino+aekOWQjuW/heWhq+WtkOWRveS7pO+8iGNhdGFsb2cvY2FyZC9leHBvcnQvaW1wb3J0IOetie+8ieS5i+S4gO+8jOWPguaVsOe8uuWk" 
    "seaIlumdnuazleeUsSBhcmdwYXJzZSDnm7TmjqXpgIDlh7rvvJvov5Tlm57ov5vnqIvpgIDlh7rnoIHvvJsKZGVmIG1haW4oYXJndj1Ob25lKToKICAgIGFw" 
    "ID0gYXJncGFyc2UuQXJndW1lbnRQYXJzZXIoCiAgICAgICAgcHJvZz0icHl0aG9uIC1tIG1kX2NnLmV2aWRlbmNlIiwKICAgICAgICBkZXNjcmlwdGlvbj0i" 
    "6Leo6IqC54K56K+B5o2u5a2Y5YKo77ya5ZCN54mHIC8g5a+85Ye6IC8g5a+85YWl77yIdjAuM++8iSIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tcm9vdCIs" 
    "IGRlZmF1bHQ9Tm9uZSwgaGVscD0i6K6k55+l5Zu+5qC577yI6buY6K6kIE1EQ0dfUk9PVO+8iSIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tc3dhcm0iLCBk" 
    "ZWZhdWx0PU5vbmUsIGhlbHA9IuWFseS6q+ebruW9le+8iOm7mOiupCB+Ly5tZGNnL3N3YXJt77yJIikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1zaWduZXJz" 
    "LWZpbGUiLCBkZWZhdWx0PU5vbmUpCiAgICBzdWIgPSBhcC5hZGRfc3VicGFyc2VycyhkZXN0PSJjbWQiLCByZXF1aXJlZD1UcnVlKQoKICAgIHN1Yi5hZGRf" 
    "cGFyc2VyKCJjYXRhbG9nIiwgaGVscD0i6Ieq5o+P6L+wIikKICAgIHN1Yi5hZGRfcGFyc2VyKCJjYXJkIiwgaGVscD0i5pys6IqC54K55ZCN54mHIikKICAg" 
    "IHN1Yi5hZGRfcGFyc2VyKCJwdWJsaXNoIiwgaGVscD0i5Y+R5biD5ZCN54mH5Yiw5YWx5Lqr55uu5b2VIikKICAgIHN1Yi5hZGRfcGFyc2VyKCJwZWVycyIs" 
    "IGhlbHA9IuWPkeeOsOWvueerr+WQjeeJhyIpCgogICAgcF9leCA9IHN1Yi5hZGRfcGFyc2VyKCJleHBvcnQiLCBoZWxwPSLlr7zlh7ror4Hmja7ljIUiKQog" 
    "ICAgcF9leC5hZGRfYXJndW1lbnQoIi0tc3ViamVjdCIsIGFjdGlvbj0iYXBwZW5kIiwgZGVmYXVsdD1Ob25lKQogICAgcF9leC5hZGRfYXJndW1lbnQoIi0t" 
    "b3V0IiwgZGVmYXVsdD1Ob25lLCBoZWxwPSLovpPlh7rmlofku7bvvIjpu5jorqTlhpnmlLbku7bnrrHvvIkiKQoKICAgIHBfaW0gPSBzdWIuYWRkX3BhcnNl" 
    "cigiaW1wb3J0IiwgaGVscD0i5a+85YWl6K+B5o2u5YyFIikKICAgIHBfaW0uYWRkX2FyZ3VtZW50KCJwYXRoIikKCiAgICBwX2xzID0gc3ViLmFkZF9wYXJz" 
    "ZXIoImxzIiwgaGVscD0i5YiX5bey5a+85YWl55qE6Leo6IqC54K56K+B5o2uIikKICAgIHBfbHMuYWRkX2FyZ3VtZW50KCItLXN1YmplY3QiLCBkZWZhdWx0" 
    "PU5vbmUpCiAgICBwX2xzLmFkZF9hcmd1bWVudCgiLS1zb3VyY2UiLCBkZWZhdWx0PU5vbmUpCiAgICBwX2xzLmFkZF9hcmd1bWVudCgiLS1saW1pdCIsIHR5" 
    "cGU9aW50LCBkZWZhdWx0PTEwMCkKCiAgICBhID0gYXAucGFyc2VfYXJncyhhcmd2KQogICAgY2cgPSBOb25lCiAgICB0cnk6CiAgICAgICAgaWYgYS5jbWQg" 
    "PT0gImNhdGFsb2ciOgogICAgICAgICAgICBfcHJpbnQoY2F0YWxvZygpKQogICAgICAgIGVsaWYgYS5jbWQgPT0gImNhcmQiOgogICAgICAgICAgICBfcHJp" 
    "bnQoY2FyZChhLnJvb3QsIHNpZ25lcnNfZmlsZT1hLnNpZ25lcnNfZmlsZSkpCiAgICAgICAgZWxpZiBhLmNtZCA9PSAicHVibGlzaCI6CiAgICAgICAgICAg" 
    "IF9wcmludChwdWJsaXNoX2NhcmQoYS5yb290LCBzd2FybT1hLnN3YXJtLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNpZ25lcnNfZmlsZT1h" 
    "LnNpZ25lcnNfZmlsZSkpCiAgICAgICAgZWxpZiBhLmNtZCA9PSAicGVlcnMiOgogICAgICAgICAgICBfcHJpbnQocGVlcnMoYS5zd2FybSwgcm9vdD1hLnJv" 
    "b3QpKQogICAgICAgIGVsaWYgYS5jbWQgPT0gImV4cG9ydCI6CiAgICAgICAgICAgIGNnID0gX29wZW5fY2coYS5yb290KQogICAgICAgICAgICByZXMgPSBl" 
    "eHBvcnRfcGFjayhjZywgc3ViamVjdHM9YS5zdWJqZWN0LCBzd2FybT1hLnN3YXJtLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzaWduZXJzX2Zp" 
    "bGU9YS5zaWduZXJzX2ZpbGUpCiAgICAgICAgICAgIF9wcmludCh3cml0ZV9wYWNrKHJlc1sicGFjayJdLCBwYXRoPWEub3V0LCBzd2FybT1hLnN3YXJtKQog" 
    "ICAgICAgICAgICAgICAgICAgaWYgYS5vdXQgZWxzZSByZXMpCiAgICAgICAgZWxpZiBhLmNtZCA9PSAiaW1wb3J0IjoKICAgICAgICAgICAgY2cgPSBfb3Bl" 
    "bl9jZyhhLnJvb3QpCiAgICAgICAgICAgIF9wcmludChpbXBvcnRfcGFjayhjZywgYS5wYXRoLCBzd2FybT1hLnN3YXJtLAogICAgICAgICAgICAgICAgICAg" 
    "ICAgICAgICAgICAgc2lnbmVyc19maWxlPWEuc2lnbmVyc19maWxlKSkKICAgICAgICBlbGlmIGEuY21kID09ICJscyI6CiAgICAgICAgICAgIGNnID0gX29w" 
    "ZW5fY2coYS5yb290KQogICAgICAgICAgICBfcHJpbnQoZXZpZGVuY2UoY2csIHN1YmplY3Q9YS5zdWJqZWN0LCBzb3VyY2U9YS5zb3VyY2UsCiAgICAgICAg" 
    "ICAgICAgICAgICAgICAgICAgICBsaW1pdD1hLmxpbWl0KSkKICAgIGV4Y2VwdCAoRXZpZGVuY2VFcnJvciwgX3NpZ25lci5TaWduZXJFcnJvcikgYXMgZToK" 
    "ICAgICAgICBwcmludChmIlttZF9jZy5ldmlkZW5jZV0ge2V9IiwgZmlsZT1zeXMuc3RkZXJyKQogICAgICAgIHJldHVybiAyCiAgICBmaW5hbGx5OgogICAg" 
    "ICAgIGlmIGNnIGlzIG5vdCBOb25lOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjZy5jbG9zZSgpICAgICAgICAgICMg6JC955uY57Si5byV" 
    "77yM5L+d6K+B6Leo6L+b56iL5Y+v6KeBCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246ICAgICAgICMgbm9xYTogQkxFMDAxIOKAlOKAlCDlhbPpl63l" 
    "pLHotKXkuI3mjqnnm5bkuLvmtYHnqIvnu5PmnpwKICAgICAgICAgICAgICAgIHBhc3MKICAgIHJldHVybiAwCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9f" 
    "IjoKICAgIHN5cy5leGl0KG1haW4oKSk="
)


def _before_source():
    """取修复前源。git 历史里若是「修复后源」就回落内嵌夹具（fail-closed，不 SKIP）。

    why：CI 的 pull/<n>/merge 提交**已含本件修复**，`git show HEAD:` 拿到的是修复后
    源；浅克隆下祖先提交也不可得。两条路都走不通时用内嵌夹具，判据仍按同一组锚点
    校验 —— 不放松、不降级。
    """
    notes = []
    try:
        out = subprocess.run(["git", "show", "HEAD:" + _REL], cwd=_REPO,
                             capture_output=True, timeout=30)
        if out.returncode == 0:
            src = out.stdout.decode("utf-8", "replace")
            if _MARK not in src:
                return src, "HEAD（本改动尚未提交）"
            notes.append("HEAD 已是修复后源")
        else:
            notes.append("git show HEAD 返回 %d" % out.returncode)
    except Exception as e:
        notes.append("git show HEAD 异常 %s" % type(e).__name__)
    try:
        src = _b64.b64decode("".join(_BEFORE_B64.split())).decode("utf-8")
        if _MARK in src:
            return None, "内嵌夹具竟含本件标记（夹具自检失败）"
        return src, "内嵌夹具（%s）" % "；".join(notes)
    except Exception as e:
        return None, "内嵌夹具解码失败 %s: %s（%s）" % (
            type(e).__name__, e, "；".join(notes))


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


def s11_whole_pack_gate():
    """S11 ★ 归档闸扫整包：切片外的加密档条目也要挡住收件箱（明文归档绕过）。

    审计发现（@ybyz2 对 #260 的复核指出的真缺口）：归档写的是 write_pack(pack)
    即**整包明文 JSON**，而闸只扫 pack["items"][:MAX_ITEMS]。构造「头部 MAX_ITEMS
    条全 internal、尾部 1 条 private」的包，切片内 sealed 为空 => 原实现照常归档，
    尾部私密正文随整包明文落进收件箱。
    """
    cg = _fresh("s11")
    items = [_item("n%d" % i, "t%d" % i, sens="internal")
             for i in range(ev.MAX_ITEMS)]
    items.append(_item("ntail", "TAIL-SECRET-BODY", sens="private"))
    pack = _pack("peer-tail", items, created_at=3000.0, pack_id="pack-tailtailtail")
    out = ev.import_pack(cg, _write(pack), swarm=os.environ["MDCG_SWARM_DIR"])
    _check("S11.1 ★ 切片外 private 条目挡住归档（整包判据）",
           not out.get("archived") and bool(out.get("archive_skipped")),
           "archived=%r skipped=%r" % (out.get("archived"),
                                       (out.get("archive_skipped") or "")[:40]))
    _check("S11.2 ★ 整包判据直接可调用且为 True",
           ev._pack_has_unarchivable(pack) is True,
           str(ev._pack_has_unarchivable(pack)))
    clean = _pack("peer-clean", [_item("na", "b")], created_at=3001.0,
                  pack_id="pack-cleanclean")
    _check("S11.3 阴性对照：全 internal 的包不误挡",
           ev._pack_has_unarchivable(clean) is False,
           str(ev._pack_has_unarchivable(clean)))
    naked = {"node_id": "nx", "subject": "bob", "text": "x"}
    # 判不了档位的条目**不单独挡归档** —— 这是 main 已落地的既有行为（#147 G2 的合法包
    # 不带 sensitivity 且必须照常归档），本件只把扫描面从切片扩到整包，不改这条。
    _check("S11.4 判不了档位的条目不单独挡归档（与 main 既有行为一致）",
           ev._pack_has_unarchivable(_pack("peer-naked", [naked])) is False,
           "缺 sensitivity 字段")
    _check("S11.5 非 dict 条目不单独挡归档",
           ev._pack_has_unarchivable(_pack("peer-junk", ["not-a-dict"])) is False, ""
           )
    _check("S11.6 ★ 判不了档位的条目在**切片外**也不致漏扫加密档",
           ev._pack_sealed_levels(_pack("peer-mix", [naked, _item("nz", "z", sens="secret")]))
           == ["secret"],
           str(ev._pack_sealed_levels(_pack("peer-mix",
                                      [naked, _item("nz", "z", sens="secret")]))))


_GROUPS = (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4), ("S5", s5),
           ("S6", s6), ("S7", s7), ("S8", s8), ("S9", s9), ("S10", s10),
           ("S11", s11_whole_pack_gate))


def main():
    if _MARK not in open(os.path.join(_REPO, _REL), encoding="utf-8").read():
        print("SOURCE-ALREADY-MUTATED：%s 不含本件标记，先恢复到修复版再跑" % _REL)
        return 2
    want = [a for a in sys.argv[1:] if a.startswith("S")]
    groups = [g for g in _GROUPS if not want or any(g[0].startswith(w) for w in want)]
    for gid, fn in groups:
        print("[%s]" % gid)
        try:
            fn()
        except Exception as e:
            _check("%s 组内异常：%s: %s" % (gid, type(e).__name__, e), False, "")
    print("对端证据包导入范围守卫（issue #191）：通过 %d / 失败 %d"
          % (len(_OK), len(_BAD)))
    return 0 if not _BAD else 1


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
    for name in ("_import_importance", "_seen_load", "_seen_save", "_seen_path",
                 "_pack_sealed_levels", "_pack_has_unarchivable"):
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


_MUTATIONS = (
    ("V1 落层白名单被去掉（对端 layer 原样透传）",
     "        if layer not in IMPORT_LAYERS:\n            layer = \"knowledge\"\n            clamped += 1\n",
     "        pass\n",
     "S2"),
    ("V2 重要度不再夹取（对端可自行顶到保护线以上）",
     "    return min(max(float(raw), 0.0), IMPORT_IMPORTANCE_MAX)\n",
     "    return float(raw)\n",
     "S3"),
    ("V3 created_at 版本闸被去掉（旧包回滚已入库证据）",
     "and created <= float(last):\n",
     "and False:\n",
     "S5"),
    ("V4 版本闸方向反转（新包被判为旧包）",
     "and created <= float(last):\n",
     "and created >= float(last):\n",
     "S5"),
    ("V5 本地节点覆写闸被去掉（同名本地节点被覆盖）",
     "        if cur is not None and TAG_XNODE not in (cur.get(\"tags\") or []):\n",
     "        if False:\n",
     "S8"),
    ("V6 seen 落盘被跳过（跨进程/跨实例记忆失效）",
     "    _seen_save(cg, seen)\n",
     "    pass\n",
     "S5"),
    ("V7 归档闸退回「只扫已写盘切片」",
     "        sealed = _pack_sealed_levels(pack)\n",
     "        sealed = sorted(set(_item_sensitivity(x)[0] for x in items\n"
     "                        if isinstance(x, dict)) & _ENCRYPTED_LEVELS)\n",
     "S11"),
)


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
