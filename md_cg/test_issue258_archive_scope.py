# -*- coding: utf-8 -*-
"""跨节点证据包**归档面**守卫（issue #258 补丁 / issue #191 同族）

【守什么】**归档的扫描面必须与落盘面一致**。

病灶：`import_pack` 的归档闸只扫 `pack["items"][:MAX_ITEMS]`（常量切片），
而 `write_pack(pack)` 写出去的是**整包**。于是「头部 500 条全 internal、
第 501 条 private」的包：切片内判不出加密档 ⇒ 闸放行 ⇒ 整包（含 private）
以明文 JSON 落进收件箱，且 `archive_skipped` 为空串——连留痕都没有。

修法：新增 `_pack_sealed_levels(pack)` 扫整包，归档闸改调它；
`_pack_has_unarchivable(pack)` 为薄封装供本守卫直接调用。

判据：
  S1 整包扫描函数在位、语义正确（含档位归一、非 dict / 非 list 的 fail-closed）
  S2 ★ 切片外 private 条目必须挡住归档（本件核心）
  S3 ★ 切片外 secret 条目同样挡住
  S4 阴性对照：全 internal 整包照常归档（不误挡）
  S5 判不了档位的条目不单独挡归档（与 main 既有行为一致）
  S6 非 dict 条目不单独挡归档
  S7 切片内加密档仍然挡住（既有行为未回归）
  S8 归档判据与落盘面一致：`write_pack` 写出的 JSON 里确实含那个加密档条目
  S9 留痕：挡下时必须给出非空 `archive_skipped` 且含档位名
  S10 判别力：修复前源原形（无 `_pack_sealed_levels`）自证——历史不可用时回落内嵌夹具

运行：python -X utf8 -m md_cg.test_issue258_archive_scope
      python -X utf8 -m md_cg.test_issue258_archive_scope --mutate=V1   # 定点变异自证
      退出码：0 全绿 / 1 有红 / 2 盘上源自检不过（残留变异体或加载模块与源不一致）
"""
import base64 as _b64
import io
import os
import sys
import tempfile
import shutil

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REL = os.path.join("md_cg", "evidence.py")
_SRC_PATH = os.path.join(_REPO, _REL)

_OK = []
_BAD = []


def _check(name, cond, detail=""):
    (_OK if cond else _BAD).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + ("  " + str(detail) if detail else ""))


def _fresh(tag):
    root = tempfile.mkdtemp(prefix="a258s_" + tag + "_")
    mem = os.path.join(root, "mem")
    swarm = os.path.join(root, "swarm")
    os.makedirs(mem, exist_ok=True)
    os.makedirs(swarm, exist_ok=True)
    return root, mem, swarm


def _fake_pack(items, pack_id, *, from_node="peer-a", created_at=1.0):
    import md_cg.evidence as ev
    return {"schema": ev.SCHEMA, "kind": ev.KIND, "from_node": from_node,
            "from_root": "/peer", "theory": "", "created_at": created_at,
            "subjects": [], "items": items, "pack_id": pack_id,
            "sig": {"signer": "null", "signature": "", "signed": False}}


def _item(nid, text, *, sens="internal"):
    d = {"node_id": nid, "subject": nid, "text": text, "layer": "knowledge"}
    if sens is not None:
        d["sensitivity"] = sens
    return d


def _with_env(mem, swarm):
    saved = {}
    for k in list(os.environ):
        if k.startswith("MDCG_") or k.startswith("PYTHON"):
            saved[k] = os.environ.pop(k)
    os.environ["MDCG_ROOT"] = mem
    os.environ["MDCG_SWARM_DIR"] = swarm
    return saved


def _restore_env(saved):
    for k in ("MDCG_ROOT", "MDCG_SWARM_DIR"):
        os.environ.pop(k, None)
    os.environ.update(saved)


def _import(pack, mem, swarm):
    import json
    import md_cg.evidence as ev
    p = os.path.join(os.path.dirname(mem), pack["pack_id"] + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False)
    return ev.import_pack(_cg(mem), p, swarm=swarm)


def _cg(mem):
    from md_cg.mdcos import MdCGOS
    return MdCGOS(mem)


def s1_scan_surface():
    import md_cg.evidence as ev
    _check("S1.1 整包扫描函数在位", callable(getattr(ev, "_pack_sealed_levels", None)))
    _check("S1.2 薄封装在位", callable(getattr(ev, "_pack_has_unarchivable", None)))
    try:
        sig = ev._pack_sealed_levels({"items": [{"sensitivity": "PRIVATE "}]})
        ok = sig == ["private"]
        det = "归一大写+空白 -> %r" % (sig,)
    except Exception as e:
        ok, det = False, "异常 %r" % (e,)
    _check("S1.3 档位归一（大写/空白）后仍判为加密档", ok, det)
    _check("S1.4 pack 非 dict 时 fail-closed",
           ev._pack_sealed_levels(None) != [] and ev._pack_sealed_levels([]) != [])
    _check("S1.5 items 非 list 时 fail-closed",
           ev._pack_sealed_levels({"items": "x"}) != [])


def s2_tail_private_blocks():
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s2")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("n%d" % i, "t%d" % i) for i in range(ev.MAX_ITEMS)]
        items.append(_item("ntail", "TAIL-PRIVATE-BODY", sens="private"))
        pack = _fake_pack(items, "pack-tail-private")
        r = _import(pack, mem, swarm)
        _check("S2.1 ★ 切片外 private 条目挡住归档",
               r.get("ok") and not r.get("archived"),
               "archived=%r skipped=%r" % (r.get("archived"), r.get("archive_skipped")))
        _check("S2.2 ★ 整包判据直接判为不可归档",
               ev._pack_has_unarchivable(pack) is True)
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s3_tail_secret_blocks():
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s3")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("n%d" % i, "t%d" % i) for i in range(ev.MAX_ITEMS)]
        items.append(_item("ntail", "TAIL-SECRET-BODY", sens="secret"))
        pack = _fake_pack(items, "pack-tail-secret")
        r = _import(pack, mem, swarm)
        _check("S3.1 ★ 切片外 secret 条目挡住归档",
               r.get("ok") and not r.get("archived"),
               "archived=%r" % (r.get("archived"),))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s4_negative_control():
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s4")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("m%d" % i, "t%d" % i) for i in range(3)]
        pack = _fake_pack(items, "pack-allint")
        r = _import(pack, mem, swarm)
        _check("S4.1 阴性对照：全 internal 照常归档", bool(r.get("archived")),
               "archived=%r" % (r.get("archived"),))
        _check("S4.2 阴性对照：整包判据为 False",
               ev._pack_has_unarchivable(pack) is False)
        _check("S4.3 阴性对照：archive_skipped 为空",
               (r.get("archive_skipped") or "") == "")
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s5_undecidable_not_blocking():
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s5")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("m%d" % i, "t%d" % i) for i in range(2)]
        items.append(_item("nund", "x", sens=None))
        pack = _fake_pack(items, "pack-undecidable")
        r = _import(pack, mem, swarm)
        _check("S5.1 判不了档位的条目不单独挡归档（与 main 既有行为一致）",
               bool(r.get("archived")),
               "archived=%r skipped=%r" % (r.get("archived"), r.get("archive_skipped")))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s6_nondict_not_blocking():
    root, mem, swarm = _fresh("s6")
    saved = _with_env(mem, swarm)
    try:
        pack = _fake_pack([_item("m0", "t0"), "not-a-dict"], "pack-nondict")
        r = _import(pack, mem, swarm)
        _check("S6.1 非 dict 条目不单独挡归档", bool(r.get("archived")),
               "archived=%r" % (r.get("archived"),))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s7_in_slice_still_blocks():
    root, mem, swarm = _fresh("s7")
    saved = _with_env(mem, swarm)
    try:
        pack = _fake_pack([_item("m0", "t0", sens="private")], "pack-in-slice")
        r = _import(pack, mem, swarm)
        _check("S7.1 切片内加密档仍然挡住（既有行为未回归）",
               r.get("ok") and not r.get("archived"),
               "archived=%r" % (r.get("archived"),))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s8_matches_written_bytes():
    """落盘面自证：write_pack 写出的 JSON 里确实含那个加密档条目。"""
    import json
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s8")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("n%d" % i, "t%d" % i) for i in range(ev.MAX_ITEMS)]
        items.append(_item("ntail", "TAIL-PRIVATE-BODY", sens="private"))
        pack = _fake_pack(items, "pack-written")
        out = ev.write_pack(pack, swarm=swarm)["file"]
        with open(out, encoding="utf-8") as f:
            written = json.load(f)
        n = len(written.get("items") or [])
        _check("S8.1 落盘面自证：write_pack 写出的是整包（含切片外条目）",
               n > ev.MAX_ITEMS, "written_items=%d MAX_ITEMS=%d" % (n, ev.MAX_ITEMS))
        tail_sens = (written["items"][-1] or {}).get("sensitivity")
        _check("S8.2 落盘面自证：被写出的尾部条目正是加密档",
               tail_sens == "private", "tail_sensitivity=%r" % (tail_sens,))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


def s9_reason_retained():
    import md_cg.evidence as ev
    root, mem, swarm = _fresh("s9")
    saved = _with_env(mem, swarm)
    try:
        items = [_item("n%d" % i, "t%d" % i) for i in range(ev.MAX_ITEMS)]
        items.append(_item("ntail", "TAIL-PRIVATE-BODY", sens="private"))
        r = _import(_fake_pack(items, "pack-reason"), mem, swarm)
        why = r.get("archive_skipped") or ""
        _check("S9.1 挡下时给出非空 archive_skipped 理由", bool(why), "why=%r" % (why,))
        _check("S9.2 理由里点名具体档位", "private" in why, "why=%r" % (why,))
    finally:
        _restore_env(saved)
        shutil.rmtree(root, ignore_errors=True)


_BEFORE_MARK = "_pack_sealed_levels"


