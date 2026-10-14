# -*- coding: utf-8 -*-
"""结论比对方向性守卫（issue #189）。

【守什么】
#189 报：同生效条件、同结论槽下，**新结论整段是旧结论的子串**时，写入期冲突
检测返回 ACCEPT「无冲突」，不出 same_condition_divergence。删掉开头的否定词
（「不启用缓存」-> 「启用缓存」）或末位数字（「超时 300」-> 「超时 30」）即命中，
而反方向（旧「启用缓存」-> 新「不启用缓存」）能正常判 DEFER —— 判据不对称。

病灶：结论比对只量**一个方向**（新结论的词在旧结论里覆盖多少）：
  md_cg/consistency.py:801-802
      concl = (_cov(tw_content, _norm_ws(e_body)) if tw_content else 0.0)
  而 md_cg/mdcos.py _term_degree 对「词是文本的子串」直接给满分 1.0，
  _weighted_coverage 遂得 1.0 >= CONCLUSION_SAME（0.95，consistency.py:93）
  => 被当成「重复」，分歧分支（:803）不执行。

修法：判「相同」要求两个方向都达标。正向已达标（>= CONCLUSION_SAME）时再反
向量一次，取较小值；正向未达标时不做反向 —— 既有分歧的 conclusion_overlap
读数与阈值一字不动。

判据：
  S1  结构：反向比对在位（正向达标才做、取 min、量旧正文对新结论）。
  S2  * 否定词盲区：旧「不启用缓存」-> 新「启用缓存」须判同条件分歧。
  S3  * 数字盲区：旧「超时 300」-> 新「超时 30」须判同条件分歧。
  S4  * 端到端：cg(op=write) 动词面 + add(consistency=True) 写入面同样判出。
  S5  反方向对照：旧「启用缓存」-> 新「不启用缓存」仍判 DEFER，读数不变。
  S6  逐字重复仍判 ACCEPT（不误伤「该合并」）。
  S7  方向对称：子串/超集两个方向的 verdict 一致。
  S8  既有分歧读数不变：p11 G2 同槽不同值 0.6928、G3 同值异措辞 0.3385。
  S9  判定面不变：DEFER 只提示不拦截，两条都落盘；阈值仍 0.95。
  S10 修复前原形（git log -S 定位引入提交取父版本；未提交回落 HEAD），
      并用**临时树 + PYTHONPATH 隔离**真跑修复前源码，不得触碰本工作树。

运行：python -X utf8 -m md_cg.test_issue189_conclusion_direction
      python -X utf8 -m md_cg.test_issue189_conclusion_direction --mutate
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i189g_")
for _k in ("HOME", "MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
    # 注：末段不用 "aux"——Windows 保留设备名会被 datapath.py 的 #57 守卫拒绝。
    _name = "auxd" if _k == "MDCG_AUX_ROOT" else _k.lower()
    os.environ[_k] = os.path.join(_TMP, _name)
    os.makedirs(os.environ[_k], exist_ok=True)
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_SLEEP"] = "0"
os.environ["MDCG_WRITELIMIT"] = "0"
os.environ["MDCG_TOKEN_FILE"] = os.path.join(os.environ["MDCG_AUX_ROOT"],
                                             "tokens.json")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import consistency                    # noqa: E402
from md_cg.mdcos import MdCGOS                   # noqa: E402

_ROOT = os.environ["MDCG_ROOT"]
_OK = 0
_BAD = []

_MARK = "issue #189"
_REL = "md_cg/consistency.py"


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _ccg(fn, exe, cond="生产环境", sub="服务参数"):
    return ("# 功能名：%s\n# 生效条件：%s\n# 子功能：%s\n"
            "# 执行：%s\n# 验证方式：test\n# 不适用条件：无\n"
            % (fn, cond, sub, exe))


def _fresh():
    return MdCGOS(tempfile.mkdtemp(prefix="i189_"))


def _probe(cg, old_exe, new_exe, fn="缓存开关", sub="服务参数"):
    """落旧值 -> 对同条件同槽的新结论跑 check_consistency。

    返回 (verdict, reason, 分歧条目列表)。
    """
    cg.add("old", _ccg(fn, old_exe, sub=sub), layer="knowledge",
           consistency=True)
    r = cg.check_consistency(_ccg(fn, new_exe, sub=sub), layer="knowledge",
                             depth=0) or {}
    div = [x for x in r.get("conflicts", []) or []
           if x.get("type") == "same_condition_divergence"]
    return r.get("verdict"), r.get("reason"), div


def s1():
    print("\n[S1] 结构：正向达标时再做反向、取 min")
    src = io.open(os.path.join(_REPO, _REL), encoding="utf-8").read()
    _check("S1.1 反向比对在位（正向达标才做）",
           "if concl >= CONCLUSION_SAME:" in src and _MARK in src,
           "未找到「正向达标才做反向」的守卫")
    _check("S1.2 取 min 而非 max（取小才是否决单向满分）",
           "concl = min(concl, _cov(" in src,
           "未找到 min(concl, _cov(...))")
    _check("S1.3 反向量的是旧正文对新结论（方向不能写反）",
           "expand_query_terms_weighted(_norm_ws(e_body))" in src
           and "_norm_ws(n_concl)" in src,
           "反向两侧写反或缺失")
    _check("S1.4 未新增 import（expand_query_terms_weighted 本就在 :53 导入）",
           src.count("from .mdcg import") == 1,
           str(src.count("from .mdcg import")))

    # v2 的关键不变量：反向取小必须落在 `else:` 支内（真分歧路径）。
    # 放到支外（参考补丁形态）会把 H8 的 tight 短路 conc1 = 1.0 与
    # 结论面皆空短路一并打成假分歧 —— 实测 3 项回归。
    _blk = src[src.find("# issue #189"):]
    _else_at = src.rfind("                else:", 0, src.find("# issue #189"))
    _if_at = src.find("if concl >= CONCLUSION_SAME:", _blk and src.find("# issue #189"))
    _ind = _if_at - (src.rfind(chr(10), 0, _if_at) + 1) if _if_at > 0 else -1
    _before = src[src.find("# issue #189"):_if_at] if _if_at > 0 else ""
    _after = src[_if_at:src.find("if concl < CONCLUSION_SAME:", _if_at)] if _if_at > 0 else ""
    _mark_at = src.find("# issue #189")
    _if_at = src.find("if concl >= CONCLUSION_SAME:", _mark_at)
    _ind = _if_at - (src.rfind(chr(10), 0, _if_at) + 1) if _if_at > 0 else -1
    _pre = src[max(0, _mark_at - 260):_mark_at] if _mark_at > 0 else ""
    _check("S1.5 * 反向取小在 else 支内（不作用于 tight 短路路径）",
           _ind == 20 and "else:" in _pre and "concl = (_cov(tw_content" in _pre,
           "缩进=%s（须 20：在 else 支内；前文须含 else: 与 concl = (_cov(tw_content" % _ind)


def s2():
    print("\n[S2] 否定词盲区：新结论是旧结论去掉否定词后的子串")
    v, reason, div = _probe(_fresh(), "不启用缓存", "启用缓存")
    _check("S2.1 * 「不启用缓存」-> 「启用缓存」判同条件分歧",
           bool(div), "verdict=%s reason=%s" % (v, reason))
    _check("S2.2 verdict 为 DEFER（需裁决是更正还是分支）", v == "DEFER", str(v))
    _check("S2.3 conclusion_overlap 读数 > 0 且 < CONCLUSION_SAME",
           bool(div) and 0.0 < div[0].get("conclusion_overlap", 1.0) < 0.95,
           str(div[0].get("conclusion_overlap") if div else None))
    v2, _r2, div2 = _probe(_fresh(), "禁止直接推送到 main 分支",
                           "直接推送到 main 分支", fn="推送规则")
    _check("S2.4 * 长否定前缀「禁止…」-> 去前缀同样判分歧", bool(div2),
           "verdict=%s" % v2)


def s3():
    print("\n[S3] 数字盲区：新结论是旧结论去掉末位数字后的子串")
    v, _reason, div = _probe(_fresh(), "超时 300", "超时 30", fn="请求超时")
    _check("S3.1 * 「超时 300」-> 「超时 30」判同条件分歧", bool(div),
           "verdict=%s" % v)
    _v2, _r2, div2 = _probe(_fresh(), "限制 1000", "限制 100", fn="限流阈值")
    _check("S3.2 * 「限制 1000」-> 「限制 100」同样判分歧", bool(div2))
    _v3, _r3, div3 = _probe(_fresh(), "版本 3.12", "版本 3.1", fn="依赖版本")
    _check("S3.3 * 小数版本号「3.12」-> 「3.1」同样判分歧", bool(div3))


def s4():
    print("\n[S4] 端到端：cg(op=write) 动词面 + add(consistency=True) 写入面")
    from md_cg import mcp_server
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    from md_cg.tokens import role_spec
    root = tempfile.mkdtemp(prefix="i189_mcp_")
    sp = role_spec("designer")
    cg = MdCGSecure(root, principal=Principal(
        actor="designer", clearance="internal", can_write=True,
        can_admin=True, role="designer", layers_allow=sp["layers_allow"],
        ops_allow=sp["ops_allow"], session="s189"))

    def w(nid, exe):
        return mcp_server._dispatch(cg, "cg", {
            "op": "write", "node_id": nid, "content": _ccg("缓存开关", exe),
            "layer": "knowledge", "content_kind": "text",
            "verification_basis": "test"})

    w("e2e_old", "不启用缓存")
    r2 = w("e2e_new", "启用缓存")
    c = (r2 or {}).get("consistency") or {}
    div = [x for x in c.get("conflicts", []) or []
           if x.get("type") == "same_condition_divergence"]
    _check("S4.1 * cg(op=write) 端到端判出同条件分歧", bool(div),
           json.dumps(c, ensure_ascii=False, default=str)[:220])
    _check("S4.2 端到端 verdict=DEFER", c.get("verdict") == "DEFER",
           str(c.get("verdict")))
    _check("S4.3 DEFER 不拦截写入（新条目仍落盘）",
           bool(cg.get("e2e_new")), "e2e_new 未落盘")

    # 写入面（add(consistency=True)）：结果落 frontmatter.consistency
    cg2 = _fresh()
    cg2.add("w_old", _ccg("缓存开关", "不启用缓存"), layer="knowledge",
            consistency=True)
    cg2.add("w_new", _ccg("缓存开关", "启用缓存"), layer="knowledge",
            consistency=True)
    fm = (cg2.get("w_new") or {}).get("frontmatter") or {}
    _check("S4.4 * add(consistency=True) 写入面 frontmatter 判 DEFER",
           (fm.get("consistency") or {}).get("verdict") == "DEFER",
           str(fm.get("consistency")))


def s5():
    print("\n[S5] 反方向对照：旧「启用缓存」-> 新「不启用缓存」")
    v, _reason, div = _probe(_fresh(), "启用缓存", "不启用缓存")
    _check("S5.1 仍判 DEFER（修前本来就检得出）", v == "DEFER", str(v))
    _check("S5.2 * 读数不变：conclusion_overlap == 0.4",
           bool(div) and round(div[0].get("conclusion_overlap", -1), 4) == 0.4,
           str(div[0].get("conclusion_overlap") if div else None))


def s6():
    print("\n[S6] 不误伤：逐字重复仍判 ACCEPT（该合并）")
    _fresh_cg = _fresh()
    v, _reason, div = _probe(_fresh_cg, "启用缓存", "启用缓存")
    _check("S6.1 逐字重复判 ACCEPT 且无分歧", v == "ACCEPT" and not div,
           "verdict=%s div=%d" % (v, len(div)))
    cg = _fresh()
    cg.add("old", _ccg("缓存开关", "启用缓存"), layer="knowledge",
           consistency=True)
    rr = cg.check_consistency(_ccg("缓存开关", "启用缓存"), layer="knowledge",
                              depth=0, auto_flywheel=True)
    _check("S6.2 逐字重复不建 unresolved 工单",
           not (rr or {}).get("unresolved_id"), "")


def s7():
    print("\n[S7] 方向对称：子串/超集两个方向 verdict 一致")
    v_new_sub = _probe(_fresh(), "启用缓存，TTL 60 秒", "启用缓存")[0]
    v_old_sub = _probe(_fresh(), "启用缓存", "启用缓存，TTL 60 秒")[0]
    _check("S7.1 * 两个方向 verdict 一致（修前一个 ACCEPT 一个 DEFER）",
           v_new_sub == v_old_sub, "新是旧子串=%s 旧是新子串=%s"
           % (v_new_sub, v_old_sub))
    _check("S7.2 该方向对 verdict 为 DEFER（内容确有增减 => 需裁决）",
           v_new_sub == "DEFER", str(v_new_sub))


def s8():
    print("\n[S8] 既有分歧读数不变（p11 G2/G3 标定值）")
    h = ("# 功能名：网关心跳端口与重连参数\n"
         "# 子功能：端口取值与退避次数\n"
         "# 生效条件：网关在线且心跳已启用\n")
    body = ("服务端心跳端口：9090。客户端使用长连接轮询，超时时间为 30 秒。\n"
            "故障处置：连接断开后由客户端指数退避重连，最多重试 5 次。")
    g = _fresh()
    g.add("h8_old", h + "\n" + body + "\n", layer="knowledge",
          verification_basis="test", importance=0.5)

    def _c(content):
        r = g.check_consistency(content, layer="knowledge", depth=0)
        d = [c for c in r["conflicts"]
             if c.get("type") == "same_condition_divergence"]
        return r, d, (d[0]["conclusion_overlap"] if d else None)

    r, d, c = _c(h + "\n"
                 "服务端心跳端口：8080。客户端使用长连接轮询，超时时间为 60 秒。\n"
                 "故障处置：连接断开后由客户端指数退避重连，最多重试 9 次。\n")
    _check("S8.1 * 同槽不同值仍判分歧且读数 0.6928 不变（p11 G2 标定）",
           bool(d) and r["verdict"] == "DEFER" and round(c, 4) == 0.6928,
           "%s/%s" % (r["verdict"], c))
    r, d, c = _c(h + "\n"
                 "心跳所用服务端端口为 9090；客户端以长连接方式轮询，"
                 "超时设定 30 秒。\n"
                 "断开后的处理：客户端按指数退避重新连接，尝试上限 5 次。\n")
    _check("S8.2 * 同值异措辞仍判分歧且读数 0.3385 不变（p11 G3 标定）",
           bool(d) and r["verdict"] == "DEFER" and round(c, 4) == 0.3385,
           "%s/%s" % (r["verdict"], c))
    r, d, _c2 = _c(h + "\n" + body + "\n")
    _check("S8.3 逐字重复仍 ACCEPT（h8 原样）",
           not d and r["verdict"] == "ACCEPT" and r["conflict_strength"] == 0.0,
           "%s/%s" % (r["verdict"], r["conflict_strength"]))
    r, d, _c3 = _c(h + "\n" + body.replace("\n", "\n\n") + "\n")
    _check("S8.4 纯空白差异仍 ACCEPT（h8 插空行）",
           not d and r["verdict"] == "ACCEPT", str(r["verdict"]))


def s9():
    print("\n[S9] 判定面不变")
    _check("S9.1 阈值仍为标定值 0.95（防「为了让守卫变绿而调参」）",
           consistency.CONCLUSION_SAME == 0.95,
           str(consistency.CONCLUSION_SAME))
    cg = _fresh()
    cg.add("old", _ccg("缓存开关", "不启用缓存"), layer="knowledge",
           consistency=True)
    cg.add("new", _ccg("缓存开关", "启用缓存"), layer="knowledge",
           consistency=True)
    _check("S9.2 * DEFER 只提示不拦截：两条都落盘",
           bool(cg.get("old")) and bool(cg.get("new")), "")


def _before_source():
    """取修复前的 consistency.py 源码文本。

    优先 git log -S 定位引入提交的父版本；未提交时回落 HEAD。
    返回 (源码, 说明)；取不到返回 (None, 原因)。
    """
    try:
        log = subprocess.run(["git", "log", "-S", _MARK, "--format=%H", "--", _REL],
                             cwd=_REPO, capture_output=True, text=True, timeout=60)
        if log.returncode != 0:
            return None, "git log 失败：%s" % (log.stderr or "").strip()[:120]
        shas = [x.strip() for x in log.stdout.split() if x.strip()]
        if shas:
            rev = shas[-1] + "^"
            how = "引入提交 %s 的父版本" % shas[-1][:8]
        else:
            rev, how = "HEAD", "HEAD（本改动尚未提交）"
        got = subprocess.run(["git", "show", "%s:%s" % (rev, _REL)],
                             cwd=_REPO, capture_output=True, text=True, timeout=60)
        if got.returncode != 0:
            return None, "git show %s 失败：%s" % (
                rev, (got.stderr or "").strip()[:120])
        return got.stdout, how
    except Exception as e:            # noqa: BLE001
        return None, "异常：%s" % e


def _run_in_isolated_tree(before_src, tmp):
    """把仓库的 md_cg 复制到临时树，consistency.py 换成修复前版本后真跑。

    隔离跑是为了**不触碰本工作树**（历史上守 vi 曾在原地改源码）。
    返回 (verdict, 分歧列表, err)。
    """
    dst = os.path.join(tmp, "repo")
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(os.path.join(_REPO, "md_cg"), os.path.join(dst, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    io.open(os.path.join(dst, _REL), "w", encoding="utf-8",
            newline="\n").write(before_src)
    probe = os.path.join(tmp, "probe.py")
    lines = [
        "import json, os, sys, tempfile",
        "sys.path.insert(0, %r)" % dst,
        "from md_cg.mdcos import MdCGOS",
        "root = tempfile.mkdtemp(prefix='i189_br_')",
        "cg = MdCGOS(root)",
        "def ccg(exe):",
        "    return ('# 功能名：缓存开关\\n# 生效条件：生产环境\\n'",
        "            '# 子功能：服务参数\\n# 执行：' + exe + '\\n'",
        "            '# 验证方式：test\\n# 不适用条件：无\\n')",
        "cg.add('old', ccg('不启用缓存'), layer='knowledge',",
        "       verification_basis='test', importance=0.5)",
        "r = cg.check_consistency(ccg('启用缓存'), layer='knowledge', depth=0) or {}",
        "print(json.dumps({'verdict': r.get('verdict'),",
        "                  'div': [x for x in (r.get('conflicts') or [])",
        "                          if x.get('type') =="
        " 'same_condition_divergence']}, ensure_ascii=False))",
    ]
    io.open(probe, "w", encoding="utf-8", newline="\n").write(
        "\n".join(lines) + "\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MDCG_", "PYTHON"))}
    env["PYTHONPATH"] = dst
    env["PYTHONUTF8"] = "1"
    env["MDCG_ROOT"] = tempfile.mkdtemp(prefix="i189_brroot_")
    env["MDCG_SUSTAIN"] = "0"
    env["MDCG_SLEEP"] = "0"
    env["HOME"] = tempfile.mkdtemp(prefix="i189_brhome_")
    run = subprocess.run([sys.executable, "-X", "utf8", probe],
                         cwd=tmp, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=600)
    obj = {}
    for ln in reversed((run.stdout or "").strip().splitlines()):
        try:
            obj = json.loads(ln)
            break
        except Exception:            # noqa: BLE001
            continue
    if not obj:
        return None, None, (run.stdout or "")[-200:] + (run.stderr or "")[-400:]
    return obj.get("verdict"), obj.get("div"), None


def s10():
    print("\n[S10] 修复前原形（取不到修复前源则本次判别力无法自证）")
    src, how = _before_source()
    if src is None:
        _check("S10a 修复前源不可得（%s）" % how, False, "判别力无法自证")
        _check("S10b 修复前源不可得 => 修复前无反向比对", False, "同上")
        _check("S10c 修复前源不可得 => 修复前判 ACCEPT", False, "同上")
        return
    print("  （修复前源取自 %s）" % how)
    _check("S10a 修复前的 consistency.py 无反向比对（无本件标记）",
           _MARK not in src, "修复前源里已含本件标记")
    _check("S10b * 修复前正向达标后直接进分歧分支（无 min 取小）",
           "concl = min(concl, _cov(" not in src, "修复前源里已有取小")
    tmp = tempfile.mkdtemp(prefix="i189_before_")
    try:
        v, div, err = _run_in_isolated_tree(src, tmp)
        _check("S10c * 修复前同夹具判 ACCEPT（无同条件分歧）——判别力在此",
               v == "ACCEPT" and not div,
               "修复前读数 verdict=%s div=%d err=%s"
               % (v, len(div or []), err))
    except Exception as e:            # noqa: BLE001
        _check("S10c * 修复前同夹具判 ACCEPT（无同条件分歧）", False,
               "隔离跑修复前源码失败：%s" % e)


_GROUPS = (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4), ("S5", s5),
           ("S6", s6), ("S7", s7), ("S8", s8), ("S9", s9), ("S10", s10))


def main():
    global _OK, _BAD
    _OK, _BAD = 0, []
    for gid, fn in _GROUPS:
        try:
            fn()
        except Exception:            # noqa: BLE001
            import traceback
            _BAD.append("%s 组内异常" % gid)
            print("  FAIL %s 组内异常：%s" % (gid, traceback.format_exc()[-600:]))
    n = len(_BAD)
    print("\n结论比对方向性守卫（issue #189）：通过 %d / 失败 %d" % (_OK, n))
    if _BAD:
        print("失败项：" + "、".join(_BAD))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 撤掉反向比对", "md_cg/consistency.py",
     "                    if concl >= CONCLUSION_SAME:",
     "                    if False:",
     "S2.1"),
    ("V2 反向写成正向（方向颠倒）", "md_cg/consistency.py",
     "                        concl = min(concl, _cov(\n"
     "                            expand_query_terms_weighted(_norm_ws(e_body)),\n"
     "                            _norm_ws(n_concl)))",
     "                        concl = min(concl, _cov(\n"
     "                            tw_content, _norm_ws(e_body)))",
     "S2.1"),
    ("V3 min 写成 max（取小失效）", "md_cg/consistency.py",
     "                    concl = min(concl, _cov(",
     "                    concl = max(concl, _cov(",
     "S2.1"),
    ("V4 去掉「正向达标才算反向」守卫（无条件反向）", "md_cg/consistency.py",
     "                    if concl >= CONCLUSION_SAME:",
     "                    if True:",
     "S1.1"),
    ("V5 反向取小移出 else 支（还原参考补丁形态）", "md_cg/consistency.py",
     "                    if concl >= CONCLUSION_SAME:\n"
     "                        concl = min(concl, _cov(\n"
     "                            expand_query_terms_weighted(_norm_ws(e_body)),\n"
     "                            _norm_ws(n_concl)))",
     "                if concl >= CONCLUSION_SAME:\n"
     "                    concl = min(concl, _cov(\n"
     "                        expand_query_terms_weighted(_norm_ws(e_body)),\n"
     "                        _norm_ws(n_concl)))",
     "S1.5"),
)


def _mutate():
    bad = []
    prist = {}
    for _n, rel, _a, _r, _w in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            prist[rel] = f.read()
        if _MARK not in prist[rel]:
            print("  SOURCE-ALREADY-MUTATED：%s 里找不到本件标记" % rel)
            return 1
    for name, rel, anchor, repl, want in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        orig = prist[rel]
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        if orig.count(a_) != 1:
            print("  ANCHOR-AMBIGUOUS %s（命中 %d 处，须唯一定位）"
                  % (name, orig.count(a_)))
            bad.append(name)
            continue
        try:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", "-m",
                 "md_cg.test_issue189_conclusion_direction"],
                cwd=_REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900)
            out = (r.stdout or "") + (r.stderr or "")
            reds = [ln.strip() for ln in out.splitlines()
                    if ln.strip().startswith("FAIL")]
            hit = any(want in ln for ln in reds)
            print("  %-4s %-52s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                print("       rc=%d 尾部=%s" % (r.returncode, out[-400:]))
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != orig:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    sys.exit(_mutate() if "--mutate" in sys.argv else main())