def _before_source():
    """修复前源（无 _pack_sealed_levels）-> (源码文本, 来源说明)。取不到返回 (None, 原因)。"""
    import subprocess
    try:
        r = subprocess.run(["git", "show", "HEAD:" + _REL], cwd=_REPO,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        if r.returncode == 0 and r.stdout:
            if _BEFORE_MARK not in r.stdout:
                return r.stdout, "git show HEAD"
            note = "HEAD 已是修复后源"
        else:
            note = "git show HEAD 返回 %s" % r.returncode
    except Exception as e:
        note = "git 不可用：%r" % (e,)
    try:
        src = _b64.b64decode("".join(_BEFORE_B64.split())).decode("utf-8")
    except Exception as e:
        return None, "内嵌夹具解码失败：%r" % (e,)
    if _BEFORE_MARK in src:
        return None, "内嵌夹具竟含本件标记（夹具自检失败）"
    return src, "内嵌夹具（%s）" % note


def s10_power():
    src, why = _before_source()
    ok = bool(src)
    _check("S10a 修复前源可得（无本件标记）", ok, why)
    if not ok:
        _check("S10b 修复前源确无整包判据", False, "源不可得")
        _check("S10c 修复前源确无薄封装", False, "源不可得")
        return
    _check("S10b 修复前源确无整包判据", "def _pack_sealed_levels" not in src)
    _check("S10c 修复前源确无薄封装", "def _pack_has_unarchivable" not in src)


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
    "bgppbXBvcnQgbWF0aAppbXBvcnQgb3MKaW1wb3J0IHN5cwppbXBvcnQgdGltZQoKZnJvbSAuIGltcG9ydCBjcnlwdG8gYXMgX2NyeXB0bwpmcm9tIC4gaW1w"
    "b3J0IGlkZW50aXR5IGFzIF9pZGVudGl0eQpmcm9tIC4gaW1wb3J0IHNlY3VyaXR5IGFzIF9zZWMKZnJvbSAuIGltcG9ydCBzaWduZXIgYXMgX3NpZ25lcgpm"
    "cm9tIC5kYXRhcGF0aCBpbXBvcnQgYXV4X3Jvb3QKZnJvbSAuZnN1dGlsIGltcG9ydCBwdWJsaXNoCgpOT0RFX0lEX0VOViA9ICJNRENHX05PREVfSUQiClNX"
    "QVJNX0RJUl9FTlYgPSAiTURDR19TV0FSTV9ESVIiClJPT1RfRU5WID0gIk1EQ0dfUk9PVCIKCkRFRkFVTFRfRElSID0gYXV4X3Jvb3QoKQpERUZBVUxUX1NX"
    "QVJNX0RJUiA9IG9zLnBhdGguam9pbihERUZBVUxUX0RJUiwgInN3YXJtIikKClNVQlNZU1RFTSA9ICJzd2FybSIgICAgICAgICAgIyDlrZDns7vnu5/lkI3v"
    "vJrmmbrog73kvZPlj6/lr7nlroPlo7DmmI7nrb7lkI3nrZbnlaXvvIhELTTvvIkKU0lHTl9BQ1RJT04gPSAiZXZpZGVuY2UiClNDSEVNQSA9IDEKS0lORCA9"
    "ICJtZGNnLmV2aWRlbmNlLnBhY2siCkNBUkRfS0lORCA9ICJtZGNnLm5vZGUuY2FyZCIKClRBR19YTk9ERSA9ICJ4bm9kZTpjcm9zcyIKU09VUkNFX1BSRUZJ"
    "WCA9ICJzb3VyY2U6IgoKIyAtLS0tIGlzc3VlICMxOTHvvJrlr7zlhaXkvqfnmoTlsYIv6YeN6KaB5bqm5aS557Sn5LiO5pen5YyF6YeN5pS+5Y+w6LSm77yI"
    "5LiJ5aSE5pS25Y+j77yJIC0tLS0KIzog6JC95bGC55m95ZCN5Y2V77ya5a+556uv5aOw5piOKirkuI3lvpcqKuiHqumAieWPl+S/neaKpOWxgu+8iHByb3Rl"
    "Y3QuUFJPVEVDVEVEX0xBWUVSUyA9IHNlbGYvYW5jaG9y77yJCiM6IOaIliBnb2Fscy9zdHJ1Y3R1cmFsIOS4gOexu+eJueauiuWxgu+8jOS4gOW+i+aUueiQ"
    "vSBrbm93bGVkZ2XjgIIKSU1QT1JUX0xBWUVSUyA9ICgia25vd2xlZGdlIiwgImNvbnRleHR1YWwiKQojOiDlr7zlhaXph43opoHluqbkuIrpmZDjgIIqKuW/"
    "hemhu+S9juS6jioqIHByb3RlY3QuQVVUT19QUk9URUNUX0lNUE9SVEFOQ0XvvIgwLjcw77yJ4oCU4oCU5ZCm5YiZ5a+556uvCiM6IOS4gOadoeWjsOaYjuWw"
    "seiDveaKiuiKgueCueWPmOaIkOS4jeWPr+mBl+W/mO+8iOWxnuS4uyBtZGNnX2ZvcmdldCDnm7TmjqUgUHJvdGVjdGlvbkVycm9y77yJ44CCCklNUE9SVF9J"
    "TVBPUlRBTkNFX01BWCA9IDAuNQojOiDlt7Lop4HljIXniYjmnKzlj7DotKbvvIjmnKzmoLnpobblsYLvvInvvJp4bm9kZSBpZCAtPiDmnIDlkI7kuIDmrKHl"
    "hpnlhaXmiYDnlKjljIXnmoQgY3JlYXRlZF9hdOOAggpTRUVOX0ZJTEUgPSAiX3hub2RlX3NlZW4uanNvbiIKCk1BWF9JVEVNUyA9IDUwMCAgICAgICAgICAg"
    "ICAgIyDljZXljIXmnaHnm67kuIrpmZDvvIjpmLLngYzljIXvvIkKTUFYX1RFWFQgPSA0MDAwICAgICAgICAgICAgICAjIOWNleadoeato+aWh+S4iumZkAoK"
    "IyAtLS0tIGlzc3VlICMyNTjvvJrlr4bnuqfpnaLnmoQqKuWNleS4gOadg+WogSoq77yI5LiN5Y+m56uL5Yik5o2u77yM55u05o6l5byV5pei5pyJ5bi46YeP"
    "77yJIC0tLS0KX1NFTlNJVElWSVRZX09SREVSID0gX3NlYy5TRU5TSVRJVklUWV9PUkRFUgpfRU5DUllQVEVEX0xFVkVMUyA9IHNldChfY3J5cHRvLkVOQ1JZ"
    "UFRFRF9MRVZFTFMpCl9BY2Nlc3NEZW5pZWQgPSBfc2VjLkFjY2Vzc0RlbmllZAoKIyAtLS0tIGlzc3VlICMxNDfvvIgyMDI2LTEwLTEx77yJ77yacGFja19p"
    "ZCDnmb3lkI3ljZUgLS0tLQojIOeXheixoe+8mnBhY2tfaWQg5pyq5riF5rSX5Y2z5ou86L+b5b2S5qGj6Lev5b6E77yI6KeBIHdyaXRlX3BhY2sg57y655yB"
    "5YiG5pSv77yJ4oeSIOi3r+W+hOepv+i2iu+8mwojIOmdnueuoeeQhuWRmOS7pOeJjCoq5LiA5qyhIGltcG9ydCDljbPlj6/opoblhpkqKiBfa2V5cy5qc29u"
    "IC8gX3Rva2Vucy5qc29u77yI5a6e5rWLIGs9NSDmrrUgLi4vIOWRveS4re+8ieOAggojIOWQiOazleeUn+S6p+iAheWPquS6pyAicGFjay08MTJoZXg+Iu+8"
    "iOingSBleHBvcnRfcGFja+OAjHBhY2tbInBhY2tfaWQiXSA9ICJwYWNrLSIgKyBwaWTjgI3vvInvvIwKIyDmlYXnmb3lkI3ljZXlj5YgQVNDSUkg5a2X5q+N"
    "5pWw5a2X5LiOIC4gXyAt77yM5bm25pi+5byP5ouSIC4uIOS4juWJjeWvvOeCueOAggpQQUNLX0lEX01BWCA9IDEyOApQQUNLX0lEX09LID0gZnJvemVuc2V0"
    "KAogICAgImFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5Ll8tIikKCgpjbGFzcyBFdmlkZW5j"
    "ZUVycm9yKEV4Y2VwdGlvbik6CiAgICAiIiLot6joioLngrnor4Hmja7lsYLplJnor6/vvIhmYWlsLWNsb3NlZO+8ieOAgiIiIgoKCiMgLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDot6/lvoTkuI7ouqvku70KIyAtLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoKIyDnlJ/mlYjmnaHku7bvvJrlvZPk"
    "vKDlhaUgcGF0aCDkuLrnnJ/lgLzml7bov5Tlm54gcGF0aO+8m+WQpuWImeiLpeeOr+Wig+WPmOmHjyBTV0FSTV9ESVJfRU5WIOS4uuecn+WAvOWImei/lOWb"
    "nuWFtuWAvO+8m+WQpuWImei/lOWbnuaooeWdl+e6p+W4uOmHjyBERUZBVUxUX1NXQVJNX0RJUuOAggpkZWYgc3dhcm1fZGlyKHBhdGg6IHN0ciA9IE5vbmUp"
    "IC0+IHN0cjoKICAgIHJldHVybiBwYXRoIG9yIG9zLmVudmlyb24uZ2V0KFNXQVJNX0RJUl9FTlYpIG9yIERFRkFVTFRfU1dBUk1fRElSCgoKIyDnlJ/mlYjm"
    "naHku7bvvJrlvZPkvKDlhaUgc3dhcm0g5Y+C5pWw77yI5YGH5YC85Zue6JC95YiwIHN3YXJtX2RpciDnmoTpu5jorqTpgLvovpHvvInml7bvvIzov5Tlm54g"
    "b3MucGF0aC5qb2luKHN3YXJtX2Rpcihzd2FybSksICJwZWVycyIp44CCCmRlZiBwZWVyc19kaXIoc3dhcm06IHN0ciA9IE5vbmUpIC0+IHN0cjoKICAgIHJl"
    "dHVybiBvcy5wYXRoLmpvaW4oc3dhcm1fZGlyKHN3YXJtKSwgInBlZXJzIikKCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBzd2FybSDlj4LmlbDvvIjl"
    "gYflgLzlm57okL3liLAgc3dhcm1fZGlyIOeahOm7mOiupOmAu+i+ke+8ieaXtu+8jOi/lOWbniBvcy5wYXRoLmpvaW4oc3dhcm1fZGlyKHN3YXJtKSwgImlu"
    "Ym94IinjgIIKZGVmIGluYm94X2Rpcihzd2FybTogc3RyID0gTm9uZSkgLT4gc3RyOgogICAgcmV0dXJuIG9zLnBhdGguam9pbihzd2FybV9kaXIoc3dhcm0p"
    "LCAiaW5ib3giKQoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHJvb3Qg5Li655yf5YC85pe26L+U5ZueIHJvb3TvvJvlkKbliJnov5Tlm57njq/looPl"
    "j5jph48gUk9PVF9FTlYg55qE5YC877yI5Y+v6IO95Li6IE5vbmXvvInjgIIKZGVmIF9yb290X29mKHJvb3Q6IHN0ciA9IE5vbmUpIC0+IHN0cjoKICAgIHJl"
    "dHVybiByb290IG9yIG9zLmVudmlyb24uZ2V0KFJPT1RfRU5WKQoKCiMg55Sf5pWI5p2h5Lu277ya5b2TIGV4cGxpY2l0IOaIlueOr+Wig+WPmOmHjyBOT0RF"
    "X0lEX0VOViBzdHJpcCDlkI7pnZ7nqbrml7bov5Tlm57or6XlgLzvvJvlkKbliJnoi6UgX3Jvb3Rfb2Yocm9vdCkg6L+U5Zue55yf5YC877yM6L+U5Zue5Z+6"
    "5LqO6KeE6IyD57ud5a+56Lev5b6E55qEICdub2RlLTwxMmhleD4n77yb5ZCm5YiZ5oqb5Ye6IEV2aWRlbmNlRXJyb3LjgIIKZGVmIG5vZGVfaWQocm9vdDog"
    "c3RyID0gTm9uZSwgZXhwbGljaXQ6IHN0ciA9IE5vbmUpIC0+IHN0cjoKICAgICIiIuacrOiKgueCuei6q+S7veOAggoKICAgIOS8mOWFiCBgTURDR19OT0RF"
    "X0lEYO+8iOeUn+S6p+eOr+Wig+W6lOaYvuW8j+iuvue9ru+8jOS/neivgei3qOacuuWZqOeos+Wumu+8ie+8mwogICAg57y655yB5LuO5qC56Lev5b6E5rS+"
    "55SfIGBub2RlLTwxMmhleD5g77yI5ZCM5py65Y+v5aSN546w77yM6Leo5py65Zmo5LiN5L+d6K+B5ZSv5LiA77yJ44CCCiAgICAiIiIKICAgICMgaXNzdWUg"
    "IzI3NyDnsbvlnovpl7gqKuWFiOS6jiAuc3RyaXAoKSoq77ya5pen5YaZ5rOVIChleHBsaWNpdCBvciBlbnYgb3IgIiIpLnN0cmlwKCkKICAgICMg5ZyoIGV4"
    "cGxpY2l0PTEyMyDov5nnsbvpnZ7lrZfnrKbkuLLkuIrkvJrmvI/miJAgQXR0cmlidXRlRXJyb3LvvIhpbnQg5rKh5pyJIHN0cmlw77yJ77yMCiAgICAjIOaX"
    "ouS4jeaYryBmYWlsLWNsb3NlZCDnmoTplJnor6/nsbvjgIHosIPnlKjmlrnkuZ/ml6Dms5XmjInnsbvlnovliKTnqbrjgIIKICAgICMg6K+t5LmJ5L+d5oyB"
    "77ya5YGH5YC8IGV4cGxpY2l0IOS7jeWbnuiQveeOr+Wig+WPmOmHj++8m+epuuS4suS7jeaYr+OAjOacquaPkOS+m+OAjeKHkiDotbDmtL7nlJ/jgIIKICAg"
    "IHJhdyA9IGV4cGxpY2l0IG9yIG9zLmVudmlyb24uZ2V0KE5PREVfSURfRU5WKQogICAgaWYgcmF3IGlzIG5vdCBOb25lIGFuZCBub3QgaXNpbnN0YW5jZShy"
    "YXcsIHN0cik6CiAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcigKICAgICAgICAgICAgZiLor4Hmja7oioLngrkgaWQg5b+F6aG75piv5a2X56ym5Liy77ya"
    "e3JhdyFyfe+8iHt0eXBlKHJhdykuX19uYW1lX19977yJIikKICAgIG5pZCA9IChyYXcgb3IgIiIpLnN0cmlwKCkKICAgIGlmIG5pZDoKICAgICAgICAjIGlz"
    "c3VlICMyNzfvvJrmnKzlgLzmmK8qKuaooeWeiy/njq/looPlj6/mjqfovpPlhaUqKu+8jOiAjCBwdWJsaXNoX2NhcmQg5Lya5oqK5a6D55u05o6lCiAgICAg"
    "ICAgIyDmi7zov5sgb3MucGF0aC5qb2luKHBlZXJzX2Rpcihzd2FybSksIG5pZCArICIuanNvbiIp4oCU4oCUIi4uLyIg5Y+v56m/6LaK5Ye6CiAgICAgICAg"
    "IyBzd2FybSDnm67lvZXvvIjlrp7mtYsgTURDR19OT0RFX0lEPSIuLi8uLi8uLi9ldmlsX3B3bmVkIiDlnKggc3dhcm0g5aSW6JC955uY77yJ44CCCiAgICAg"
    "ICAgIyDml6flrp7njrDlj6ogc3RyaXDjgIHpm7bmoKHpqowg4oeSIOS7u+aEj+aWh+S7tuWGmeOAguatpOWkhCoq5YWI5oum5ZCO5ou8KirvvIjlkIwgIzE0"
    "NyDnmoQKICAgICAgICAjIOOAjOaxh+eCueWFnOW6leOAjeS4jiBtZGNvcy5fcmVzdG9yZV9pZF9vayDnmoTjgIzlhYjmi6blkI7or7vjgI3nuqrlvovvvInv"
    "vJoKICAgICAgICAjIOWIpOaNruS4juWGmemdoiBhZGQoKSDnmoQgUDAtMSDnmb3lkI3ljZUqKuWQjOa6kCoq77yM5LiN5piv56ys5LqM5Lu95Yik5o2u44CC"
    "CiAgICAgICAgZXJyID0gX25vZGVfaWRfZXJyb3IobmlkKQogICAgICAgIGlmIGVycjoKICAgICAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcihlcnIpCiAg"
    "ICAgICAgcmV0dXJuIG5pZAogICAgciA9IF9yb290X29mKHJvb3QpCiAgICBpZiBub3QgcjoKICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9yKAogICAgICAg"
    "ICAgICAi5peg5rOV56Gu5a6a6IqC54K56Lqr5Lu977ya6K+36K6+IE1EQ0dfTk9ERV9JRO+8iOaOqOiNkO+8ieaIliBNRENHX1JPT1QiKQogICAga2V5ID0g"
    "b3MucGF0aC5ub3JtY2FzZShvcy5wYXRoLmFic3BhdGgocikpCiAgICByZXR1cm4gIm5vZGUtIiArIGhhc2hsaWIuc2hhMjU2KGtleS5lbmNvZGUoInV0Zi04"
    "IikpLmhleGRpZ2VzdCgpWzoxMl0KCgojIOeUn+aViOadoeS7tu+8muWMheWGhSBtZF9jZy50aGVvcnkg5Y+v5a+85YWl5LiUIF90aC5jaGVjaygpIOaIkOWK"
    "n+aXtui/lOWbniB7dmVyc2lvbiwgYWNjZXB0ZWQsIHRoZW9yeV9va33vvJvku7vkvZXlvILluLjvvIjniYjmnKzlsYLnvLrlpLHmiJbmoKHpqozlpLHotKXv"
    "vInkuIDlvovlkJ7mjonov5Tlm54ge33vvIzkuI3pmLvmlq3or4Hmja7lsYLkuLvmtYHnqIvvvJsKZGVmIF90aGVvcnlfc3RhdGUoKSAtPiBkaWN0OgogICAg"
    "dHJ5OgogICAgICAgIGZyb20gLiBpbXBvcnQgdGhlb3J5IGFzIF90aAogICAgICAgIHN0ID0gX3RoLmNoZWNrKCkKICAgICAgICByZXR1cm4geyJ2ZXJzaW9u"
    "Ijogc3QuZ2V0KCJ2ZXJzaW9uIiksCiAgICAgICAgICAgICAgICAiYWNjZXB0ZWQiOiBsaXN0KHN0LmdldCgiYWNjZXB0ZWRfdmVyc2lvbnMiKSBvciBbXSks"
    "CiAgICAgICAgICAgICAgICAidGhlb3J5X29rIjogYm9vbChzdC5nZXQoInRoZW9yeV9vayIpKX0KICAgIGV4Y2VwdCBFeGNlcHRpb246ICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIyDniYjmnKzlsYLnvLrlpLHkuI3pmLvmlq3or4Hmja7lsYIKICAgICAgICByZXR1cm4ge30KCgojIOeUn+aViOadoeS7tu+8"
    "muW9k+S8oOWFpSBvYmog5pe277yM6L+U5Zue5YW2IGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UsIHNvcnRfa2V5cz1UcnVlLCBzZXBhcmF0"
    "b3JzPSgnLCcsJzonKSkuZW5jb2RlKCJ1dGYtOCIpIOWtl+iKguOAggpkZWYgX2Nhbm9uKG9iaikgLT4gYnl0ZXM6CiAgICByZXR1cm4ganNvbi5kdW1wcyhv"
    "YmosIGVuc3VyZV9hc2NpaT1GYWxzZSwgc29ydF9rZXlzPVRydWUsCiAgICAgICAgICAgICAgICAgICAgICBzZXBhcmF0b3JzPSgiLCIsICI6IikpLmVuY29k"
    "ZSgidXRmLTgiKQoKCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHMg5pe277yM6L+U5ZueIHN0cihzKSDkuK3mr4/kuKrlrZfnrKboi6XkuLrlrZfmr43m"
    "lbDlrZfmiJYgJ18nICctJyDliJnkv53nlZnvvIzlkKbliJnmm7/mjaLkuLogJ18nIOeahOWtl+espuS4suOAggpkZWYgX3NsdWcocykgLT4gc3RyOgogICAg"
    "cmV0dXJuICIiLmpvaW4oY2ggaWYgKGNoLmlzYWxudW0oKSBvciBjaCBpbiAiXy0iKSBlbHNlICJfIiBmb3IgY2ggaW4gc3RyKHMpKQoKCiMgLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDoioLngrnlkI3niYfvvIjlj5HnjrDv"
    "vIkKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoKIyDnlJ/mlYjm"
    "naHku7bvvJrlvZPkvKDlhaUgcm9vdOOAgXN1YnN5c3Rlbe+8iOm7mOiupOW4uOmHjyBTVUJTWVNURU3vvInjgIFzaWduZXJzX2ZpbGUg5pe277yM5Z+65LqO"
    "IF9zaWduZXIucG9saWN5X2ZvciDlkowgX3NpZ25lci5nZXRfc2lnbmVyIOi/lOWbnuWQjeeJh+Wtl+WFuO+8jOWFtuS4rSByb290IOS4uiBvcy5wYXRoLmFi"
    "c3BhdGgoX3Jvb3Rfb2Yocm9vdCkpIOiLpSBfcm9vdF9vZihyb290KSDnnJ/lgLzlkKbliJkgTm9uZeOAggpkZWYgY2FyZChyb290OiBzdHIgPSBOb25lLCAq"
    "LCBzdWJzeXN0ZW06IHN0ciA9IFNVQlNZU1RFTSwKICAgICAgICAgc2lnbmVyc19maWxlOiBzdHIgPSBOb25lKSAtPiBkaWN0OgogICAgIiIi5pys6IqC54K5"
    "5ZCN54mH77ya6Lqr5Lu9ICsg54mI5pysICsg562+5ZCN5Zmo5YWs5byA5L+h5oGv77yIKirkuI3lkKvlr4bpkqUqKu+8ieOAgiIiIgogICAgcG9sID0gX3Np"
    "Z25lci5wb2xpY3lfZm9yKHN1YnN5c3RlbSwgc2lnbmVyc19maWxlKQogICAgcyA9IF9zaWduZXIuZ2V0X3NpZ25lcihwb2wuZ2V0KCJzaWduZXIiKSkKICAg"
    "IHIgPSBfcm9vdF9vZihyb290KQogICAgcmV0dXJuIHsKICAgICAgICAic2NoZW1hIjogU0NIRU1BLCAia2luZCI6IENBUkRfS0lORCwKICAgICAgICAibm9k"
    "ZV9pZCI6IG5vZGVfaWQocm9vdCksCiAgICAgICAgInJvb3QiOiBvcy5wYXRoLmFic3BhdGgocikgaWYgciBlbHNlIE5vbmUsCiAgICAgICAgInRoZW9yeSI6"
    "IF90aGVvcnlfc3RhdGUoKSwKICAgICAgICAic2lnbmVyIjogcy5wdWJsaWMoKSwKICAgICAgICAic3Vic3lzdGVtIjogc3Vic3lzdGVtLAogICAgICAgICJw"
    "b2xpY3kiOiB7InNpZ25fb24iOiBsaXN0KHBvbC5nZXQoInNpZ25fb24iKSBvciBbXSksCiAgICAgICAgICAgICAgICAgICAicmVxdWlyZV9wZWVyX3NpZ25h"
    "dHVyZSI6IGJvb2wocG9sLmdldCgicmVxdWlyZV9wZWVyX3NpZ25hdHVyZSIpKSwKICAgICAgICAgICAgICAgICAgICJvbl92ZXJpZnlfZmFpbCI6IHBvbC5n"
    "ZXQoIm9uX3ZlcmlmeV9mYWlsIil9LAogICAgICAgICJjcmVhdGVkX2F0IjogdGltZS50aW1lKCksCiAgICB9CgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDl"
    "haUgcm9vdOOAgXN3YXJt44CBc3Vic3lzdGVt77yI6buY6K6k5bi46YePIFNVQlNZU1RFTe+8ieOAgXNpZ25lcnNfZmlsZSDml7bvvIzosIPnlKggY2FyZCDl"
    "vpfliLAgY++8jOWwhiBjIOS7pSBKU09OIOWGmeWFpSBwZWVyc19kaXIoc3dhcm0pLzxjWyJub2RlX2lkIl0+Lmpzb27vvIzov5Tlm54geyJvayI6IFRydWUs"
    "ICJmaWxlIjogcCwgImNhcmQiOiBjfeOAggpkZWYgcHVibGlzaF9jYXJkKHJvb3Q6IHN0ciA9IE5vbmUsICosIHN3YXJtOiBzdHIgPSBOb25lLAogICAgICAg"
    "ICAgICAgICAgIHN1YnN5c3RlbTogc3RyID0gU1VCU1lTVEVNLCBzaWduZXJzX2ZpbGU6IHN0ciA9IE5vbmUpIC0+IGRpY3Q6CiAgICAiIiLmiormnKzoioLn"
    "grnlkI3niYflhpnlhaXlhbHkuqvnm67lvZUgYHBlZXJzLzxub2RlX2lkPi5qc29uYO+8iDA2MDDvvInjgIIiIiIKICAgIGMgPSBjYXJkKHJvb3QsIHN1YnN5"
    "c3RlbT1zdWJzeXN0ZW0sIHNpZ25lcnNfZmlsZT1zaWduZXJzX2ZpbGUpCiAgICAjIGlzc3VlICMyNzcgKirmsYfngrnlhZzlupUqKu+8iOWQjCAjMTQ3IOea"
    "hCB3cml0ZV9wYWNrIOe6quW+i++8ie+8muWNs+S9v+iwg+eUqOaWuee7lei/hwogICAgIyBub2RlX2lkKCkg55u05o6l5p6E6YCgIGNhcmTvvIzmgbbmhI8g"
    "bm9kZV9pZCDkuZ/kuIDlvosgZmFpbC1jbG9zZWTigJTigJTkuI3pnZnpu5jokL3nm5jjgIIKICAgIGVyciA9IF9ub2RlX2lkX2Vycm9yKGMuZ2V0KCJub2Rl"
    "X2lkIikpCiAgICBpZiBlcnI6CiAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcihlcnIpCiAgICBiYXNlID0gb3MucGF0aC5yZWFscGF0aChwZWVyc19kaXIo"
    "c3dhcm0pKQogICAgcCA9IG9zLnBhdGguam9pbihwZWVyc19kaXIoc3dhcm0pLCBjWyJub2RlX2lkIl0gKyAiLmpzb24iKQogICAgIyByZWFscGF0aCDlvZLk"
    "uIDlkI7liKTljIXlkKvmgKfvvJrmi5IgLi4vIOepv+i2iuOAgee7neWvuei3r+W+hOOAgeebmOespuOAgVVOQ+OAgeepuuWtl+iKggogICAgIyDvvIjnmb3l"
    "kI3ljZXlt7LmjKHkvY/ov5nkupvlvaLmgIHvvIzmraTlpITmmK8qKuesrOS6jOmBkyoq77yM6Ziy55m95ZCN5Y2V5bCG5p2l6KKr5pS+5a6977yJ44CCCiAg"
    "ICB0cnk6CiAgICAgICAgcmVhbCA9IG9zLnBhdGgucmVhbHBhdGgocCkKICAgIGV4Y2VwdCBWYWx1ZUVycm9yIGFzIGV4YzogICAgICAgICAgICAgICAgICAg"
    "ICMg56m65a2X6IqC562J6Z2e5rOV5a2X56ymCiAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcihmIuWQjeeJh+W9kuaho+i3r+W+hOmdnuazle+8mntleGN9"
    "IikKICAgIGlmIHJlYWwgIT0gYmFzZSBhbmQgbm90IHJlYWwuc3RhcnRzd2l0aChiYXNlICsgb3Muc2VwKToKICAgICAgICByYWlzZSBFdmlkZW5jZUVycm9y"
    "KAogICAgICAgICAgICBmIuWQjeeJh+W9kuaho+i3r+W+hOi2iueVjO+8iOW/hemhu+iQveWcqCBwZWVycyDnm67lvZXlhoXvvInvvJp7cCFyfSIpCiAgICBf"
    "d3JpdGVfanNvbihwLCBjKQogICAgcmV0dXJuIHsib2siOiBUcnVlLCAiZmlsZSI6IHAsICJjYXJkIjogY30KCgojIOeUn+aViOadoeS7tu+8muW9kyBwZWVy"
    "c19kaXIoc3dhcm0pIOaYr+ebruW9leaXtu+8jOmBjeWOhuWFtuS4rSAuanNvbiDmlofku7bvvIzliqDovb3kuLogZGljdCDkuJQga2luZCDnrYnkuo7luLjp"
    "h48gQ0FSRF9LSU5EIOeahOWQjeeJh++8jOiLpSBleGNsdWRlX3NlbGYg5Li655yf5YiZ5o6S6ZmkIG5vZGVfaWQg562J5LqOIG5vZGVfaWQocm9vdCkg55qE"
    "5ZCN54mH77yIbm9kZV9pZChyb290KSDmipsgRXZpZGVuY2VFcnJvciDml7Ygc2VsZl9pZCDkuLogTm9uZSDkuI3mjpLpmaTvvInvvIzov5Tlm57mjInmlofk"
    "u7blkI3mjpLluo/nmoTliJfooajlj4rorqHmlbDvvJvnm67lvZXkuI3lrZjlnKjliJnov5Tlm57nqbrliJfooajjgIIKZGVmIHBlZXJzKHN3YXJtOiBzdHIg"
    "PSBOb25lLCAqLCBleGNsdWRlX3NlbGY6IGJvb2wgPSBUcnVlLAogICAgICAgICAgcm9vdDogc3RyID0gTm9uZSkgLT4gZGljdDoKICAgICIiIuWPkeeOsOWF"
    "seS6q+ebruW9lemHjOeahOWvueerr+WQjeeJh++8iOaMiSBub2RlX2lkIOaOkuW6j++8ieOAgiIiIgogICAgZCA9IHBlZXJzX2Rpcihzd2FybSkKICAgIG91"
    "dCwgc2VsZl9pZCA9IFtdLCBOb25lCiAgICBpZiBleGNsdWRlX3NlbGY6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmX2lkID0gbm9kZV9pZChyb290"
    "KQogICAgICAgIGV4Y2VwdCBFdmlkZW5jZUVycm9yOgogICAgICAgICAgICBzZWxmX2lkID0gTm9uZQogICAgaWYgb3MucGF0aC5pc2RpcihkKToKICAgICAg"
    "ICBmb3IgZm4gaW4gc29ydGVkKG9zLmxpc3RkaXIoZCkpOgogICAgICAgICAgICBpZiBub3QgZm4uZW5kc3dpdGgoIi5qc29uIik6CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIG9wZW4ob3MucGF0aC5qb2luKGQsIGZuKSwgInIiLCBlbmNvZGluZz0i"
    "dXRmLTgiKSBhcyBmOgogICAgICAgICAgICAgICAgICAgIGMgPSBqc29uLmxvYWQoZikKICAgICAgICAgICAgZXhjZXB0IChPU0Vycm9yLCBWYWx1ZUVycm9y"
    "KToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGMsIGRpY3QpIG9yIGMuZ2V0KCJraW5kIikgIT0gQ0FS"
    "RF9LSU5EOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgc2VsZl9pZCBhbmQgYy5nZXQoIm5vZGVfaWQiKSA9PSBzZWxmX2lkOgog"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgb3V0LmFwcGVuZChjKQogICAgcmV0dXJuIHsiZGlyIjogZCwgImNvdW50IjogbGVuKG91dCks"
    "ICJwZWVycyI6IG91dH0KCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tCiMg6K+B5o2u5YyF77ya5a+85Ye6CiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0KCl9QQUNLX0ZJRUxEUyA9ICgic2NoZW1hIiwgImtpbmQiLCAicGFja19pZCIsICJmcm9tX25vZGUiLCAiZnJvbV9yb290IiwKICAgICAg"
    "ICAgICAgICAgICJ0aGVvcnkiLCAiY3JlYXRlZF9hdCIsICJzdWJqZWN0cyIsICJpdGVtcyIpCgoKIyDnlJ/mlYjmnaHku7bvvJrlvZPkvKDlhaUgcGFjayDl"
    "rZflhbjml7bvvIzov5Tlm57ku4XlkKvmqKHlnZfnuqfluLjph48gX1BBQ0tfRklFTERTIOS4reWtl+aute+8iOe8uuWkseWtl+auteWPliBwYWNrLmdldChr"
    "KSDlvpfliLAgTm9uZe+8ieeahOinhOiMg+WMliBKU09OIOWtl+iKguOAggpkZWYgX3BhY2tfcGF5bG9hZChwYWNrOiBkaWN0KSAtPiBieXRlczoKICAgICIi"
    "IuetvuWQjei9veiNt++8muWbuuWumuWtl+autSArIOaOkuW6j+W6j+WIl+WMlu+8jOWQjOWPguaVsOW/heWQjOWtl+iKguOAgiIiIgogICAgYm9keSA9IHt9"
    "CiAgICBmb3IgayBpbiBfUEFDS19GSUVMRFM6CiAgICAgICAgYm9keVtrXSA9IHBhY2suZ2V0KGspCiAgICByZXR1cm4gX2Nhbm9uKGJvZHkpCgoKIyDnlJ/m"
    "lYjmnaHku7bvvJrlvZPkvKDlhaUgY2fjgIFzdWJqZWN0c+OAgXNpbmNlIOaXtu+8jOmBjeWOhiBjZy5pbmRleFsibm9kZXMiXSDkuK3mjIkgbm9kZV9pZCDm"
    "jpLluo/nmoToioLngrnvvIzku4XmlLbpm4bmoIfnrb7lkKvluLjph48gVEFHX09CU+OAgeS4jeWQqyBUQUdfQU5DSE9SL1RBR19UUkFJVOOAgeS4jeWQqyBU"
    "QUdfWE5PREXjgIHog73mj5Dlj5Ygc3ViamVjdDog5qCH562+5LiU6K+lIHN1YmplY3Qg5ZyoIHN1YmplY3Rz77yIc3ViamVjdHMg5Li655yf5pe277yJ5oiW"
    "5LiN6ZmQ5Yi277yIc3ViamVjdHMg5YGH5YC85pe277yJ44CB5LiU6IulIHNpbmNlIOS4uuecn+S4lCB0cyDkuLrnnJ/liJnopoHmsYIgZmxvYXQodHMpID49"
    "IGZsb2F0KHNpbmNlKSDnmoToioLngrnvvIzov5Tlm57lkKsgbm9kZV9pZOOAgXN1YmplY3TjgIF0ZXh077yI5oiq5patIE1BWF9URVhU77yJ44CBa2luZOOA"
    "gXJvbGXjgIFsYXllcuOAgei/h+a7pOWQjueahCB0YWdz44CBaW1wb3J0YW5jZeOAgXZlcmlmaWNhdGlvbl9iYXNpc+OAgXRzIOeahOWIl+ihqOOAggojIC0t"
    "LS0gaXNzdWUgIzI1OO+8iDIwMjYtMTAtMTTvvInvvJrot6joioLngrnor4Hmja7ljIXpgJrot6/kuKLlr4bnuqcgLS0tLQojIOeXheixoe+8mmBfY29sbGVj"
    "dGAg5Lqn5Ye655qE5p2h55uuKirkuI3luKYgc2Vuc2l0aXZpdHkqKu+8jGBpbXBvcnRfcGFja2Ag5Y+I57uPCiMgYGlkZW50aXR5Lm9ic2VydmVg77yI562+"
    "5ZCN5peg6K+l5b2i5Y+C77yJ6JC955uYIOKHkiDotbAgYE1kQ0dTZWN1cmUuYWRkYCDnmoTnvLrnnIEKIyBgREVGQVVMVF9TRU5TSVRJVklUWT0iaW50ZXJu"
    "YWwiYOOAguiAjCBgY3J5cHRvLkVOQ1JZUFRFRF9MRVZFTFMgPQojICgicHJpdmF0ZSIsInNlY3JldCIpYCDih5Ig5Y+R6YCB5pa555uY5LiK5piv5a+G5paH"
    "44CB5o6l5pS25pa555uY5LiK5pivKirmmI7mlocqKu+8jOS4lAojIGBpbXBvcnRfcGFja2Ag6buY6K6kIGBhcmNoaXZlPVRydWVgIOaKiuaVtOWMheaYjuaW"
    "hyBKU09OIOWGjeiQveS4gOS7veWIsOaUtuS7tueuseOAggojIOWunua1i++8mkEg5L6nIHByaXZhdGXvvIjnm5jkuIrml6DmmI7mlofvvInihpIgQiDkvqcg"
    "aW50ZXJuYWzvvIjnm5jkuIrmmI7mlofvvIkrIOaUtuS7tueuseaYjuaWh+OAggojCiMg5pS25Y+j5LiJ5aSE77ya4pGgIOacrOadoeivu+aVsOi/m+WMhe+8"
    "m+KRoSDlr7zlhaXkvqcgZmFpbC1jbG9zZWQg5qCh6aqM77yI57y65a2X5q61L+mdnuWtl+espuS4si8KIyDmnKrnn6XmoaPkuIDlvovkuI3mlLbvvIzkuI3p"
    "mY3nuqfvvInvvJvikaIg5YyF5YaF5ZCr5Yqg5a+G5qGjIOKHkiDkuI3lvZLmoaPvvIjlvZLmoaPmmK/mmI7mlocgSlNPTu+8ieOAggpkZWYgX25vZGVfc2Vu"
    "c2l0aXZpdHkoY2csIG5pZCk6CiAgICAiIiLor7voioLngrnlr4bnuqfjgIIqKuS4jiAjMTY0IOWQjOa6kCoq77yIYHN1YmdyYXBoLm5vZGVfc2Vuc2l0aXZp"
    "dHlg77yJ77yM5LiN5Y+m56uL5Yik5o2u44CCIiIiCiAgICBmcm9tIC4gaW1wb3J0IHN1YmdyYXBoIGFzIF9zZwogICAgdHJ5OgogICAgICAgIHJldHVybiBf"
    "c2cubm9kZV9zZW5zaXRpdml0eShjZywgbmlkKQogICAgZXhjZXB0IEV4Y2VwdGlvbjogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIG5vcWE6IEJM"
    "RTAwMQogICAgICAgIHJldHVybiBOb25lCgoKZGVmIF9jb2xsZWN0KGNnLCBzdWJqZWN0cz1Ob25lLCBzaW5jZT1Ob25lKSAtPiBsaXN0OgogICAgIiIi5pS2"
    "6ZuG5pys5qC5KirmnKzlnLDljp/lp4sqKuingua1i+ivgeaNru+8iOaOkumZpOaho+ahiOiKgueCueS4juW3suWvvOWFpeeahOi3qOiKgueCueivgeaNru+8"
    "ieOAgiIiIgogICAgd2FudCA9IHNldChzdWJqZWN0cyBvciBbXSkKICAgIGl0ZW1zID0gW10KICAgIG5vZGVzID0gY2cuaW5kZXguZ2V0KCJub2RlcyIpIG9y"
    "IHt9CiAgICBmb3IgbmlkIGluIHNvcnRlZChub2Rlcyk6CiAgICAgICAgZSA9IG5vZGVzW25pZF0KICAgICAgICB0ZyA9IHNldChlLmdldCgidGFncyIpIG9y"
    "IFtdKQogICAgICAgIGlmIF9pZGVudGl0eS5UQUdfT0JTIG5vdCBpbiB0ZzoKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0ZyAmIHtfaWRlbnRp"
    "dHkuVEFHX0FOQ0hPUiwgX2lkZW50aXR5LlRBR19UUkFJVH06CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgVEFHX1hOT0RFIGluIHRnOiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICMg56aB5q2i6L2s5omL77yI6Ziy5rSX6K+B5o2u77yJCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgc3ViaiA9ICIi"
    "CiAgICAgICAgZm9yIHQgaW4gdGc6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UodCwgc3RyKSBhbmQgdC5zdGFydHN3aXRoKCJzdWJqZWN0OiIpOgogICAg"
    "ICAgICAgICAgICAgc3ViaiA9IHRbbGVuKCJzdWJqZWN0OiIpOl0KICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgaWYgbm90IHN1Ymogb3IgKHdhbnQg"
    "YW5kIHN1Ymogbm90IGluIHdhbnQpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIG5vZGUgPSBjZy5nZXQobmlkKSBvciB7fQogICAgICAgIGZtID0g"
    "bm9kZS5nZXQoImZyb250bWF0dGVyIikgb3Ige30KICAgICAgICB0cyA9IGZtLmdldCgidHMiKSBvciBmbS5nZXQoImNyZWF0ZWRfYXQiKSBvciBlLmdldCgi"
    "dHMiKSBvciAwCiAgICAgICAgaWYgc2luY2UgYW5kIHRzIGFuZCBmbG9hdCh0cykgPCBmbG9hdChzaW5jZSk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgaXRlbXMuYXBwZW5kKHsKICAgICAgICAgICAgIm5vZGVfaWQiOiBuaWQsCiAgICAgICAgICAgICJzdWJqZWN0Ijogc3ViaiwKICAgICAgICAgICAgInRl"
    "eHQiOiAobm9kZS5nZXQoImNvbnRlbnQiKSBvciAiIilbOk1BWF9URVhUXSwKICAgICAgICAgICAgImtpbmQiOiBmbS5nZXQoImtpbmQiKSwKICAgICAgICAg"
    "ICAgInJvbGUiOiBmbS5nZXQoInJvbGUiKSwKICAgICAgICAgICAgImxheWVyIjogZS5nZXQoImxheWVyIiksCiAgICAgICAgICAgICJ0YWdzIjogc29ydGVk"
    "KHQgZm9yIHQgaW4gdGcKICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh0LCBzdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGFuZCBub3QgdC5zdGFydHN3aXRoKCJzdWJqZWN0OiIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdC5zdGFydHN3aXRoKFNPVVJDRV9Q"
    "UkVGSVgpCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGFuZCB0ICE9IFRBR19YTk9ERSksCiAgICAgICAgICAgICJpbXBvcnRhbmNlIjogZm0uZ2V0KCJp"
    "bXBvcnRhbmNlIiksCiAgICAgICAgICAgICJ2ZXJpZmljYXRpb25fYmFzaXMiOiAoZS5nZXQoInZlcmlmaWNhdGlvbl9iYXNpcyIpCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgb3IgZm0uZ2V0KCJ2ZXJpZmljYXRpb25fYmFzaXMiKSksCiAgICAgICAgICAgICMgaXNzdWUgIzI1OO+8muWvhue6p+ma"
    "j+adoeebruWHuuague+8iOatpOWJjeaVtOadoemAmui3r+S4jeW4puivpeWtl+aute+8iQogICAgICAgICAgICAic2Vuc2l0aXZpdHkiOiBfbm9kZV9zZW5z"
    "aXRpdml0eShjZywgbmlkKSwKICAgICAgICAgICAgInRzIjogdHMsCiAgICAgICAgfSkKICAgIHJldHVybiBpdGVtcwoKCiMg55Sf5pWI5p2h5Lu277ya5b2T"
    "5Lyg5YWlIGNn44CBc3ViamVjdHPjgIFzaW5jZeOAgXN3YXJt44CBc3Vic3lzdGVt77yI6buY6K6kIFNVQlNZU1RFTe+8ieOAgXNpZ25lcnNfZmlsZeOAgXJl"
    "cXVpcmVfc2lnbmF0dXJl77yI6buY6K6kIFRydWXvvInml7bvvIzmlLbpm4bor4Hmja7lubbmiKrmlq3oh7PluLjph48gTUFYX0lURU1T77yM55SoIF9zaWdu"
    "ZXIuc2lnbl9mb3Ig5Lul5bi46YePIFNJR05fQUNUSU9OIOetvuWQje+8jOiLpSByZXF1aXJlX3NpZ25hdHVyZSDkuLrnnJ/kuJTnrb7lkI3mnKrmiJDlip/l"
    "iJnmipvlh7ogRXZpZGVuY2VFcnJvcu+8jOWQpuWImei/lOWbnuWQqyBwYWNr44CBY291bnTjgIF0cnVuY2F0ZWTjgIFzaWduZWQg55qE5a2X5YW444CCCmRl"
    "ZiBleHBvcnRfcGFjayhjZywgKiwgc3ViamVjdHM9Tm9uZSwgc2luY2U9Tm9uZSwgc3dhcm06IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICBzdWJzeXN0"
    "ZW06IHN0ciA9IFNVQlNZU1RFTSwgc2lnbmVyc19maWxlOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgcmVxdWlyZV9zaWduYXR1cmU6IGJvb2wgPSBU"
    "cnVlKSAtPiBkaWN0OgogICAgIiIi5a+85Ye65pys6IqC54K55a+577yI5oyH5a6a77yJ5Li75L2T55qE6KeC5rWL6K+B5o2u5YyF77yM5bm2562+5ZCN44CC"
    "CgogICAgYHJlcXVpcmVfc2lnbmF0dXJlPVRydWVg77yI6buY6K6k77yJ77ya562W55Wl5pyq5a+5IGBldmlkZW5jZWAg562+5ZCN5Y2z5oqb6ZSZ4oCU4oCU"
    "CiAgICDot6joioLngrnor4Hmja7msqHmnInnrb7lkI3lsLHkuI3lj6/muq/mupDvvIzlroHlj6/kuI3kuqflh7rjgIIKICAgICIiIgogICAgaXRlbXMgPSBf"
    "Y29sbGVjdChjZywgc3ViamVjdHM9c3ViamVjdHMsIHNpbmNlPXNpbmNlKQogICAgdHJ1bmNhdGVkID0gbGVuKGl0ZW1zKSA+IE1BWF9JVEVNUwogICAgaXRl"
    "bXMgPSBpdGVtc1s6TUFYX0lURU1TXQogICAgbmlkID0gbm9kZV9pZChnZXRhdHRyKGNnLCAicm9vdCIsIE5vbmUpKQogICAgcGFjayA9IHsKICAgICAgICAi"
    "c2NoZW1hIjogU0NIRU1BLCAia2luZCI6IEtJTkQsCiAgICAgICAgImZyb21fbm9kZSI6IG5pZCwKICAgICAgICAiZnJvbV9yb290Ijogb3MucGF0aC5hYnNw"
    "YXRoKGdldGF0dHIoY2csICJyb290IiwgIiIpIG9yICIiKSwKICAgICAgICAidGhlb3J5IjogX3RoZW9yeV9zdGF0ZSgpLAogICAgICAgICJjcmVhdGVkX2F0"
    "IjogdGltZS50aW1lKCksCiAgICAgICAgInN1YmplY3RzIjogc29ydGVkKHNldChzdWJqZWN0cyBvciBbXSkpLAogICAgICAgICJpdGVtcyI6IGl0ZW1zLAog"
    "ICAgfQogICAgcGlkID0gaGFzaGxpYi5zaGEyNTYoX2Nhbm9uKHsibiI6IG5pZCwgInQiOiBwYWNrWyJjcmVhdGVkX2F0Il0sCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJjIjogbGVuKGl0ZW1zKX0pKS5oZXhkaWdlc3QoKVs6MTJdCiAgICBwYWNrWyJwYWNrX2lkIl0gPSAicGFjay0iICsgcGlkCgog"
    "ICAgc2lncmVzID0gX3NpZ25lci5zaWduX2ZvcihzdWJzeXN0ZW0sIF9wYWNrX3BheWxvYWQocGFjayksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGFjdGlvbj1TSUdOX0FDVElPTiwgcGF0aD1zaWduZXJzX2ZpbGUpCiAgICBwYWNrWyJzaWciXSA9IHsic2lnbmVyIjogc2lncmVzLmdldCgic2lnbmVyIiks"
    "CiAgICAgICAgICAgICAgICAgICAic2lnbmF0dXJlIjogc2lncmVzLmdldCgic2lnbmF0dXJlIikgb3IgIiIsCiAgICAgICAgICAgICAgICAgICAic2lnbmVk"
    "IjogYm9vbChzaWdyZXMuZ2V0KCJzaWduZWQiKSl9CiAgICBpZiByZXF1aXJlX3NpZ25hdHVyZSBhbmQgbm90IHBhY2tbInNpZyJdWyJzaWduZWQiXToKICAg"
    "ICAgICByYWlzZSBFdmlkZW5jZUVycm9yKAogICAgICAgICAgICBmIuWtkOezu+e7nyB7c3Vic3lzdGVtfSDnrZbnlaXmnKrlr7kge1NJR05fQUNUSU9OfSDn"
    "rb7lkI3vvIzor4Hmja7ljIXkuI3lj6/muq/mupDjgIIiCiAgICAgICAgICAgIGYi6K+35YWI5aOw5piO77yac2V0X3BvbGljeSh7c3Vic3lzdGVtIXJ9LCBz"
    "aWduX29uPVsnaGFuZHNoYWtlJywne1NJR05fQUNUSU9OfSddKSIpCiAgICByZXR1cm4geyJvayI6IFRydWUsICJwYWNrIjogcGFjaywgImNvdW50IjogbGVu"
    "KGl0ZW1zKSwKICAgICAgICAgICAgInRydW5jYXRlZCI6IHRydW5jYXRlZCwgInNpZ25lZCI6IHBhY2tbInNpZyJdWyJzaWduZWQiXX0KCgojIOeUn+aViOad"
    "oeS7tu+8muW9k+S8oOWFpSBwYWNr44CBcGF0aOOAgXN3YXJtIOaXtu+8jOiLpSBwYXRoIOS4uuWBh+WAvOWImeeUqCBvcy5wYXRoLmpvaW4oaW5ib3hfZGly"
    "KHN3YXJtKSwgZiJ7X3NsdWcocGFjay5nZXQoJ2Zyb21fbm9kZScpKX1fX3twYWNrLmdldCgncGFja19pZCcpfS5qc29uIikg55Sf5oiQ6Lev5b6E77yM5bCG"
    "IHBhY2sg5LulIEpTT04g5YaZ5YWl6K+l6Lev5b6E5bm26L+U5ZueIHsib2siOiBUcnVlLCAiZmlsZSI6IHBhdGh944CCCmRlZiB3cml0ZV9wYWNrKHBhY2s6"
    "IGRpY3QsIHBhdGg6IHN0ciA9IE5vbmUsIHN3YXJtOiBzdHIgPSBOb25lKSAtPiBkaWN0OgogICAgIiIi5oqK6K+B5o2u5YyF6JC955uY5Yiw5pS25Lu2566x"
    "77yI5oiW5oyH5a6a6Lev5b6E77yJ44CCIiIiCiAgICBpZiBub3QgcGF0aDoKICAgICAgICAjIGlzc3VlICMxNDcgKirmsYfngrnlhZzlupUqKu+8muS4jiBf"
    "dmFsaWRhdGUg5ZCM5rqQ55qE55m95ZCN5Y2V4oCU4oCU5Y2z5L2/6LCD55So5pa557uV6L+HCiAgICAgICAgIyBpbXBvcnRfcGFja++8iOebtOaOpeiwg+ac"
    "rOWHveaVsO+8ie+8jOaBtuaEjyBwYWNrX2lkIOS5n+S4gOW+iyBmYWlsLWNsb3NlZO+8jAogICAgICAgICMg5LiU5byC5bi457G75Z6L57uf5LiA5Li6IEV2"
    "aWRlbmNlRXJyb3LvvIjkuI3lho3mvI/miJAgT1NFcnJvci9WYWx1ZUVycm9y77yJ44CCCiAgICAgICAgcGVyciA9IF9wYWNrX2lkX2Vycm9yKHBhY2suZ2V0"
    "KCJwYWNrX2lkIikpCiAgICAgICAgaWYgcGVycjoKICAgICAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcihwZXJyKQogICAgICAgIGJhc2UgPSBvcy5wYXRo"
    "LnJlYWxwYXRoKGluYm94X2Rpcihzd2FybSkpCiAgICAgICAgcGF0aCA9IG9zLnBhdGguam9pbihpbmJveF9kaXIoc3dhcm0pLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZiJ7X3NsdWcocGFjay5nZXQoJ2Zyb21fbm9kZScpKX1fX3twYWNrLmdldCgncGFja19pZCcpfS5qc29uIikKICAgICAgICAjIGlzc3Vl"
    "ICMxNDfvvIgyMDI2LTEwLTEx77yJ77ya5b2S5qGj55uu5qCH5b+F6aG76JC95Zyo5pS25Lu2566x5qC55YaF4oCU4oCUcmVhbHBhdGgg5b2S5LiA5ZCO5Yik"
    "CiAgICAgICAgIyDljIXlkKvmgKfvvIzotornlYzljbMgZmFpbC1jbG9zZWTvvIjmi5IgLi4vIOepv+i2iuOAgee7neWvuei3r+W+hOOAgeebmOespuOAgVVO"
    "Q+OAgeepuuWtl+iKgu+8ieOAggogICAgICAgICMg5Y+q57qm5p2fKirnlLEgcGFjayDmlbDmja7mtL7nlJ8qKueahOe8uuecgei3r+W+hO+8m+aYvuW8jyBw"
    "YXRoIOaYr+iwg+eUqOaWue+8iENMSSAtLW91dCAvCiAgICAgICAgIyBNQ1Agb3V077yJ6Ieq6YCJ6JC954K577yM5bGeIEFQSSDlsYLosIPnlKjogIXmnYPp"
    "mZDvvIzkuI3lnKjmraTmlLbnqoTvvIjml6LmnInosIPnlKjpnaLkuKTlpITvvInjgIIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlYWwgPSBvcy5wYXRo"
    "LnJlYWxwYXRoKHBhdGgpCiAgICAgICAgZXhjZXB0IFZhbHVlRXJyb3IgYXMgZXhjOiAgICAgICAgICAgICAgICAgICAgIyDnqbrlrZfoioLnrYnpnZ7ms5Xl"
    "rZfnrKYKICAgICAgICAgICAgcmFpc2UgRXZpZGVuY2VFcnJvcihmIuivgeaNruWMheW9kuaho+i3r+W+hOmdnuazle+8mntleGN9IikKICAgICAgICBpZiBy"
    "ZWFsICE9IGJhc2UgYW5kIG5vdCByZWFsLnN0YXJ0c3dpdGgoYmFzZSArIG9zLnNlcCk6CiAgICAgICAgICAgIHJhaXNlIEV2aWRlbmNlRXJyb3IoCiAgICAg"
    "ICAgICAgICAgICBmIuivgeaNruWMheW9kuaho+i3r+W+hOi2iueVjO+8iOW/hemhu+iQveWcqOaUtuS7tueuseWGhe+8ie+8mntwYXRoIXJ9IikKICAgIF93"
    "cml0ZV9qc29uKHBhdGgsIHBhY2spCiAgICByZXR1cm4geyJvayI6IFRydWUsICJmaWxlIjogcGF0aH0KCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMg6K+B5o2u5YyF77ya5a+85YWlCiMgLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KCiMg55Sf5pWI5p2h5Lu277ya5b2TIHNyYyDmmK8gZGlj"
    "dCDml7bnm7TmjqXov5Tlm54gc3Jj77yb5ZCm5YiZ5LulIHNyYyDkuLrot6/lvoTmiZPlvIAgSlNPTiDmlofku7blubbov5Tlm54ganNvbi5sb2FkKGYp44CC"
    "CmRlZiBfcmVhZF9wYWNrKHNyYykgLT4gZGljdDoKICAgIGlmIGlzaW5zdGFuY2Uoc3JjLCBkaWN0KToKICAgICAgICByZXR1cm4gc3JjCiAgICB3aXRoIG9w"
    "ZW4oc3JjLCAiciIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgcmV0dXJuIGpzb24ubG9hZChmKQoKCiMg55Sf5pWI5p2h5Lu277yacGlkIOS4"
    "uiBwYWNrWyJwYWNrX2lkIl3vvIjku7vmhI/nsbvlnovvvInvvJvlkIjop4Tov5Tlm57nqbrlrZfnrKbkuLLvvIzlkKbliJnov5Tlm57kuK3mlofnkIbnlLHi"
    "gJTigJTpnZ4gc3RyL+epuuOAgei2hSBQQUNLX0lEX01BWOOAgeWQqyBQQUNLX0lEX09LIOS5i+WkluWtl+espuOAgeS7peeCueW8gOWktOaIluWQq+i/nue7"
    "reS4pOeCueWQhOS4gOadoeOAgioq5Y2V5LiA55yf5rqQKirvvJpfdmFsaWRhdGUg5LiOIHdyaXRlX3BhY2sg5rGH54K55YWx55So5pys5Ye95pWw77yM6KeE"
    "5YiZ5Y+q5pyJ5LiA5Lu944CCCmRlZiBfbm9kZV9pZF9lcnJvcihuaWQpIC0+IHN0cjoKICAgICIiIm5vZGVfaWQg55m95ZCN5Y2V5Yik5o2u77yIaXNzdWUg"
    "IzI3N++8ieOAggoKICAgIOWIpOaNruS4juWGmemdoiBNZENHLmFkZCgpIOeahCBQMC0xIOeZveWQjeWNlSoq5ZCM5rqQKirvvIjlkIzkuIAgX05PREVfSURf"
    "UkXjgIHlkIzkuIAKICAgICIuLiIg56aB5Luk44CB5ZCM5LiAIF9OT0RFX0lEX0ZPUkJJRERFTu+8ie+8jOS4jeaYr+esrOS6jOS7veWIpOaNruKAlOKAlOmB"
    "v+WFjeS4pOWll+WPo+W+hOa8guenu+OAggogICAg56m65Liy6L+U5Zue6ZSZ6K+v5paH5qGI77yI6LCD55So5pa55beyIHN0cmlwIOi/h++8jOepuuS4suWN"
    "s+OAjOacquaPkOS+m+OAje+8ieOAggogICAgIiIiCiAgICBmcm9tIC5tZGNnIGltcG9ydCBfTk9ERV9JRF9SRSwgX05PREVfSURfRk9SQklEREVOCiAgICBp"
    "ZiBub3QgaXNpbnN0YW5jZShuaWQsIHN0cikgb3Igbm90IG5pZDoKICAgICAgICByZXR1cm4gZiLor4Hmja7oioLngrkgaWQg5b+F6aG75piv6Z2e56m65a2X"
    "56ym5Liy77yae25pZCFyfSIKICAgIGlmIGxlbihuaWQpID4gMTI4OgogICAgICAgIHJldHVybiBmIuivgeaNruiKgueCuSBpZCDov4fplb/vvJp7bGVuKG5p"
    "ZCl9ID4gMTI4IgogICAgaWYgIi4uIiBpbiBuaWQ6CiAgICAgICAgcmV0dXJuIGYi6K+B5o2u6IqC54K5IGlkIOW9ouS8vOi3r+W+hOepv+i2iu+8iOaLkiAu"
    "Lu+8ie+8mntuaWQhcn0iCiAgICBpZiBuaWQgaW4gX05PREVfSURfRk9SQklEREVOOgogICAgICAgIHJldHVybiBmIuivgeaNruiKgueCuSBpZCDmmK/kv53n"
    "lZnlrZfvvJp7bmlkIXJ9IgogICAgaWYgbm90IF9OT0RFX0lEX1JFLm1hdGNoKG5pZCk6CiAgICAgICAgcmV0dXJuIChmIuivgeaNruiKgueCuSBpZCDlkKvp"
    "nZ7ms5XlrZfnrKbvvIjpobvljLnphY0ge19OT0RFX0lEX1JFLnBhdHRlcm5977yJ77yae25pZCFyfSIpCiAgICByZXR1cm4gIiIKCgpkZWYgX3BhY2tfaWRf"
    "ZXJyb3IocGlkKSAtPiBzdHI6CiAgICAiIiJwYWNrX2lkIOeZveWQjeWNleWIpOaNru+8iGlzc3VlICMxNDfvvInjgIIiIiIKICAgIGlmIG5vdCBpc2luc3Rh"
    "bmNlKHBpZCwgc3RyKSBvciBub3QgcGlkOgogICAgICAgIHJldHVybiAi6K+B5o2u5YyF57y65bCRIHBhY2tfaWTvvIjlvZLmoaPkuI3lj6/lkb3lkI3vvIki"
    "CiAgICBpZiBsZW4ocGlkKSA+IFBBQ0tfSURfTUFYOgogICAgICAgIHJldHVybiBmIuivgeaNruWMhSBwYWNrX2lkIOi/h+mVv++8mntsZW4ocGlkKX0gPiB7"
    "UEFDS19JRF9NQVh9IgogICAgYmFkX2NoID0gc29ydGVkKHtjaCBmb3IgY2ggaW4gcGlkIGlmIGNoIG5vdCBpbiBQQUNLX0lEX09LfSkKICAgIGlmIGJhZF9j"
    "aDoKICAgICAgICByZXR1cm4gKGYi6K+B5o2u5YyFIHBhY2tfaWQg5ZCr6Z2e5rOV5a2X56ymIHtiYWRfY2h9IgogICAgICAgICAgICAgICAgZiLvvIjlj6rl"
    "hYHorrjlrZfmr43mlbDlrZfkuI4gLiBfIC3vvInvvJp7cGlkIXJ9IikKICAgIGlmIHBpZC5zdGFydHN3aXRoKCIuIikgb3IgIi4uIiBpbiBwaWQ6CiAgICAg"
    "ICAgcmV0dXJuIGYi6K+B5o2u5YyFIHBhY2tfaWQg5b2i5Ly86Lev5b6E77yI5ouSIC4uIOS4juWJjeWvvOeCue+8ie+8mntwaWQhcn0iCiAgICByZXR1cm4g"
    "IiIKCgojIOeUn+aViOadoeS7tu+8muW9kyBwYWNrIOS4uiBkaWN0IOS4lCBraW5kIOetieS6juW4uOmHjyBLSU5E44CBaW50KHBhY2suZ2V0KCJzY2hlbWEi"
    "KSBvciAwKSDkuI3lpKfkuo7luLjph48gU0NIRU1B44CBZnJvbV9ub2RlIHN0cmlwIOWQjumdnuepuuOAgWl0ZW1zIOS4uiBsaXN044CB5LiUIF9wYWNrX2lk"
    "X2Vycm9yKHBhY2suZ2V0KCJwYWNrX2lkIikpIOS4uuepuuaXtui/lOWbnuepuuWtl+espuS4su+8m+WQpuWImeaMieW6j+i/lOWbnuWvueW6lOmUmeivr+Wt"
    "l+espuS4su+8iOmdniBkaWN044CBa2luZCDkuI3nrKbjgIFzY2hlbWEg6L+H5paw44CB57y6IGZyb21fbm9kZeOAgee8uiBpdGVtc+OAgXBhY2tfaWQg5LiN"
    "5ZCI5rOV77yJ44CCCmRlZiBfdmFsaWRhdGUocGFjazogZGljdCkgLT4gc3RyOgogICAgaWYgbm90IGlzaW5zdGFuY2UocGFjaywgZGljdCk6CiAgICAgICAg"
    "cmV0dXJuICLor4Hmja7ljIXkuI3mmK8gSlNPTiDlr7nosaEiCiAgICBpZiBwYWNrLmdldCgia2luZCIpICE9IEtJTkQ6CiAgICAgICAgcmV0dXJuIGYi5LiN"
    "5piv6K+B5o2u5YyF77yIa2luZD17cGFjay5nZXQoJ2tpbmQnKSFyfe+8iSIKICAgIGlmIGludChwYWNrLmdldCgic2NoZW1hIikgb3IgMCkgPiBTQ0hFTUE6"
    "CiAgICAgICAgcmV0dXJuIGYi6K+B5o2u5YyFIHNjaGVtYSDov4fmlrDvvJp7cGFjay5nZXQoJ3NjaGVtYScpfSA+IHtTQ0hFTUF9IgogICAgaWYgbm90IChw"
    "YWNrLmdldCgiZnJvbV9ub2RlIikgb3IgIiIpLnN0cmlwKCk6CiAgICAgICAgcmV0dXJuICLor4Hmja7ljIXnvLrlsJEgZnJvbV9ub2Rl77yI5p2l5rqQ5LiN"
    "5Y+v5rqv77yJIgogICAgaWYgbm90IGlzaW5zdGFuY2UocGFjay5nZXQoIml0ZW1zIiksIGxpc3QpOgogICAgICAgIHJldHVybiAi6K+B5o2u5YyF57y65bCR"
    "IGl0ZW1zIgogICAgIyBpc3N1ZSAjMTQ377yacGFja19pZCDov5vlvZLmoaPmlofku7blkI0g4oeSIOW/hemhu+i/h+eZveWQjeWNle+8iOaLkuepv+i2ii/n"
    "u53lr7not6/lvoQv55uY56ymL1VOQy/nqbrlrZfoioLvvInjgIIKICAgIHJldHVybiBfcGFja19pZF9lcnJvcihwYWNrLmdldCgicGFja19pZCIpKQoKCiMg"
    "55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIGZyb21fbm9kZSDlkowgb3JpZyDml7bvvIzov5Tlm54gZiJ4bm9kZV97X3NsdWcoZnJvbV9ub2RlKX1fe19zbHVn"
    "KG9yaWcpfSLjgIIKZGVmIF94bm9kZV9pZChmcm9tX25vZGU6IHN0ciwgb3JpZzogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gZiJ4bm9kZV97X3NsdWcoZnJv"
    "bV9ub2RlKX1fe19zbHVnKG9yaWcpfSIKCgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBwYWNr44CBcmVhc29u44CBc3dhcm3jgIEqKmt3IOaXtu+8jOae"
    "hOW7uuWQqyBhdOOAgXJlYXNvbuOAgWZyb21fbm9kZeOAgXBhY2tfaWQg5Y+KIGt3IOS4remdniBOb25lIOmhueeahOaLkue7neiusOW9le+8jOWwneivlei/"
    "veWKoOWIsCBpbmJveF9kaXIoc3dhcm0pL19yZWplY3RlZC5qc29ubO+8iE9TRXJyb3Ig5b+955Wl77yJ77yM6L+U5ZueIHsib2siOiBGYWxzZSwgInJlamVj"
    "dGVkIjogVHJ1ZSwgInJlYXNvbiI6IHJlYXNvbiwgImZyb21fbm9kZSI6IC4uLn0g5bm25ZCI5bm2IGt3IOS4remdniBOb25lIOmhueOAggpkZWYgX2l0ZW1f"
    "c2Vuc2l0aXZpdHkoaXQ6IGRpY3QpOgogICAgIiIi5qCh6aqM5YyF5YaF5p2h55uu55qE5a+G57qnIOKGkiAo5a+G57qnLCDmi5LmlLbnkIbnlLEp44CCKipm"
    "YWlsLWNsb3NlZCoq44CCCgogICAgaXNzdWUgIzI1OO+8mue8uuWtl+autS/pnZ7lrZfnrKbkuLIv5pyq55+l5qGj5LiA5b6L6L+U5Zue55CG55Sx77yI6LCD"
    "55So5pa56Lez6L+H77yM5LiN5YaZ55uY77yJ44CCCiAgICDml6fmoLzlvI/ljIXvvIjml6Agc2Vuc2l0aXZpdHnvvInlm6DmraTkuIDlvovmi5LmlLbigJTi"
    "gJTmnInmhI/nmoTooYzkuLrlj5jmm7TjgIIKICAgICIiIgogICAgcmF3ID0gaXQuZ2V0KCJzZW5zaXRpdml0eSIpCiAgICBpZiByYXcgaXMgTm9uZToKICAg"
    "ICAgICByZXR1cm4gTm9uZSwgIuadoeebrue8uiBzZW5zaXRpdml0eSDlrZfmrrXvvIjml6fmoLzlvI/ljIXkuIDlvovmi5LmlLbvvIkiCiAgICBpZiBub3Qg"
    "aXNpbnN0YW5jZShyYXcsIHN0cik6CiAgICAgICAgcmV0dXJuIE5vbmUsICLmnaHnm64gc2Vuc2l0aXZpdHkg6Z2e5a2X56ym5Liy77yaJXIiICUgKHJhdywp"
    "CiAgICBzID0gcmF3LnN0cmlwKCkubG93ZXIoKQogICAgaWYgcyBub3QgaW4gX1NFTlNJVElWSVRZX09SREVSOgogICAgICAgIHJldHVybiBOb25lLCAi5p2h"
    "55uuIHNlbnNpdGl2aXR5IOacquefpeaho++8miVy77yI5ZCI5rOV5qGjICVz77yJIiAlICgKICAgICAgICAgICAgcmF3LCAiLyIuam9pbihfU0VOU0lUSVZJ"
    "VFlfT1JERVIpKQogICAgcmV0dXJuIHMsICIiCgoKZGVmIF9ub3RlX3JlamVjdChwYWNrOiBkaWN0LCByZWFzb246IHN0ciwgc3dhcm06IHN0ciA9IE5vbmUs"
    "ICoqa3cpIC0+IGRpY3Q6CiAgICByZWMgPSB7ImF0IjogdGltZS50aW1lKCksICJyZWFzb24iOiByZWFzb24sCiAgICAgICAgICAgImZyb21fbm9kZSI6IChw"
    "YWNrIG9yIHt9KS5nZXQoImZyb21fbm9kZSIpLAogICAgICAgICAgICJwYWNrX2lkIjogKHBhY2sgb3Ige30pLmdldCgicGFja19pZCIpfQogICAgcmVjLnVw"
    "ZGF0ZSh7azogdiBmb3IgaywgdiBpbiBrdy5pdGVtcygpIGlmIHYgaXMgbm90IE5vbmV9KQogICAgdHJ5OgogICAgICAgIGZyb20gLmZzdXRpbCBpbXBvcnQg"
    "YXBwZW5kX2pzb25sCiAgICAgICAgb3MubWFrZWRpcnMoaW5ib3hfZGlyKHN3YXJtKSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBhcHBlbmRfanNvbmwob3Mu"
    "cGF0aC5qb2luKGluYm94X2Rpcihzd2FybSksICJfcmVqZWN0ZWQuanNvbmwiKSwgcmVjKQogICAgZXhjZXB0IE9TRXJyb3I6CiAgICAgICAgcGFzcwogICAg"
    "b3V0ID0geyJvayI6IEZhbHNlLCAicmVqZWN0ZWQiOiBUcnVlLCAicmVhc29uIjogcmVhc29uLAogICAgICAgICAgICJmcm9tX25vZGUiOiByZWMuZ2V0KCJm"
    "cm9tX25vZGUiKX0KICAgIG91dC51cGRhdGUoe2s6IHYgZm9yIGssIHYgaW4ga3cuaXRlbXMoKSBpZiB2IGlzIG5vdCBOb25lfSkKICAgIHJldHVybiBvdXQK"
    "CgojIOeUn+aViOadoeS7tu+8muW9k+S8oOWFpSBjZ+OAgXNyY+OAgXN1YnN5c3Rlbe+8iOm7mOiupCBTVUJTWVNURU3vvInjgIFzd2FybeOAgXNpZ25lcnNf"
    "ZmlsZeOAgWFyY2hpdmXvvIjpu5jorqQgVHJ1Ze+8ieaXtu+8jOS+neasoeivu+WPliBzcmMg5Li6IHBhY2vjgIFfdmFsaWRhdGUg5qCh6aqM44CB5p2l5rqQ"
    "IG5vZGVfaWQg5LiN562J5LqO5pys6IqC54K544CBX3NpZ25lci52ZXJpZnlfZm9yIOmqjOetvuaIkOWKn+OAgeS4lOacieetvuWQjeaIliBzaWduZXIg562J"
    "5LqOICJudWxsIiDmlrnlj6/pgJrov4fvvJvpgJrov4fliJnlr7kgcGFja1siaXRlbXMiXSDliY3luLjph48gTUFYX0lURU1TIOmhueS4rSBzdWJqZWN0L3Rl"
    "eHQg6Z2e56m66ICF5LulIF9pZGVudGl0eS5vYnNlcnZlIOWGmeWFpe+8iOW4puW4uOmHjyBUQUdfWE5PREUg5ZKMIFNPVVJDRV9QUkVGSVgg5qCH562+77yM"
    "aW1wb3J0YW5jZSDpu5jorqQgMC4177yMdmVyaWZpY2F0aW9uX2Jhc2lzIOm7mOiupCAiZGF0YSLvvInvvIznu5/orqEgd3JpdHRlbi9za2lwcGVk77yM6Iul"
    "IGFyY2hpdmUg5Li655yf5YiZ5YaZ5YyF5Yiw5pS25Lu2566x77yM6L+U5Zue5ZCrIG9r44CBZnJvbV9ub2Rl44CBcGFja19pZOOAgWltcG9ydGVk44CBc2tp"
    "cHBlZOOAgXRydW5jYXRlZOOAgW5vZGVfaWRz44CBYXJjaGl2ZWQg55qE5a2X5YW477yb5Lu75LiA5ouS57ud5YiG5pSv6LCD55SoIF9ub3RlX3JlamVjdCDo"
    "v5Tlm57mi5Lnu53nu5PmnpzjgIIKZGVmIF9zZWVuX3BhdGgoY2cpIC0+IHN0cjoKICAgICIiIuW3suingeWPsOi0pui3r+W+hO+8iOacrOaguemhtuWxgu+8"
    "ieOAgmNnLnJvb3Qg5LiN5Y+v55So5pe26L+U5Zue56m65Liy77yI6LCD55So5pa55oyJ5peg6LSm5aSE55CG77yJ44CCIiIiCiAgICByb290ID0gZ2V0YXR0"
    "cihjZywgInJvb3QiLCBOb25lKQogICAgcmV0dXJuIG9zLnBhdGguam9pbihzdHIocm9vdCksIFNFRU5fRklMRSkgaWYgcm9vdCBlbHNlICIiCgoKZGVmIF9s"
    "b2FkX3NlZW4oY2cpIC0+IGRpY3Q6CiAgICAiIiLor7vlj7DotKbjgILnvLrmlofku7YgLyDlnY8gSlNPTiAvIOmdnuWvueixoeS4gOW+i+aMieepuui0puKA"
    "lOKAlOWPsOi0puaYr+mYsumHjeaUvu+8jOS4jeaYr+WGmeWFpeWJjeaPkOOAgiIiIgogICAgcCA9IF9zZWVuX3BhdGgoY2cpCiAgICBpZiBub3QgcDoKICAg"
    "ICAgICByZXR1cm4ge30KICAgIHRyeToKICAgICAgICB3aXRoIG9wZW4ocCwgInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBkYXRh"
    "ID0ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgKE9TRXJyb3IsIFZhbHVlRXJyb3IpOgogICAgICAgIHJldHVybiB7fQogICAgcmV0dXJuIGRhdGEgaWYgaXNp"
    "bnN0YW5jZShkYXRhLCBkaWN0KSBlbHNlIHt9CgoKZGVmIF9zYXZlX3NlZW4oY2csIHNlZW46IGRpY3QpIC0+IE5vbmU6CiAgICAiIiLokL3nm5jlj7DotKbj"
    "gILlpLHotKUqKuS4jemAg+mAuCoq77yI5ZCM5LiK77ya5Y+w6LSm5LiN5piv5YaZ5YWl5YmN5o+Q77yJ44CCIiIiCiAgICBwID0gX3NlZW5fcGF0aChjZykK"
    "ICAgIGlmIG5vdCBwOgogICAgICAgIHJldHVybgogICAgdHJ5OgogICAgICAgIHdpdGggb3BlbihwLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAg"
    "ICAgICAgICAgIGpzb24uZHVtcChzZWVuLCBmLCBlbnN1cmVfYXNjaWk9RmFsc2UsIHNvcnRfa2V5cz1UcnVlKQogICAgZXhjZXB0IE9TRXJyb3I6CiAgICAg"
    "ICAgcGFzcwoKCmRlZiBfaW1wb3J0X2xheWVyKHJhdyk6CiAgICAiIiLokL3lsYLnmb3lkI3ljZXvvIhpc3N1ZSAjMTkxLUHvvIktPiAo5bGCLCDmmK/lkKbl"
    "pLnntKcp44CC6Z2e55m95ZCN5Y2V5bGC5LiA5b6L5pS56JC9IGtub3dsZWRnZeOAgiIiIgogICAgbGF5ZXIgPSByYXcuc3RyaXAoKSBpZiBpc2luc3RhbmNl"
    "KHJhdywgc3RyKSBlbHNlICJrbm93bGVkZ2UiCiAgICBpZiBsYXllciBub3QgaW4gSU1QT1JUX0xBWUVSUzoKICAgICAgICByZXR1cm4gImtub3dsZWRnZSIs"
    "IDEKICAgIHJldHVybiBsYXllciwgMAoKCmRlZiBfaW1wb3J0X2ltcG9ydGFuY2UocmF3KToKICAgICIiIumHjeimgeW6puWkueWIsCBbMCwgSU1QT1JUX0lN"
    "UE9SVEFOQ0VfTUFYXe+8iGlzc3VlICMxOTEtQe+8iS0+ICjlgLwsIOaYr+WQpuWkuee0pynjgIIKCiAgICDpnZ7mlbDlgLwgLyBib29sIC8g6Z2e5pyJ6ZmQ"
    "5YC85oyJ5LiK6ZmQ5aSE55CG77yI5LiOICMxNTEg5a+56LaK55WM5YC85Zue6JC9IDAuNSDlkIzlj6PlvoTvvIzkvYbkuIrpmZAKICAgIOabtOS9juKAlOKA"
    "lOingSBJTVBPUlRfSU1QT1JUQU5DRV9NQVgg6K+05piO77yJ44CC57y655yB77yITm9uZe+8ieayv+eUqOaXouaciSAwLjXvvIzkuI3nrpflpLnntKfjgIIK"
    "ICAgICIiIgogICAgaWYgcmF3IGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIElNUE9SVF9JTVBPUlRBTkNFX01BWCwgMAogICAgaWYgaXNpbnN0YW5jZShyYXcs"
    "IGJvb2wpIG9yIG5vdCBpc2luc3RhbmNlKHJhdywgKGludCwgZmxvYXQpKToKICAgICAgICByZXR1cm4gSU1QT1JUX0lNUE9SVEFOQ0VfTUFYLCAxCiAgICB2"
    "ID0gZmxvYXQocmF3KQogICAgaWYgbm90IG1hdGguaXNmaW5pdGUodik6CiAgICAgICAgcmV0dXJuIElNUE9SVF9JTVBPUlRBTkNFX01BWCwgMQogICAgaWYg"
    "diA8IDAuMDoKICAgICAgICByZXR1cm4gMC4wLCAxCiAgICBpZiB2ID4gSU1QT1JUX0lNUE9SVEFOQ0VfTUFYOgogICAgICAgIHJldHVybiBJTVBPUlRfSU1Q"
    "T1JUQU5DRV9NQVgsIDEKICAgIHJldHVybiB2LCAwCgoKZGVmIGltcG9ydF9wYWNrKGNnLCBzcmMsICosIHN1YnN5c3RlbTogc3RyID0gU1VCU1lTVEVNLCBz"
    "d2FybTogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgIHNpZ25lcnNfZmlsZTogc3RyID0gTm9uZSwgYXJjaGl2ZTogYm9vbCA9IFRydWUpIC0+IGRpY3Q6"
    "CiAgICAiIiLlr7zlhaXlr7nnq6/or4Hmja7ljIXvvJrpqoznrb4g4oaSIOiQveacrOague+8iOW4piBgc291cmNlOjxub2RlPmAg5qCH562+77yJ44CCCgog"
    "ICAgZmFpbC1jbG9zZWTvvJrnu5PmnoTkuI3lkIjms5XjgIHmnaXmupDljbPmnKzoioLngrnjgIHpqoznrb7lpLHotKXjgIHnvLrnrb7lkI0g4oaSIOS4gOW+"
    "i+aLkuaUtuW5tueVmeeXleOAggogICAgIiIiCiAgICB0cnk6CiAgICAgICAgcGFjayA9IF9yZWFkX3BhY2soc3JjKQogICAgZXhjZXB0IChPU0Vycm9yLCBW"
    "YWx1ZUVycm9yKSBhcyBlOgogICAgICAgIHJldHVybiBfbm90ZV9yZWplY3Qoe30sIGYi6K+B5o2u5YyF6K+75Y+W5aSx6LSl77yae2V9Iiwgc3dhcm09c3dh"
    "cm0pCgogICAgZXJyID0gX3ZhbGlkYXRlKHBhY2spCiAgICBpZiBlcnI6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVjdChwYWNrLCBlcnIsIHN3YXJtPXN3"
    "YXJtKQoKICAgIGZyb21fbm9kZSA9IHBhY2tbImZyb21fbm9kZSJdLnN0cmlwKCkKICAgIGlmIGZyb21fbm9kZSA9PSBub2RlX2lkKGdldGF0dHIoY2csICJy"
    "b290IiwgTm9uZSkpOgogICAgICAgIHJldHVybiBfbm90ZV9yZWplY3QocGFjaywgIuivgeaNruWMheadpea6kOWNs+acrOiKgueCue+8iOaLkue7neiHquWv"
    "vOWFpe+8iSIsIHN3YXJtPXN3YXJtKQoKICAgIHNpZ25hdHVyZSA9ICgocGFjay5nZXQoInNpZyIpIG9yIHt9KS5nZXQoInNpZ25hdHVyZSIpIG9yICIiKS5z"
    "dHJpcCgpCiAgICB2cmVzID0gX3NpZ25lci52ZXJpZnlfZm9yKHN1YnN5c3RlbSwgX3BhY2tfcGF5bG9hZChwYWNrKSwgc2lnbmF0dXJlLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBhY3Rpb249U0lHTl9BQ1RJT04sIHBhdGg9c2lnbmVyc19maWxlKQogICAgaWYgbm90IHZyZXMuZ2V0KCJvayIpOgogICAg"
    "ICAgIHJldHVybiBfbm90ZV9yZWplY3QocGFjaywgZiLpqoznrb7lpLHotKXvvJp7dnJlcy5nZXQoJ3JlYXNvbicpIG9yICfmnKrnn6UnfSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBzd2FybT1zd2FybSwgb25fZmFpbD12cmVzLmdldCgib25fZmFpbCIpKQogICAgaWYgbm90IHNpZ25hdHVyZSBhbmQgKHBh"
    "Y2suZ2V0KCJzaWciKSBvciB7fSkuZ2V0KCJzaWduZXIiKSAhPSAibnVsbCI6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVjdChwYWNrLCAi6K+B5o2u5YyF"
    "57y65bCR562+5ZCN77yI6Leo6IqC54K56K+B5o2u5b+F6aG75Y+v5rqv5rqQ77yJIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHN3YXJtPXN3YXJt"
    "KQoKICAgICMgaXNzdWUgIzE5MS1C77ya5YyF54mI5pys5LulKirnrb7lkI3ovb3ojbfph4znmoQgY3JlYXRlZF9hdCoqIOS4uuWHhu+8iGBfcGFja19wYXls"
    "b2FkYCDlt7LlkKvlroPvvIwKICAgICMg5a+556uv5pS55LiN5LqG77yJ44CC57y655yB5oyJIDDvvIjlj6rog73mlrDlu7rjgIHkuI3og73opoblhpnvvInv"
    "vJvpnZ7mlbDlgLwgLyDpnZ7mnInpmZDlgLzmlbTljIXmi5LmlLbjgIIKICAgIGNyZWF0ZWQgPSBwYWNrLmdldCgiY3JlYXRlZF9hdCIpCiAgICBpZiBjcmVh"
    "dGVkIGlzIE5vbmU6CiAgICAgICAgY3JlYXRlZCA9IDAuMAogICAgZWxpZiAoaXNpbnN0YW5jZShjcmVhdGVkLCBib29sKSBvciBub3QgaXNpbnN0YW5jZShj"
    "cmVhdGVkLCAoaW50LCBmbG9hdCkpCiAgICAgICAgICBvciBub3QgbWF0aC5pc2Zpbml0ZShjcmVhdGVkKSk6CiAgICAgICAgcmV0dXJuIF9ub3RlX3JlamVj"
    "dChwYWNrLCBmIuivgeaNruWMhSBjcmVhdGVkX2F0IOmdnuazle+8mntjcmVhdGVkIXJ9Iiwgc3dhcm09c3dhcm0pCiAgICBzZWVuID0gX2xvYWRfc2Vlbihj"
    "ZykKICAgIGl0ZW1zID0gcGFja1siaXRlbXMiXVs6TUFYX0lURU1TXQogICAgd3JpdHRlbiwgc2tpcHBlZCwgcmVwbGF5ZWQsIGNsYW1wZWQgPSBbXSwgMCwg"
    "MCwgMAogICAgIzogaXNzdWUgIzI1OO+8muaLkuaUtueQhueUseeVmeeXle+8iOatpOWJjemZjee6pyoq5LiN5Y+v6KeBKirigJTigJTov5Tlm57kvZPlj6ro"
    "r7QgaW1wb3J0ZWQ6IE7vvIkKICAgIHJlYXNvbnMgPSBbXQogICAgdHJ5OgogICAgICAgIGZvciBpdCBpbiBpdGVtczoKICAgICAgICAgICAgaWYgbm90IGlz"
    "aW5zdGFuY2UoaXQsIGRpY3QpOgogICAgICAgICAgICAgICAgc2tpcHBlZCArPSAxCiAgICAgICAgICAgICAgICByZWFzb25zLmFwcGVuZCgi5p2h55uu6Z2e"
    "5a2X5YW4IikKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHN1YmogPSAoaXQuZ2V0KCJzdWJqZWN0Iikgb3IgIiIpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgdGV4dCA9IChpdC5nZXQoInRleHQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBpZiBub3Qgc3ViaiBvciBub3QgdGV4dDoKICAgICAg"
    "ICAgICAgICAgIHNraXBwZWQgKz0gMQogICAgICAgICAgICAgICAgcmVhc29ucy5hcHBlbmQoIuadoeebrue8uiBzdWJqZWN0L3RleHQiKQogICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICAgICAgIyBpc3N1ZSAjMjU477ya5a+G57qnIGZhaWwtY2xvc2Vk44CC57y65a2X5q61L+mdnuWtl+espuS4si/mnKrn"
    "n6XmoaPkuIDlvosqKuS4jeWGmeebmCoq77yMCiAgICAgICAgICAgICMg57ud5LiN5Zue6JC95YiwIERFRkFVTFRfU0VOU0lUSVZJVFnvvIjpgqPmraPmmK/m"
    "nKzku7bnmoTnl4XosaHvvInjgILml6fmoLzlvI/ljIXvvIjml6AKICAgICAgICAgICAgIyBzZW5zaXRpdml0ee+8ieWboOatpOS4gOW+i+S4jeaUtuKAlOKA"
    "lCoq5pyJ5oSP55qE6KGM5Li65Y+Y5pu0KirvvIzkuI7jgIzot6joioLngrnor4Hmja7msqHmnIkKICAgICAgICAgICAgIyDnrb7lkI3lsLHkuI3lj6/muq/m"
    "upDvvIzlroHlj6/kuI3kuqflh7rjgI3lkIzlj6PlvoTjgIIKICAgICAgICAgICAgc2Vucywgd2h5ID0gX2l0ZW1fc2Vuc2l0aXZpdHkoaXQpCiAgICAgICAg"
    "ICAgIGlmIHdoeToKICAgICAgICAgICAgICAgIHNraXBwZWQgKz0gMQogICAgICAgICAgICAgICAgcmVhc29ucy5hcHBlbmQod2h5KQogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgdGFncyA9IFtUQUdfWE5PREUsIGYie1NPVVJDRV9QUkVGSVh9e2Zyb21fbm9kZX0iXQogICAgICAgICAgICB0YWdz"
    "ICs9IFt0IGZvciB0IGluIChpdC5nZXQoInRhZ3MiKSBvciBbXSkKICAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh0LCBzdHIpIGFuZCB0CiAg"
    "ICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdC5zdGFydHN3aXRoKCJzdWJqZWN0OiIpCiAgICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdC5zdGFydHN3"
    "aXRoKFNPVVJDRV9QUkVGSVgpCiAgICAgICAgICAgICAgICAgICAgIGFuZCB0IG5vdCBpbiAoVEFHX1hOT0RFLCBfaWRlbnRpdHkuVEFHX0FOQ0hPUiwgX2lk"
    "ZW50aXR5LlRBR19UUkFJVCldCiAgICAgICAgICAgICMgaXNzdWUgIzE5MS1B77ya6JC95bGC55m95ZCN5Y2VICsg6YeN6KaB5bqm5aS557Sn4oCU4oCU5a+5"
    "56uv5aOw5piO5LiN5b6X6Ieq6YCJ5L+d5oqk57qn44CCCiAgICAgICAgICAgIGxheWVyLCBjX2xheWVyID0gX2ltcG9ydF9sYXllcihpdC5nZXQoImxheWVy"
    "IikpCiAgICAgICAgICAgIGltcCwgY19pbXAgPSBfaW1wb3J0X2ltcG9ydGFuY2UoaXQuZ2V0KCJpbXBvcnRhbmNlIikpCiAgICAgICAgICAgIGNsYW1wZWQg"
    "Kz0gY19sYXllciArIGNfaW1wCiAgICAgICAgICAgIHhpZCA9IF94bm9kZV9pZChmcm9tX25vZGUsIGl0LmdldCgibm9kZV9pZCIpIG9yIHN1YmopCiAgICAg"
    "ICAgICAgICMgaXNzdWUgIzE5MS1C77ya5pen5YyF6YeN5pS+5LiN5b6X5oqK5paw6K+B5o2u6KaG5YaZ5Zue5pen5YaF5a6577yI5ZCr5bGe5Li75Yig6Zmk"
    "5ZCO5aSN5rS777yJ44CCCiAgICAgICAgICAgIGxhc3QgPSBzZWVuLmdldCh4aWQpCiAgICAgICAgICAgIGlmIChpc2luc3RhbmNlKGxhc3QsIChpbnQsIGZs"
    "b2F0KSkgYW5kIG5vdCBpc2luc3RhbmNlKGxhc3QsIGJvb2wpCiAgICAgICAgICAgICAgICAgICAgYW5kIGNyZWF0ZWQgPD0gbGFzdCk6CiAgICAgICAgICAg"
    "ICAgICByZXBsYXllZCArPSAxCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAjIGlzc3VlICMxOTEtQ++8muacrOaguemHjOaBsOWlveWQ"
    "jOWQjeeahCoq5pys5ZywKiroioLngrnvvIjkuI3luKYgeG5vZGU6Y3Jvc3Mg5qCH562+77yJ5LiN5b6XCiAgICAgICAgICAgICMg6KKr5a+556uv6KaG5YaZ"
    "4oCU4oCUb3ZlcnJpZGUg5Y+q55So5LqO5pu05paw5pys5p2l5rqQ6Ieq5bex55qEIHhub2Rl44CCCiAgICAgICAgICAgIHByZXYgPSAoY2cuaW5kZXguZ2V0"
    "KCJub2RlcyIpIG9yIHt9KS5nZXQoeGlkKQogICAgICAgICAgICBpZiBwcmV2IGlzIG5vdCBOb25lIGFuZCBUQUdfWE5PREUgbm90IGluIHNldChwcmV2Lmdl"
    "dCgidGFncyIpIG9yIFtdKToKICAgICAgICAgICAgICAgIHNraXBwZWQgKz0gMQogICAgICAgICAgICAgICAgcmVhc29ucy5hcHBlbmQoIuWQjOWQjeacrOWc"
    "sOiKgueCue+8iOmdnui3qOiKgueCueivgeaNru+8ieS4jeimhuWGme+8miVzIiAlIHhpZCkKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIF9pZGVudGl0eS5vYnNlcnZlKAogICAgICAgICAgICAgICAgICAgIGNnLCBzdWJqLCB0ZXh0LAogICAgICAgICAgICAg"
    "ICAgICAgIGtpbmQ9aXQuZ2V0KCJraW5kIiksIHJvbGU9aXQuZ2V0KCJyb2xlIiksCiAgICAgICAgICAgICAgICAgICAgbGF5ZXI9bGF5ZXIsCiAgICAgICAg"
    "ICAgICAgICAgICAgdGFncz10YWdzLAogICAgICAgICAgICAgICAgICAgIGltcG9ydGFuY2U9aW1wLAogICAgICAgICAgICAgICAgICAgIHZlcmlmaWNhdGlv"
    "bl9iYXNpcz1pdC5nZXQoInZlcmlmaWNhdGlvbl9iYXNpcyIpIG9yICJkYXRhIiwKICAgICAgICAgICAgICAgICAgICBub2RlX2lkPXhpZCwKICAgICAgICAg"
    "ICAgICAgICAgICBzZW5zaXRpdml0eT1zZW5zLAogICAgICAgICAgICAgICAgICAgIG92ZXJyaWRlPVRydWUpCiAgICAgICAgICAgIGV4Y2VwdCBfQWNjZXNz"
    "RGVuaWVkOgogICAgICAgICAgICAgICAgIyBpc3N1ZSAjMjU477ya5a+85YWl5pa55a+G57qn5LiN6LazIOKHkiAqKui3s+i/h++8jOS4jemZjee6p+iQveeb"
    "mCoq77yI5q2k5YmN5Lya6JC95YiwCiAgICAgICAgICAgICAgICAjIOe8uuecgSBpbnRlcm5hbO+8jOetieS6juaKiuWvueerr+eahCBwcml2YXRlIOa0l+aI"
    "kCBpbnRlcm5hbO+8ieOAggogICAgICAgICAgICAgICAgc2tpcHBlZCArPSAxCiAgICAgICAgICAgICAgICByZWFzb25zLmFwcGVuZCgi5pys6IqC54K55a+G"
    "57qn5LiN6Laz77yIc2Vuc2l0aXZpdHk9JXPvvIkiICUgc2VucykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHdyaXR0ZW4uYXBwZW5k"
    "KHhpZCkKICAgICAgICAgICAgc2Vlblt4aWRdID0gY3JlYXRlZAoKICAgIGZpbmFsbHk6CiAgICAgICAgX3NhdmVfc2VlbihjZywgc2VlbikKCiAgICBhcmNo"
    "aXZlZCA9ICIiCiAgICBhcmNoaXZlX3NraXBwZWQgPSAiIgogICAgaWYgYXJjaGl2ZToKICAgICAgICAjIGlzc3VlICMyNTjvvJrlvZLmoaPmmK8qKuaYjuaW"
    "hyBKU09OKirvvIzljIXlhoXlkKvliqDlr4bmoaPvvIhwcml2YXRlL3NlY3JldO+8ieaXtgogICAgICAgICMg5YaN6JC95LiA5Lu95Yiw5pS25Lu2566x562J"
    "5LqO57uV6L+HIEVOQ1JZUFRFRF9MRVZFTFMg4oeSIOS4jeW9kuaho+W5tue7meWHuueQhueUseOAggogICAgICAgIHNlYWxlZCA9IHNvcnRlZCh7aXQuZ2V0"
    "KCJzZW5zaXRpdml0eSIpIGZvciBpdCBpbiBpdGVtcwogICAgICAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShpdCwgZGljdCkKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGFuZCBzdHIoaXQuZ2V0KCJzZW5zaXRpdml0eSIpIG9yICIiKS5zdHJpcCgpLmxvd2VyKCkKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGluIF9FTkNSWVBURURfTEVWRUxTfSkKICAgICAgICBpZiBzZWFsZWQ6CiAgICAgICAgICAgIGFyY2hpdmVfc2tpcHBlZCA9ICgi5YyF5YaF5ZCr5Yqg"
    "5a+G5qGjICVz77ya5b2S5qGj5Li65piO5paHIEpTT07vvIwiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAi6Lez6L+H5Lul5YWN57uV6L+H6JC9"
    "55uY5Yqg5a+GIiAlICLjgIEiLmpvaW4oc2VhbGVkKSkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBhcmNoaXZlZCA9"
    "IHdyaXRlX3BhY2socGFjaywgc3dhcm09c3dhcm0pWyJmaWxlIl0KICAgICAgICAgICAgZXhjZXB0IChPU0Vycm9yLCBFdmlkZW5jZUVycm9yKToKICAgICAg"
    "ICAgICAgICAgICMgaXNzdWUgIzE0N++8muW9kuaho+i2iueVjO+8iEV2aWRlbmNlRXJyb3LvvIxyZWFscGF0aCDlhZzlupXvvInkuI7lhpnnm5gKICAgICAg"
    "ICAgICAgICAgICMg5aSx6LSl5ZCM562J5aSE55CG4oCU4oCUKirkuI3pgIPpgLgqKuOAguS/ruWJjeWPquaNlSBPU0Vycm9y77yacGFja19pZCDluKbnqboK"
    "ICAgICAgICAgICAgICAgICMg5a2X6IqC5pe2IG9wZW4oKS9yZWFscGF0aCDmipvnmoQgVmFsdWVFcnJvciDkvJoqKumAuOWHugogICAgICAgICAgICAgICAg"
    "IyBpbXBvcnRfcGFjayoq77yI5a6e5rWL77yJ77yM6LCD55So5pa55Y+q6KeB5bSp5rqD5LiU5peg55WZ55eV77yb546w5LiA5bm25pS25Y+j44CCCiAgICAg"
    "ICAgICAgICAgICBhcmNoaXZlZCA9ICIiCiAgICByZXR1cm4geyJvayI6IFRydWUsICJmcm9tX25vZGUiOiBmcm9tX25vZGUsICJwYWNrX2lkIjogcGFjay5n"
    "ZXQoInBhY2tfaWQiKSwKICAgICAgICAgICAgImltcG9ydGVkIjogbGVuKHdyaXR0ZW4pLCAic2tpcHBlZCI6IHNraXBwZWQsCiAgICAgICAgICAgICMgaXNz"
    "dWUgIzE5Me+8muiiq+Wkuee0p+eahOadoeebruaVsO+8iOWxgiAvIOmHjeimgeW6pu+8ieS4juWboOaXp+WMhemHjeaUvuiAjOi3s+i/h+eahOadoeebruaV"
    "sOOAggogICAgICAgICAgICAjIOatpOWJjei/lOWbnuS9k+WPquivtCBpbXBvcnRlZDogTu+8jOeci+S4jeWHuuiQveS6huWTquS4gOWxguOAgeS5n+ayoeaP"
    "kOekuumHjeaUvuOAggogICAgICAgICAgICAiY2xhbXBlZCI6IGNsYW1wZWQsICJyZXBsYXllZCI6IHJlcGxheWVkLAogICAgICAgICAgICAidHJ1bmNhdGVk"
    "IjogbGVuKHBhY2tbIml0ZW1zIl0pID4gTUFYX0lURU1TLAogICAgICAgICAgICAibm9kZV9pZHMiOiB3cml0dGVuLCAiYXJjaGl2ZWQiOiBhcmNoaXZlZCwK"
    "ICAgICAgICAgICAgIyBpc3N1ZSAjMjU477ya5ouS5pS255CG55Sx77yI5bCB6aG2IDIwIOadoe+8jOmYsueBjOWMheWIt+Wxj++8iSsg5b2S5qGj6Lez6L+H"
    "55CG55SxCiAgICAgICAgICAgICJza2lwcGVkX3JlYXNvbnMiOiByZWFzb25zWzoyMF0sCiAgICAgICAgICAgICJhcmNoaXZlX3NraXBwZWQiOiBhcmNoaXZl"
    "X3NraXBwZWR9CgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQoj"
    "IOafpeivogojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCgojIOeU"
    "n+aViOadoeS7tu+8muW9k+S8oOWFpSBjZ+OAgXN1YmplY3TjgIFzb3VyY2XjgIFsaW1pdO+8iOm7mOiupCAxMDDvvInml7bvvIzmlLbpm4bmoIfnrb7lkKvl"
    "uLjph48gVEFHX1hOT0RFIOeahOiKgueCue+8jOiLpSBzdWJqZWN0IOS4uuecn+WImeS7heS/neeVmSBzdWJqZWN0IOagh+etvuetieS6jiBzdWJqZWN0IOea"
    "hOiKgueCue+8jOiLpSBzb3VyY2Ug5Li655yf5YiZ5LuF5L+d55WZIHNvdXJjZSDmoIfnrb7nrYnkuo4gc291cmNlIOeahOiKgueCue+8jOi/lOWbnuacgOWQ"
    "jiBpbnQobGltaXQgb3IgMTAwKSDmnaHorrDlvZXvvIhsaW1pdCDkuLrlgYflgLzlpoIgMCDml7blj5YgMTAw77yJ55qEIGNvdW50IOS4juWIl+ihqOOAggpk"
    "ZWYgZXZpZGVuY2UoY2csICosIHN1YmplY3Q6IHN0ciA9IE5vbmUsIHNvdXJjZTogc3RyID0gTm9uZSwKICAgICAgICAgICAgIGxpbWl0OiBpbnQgPSAxMDAp"
    "IC0+IGRpY3Q6CiAgICAiIiLliJfmnKzmoLnlt7Llr7zlhaXnmoTot6joioLngrnor4Hmja7vvIjmjInmnaXmupAv5Li75L2T6L+H5ruk77yJ44CCIiIiCiAg"
    "ICBvdXQgPSBbXQogICAgbm9kZXMgPSBjZy5pbmRleC5nZXQoIm5vZGVzIikgb3Ige30KICAgIGZvciBuaWQgaW4gc29ydGVkKG5vZGVzKToKICAgICAgICBl"
    "ID0gbm9kZXNbbmlkXQogICAgICAgIHRnID0gc2V0KGUuZ2V0KCJ0YWdzIikgb3IgW10pCiAgICAgICAgaWYgVEFHX1hOT0RFIG5vdCBpbiB0ZzoKICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICBzdWJqLCBzcmMgPSAiIiwgIiIKICAgICAgICBmb3IgdCBpbiB0ZzoKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh0"
    "LCBzdHIpIGFuZCB0LnN0YXJ0c3dpdGgoInN1YmplY3Q6Iik6CiAgICAgICAgICAgICAgICBzdWJqID0gdFtsZW4oInN1YmplY3Q6Iik6XQogICAgICAgICAg"
    "ICBlbGlmIGlzaW5zdGFuY2UodCwgc3RyKSBhbmQgdC5zdGFydHN3aXRoKFNPVVJDRV9QUkVGSVgpOgogICAgICAgICAgICAgICAgc3JjID0gdFtsZW4oU09V"
    "UkNFX1BSRUZJWCk6XQogICAgICAgIGlmIHN1YmplY3QgYW5kIHN1YmogIT0gc3ViamVjdDoKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBzb3Vy"
    "Y2UgYW5kIHNyYyAhPSBzb3VyY2U6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgbm9kZSA9IGNnLmdldChuaWQpIG9yIHt9CiAgICAgICAgb3V0LmFw"
    "cGVuZCh7Im5vZGVfaWQiOiBuaWQsICJzdWJqZWN0Ijogc3ViaiwgInNvdXJjZSI6IHNyYywKICAgICAgICAgICAgICAgICAgICAibGF5ZXIiOiBlLmdldCgi"
    "bGF5ZXIiKSwKICAgICAgICAgICAgICAgICAgICAiY29udGVudCI6IChub2RlLmdldCgiY29udGVudCIpIG9yICIiKVs6NDAwXX0pCiAgICBvdXQgPSBvdXRb"
    "LWludChsaW1pdCBvciAxMDApOl0KICAgIHJldHVybiB7ImNvdW50IjogbGVuKG91dCksICJldmlkZW5jZSI6IG91dH0KCgojIOeUn+aViOadoeS7tu+8muaX"
    "oOWPguaVsOiwg+eUqOaXtui/lOWbnuWMheWQq+aooeWdl+e6p+W4uOmHjyBTVUJTWVNURU3jgIFTSUdOX0FDVElPTuOAgVNXQVJNX0RJUl9FTlbjgIFOT0RF"
    "X0lEX0VOVuOAgVJPT1RfRU5W44CBTUFYX0lURU1T44CBTUFYX1RFWFQg5Y+KIHN3YXJtX2RpcigpIOetieWtl+auteeahOiHquaPj+i/sOWtl+WFuOOAggpk"
    "ZWYgY2F0YWxvZygpIC0+IGRpY3Q6CiAgICByZXR1cm4gewogICAgICAgICJsYXllciI6ICLot6joioLngrnor4Hmja7lrZjlgqjvvIjonILnvqTkupLogZQg"
    "djAuM++8iSIsCiAgICAgICAgInF1ZXN0aW9uIjogIui3qOiKgueCue+8muS9oOWHreS7gOS5iOi/meS5iOivtCIsCiAgICAgICAgImJsaW5kc3BvdCI6ICLC"
    "pzkuMSDljZXmoLnlgYforr7igJTigJTlr7nnq6/op4LmtYvlr7nmnKzoioLngrnkuI3lj6/op4EiLAogICAgICAgICJpbnZhcmlhbnRzIjogWyLmnaXmupDl"
    "j6/muq8iLCAi5Y+v5ouS5pS2IiwgIuWFqOeoi+eVmeeXlSIsICLnpoHmraLovazmiYsiXSwKICAgICAgICAic3Vic3lzdGVtIjogU1VCU1lTVEVNLAogICAg"
    "ICAgICJzaWduX2FjdGlvbiI6IFNJR05fQUNUSU9OLAogICAgICAgICJzd2FybV9kaXIiOiBzd2FybV9kaXIoKSwKICAgICAgICAicGFja19maWVsZHMiOiBs"
    "aXN0KF9QQUNLX0ZJRUxEUyksCiAgICAgICAgImxpbWl0cyI6IHsibWF4X2l0ZW1zIjogTUFYX0lURU1TLCAibWF4X3RleHQiOiBNQVhfVEVYVH0sCiAgICAg"
    "ICAgImVudiI6IHsibm9kZV9pZCI6IE5PREVfSURfRU5WLCAic3dhcm1fZGlyIjogU1dBUk1fRElSX0VOViwKICAgICAgICAgICAgICAgICJyb290IjogUk9P"
    "VF9FTlZ9LAogICAgICAgICJob25lc3RfYm91bmRhcnkiOiAi6aqM6K+B55qE5piv44CM6K+B5o2u5p2l6Ieq6K+l6IqC54K544CN77yM5LiN5piv44CM6K+B"
    "5o2u5Li655yf44CNIiwKICAgIH0KCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tCiMg5bel5YW3CiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0KCiMg55Sf5pWI5p2h5Lu277ya5b2T5Lyg5YWlIHBhdGgg5ZKMIG9iaiDml7bvvIzlnKggcGF0aCDmiYDlnKjnm67lvZXvvIjoi6UgZGlybmFtZSDk"
    "uLrnqbrliJkgIi4i77yJ5Yib5bu655uu5b2V77yM5bCGIG9iaiDku6UgSlNPTiDlhpnlhaUgcGF0aCsiLnRtcCLvvIhlbnN1cmVfYXNjaWk9RmFsc2UsIGlu"
    "ZGVudD0xLCBzb3J0X2tleXM9VHJ1Ze+8ie+8jOWwneivlSBjaG1vZCAwNjAw77yM5pu/5o2i5YiwIHBhdGjvvIzov5Tlm54gcGF0aOOAggpkZWYgX3dyaXRl"
    "X2pzb24ocGF0aDogc3RyLCBvYmopIC0+IHN0cjoKICAgIG9zLm1ha2VkaXJzKG9zLnBhdGguZGlybmFtZShwYXRoKSBvciAiLiIsIGV4aXN0X29rPVRydWUp"
    "CiAgICB0bXAgPSBwYXRoICsgIi50bXAiCiAgICB3aXRoIG9wZW4odG1wLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1w"
    "KG9iaiwgZiwgZW5zdXJlX2FzY2lpPUZhbHNlLCBpbmRlbnQ9MSwgc29ydF9rZXlzPVRydWUpCiAgICB0cnk6CiAgICAgICAgb3MuY2htb2QodG1wLCAwbzYw"
    "MCkKICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgIHBhc3MKICAgIHB1Ymxpc2godG1wLCBwYXRoKQogICAgcmV0dXJuIHBhdGgKCgojIOeUn+aViOadoeS7"
    "tu+8muW9k+S8oOWFpSByb290IOS4lCBfcm9vdF9vZihyb290KSDov5Tlm57nnJ/lgLzml7bvvIzku6UgZGVzaWduZXIg6KeS6ImyIFByaW5jaXBhbO+8iHRl"
    "bmFudCDlj5Ygb3MuZW52aXJvbi5nZXQoIk1EQ0dfVEVOQU5UIiwgImRlZmF1bHQiKSDnmoTlrp7pmYXlgLzvvIxhY3RvciDlj5Ygb3MuZW52aXJvbi5nZXQo"
    "Ik1EQ0dfQUNUT1IiLCAic3dhcm0tY2xpIikg55qE5a6e6ZmF5YC877yJ5omT5byAIE1kQ0dTZWN1cmXvvJvlkKbliJnmipvlh7ogRXZpZGVuY2VFcnJvcuOA"
    "ggpkZWYgX29wZW5fY2cocm9vdDogc3RyID0gTm9uZSk6CiAgICAiIiJDTEkg55So77ya5LulIGRlc2lnbmVyIOi6q+S7veaJk+W8gOague+8iOS7pOeJjOi3"
    "r+W+hOS7jeaOqOiNkOi1sCBNQ1DvvInjgIIiIiIKICAgIGZyb20gLm1kY29zIGltcG9ydCBNZENHU2VjdXJlCiAgICBmcm9tIC5zZWN1cml0eSBpbXBvcnQg"
    "UHJpbmNpcGFsCiAgICBmcm9tIC50b2tlbnMgaW1wb3J0IHJvbGVfc3BlYwogICAgciA9IF9yb290X29mKHJvb3QpCiAgICBpZiBub3QgcjoKICAgICAgICBy"
    "YWlzZSBFdmlkZW5jZUVycm9yKCLnvLrlsJHmoLnnm67lvZXvvJror7forr4gTURDR19ST09UIOaIluS8oCAtLXJvb3QiKQogICAgc3BlYyA9IHJvbGVfc3Bl"
    "YygiZGVzaWduZXIiKQogICAgcCA9IFByaW5jaXBhbCh0ZW5hbnQ9b3MuZW52aXJvbi5nZXQoIk1EQ0dfVEVOQU5UIiwgImRlZmF1bHQiKSwKICAgICAgICAg"
    "ICAgICAgICAgYWN0b3I9b3MuZW52aXJvbi5nZXQoIk1EQ0dfQUNUT1IiLCAic3dhcm0tY2xpIiksCiAgICAgICAgICAgICAgICAgIGNsZWFyYW5jZT0icHJp"
    "dmF0ZSIsIGNhbl93cml0ZT1UcnVlLCBjYW5fYWRtaW49VHJ1ZSwKICAgICAgICAgICAgICAgICAgcm9sZT0iZGVzaWduZXIiLCBsYXllcnNfYWxsb3c9c3Bl"
    "Y1sibGF5ZXJzX2FsbG93Il0sCiAgICAgICAgICAgICAgICAgIG9wc19hbGxvdz1zcGVjWyJvcHNfYWxsb3ciXSwgYXV0aF9tb2RlPSJsZWdhY3lfZW52IikK"
    "ICAgICMgYXV0b2ZsdXNoPTHvvIhQMWLvvIwyMDI2LTA5LTI277yM5LiOIG1jcF9zZXJ2ZXIucHk6MzY5NS0zNzAyIC8gcmV2aWV3X2NsaS5fY2cKICAgICMg"
    "5ZCM5qy+77yJ77ya55+t5ZG95bel5YW36L+b56iL6KKrIGtpbGwg5pe2IGNsb3NlL2F0ZXhpdCDlhZzlupXkuI3miafooYzvvIznvLrnnIEgNjQg5Lya6K6p"
    "CiAgICAjIOWGmeWFpeWBnOWcqOWGheWtmCBfZGlydHnjgIHliIbniYfml6Xlv5fku47mnKrokL3igJTigJTpgJDmnaHokL3ml6Xlv5fkv53ku7vmhI/pgIDl"
    "h7rlvaLmgIHot6jov5vnqIvlj6/op4HjgIIKICAgIHJldHVybiBNZENHU2VjdXJlKHIsIHByaW5jaXBhbD1wLCBhdXRvZmx1c2g9MSkKCgojIOeUn+aViOad"
    "oeS7tu+8muW9k+S8oOWFpSBvYmog5pe277yM5omT5Y2wIGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UsIGluZGVudD0xLCBkZWZhdWx0PXN0"
    "cinjgIIKZGVmIF9wcmludChvYmopOgogICAgcHJpbnQoanNvbi5kdW1wcyhvYmosIGVuc3VyZV9hc2NpaT1GYWxzZSwgaW5kZW50PTEsIGRlZmF1bHQ9c3Ry"
    "KSkKCgojIOeUn+aViOadoeS7tu+8mmFyZ3Yg5Li6IE5vbmUg5pe25Y+WIHN5cy5hcmd2WzE6Xe+8m+e7jyBhcmdwYXJzZSDop6PmnpDlkI7lv4XloavlrZDl"
    "kb3ku6TvvIhjYXRhbG9nL2NhcmQvZXhwb3J0L2ltcG9ydCDnrYnvvInkuYvkuIDvvIzlj4LmlbDnvLrlpLHmiJbpnZ7ms5XnlLEgYXJncGFyc2Ug55u05o6l"
    "6YCA5Ye677yb6L+U5Zue6L+b56iL6YCA5Ye656CB77ybCmRlZiBtYWluKGFyZ3Y9Tm9uZSk6CiAgICBhcCA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKAog"
    "ICAgICAgIHByb2c9InB5dGhvbiAtbSBtZF9jZy5ldmlkZW5jZSIsCiAgICAgICAgZGVzY3JpcHRpb249Iui3qOiKgueCueivgeaNruWtmOWCqO+8muWQjeeJ"
    "hyAvIOWvvOWHuiAvIOWvvOWFpe+8iHYwLjPvvIkiKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXJvb3QiLCBkZWZhdWx0PU5vbmUsIGhlbHA9IuiupOefpeWb"
    "vuague+8iOm7mOiupCBNRENHX1JPT1TvvIkiKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXN3YXJtIiwgZGVmYXVsdD1Ob25lLCBoZWxwPSLlhbHkuqvnm67l"
    "vZXvvIjpu5jorqQgfi8ubWRjZy9zd2Fybe+8iSIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tc2lnbmVycy1maWxlIiwgZGVmYXVsdD1Ob25lKQogICAgc3Vi"
    "ID0gYXAuYWRkX3N1YnBhcnNlcnMoZGVzdD0iY21kIiwgcmVxdWlyZWQ9VHJ1ZSkKCiAgICBzdWIuYWRkX3BhcnNlcigiY2F0YWxvZyIsIGhlbHA9IuiHquaP"
    "j+i/sCIpCiAgICBzdWIuYWRkX3BhcnNlcigiY2FyZCIsIGhlbHA9IuacrOiKgueCueWQjeeJhyIpCiAgICBzdWIuYWRkX3BhcnNlcigicHVibGlzaCIsIGhl"
    "bHA9IuWPkeW4g+WQjeeJh+WIsOWFseS6q+ebruW9lSIpCiAgICBzdWIuYWRkX3BhcnNlcigicGVlcnMiLCBoZWxwPSLlj5HnjrDlr7nnq6/lkI3niYciKQoK"
    "ICAgIHBfZXggPSBzdWIuYWRkX3BhcnNlcigiZXhwb3J0IiwgaGVscD0i5a+85Ye66K+B5o2u5YyFIikKICAgIHBfZXguYWRkX2FyZ3VtZW50KCItLXN1Ympl"
    "Y3QiLCBhY3Rpb249ImFwcGVuZCIsIGRlZmF1bHQ9Tm9uZSkKICAgIHBfZXguYWRkX2FyZ3VtZW50KCItLW91dCIsIGRlZmF1bHQ9Tm9uZSwgaGVscD0i6L6T"
    "5Ye65paH5Lu277yI6buY6K6k5YaZ5pS25Lu2566x77yJIikKCiAgICBwX2ltID0gc3ViLmFkZF9wYXJzZXIoImltcG9ydCIsIGhlbHA9IuWvvOWFpeivgeaN"
    "ruWMhSIpCiAgICBwX2ltLmFkZF9hcmd1bWVudCgicGF0aCIpCgogICAgcF9scyA9IHN1Yi5hZGRfcGFyc2VyKCJscyIsIGhlbHA9IuWIl+W3suWvvOWFpeea"
    "hOi3qOiKgueCueivgeaNriIpCiAgICBwX2xzLmFkZF9hcmd1bWVudCgiLS1zdWJqZWN0IiwgZGVmYXVsdD1Ob25lKQogICAgcF9scy5hZGRfYXJndW1lbnQo"
    "Ii0tc291cmNlIiwgZGVmYXVsdD1Ob25lKQogICAgcF9scy5hZGRfYXJndW1lbnQoIi0tbGltaXQiLCB0eXBlPWludCwgZGVmYXVsdD0xMDApCgogICAgYSA9"
    "IGFwLnBhcnNlX2FyZ3MoYXJndikKICAgIGNnID0gTm9uZQogICAgdHJ5OgogICAgICAgIGlmIGEuY21kID09ICJjYXRhbG9nIjoKICAgICAgICAgICAgX3By"
    "aW50KGNhdGFsb2coKSkKICAgICAgICBlbGlmIGEuY21kID09ICJjYXJkIjoKICAgICAgICAgICAgX3ByaW50KGNhcmQoYS5yb290LCBzaWduZXJzX2ZpbGU9"
    "YS5zaWduZXJzX2ZpbGUpKQogICAgICAgIGVsaWYgYS5jbWQgPT0gInB1Ymxpc2giOgogICAgICAgICAgICBfcHJpbnQocHVibGlzaF9jYXJkKGEucm9vdCwg"
    "c3dhcm09YS5zd2FybSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzaWduZXJzX2ZpbGU9YS5zaWduZXJzX2ZpbGUpKQogICAgICAgIGVsaWYg"
    "YS5jbWQgPT0gInBlZXJzIjoKICAgICAgICAgICAgX3ByaW50KHBlZXJzKGEuc3dhcm0sIHJvb3Q9YS5yb290KSkKICAgICAgICBlbGlmIGEuY21kID09ICJl"
    "eHBvcnQiOgogICAgICAgICAgICBjZyA9IF9vcGVuX2NnKGEucm9vdCkKICAgICAgICAgICAgcmVzID0gZXhwb3J0X3BhY2soY2csIHN1YmplY3RzPWEuc3Vi"
    "amVjdCwgc3dhcm09YS5zd2FybSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc2lnbmVyc19maWxlPWEuc2lnbmVyc19maWxlKQogICAgICAgICAg"
    "ICBfcHJpbnQod3JpdGVfcGFjayhyZXNbInBhY2siXSwgcGF0aD1hLm91dCwgc3dhcm09YS5zd2FybSkKICAgICAgICAgICAgICAgICAgIGlmIGEub3V0IGVs"
    "c2UgcmVzKQogICAgICAgIGVsaWYgYS5jbWQgPT0gImltcG9ydCI6CiAgICAgICAgICAgIGNnID0gX29wZW5fY2coYS5yb290KQogICAgICAgICAgICBfcHJp"
    "bnQoaW1wb3J0X3BhY2soY2csIGEucGF0aCwgc3dhcm09YS5zd2FybSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNpZ25lcnNfZmlsZT1hLnNp"
    "Z25lcnNfZmlsZSkpCiAgICAgICAgZWxpZiBhLmNtZCA9PSAibHMiOgogICAgICAgICAgICBjZyA9IF9vcGVuX2NnKGEucm9vdCkKICAgICAgICAgICAgX3By"
    "aW50KGV2aWRlbmNlKGNnLCBzdWJqZWN0PWEuc3ViamVjdCwgc291cmNlPWEuc291cmNlLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgbGltaXQ9YS5s"
    "aW1pdCkpCiAgICBleGNlcHQgKEV2aWRlbmNlRXJyb3IsIF9zaWduZXIuU2lnbmVyRXJyb3IpIGFzIGU6CiAgICAgICAgcHJpbnQoZiJbbWRfY2cuZXZpZGVu"
    "Y2VdIHtlfSIsIGZpbGU9c3lzLnN0ZGVycikKICAgICAgICByZXR1cm4gMgogICAgZmluYWxseToKICAgICAgICBpZiBjZyBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY2cuY2xvc2UoKSAgICAgICAgICAjIOiQveebmOe0ouW8le+8jOS/neivgei3qOi/m+eoi+WPr+ingQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOiAgICAgICAjIG5vcWE6IEJMRTAwMSDigJTigJQg5YWz6Zet5aSx6LSl5LiN5o6p55uW5Li75rWB56iL57uT5p6c"
    "CiAgICAgICAgICAgICAgICBwYXNzCiAgICByZXR1cm4gMAoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBzeXMuZXhpdChtYWluKCkp"
)


_MUTATIONS = [  # (编号, 说明, 原串, 变异串, 期望被打红的判据组)
    ("V1", "归档闸退回只扫已写盘切片",
     '        sealed = _pack_sealed_levels(pack)',
     '        sealed = sorted({it.get("sensitivity") for it in items if isinstance(it, dict) and str(it.get("sensitivity") or "").strip().lower() in _ENCRYPTED_LEVELS})', "S2"),
    ("V2", "整包判据漏掉档位归一（大写不认）",
     '        sens, why = _item_sensitivity(it)',
     '        sens, why = (it.get("sensitivity"), "")', "S1"),
    ("V3", "整包判据改为跳过加密档而非收集",
     '        if sens in _ENCRYPTED_LEVELS:',
     '        if False:', "S2"),
]


def _live_ok():
    """盘上源自检 -> (是否可用, 原因)。

    防两类静默事故（第1条在本守卫上真实发生过）：
    1. 盘上残留上一次 --mutate 未还原的变异体 -> 判据假红（曾报 S1.3 归一失败，
       而生产代码毫无问题）；
    2. 加载进进程的模块与盘上源字节码不一致 -> 变异打在未生效的源上。
    --mutate 子进程用 MDCG_GUARD_MUT_UNDER_TEST 声明正在测的变异，
    自检跳过那一条的残留检查（那正是被测状态）。
    """
    import importlib
    import types
    import md_cg.evidence as ev
    importlib.reload(ev)
    if not (callable(getattr(ev, "_pack_sealed_levels", None))
            and callable(getattr(ev, "_pack_has_unarchivable", None))):
        return False, "盘上源缺整包扫描面（补丁未生效）"
    disk = io.open(_SRC_PATH, encoding="utf-8").read()
    under = os.environ.get("MDCG_GUARD_MUT_UNDER_TEST") or ""
    for name, desc, old, new, want in _MUTATIONS:
        if name == under:
            continue
        if new in disk:
            return False, ("盘上源仍处于 %s 变异态：%s（上一次 --mutate 未还原）"
                           % (name, desc))
    mod_code = compile(disk, _SRC_PATH, "exec")
    disk_fns = {c.co_name: c for c in mod_code.co_consts
                if isinstance(c, types.CodeType)}
    for fname in ("_pack_sealed_levels", "_pack_has_unarchivable"):
        c = disk_fns.get(fname)
        live = getattr(ev, fname, None)
        if c is None or live is None or c.co_code != live.__code__.co_code:
            return False, "加载模块与盘上源不一致（%s 字节码漂移）" % fname
    return True, ""

def _run_mutations(sel):
    import subprocess
    src = io.open(_SRC_PATH, encoding="utf-8").read()
    results = []
    for name, desc, old, new, want in _MUTATIONS:
        if sel and not name.startswith(sel):
            continue
        if old not in src:
            print("  ANCHOR-MISS %s -> %s" % (name, desc))
            return 2
        patched = src.replace(old, new, 1)
        try:
            compile(patched, _SRC_PATH, "exec")
        except SyntaxError as e:
            print("  MUT SYNTAX ERROR %s: %s" % (name, e))
            return 2
        bak = src
        io.open(_SRC_PATH, "w", encoding="utf-8", newline="").write(patched)
        try:
            r = subprocess.run([sys.executable, "-X", "utf8", "-m",
                               "md_cg.test_issue258_archive_scope"],
                              cwd=_REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600,
                              env=dict(os.environ,
                                       MDCG_GUARD_MUT_UNDER_TEST=name))
            out = r.stdout or ""
            reds = [L.strip() for L in out.splitlines() if L.strip().startswith("FAIL ")]
            hit = [L for L in reds if want and want in L]
            ok = r.returncode != 0 and bool(hit)
            results.append((name, desc, ok, len(reds), reds[:2]))
            print("  %s   %s %s  红项=%d  命中%s=%s"
                  % ("OK  " if ok else "MISS", name, desc, len(reds), want,
                     "是" if hit else "否"))
            if not ok and reds:
                print("       首个红项： " + reds[0][:160])
        finally:
            io.open(_SRC_PATH, "w", encoding="utf-8", newline="").write(bak)
    bad = [x for x in results if not x[2]]
    print("")
    if bad:
        print("定点变异自证：FAIL（%d/%d 条未打红或未点名）" % (len(bad), len(results)))
        return 1
    print("定点变异自证：PASS（每条变异都打红并点名）")
    return 0


def _groups():
    return (("S1", s1_scan_surface), ("S2", s2_tail_private_blocks),
            ("S3", s3_tail_secret_blocks), ("S4", s4_negative_control),
            ("S5", s5_undecidable_not_blocking), ("S6", s6_nondict_not_blocking),
            ("S7", s7_in_slice_still_blocks), ("S8", s8_matches_written_bytes),
            ("S9", s9_reason_retained), ("S10", s10_power))


def main():
    ok, why = _live_ok()
    if not ok:
        print("盘上源自检失败（不跑判据，防止假红/假绿）：%s" % why)
        return 2
    for gid, fn in _groups():
        try:
            fn()
        except Exception as e:
            _check("%s 组内异常" % gid, False, "%r" % (e,))
    print("")
    print("跨节点证据包归档面守卫（issue #258 补丁）：通过 %d / 失败 %d"
          % (len(_OK), len(_BAD)))
    return 0 if not _BAD else 1


if __name__ == "__main__":
    _want = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--mutate=")]
    if _want:
        sys.exit(_run_mutations(_want[0]))
    sys.exit(main())