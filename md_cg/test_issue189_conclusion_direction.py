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


def _git(*args):
    return subprocess.run(["git"] + list(args), cwd=_REPO, capture_output=True,
                          text=True, timeout=60)

def _is_before(src):
    """修复前源 = **不含本件标记**的版本。"""
    return src is not None and _MARK not in src

# ---- issue #189 判别力夹具：修复前源**内嵌**（不依赖 git 历史可达性）----
# PR #311 CI（2026-10-14）：actions/checkout@v4 默认 depth=1，HEAD 是 pull/<n>/merge
# 中间提交 ⇒ git show <sha>^:path 直接 fatal。历史锚在 CI 上不可达属**仓库级既有
# 属性**（#190/#245/#258/#265/#277/#294/#295/#297 同样红），但本件判别力不能因此
# 无法自证 ⇒ 把修复前源按 blob 3a6fea35974b0cc623ccdc49fa92463d1156f708 内嵌，
# S10a/S10b 断言内嵌源；S10c 用内嵌源在隔离树真跑（无 git 依赖，CI 上必绿）。
import base64 as _b64
_BEFORE_B64 = (
    "IyAtKi0gY29kaW5nOiB1dGYtOCAtKi0KIiIibWRfY2cgwrcg6IqC54K56Ze06Ieq5Yqo5Yay56qB5qOA5rWL77yI5LiJ57qn"
    "5Yaz562W77ya5oOF57uqIOKGkiDlj43mgJ0g4oaSIOmAkuW9kuWPjeaAne+8iQoK55CG6K665Ye65aSE77yI5pys5LuT5Y6f"
    "5paH77yM6Z2e5aSW6YOo55+l6K+G77yJ77yaCgogIMK3ICoq5oOF57uqID0g5L+h5oGv5beu55qE5LqM6Zi25Y+Y5YyWIGTC"
    "skQvZHTCsioq77yIYGRvY3MvdGhlb3J5L+aZuuiDveeahOWFrOeQhuWMluWfuuefsy5tZGAgwqfljYHkuIDvvIw6NDEyLTUx"
    "MO+8iQogICAg5bel56iL56uv5a+55bqUIGBlbW90aW9uYWxfYmlhc2DvvIhhcHByb2FjaGluZyAvIGF2b2lkaW5nIC8gc3Rh"
    "Ymxl77yJ77yM5bm25LiU5Y6f5paH5piO56Gu77yaCiAgICDjgIzmg4Xnu6rpgJrpgZMqKueLrOeri+OAgeS4jeWPguS4juS/"
    "oeS7u+iuoeeulyoq44CN44CC5pWF5pys5qih5Z2XIEwwIOWPquWBmioq5rWB56iL6LCD5bqmKirvvIwKICAgIOe7neS4jeaU"
    "ueWKqCBjb25maWRlbmNlIC8g6LWE5qC85Yik5a6a4oCU4oCU6YG/5YWN5oqK5oOF57uq5re36L+b5LqL5a6e5Yik5pat44CC"
    "CgogIMK3ICoq5Y+N6aKYID0g6aKE5rWL5LiO5LqL5a6e5Yay56qBKirvvIjlkIzmlofmoaMgOjUyOe+8jOadoeS7tuiuuuS4"
    "g+aTjeS9nOS5i+S4gO+8iQogICAg4oCU4oCUIEwxIOS4gOasoeWGsueqgeajgOa1i+eahOeQhuiuuuWQje+8muaWsOS/oeaB"
    "r+S4juaXouacieadoeS7tueahOOAjOWPjemimOOAjeWFs+ezu+OAggoKICDCtyAqKumAkuW9kuW/hemhu+WPl+e6puadnyoq"
    "77yI5ZCM5paH5qGjIDoyNzPvvInvvJoKICAgIOOAjOmAkuW9kuW/hemhu+WPl+WIsOa3seW6puOAgeafpeivouasoeaVsOOA"
    "geiKgueCueaVsOOAgeW+queOr+ajgOa1i+WSjOS/oeaBr+WinuebiumXqOanm+e6puadn+OAggogICAgIOiLpemAkuW9kuay"
    "oeacieWHj+WwkeWAmemAieepuumXtO+8jOWwseS4jeW6lOe7p+e7reaQnOe0ouOAguOAjQogICAg4oCU4oCUIEwyIOmAkuW9"
    "kuWPjeaAneeahOehrOe6puadn++8iOacrOaooeWdl+aMieatpOWunueOsO+8jOiAjOmdnuaXoOmZkOWxleW8gO+8ieOAggoK"
    "ICDCtyAqKuWbm+aAgei3r+eUsSoqIEFDQ0VQVCAvIFJFSkVDVCAvIERFRkVSIC8gQkxJTkRTUE9U77yI5ZCM5paH5qGjIDo3"
    "MjHvvJsKICAgIGBtZF9jZy9tZGNnLnB5YCDlm5vmgIHlrprkuYnvvInigJTigJQgTDEg55qE6L6T5Ye66K+t5LmJ44CCCgog"
    "IMK3ICoq55+l6K+G6aOe6L2u77ya6K+v5beuIOKGkiDooaXmnaHku7Yg4oaSIOe7k+aehOabtOaWsCoq77yI5ZCM5paH5qGj"
    "IDo3MjXvvJtgbWRjZy5weToxMDAxYAogICAgYGZseXdoZWVsX3N0ZXBg77yJ4oCU4oCUIOWGsueqgSoq6Ieq5YqoKirokL0g"
    "dW5yZXNvbHZlZO+8jOivr+W3ruaYr+e7k+aehOabtOaWsOeahOi+k+WFpeOAggoKICDCtyAqKue6quW+i+Wbm+imgee0oOWQ"
    "jOaehCoq77yIYGRvY3Mv5bel5L2c57qq5b6LX+iupOefpeWbvuadoeebrl92MS4xLmpzb25g77ybCiAgICBgY29uc29saWRh"
    "dGUucHlgIENDRyDlm5vopoHntKDvvInigJTigJQg44CM5LiN6IO96L+d5Y+N57qq5b6L44CNPSDmlrDlhoXlrrnkuI3lvpfl"
    "kb3kuK3nuqrlvovoioLngrnnmoQKICAgIGBuZWdhdGl2ZS5yZWplY3Rg77yI5LiN6YCC55So5p2h5Lu277yJ44CC57qq5b6L"
    "6IqC54K555SoIHRhZy/liY3nvIDor4bliKvvvIzkuI3noaznvJbnoIHlhbfkvZPmnaHnm67jgIIKCuS4iee6p+WGs+etlu+8"
    "iOmhuuW6j+WNs+ivreS5ie+8jOi2iumdoOWJjei2iuW7ieS7t++8ie+8mgoKICAgIEwwIOaDhee7qiAgICDvvJrkuozpmLbk"
    "v6Hlj7fvvIzlv6vpgJ/mlrnlkJHosIPmlbTvvIhhcHByb2FjaGluZyAvIHN0YWJsZSAvIGF2b2lkaW5n77yJ4oCU4oCU5LiN"
    "6KOB5Yaz6LWE5qC8CiAgICBMMSDlj43mgJ0gICAg77ya5LiA5qyh5p2h5Lu257qn5Yay56qB5qOA5rWL77yI6Ieq5ZCm5a6a"
    "IC8g57qq5b6L6L+d5Y+NIC8g5p2h5Lu25LqS5pal77yJ4oaSIOWbm+aAgQogICAgTDIg6YCS5b2S5Y+N5oCd77yaTDEg5pyq"
    "5YazIOKGkiDmsr/lhbPns7vpk77pgJLlvZLmib7jgIzljLrliIbmnaHku7bjgI3vvJvlj5fmt7HluqYv6IqC54K55pWwL+W+"
    "queOry/lop7nm4rpl6jmp5vnuqbmnZ8KCuWGsueqgeiHquWKqOinpuWPkemjnui9ru+8mnZlcmRpY3QgPT0gUkVKRUNU77yI"
    "KirnnJ/lhrLnqoEqKu+8ieS4lCBhdXRvX2ZseXdoZWVsIOKGkgogICAgYGNnLmZseXdoZWVsX3N0ZXAoe3F1ZXJ5LCBleHBl"
    "Y3RlZF9zdGF0ZToiQUNDRVBUIiwgYWN0dWFsX3N0YXRlOnZlcmRpY3QsIG1pc3Npbmd9KWAKICAgIO+8iEgxMeKRpSAyMDI2"
    "LTA5LTMw77yaREVGRVIvQkxJTkRTUE9UIOS4jeWGjeiHquWKqOW7uuWNleKAlOKAlERFRkVSIOaYr+OAjOW+heehruiupOOA"
    "jeOAgQogICAgQkxJTkRTUE9UIOaYr+OAjOajgOa1i+WJjeaPkOS4jeWtmOWcqO+8iOaXoOWPr+avlOWvueiKgueCue+8jOep"
    "uuW6k+S4iuaBkuaIkOeri++8ieOAje+8jOS6jOiAhemDveS4jeaYrwogICAg5bey5Yik5a6a55qE5Yay56qB77yb5oqK5b6F"
    "56Gu6K6k5YaZ5oiQ5b6F5Yqe5bel5Y2V5Y+q5piv5oqK6K+v5Yik5Zu65YyW44CC5Yik5a6a5pys6Lqr5LuN5aaC5a6e6L+U"
    "5Zue44CC77yJCgrnlZnnl5UgYF9jb25zaXN0ZW5jeS5qc29ubGDvvIhhcHBlbmQtb25see+8ie+8muavj+adoeWIpOWumuWP"
    "r+WuoeiuoeOAjOS4uuS7gOS5iOWGsueqgSAvIOS4uuS7gOS5iOaUvuihjOOAjeOAggoK6K+a5a6e6L6555WM77ya5pys5qih"
    "5Z2X5pivKirmnaHku7bnuqfvvIjnu5PmnoTljJbvvIkqKuWGsueqgeajgOa1i++8jOS4jeaYr+ivreS5ieiVtOWQq+ivgeaY"
    "juOAguWug+WIpOaWreeahOaYrwrjgIzlo7DmmI7nmoTpgILnlKgv5LiN6YCC55So5p2h5Lu25piv5ZCm5LqS55u46KaG55uW"
    "44CN77yM6ICM6Z2e44CM5Lik5Y+l6K+d5Zyo6YC76L6R5LiK5piv5ZCm55+b55u+44CN44CCCuaXoOazleW7uueri+WPr+av"
    "lOWvuei3r+W+hOaXtui/lOWbniBCTElORFNQT1TvvIzkuI3lgYfoo4Xnoa7lrprjgIIKIiIiCmZyb20gX19mdXR1cmVfXyBp"
    "bXBvcnQgYW5ub3RhdGlvbnMKCmltcG9ydCBqc29uCmltcG9ydCBvcwppbXBvcnQgdGltZQoKZnJvbSAubWRjZyBpbXBvcnQg"
    "ZXhwYW5kX3F1ZXJ5X3Rlcm1zX3dlaWdodGVkCmZyb20gLiBpbXBvcnQgbm9kZWZpbGUKZnJvbSAuZnN1dGlsIGltcG9ydCBl"
    "bmRzX21pZF9saW5lCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tCiMg5bi46YeP77yI5YWo6YOo5Y+v5a6h6K6h44CB5Y+v6LCD77yJCiMgLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KCkxPR19GSUxF"
    "ID0gIl9jb25zaXN0ZW5jeS5qc29ubCIKCiMgLS0tLSBpc3N1ZSAjMjk477yIMjAyNi0xMC0xNCBEU0gg56uv77yJ77ya5Y+w"
    "6LSm55qE5a+G57qn6Z2iIC0tLS0KIwojIOeXheeBtu+8mmBfY29uc2lzdGVuY3kuanNvbmxgIOaYryoq5piO5paHKiogYXBw"
    "ZW5kLW9ubHkg5Y+w6LSm77yM6ICMIGBjaGVjaygpYCDlrozlhajkuI3nn6XpgZMKIyDlhpnlhaXnmoTlr4bnuqfjgILkuIDm"
    "naHlo7DmmI4gYHNlbnNpdGl2aXR5PXByaXZhdGVgIOeahOWGmeWFpe+8jOiKgueCueacrOS9k+WKoOWvhuiQveebmO+8jOWQ"
    "jOS4gOasoeWIpOWumgojIOeahCBgcG9zYC9gbmVnYO+8iOeUn+aViOadoeS7ti/kuI3pgILnlKjmnaHku7bljp/mlofvvInj"
    "gIFgY29uZmxpY3RzW10ucG9zX3NpZGVgL2BuZWdfc2lkZWDjgIEKIyBgc2xvdGDvvIjlip/og73lkI3liY0gNDAg5a2X77yJ"
    "44CBYGNvbmRfcm91dGVzLm9ubHlfbmV3X3NpZGVgL2Bvbmx5X2V4aXN0aW5nX3NpZGVgCiMg5Y2054Wn5qC35piO5paH6K6w"
    "5LiL77ybYGNvbnNpc3RlbmN5Lmhpc3RvcnlgIOWPquimgeaxgiB3cml0ZSDmnYPpmZDjgIHkuI3ov4flj6/op4HmgKfov4fm"
    "u6TvvIwKIyDkuo7mmK8gY2xlYXJhbmNlIOS7hSBpbnRlcm5hbCDnmoQgcmVjb3JkL3N1c3RhaW4vdmVyaWZ5L3JlZmxlY3Qv"
    "b3JjaGVzdHIg5Luk54mMCiMg6IO95Y6f5qC36K+75Yiw5ZCM5LiA5om56IqC54K5IGBnZXRgIOWIpCBgbm90X2ZvdW5kYCDn"
    "moTmnaHku7bljp/mlofjgIIKIwojIOS/ruazle+8mioq6JC955uY5Ymv5pysKirljrvljp/mlofvvIhgY2hlY2soKWAg6L+U"
    "5Zue57uZ6LCD55So5pa555qE5Zue5omn5LiA5a2X5LiN5Yqo77yJ44CC5a+G57qn5Y+WCiMg44CM6LCD55So5pa55aOw5piO"
    "5YC844CN5LiO44CM5pys5qyh5q+U5a+555qE5pei5pyJ6IqC54K55ZCE6Ieq5a+G57qn44CN55qE5pyA6auY5qGj4oCU4oCU"
    "YG9ubHlfZXhpc3Rpbmdfc2lkZWAKIyDorrDnmoTmraPmmK/ooqvmr5Tlr7noioLngrnnmoTmnaHku7bvvIzmlYXml6LmnIno"
    "ioLngrnkvqflv4XpobvkuIDotbfov5vlr4bnuqfpnaLjgIIKIwojIOW6j+S4jiBgc2VjdXJpdHkuU0VOU0lUSVZJVFlfT1JE"
    "RVJgIOmAkOS9jeWQjOW6j++8iOatpOWkhOWkjeWItuiAjOmdniBpbXBvcnTvvJrmnKzmqKHlnZfooqsKIyBgbWRjb3NgL2Bz"
    "ZWN1cml0eWAg5LiL5ri45aSn6YeP5byV55So77yM5Y+N5ZCRIGltcG9ydCDkvJrmiJDnjq/vvInjgIIKX0xFREdFUl9MRVZF"
    "TFMgPSAoInB1YmxpYyIsICJpbnRlcm5hbCIsICJyZXN0cmljdGVkIiwgInByaXZhdGUiLCAic2VjcmV0IikKCiMg5Y+w6LSm"
    "6YeM5om/6L2944CM5p2h5Lu25Y6f5paHIC8g5Yqf6IO95ZCN5qe944CN55qE5a2X5q614oCU4oCU6auY5LqOIGludGVybmFs"
    "IOaXtuS4gOW+i+WOu+WOn+aWh+OAggpfTEVER0VSX1RFWFRfRklFTERTID0gKCJwb3MiLCAibmVnIikKX0xFREdFUl9DT05G"
    "TElDVF9GSUVMRFMgPSAoInBvc19zaWRlIiwgIm5lZ19zaWRlIiwgInNsb3QiKQpfTEVER0VSX1JPVVRFX0ZJRUxEUyA9ICgi"
    "b25seV9uZXdfc2lkZSIsICJvbmx5X2V4aXN0aW5nX3NpZGUiKQoKCiMg55Sf5pWI5p2h5Lu277ya5b2i5Y+CIGxldmVsIOS4"
    "uiBfTEVER0VSX0xFVkVMUyDkuK3nmoTlhYPntKDml7bov5Tlm57lhbbkuIvmoIfvvJvlgYflgLzov5Tlm54gTm9uZe+8iOin"
    "huS4uuacquWjsOaYju+8ie+8m+mdnuazleWAvOi/lOWbniBsZW4oX0xFREdFUl9MRVZFTFMp77yIPeacgOmrmOaho++8jGZh"
    "aWwtY2xvc2Vk77yJ44CCCmRlZiBfbGV2ZWxfcmFuayhsZXZlbCk6CiAgICAiIiLlr4bnuqfluo/vvIjkuI4gc2VjdXJpdHku"
    "U0VOU0lUSVZJVFlfT1JERVIg5ZCM5bqP77yJ77yb5YGH5YC8IE5vbmXjgIHpnZ7ms5XlgLwgZmFpbC1jbG9zZWQg5pyA6auY"
    "5qGj44CCIiIiCiAgICBzID0gc3RyKGxldmVsIG9yICIiKS5zdHJpcCgpLmxvd2VyKCkKICAgIGlmIG5vdCBzOgogICAgICAg"
    "IHJldHVybiBOb25lCiAgICByZXR1cm4gKF9MRURHRVJfTEVWRUxTLmluZGV4KHMpIGlmIHMgaW4gX0xFREdFUl9MRVZFTFMK"
    "ICAgICAgICAgICAgZWxzZSBsZW4oX0xFREdFUl9MRVZFTFMpKQoKCiMg55Sf5pWI5p2h5Lu277yaZGVjbGFyZWQg5Li66LCD"
    "55So5pa55aOw5piO5a+G57qn44CBbGV2ZWxzIOS4uuacrOasoeavlOWvueWIsOeahOaXouacieiKgueCueWvhue6p+W6j+WI"
    "l++8m+WPluS4pOiAheacgOmrmOaho++8jOWFqOS4uuWBh+WAvOaXtuWbnuiQvSBpbnRlcm5hbOOAggpkZWYgbGVkZ2VyX2xl"
    "dmVsKGRlY2xhcmVkLCBsZXZlbHM9Tm9uZSk6CiAgICAiIiLmnKzmrKHliKTlrprnmoQqKuiQvei0puWvhue6pyoq77yd5aOw"
    "5piO5YC85LiO5ZCE6KKr5q+U5a+55pei5pyJ6IqC54K55a+G57qn5Lit55qE5pyA6auY5qGj44CCCgogICAg5pyq5aOw5piO"
    "77yITm9uZS/nqbrkuLLvvInmjIkgaW50ZXJuYWzvvIjkuI4gIzg3IOe8uuecgeaho+S4gOiHtO+8jOmbtuWPmOWMlu+8ie+8"
    "mwogICAg6Z2e5rOV5YC8IGZhaWwtY2xvc2VkIOaMieacgOmrmOahoyBzZWNyZXTvvIjlroHlj6/lpJrmirnvvIzkuI3lj6/o"
    "tormnYPvvInjgIIKICAgICIiIgogICAgYmVzdCA9ICJpbnRlcm5hbCIKICAgIGJlc3RfciA9IF9MRURHRVJfTEVWRUxTLmlu"
    "ZGV4KGJlc3QpCiAgICBmb3IgeCBpbiBbZGVjbGFyZWRdICsgbGlzdChsZXZlbHMgb3IgW10pOgogICAgICAgIHIgPSBfbGV2"
    "ZWxfcmFuayh4KQogICAgICAgIGlmIHIgaXMgTm9uZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiByID4gYmVz"
    "dF9yOgogICAgICAgICAgICBiZXN0X3IsIGJlc3QgPSByLCBfTEVER0VSX0xFVkVMU1ttaW4ociwgbGVuKF9MRURHRVJfTEVW"
    "RUxTKSAtIDEpXQogICAgcmV0dXJuIGJlc3QKCgojIOeUn+aViOadoeS7tu+8mnJlYyDkuLrliKTlrprnlZnnl5XlrZflhbjm"
    "l7bov5Tlm54qKuWOu+WOn+aWh+WJr+acrCoq77yI5Y6fIHJlYyDkuI3ooqvkv67mlLnvvInvvJtyZWMg6Z2e5a2X5YW45pe2"
    "5Y6f5qC36L+U5Zue44CCCmRlZiBzY3J1Yl9yZWNvcmQocmVjKToKICAgICIiIuWOu+WOn+aWh+WJr+acrO+8muadoeS7tuWO"
    "n+aWh+S4juWKn+iDveWQjeanvee9ruepuu+8jOWIpOaNruaVsOWAvCAvIHZlcmRpY3QgLyDoioLngrkgaWQg54Wn5bi45L+d"
    "55WZ44CCCgogICAg5Y+q5Yqo5Ymv5pys4oCU4oCUYGNoZWNrKClgIOi/lOWbnue7meiwg+eUqOaWueeahOWbnuaJp+S4jeWP"
    "l+W9seWTje+8iOWkjeaguOmdoumcgOimgeWOn+aWh++8jAogICAg6JC955uY6Z2i5LiN6ZyA6KaB77yJ44CC6IqC54K5IGlk"
    "IOS/neeVmeaYr+WIu+aEj+eahO+8muWPsOi0pueahOWPr+WuoeiuoeaAp++8iOWTquS4pOS4quiKgueCueWGsueqge+8iQog"
    "ICAg5LiN5L6d6LWW5p2h5Lu25Y6f5paH77yM6ICMIGlkIOacrOi6q+W3suWPlyBgZ2V0YC9gc2VhcmNoYCDnmoTlr4bnuqfo"
    "v4fmu6Tkv53miqTjgIIKICAgICIiIgogICAgaWYgbm90IGlzaW5zdGFuY2UocmVjLCBkaWN0KToKICAgICAgICByZXR1cm4g"
    "cmVjCiAgICBvdXQgPSBkaWN0KHJlYykKICAgIGZvciBrIGluIF9MRURHRVJfVEVYVF9GSUVMRFM6CiAgICAgICAgaWYgayBp"
    "biBvdXQ6CiAgICAgICAgICAgIG91dFtrXSA9IFtdCiAgICBpZiBpc2luc3RhbmNlKG91dC5nZXQoImNvbmZsaWN0cyIpLCBs"
    "aXN0KToKICAgICAgICBjcyA9IFtdCiAgICAgICAgZm9yIGMgaW4gb3V0WyJjb25mbGljdHMiXToKICAgICAgICAgICAgaWYg"
    "bm90IGlzaW5zdGFuY2UoYywgZGljdCk6CiAgICAgICAgICAgICAgICBjcy5hcHBlbmQoYykKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgICAgIGMyID0gZGljdChjKQogICAgICAgICAgICBmb3IgayBpbiBfTEVER0VSX0NPTkZMSUNUX0ZJ"
    "RUxEUzoKICAgICAgICAgICAgICAgIGlmIGsgaW4gYzI6CiAgICAgICAgICAgICAgICAgICAgYzJba10gPSBbXSBpZiBpc2lu"
    "c3RhbmNlKGMyW2tdLCBsaXN0KSBlbHNlICIiCiAgICAgICAgICAgIGNyID0gYzIuZ2V0KCJjb25kX3JvdXRlcyIpCiAgICAg"
    "ICAgICAgIGlmIGlzaW5zdGFuY2UoY3IsIGRpY3QpOgogICAgICAgICAgICAgICAgY3IgPSBkaWN0KGNyKQogICAgICAgICAg"
    "ICAgICAgZm9yIGsgaW4gX0xFREdFUl9ST1VURV9GSUVMRFM6CiAgICAgICAgICAgICAgICAgICAgaWYgayBpbiBjcjoKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgY3Jba10gPSBbXQogICAgICAgICAgICAgICAgYzJbImNvbmRfcm91dGVzIl0gPSBjcgog"
    "ICAgICAgICAgICBjcy5hcHBlbmQoYzIpCiAgICAgICAgb3V0WyJjb25mbGljdHMiXSA9IGNzCiAgICByZXR1cm4gb3V0CgoK"
    "TUFYX1NDQU4gPSAyMDAgICAgICAgIyDljZXmrKHmo4DmtYvmnIDlpJrmr5Tlr7nnmoTml6LmnInoioLngrnmlbDvvIjpmLIg"
    "TyhOKSDniIbngrjvvIkKICAgICAgICAgICAgICAgICAgICAgIyBjb25zMjAw77yIMjAyNi0xMC0wM++8ie+8muacrOWAvOaY"
    "ryoq55u45YWz6Z2iL+S/neW6lemdouWQhOiHqueahOmZkOminSoq77yM5LiN5pivCiAgICAgICAgICAgICAgICAgICAgICMg"
    "44CM57Si5byV5bqP5YmNIE7jgI3igJTigJTmlbDlgLzkuIDlrZfmnKrliqjvvIjlpZHnuqbnpoHmraLpnaLvvInvvJvotoXp"
    "mZDotbDlj6/op4LmtYsKICAgICAgICAgICAgICAgICAgICAgIyDvvIh0cnVuY2F0ZWQva2VwdC9oaW5077yJ77yM5L+u5rOV"
    "5piv6YCJ6Z2i5LiO6aKE562b77yM5LiN5piv6LCD5aSn5pys5YC844CCCk1BWF9ERVBUSCA9IDMgICAgICAgICMgTDIg6YCS"
    "5b2S5rex5bqm5LiK6ZmQ77yI5a+56b2QIDoyNzPvvIkKTUFYX05PREVTID0gNjAgICAgICAgIyBMMiDpgJLlvZLlsZXlvIDo"
    "ioLngrnkuIrpmZDvvIjlr7npvZAgOjI3M++8iQpNSU5fR0FJTiA9IDAuMTUgICAgICAjIOS/oeaBr+WinuebiumXqOanm++8"
    "muWAmemAieepuumXtOWHj+WwkeavlOS+i+S9juS6juatpOWAvOWNs+WBnO+8iOWvuem9kCA6Mjcz77yJCgojIOaIquaWreWP"
    "r+aTjeS9nOaPkOekuu+8iGNvbnMyMDDvvJrkuI4gc3RnIGBfQ0FQX0hJTlRgIOWQjOWPo+W+hOeyvuelnuKAlOKAlOemgeat"
    "oumdmem7mO+8ieKAlOKAlOaWh+ahiOW/hemhuwojIOWQq+OAjOe7huWMlueUn+aViOadoeS7ti/kuI3pgILnlKjmnaHku7bj"
    "gI3kuI7jgIzlu7rnq4vmnaHku7bntKLlvJXjgI3or63kuYnvvJvmlbDlgLzmlL7lpKfvvIjosIMgbGltaXQvTUFYX1NDQU7v"
    "vIkKIyDkuI3mmK/kv67ms5XvvIzmlYXmmI7mloflip3pmLvjgIIKX1NDQU5fSElOVCA9ICgi5YCZ6YCJICVzIOadoei2hei/"
    "h+WNleasoeajgOa1i+mZkOminSBsaW1pdD0lc++8jOW3suaMieebuOWFs+aAp+S/neeVmSAlcyDmnaEiCiAgICAgICAgICAg"
    "ICAgIu+8iOaIquaWreS4jemdmem7mO+8ie+8muivt+e7huWMlueUn+aViOadoeS7ti/kuI3pgILnlKjmnaHku7bmlLbnqoTl"
    "gJnpgInpm4bvvIwiCiAgICAgICAgICAgICAgIuaIluaMieiuvuiuoeeov+W7uueri+adoeS7tue0ouW8le+8iGRvY3MvcGxh"
    "bnMvc3Rn5p2h5Lu25YyW5LiO57uT5p6E57Si5byVX+iuvuiuoV92MC4xLm1k77yJIgogICAgICAgICAgICAgICLigJTigJTk"
    "uI3opoHosIPlpKcgbGltaXQvTUFYX1NDQU4g5pWw5YC844CCIikKCkNMQVNIX0hJR0ggPSAwLjYgICAgICMg5p2h5Lu25LqS"
    "55u46KaG55uW6ZiI5YC8IOKGkiDmmI7noa7kupLmlqUKQ0xBU0hfTE9XID0gMC4zNSAgICAgIyDmnaHku7bpg6jliIbopobn"
    "m5bpmIjlgLwg4oaSIOW+heWumgpTRUxGX05FR0FUSU9OID0gMC41ICAjIOiHquWQpuWumumYiOWAvO+8mui0n+adoeS7tuii"
    "q+iHqui6q+ato+aWh+W8uuWRveS4rQoKIyDigJTigJQg56ys5LqM57G75YWz57O777yI5ZCM5p2h5Lu256m66Ze0IMK3IOe7"
    "k+iuuuanveWPluWAvOWIhuatp++8iemYiOWAvO+8m+Wdh+eUseaOoumSiOWunua1i+agh+WumiDigJTigJQKIyBydW5fcHJv"
    "YmVfc2FtZWNvbmQucHkg5a6e5rWL77ya5ZCM5p2h5Lu2IHNhbWVfY29uZD0xLjAgLyDlvILmnaHku7bnqbrpl7QgMC4zMjgg"
    "4oaSIDAuNzUg5Y+v5YiGClNBTUVfQ09ORF9ISUdIID0gMC43NSAgICMg5ZCM5L6n5p2h5Lu26YeN5ZCIIOKGkiDliKTlrprj"
    "gIzlkIzkuIDmnaHku7bnqbrpl7TjgI0KIyDlrp7mtYvnu5Porrrmp73vvIjlrZDlip/og73vvInvvJrlkIzmp70gMS4wIC8g"
    "5ZCM5Li76K+t5byC5bGe5oCnIDAuMTQgLyDlvILkuLvpopggMC4wIOKGkiAwLjYg5Y+v5YiGClNMT1RfSElHSCA9IDAuNiAg"
    "ICAgICAgICMg57uT6K665qe977yI5Yqf6IO95ZCNL+WtkOWKn+iDve+8iemHjeWQiCDihpIg5Yik5a6a44CM5ZCM5LiA5Lu2"
    "5LqL44CNCiMg5a6e5rWL77ya6YCQ5a2X6YeN5aSNIDEuMCAvIOWQjOanveS4jeWQjOWAvCAwLjYxIC8g5ZCM5YC85byC5o6q"
    "6L6eIDAuNzQg4oaSIDAuOTUg5Y+q5o6S6Zmk6YCQ5a2X6YeN5aSNCiMgSDjvvIgyMDI2LTA5LTMw77yJ77ya5Lik5L6n5YWI"
    "6L+H5ZCM5LiA5aWX56m655m95b2S5LiA5YyW77yIYF9ub3JtX3dzYO+8ieWGjeavlO+8m+S4lOWOu+epuueZveWQjumAkOWt"
    "lwojIOebuOWQjOiAheebtOaOpeefrei3r+S4uuOAjOmHjeWkjeOAjeOAgumYiOWAvOacrOi6qyoq5LiN5YqoKirigJTigJTn"
    "uq/nqbrnmb3lt67lvILvvIjmjqLpkojlrp7mtYvmnKrlvZLkuIDljJbml7YKIyAwLjkxNDV+MC45NDM277yJ5pu+5oqK44CM"
    "5ZCM5p2h5Lu2wrflkIzmp73jgI3ljovliLAgMC45NSDku6XkuIvpgKDmiJDlgYflhrLnqoHvvIzkv67ms5XmmK/mtojpmaTl"
    "j6PlvoQKIyDkuI3lr7nnp7DvvIzkuI3mmK/mlL7lrr0gMC45Ne+8iOaUvuWuveWIsCAwLjk0MzYg5Lul5LiL5omN6IO95pWR"
    "77yM5Lya5LiA5bm25ZCe5o6J55yf5YiG5q2n77yJ44CCCkNPTkNMVVNJT05fU0FNRSA9IDAuOTUgICMg5q2j5paH5Yeg5LmO"
    "6YCQ5a2X55u45ZCMIOKGkiDlsZ7jgIzph43lpI3jgI3vvIjor6XlkIjlubbvvInvvIzkuI3nrpflhrLnqoEKCkVNT19BVk9J"
    "RCA9IDAuNzAgICAgICMg5Yay56qB5by65bqmIOKJpSDmraTlgLwg4oaSIGF2b2lkaW5nCkVNT19BUFBST0FDSCA9IDAuMzAg"
    "ICMg5Yay56qB5by65bqmIOKJpCDmraTlgLwg4oaSIGFwcHJvYWNoaW5nCgojIOe6quW+i+iKgueCueivhuWIq++8iHRhZyDm"
    "iJYgaWQg5YmN57yA77yb5LiN56Gs57yW56CB5YW35L2T57qq5b6L5p2h55uu77yJCkRJU0NJUExJTkVfVEFHUyA9ICgiZGlz"
    "Y2lwbGluZSIsICLnuqrlvosiLCAid29ya19kaXNjaXBsaW5lIiwgInJ1bGUiLCAi6KeE5YiZIiwgIuaIkuW+iyIpCgpWRVJE"
    "SUNUUyA9ICgiQUNDRVBUIiwgIlJFSkVDVCIsICJERUZFUiIsICJCTElORFNQT1QiKQoKIzog6Ieq5Yqo5bu65Y2V77yI6aOe"
    "6L2u77yJKirllK/kuIAqKueahOinpuWPkeaAgeKAlOKAlOWPquacieecn+WGsueqgeaJjeiQvSB1bnJlc29sdmVk77yISDEx"
    "4pGl77yMMjAyNi0wOS0zMO+8ieOAggojOiDmlLnliY3mmK8gKCJSRUpFQ1QiLCJERUZFUiIsIkJMSU5EU1BPVCIp77yaREVG"
    "RVI944CM5p2h5Lu25LqS5palL+mDqOWIhuimhuebluOAgeW+heehruiupOOAjeOAgQojOiBCTElORFNQT1Q944CM5peg6IqC"
    "54K55Y+v5q+U5a+577yI5qOA5rWL5YmN5o+Q5LiN5a2Y5Zyo77yJ44CN4oCU4oCU6YO95LiN5piv44CM5bey5Yik5a6a55qE"
    "5Yay56qB44CN44CCCiM6IOWNleeCue+8mmBjaGVjaygpYCDkuI4gYGNhdGFsb2coKWAg6YO96K+75pys5YWD57uE44CCCkZM"
    "WVdIRUVMX1RSSUdHRVJTID0gKCJSRUpFQ1QiLCkKCgojIOeUn+aViOadoeS7tu+8muS7pSB2ZXJkaWN0IOS4jiByZWFzb24g"
    "5p6E6YCg5byC5bi477yI5raI5oGvIGBbe3ZlcmRpY3R9XSB7cmVhc29ufWDvvInvvIxjb25mbGljdHMg5Lyg5YGH5YC877yI"
    "Tm9uZS/nqbrlrrnlmajnrYnvvIzmupDnoIEgYGNvbmZsaWN0cyBvciBbXWDvvInml7Ygc2VsZi5jb25mbGljdHMg5Li6IFtd"
    "77yM5Lyg55yf5YC85pe25Y6f5qC35L+d55WZ77ybCmNsYXNzIENvbnNpc3RlbmN5RXJyb3IoRXhjZXB0aW9uKToKICAgICIi"
    "IuehrOWGsueqge+8muWGmeWFpeiiq+aLku+8iOiHquWQpuWumiAvIOi/neWPjee6quW+i++8ieOAgiIiIgoKIyDnlJ/mlYjm"
    "naHku7bvvJp2ZXJkaWN0IOS4jiByZWFzb24g5b+F5Lyg5bm26LWL57uZ5ZCM5ZCN5bGe5oCn44CB5ou85oiQ5byC5bi45raI"
    "5oGvIGBbe3ZlcmRpY3R9XSB7cmVhc29ufWDvvJtjb25mbGljdHMg5Li65YGH5YC877yITm9uZS/nqbrlrrnlmajnrYnvvIzm"
    "upDnoIEgYGNvbmZsaWN0cyBvciBbXWDvvInml7Ygc2VsZi5jb25mbGljdHMg5Zue6JC95YiwIFtd77yM5Li655yf5YC85pe2"
    "5Y6f5qC35L+d55WZ77ybCiAgICBkZWYgX19pbml0X18oc2VsZiwgdmVyZGljdCwgcmVhc29uLCBjb25mbGljdHM9Tm9uZSk6"
    "CiAgICAgICAgc2VsZi52ZXJkaWN0ID0gdmVyZGljdAogICAgICAgIHNlbGYucmVhc29uID0gcmVhc29uCiAgICAgICAgc2Vs"
    "Zi5jb25mbGljdHMgPSBjb25mbGljdHMgb3IgW10KICAgICAgICBzdXBlcigpLl9faW5pdF9fKGYiW3t2ZXJkaWN0fV0ge3Jl"
    "YXNvbn0iKQoKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0KIyDljp/or63vvJrlu7bov5/lr7zlhaUgbWRjb3PvvIjpgb/lhY0gbWRjZyDihpAgbWRjb3Mg4oaQ"
    "IGNvbnNpc3RlbmN5IOeahOW+queOr+WvvOWFpe+8iQojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCgojIOeUn+aViOadoeS7tu+8muaXoCByZXF1aXJlZCDlvaLl"
    "j4LvvIzku7vkuIDosIPnlKjov5Tlm54gKCBfY2NnX2ZpZWxkLCBfZGVjbGFyZWRfY29uZGl0aW9ucywgX25lZ19oaXQsIF93"
    "ZWlnaHRlZF9jb3ZlcmFnZSApIOWbm+WFg+e7hO+8mwpkZWYgX3ByaW1zKCk6CiAgICAiIiLlj5YgbWRfY2cg5bey5pyJ55qE"
    "5p2h5Lu25Yy56YWN5Y6f6K+t77yI5p2h5Lu26K6644CM5Y+N6aKY44CN55qE5pei5pyJ5a6e546w77yJ44CCIiIiCiAgICBm"
    "cm9tIC5tZGNvcyBpbXBvcnQgKF9jY2dfZmllbGQsIF9kZWNsYXJlZF9jb25kaXRpb25zLCBfbmVnX2hpdCwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgX3dlaWdodGVkX2NvdmVyYWdlKQogICAgcmV0dXJuIF9jY2dfZmllbGQsIF9kZWNsYXJlZF9jb25k"
    "aXRpb25zLCBfbmVnX2hpdCwgX3dlaWdodGVkX2NvdmVyYWdlCgoKIyDnlJ/mlYjmnaHku7bvvJp4cyDkuLrlj6/ov63ku6Pl"
    "r7nosaHml7bvvIzpgJDpobkgc3RyKHgpLnN0cmlwKCkg5ZCO5LuF5b2T57uT5p6c6Z2e56m65LiU5pyq5Ye6546w6L+H5omN"
    "5Yqg5YWlIG91dCDlubbov5Tlm54gb3V077ybeHMg5Li6IE5vbmUvRmFsc2UvMCDml7blnKggZm9yIOWkhOi/reS7o+Wksei0"
    "pe+8iFR5cGVFcnJvcu+8ie+8mwpkZWYgX2RlZHVwKHhzKToKICAgIG91dCA9IFtdCiAgICBmb3IgeCBpbiB4czoKICAgICAg"
    "ICBzID0gc3RyKHgpLnN0cmlwKCkKICAgICAgICBpZiBzIGFuZCBzIG5vdCBpbiBvdXQ6CiAgICAgICAgICAgIG91dC5hcHBl"
    "bmQocykKICAgIHJldHVybiBvdXQKCgojIOeUn+aViOadoeS7tu+8mmZtIOe7meWHuuaXtu+8jOmBjeWOhiBmbS5nZXQoImVk"
    "Z2VzIinvvIjnvLrplK7miJblgYflgLzmjInnqbrliJfooajvvInkuK3lhYPntKDvvIxkaWN0IOWFg+e0oOaMiSB0b+KGknRh"
    "cmdldOKGkm5vZGXihpJpZCDlj5bpppbkuKrnnJ/lgLzjgIHpnZ4gZGljdCDlhYPntKDnm7TmjqXkvZzlgJnpgInvvIzlgJnp"
    "gInnnJ/lgLzml7Ygc3RyKHQpIOWKoOWFpSBvdXQg5bm26L+U5Zue77ybCmRlZiBfZWRnZV90YXJnZXRzKGZtKToKICAgICIi"
    "IuiKgueCueWjsOaYjueahOWHuui+ueebruagh++8iOWFvOWuuSBkaWN0IC8gc3RyIOS4pOenjeW9ouaAge+8ieOAgiIiIgog"
    "ICAgb3V0ID0gW10KICAgIGZvciBlIGluIChmbS5nZXQoImVkZ2VzIikgb3IgW10pOgogICAgICAgIGlmIGlzaW5zdGFuY2Uo"
    "ZSwgZGljdCk6CiAgICAgICAgICAgIHQgPSBlLmdldCgidG8iKSBvciBlLmdldCgidGFyZ2V0Iikgb3IgZS5nZXQoIm5vZGUi"
    "KSBvciBlLmdldCgiaWQiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHQgPSBlCiAgICAgICAgaWYgdDoKICAgICAgICAg"
    "ICAgb3V0LmFwcGVuZChzdHIodCkpCiAgICByZXR1cm4gb3V0CgoKIyDnlJ/mlYjmnaHku7bvvJpmbSDkuI4gbm9kZV9pZCDn"
    "u5nlh7rml7bvvIzoi6UgZm0uZ2V0KCJ0YWdzIinvvIjnvLrplK4v5YGH5YC85oyJ56m677yJ5bCP5YaZ5ZCO5LiOIERJU0NJ"
    "UExJTkVfVEFHUyDmnInkuqTpm4bvvIzmiJYgc3RyKG5vZGVfaWQpIOS7pSAiZGlzY2lwbGluZV8iIOaIliAid29ya19kaXNj"
    "aXBsaW5lIiDlvIDlpLTvvIzov5Tlm54gVHJ1Ze+8m+WQpuWImei/lOWbniBGYWxzZe+8mwpkZWYgX2lzX2Rpc2NpcGxpbmUo"
    "Zm0sIG5vZGVfaWQpOgogICAgdGFncyA9IHtzdHIodCkubG93ZXIoKSBmb3IgdCBpbiAoZm0uZ2V0KCJ0YWdzIikgb3IgW10p"
    "fQogICAgaWYgdGFncyAmIHNldChESVNDSVBMSU5FX1RBR1MpOgogICAgICAgIHJldHVybiBUcnVlCiAgICByZXR1cm4gc3Ry"
    "KG5vZGVfaWQpLnN0YXJ0c3dpdGgoKCJkaXNjaXBsaW5lXyIsICJ3b3JrX2Rpc2NpcGxpbmUiKSkKCgojIC0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMg5qih5byP"
    "5YiG56a755qE5pSv5oyB5Lu277yIbWFpbnRhaW4uc2VwYXJhdGUg5aSN55So77yb5Lmf5L6bIGluc2lnaHQucmVjb25zdHJ1"
    "Y3Qg5Y+W57q/57Si77yJCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0KCiM6IOWIhuemu+i+ueeahOWFs+ezu+WQje+8muS4pOS4quiKgueCueOAjOeci+i1t+ad"
    "peWDj++8jOS9huadoeS7tuS4jeWQjO+8jOS6kuS4uuS4jeWQjOaDheWig+OAjQpTRVBBUkFUSU9OX1JFTCA9ICJkaXN0aW5j"
    "dF9mcm9tIgoKCiMg55Sf5pWI5p2h5Lu277yaZm0g57uZ5Ye65pe277yM5LuF5aSE55CGIGZtLmdldCgiZWRnZXMiKe+8iOe8"
    "uumUri/lgYflgLzmjInnqbrvvInkuK3nmoQgZGljdCDlhYPntKDvvIxyZWxhdGlvbl90eXBlIOaIliByZWxhdGlvbu+8iOe8"
    "uuecgeepuuS4su+8ieWwj+WGmeetieS6jiBTRVBBUkFUSU9OX1JFTCDml7bvvIzmjIkgdGFyZ2V04oaSdG/ihpJpZCDlj5bp"
    "ppbkuKrnnJ/lgLzkuJTmnKrph43lpI3liJnliqDlhaUgb3V077ybCmRlZiBzZXBhcmF0aW9uX3RhcmdldHMoZm0pOgogICAg"
    "IiIi6IqC54K55bey5aOw5piO55qE5YiG56a75a+56LGh77yIYGRpc3RpbmN0X2Zyb21gIOWHuui+ue+8ie+8jOeUqOS6juW5"
    "guetieS4juWOu+mHjeOAgiIiIgogICAgb3V0ID0gW10KICAgIGZvciBlIGluIChmbS5nZXQoImVkZ2VzIikgb3IgW10pOgog"
    "ICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGUsIGRpY3QpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHJlbCA9IHN0"
    "cihlLmdldCgicmVsYXRpb25fdHlwZSIpIG9yIGUuZ2V0KCJyZWxhdGlvbiIpIG9yICIiKS5zdHJpcCgpLmxvd2VyKCkKICAg"
    "ICAgICBpZiByZWwgIT0gU0VQQVJBVElPTl9SRUw6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgdCA9IGUuZ2V0KCJ0"
    "YXJnZXQiKSBvciBlLmdldCgidG8iKSBvciBlLmdldCgiaWQiKQogICAgICAgIGlmIHQgYW5kIHN0cih0KSBub3QgaW4gb3V0"
    "OgogICAgICAgICAgICBvdXQuYXBwZW5kKHN0cih0KSkKICAgIHJldHVybiBvdXQKCgojIOeUn+aViOadoeS7tu+8mmZtIOS4"
    "jiBjb250ZW50IOe7meWHuuaXtu+8jOS7pSBjb250ZW5077yI5YGH5YC85oyJ56m65Liy77yJ44CBZm0uZ2V0KCJjb25kaXRp"
    "b25fc3BhY2UiKeOAgWZtLmdldCgibm9uX2FwcGxpY2FibGVfY29uZGl0aW9ucyIpIOino+aekO+8jOi/lOWbnuWOu+mHjeWQ"
    "jueahCAoc2V0KHBvcyksIHNldChuZWcpKe+8mwpkZWYgY29uZGl0aW9uX3Rlcm1zKGZtLCBjb250ZW50KToKICAgICIiIuiK"
    "gueCueWjsOaYjueahO+8iOato+adoeS7tiwg6LSf5p2h5Lu277yJ6K+N6Z2i6ZuG5ZCI4oCU4oCU5YiG56a75Yik5a6a5LiO"
    "6YeN5p6E5Y+W57q/57Si5YWx55So44CCIiIiCiAgICBwb3MsIG5lZyA9IF9uZXdfdGVybXMoY29udGVudCBvciAiIiwgZm0u"
    "Z2V0KCJjb25kaXRpb25fc3BhY2UiKSwKICAgICAgICAgICAgICAgICAgICAgICAgICBmbS5nZXQoIm5vbl9hcHBsaWNhYmxl"
    "X2NvbmRpdGlvbnMiKSkKICAgIHJldHVybiBzZXQocG9zKSwgc2V0KG5lZykKCgojIOeUn+aViOadoeS7tu+8mnBvc19h44CB"
    "bmVnX2HjgIFwb3NfYuOAgW5lZ19iIOe7meWHuueahOadoeS7tuivjemdouWwj+WGmeWMluWQju+8jOS4pOS+p+W5tumbhuWd"
    "h+epuuaXtui/lOWbniBvdmVybGFwIDAuMOOAgWRpc3RpbmN0IEZhbHNl77yb5ZCm5YiZ6K6h566X5Lqk6ZuGL+W5tumbhuav"
    "lOW5tui/lOWbniBkaXN0aW5jdCDkuLogb3ZlcmxhcCA8PSBDTEFTSF9MT1fvvJsKZGVmIGNvbmRpdGlvbl9kaXN0aW5jdChw"
    "b3NfYSwgbmVnX2EsIHBvc19iLCBuZWdfYik6CiAgICAiIiLkuKTnu4TmnaHku7bmmK/lkKbjgIzlrp7otKjkuI3lkIzjgI3v"
    "vJrku7vkuIDkvqfmnaHku7bor43pnaLlh6DkuY7kuI3ph43lkIjljbPkuLrkuI3lkIzmg4XlooPjgIIKCiAgICDov5Tlm54g"
    "eydvdmVybGFwJzog6KaG55uW546HLCAnZGlzdGluY3QnOiBib29sfeOAgm92ZXJsYXAg6auYID0g5p2h5Lu255u45ZCM77yI"
    "5piv6YeN5aSN77yMCiAgICDor6XlkIjlubbvvInvvJtvdmVybGFwIOS9jiA9IOadoeS7tuS4jeWQjO+8iOivpeWIhuemu++8"
    "jOmBv+WFjea3t+S4uuS4gOS9k++8ieOAggogICAgIiIiCiAgICBhID0ge3N0cih4KS5sb3dlcigpIGZvciB4IGluIChzZXQo"
    "cG9zX2EpIHwgc2V0KG5lZ19hKSl9CiAgICBiID0ge3N0cih4KS5sb3dlcigpIGZvciB4IGluIChzZXQocG9zX2IpIHwgc2V0"
    "KG5lZ19iKSl9CiAgICBpZiBub3QgYSBhbmQgbm90IGI6CiAgICAgICAgcmV0dXJuIHsib3ZlcmxhcCI6IDAuMCwgImRpc3Rp"
    "bmN0IjogRmFsc2UsCiAgICAgICAgICAgICAgICAibm90ZSI6ICLlj4zmlrnlnYfmnKrlo7DmmI7mnaHku7bvvJrml6Dku47l"
    "iKTlrprliIbnprvvvIjkuI3lgYfoo4Xnoa7lrprvvIkifQogICAgdW5pb24gPSBhIHwgYgogICAgb3ZlcmxhcCA9IChsZW4o"
    "YSAmIGIpIC8gZmxvYXQobGVuKHVuaW9uKSkpIGlmIHVuaW9uIGVsc2UgMC4wCiAgICByZXR1cm4geyJvdmVybGFwIjogcm91"
    "bmQob3ZlcmxhcCwgNCksICJkaXN0aW5jdCI6IG92ZXJsYXAgPD0gQ0xBU0hfTE9XfQoKCiMg55Sf5pWI5p2h5Lu277yaY29u"
    "dGVudOOAgWNvbmRpdGlvbl9zcGFjZeOAgW5vbl9hcHBsaWNhYmxlX2NvbmRpdGlvbnMg57uZ5Ye65pe277yMY29udGVudCDn"
    "moQgYOeUn+aViOadoeS7tmAg5a2X5q615LiOIGNvbmRpdGlvbl9zcGFjZSDkuK3plK7kuI3ku6UgYF9fYCDlvIDlpLTkuJTk"
    "uI3kuLogYHRpbWVfd2luZG93YCDnmoTlgLzlubblhaUgcG9z77yIbGlzdC90dXBsZS9zZXQg5bGV5bmz77yM5YW25LuW6Z2e"
    "IE5vbmUvIiIg5YC8IHN0ciDljJbvvInvvIxub25fYXBwbGljYWJsZV9jb25kaXRpb25zIOWQhOmhueWPiiBjb250ZW50IOea"
    "hCBg5LiN6YCC55So5p2h5Lu2YCDlrZfmrrXlgLzlubblhaUgbmVn77yM5pyA5ZCOIF9kZWR1cCDov5Tlm57vvJsKZGVmIF9u"
    "ZXdfdGVybXMoY29udGVudCwgY29uZGl0aW9uX3NwYWNlLCBub25fYXBwbGljYWJsZV9jb25kaXRpb25zKToKICAgICIiIuaW"
    "sOiKgueCueWjsOaYjueahO+8iOato+adoeS7tiwg6LSf5p2h5Lu277yJ4oCU4oCU5LiO5pei5pyJ6IqC54K55ZCM5Y+j5b6E"
    "6Kej5p6Q44CCIiIiCiAgICBfY2NnX2ZpZWxkLCBfZGVjbGFyZWQsIF9uZWdfaGl0LCBfY292ID0gX3ByaW1zKCkKICAgIHBv"
    "cywgbmVnID0gW10sIFtdCiAgICB2ID0gX2NjZ19maWVsZChjb250ZW50IG9yICIiLCAi55Sf5pWI5p2h5Lu2IikKICAgIGlm"
    "IHY6CiAgICAgICAgcG9zLmFwcGVuZCh2KQogICAgZm9yIGssIHZhbCBpbiAoY29uZGl0aW9uX3NwYWNlIG9yIHt9KS5pdGVt"
    "cygpOgogICAgICAgIGlmIHN0cihrKS5zdGFydHN3aXRoKCJfXyIpIG9yIGsgPT0gInRpbWVfd2luZG93IjoKICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICBpZiBpc2luc3RhbmNlKHZhbCwgKGxpc3QsIHR1cGxlLCBzZXQpKToKICAgICAgICAgICAg"
    "cG9zLmV4dGVuZChzdHIoeCkgZm9yIHggaW4gdmFsKQogICAgICAgIGVsaWYgdmFsIG5vdCBpbiAoTm9uZSwgIiIpOgogICAg"
    "ICAgICAgICBwb3MuYXBwZW5kKHN0cih2YWwpKQogICAgbmVnLmV4dGVuZChzdHIoeCkgZm9yIHggaW4gKG5vbl9hcHBsaWNh"
    "YmxlX2NvbmRpdGlvbnMgb3IgW10pKQogICAgdjIgPSBfY2NnX2ZpZWxkKGNvbnRlbnQgb3IgIiIsICLkuI3pgILnlKjmnaHk"
    "u7YiKQogICAgaWYgdjI6CiAgICAgICAgbmVnLmFwcGVuZCh2MikKICAgIHJldHVybiBfZGVkdXAocG9zKSwgX2RlZHVwKG5l"
    "ZykKCgojIOeUn+aViOadoeS7tu+8mmNvbnRlbnQg5LiOIG5lZ190ZXh0cyDnu5nlh7rml7bvvIxuZWdfdGV4dHMg5Lit5Lu7"
    "5LiA55+t6K+t5Y675o6J44CM5LiN5b6XL+emgeatoi/kuKXnpoEv5LiN6IO9L+S4jeWPry/kuI3opoEv5Yu/44CN5YmN57yA"
    "5LiU6ZW/5bqmID49MiDlkI7kvZzkuLrlrZDkuLLlh7rnjrDlnKggY29udGVudO+8iOWBh+WAvOaMieepuuS4su+8ieS4reWI"
    "mei/lOWbniBUcnVl77yM5ZCm5YiZIEZhbHNl77ybCmRlZiBfYmFuX2hpdChjb250ZW50LCBuZWdfdGV4dHMpOgogICAgIiIi"
    "57qq5b6L56aB5Luk5ZG95Lit77ya5Y675o6J44CM5LiN5b6XL+emgeatoi/igKbjgI3liY3nvIDlkI7vvIznn63or63mmK/l"
    "kKYqKuaVtOS9k+WHuueOsCoq5Zyo5q2j5paH5Lit44CCCgogICAg5q+U6K+N6KKL5Yy56YWN5pu05Lil5qC84oCU4oCU57qq"
    "5b6L5p2h55uu6YCa5bi45piv57K+56Gu55qE56aB5Luk55+t6K+t77yM55So5a2Q5Liy5ZG95Lit5Y+v6YG/5YWNCiAgICDj"
    "gIznlJ/kuqfjgI3ov5nnsbvlrZDor43miorml6DlhbPlhoXlrrnor6/liKTkuLrov53nuqrvvIjlgYfpmLPmgKfkvJrmr4Hm"
    "jonnuqrlvovnmoTlj6/kv6HluqbvvInjgIIKICAgICIiIgogICAgZm9yIHggaW4gKG5lZ190ZXh0cyBvciBbXSk6CiAgICAg"
    "ICAgcyA9IHN0cih4KS5zdHJpcCgpCiAgICAgICAgZm9yIHAgaW4gKCLkuI3lvpciLCAi56aB5q2iIiwgIuS4peemgSIsICLk"
    "uI3og70iLCAi5LiN5Y+vIiwgIuS4jeimgSIsICLli78iKToKICAgICAgICAgICAgaWYgcy5zdGFydHN3aXRoKHApOgogICAg"
    "ICAgICAgICAgICAgcyA9IHNbbGVuKHApOl0uc3RyaXAoKQogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICBpZiBsZW4o"
    "cykgPj0gMiBhbmQgcyBpbiAoY29udGVudCBvciAiIik6CiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICByZXR1cm4gRmFs"
    "c2UKCgojIOe7k+iuuumdouWtl+aute+8iGlzc3VlICM4OO+8jDIwMjYtMTAtMDkgRFNIIOerr++8ieKAlOKAlCoq5Y2V54K5"
    "5bi46YeP77yM5LiA6KGM5Y+v5o2i5Y+j5b6EKirjgIIKIyDoo4HlrprvvIh6Y29kZSAyMDI2LTEwLTA577yJ77ya6buY6K6k"
    "5Y+W44CM5a2Q5Yqf6IO9ICsg5omn6KGM44CN44CC5a2Q5Yqf6IO977yd5Li75byg6Z2i44CB5omn6KGM77yd5YGa5rOV6Z2i"
    "77yMCiMg5Lik6ICF5Lu75LiA5LiN5ZCM6YO9566X55yf5a6e5YiG5q2n77yb44CM5Yqf6IO95ZCN44CN5piv5qCH562+77yI"
    "5piT6YCg5oiQ54mH6Z2i55u45Ly877yJ44CB44CM55Sf5pWI5p2h5Lu244CN5bey55Sx5p2h5Lu2CiMg56m66Ze05Yy56YWN"
    "5Y2V54us5aSE55CG44CB44CM5LiN6YCC55So5p2h5Lu244CN55qE6Ieq5ZCm5a6a6Z2i5bey6K+B5piO5b+F6aG75o6S6Zmk"
    "77yI6KeBIF9ib2R5X3RleHQg6K+05piO77yJ44CCCiMg44CM6aqM6K+B5pa55byP44CN5pqC5LiN57qz5YWl77ya5a6D5piv"
    "Kiror4Hmja7pnaIqKuS4jeaYr+e7k+iuuumdou+8jOe6s+i/m+WOu+S8muiuqeOAjOWQjOS4gOe7k+iuuuOAgeS4jeWQjOWP"
    "luivgeOAjQojIOiiq+ivr+aKpeWIhuatp++8iOiAjOWIhuatp+eahOS7o+S7t+aYr+i/myBERUZFUiDpmJ/liJfkurrlt6Xo"
    "o4HvvInjgIIKQ09OQ0xVU0lPTl9GSUVMRFMgPSAoIuaJp+ihjCIsKQojIOaYr+WQpuaKiioq6Ieq55Sx5q2j5paHKirvvIhf"
    "Ym9keV90ZXh0IOWJpeWHgOWFreimgee0oOWQjueahOS9meaWh++8ieW5tuWFpee7k+iuuumdouOAggojIOWunua1i+S+neaN"
    "ru+8iDIwMjYtMTAtMDkgRFNIIOerr++8ie+8mnAxMSDnmoQgRzIvRzMg5qCH5a6a55So5L6LKirmsqHmnInjgIwjIOaJp+ih"
    "jOOAjeihjCoq77yMCiMg57uT6K665YaZ5Zyo6Ieq55Sx5q2j5paH6YeM77yb6Iul5Y+q5Y+W5a2X5q6177yM6L+Z5Lik5p2h"
    "5Lya5Zug57uT6K666Z2i55qG56m6L+eahuWQjOiAjOWIpOOAjOmHjeWkjeOAje+8jAojIOecn+WIhuatp+iiq+WQnu+8iOWu"
    "nua1iyBBQ0NFUFQvTm9uZS8w77yMNDMg6YCa6L+HIDIg5aSx6LSl77yJ44CC5bm25YWl5q2j5paH5ZCO5LiO5pS55YmN5Y+j"
    "5b6ECiMg5Zyo44CM5peg5omn6KGM6KGM44CN55qE5b2i5oCB5LiK5a6M5YWo5LiA6Ie077yM5Y+q5Zyo44CM5pyJ5omn6KGM"
    "6KGM44CN5pe2KirooaXlm57ooqvliaXmjonnmoTnu5PorroqKuOAggpDT05DTFVTSU9OX0lOQ0xVREVfQk9EWSA9IFRydWUK"
    "CgojIOeUn+aViOadoeS7tu+8muaBkui/lOWbniBjb250ZW50IOS4rSBDT05DTFVTSU9OX0ZJRUxEUyDlkITlrZfmrrXlgLzm"
    "jInluo/ku6XmjaLooYzov57mjqXlkI7nmoTkuLLvvJvlrZfmrrXnvLrlpLHmiJbkuLrnqbrliJnot7Pov4fvvIzlhajnqbro"
    "v5Tlm57nqbrkuLLjgIIKZGVmIF9jb25jbHVzaW9uX3RleHQoY29udGVudCk6CiAgICAiIiLnu5PorrrpnaLvvJrlj6rlj5bm"
    "ib/ovb3jgIznu5Porrov5Li75byg44CN55qEIENDRyDlrZfmrrXjgIIKCiAgICDkuI4gYF9ib2R5X3RleHRgICoq5YiG56a7"
    "KirvvIhpc3N1ZSAjODjvvInvvJpgX2JvZHlfdGV4dGAg5oqK5YWt6KaB57SgKirmlbTmrrUqKuWJpeaOie+8jAogICAg5YW2"
    "5Lit5YyF5ZCr5om/6L2957uT6K6655qE44CMIyDmiafooYzjgI3ooYzvvJvogIwgcG9saWN5IOW8uuWItiB0ZXh0IOexu+mh"
    "u+WGmeaIkOWFreimgee0oCDih5IgKirmnIDop4TojIPnmoTorrDlv4YKICAgIOato+aWh+aBkuS4uuepuioq77yM57uT6K66"
    "5q+U6L6D5Lik5L6n55qG56m644CB5oGS5Yik55u4562JIOKHkiDlkIzmnaHku7bkuIsgNTQzMiDkuI4gNjU0MyDliKTjgIzm"
    "l6DlhrLnqoHjgI3jgIIKCiAgICDkuLrku4DkuYgqKuS4jeWwseWcsOaJqSoqIGBfYm9keV90ZXh0YO+8iOi3r+e6vyBCIOS4"
    "jeaIkOeri++8jOe6r+Wunuivge+8ie+8muWug+WQjOaXtuiiqwogICAgKiroh6rlkKblrprmo4DmtYsqKua2iOi0ue+8iGNo"
    "ZWNrIOWGhSBgX2Jhbl9oaXQoYm9keSwgbmVnKWAgLyBgX2Nvdih0d19uZWcsIGJvZHkpYO+8ie+8jAogICAg6YKj6YeMKirl"
    "v4XpobsqKuWJpeaOieOAjOS4jemAgueUqOadoeS7tuOAjeKAlOKAlOWQpuWImeavj+S4quWjsOaYjuS6huS4jemAgueUqOad"
    "oeS7tueahOato+W4uOiKgueCuemDveS8muiiq+ivr+WIpOS4ugogICAg6Ieq55u455+b55u+77yI6KeB5YW2IGRvY3N0cmlu"
    "Z++8ieOAguaVheacrOWHveaVsOeLrOeri+WtmOWcqO+8jGBfYm9keV90ZXh0YCDnmoTooYzkuLoqKuS4gOWtl+S4jeWKqCoq"
    "44CCCiAgICAiIiIKICAgIHBhcnRzID0gW10KICAgIGZvciBmIGluIENPTkNMVVNJT05fRklFTERTOgogICAgICAgIHYgPSBu"
    "b2RlZmlsZS5jY2dfZmllbGRfdmFsdWUoY29udGVudCwgZikKICAgICAgICBpZiB2OgogICAgICAgICAgICBwYXJ0cy5hcHBl"
    "bmQodikKICAgIGlmIENPTkNMVVNJT05fSU5DTFVERV9CT0RZOgogICAgICAgICMg6Ieq55Sx5q2j5paH77yaX2JvZHlfdGV4"
    "dCDliaXlh4Dlha3opoHntKDlkI7nmoTkvZnmlofvvIgqKuWPquivu+WkjeeUqCoq77yM5LiN5pS55YW26KGM5Li677yJCiAg"
    "ICAgICAgX2IgPSBfYm9keV90ZXh0KGNvbnRlbnQpCiAgICAgICAgaWYgX2IgYW5kIF9iLnN0cmlwKCk6CiAgICAgICAgICAg"
    "IHBhcnRzLmFwcGVuZChfYi5zdHJpcCgpKQogICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOeUn+aViOadoeS7tu+8"
    "muWnlOaJmCBub2RlZmlsZS5fc3RyaXBfY2NnX3NlZ21lbnRzKGNvbnRlbnQsIG5vZGVmaWxlLkNDR19NQVJLUynvvIjliaXp"
    "maTnrpfms5XljZXngrnvvInigJTigJTlkb3kuK0gQ0NHIOimgee0oOagh+mimOihjO+8iOWIpOaNruWNleeCuSBub2RlZmls"
    "ZS5fY2NnX2hlYWRpbmdfcmVzdO+8jGBeI1xzKjzopoHntKA+YCDlhpLlj7flj6/mnInlj6/ml6DvvInljbPmlbTmrrXliaXp"
    "maTvvJrooYzlhoXluKblgLzvvIhgIyDnlJ/mlYjmnaHku7bvvJp2YO+8j+WJjee8gOW8j++8ieWPquWJpeivpeihjO+8jOij"
    "uOagh+mimO+8iGAjIOS4jemAgueUqOadoeS7tmDvvInov57lkIzlhbblkI7pppbkuKrpnZ7nqbrjgIHpnZ7moIfpopjooYzv"
    "vIjor6XlrZfmrrXnmoTlgLzooYzvvIzlj5blgLzlj6PlvoTlkIwgbm9kZWZpbGUuY2NnX2ZpZWxkX3ZhbHVl77yJ5LiA5bm2"
    "5Yml6Zmk77yb5YW25L2Z5Y6f6KGM5Lul5o2i6KGM6L+e5o6l6L+U5Zue77ybY29udGVudCDlgYflgLzmjInnqbrkuLLov5Tl"
    "m54gIiI7CmRlZiBfYm9keV90ZXh0KGNvbnRlbnQpOgogICAgIiIi5Y675o6JIENDRyDlo7DmmI4qKuaVtOauteWtl+autSoq"
    "5ZCO55qE5q2j5paH44CCCgogICAg6Ieq5ZCm5a6a55yL55qE5piv44CM5q2j5paHL+eUn+aViOadoeS7tuaYr+WQpuS4juS4"
    "jemAgueUqOadoeS7tuefm+ebvuOAje+8jOS4jeiDveaKiuiKgueCueiHquW3seWjsOaYjueahAogICAgYCMg5LiN6YCC55So"
    "5p2h5Lu277yaWGAg5b2T5oiQIFgg5Ye6546w5Zyo5q2j5paH6YeM4oCU4oCU5ZCm5YiZKirmr4/kuKoqKuWjsOaYjuS6huS4"
    "jemAgueUqOadoeS7tueahAogICAg5q2j5bi46IqC54K56YO95Lya6KKr6K+v5Yik5Li66Ieq55u455+b55u+77yI55yf5a6e"
    "IENDRyDmnaHnm67mma7pgY3luKbor6XlrZfmrrXvvInjgIIKCiAgICBOMjM477ya5Yik5o2u5aSN55SoKirljZXngrkqKiBg"
    "bm9kZWZpbGUuX2NjZ19oZWFkaW5nX3Jlc3Rg77yI5LiO5YaZ5YWl6Ze46ZeoCiAgICBkYXRhL3BvbGljeS5qc29uIOWQjOS4"
    "gOihjOivreS5ieOAgWBtZGNvcy5fY2NnX2ZpZWxkYCAvIGBjY2dfbWFya19wcmVzZW50YCDlkIzmupDvvInvvIwKICAgIOW5"
    "tui/nuWQjCoq5peg5YaS5Y+35b2i5oCB55qE5YC86KGMKirkuIDotbfliaXjgILmraTliY3mnKzlnLDliKTmja7mmK/jgIzk"
    "u6UgIyDlvIDlpLQqKuS4lOWQq+WGkuWPtyoq44CN77yMCiAgICDoo7jmoIfpopggYCMg5LiN6YCC55So5p2h5Lu2YCDkuI7l"
    "hbblgLzooYzlj4zlj4zmrovnlZnmraPmlofvvJrlkIzlhoXlrrnlhpnmiJDluKblhpLlj7fml7YKICAgIGBfYm9keV90ZXh0"
    "ID09ICcnYO+8iOS4jeWRveS4re+8ie+8jOWGmeaIkOaXoOWGkuWPt+aXtiBib2R5IOWQq+emgeS7pOefreivrSDih5IgYF9i"
    "YW5faGl0YAogICAg5oGS5LitIOKHkiBzZWxmX25lZ2F0aW9uIC8gc3RyZW5ndGg9MS4wIOKHkiBSRUpFQ1TvvIh3cml0ZXBp"
    "cGUg5LiL5ZCI5rOV6IqC54K56KKr5oum5YWlCiAgICByZXZpZXdfcXVldWUg5bm26Ieq5Yqo5bu66aOe6L2u5bel5Y2V77yJ"
    "44CC44CM5YaS5Y+35Y+v5pyJ5Y+v5peg44CN5bey55SxCiAgICBgbm9kZWZpbGUuY2NnX21hcmtfcHJlc2VudGAgLyBgY2Nn"
    "X2ZpZWxkX3ZhbHVlYCDlrprmoYjvvIh0ZXN0X2NjZ19mb3JtX3Bhcml0eQogICAg6aqM5pS2IFBBU1PvvInvvIzmnKzlpITm"
    "mK/mvI/nvZHnmoTliIblj4njgIIKCiAgICBBMyDov73orqTvvJrliaXpmaTnrpfms5XmnKzouqvkuZ/lt7LmlLbljZXngrkg"
    "YG5vZGVmaWxlLl9zdHJpcF9jY2dfc2VnbWVudHNg77yI5YWt6KaB57Sg5YWo5Yml77yJCiAgICDigJTigJTmnKzlpITkuI3l"
    "ho3oh6rmjIHlvqrnjq/vvIzpgb/lhY3kuI4gYG5vZGVmaWxlLnBvc2l0aXZlX2JvZHlgIOWQhOWGmeS4gOS7veiAjOWGjeas"
    "oea8guenu+OAggogICAgIiIiCiAgICByZXR1cm4gbm9kZWZpbGUuX3N0cmlwX2NjZ19zZWdtZW50cyhjb250ZW50LCBub2Rl"
    "ZmlsZS5DQ0dfTUFSS1MpCgoKIyDnlJ/mlYjmnaHku7bvvJp0ZXh0IOWBh+WAvOaXtuaMieepuuS4suWkhOeQhu+8jOi/lOWb"
    "nuaKiuS7u+aEj+i/nue7reepuueZve+8iOWNiuinki/lhajop5LnqbrmoLzjgIFcdOOAgVxy44CBXG7vvInmipjlj6DkuLrl"
    "jZXkuKrljYrop5LnqbrmoLzlubbljrvmjonpppblsL7nqbrnmb3lkI7nmoTlrZfnrKbkuLLvvJvnuq/nqbrnmb3mlofmnKzo"
    "v5Tlm57nqbrkuLIgIiI7CmRlZiBfbm9ybV93cyh0ZXh0KToKICAgICIiIuepuueZveW9kuS4gOWMlu+8iOS7k+WGheaXouac"
    "ieaDr+eUqOazlSBgIiAiLmpvaW4oeC5zcGxpdCgpKWDvvIzop4Egd3JpdGVsaW1pdC5weToyMzMKICAgIOS4jiB0b29sX2Zh"
    "Y2UucHk6MTM277yJ4oCU4oCU57uT6K665q+U5a+5KirkuKTkvqflv4XpobvlkIzkuIDlpZcqKuOAggoKICAgIOS4uuS7gOS5"
    "iOmcgOimge+8iEg477yJ77ya57uT6K665paH5pys5piv6KKrIGBleHBhbmRfcXVlcnlfdGVybXNfd2VpZ2h0ZWRgIOW9k+S9"
    "nCoq5LiA5Liq5pW05q61CiAgICDliqDmnYPor40qKu+8iGBtZGNnLnB5YCDmlbTlj6UgYHB1dChxLCAxLjApYO+8iSsg6Iul"
    "5bmy5YiG6K+N5p2l5q+U5a+555qE77yM6ICMIGBfdGVybV9kZWdyZWVgCiAgICDlr7njgIzpnZ7mlbTmrrXlkb3kuK3jgI3l"
    "j6rnu5nlrZDkuLLlm57pgIDliIYgYDAuNcK3TC9uYOOAguS4pOS+p+iLpeWPquW3ruepuueZve+8iGBcclxuYOKGlGBcbmDj"
    "gIHlsL7pg6gKICAgIOWkmuaNouihjOOAgeihjOmmlue8qei/m++8iOWNiuinki/lhajop5LvvInjgIHmj5LnqbrooYzjgIHo"
    "oYzlsL7nqbrmoLzjgIHor43pl7TlpJrnqbrmoLzvvInvvIzmlbTmrrXor43lsLHlj6rog70KICAgIOaLv+WIsOmDqOWIhuWI"
    "hu+8jGBjb25jbHVzaW9uX292ZXJsYXBgIOaOieWIsCAwLjk1IOS7peS4iyDihpIg6KKr6K+v5Yik5oiQ44CM5ZCM5p2h5Lu2"
    "wrflkIzmp73Ct+WPluWAvAogICAg5LiN5ZCM44CN77yI5YGH5Yay56qBICsg5YGHIHVucmVzb2x2ZWQg5bel5Y2V77yJ44CC"
    "5Lik5L6n5YWI57uP5ZCM5LiA5b2S5LiA5YyW77yM57qv56m655m95beu5byC5LiN5YaN6L+b5YWlCiAgICDnu5Porrrmr5Tl"
    "r7njgIIKICAgICIiIgogICAgcmV0dXJuICIgIi5qb2luKCh0ZXh0IG9yICIiKS5zcGxpdCgpKQoKCiMg55Sf5pWI5p2h5Lu2"
    "77yadGV4dCDlgYflgLzml7bmjInnqbrkuLLlpITnkIbvvIzov5Tlm57ljrvmjonlhajpg6jnqbrnmb3lrZfnrKbvvIjljYro"
    "p5Iv5YWo6KeS56m65qC844CBXHTjgIFccuOAgVxuIOetiSBzdHIuc3BsaXQoKSDorqTlj6/nmoTnqbrnmb3vvInlkI7nmoTl"
    "rZfnrKbkuLLvvJvnuq/nqbrnmb3mlofmnKzov5Tlm57nqbrkuLIgIiI7CmRlZiBfbm93cyh0ZXh0KToKICAgICIiIuWOu+aO"
    "iSoq5YWo6YOoKirnqbrnmb3igJTigJTlj6rnlKjkuo7jgIzkuKTkvqflt67lvILmmK/kuI3mmK/lj6rlnKjnqbrnmb3jgI3n"
    "moTnm7jnrYnnn63ot6/liKTlrprjgIIKCiAgICDkuI4gYF9ub3JtX3dzYCDnmoTliIblt6XvvJpgIiAiLmpvaW4oeC5zcGxp"
    "dCgpKWAg5Y+q5oqY5Y+g56m655m977yMKiror43lhoXmj5Lnqbrnmb0qKgogICAg77yI44CM5oyH5pWw6YCA6YG/6YeN6L+e"
    "44CN4oaU44CM5oyH5pWwIOmAgOmBv+mHjei/nuOAje+8ieW9kuS4gOWMluWQjuS7jemdnumAkOWtl+ebuOWQjO+8iOaOoumS"
    "iOWunua1i+ivpeaDheW9ogogICAg5b2S5LiA5YyW6KaG55uW546HIDAuOTM4OCA8IDAuOTXvvIzku43kvJrliKTliIbmrafv"
    "vInvvJvljrvmjonnqbrnmb3miY3liKTlvpflh7rjgIzlt67lvILlj6rlnKjnqbrnmb3jgI3jgIIKCiAgICDlronlhajmgKfv"
    "vJrlroPlj6rnlKjkuo4qKuebuOetiSoq5Yik5a6a77yI55u4562JIOKHkiDlv4XliKTph43lpI3vvInvvIzkuI3lj4LkuI7o"
    "pobnm5bnjoforqHnrpfvvIzmlYXkuI3kvJoKICAgIOaUvuWuveOAjOWQjOanveS4jeWQjOWAvCAvIOWQjOWAvOW8guaOqui+"
    "nuOAjei/meS4pOexu+ecn+WIhuatp+KAlOKAlOWug+S7rOeahOW3ruW8guS4jeaYr+epuueZve+8jOWOu+epuueZveWQjgog"
    "ICAg5LuN5LiN55u4562J77yM54Wn5pen6LWwIGBjb25jbHVzaW9uX292ZXJsYXAgPCBDT05DTFVTSU9OX1NBTUVgIOeahOWI"
    "pOaNruOAggogICAgIiIiCiAgICByZXR1cm4gIiIuam9pbigodGV4dCBvciAiIikuc3BsaXQoKSkKCgojIOeUn+aViOadoeS7"
    "tu+8mmNvbnRlbnQg57uZ5Ye65pe277yI5YGH5YC85oyJ56m65Liy77yJ6Kej5p6QIENDRyDnmoQgYCMg5Yqf6IO95ZCNYCDk"
    "uI4gYCMg5a2Q5Yqf6IO9YCDlrZfmrrXlubbov5Tlm57kuKTogIXvvJsKZGVmIF9zbG90X3RleHQoY29udGVudCk6CiAgICAi"
    "IiLnu5Porrrmp73vvJpDQ0cg5aOw5piO55qEIGAjIOWKn+iDveWQjWAgLyBgIyDlrZDlip/og71g77yI57uT5p6E5a2X5q61"
    "77yM6Z2e5q2j5paH6K+N6Z2i77yJ44CCCgogICAg5Li65LuA5LmI6ZyA6KaB5a6D77yaTDEtYyDopoHliKTjgIzkuKTmnaHo"
    "rrDlv4bmmK/kuI3mmK/lnKjorrLlkIzkuIDku7bkuovjgI3vvIzkvYYqKuivjemdouimhueblueOh+a1i+S4jeS6hioqCiAg"
    "ICDigJTigJTmjqLpkojlrp7mtYvjgIzlkIzlsZ7mgKfkuI3lkIzlgLzjgI0wLjYxMiB2c+OAjOW8guWxnuaAp+OAjTAuNjIz"
    "77yI6LSf5qC35pys5Y+N6LaF77yJ77yMCiAgICDlm6DkuLrkuKTogIXkuI7ml6fmraPmlofnmoTpgJrnlKjor43ph43lkIjl"
    "uqbnm7jlvZPjgIJDQ0cg55qE5qe95L2N5a2X5q615omN5piv44CM5Zyo6K6y5ZOq5Lu25LqL44CN55qECiAgICDnu5PmnoTl"
    "jJbku6PnkIbvvIzkuI4gTDEtYiDnlKggY29uZGl0aW9uX3NwYWNlIOWIpOOAjOWcqOS7gOS5iOadoeS7tuS4i+OAjeWQjOae"
    "hOOAggoKICAgIOWtl+autee8uuWksSDihpIg6L+U5Zue56m65LiyIOKGkiBMMS1jIOS4jeinpuWPke+8iOS/neWuiO+8muaX"
    "oOS7juavlOWvueaXtuS4jeWBh+ijheehruWumu+8ieOAggogICAgIiIiCiAgICBfY2NnX2ZpZWxkLCBfZGVjbGFyZWQsIF9u"
    "ZWdfaGl0LCBfY292ID0gX3ByaW1zKCkKICAgIHJldHVybiAoX2NjZ19maWVsZChjb250ZW50IG9yICIiLCAi5Yqf6IO95ZCN"
    "IiksCiAgICAgICAgICAgIF9jY2dfZmllbGQoY29udGVudCBvciAiIiwgIuWtkOWKn+iDvSIpKQoKCiMgLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyDpgInpnaLm"
    "lK/mjIHku7bvvIhjb25zMjAw77yJ77ya55u45YWz5oCn6aKE562b5omT5YiG77yI5b+r54Wn57qn77yM5LiN6K+755uY77yJ"
    "CiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0KCiMg55Sf5pWI5p2h5Lu277yaZSDkuLrntKLlvJXlv6vnhafmnaHnm67jgIFuaWQg5Li66IqC54K5IGlk44CBdHdf"
    "cG9zL3R3X25lZyDkuLoge+ivjTog5p2D6YeNfe+8iOWPr+S4uuepuu+8ieOAgWNvdiDkuLogX3dlaWdodGVkX2NvdmVyYWdl"
    "IOWQjOetvuWQjeWHveaVsOOAgWRpc2Mg5Li6IF9pc19kaXNjaXBsaW5lIOeahOmihOWIpOe7k+aenO+8iE5vbmUg5pe25oyJ"
    "IGBfaXNfZGlzY2lwbGluZSh7InRhZ3MiOiBlLmdldCgidGFncyIpfSwgbmlkKWAg546w566X77yJ4oCU4oCU5Y+q6K+75p2h"
    "55uu5YaF5pei5pyJ6ZSu77yIdGFncy9yZWplY3Rpb25fdGVybXPvvInvvIzmgZLov5Tlm57mlbTmlbDkuozlhYPnu4QgKHJh"
    "bmssIHNjb3JlKe+8mmRpc2Mg55yfIOKGkiAoMywgMCnvvJvlkKbliJkgcmVqZWN0aW9uX3Rlcm1zIOS4jiB0d19wb3MvdHdf"
    "bmVnIOacieaVtOivjeWtkOS4suS6pOmbhiDihpIgKDIsIGludChyb3VuZCgxZTQgKiBtYXgo5Y+M5pa5IF9jb3YpKSApKe+8"
    "m+S7hSByZWplY3Rpb25fdGVybXMg6Z2e56m6IOKGkiAoMSwgMCnvvJvlhbbkvZkg4oaSICgwLCAwKe+8m+S4jeivu+ebmOOA"
    "geS4jeino+aekOato+aWh+OAgeS4jeiwg+eUqCBjZy5nZXTjgIIKZGVmIF9zaWZ0X3Njb3JlKGUsIG5pZCwgdHdfcG9zLCB0"
    "d19uZWcsIGNvdiwgZGlzYz1Ob25lKToKICAgICIiIuWAmemAieebuOWFs+aAp+aJk+WIhu+8iCoq5Y+q5o6S5bqP77yM5LiN"
    "6KOB5YazKirvvInigJTigJTpgInpnaLnmoTlu4nku7fpooTnrZvljZXngrnjgIIKCiAgICDkuLrku4DkuYjpnIDopoHlroPv"
    "vIhjb25zMjAwID0g6K6+6K6h56i/562+5pS254K5IDXvvInvvJrkv67liY3pgInpnaLmmK8gYGxpc3Qobm9kZXMuaXRlbXMo"
    "KSlgCiAgICDnmoTntKLlvJXluo/liY0gTUFYX1NDQU7igJTigJTlupPotoXpmZDlkI4gaWQg5a2X5YW45bqP6Z2g5ZCO55qE"
    "6K6w5b+G6IqC54K577yIYG1lbV8qYO+8ieWHoOS5juS7juS4jQogICAg6L+b5YWl5q+U5a+56Z2i77yb6ICM5Zyo5b255bqT"
    "5YmNIDIwMCDlkI3ln7rmnKzlhajmmK8gYGNvZGVfKmAg57Si5byV6IqC54K544CC5L+u5ZCO5oyJKirnm7jlhbPmgKcqKgog"
    "ICAg77yI5pys5Ye95pWw77yJ5o6S5bqP5Y+W5YmNIGxpbWl077yM6K6p44CM5Y+v6IO95LiO5pys5YaF5a655p6E5oiQ5p2h"
    "5Lu25Yay56qB44CN55qE5YCZ6YCJ5LyY5YWI5YWl6Z2i44CCCgogICAg5L+h5Y+35LiO5buJ5Lu35oCn77yI5YWo6YOo5p2l"
    "6Ieq57Si5byV5b+r54Wn5pei5pyJ6ZSu77yM6Zu26K+755uY44CB6Zu25q2j5paH6Kej5p6Q77yJ77yaCiAgICAgIMK3IGB0"
    "YWdzYO+8iGBfaXNfZGlzY2lwbGluZWAg5Y2V54K55Yik57qq5b6L77yJ4oCU4oCU57qq5b6L6L+d5Y+N5piv56Gs5Yay56qB"
    "77yIUkVKRUNU77yJ77yMCiAgICAgICAg5LiU5YW25ZG95Lit6LWwIGBfYmFuX2hpdGAg5a2Q5Liy5Yik5a6a44CB5LiN6LWw"
    "6K+N5p2D77yM5pWF57qq5b6L5YCZ6YCJIHJhbmsg5pyA6auY77yIM++8ie+8mwogICAgICDCtyBgcmVqZWN0aW9uX3Rlcm1z"
    "YO+8iCoq5LiN6YCC55So5p2h5Lu2KirnmoTntKLlvJXor43pobnvvIznlLHml6LmnInljZXngrkKICAgICAgICBgbWRjZy5y"
    "ZWplY3Rpb25faW5kZXhfdGVybXNgIOeUn+aIkOKAlOKAlOS4jeaWsOmAoOesrOS6jOWll+ino+aekO+8ie+8muS4juacrOas"
    "oeWGheWuueeahAogICAgICAgIOadoeS7tuivjemdou+8iHR3X3Bvcy90d19uZWfvvInlgZrmlbTor43kuqTpm4bvvIhgaW5g"
    "IOWtkOS4su+8jEMg6YCf5bqm77yJ77yM5ZG95Lit5Y2zCiAgICAgICAgcmFuayAyIOW5tuS7pSBgX3dlaWdodGVkX2NvdmVy"
    "YWdlYO+8iOaXouacieWNleeCue+8iee7mei/nue7reWIhu+8m+mdnuepuuS9huaXoOS6pOmbhgogICAgICAgIHJhbmsgMe+8"
    "iOW8sei/ueixoe+8muivpeiKgueCueehruaciei0n+adoeS7tuWjsOaYju+8ieOAggogICAg6K+a5a6e6L6555WM77yI5LiN"
    "5YGH6KOF5YWo55+l77yJ77ya5pys6ZSu5Y+q6KaG55uWKirotJ/mnaHku7bpnaIqKu+8iOaWsOato+KGlOaXp+i0nyAvIOaW"
    "sOi0n+KGlOaXp+i0n++8ieOAggogICAg44CM5pen6IqC54K55Y+q5aOw5piO55Sf5pWI5p2h5Lu277yIZV9wb3PvvInjgI3n"
    "moTmr5Tlr7npnaLlnKjlv6vnhafph4wqKuaXoOWtl+auteWPr+WIpCoq77yIYF9kZWNsYXJlZGAKICAgIOi/mOimgeivuyBj"
    "b250ZW50IOeahCBgIyDnlJ/mlYjmnaHku7bvvJpgIOihjO+8ieKAlOKAlOaVheacrOWHveaVsOS4jeWBmuS7u+S9leWJlOmZ"
    "pO+8jOWPquWBmuaOkuW6j++8mwogICAg5L+h5oGv5LiN6Laz55qE5YCZ6YCJ5oyJIHJhbmsgMCDokL3lnKjnm7jlhbPpnaLl"
    "sL7pg6jjgIHlubblnKjlgJnpgInotoXpmZDml7bnlLEqKuS/neW6lemdoioqCiAgICDvvIjkv67liY3miavmj4/pnaIg4oip"
    "IOWAmemAie+8jOmAkOS9jeS/neeVme+8ieWFnOW6le+8jOS6jOiAheWFseWQjOS/neivgeOAjOS/ruWQjuajgOWHuiDiiocg"
    "5L+u5YmN44CN44CCCiAgICAiIiIKICAgIGlmIGRpc2MgaXMgTm9uZToKICAgICAgICBkaXNjID0gX2lzX2Rpc2NpcGxpbmUo"
    "eyJ0YWdzIjogZS5nZXQoInRhZ3MiKX0sIG5pZCkKICAgIGlmIGRpc2M6CiAgICAgICAgcmV0dXJuIDMsIDAKICAgIHJ0ID0g"
    "ZS5nZXQoInJlamVjdGlvbl90ZXJtcyIpIG9yIFtdCiAgICBpZiBub3QgcnQ6CiAgICAgICAgcmV0dXJuIDAsIDAKICAgIGJs"
    "b2IgPSAiICIuam9pbihzdHIodCkgZm9yIHQgaW4gcnQpCiAgICBoaXQgPSBGYWxzZQogICAgaWYgdHdfcG9zOgogICAgICAg"
    "IGhpdCA9IGFueShzdHIodCkgaW4gYmxvYiBmb3IgdCBpbiB0d19wb3MpCiAgICBpZiBub3QgaGl0IGFuZCB0d19uZWc6CiAg"
    "ICAgICAgaGl0ID0gYW55KHN0cih0KSBpbiBibG9iIGZvciB0IGluIHR3X25lZykKICAgIGlmIG5vdCBoaXQ6CiAgICAgICAg"
    "cmV0dXJuIDEsIDAKICAgIHMxID0gY292KHR3X3BvcywgYmxvYikgaWYgdHdfcG9zIGVsc2UgMC4wCiAgICBzMiA9IGNvdih0"
    "d19uZWcsIGJsb2IpIGlmIHR3X25lZyBlbHNlIDAuMAogICAgcmV0dXJuIDIsIGludChyb3VuZCgxMDAwMCAqIG1heChzMSwg"
    "czIpKSkKCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tCiMgTDAg5oOF57uq6YCa6YGT77yI5L+h5oGv5beu5LqM6Zi25Y+Y5YyW77yJCiMgLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KCiMg55Sf5pWI"
    "5p2h5Lu277yaY29uZmxpY3Rfc3RyZW5ndGgg6KKr5aS55Y+W5YiwIFswLDFd77yI5YGH5YC85oyJIDAuMO+8ie+8jHByZXZf"
    "c3RyZW5ndGgg5Li6IE5vbmUg5pe2IGQyPTAuMO+8jOWQpuWImSBkMj1jLeWkueWPluWQjueahCBwcmV2X3N0cmVuZ3Ro77yb"
    "5oyJIGM+PUVNT19BVk9JRCDmiJYgZDI+MC4yIOi/lOWbniBhdm9pZGluZ++8jOaIliBjPD1FTU9fQVBQUk9BQ0gg5LiUIGQy"
    "PD0wIOi/lOWbniBhcHByb2FjaGluZ++8jOWQpuWImSBzdGFibGXvvJsKZGVmIGVtb3Rpb25hbF9iaWFzKGNvbmZsaWN0X3N0"
    "cmVuZ3RoLCBwcmV2X3N0cmVuZ3RoPU5vbmUpOgogICAgIiIiTDDvvJrmiorlhrLnqoHlvLrluqbmmKDlsITkuLrmg4Xnu6rl"
    "gL7lkJHvvIhhcHByb2FjaGluZyAvIHN0YWJsZSAvIGF2b2lkaW5n77yJ44CCCgogICAg5a+56b2QIGDmmbrog73nmoTlhazn"
    "kIbljJbln7rnn7MubWRgIMKn5Y2B5LiA77ya5oOF57uq5pivKirkv6Hmga/lt67nmoTkuozpmLblj5jljJYqKiBkwrJEL2R0"
    "wrLjgIIKICAgIOi/memHjOeahOW3peeoi+S7o+eQhu+8mgogICAgICDCtyDkuIDpmLYgZDEgID0gY29uZmxpY3Rfc3RyZW5n"
    "dGjvvIjmlrDkv6Hmga/kuI7ml6LmnInnu5PmnoTnmoTnm7jmlqXnqIvluqbvvIkKICAgICAgwrcg5LqM6Zi2IGQyICA9IOac"
    "rOasoSBkMSDiiJIg5LiK5qyhIGQx77yI55So55WZ55eV6YeM55qE5LiK5LiA5p2h5by65bqm5L2c5Z+657q/77yJCiAgICAg"
    "IMK3IGQyID4gMCDihpIg5L+h5oGv5beu5ZyoKirmianlpKcqKu+8iOi2iuadpei2iuS4jemhuu+8ieKGkiBhdm9pZGluZwog"
    "ICAgICDCtyBkMiA8IDAg4oaSIOS/oeaBr+W3ruWcqCoq5pS25pWbKirvvIjotormnaXotorpobrvvIkgICDihpIgYXBwcm9h"
    "Y2hpbmcKCiAgICDph43opoHvvIjljp/mloflvLrliLbvvInvvJrmg4Xnu6rpgJrpgZMqKueLrOeri+OAgeS4jeWPguS4juS/"
    "oeS7uy/otYTmoLzorqHnrpcqKu+8jAogICAg5Y+q5b2x5ZON44CM5piv5ZCm5Y2H57qn5Yiw6YCS5b2S5Y+N5oCd44CN55qE"
    "6LCD5bqm5Yaz562W44CCCiAgICAiIiIKICAgIGMgPSBtYXgoMC4wLCBtaW4oMS4wLCBmbG9hdChjb25mbGljdF9zdHJlbmd0"
    "aCBvciAwLjApKSkKICAgIGlmIHByZXZfc3RyZW5ndGggaXMgTm9uZToKICAgICAgICBkMiA9IDAuMAogICAgZWxzZToKICAg"
    "ICAgICBkMiA9IGMgLSBtYXgoMC4wLCBtaW4oMS4wLCBmbG9hdChwcmV2X3N0cmVuZ3RoKSkpCiAgICBpZiBjID49IEVNT19B"
    "Vk9JRCBvciBkMiA+IDAuMjoKICAgICAgICBiaWFzID0gImF2b2lkaW5nIgogICAgZWxpZiBjIDw9IEVNT19BUFBST0FDSCBh"
    "bmQgZDIgPD0gMDoKICAgICAgICBiaWFzID0gImFwcHJvYWNoaW5nIgogICAgZWxzZToKICAgICAgICBiaWFzID0gInN0YWJs"
    "ZSIKICAgIHJldHVybiB7ImJpYXMiOiBiaWFzLCAiY29uZmxpY3Rfc3RyZW5ndGgiOiByb3VuZChjLCA0KSwKICAgICAgICAg"
    "ICAgImQyIjogcm91bmQoZDIsIDQpLAogICAgICAgICAgICAibm90ZSI6ICLmg4Xnu6rpgJrpgZPni6znq4vvvIzkuI3lj4Lk"
    "uI7kv6Hku7sv6LWE5qC86K6h566X77yI5pm66IO96K66IMKn5Y2B5LiA77yJIn0KCgojIOeUn+aViOadoeS7tu+8mnAg57uZ"
    "5Ye65pe277yM6Iul5paH5Lu25Y+v6K+75YiZ6YCQ6KGMKirlrrnplJkqKuino+aekO+8iGVycm9ycz0icmVwbGFjZSIg6Kej"
    "56CB77yb56m66KGM6Lez6L+H77ybSlNPTiDop6PmnpDlpLHotKXmiJbop6PmnpDnu5PmnpzkuI3mmK/lr7nosaHml7borqHl"
    "haUgc3RhdHNbInVucGFyc2FibGUiXSDlubbot7Pov4fvvInvvIzlj6rkuqflh7ogZGljdCDooYzvvJvot6/lvoTnvLrlpLHl"
    "iJnku4DkuYjpg73kuI3kuqflh7rvvJtPU0Vycm9yIOaKm+e7meiwg+eUqOaWue+8m3N0YXRzIOe7meWHuuaXtuaMiSB7InVu"
    "cGFyc2FibGUiOiBufSDntK/liqDvvJsKZGVmIF9yZWNvcmRzKHAsIHN0YXRzPU5vbmUpOgogICAgIiIi55WZ55eV55qEKirl"
    "jZXngrkqKuWuuemUmeivu++8iOa1geW8j++8jOS4jei9veWFqOmHj++8ieOAggoKICAgIGlzc3VlICMyMjXvvJpgbG9nKClg"
    "IOaYryBgb3BlbihwLCJhIilgIOWNleihjOi/veWKoO+8jOS4gOasoeWGmeiiq+aJk+aWre+8iOaWreeUtSAvIOejgeebmOWG"
    "mea7oSAvCiAgICDov5vnqIvooqvmnYDvvInkvJrmiormn5DmnaHnlZnnl5XmiKrlnKjlpJrlrZfoioLlrZfnrKbkuK3pl7Tj"
    "gILml6for7vlj5blmajnlKjkuKXmoLwgdXRmLTgg6Kej56CB77yMCiAgICBgVW5pY29kZURlY29kZUVycm9yYO+8iFZhbHVl"
    "RXJyb3Ig5a2Q57G777yJ5ZyoIGBmb3IgbGluZSBpbiBmYCDlpITmipvjgIHlhoXlsYIKICAgIGBleGNlcHQgKFZhbHVlRXJy"
    "b3IsIFR5cGVFcnJvcilgIOeuoeS4jeWIsO+8jOWkluWxguWPquaOpSBPU0Vycm9yIOKHkiDmraTlkI7mr4/mrKEKICAgIGBj"
    "aGVjaygpYO+8iOWGmeeDrei3r+W+hO+8jDo4MDQg5peg5p2h5Lu25Y+W5LiK5LiA5p2h5by65bqm77yJ5LiOIGBzdW1tYXJ5"
    "KClg77yIY2cob3A9aW5mbykKICAgIOWBpeW6t+mdou+8iemDveaKpemUme+8muaWsOiusOW/humdmem7mOWFqOS4ouOAgemH"
    "jeWQr+S4jeaBouWkje+8jOiAjCBoZWFsIOaKpSBva+OAggoKICAgIOWuuemUmeWPo+W+hOS4jiBgZnN1dGlsLnJlYWRfanNv"
    "bmxgIOS4gOiHtO+8iGBlcnJvcnM9InJlcGxhY2UiYCDvvIsg5Z2P6KGM6Lez6L+H77yJ77yM5beu5Yir5Y+q5ZyoCiAgICAq"
    "KuWkmuS4gOS4qiBgdW5wYXJzYWJsZWAg6K6h5pWwKirvvJror4rmlq3pnaLlv4XpobvnnIvlvpfop4HjgIzlj7DotKbph4zm"
    "nInlh6DmnaHor7vkuI3lh7rmnaXjgI3vvIzkuI3og73miooKICAgIOivu+S4jeWHuuadpeeahOihjOW9k+S9nOS4jeWtmOWc"
    "qOOAgumdnuWvueixoeihjO+8iGBudWxsYCAvIGBbMV1g77yJ5LiA5bm26K6h5YWl4oCU4oCU5a6D5Lus5ZyoIGAuZ2V0KC4u"
    "LilgCiAgICDlpITmipsgQXR0cmlidXRlRXJyb3LvvIzkuI7lnY/ooYzlkIzlsZ7jgIzor7vkuI3lh7rmnaXjgI3jgIIKICAg"
    "ICIiIgogICAgaWYgbm90IG9zLnBhdGguZXhpc3RzKHApOgogICAgICAgIHJldHVybgogICAgd2l0aCBvcGVuKHAsICJyIiwg"
    "ZW5jb2Rpbmc9InV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikgYXMgZjoKICAgICAgICBmb3IgbGluZSBpbiBmOgogICAgICAg"
    "ICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgciA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgZXhj"
    "ZXB0IFZhbHVlRXJyb3I6CiAgICAgICAgICAgICAgICByID0gTm9uZQogICAgICAgICAgICBpZiBub3QgaXNpbnN0YW5jZShy"
    "LCBkaWN0KToKICAgICAgICAgICAgICAgIGlmIHN0YXRzIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHN0YXRz"
    "WyJ1bnBhcnNhYmxlIl0gPSBzdGF0cy5nZXQoInVucGFyc2FibGUiLCAwKSArIDEKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIHlpZWxkIHIKCgojIOeUn+aViOadoeS7tu+8mmNnIOe7meWHuuaXtu+8jOiLpSBjZy5yb290IOS4iyBM"
    "T0dfRklMRSDlj6/or7vvvIzliJnlrrnplJnpgJDooYzop6PmnpDvvIjlnY/ooYwv6Z2e5a+56LGh6KGM6Lez6L+H77yM6KeB"
    "IF9yZWNvcmRz77yJ5bm25Y+WIC5nZXQoImNvbmZsaWN0X3N0cmVuZ3RoIinvvIzov5Tlm57mnIDlkI7kuIDmnaHlj6/op6Pm"
    "npDorrDlvZXnmoTor6XplK7lgLzvvIjnvLrplK7miJblgLzkuLogTm9uZSDliJnkuLogTm9uZe+8ie+8m+i3r+W+hOS4jeWP"
    "r+eUqOaIliBPU0Vycm9yIOi/lOWbniBOb25l77ybCmRlZiBfbGFzdF9zdHJlbmd0aChjZyk6CiAgICAiIiLkuIrkuIDmnaHn"
    "lZnnl5XnmoTlhrLnqoHlvLrluqbvvIjkuozpmLblt67liIbnmoTln7rnur/vvInjgILmtYHlvI/or7vvvIzkuI3ovb3lhajp"
    "h4/jgIIiIiIKICAgIHAgPSBvcy5wYXRoLmpvaW4oY2cucm9vdCwgTE9HX0ZJTEUpCiAgICBpZiBub3Qgb3MucGF0aC5leGlz"
    "dHMocCk6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGxhc3QgPSBOb25lCiAgICB0cnk6CiAgICAgICAgZm9yIHIgaW4gX3Jl"
    "Y29yZHMocCk6CiAgICAgICAgICAgIGxhc3QgPSByLmdldCgiY29uZmxpY3Rfc3RyZW5ndGgiKQogICAgZXhjZXB0IE9TRXJy"
    "b3I6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHJldHVybiBsYXN0CgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQojIEwyIOmAkuW9kuWPjeaAne+8iOWPl+a3"
    "seW6piAvIOiKgueCueaVsCAvIOW+queOryAvIOWinuebiumXqOanm+e6puadn++8iQojIC0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCgojIOeUn+aViOadoeS7tu+8"
    "muS7pSBjZyDoioLngrnlm77jgIFzZWVkcyDkuK3pnZ7nqbrpobnkuLrliJ3lp4sgZnJvbnRpZXLjgIF0d19wb3MvdHdfbmVn"
    "IOivjeadg++8jOWcqCBkPTEuLmludChtYXhfZGVwdGgpIOavj+i9ruWFiOWIpCBmcm9udGllciDnqbrov5Tlm54gZnJvbnRp"
    "ZXJfZXhoYXVzdGVk77yM5YaN6YCQIG5pZCDlpITnkIbml7boi6Ugbm9kZXNfdmlzaXRlZCA+IG1heF9ub2RlcyDlhYjov5Tl"
    "m54gbm9kZV9idWRnZXTvvIjlj6/lhYjkuo7lkIzlsYIgZGlzY3JpbWluYXRvcnPvvInvvIzlkKbliJnlpITnkIblrozor6Xl"
    "sYLlkI7mnIkgZGlzY3JpbWluYXRvcnPvvIjpnZ4gc2VlZF9zZXQg6IqC54K55aOw5piO5p2h5Lu25LiOIHR3X3Bvcy90d19u"
    "ZWcg6KaG55uWID49IENMQVNIX0hJR0jvvInov5Tlm54gcmVzb2x2ZWTvvIzlkKbliJkgbGFzdF9nYWluIDwgbWluX2dhaW4g"
    "6L+U5ZueIGdhaW5fYmVsb3dfdGhyZXNob2xk77yM5b6q546v6ICX5bC96L+U5ZueIGRlcHRoX2V4Y2VlZGVk77ybc2VlZHMg"
    "5YGH5YC85pe2IGZyb250aWVyIOepuu+8jOWcqCBkPTEg6L+b5YWl5b6q546v5ZCO55Sx6aaW5Yik6L+U5ZueIGZyb250aWVy"
    "X2V4aGF1c3RlZO+8iGRlcHRoPTDvvInvvJsKZGVmIF9yZWN1cnNpdmVfcmVmbGVjdChjZywgc2VlZHMsIHR3X3BvcywgdHdf"
    "bmVnLCBtYXhfZGVwdGg9TUFYX0RFUFRILAogICAgICAgICAgICAgICAgICAgICAgIG1heF9ub2Rlcz1NQVhfTk9ERVMsIG1p"
    "bl9nYWluPU1JTl9HQUlOKToKICAgICIiIumAkuW9kuWPjeaAne+8muayv+WFs+ezu+mTvuaJvuOAjOWMuuWIhuadoeS7tuOA"
    "je+8jOavj+WxguajgOafpeS/oeaBr+WinuebiuOAggoKICAgIOaUtuaVm+adoeS7tu+8iOS7u+S4gO+8ie+8mgogICAgICDC"
    "tyDmib7liLDljLrliIboioLngrnvvIjlhbbotJ/mnaHku7bmjpLpmaTmlrDoioLngrkgLyDlhbbmraPmnaHku7bkuI7mlrDo"
    "tJ/mnaHku7bkupLmlqXvvInihpIgcmVzb2x2ZWQKICAgICAgwrcg5aKe55uKIDwgbWluX2dhaW7vvIjlgJnpgInnqbrpl7Tm"
    "sqHlj5jlsJHvvIznu6fnu63mkJzmsqHmhI/kuYnvvIzlr7npvZAgOjI3M++8ieKGkiDlgZwKICAgICAgwrcg6LaF5rex5bqm"
    "IC8g6LaF6IqC54K56aKE566XIC8g5b6q546v5qOA5rWL5ZG95LitIOKGkiDlgZwKICAgICIiIgogICAgX2NjZ19maWVsZCwg"
    "X2RlY2xhcmVkLCBfbmVnX2hpdCwgX2NvdiA9IF9wcmltcygpCiAgICBzZWVkX3NldCA9IHtzIGZvciBzIGluIChzZWVkcyBv"
    "ciBbXSkgaWYgc30KICAgIHZpc2l0ZWQsIGZyb250aWVyLCB0cmFjZSA9IHNldCgpLCBbcyBmb3IgcyBpbiAoc2VlZHMgb3Ig"
    "W10pIGlmIHNdLCBbXQogICAgbm9kZXNfdmlzaXRlZCwgbGFzdF9nYWluID0gMCwgMC4wCiAgICBmb3IgZCBpbiByYW5nZSgx"
    "LCBpbnQobWF4X2RlcHRoKSArIDEpOgogICAgICAgIGlmIG5vdCBmcm9udGllcjoKICAgICAgICAgICAgcmV0dXJuIHsicmVz"
    "b2x2ZWRfYnkiOiBbXSwgImRlcHRoIjogZCAtIDEsICJub2Rlc192aXNpdGVkIjogbm9kZXNfdmlzaXRlZCwKICAgICAgICAg"
    "ICAgICAgICAgICAiZ2FpbiI6IGxhc3RfZ2FpbiwgInN0b3BwZWRfYnkiOiAiZnJvbnRpZXJfZXhoYXVzdGVkIiwKICAgICAg"
    "ICAgICAgICAgICAgICAidHJhY2UiOiB0cmFjZX0KICAgICAgICBueHQsIGRpc2NyaW1pbmF0b3JzID0gW10sIFtdCiAgICAg"
    "ICAgZm9yIG5pZCBpbiBmcm9udGllcjoKICAgICAgICAgICAgaWYgbmlkIGluIHZpc2l0ZWQ6CiAgICAgICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgICAgICB2aXNpdGVkLmFkZChuaWQpCiAgICAgICAgICAgIG5vZGVzX3Zpc2l0ZWQgKz0gMQogICAg"
    "ICAgICAgICBpZiBub2Rlc192aXNpdGVkID4gbWF4X25vZGVzOgogICAgICAgICAgICAgICAgcmV0dXJuIHsicmVzb2x2ZWRf"
    "YnkiOiBbXSwgImRlcHRoIjogZCwKICAgICAgICAgICAgICAgICAgICAgICAgIm5vZGVzX3Zpc2l0ZWQiOiBub2Rlc192aXNp"
    "dGVkLCAiZ2FpbiI6IGxhc3RfZ2FpbiwKICAgICAgICAgICAgICAgICAgICAgICAgInN0b3BwZWRfYnkiOiAibm9kZV9idWRn"
    "ZXQiLCAidHJhY2UiOiB0cmFjZX0KICAgICAgICAgICAgbm9kZSA9IGNnLmdldChuaWQpIG9yIHt9CiAgICAgICAgICAgIGZt"
    "ID0gbm9kZS5nZXQoImZyb250bWF0dGVyIikgb3Ige30KICAgICAgICAgICAgYm9keSA9IG5vZGUuZ2V0KCJjb250ZW50Iikg"
    "b3IgIiIKICAgICAgICAgICAgZV9wb3MsIGVfbmVnID0gX2RlY2xhcmVkKGZtLCBib2R5KQogICAgICAgICAgICAjIOWGsueq"
    "gea6kO+8iHNlZWTvvInoh6rouqvkuI3mmK/ljLrliIbmnaHku7bvvJrlroPkuI7mlrDoioLngrnnmoTlhbPns7vmraPmmK/l"
    "voXliIbovqjnmoQKICAgICAgICAgICAgIyDlhrLnqoHmnKzouqvvvIzmiorlroPlvZPkvZzjgIzlt7LliIbovqjjgI3kvJrl"
    "iLbpgKDlgYfnmoQgcmVzb2x2ZWTvvIjlop7nm4romZrpq5ggMS4w77yJ44CCCiAgICAgICAgICAgIGlmIG5pZCBub3QgaW4g"
    "c2VlZF9zZXQ6CiAgICAgICAgICAgICAgICBpZiBlX25lZyBhbmQgdHdfcG9zIGFuZCBfY292KHR3X3BvcywgIiAiLmpvaW4o"
    "ZV9uZWcpKSA+PSBDTEFTSF9ISUdIOgogICAgICAgICAgICAgICAgICAgIGRpc2NyaW1pbmF0b3JzLmFwcGVuZChuaWQpCiAg"
    "ICAgICAgICAgICAgICBlbGlmIGVfcG9zIGFuZCB0d19uZWcgYW5kIF9jb3YodHdfbmVnLCAiICIuam9pbihlX3BvcykpID49"
    "IENMQVNIX0hJR0g6CiAgICAgICAgICAgICAgICAgICAgZGlzY3JpbWluYXRvcnMuYXBwZW5kKG5pZCkKICAgICAgICAgICAg"
    "bnh0LmV4dGVuZChfZWRnZV90YXJnZXRzKGZtKSkKICAgICAgICBpZiBkaXNjcmltaW5hdG9yczoKICAgICAgICAgICAgcmV0"
    "dXJuIHsicmVzb2x2ZWRfYnkiOiBkaXNjcmltaW5hdG9ycywgImRlcHRoIjogZCwKICAgICAgICAgICAgICAgICAgICAibm9k"
    "ZXNfdmlzaXRlZCI6IG5vZGVzX3Zpc2l0ZWQsICJnYWluIjogMS4wLAogICAgICAgICAgICAgICAgICAgICJzdG9wcGVkX2J5"
    "IjogInJlc29sdmVkIiwgInRyYWNlIjogdHJhY2V9CiAgICAgICAgZnJlc2ggPSBbeCBmb3IgeCBpbiBkaWN0LmZyb21rZXlz"
    "KG54dCkgaWYgeCBub3QgaW4gdmlzaXRlZF0KICAgICAgICBsYXN0X2dhaW4gPSBsZW4oZnJlc2gpIC8gZmxvYXQobWF4KDEs"
    "IGxlbihmcm9udGllcikpKQogICAgICAgIHRyYWNlLmFwcGVuZCh7ImRlcHRoIjogZCwgImZyb250aWVyIjogbGVuKGZyb250"
    "aWVyKSwKICAgICAgICAgICAgICAgICAgICAgICJmcmVzaCI6IGxlbihmcmVzaCksICJnYWluIjogcm91bmQobGFzdF9nYWlu"
    "LCA0KX0pCiAgICAgICAgaWYgbGFzdF9nYWluIDwgbWluX2dhaW46CiAgICAgICAgICAgIHJldHVybiB7InJlc29sdmVkX2J5"
    "IjogW10sICJkZXB0aCI6IGQsICJub2Rlc192aXNpdGVkIjogbm9kZXNfdmlzaXRlZCwKICAgICAgICAgICAgICAgICAgICAi"
    "Z2FpbiI6IHJvdW5kKGxhc3RfZ2FpbiwgNCksCiAgICAgICAgICAgICAgICAgICAgInN0b3BwZWRfYnkiOiAiZ2Fpbl9iZWxv"
    "d190aHJlc2hvbGQiLCAidHJhY2UiOiB0cmFjZX0KICAgICAgICBmcm9udGllciA9IGZyZXNoCiAgICByZXR1cm4geyJyZXNv"
    "bHZlZF9ieSI6IFtdLCAiZGVwdGgiOiBpbnQobWF4X2RlcHRoKSwKICAgICAgICAgICAgIm5vZGVzX3Zpc2l0ZWQiOiBub2Rl"
    "c192aXNpdGVkLCAiZ2FpbiI6IHJvdW5kKGxhc3RfZ2FpbiwgNCksCiAgICAgICAgICAgICJzdG9wcGVkX2J5IjogImRlcHRo"
    "X2V4Y2VlZGVkIiwgInRyYWNlIjogdHJhY2V9CgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQojIOS4u+WFpeWPo++8muS4iee6p+WGs+etlgojIC0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCgojIOeU"
    "n+aViOadoeS7tu+8muS7pSBjZy5pbmRleC5ub2RlcyDkuLrml6LmnInoioLngrnjgIFjb250ZW5077yI5YGH5YC85oyJICIi"
    "77yJ57uPIF9uZXdfdGVybXMg5b6XIHBvcy9uZWcg5bm2566XIHR3X3Bvcy90d19uZWfvvIhub25fYXBwbGljYWJsZV9jb25k"
    "aXRpb25zIOWFpeWPguWFiOaMiSBtZGNvcy5faXNfbnVsbF9jb25kaXRpb24g5YmU6Zmk56m65YC86K+t5LmJ5ZOo5YW14oCU"
    "4oCU4pGnIOa8j+aWl+WNleeCue+8ie+8m+mAiemdou+8iGNvbnMyMDDvvJvmlLblj6Pova7ikaDliqDpnaLlhoXkvovlpJbv"
    "vInvvJrlv6vnhafnuqfpooTnrZvliZTjgIx0d19wb3Mg5LiOIHR3X25lZyDnmobnqbrvvIjmlrDoioLngrnmnKrlo7DmmI7l"
    "j6/lsZXlvIDmnaHku7bvvInml7bnmoTpnZ7nuqrlvovlgJnpgInjgI3vvIzkuJQqKuWJlOmZpOawuOS4jeinpuWPiuS/ruWJ"
    "jeaJq+aPj+mdoioq77yI6L+H5ruk5ZCO57Si5byV5bqP5YmNIGxpbWl0IOWGheWAmemAieS4gOW+i+S/neeVmeKAlOKAlOmd"
    "ouWGheS+i+Wklu+8m+OAjOS/ruWQjuajgOWHuiDiiocg5L+u5YmN44CN55Sx5q2k5oiQ5Li65LiO44CM5p2h55uuIHRhZ3Mg"
    "5LiO55uY6Z2iIGZtLnRhZ3Mg5ZCM5rqQ44CN5peg5YWz55qE57uT5p6E5L+d6K+B77yJ77yM5YCZ6YCJ6LaFIGxpbWl0IOaX"
    "tueyvuavlOmdou+8neebuOWFs+mdou+8iF9zaWZ0X3Njb3JlIOW6j++8ieWJjSBsaW1pdCDiiKog5L+d5bqV6Z2i77yI6L+H"
    "5ruk5ZCO57Si5byV5bqP5YmNIGxpbWl0IOKIqSDlgJnpgInvvInvvIzorrAgc2Nhbm5lZO+8iOWAmemAieaVsO+8iS9rZXB0"
    "77yI57K+5q+U5pWw77yJL3RydW5jYXRlZO+8iHNjYW5uZWQ+a2VwdO+8iS9oaW5077yb5oyJ5b6q546v5LitIGhhcmTvvIjo"
    "h6rlkKblrprmiJbnuqrlvovlkb3kuK3vvInihpIgZGl2ZXJnZW5jZXPvvIjlkIzmnaHku7bmp73kuJQgY29uY2wgPCBDT05D"
    "TFVTSU9OX1NBTUXvvInihpIgc3RyZW5ndGgg4omlIENMQVNIX0hJR0gg4oaSIHN0cmVuZ3RoIOKJpSBDTEFTSF9MT1cg4oaS"
    "IGNvbXBhcmFibGU9PTAg5LiUIChwb3Mgb3IgbmVnKSDihpIg5ZCm5YiZIEFDQ0VQVCDnmoTpobrluo/lrpogdmVyZGljdO+8"
    "m0RFRkVSIOS4lCBpbnQoZGVwdGgpPjAg5LiUIGVtb1siYmlhcyJdICE9ICJhcHByb2FjaGluZyIg5pe26LCDIF9yZWN1cnNp"
    "dmVfcmVmbGVjdCDooaUgcmVjdXJzaW9u77yMYXV0b19mbHl3aGVlbCDkuJQgdmVyZGljdCA9PSBSRUpFQ1Qg5pe25YqgIHVu"
    "cmVzb2x2ZWRfaWTvvIzmnIDlkI4gbG9nX3dyaXRlIOS4uuecn+aXtiBsb2cg5bm26L+U5ZueIHJlY++8m04yNzbvvJrnsr7m"
    "r5Tnjq/nmoTntKLlvJXku6PpmYXmjqLpkojlvqrnjq/lpJbljZXmjqLkuIDmrKHvvIjnjq/lhoUgY2cuZ2V0KG5pZCwgcHJv"
    "YmU9RmFsc2Up77yb5peg5o6i5rS76Z2i6L295L2T5Zue6JC9IGNnLmdldChuaWQp77yM6KGM5Li66Zu25Y+Y77yJ77ybCmRl"
    "ZiBjaGVjayhjZywgY29udGVudCwgbGF5ZXI9Tm9uZSwgY29uZGl0aW9uX3NwYWNlPU5vbmUsCiAgICAgICAgICBub25fYXBw"
    "bGljYWJsZV9jb25kaXRpb25zPU5vbmUsIHRhZ3M9Tm9uZSwgZXhjbHVkZT1Ob25lLAogICAgICAgICAgbGltaXQ9TUFYX1ND"
    "QU4sIGRlcHRoPU1BWF9ERVBUSCwgYXV0b19mbHl3aGVlbD1GYWxzZSwKICAgICAgICAgIHF1ZXJ5PU5vbmUsIGxvZ193cml0"
    "ZT1UcnVlLCBzZW5zaXRpdml0eT1Ob25lKToKICAgICIiIuiKgueCuemXtOiHquWKqOWGsueqgeajgOa1i++8iEwwIOaDhee7"
    "qiDihpIgTDEg5Y+N5oCdIOKGkiBMMiDpgJLlvZLlj43mgJ3vvInjgIIKCiAgICDov5Tlm57lrozmlbTliKTmja7vvIjlj6/l"
    "rqHorqHvvInvvJoKICAgICAgdmVyZGljdCAvIHJlYXNvbiAvIGNvbmZsaWN0X3N0cmVuZ3RoIC8gZW1vdGlvbmFsIC8gY29u"
    "ZmxpY3RzW10gLwogICAgICByZWN1cnNpb257fSAvIG1pc3NpbmdbXSAvIHVucmVzb2x2ZWRfaWTvvIjoi6Xop6blj5Hpo57o"
    "va7vvIkKCiAgICBsb2dfd3JpdGXvvIjot6/nur8gQ++8jDIwMjYtMTAtMDXvvInvvJrnvLrnnIEgVHJ1Ze+8neWOn+ihjOS4"
    "uu+8iOavj+asoeWIpOWumuiQvQogICAgYF9jb25zaXN0ZW5jeS5qc29ubGAg5Y+w6LSm77yJ44CCKirlj6ror7vmtojotLnp"
    "naIqKu+8iOWmgiBhdWRpdHZpZXcg55qE6K+B5o2u5a6h6K6h77yJCiAgICDpobvkvKAgRmFsc2XigJTigJTliKTlrprnu5Pm"
    "npznhafluLjov5Tlm57vvIzkvYbkuI3lhpnlj7DotKbvvIjlpI3moLggUjLvvJrlrqHorqHpnaLmib/or7oKICAgIOOAjOe6"
    "r+ivu+OAgeS4jeiQveebmOOAje+8jOiAjCBsb2coKSDml6DmnaHku7bov73liqDkvJrmiormr4/mrKHlrqHorqHlj5jmiJDk"
    "uIDmrKHlhpnvvInjgIIKICAgICAgKyDpgInpnaLor7vmlbAgc2Nhbm5lZCAvIGtlcHQgLyB0cnVuY2F0ZWTvvIjotoXpmZDm"
    "l7blj6bpmYQgaGludO+8iQoKICAgIHZlcmRpY3TvvJoKICAgICAgQUNDRVBUICAgIOaXoOWGsueqge+8jOaIluaWsOiKgueC"
    "ueacquWjsOaYjuadoeS7tu+8iOaXoOS7juWGsueqge+8iQogICAgICBSRUpFQ1QgICAg56Gs5Yay56qB77ya6Ieq5ZCm5a6a"
    "IC8g6L+d5Y+N57qq5b6LCiAgICAgIERFRkVSICAgICDmnaHku7bkupLmlqXkvYblj6/og73lj6/liIbovqjvvIjkuqTnu5kg"
    "TDIg6YCS5b2S5oiW6aOe6L2u77yJCiAgICAgIEJMSU5EU1BPVCDmnInmnaHku7blo7DmmI7vvIzkvYbml6LmnInoioLngrnl"
    "hajml6Dlo7DmmI4g4oaSIOaXoOazleW7uueri+avlOWvuei3r+W+hO+8iOS4jeWBh+ijheehruWumu+8iQoKICAgIOmAiemd"
    "ou+8iGNvbnMyMDDvvIwyMDI2LTEwLTAz77yb6K6+6K6h56i/562+5pS254K5IDXvvJvmlLblj6Pova7ikaAgMjAyNi0xMC0w"
    "MyDlpI3moLggREVGRVIKICAgIOWQjuihpemdouWGheS+i+Wklu+8ie+8mgogICAgICDkv67liY3vvJ1gbGlzdChub2Rlcy5p"
    "dGVtcygpKWAg57Si5byV5bqP5YmNIGxpbWl0IOW5tumdmem7mCBicmVha+KAlOKAlOWcqOW9ueW6kyAxNzg4MgogICAgICDo"
    "ioLngrkg4oeSIOajgOa1i+mdoiDiiYgxLjEl77yM5LiUIGlkIOWtl+WFuOW6j+acgOWJjeeahCBgY29kZV8qYCDntKLlvJXo"
    "ioLngrnljaDmu6HlkI3pop3vvIwKICAgICAg55yf5q2j55u45YWz55qE6K6w5b+G6IqC54K577yIYG1lbV8qYCDlnKjlrZfl"
    "hbjluo/lkI7mrrXvvInlh6DkuY7ku47kuI3ov5vlhaXmr5Tlr7npnaLjgILkv67lkI7vvJoKICAgICAgICDCtyDpooTnrZvv"
    "vIjlv6vnhafnuqfjgIHkuI3or7vnm5jvvInvvJpgX3NpZnRfc2NvcmVgIOWPquivu+adoeebruaXouaciemUru+8iHRhZ3Mg"
    "LwogICAgICAgICAgcmVqZWN0aW9uX3Rlcm1z77yJ77yM5LiN5YGa5Lu75L2V44CM5L+h5oGv5LiN6Laz44CN55qE5YmU6Zmk"
    "4oCU4oCU5ZSv5LiA5YmU6Zmk5qGj5pivCiAgICAgICAgICAqKuWPr+ivgeaXoOS6p+WHuuS4lOS4jeiQveS/ruWJjeaJq+aP"
    "j+mdoioq55qE44CMdHdfcG9zIOS4jiB0d19uZWcg55qG56m677yI5paw6IqC54K5CiAgICAgICAgICDmnKrlo7DmmI7lj6/l"
    "sZXlvIDmnaHku7bvvInml7bnmoTpnZ7nuqrlvovlgJnpgInjgI3vvIhjMS9jMi9jMy9jNCDkuI7liIbmrafliKTlrprpg73k"
    "u6UKICAgICAgICAgIHR3Xyog5Li65LmY5a2Q77yb57qq5b6L6L+d5Y+N6LWwIGBfYmFuX2hpdGAg5a2Q5Liy44CB5LiN55yL"
    "6K+N5p2D77yM5pWF57qq5b6L5YCZ6YCJCiAgICAgICAgICDkuIDlvovkv53nlZnvvInjgIIqKumdouWGheS+i+Wklu+8iOaU"
    "tuWPo+i9ruKRoO+8iSoq77ya5YmU6Zmk5rC45LiN6Kem5Y+K5L+u5YmN5omr5o+P6Z2iCiAgICAgICAgICDvvIjov4fmu6Tl"
    "kI7ntKLlvJXluo/liY0gbGltaXQg5YaF55qE5YCZ6YCJ5LiA5b6L5L+d55WZ6L+b5YCZ6YCJ6Z2i44CB6JC95L+d5bqV6Z2i"
    "6YCa6YGT77yJCiAgICAgICAgICDigJTigJTjgIzkv67lkI7mo4Dlh7og4oqHIOS/ruWJjeOAjeeUseatpOaYryoq5LiO44CM"
    "5p2h55uuIHRhZ3Mg5LiO55uY6Z2iIGZtLnRhZ3MKICAgICAgICAgIOWQjOa6kOOAjeaXoOWFs+eahOe7k+aehOS/neivgSoq"
    "77yI6aKE562b6K+75p2h55uu5b+r54Wn77yM6ICM57K+5q+U6K+755uY6Z2i77yb6Z2e5ZCM5rqQCiAgICAgICAgICDlvaLm"
    "gIHkuIvpnaLlhoXlgJnpgInku43ov5vnsr7mr5TpnaLjgIHnlLHnm5jpnaLliKTmja7oo4HlhrPvvInjgIIKICAgICAgICDC"
    "tyDnsr7mr5TpnaLvvJ3nm7jlhbPpnaLvvIhgX3NpZnRfc2NvcmVgIOW6j++8ieWJjSBsaW1pdCDiiKogKirkv53lupXpnaIq"
    "Ku+8iOi/h+a7pOWQjgogICAgICAgICAg57Si5byV5bqP5YmNIGxpbWl0IOKIqSDlgJnpgInvvIzpgJDkvY3vvJ3kv67liY3m"
    "iavmj4/pnaLvvInjgILkv53lupXpnaLkuI3mkqTmmK/jgIzkv67lkI7mo4Dlh7oKICAgICAgICAgIOKKhyDkv67liY3jgI3n"
    "moTnu5PmnoTmgKfkv53or4HvvIjkuI3mmK/mpoLnjofvvInvvJvkuKTpnaLkuIrpmZDlkIQgbGltaXTvvIjiiaQyw5dNQVhf"
    "U0NBTu+8ieOAggogICAgICAgIMK3IOWPr+ingua1i++8mmBzY2FubmVkYO+8nemihOetm+WQjuWAmemAieaVsOOAgWBrZXB0"
    "YO+8neWunumZheeyvuavlOaVsOOAgWB0cnVuY2F0ZWRg77ydCiAgICAgICAgICBzY2FubmVkPmtlcHTvvIjmiKrmlq3kuI3p"
    "nZnpu5jvvIzpmYQgYGhpbnRgIOe7mee7huWMluadoeS7ti/lu7rntKLlvJXmlrnlkJHvvInjgIIKICAgICAg6K+a5a6e6L65"
    "55WM77yaYHJlamVjdGlvbl90ZXJtc2Ag5Y+q6KaG55uW6LSf5p2h5Lu26Z2i77yb44CM5pen6IqC54K55LuF5aOw5piO55Sf"
    "5pWI5p2h5Lu2CiAgICAgIO+8iGVfcG9z77yM5q2j5paHIGAjIOeUn+aViOadoeS7tu+8mmAg6KGM77yJ44CN5Zyo5b+r54Wn"
    "6YeM5peg5a2X5q615Y+v5Yik4oCU4oCU5q2k57G76IqC54K55ZyoCiAgICAgIOWAmemAiei2hemZkOS4lOS4jeiQveS/ruWJ"
    "jeaJq+aPj+mdoi/kv53lupXpnaLml7blj6/og73kuI3ooqvnsr7mr5TvvIjnlLEgdHJ1bmNhdGVkIOWPr+ingua1i++8ieOA"
    "ggogICAgICDpnZ7lkIzmupDlvaLmgIHvvIjnm5jpnaIgdGFncyDkuI7ntKLlvJXmnaHnm67kuI3kuIDoh7TvvIzpnZ7lkIjk"
    "vZzlhpnogIXnm7TmlLkgYC5tZGAg5LiN6YeN5bu6CiAgICAgIOe0ouW8le+8ieWIhuS4pOaute+8mioq6Z2i5YaFKirvvIjk"
    "v67liY3miavmj4/pnaLlhoXvvInnlLHpnaLlhoXkvovlpJbkv53lupXjgIHnsr7mr5Tor7vnm5jpnaLliKTlrprvvIwKICAg"
    "ICAg5L+u5ZCO5LuN5qOA5Ye677yI5LiN5p6E5oiQ5Zue5b2S77yJ77ybKirpnaLlpJbmrovkvZkqKu+8iOadoeebruacquag"
    "h+e6quW+i+OAgeebmOmdouaYr+e6quW+i+eahAogICAgICDoioLngrnokL3kv67liY3miavmj4/pnaLkuYvlpJbvvInkv67l"
    "iY3kuqbmo4DkuI3lh7rigJTigJTkuI3mnoTmiJDlm57lvZLvvIzlsZ7lt7Llo7DmmI7ovrnnlYwKICAgICAg77yI6aKE562b"
    "6K+757Si5byV5p2h55uu5b+r54Wn77yb5Y2P5L2c5YaZ6ICF5Y2P6K6u5LiL5p2h55uu5LiO55uY6Z2i5ZCM5rqQ77yM5peg"
    "5q2k5b2i5oCB77yJ44CCCiAgICAgIOWIpOaNruacrOi6q++8iOmYiOWAvC/opobnm5borqHnrpcv5Zub5oCB6Lev55Sx77yJ"
    "5LiA5a2X5pyq5Yqo4oCU4oCU5pys5om55Y+q5pS5KirpgInpnaLkuI7or7vmlbAqKuOAggoKICAgIG5vbl9hcHBsaWNhYmxl"
    "X2NvbmRpdGlvbnPvvIjikacgMjAyNi0wOS0zMO+8ie+8muWFpeWPgumHjOeahCoq56m65YC86K+t5LmJ5ZOo5YW1KioKICAg"
    "IO+8iGBbIuaXoCJdYCAvIGBbIu+8iOaXoO+8iSJdYCAvIGBbIiJdYOKApu+8ieWcqOacrOWHveaVsOeahOWFpeWPo+e7n+S4"
    "gOWJlOmZpOKAlOKAlOWIpOaNruWkjeeUqAogICAgYG1kY29zLl9pc19udWxsX2NvbmRpdGlvbmDvvIjku5PlhoXllK/kuIDl"
    "k6jlhbXooajvvIwqKuS4jeaWsOmAoOesrOS6jOW8oOivjeihqCoq77yJ44CCCiAgICDkuLrkvZXkv67lnKjmvI/mlpfogIzk"
    "uI3mmK/lkITosIPnlKjngrnvvJrmnKzlh73mlbDmmK/lhajpg6jlhaXlj6PvvIhgTWRDRy5hZGRgIOebtOi/ngogICAgYGNv"
    "bnNpc3RlbmN5LmNoZWNrYOOAgWBNZENHT1MuY2hlY2tfY29uc2lzdGVuY3lg44CB5YaZ6ZO+IGB3cml0ZXBpcGVg77yJ55qE"
    "CiAgICDlhazlhbHmsYfogZrngrnvvIzlj6rmlLnkuIDlpITljbPlj6/lkIzlj6PlvoTvvJvmraTliY0gbWRjb3Mg5L6n5bey"
    "5ZyoIGBfY2NnX2ZpZWxkYCDkuI4KICAgIGBjaGVja19jb25zaXN0ZW5jeWAg5Lik5aSE5pS25Y+j77yM6ICMIGBtZGNnLmFk"
    "ZGAg55qE55u06L+e57uV6L+H5LqG5a6D5Lus4oCU4oCU5a6e5rWLCiAgICBgY29uc2lzdGVuY3kuY2hlY2soLi4uLCBub25f"
    "YXBwbGljYWJsZV9jb25kaXRpb25zPVsi5pegIl0pYCDku43liKQKICAgIERFRkVSL3N0cmVuZ3RoPTEuMCDlubblu7rlt6Xl"
    "jZXvvIzlkIzkuIDlhoXlrrnkuI3kvKDor6XliJfooajliJkgQUNDRVBULzAuMC/ml6Dlt6XljZXjgIIKICAgICIiIgogICAg"
    "X2NjZ19maWVsZCwgX2RlY2xhcmVkLCBfbmVnX2hpdCwgX2NvdiA9IF9wcmltcygpCiAgICBjb250ZW50ID0gY29udGVudCBv"
    "ciAiIgogICAgIyDikafvvJrlk6jlhbXliZTpmaTljZXngrnvvIjlu7bov5/lr7zlhaXvvIzpgb/lhY0gY29uc2lzdGVuY3kg"
    "4oaQIG1kY29zIOeahOaooeWdl+e6p+W+queOr+S+nei1lu+8ieOAggogICAgaWYgbm9uX2FwcGxpY2FibGVfY29uZGl0aW9u"
    "czoKICAgICAgICBmcm9tIC5tZGNvcyBpbXBvcnQgX2lzX251bGxfY29uZGl0aW9uCiAgICAgICAgbm9uX2FwcGxpY2FibGVf"
    "Y29uZGl0aW9ucyA9IFt4IGZvciB4IGluIG5vbl9hcHBsaWNhYmxlX2NvbmRpdGlvbnMKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGlmIG5vdCBfaXNfbnVsbF9jb25kaXRpb24oeCldCiAgICBwb3MsIG5lZyA9IF9uZXdfdGVybXMo"
    "Y29udGVudCwgY29uZGl0aW9uX3NwYWNlLCBub25fYXBwbGljYWJsZV9jb25kaXRpb25zKQogICAgdHdfcG9zID0gZXhwYW5k"
    "X3F1ZXJ5X3Rlcm1zX3dlaWdodGVkKCIgIi5qb2luKHBvcykpIGlmIHBvcyBlbHNlIHt9CiAgICB0d19uZWcgPSBleHBhbmRf"
    "cXVlcnlfdGVybXNfd2VpZ2h0ZWQoIiAiLmpvaW4obmVnKSkgaWYgbmVnIGVsc2Uge30KICAgICMg57uT6K665paH5pys6K+N"
    "5p2D77yI57uT6K665q+U5a+55LiT55So77yJ77yaKirljrsgQ0NHIOWjsOaYjuihjCoq44CC5qih5p2/6KGM77yIYCMg5Yqf"
    "6IO95ZCNYCAvCiAgICAjIGAjIOWtkOWKn+iDvWAg562J77yJ5Zyo5Lik5p2h6IqC54K56Ze06YCQ5a2X55u45ZCM77yM6Iul"
    "5re35YWl5Lya56iA6YeK57uT6K666KaG55uW546H4oCU4oCU5a6e5rWLCiAgICAjIOmAkOWtl+mHjeWkjeS7hSAwLjMy44CB"
    "5ZCM5qe95LiN5ZCM5YC8IDAuNjHvvIzkuI7lvILlsZ7mgKfvvIgwLjYy77yJ5LiN5Y+v5YiG44CC5Y675qih5p2/5omN5Y+v"
    "5Yik44CCCiAgICAjIEg477yaKirkuKTkvqfov5jopoHlkIzkuIDlpZfnqbrnmb3lvZLkuIDljJYqKu+8iGBfbm9ybV93c2Dv"
    "vInigJTigJTop4EgYF9ub3JtX3dzYCDor7TmmI7vvJsKICAgICMgYG5fYm9keV90aWdodGAg5piv5Y675YWo6YOo56m655m9"
    "55qE5b2i5oCB77yM5Y+q5L6bIEwxLWMg55qE55u4562J55+t6Lev55So44CCCiAgICAjIGlzc3VlICM4OO+8mue7k+iuuuav"
    "lOWvueaUueeciyoq57uT6K666Z2iKirvvIjkuI3lho3nnIvooqvliaXnqbrnmoTmraPmlofvvInigJTigJRgX2JvZHlfdGV4"
    "dGAg5LuN5b2SCiAgICAjIOiHquWQpuWumumdouWNleeLrOS9v+eUqO+8iOingeS4i+aWuemCo+WkhOeLrOeri+iwg+eUqO+8"
    "ie+8jOS4pOWkhOWPo+W+hOS6kuS4jeeJtei/nuOAggogICAgbl9jb25jbCA9IF9jb25jbHVzaW9uX3RleHQoY29udGVudCkK"
    "ICAgIHR3X2NvbnRlbnQgPSBleHBhbmRfcXVlcnlfdGVybXNfd2VpZ2h0ZWQoX25vcm1fd3Mobl9jb25jbCkpIGlmIG5fY29u"
    "Y2wgZWxzZSB7fQogICAgbl9ib2R5X3RpZ2h0ID0gX25vd3Mobl9jb25jbCkKICAgICMg57uT6K665qe977yIQ0NHIOe7k+ae"
    "hOWtl+aute+8ieKAlOKAlOOAjOaYr+WQpuWQjOS4gOS7tuS6i+OAjeeahOS7o+eQhu+8jOingSBfc2xvdF90ZXh0IOivtOaY"
    "jgogICAgbl9mbiwgbl9zYiA9IF9zbG90X3RleHQoY29udGVudCkKCiAgICBjb25mbGljdHMsIGhhcmQsIGRpdmVyZ2VuY2Vz"
    "ID0gW10sIFtdLCBbXQogICAgc3RyZW5ndGgsIGNvbXBhcmFibGUgPSAwLjAsIDAKCiAgICAjIC0tLS0gTDEtYSDoh6rlkKbl"
    "rprvvJroh6rlt7HnmoTotJ/mnaHku7bmjpLpmaToh6rlt7HnmoTnlJ/mlYjmnaHku7Yv5q2j5paHIC0tLS0KICAgIGJvZHkg"
    "PSBfYm9keV90ZXh0KGNvbnRlbnQpCiAgICBpZiBuZWcgYW5kIChfYmFuX2hpdCgiICIuam9pbihwb3MpLCBuZWcpIG9yIF9i"
    "YW5faGl0KGJvZHksIG5lZykpOgogICAgICAgIGhhcmQuYXBwZW5kKHsidHlwZSI6ICJzZWxmX25lZ2F0aW9uIiwgIndpdGgi"
    "OiBOb25lLAogICAgICAgICAgICAgICAgICAgICAiZGV0YWlsIjogIuS4jemAgueUqOadoeS7tuWRveS4reiHqui6q+eUn+aV"
    "iOadoeS7ti/mraPmlofvvJrmnaHku7boh6rnm7jnn5vnm74iLAogICAgICAgICAgICAgICAgICAgICAic2NvcmUiOiAxLjB9"
    "KQogICAgICAgIHN0cmVuZ3RoID0gMS4wCiAgICBlbGlmIG5lZyBhbmQgX2Nvdih0d19uZWcsIGJvZHkpID49IFNFTEZfTkVH"
    "QVRJT046CiAgICAgICAgaGFyZC5hcHBlbmQoeyJ0eXBlIjogInNlbGZfbmVnYXRpb24iLCAid2l0aCI6IE5vbmUsCiAgICAg"
    "ICAgICAgICAgICAgICAgICJkZXRhaWwiOiAi6LSf5p2h5Lu25LiO5q2j5paH5by655u45YWz77ya5p2h5Lu25LiO57uT6K66"
    "5LqS5palIiwKICAgICAgICAgICAgICAgICAgICAgInNjb3JlIjogcm91bmQoX2Nvdih0d19uZWcsIGJvZHkpLCA0KX0pCiAg"
    "ICAgICAgc3RyZW5ndGggPSBtYXgoc3RyZW5ndGgsIHJvdW5kKF9jb3YodHdfbmVnLCBib2R5KSwgNCkpCgogICAgIyAtLS0t"
    "IEwxLWIg5LiO5pei5pyJ6IqC54K555qE5p2h5Lu257qn5q+U5a+577yI5Y+N6aKY77yJIC0tLS0KICAgICMg6YCJ6Z2i77yI"
    "Y29uczIwMO+8ie+8mumihOetm++8iOW/q+eFp+e6p++8jOS4jeivu+ebmO+8ieKGkiDlgJnpgInpnaIg4oaSIOebuOWFs+md"
    "oiDiiKog5L+d5bqV6Z2i44CCCiAgICBub2RlcyA9ICgoZ2V0YXR0cihjZywgImluZGV4IiwgTm9uZSkgb3Ige30pLmdldCgi"
    "bm9kZXMiKSBvciB7fSkKICAgIG9yZGVyID0gbGlzdChub2Rlcy5pdGVtcygpKSAgICAgICAgICAjIOe0ouW8leW6j+W/q+eF"
    "p++8iEgtNChhKe+8muW/q+eFp+WQjuWGjei/reS7o++8iQogICAgbGltID0gbWF4KDAsIGludChsaW1pdCkpCiAgICBub190"
    "ZXJtcyA9IG5vdCAodHdfcG9zIG9yIHR3X25lZykgICAgIyDmlrDoioLngrnmnKrlo7DmmI7lj6/lsZXlvIDmnaHku7YKICAg"
    "IGNhbmQgPSBbXSAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIChyYW5rLCBzY29yZSwgaW5fYmVmb3JlLCBuaWQsIGUp"
    "CiAgICBmaWR4ID0gMAogICAgZm9yIG5pZCwgZSBpbiBvcmRlcjoKICAgICAgICBpZiBleGNsdWRlIGFuZCBuaWQgPT0gZXhj"
    "bHVkZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBsYXllciBhbmQgZS5nZXQoImxheWVyIikgIT0gbGF5ZXI6"
    "CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaW5fYmVmb3JlID0gZmlkeCA8IGxpbSAgICAgICAgICAgIyDmmK/lkKbl"
    "nKjkv67liY3miavmj4/pnaLlhoXvvIjov4fmu6TlkI7liY0gbGltaXTvvIkKICAgICAgICBmaWR4ICs9IDEKICAgICAgICBk"
    "aXNjID0gX2lzX2Rpc2NpcGxpbmUoeyJ0YWdzIjogZS5nZXQoInRhZ3MiKX0sIG5pZCkKICAgICAgICAjIOmihOetm+WUr+S4"
    "gOWJlOmZpOaho++8iOWPr+ivgeaXoOS6p+WHuu+8m+WFtuS9meS4gOW+i+aUvuihjOKAlOKAlOWugeWkmuWLv+a8j++8ie+8"
    "mgogICAgICAgICMg5paw6IqC54K55pyq5aOw5piO5Y+v5bGV5byA5p2h5Lu25pe277yM6Z2e57qq5b6L5YCZ6YCJ5Zyo57K+"
    "5q+U5Lit5Lqn5Ye65oGS5Li66Zu2CiAgICAgICAgIyDvvIhjMS9jMi9jMy9jNCDkuI7liIbmrafliKTlrprlnYfku6UgdHdf"
    "cG9zL3R3X25lZyDkuLrkuZjlrZDvvJvnuqrlvovov53lj43otbAKICAgICAgICAjIF9iYW5faGl0IOWtkOS4suWIpOWumuOA"
    "geS4jeeci+ivjeadg+KAlOKAlOaVhee6quW+i+WAmemAieS4gOW+i+S/neeVme+8ieOAggogICAgICAgICMg5pS25Y+j6L2u"
    "4pGg77yI5aSN5qC4IERFRkVSIOWQjuihpe+8ie+8mioq6Z2i5YaF5L6L5aSWKirigJTigJTliZTpmaTmsLjkuI3op6blj4rk"
    "v67liY3miavmj4/pnaIKICAgICAgICAjIO+8iOi/h+a7pOWQjue0ouW8leW6j+WJjSBsaW1pdCDlhoXnmoTlgJnpgInkuIDl"
    "vovkv53nlZnvvInvvIzkvb/jgIzkv67lkI7mo4Dlh7og4oqHIOS/ruWJjeOAjQogICAgICAgICMg5oiQ5Li65LiO44CM5p2h"
    "55uuIHRhZ3Mg5LiO55uY6Z2iIGZtLnRhZ3Mg5ZCM5rqQ44CN5peg5YWz55qE57uT5p6E5L+d6K+B77yI6Z2e5ZCM5rqQ5b2i"
    "5oCBCiAgICAgICAgIyDkuIvpnaLlhoXlgJnpgInku43ov5vnsr7mr5TpnaLjgIHnlLHnm5jpnaLliKTmja7oo4HlhrPvvInv"
    "vJvpnaLlpJbpnZ7lkIzmupDmrovkvZnop4EgY2hlY2sKICAgICAgICAjIGRvY3N0cmluZyDor5rlrp7ovrnnlYzvvIjkv67l"
    "iY3kuqbmo4DkuI3lh7rvvIzkuI3mnoTmiJDlm57lvZLvvInjgIIKICAgICAgICBpZiBub190ZXJtcyBhbmQgbm90IGRpc2Mg"
    "YW5kIG5vdCBpbl9iZWZvcmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgcmFuaywgc2NvcmUgPSBfc2lmdF9zY29y"
    "ZShlLCBuaWQsIHR3X3BvcywgdHdfbmVnLCBfY292LCBkaXNjKQogICAgICAgIGNhbmQuYXBwZW5kKChyYW5rLCBzY29yZSwg"
    "aW5fYmVmb3JlLCBuaWQsIGUpKQogICAgIyDnm7jlhbPpnaLvvJpyYW5rL3Njb3JlIOmZjeW6jyArIGlkIOWNh+W6j+e7iOmU"
    "ru+8iOehruWumuaAp++8m+S4jue0ouW8leeJqeeQhuW6j+aXoOWFs++8iQogICAgcmVsID0gc29ydGVkKGNhbmQsIGtleT1s"
    "YW1iZGEgdDogKC10WzBdLCAtdFsxXSwgc3RyKHRbM10pKSlbOmxpbV0KICAgIHJlbF9pZHMgPSB7dFszXSBmb3IgdCBpbiBy"
    "ZWx9CiAgICAjIOeyvuavlOmdou+8neebuOWFs+mdoiDiiKog5L+d5bqV6Z2i77yI6L+H5ruk5ZCO57Si5byV5bqP5YmNIGxp"
    "bWl0IOKIqSDlgJnpgInvvInigJTigJTkv53lupXpnaLljbMKICAgICMg5L+u5YmN5omr5o+P6Z2i77yb5YW26YCQ5L2N5L+d"
    "55WZ5piv44CM5L+u5ZCO5qOA5Ye6IOKKhyDkv67liY3jgI3nmoTnu5PmnoTmgKfkv53or4HvvIjpnZ7mpoLnjofvvInvvIwK"
    "ICAgICMg5Lik6Z2i5LiK6ZmQ5ZCEIGxpbWl077yI4omkIDLDl01BWF9TQ0FO77ybTUFYX1NDQU4g5pWw5YC85pyq5Yqo77yJ"
    "44CCCiAgICBzY2FuX2ZhY2UgPSBbKHRbM10sIHRbNF0pIGZvciB0IGluIHJlbF0KICAgIHNjYW5fZmFjZSArPSBbKHRbM10s"
    "IHRbNF0pIGZvciB0IGluIGNhbmQgaWYgdFsyXSBhbmQgdFszXSBub3QgaW4gcmVsX2lkc10KICAgIHNjYW5uZWQgPSBsZW4o"
    "Y2FuZCkgICAgICAgICAgICAgICAgICAjIOmihOetm+WQjuWAmemAieaVsO+8iOaIquaWreWJje+8iQogICAga2VwdCA9IGxl"
    "bihzY2FuX2ZhY2UpICAgICAgICAgICAgICAgICMg5a6e6ZmF57K+5q+U5pWw77yI55u45YWz6Z2iIOKIqiDkv53lupXpnaLv"
    "vIkKICAgIHRydW5jYXRlZCA9IHNjYW5uZWQgPiBrZXB0CiAgICAjIE4yNzbvvIjnrKwgMzIg6L2u5oCn6IO96Z2i77yJ77ya"
    "c2Nhbl9mYWNlIOeyvuavlOeOr+WGhemAkOiKgueCuSBjZy5nZXQg5Lya5ZCE6Ieq6YeN5o6i57Si5byVCiAgICAjIOetvuWQ"
    "je+8iOW/q+eFpyBzdGF0ICsgbGlzdGRpciArIOmAkOWIhueJhyBzdGF077yM5Y2V54K55a6e5rWLIH4zOMK1c++8m+acrOW6"
    "kyAyMDAg5qyhLwogICAgIyDosIPnlKjlhajlkIznrb7lkI3ph43mjqLvvInigJTigJTlvqrnjq/lpJbljZXmjqLkuIDmrKHj"
    "gIHnjq/lhoUgcHJvYmU9RmFsc2XvvJvor63kuYnnqpflj6M95pys5om5CiAgICAjIOivu+acn+mXtOOAjOS7lui/m+eoi+WG"
    "meWFpeOAjeS4jeiiq+aOouefpe+8iOavq+enkue6p++8jOS4juivu+e8k+WtmOW3suWjsOaYjueahOi/m+eoi+WGheS4gOiH"
    "tOaApwogICAgIyDovrnnlYzlkIzmrL7vvInvvJvml6DmjqLmtLvpnaLnmoTovb3kvZPvvIjmtYvor5XmoanvvInlm57okL3l"
    "jp8gY2cuZ2V0KG5pZCnvvIzooYzkuLrpm7blj5jjgIIKICAgIF9wcm9iZSA9IGdldGF0dHIoY2csICJfbWF5YmVfcmVsb2Fk"
    "X2luZGV4IiwgTm9uZSkKICAgIGlmIGNhbGxhYmxlKF9wcm9iZSk6CiAgICAgICAgX3Byb2JlKCkKICAgIGVsc2U6CiAgICAg"
    "ICAgX3Byb2JlID0gTm9uZQogICAgIyBpc3N1ZSAjMjk477ya6LCD55So5pa55pyq5aOw5piO5a+G57qn44CB6ICMIGV4Y2x1"
    "ZGUg5oyH5ZCR5LiA5LiqKirlt7LlrZjlnKgqKueahOiKgueCueaXtu+8jAogICAgIyDor6XoioLngrnlvZPliY3nm5jpnaLl"
    "r4bnuqflsLHmmK/mnKzmrKHlhpnlhaXlsIbnu6fmib/nmoTmoaPkvY3vvIgjMjk3IOeahOe7p+aJv+ivreS5ie+8ieKAlOKA"
    "lAogICAgIyDkuI3lj5blroPvvIzkuIDmnaHjgIzmnKrlo7DmmI7jgI3lnLDmlLnlhpnml6LmnIkgcHJpdmF0ZSDoioLngrnn"
    "moTlhpnlhaXkvJrmiormlrDmnaHku7bljp/mlocKICAgICMg5oyJIGludGVybmFsIOaYjuaWh+iusOi/m+WPsOi0pu+8iGB3"
    "cml0ZXBpcGVgIOeahCBgY2cob3A9d3JpdGUpYCDliqjor43pnaLotbDov5nmnaHot6/vvInjgIIKICAgICMg5Y+q5Zyo5aOw"
    "5piO5YC857y65aSx5pe25p+l5LiA5qyh77yb5p+l5LiN5Yiw77yI5paw6IqC54K5IC8g5qGp5pegIGdldO+8ieWNs+e7tOaM"
    "gSBpbnRlcm5hbCDpm7blj5jljJbjgIIKICAgIGlmIG5vdCBzZW5zaXRpdml0eSBhbmQgZXhjbHVkZToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIF9lbiA9IGNnLmdldChleGNsdWRlKSBvciB7fQogICAgICAgICAgICBzZW5zaXRpdml0eSA9IChfZW4u"
    "Z2V0KCJmcm9udG1hdHRlciIpIG9yIHt9KS5nZXQoInNlbnNpdGl2aXR5Iikgb3IgTm9uZQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHNlbnNpdGl2aXR5ID0gTm9uZQogICAgIyBuaWQg4oaSIOivpeaXouacieiKgueCueebmOmd"
    "ouWvhue6p++8iOWPquWvuSoq55yf6L+b5LqG5Yik5a6aKirnmoToioLngrnlj5blgLzvvIzop4HkuIvvvIkKICAgIGxlZGdl"
    "cl9zZW5zID0ge30KICAgIHNlZWRzID0gW10KICAgIGZvciBuaWQsIGUgaW4gc2Nhbl9mYWNlOgogICAgICAgIG5vZGUgPSAo"
    "Y2cuZ2V0KG5pZCwgcHJvYmU9RmFsc2UpIGlmIF9wcm9iZSBpcyBub3QgTm9uZQogICAgICAgICAgICAgICAgZWxzZSBjZy5n"
    "ZXQobmlkKSkgb3Ige30KICAgICAgICBmbSA9IG5vZGUuZ2V0KCJmcm9udG1hdHRlciIpIG9yIHt9CiAgICAgICAgYm9keSA9"
    "IG5vZGUuZ2V0KCJjb250ZW50Iikgb3IgIiIKICAgICAgICAjIGlzc3VlICMyOTjvvJpgb25seV9leGlzdGluZ19zaWRlYCAv"
    "IGBwb3Nfc2lkZWAgLyBgbmVnX3NpZGVgIOiusOeahOaYrwogICAgICAgICMgKirov5nkuKoqKuiKgueCueeahOadoeS7tuWO"
    "n+aWh++8jOaVheWug+iHquW3seeahOWvhue6p+W/hemhu+i/m+iQvei0puWvhue6p+mdouOAggogICAgICAgICMg5q2k5aSE"
    "5Y+q55m76K6w5LiN6KOB5Yaz4oCU4oCU55yf5q2j6L+b5a+G57qn6Z2i55qE5Y+q5pyJ44CM6L+b5LqGIGFsbGMg55qE6YKj"
    "5Lqb6IqC54K544CN77yMCiAgICAgICAgIyDlkKbliJnlupPph4zku7vmhI/kuIDkuKogcHJpdmF0ZSDoioLngrnooqvmiavl"
    "iLDlsLHkvJrmiormiYDmnInlj7DotKborrDlvZXmirnmiJDljrvljp/mlocKICAgICAgICAjIO+8iOi/h+W6puaKuemZpOWQ"
    "jOagt+aYr+acieaNn++8muWPsOi0pueahOWPr+WuoeiuoeaAp+S8muaVtOS9k+a2iOWkse+8ieOAggogICAgICAgIGxlZGdl"
    "cl9zZW5zW25pZF0gPSBmbS5nZXQoInNlbnNpdGl2aXR5IikKICAgICAgICBlX3BvcywgZV9uZWcgPSBfZGVjbGFyZWQoZm0s"
    "IGJvZHkpCiAgICAgICAgaWYgbm90IGVfcG9zIGFuZCBub3QgZV9uZWc6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAg"
    "Y29tcGFyYWJsZSArPSAxCiAgICAgICAgIyDnuqrlvovov53lj43vvJoqKuato+aWh+ihjOS4uioq5ZG95Lit57qq5b6L6IqC"
    "54K555qE5LiN6YCC55So5p2h5Lu277yIbmVnYXRpdmUucmVqZWN077yJCiAgICAgICAgIyDigJTigJQg6L+Z5piv44CM5LiN"
    "6IO96L+d5Y+N57qq5b6L44CN77yM5LiO44CM5p2h5Lu25LqS5pal44CN5piv5Lik5Zue5LqL77ya5YmN6ICF55yL5YGa5LqG"
    "5LuA5LmI77yMCiAgICAgICAgIyAgICDlkI7ogIXnnIvlo7DmmI7nmoTmnaHku7bmmK/lkKbkupLnm7jopobnm5bjgIIKICAg"
    "ICAgICBpZiBfaXNfZGlzY2lwbGluZShmbSwgbmlkKSBhbmQgZV9uZWcgYW5kIF9iYW5faGl0KGNvbnRlbnQsIGVfbmVnKToK"
    "ICAgICAgICAgICAgaGFyZC5hcHBlbmQoeyJ0eXBlIjogImRpc2NpcGxpbmUiLCAid2l0aCI6IG5pZCwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJ3aXRoX2xheWVyIjogZS5nZXQoImxheWVyIiksCiAgICAgICAgICAgICAgICAgICAgICAgICAiZGV0"
    "YWlsIjogIuWRveS4ree6quW+i+iKgueCueeahOS4jemAgueUqOadoeS7tu+8iG5lZ2F0aXZlLnJlamVjdO+8iSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAic2NvcmUiOiAxLjB9KQogICAgICAgICAgICBzZWVkcy5hcHBlbmQobmlkKQogICAgICAg"
    "ICAgICBzdHJlbmd0aCA9IDEuMAogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGMxID0gX2Nvdih0d19wb3MsICIgIi5q"
    "b2luKGVfbmVnKSkgaWYgKHR3X3BvcyBhbmQgZV9uZWcpIGVsc2UgMC4wCiAgICAgICAgYzIgPSBfY292KHR3X25lZywgIiAi"
    "LmpvaW4oZV9wb3MpKSBpZiAodHdfbmVnIGFuZCBlX3BvcykgZWxzZSAwLjAKICAgICAgICBjID0gbWF4KGMxLCBjMikKICAg"
    "ICAgICAjIGlzc3VlICMyMTbvvIgyMDI2LTEwLTEzIERTSCDnq6/vvInvvJoqKmMxL2MyIOWIhui3r+ivu+aVsCoq44CC5Yik"
    "5o2u5LiA5a2X5pyq5Yqo4oCU4oCUCiAgICAgICAgIyBjIOS7jSA9IG1heChjMSwgYzIp44CB6ZiI5YC85LiO5q+U6L6D566X"
    "5a2Q6YCQ5L2N5LiN5Y+Y77yb5pys5pS55Yqo5Y+q6K6p44CM5piv5ZOq5LiA5L6n5pKR6LW3CiAgICAgICAgIyDov5nmrKEg"
    "Y29uZGl0aW9uX2NsYXNo44CB5Lik5L6n5ZCE6Ieq55qE6K+N6aG56KeE5qih5piv5aSa5bCR44CN5Y+Y5oiQ5Y+v6K+76K+7"
    "5pWw44CCCiAgICAgICAgIyDkuLrku4DkuYjlv4XpobvliIbot6/vvIhpc3N1ZSAjMjE2IMKn44CHIOiHquW3see7meWHuuea"
    "hOaVmeiure+8ie+8mmMxL2MyIOaYryoq5Lik5Liq54us56uL5LqL5a6eKioKICAgICAgICAjIOeahOS5mOenr+KAlOKAlOOA"
    "jOaXouacieiKgueCueaYr+WQpuWjsOaYjuS6huecnyBuYeOAjcOX44CM5paw6IqC54K56K+N6Z2i5piv5ZCm6KaG55uW6K+l"
    "IG5h44CN44CCCiAgICAgICAgIyDlj6rlm57kvKDlkIjlubblkI7nmoQgY++8jOivu+iAheaXoOazleWIpOaWreaUueWPmOea"
    "hOaYr+WTquS4gOS+p++8jOivu+aVsOS4jeWPr+WkjeaguOOAggogICAgICAgICMg6K+N6aG56KeE5qih5LiA5bm25Zue5Lyg"
    "77yM5piv5Zug5Li656iA6YeK55qE5pa55ZCR5Y+W5Yaz5LqOKirlk6rkuIDkvqfmmK/lkIjmiJDkuLIqKu+8mgogICAgICAg"
    "ICMg5paw6IqC54K555qEIHR3X3BvcyDlkKsgY29uZGl0aW9uX3NwYWNlX3RleHQg5ZCI5oiQ5Liy77yI6K+N6aG55aSa77yJ"
    "77yM6ICMIHR3X25lZyDlj6rmnaXoh6oKICAgICAgICAjIG5h77yI6K+N6aG55bCR77yJ77yb5pei5pyJ6IqC54K55L6n5YiZ"
    "5Y+W5Yaz5LqO5a6D5a6e6ZmF5aOw5piO55qE5YaZ5rOV44CCCiAgICAgICAgY2xhc2hfcm91dGVzID0gewogICAgICAgICAg"
    "ICAiYzEiOiByb3VuZChjMSwgNCksICJjMiI6IHJvdW5kKGMyLCA0KSwKICAgICAgICAgICAgInRlcm1zIjogeyJ0d19wb3Mi"
    "OiBsZW4odHdfcG9zIG9yIHt9KSwgInR3X25lZyI6IGxlbih0d19uZWcgb3Ige30pLAogICAgICAgICAgICAgICAgICAgICAg"
    "ImVfcG9zIjogbGVuKGVfcG9zIG9yIFtdKSwgImVfbmVnIjogbGVuKGVfbmVnIG9yIFtdKX19CiAgICAgICAgIyAtLS0tIEwx"
    "LWMg5ZCM5L6n5q+U5a+577ya56ys5LqM57G75YWz57O777yI5ZCM5p2h5Lu256m66Ze0IMK3IOe7k+iuuuanveWPluWAvOWI"
    "huatp++8iSAtLS0tCiAgICAgICAgIyDkuI4gTDEtYiDmmK8qKuS4pOexu+S4jeWQjOWFs+ezuyoq77yaTDEtYiDliKTjgIzm"
    "naHku7bkupLmlqXjgI3vvIjlj43popjvvInvvIxMMS1jIOWIpAogICAgICAgICMg44CM5ZCM5p2h5Lu2ICsg5ZCM57uT6K66"
    "5qe9ICsg5Y+W5YC85LiN5ZCM44CN77yI55+b55u+77yJ44CC5ZCO6ICF5Zyo6K+N6Z2i5LiN5Y+v5Yik4oCU4oCU5o6i6ZKI"
    "5a6e5rWLCiAgICAgICAgIyDjgIzlkIzlsZ7mgKfkuI3lkIzlgLzjgI3mraPmlofopobnm5bnjocgMC42MTIg5Y+N6ICM5L2O"
    "5LqO44CM5byC5bGe5oCn44CNMC42MjPvvIzmlYXmlLnnlKgKICAgICAgICAjIENDRyDmp73kvY3lrZfmrrXku6PnkIbjgIzm"
    "mK/lkKblkIzkuIDku7bkuovjgI3jgIIKICAgICAgICAjIOazqO+8muW/hemhu+aYr+eLrOeriyBpZiDogIzpnZ4gZWxzZeKA"
    "lOKAlOWQjOadoeS7tuaXtiBjPTDvvIzoi6XlubblhaUgTDEtYiDliIbmlK/kvJrooqsKICAgICAgICAjICAgICBgYyA8IENM"
    "QVNIX0xPVzogY29udGludWVgIOaPkOWJjei3s+i/h++8jEwxLWMg5rC45LiN5omn6KGM44CCCiAgICAgICAgYzMgPSBfY292"
    "KHR3X3BvcywgIiAiLmpvaW4oZV9wb3MpKSBpZiAodHdfcG9zIGFuZCBlX3BvcykgZWxzZSAwLjAKICAgICAgICBjNCA9IF9j"
    "b3YodHdfbmVnLCAiICIuam9pbihlX25lZykpIGlmICh0d19uZWcgYW5kIGVfbmVnKSBlbHNlIDAuMAogICAgICAgIHNhbWVf"
    "Y29uZCA9IG1heChjMywgYzQpCiAgICAgICAgIyBpc3N1ZSAjMjE177yIMjAyNi0xMC0xMyBEU0gg56uv77yJ77yaKirkuKTk"
    "vqflj6PlvoTlt67lm57kvKAqKuOAguWIpOaNruS4gOWtl+acquWKqOKAlOKAlAogICAgICAgICMgc2FtZV9jb25kIOS7jSA9"
    "IG1heChjMywgYzQp44CB6ZiI5YC85LiO5q+U6L6D566X5a2Q6YCQ5L2N5LiN5Y+Y77yb5pys5pS55Yqo5Y+q6K6pCiAgICAg"
    "ICAgIyDjgIzmlrDoioLngrnkvqfkuI7ml6LmnInoioLngrnkvqflkIToh6rop6PmnpDlh7rkuobku4DkuYjjgI3lj5jmiJDl"
    "j6/or7vor7vmlbDjgIIKICAgICAgICAjIOS4uuS7gOS5iOW/hemhu+WbnuS8oO+8iGlzc3VlICMyMTUg55qE5qC45b+D77yJ"
    "77ya5Lik5L6nKirkuI3lkIzmupAqKuKAlOKAlOaWsOiKgueCueS+pwogICAgICAgICMgX25ld190ZXJtcyDlubblhaUgY29u"
    "ZGl0aW9uX3NwYWNlIOWQhOanveWAvO+8jOaXouacieiKgueCueS+pyBfZGVjbGFyZWRfY29uZGl0aW9ucwogICAgICAgICMg"
    "5LiN6K+7IGNvbmRpdGlvbl9zcGFjZeOAguaVhSBjMyDnmoTliIblrZDlkKvmp73lgLzjgIHliIbmr43kuI3lkKvvvIzopobn"
    "m5bnjofooqvns7vnu5/mgKfljovkvY7jgIIKICAgICAgICAjIOatpOWJjeWbnuS8oOS9k+mHjOWPquacieWQiOW5tuWQjuea"
    "hCBzYW1lX2NvbmRpdGlvbiDkuIDkuKrmlbDvvIzor7vogIUqKuaXoOazleWIpOaWrSoq6L+Z5Liq5pWwCiAgICAgICAgIyDk"
    "vY7mmK/lm6DkuLrjgIzkuKTkvqfnnJ/nmoTkuI3lkIzmnaHku7bjgI3ov5jmmK/lm6DkuLrjgIzkuKTkvqflj6PlvoTkuI3l"
    "kIzmupDjgI3jgIIKICAgICAgICAjIOS4jiAjMjE2LyMyMTcvIzIxOCDlkIzkuIDmnaHmlZnorq3vvJrlkIjmiJDor7vmlbDl"
    "v4XpobvliIbot68v6ZmE5p2l5rqQ77yM5ZCm5YiZ5LiN5Y+v5aSN5qC444CCCiAgICAgICAgY29uZF9yb3V0ZXMgPSB7CiAg"
    "ICAgICAgICAgICJjMyI6IHJvdW5kKGMzLCA0KSwgImM0Ijogcm91bmQoYzQsIDQpLAogICAgICAgICAgICAibmV3X3NpZGUi"
    "OiBsZW4ocG9zIG9yIFtdKSwgImV4aXN0aW5nX3NpZGUiOiBsZW4oZV9wb3Mgb3IgW10pLAogICAgICAgICAgICAib25seV9u"
    "ZXdfc2lkZSI6IFt4IGZvciB4IGluIChwb3Mgb3IgW10pIGlmIHggbm90IGluIChlX3BvcyBvciBbXSldWzo2XSwKICAgICAg"
    "ICAgICAgIm9ubHlfZXhpc3Rpbmdfc2lkZSI6IFt4IGZvciB4IGluIChlX3BvcyBvciBbXSkgaWYgeCBub3QgaW4gKHBvcyBv"
    "ciBbXSldWzo2XSwKICAgICAgICAgICAgInNhbWVfc291cmNlIjogbGlzdChwb3Mgb3IgW10pID09IGxpc3QoZV9wb3Mgb3Ig"
    "W10pfQogICAgICAgIGlmIHNhbWVfY29uZCA+PSBTQU1FX0NPTkRfSElHSDoKICAgICAgICAgICAgZV9mbiwgZV9zYiA9IF9z"
    "bG90X3RleHQoYm9keSkKICAgICAgICAgICAgIyBpc3N1ZSAjMjE377yIMjAyNi0xMC0xMyBEU0gg56uv77yJ77yaKirpgJDo"
    "t6/lhYjnrpflho3lj5YgbWF4KirjgILliKTmja7kuIDlrZfmnKrliqgKICAgICAgICAgICAgIyDigJTigJRzbG90IOS7jSA9"
    "IG1heCjkuKTot68p77yM6KOB5Yaz57uT5p6c6YCQ5L2N5LiN5Y+Y77yb5pys5pS55Yqo5Y+q5oqK44CM5piv5ZOq5LiA6Lev"
    "5pKR6LW35LqGCiAgICAgICAgICAgICMg5qe95L2N44CN5Y+Y5oiQ5Y+v6K+76K+75pWw44CC5q2k5YmN5Y+q5Zue5Lyg5ZCI"
    "5bm25ZCO55qEIHNsb3TvvIzor7vogIXml6Dms5XliKTmlq3jgIzku4XkuIDot6/nm7jnrKbjgI3vvIwKICAgICAgICAgICAg"
    "IyDor6XlpLHmlYjmmK/pnZnpu5jnmoTvvIjlm57kvKDkvZPph4zmsqHmnInku7vkvZXlrZfmrrXorrDlvZXlroPvvInjgIIK"
    "ICAgICAgICAgICAgIyDkuI4gIzIxNiDlkIzkuIDmnaHmlZnorq3vvJpjMS9jMuOAgeanveS9jei/meexuyoq5aSa6Lev5ZCI"
    "5oiQKiror7vmlbDvvIzlm57kvKDpnaLlv4XpobvliIbot6/vvIwKICAgICAgICAgICAgIyDlkKbliJnor7vmlbDkuI3lj6/l"
    "pI3moLjjgIIKICAgICAgICAgICAgc2xvdF9mbiA9IChfY292KGV4cGFuZF9xdWVyeV90ZXJtc193ZWlnaHRlZChuX2ZuKSwg"
    "ZV9mbikKICAgICAgICAgICAgICAgICAgICAgICBpZiAobl9mbiBhbmQgZV9mbikgZWxzZSAwLjApCiAgICAgICAgICAgIHNs"
    "b3Rfc2IgPSAoX2NvdihleHBhbmRfcXVlcnlfdGVybXNfd2VpZ2h0ZWQobl9zYiksIGVfc2IpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgaWYgKG5fc2IgYW5kIGVfc2IpIGVsc2UgMC4wKQogICAgICAgICAgICBzbG90ID0gbWF4KHNsb3RfZm4sIHNsb3Rf"
    "c2IpCiAgICAgICAgICAgIGlmIHNsb3QgPj0gU0xPVF9ISUdIOgogICAgICAgICAgICAgICAgIyDlkIzlj6PlvoTmr5Tlr7nv"
    "vIjmraPmlofihpTmraPmlofvvInvvJp0d19jb250ZW50IOW3suWOu+aooeadv+ihjCArIOS4pOS+p+WQjOS4gOWllwogICAg"
    "ICAgICAgICAgICAgIyDnqbrnmb3lvZLkuIDljJbvvIhIOO+8ie+8jOingeS4iuaWh+S4jiBgX25vcm1fd3NgIC8gYF9ub3dz"
    "YCDor7TmmI7jgIIKICAgICAgICAgICAgICAgIGVfYm9keSA9IF9jb25jbHVzaW9uX3RleHQoYm9keSkgICAgICAjIGlzc3Vl"
    "ICM4OO+8muWQjOeci+e7k+iuuumdogogICAgICAgICAgICAgICAgaWYgbl9ib2R5X3RpZ2h0ID09IF9ub3dzKGVfYm9keSk6"
    "CiAgICAgICAgICAgICAgICAgICAgIyDlt67lvILlj6rlnKjnqbrnmb3vvIhcclxu4oaUXG4gLyDnvKnov5sgLyDnqbrooYwg"
    "LyDooYzlsL7nqbrmoLwgLyDor43lhoXmj5Lnqbrnmb3vvIkKICAgICAgICAgICAgICAgICAgICAjIOKHkiDlvZLkuIDljJbl"
    "kI7pgJDlrZfnm7jlkIzvvIzlv4XliKQqKumHjeWkjSoq77yI6K+l5ZCI5bm277yJ77yM5LiN5Yik5YiG5q2n44CCCiAgICAg"
    "ICAgICAgICAgICAgICAgIyDov5nkuI3mmK/mlL7lrr3nnJ/liIbmrafliKTmja7vvJrlj5blgLznnJ/kuI3lkIzogIXljrvn"
    "qbrnmb3lkI7ku43kuI3nm7jnrYnjgIIKICAgICAgICAgICAgICAgICAgICBjb25jbCA9IDEuMAogICAgICAgICAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgICAgICAgICBjb25jbCA9IChfY292KHR3X2NvbnRlbnQsIF9ub3JtX3dzKGVfYm9keSkpCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdHdfY29udGVudCBlbHNlIDAuMCkKICAgICAgICAgICAgICAgIGlmIGNv"
    "bmNsIDwgQ09OQ0xVU0lPTl9TQU1FOgogICAgICAgICAgICAgICAgICAgIGRpdmVyZ2VuY2VzLmFwcGVuZCh7CiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJ0eXBlIjogInNhbWVfY29uZGl0aW9uX2RpdmVyZ2VuY2UiLCAid2l0aCI6IG5pZCwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIndpdGhfbGF5ZXIiOiBlLmdldCgibGF5ZXIiKSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ImRldGFpbCI6ICgi6YCC55So5p2h5Lu25LiO57uT6K665qe95Z2H6YeN5ZCI5L2G5Y+W5YC85LiN5ZCM77yaIgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICLlj6/og73mmK/mm7TmraPvvIjlupTopobnm5bml6flgLzvvInmiJbliIbm"
    "rafvvIjlupTooaXljLrliIbmnaHku7bvvIkiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInNhbWVfY29uZGl0aW9uIjog"
    "cm91bmQoc2FtZV9jb25kLCA0KSwKICAgICAgICAgICAgICAgICAgICAgICAgImNvbmRfcm91dGVzIjogY29uZF9yb3V0ZXMs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICJzbG90X292ZXJsYXAiOiByb3VuZChzbG90LCA0KSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgInNsb3Rfcm91dGVzIjogeyLlip/og73lkI0iOiByb3VuZChzbG90X2ZuLCA0KSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICLlrZDlip/og70iOiByb3VuZChzbG90X3NiLCA0KX0sCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJzbG90X3NpbmdsZV9yb3V0ZSI6ICgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIChzbG90X2ZuID49"
    "IFNMT1RfSElHSCkgIT0gKHNsb3Rfc2IgPj0gU0xPVF9ISUdIKSksCiAgICAgICAgICAgICAgICAgICAgICAgICJjb25jbHVz"
    "aW9uX292ZXJsYXAiOiByb3VuZChjb25jbCwgNCksCiAgICAgICAgICAgICAgICAgICAgICAgICJzbG90IjogKG5fZm4gb3Ig"
    "bl9zYilbOjQwXX0pCiAgICAgICAgaWYgYyA8IENMQVNIX0xPVzoKICAgICAgICAgICAgY29udGludWUKICAgICAgICBjb25m"
    "bGljdHMuYXBwZW5kKHsKICAgICAgICAgICAgInR5cGUiOiAiY29uZGl0aW9uX2NsYXNoIiwgIndpdGgiOiBuaWQsCiAgICAg"
    "ICAgICAgICJ3aXRoX2xheWVyIjogZS5nZXQoImxheWVyIiksCiAgICAgICAgICAgICJkZXRhaWwiOiAoIuaWsOiKgueCuemA"
    "gueUqOadoeS7tuiQveWcqOaXouacieiKgueCueS4jemAgueUqOWMuiIKICAgICAgICAgICAgICAgICAgICAgICBpZiBjMSA+"
    "PSBjMiBlbHNlICLmlrDoioLngrnkuI3pgILnlKjmnaHku7bopobnm5bml6LmnInoioLngrnpgILnlKjljLoiKSwKICAgICAg"
    "ICAgICAgInNjb3JlIjogcm91bmQoYywgNCksCiAgICAgICAgICAgICJjbGFzaF9yb3V0ZXMiOiBjbGFzaF9yb3V0ZXMsCiAg"
    "ICAgICAgICAgICJwb3Nfc2lkZSI6IF9kZWR1cChwb3MpWzo2XSwgIm5lZ19zaWRlIjogX2RlZHVwKG5lZylbOjZdfSkKICAg"
    "ICAgICBzZWVkcy5hcHBlbmQobmlkKQogICAgICAgIHN0cmVuZ3RoID0gbWF4KHN0cmVuZ3RoLCBjKQoKICAgICMgLS0tLSBM"
    "MCDmg4Xnu6rvvIjni6znq4vpgJrpgZPvvIzlj6rosIPluqbkuI3oo4HlhrPvvIkgLS0tLQogICAgZW1vID0gZW1vdGlvbmFs"
    "X2JpYXMoc3RyZW5ndGgsIF9sYXN0X3N0cmVuZ3RoKGNnKSkKCiAgICAjIC0tLS0gTDEg5Zub5oCB5Yik5a6aIC0tLS0KICAg"
    "IHJlY3Vyc2lvbiA9IE5vbmUKICAgIG1pc3NpbmcgPSBbXQogICAgYWxsYyA9IGhhcmQgKyBjb25mbGljdHMgKyBkaXZlcmdl"
    "bmNlcwogICAgaWYgaGFyZDoKICAgICAgICB2ZXJkaWN0ID0gIlJFSkVDVCIKICAgICAgICByZWFzb24gPSAi77ybIi5qb2lu"
    "KGhbImRldGFpbCJdIGZvciBoIGluIGhhcmQpCiAgICBlbGlmIGRpdmVyZ2VuY2VzOgogICAgICAgIHZlcmRpY3QgPSAiREVG"
    "RVIiCiAgICAgICAgcmVhc29uID0gIuWQjOadoeS7tuepuumXtOS4i+e7k+iuuuanveWPluWAvOS4jeS4gOiHtO+8mumcgOij"
    "geWGs+aYr+abtOato+i/mOaYr+WIhuaUryIKICAgICAgICAjIOS4pOexu+WFs+ezu+WPr+iDveWQjOaXtuaIkOeri++8iOWQ"
    "jOadoeS7tuWIhuatpyB2cyDmn5DoioLngrkgLyDmnaHku7bkupLmlqUgdnMg5Y+m6IqC54K577yJ4oCU4oCUCiAgICAgICAg"
    "IyDoi6Xlj6rmiqUgTDEtY++8jOi3qOS+p+S6kuaWpeeahOe6v+e0ouS8muiiq+aOqeeblu+8jOmjnui9ruaUtuWIsOeahOe8"
    "uuWPo+WwseS4jeWujOaVtOOAggogICAgICAgIGlmIGNvbmZsaWN0czoKICAgICAgICAgICAgcmVhc29uICs9IGYn77yb5Y+m"
    "5pyJIHtsZW4oY29uZmxpY3RzKX0g5aSE5p2h5Lu25LqS5pal77yI6KeBIGNvbmZsaWN0c1td77yJJwogICAgZWxpZiBzdHJl"
    "bmd0aCA+PSBDTEFTSF9ISUdIOgogICAgICAgIHZlcmRpY3QgPSAiREVGRVIiCiAgICAgICAgcmVhc29uID0gIuadoeS7tuS6"
    "kuaWpe+8mumcgOihpeWMuuWIhuadoeS7tuWQjuaJjeiDveWIpOWumiIKICAgIGVsaWYgc3RyZW5ndGggPj0gQ0xBU0hfTE9X"
    "OgogICAgICAgIHZlcmRpY3QgPSAiREVGRVIiCiAgICAgICAgcmVhc29uID0gIuadoeS7tumDqOWIhuimhueblu+8muW+heeh"
    "ruiupOaYr+WQpuS6kuaWpSIKICAgIGVsaWYgY29tcGFyYWJsZSA9PSAwIGFuZCAocG9zIG9yIG5lZyk6CiAgICAgICAgdmVy"
    "ZGljdCA9ICJCTElORFNQT1QiCiAgICAgICAgcmVhc29uID0gIuaXouacieiKgueCueWdh+acquWjsOaYjuadoeS7tu+8muaX"
    "oOazleW7uueri+avlOWvuei3r+W+hCIKICAgIGVsc2U6CiAgICAgICAgdmVyZGljdCA9ICJBQ0NFUFQiCiAgICAgICAgcmVh"
    "c29uID0gIuaXoOWGsueqgSIKCiAgICAjIC0tLS0gTDIg6YCS5b2S5Y+N5oCd77yI5LuF5a+5IERFRkVS77yM5LiU5oOF57uq"
    "5pyq5oyH5ZCRIGFwcHJvYWNoaW5nIOeahOW/q+mAn+aUvuihjO+8iSAtLS0tCiAgICBpZiB2ZXJkaWN0ID09ICJERUZFUiIg"
    "YW5kIGludChkZXB0aCkgPiAwIGFuZCBlbW9bImJpYXMiXSAhPSAiYXBwcm9hY2hpbmciOgogICAgICAgIHJlY3Vyc2lvbiA9"
    "IF9yZWN1cnNpdmVfcmVmbGVjdChjZywgc2VlZHMsIHR3X3BvcywgdHdfbmVnLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBtYXhfZGVwdGg9aW50KGRlcHRoKSkKICAgICAgICBpZiByZWN1cnNpb25bInN0b3BwZWRfYnkiXSA9"
    "PSAicmVzb2x2ZWQiOgogICAgICAgICAgICAjIOaJvuWIsOWMuuWIhuadoeS7tiDihpIg5Yay56qB5Y+v5YiG6L6o77yM6ZmN"
    "57qn5Li65b6F5a6a77yI5LiN55u05o6l5pS+6KGM77yM55WZ5Lq65belL+mjnui9ru+8iQogICAgICAgICAgICByZWFzb24g"
    "PSBmJ3tyZWFzb25977yb5bey5om+5Yiw5Yy65YiG5p2h5Lu2IHtyZWN1cnNpb25bInJlc29sdmVkX2J5Il1bOjNdfScKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICBtaXNzaW5nLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAibmVlZCI6ICLljLrliIbm"
    "naHku7YiLAogICAgICAgICAgICAgICAgIndoeSI6IGYn6YCS5b2S5Y+N5oCd5YGc5q2i5LqOIHtyZWN1cnNpb25bInN0b3Bw"
    "ZWRfYnkiXX0nCiAgICAgICAgICAgICAgICAgICAgICAgZifvvIjmt7HluqYge3JlY3Vyc2lvblsiZGVwdGgiXX3vvIzlop7n"
    "m4oge3JlY3Vyc2lvblsiZ2FpbiJdfe+8iScsCiAgICAgICAgICAgICAgICAiY29uZmxpY3RzIjogW2NbIndpdGgiXSBmb3Ig"
    "YyBpbiBhbGxjIGlmIGMuZ2V0KCJ3aXRoIildWzo1XX0pCgogICAgIyDlkIzmnaHku7blj5blgLzliIbmrafvvJpMMiDpgJLl"
    "vZLmj5DkvpvkuI3kuobjgIzljLrliIbmnaHku7bjgI3vvIjmnaHku7bmnKzlsLHnm7jlkIzvvInvvIzmlYXnvLrlj6PmmK8K"
    "ICAgICMg44CM5Y+W5YC86KOB5Yaz44CN6ICM6Z2e44CM6KGl5p2h5Lu244CN44CC5b+F6aG75pi+5byP6JC9IG1pc3Npbmfi"
    "gJTigJTlkKbliJkgc3RyZW5ndGg9MCDihpIKICAgICMg5oOF57uqIGFwcHJvYWNoaW5nIOKGkiBMMiDooqvot7Pov4cg4oaS"
    "IG1pc3Npbmcg5Li656m6IOKGkiDpo57ova7mlLbkuI3liLDku7vkvZXkv6Hlj7fjgIIKICAgIGlmIGRpdmVyZ2VuY2VzIGFu"
    "ZCBub3QgbWlzc2luZzoKICAgICAgICBtaXNzaW5nLmFwcGVuZCh7CiAgICAgICAgICAgICJuZWVkIjogIuWPluWAvOijgeWG"
    "s++8iOWQjOadoeS7tsK35ZCM57uT6K665qe95a2Y5Zyo5aSa5p2h5LiN5ZCM5Y+W5YC877yJIiwKICAgICAgICAgICAgIndo"
    "eSI6ICLpgILnlKjmnaHku7bkuI7nu5Porrrmp73lnYfph43lkIjogIzmraPmloflj5blgLzkuI3lkIzvvJoiCiAgICAgICAg"
    "ICAgICAgICAgICAi6ZyA56Gu6K6k5piv44CM5pu05q2j44CN77yI5bqU6KaG55uW5pen5YC877yJ6L+Y5piv44CM5YiG5pSv"
    "44CN77yI5bqU6KGl5Yy65YiG5p2h5Lu277yJIiwKICAgICAgICAgICAgImNvbmZsaWN0cyI6IFtjWyJ3aXRoIl0gZm9yIGMg"
    "aW4gYWxsYyBpZiBjLmdldCgid2l0aCIpXVs6NV19KQoKICAgIHJlYyA9IHsidCI6IHRpbWUudGltZSgpLCAibGF5ZXIiOiBs"
    "YXllciwgInZlcmRpY3QiOiB2ZXJkaWN0LAogICAgICAgICAgICJyZWFzb24iOiByZWFzb24sICJjb25mbGljdF9zdHJlbmd0"
    "aCI6IHJvdW5kKHN0cmVuZ3RoLCA0KSwKICAgICAgICAgICAiZW1vdGlvbmFsIjogZW1vLCAiY29uZmxpY3RzIjogYWxsYywg"
    "InJlY3Vyc2lvbiI6IHJlY3Vyc2lvbiwKICAgICAgICAgICAibWlzc2luZyI6IG1pc3NpbmcsICJzY2FubmVkIjogc2Nhbm5l"
    "ZCwgImtlcHQiOiBrZXB0LAogICAgICAgICAgICJ0cnVuY2F0ZWQiOiB0cnVuY2F0ZWQsICJjb21wYXJhYmxlIjogY29tcGFy"
    "YWJsZSwKICAgICAgICAgICAicG9zIjogcG9zWzo2XSwgIm5lZyI6IG5lZ1s6Nl0sCiAgICAgICAgICAgImFjdG9yIjogZ2V0"
    "YXR0cihjZywgImFjdG9yIiwgInVua25vd24iKX0KICAgICMg5oiq5pat5LiN6Z2Z6buY77yI5LiOIHN0ZyBgX3dpdGhfc2Nh"
    "bl9yZWFkc2Ag5ZCM5Y+j5b6E57K+56We77yJ77ya5YCZ6YCJ5pyJ6KKr6ZmQ6aKd5Lii5byD5pe2CiAgICAjIOmZhOWPr+aT"
    "jeS9nCBoaW5077yI57uG5YyW5p2h5Lu2IC8g5bu657Si5byV5pa55ZCR77yb5pWw5YC85pS+5aSn5LiN5piv5L+u5rOV77yJ"
    "44CCCiAgICBpZiB0cnVuY2F0ZWQ6CiAgICAgICAgcmVjWyJoaW50Il0gPSBfU0NBTl9ISU5UICUgKHNjYW5uZWQsIGxpbSwg"
    "a2VwdCkKCiAgICAjIC0tLS0g5Yay56qB6Ieq5Yqo6Kem5Y+R6aOe6L2u77yI6K+v5beuIOKGkiDooaXmnaHku7Yg4oaSIOe7"
    "k+aehOabtOaWsO+8iSAtLS0tCiAgICAjIEgxMeKRpe+8iDIwMjYtMDktMzDvvInvvJoqKuWPquWvueecn+WGsueqge+8iFJF"
    "SkVDVO+8ieW7uuWNlSoq44CC5pS55YmN5pivCiAgICAjIHZlcmRpY3Qg4oiIIHtSRUpFQ1QsIERFRkVSLCBCTElORFNQT1R9"
    "IOWFqOW7uuKAlOKAlERFRkVSIOaYr+OAjOadoeS7tuS6kuaWpS/pg6jliIbopobnm5bjgIEKICAgICMg5b6F56Gu6K6k44CN"
    "77yMQkxJTkRTUE9UIOaYr+OAjOaXouacieiKgueCueWFqOaXoOWjsOaYjiDih5Ig5qOA5rWL5YmN5o+Q5LiN5a2Y5Zyo44CN"
    "77yI56m65bqT5LiK5oGSCiAgICAjIOaIkOeri++8ie+8jOS4pOiAhemDveS4jeaYr+OAjOW3suWIpOWumueahOWGsueqgeOA"
    "je+8m+iHquWKqOiQvSB1bnJlc29sdmVkIOetieS6juaKiuW+heehruiupOS4jgogICAgIyDml6Dms5Xmr5Tlr7nlhpnmiJDl"
    "voXlip7lt6XljZXvvIzmsaHmn5Poo4HlhrPpmJ/liJfvvIjlrp7mtYvvvJrlk6jlhbXlvaLmgIHor6/liKTlh7rnmoQgREVG"
    "RVIg55u05o6lCiAgICAjIOWbuuWMluaIkOW3peWNlSB1bnJfOWFmNDgwMzM4Me+8ieOAguWIpOWumuacrOi6q+eFp+aXp+i/"
    "lOWbnu+8jOe8uueahOWPquaYr+OAjOiHquWKqOW7uuWNleOAjeOAggogICAgaWYgYXV0b19mbHl3aGVlbCBhbmQgdmVyZGlj"
    "dCBpbiBGTFlXSEVFTF9UUklHR0VSUzoKICAgICAgICByZWNbInVucmVzb2x2ZWRfaWQiXSA9IF9maXJlX2ZseXdoZWVsKGNn"
    "LCBxdWVyeSBvciBjb250ZW50LCB2ZXJkaWN0LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgcmVhc29uLCBtaXNzaW5nLCBhbGxjLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "c2Vuc2l0aXZpdHk9c2Vuc2l0aXZpdHkpCiAgICBpZiBsb2dfd3JpdGU6CiAgICAgICAgIyBpc3N1ZSAjMjk477yaKirokL3n"
    "m5jlia/mnKwqKuW4puWvhue6p+OAgeaMiemcgOWOu+WOn+aWh++8m+S4iumdoui/lOWbnue7meiwg+eUqOaWueeahAogICAg"
    "ICAgICMgYHJlY2Ag5LiA5a2X5LiN5Yqo77yI5aSN5qC46Z2i6KaB5Y6f5paH77yM6JC955uY6Z2i5LiN6KaB77yJ44CCCiAg"
    "ICAgICAgX2x2ID0gW2xlZGdlcl9zZW5zLmdldCh4KSBmb3IgeCBpbgogICAgICAgICAgICAgICB7Yy5nZXQoIndpdGgiKSBm"
    "b3IgYyBpbiBhbGxjIGlmIGlzaW5zdGFuY2UoYywgZGljdCl9XQogICAgICAgIF9sdmwgPSBsZWRnZXJfbGV2ZWwoc2Vuc2l0"
    "aXZpdHksIF9sdikKICAgICAgICBfbHIgPSBfbGV2ZWxfcmFuayhfbHZsKQogICAgICAgIF9yZWRhY3QgPSBib29sKF9sciBp"
    "cyBub3QgTm9uZSBhbmQgX2xyID4gX0xFREdFUl9MRVZFTFMuaW5kZXgoImludGVybmFsIikpCiAgICAgICAgX3JlYyA9IHNj"
    "cnViX3JlY29yZChyZWMpIGlmIF9yZWRhY3QgZWxzZSBkaWN0KHJlYykKICAgICAgICBfcmVjWyJzZW5zaXRpdml0eSJdID0g"
    "X2x2bAogICAgICAgIF9yZWNbInJlZGFjdGVkIl0gPSBfcmVkYWN0CiAgICAgICAgbG9nKGNnLCBfcmVjKQogICAgcmV0dXJu"
    "IHJlYwoKCiMg55Sf5pWI5p2h5Lu277yabWlzc2luZyDkuLrlgYflgLzvvIhOb25lL+epuuWuueWZqC/nqbrkuLLvvInov5Tl"
    "m54gIiLvvJvlkKbliJnpgJDpobnku4Xlj5YgbS5nZXQoIm5lZWQiKSDnnJ/lgLzogIXvvIzmoLzlvI/ljJbkuLogYG5lZWTv"
    "vIh3aHnvvIlg77yId2h5IOe8uumUrueUqCAiIu+8jOWAvOS4uiBOb25lIOWImeagvOW8j+WMliAiTm9uZSLvvInvvIzku6Ug"
    "Iu+8myIg6L+e5o6l77ybCmRlZiBfbWlzc2luZ190ZXh0KG1pc3NpbmcpOgogICAgIiIi57uT5p6E5YyW57y65Y+jIOKGkiDk"
    "uIDooYzmlofmnKzvvIjkvZzkuLrpo57ova7nmoQga25vd25fY2x1ZXPvvInjgIIKCiAgICDkv67mlq3pk77vvJrljp/lhYgg"
    "YG1pc3Npbmc9cmVhc29uYCDmiorjgIzkurror53jgI3loZ7ov5sgbWlzc2luZyDlrZfmrrXvvIzogIzliKTlrprlmajkuqfl"
    "h7rnmoQKICAgIFt7bmVlZCwgd2h5LCBjb25mbGljdHN9XSDokL3lnKggZGV0YWlsIOmHjOiiqyBmbHl3aGVlbF9zdGVwIOW/"
    "veeVpeKAlOKAlOS4iua4uOS6p+WHuuS6hgogICAg57uT5p6E77yM5Y206YCB5LiN5Yiw5LiL5ri444CCCiAgICAiIiIKICAg"
    "IGlmIG5vdCBtaXNzaW5nOgogICAgICAgIHJldHVybiAiIgogICAgcmV0dXJuICLvvJsiLmpvaW4oZid7bS5nZXQoIm5lZWQi"
    "LCAiIil977yIe20uZ2V0KCJ3aHkiLCAiIil977yJJwogICAgICAgICAgICAgICAgICAgIGZvciBtIGluIG1pc3NpbmcgaWYg"
    "bS5nZXQoIm5lZWQiKSkKCgojIOeUn+aViOadoeS7tu+8mmNnIOaPkOS+m+WPr+iwg+eUqCBmbHl3aGVlbF9zdGVwIOaXtu+8"
    "jOS7pSBxdWVyee+8iOWBh+WAvOaMieepuuS4su+8ieWJjSAyMDAg5a2X56ym44CBdmVyZGljdOOAgW1pc3Npbmcg5paH5pys"
    "77yI56m65YiZIHJlYXNvbu+8ieOAgWNvbmZsaWN0cyDpnZ4gTm9uZSDliJnkvZwgZGV0YWlsIOWQpuWImSBtaXNzaW5nIOiw"
    "g+eUqO+8m+e7k+aenCBkaWN0IOeahCB1bnJlc29sdmVkX2lkIOecn+WAvOaXtui/lOWbnuWug++8jOWQpuWImeWbnuiQvSBp"
    "ZO+8m+aXoCBmbHl3aGVlbF9zdGVwIOaIluW8guW4uOi/lOWbniBOb25l77ybCmRlZiBfZmlyZV9mbHl3aGVlbChjZywgcXVl"
    "cnksIHZlcmRpY3QsIHJlYXNvbiwgbWlzc2luZywgY29uZmxpY3RzPU5vbmUsCiAgICAgICAgICAgICAgICAgICBzZW5zaXRp"
    "dml0eT1Ob25lKToKICAgICIiIuaKiuWGsueqgeS9nOS4uuOAjOivr+W3ruOAjeaKlee7meefpeivhumjnui9ru+8jOi/lOWb"
    "niB1bnJlc29sdmVkIOadoeebriBpZO+8iOWksei0peS4jemYu+WhnuWGmeWFpe+8ieOAggoKICAgIGNvbmZsaWN0c++8muWG"
    "sueqgeeOsOWcuu+8iOWQqyB0eXBlIC8gd2l0aCAvIHNhbWVfY29uZGl0aW9uIOetieaVsOWAvO+8ie+8jOS+m+S4i+a4uOeU"
    "n+aIkAogICAgYCMg546w5Zy677yaYO+8m21pc3Npbmcg5Y+q5o+P6L+w44CM57y65LuA5LmI44CN77yM5LiN5bim546w5Zy6"
    "77yM5pWF5Lik6ICF6YO96KaB6YCB44CCCgogICAgc2Vuc2l0aXZpdHnvvIhpc3N1ZSAjMjk077yMMjAyNi0xMC0xNO+8ie+8"
    "muiwg+eUqOaWueWGmeWFpeWjsOaYjueahOWvhue6p++8jCoq5b+F6aG7Kirpmo8KICAgIHBheWxvYWQg5LiL5Lyg44CC5L+u"
    "5YmN6L+Z6YeM5LiN5bim5a+G57qn77yM6ICMIHBheWxvYWQg6YeM55qEIHF1ZXJ5IOaYryoq6LCD55So5pa55q2j5paH5YmN"
    "CiAgICAyMDAg5a2XKirvvIzpo57ova7mja7mraTlu7rnmoQgdW5yZXNvbHZlZCDlt6XljZXkvr/mjInnvLrnnIHmoaMgaW50"
    "ZXJuYWwg5piO5paH6JC955uY4oCU4oCUCiAgICDkuIDmnaHlo7DmmI4gcHJpdmF0ZSDnmoTlhpnlhaXooqvliKQgUkVKRUNU"
    "IOWQju+8jOWxnuS4u+WPquaUtuWIsOOAjOWGsueqgeaLkue7neOAje+8jOato+aWh+WNtAogICAg5Lul5piO5paH5Ye6546w"
    "5Zyo5bel5Y2V5q2j5paH44CBKirmlofku7blkI3vvIhpZCDnlLHmraPmlocgc2x1ZyDogIzmnaXvvIkqKuOAgWBfaW5kZXgu"
    "anNvbmAKICAgIOS4jiBgX2F1ZGl0Lmpzb25sYCDph4zvvIzml6Dku6TniYzorr/lrqIgYHN0ZyhvcD10aW1lbGluZSlgICsg"
    "YG1kY2dfZ2V0YCDljbPlj6/or7vjgIIKICAgIOe8uuecgSBOb25l77yd6LCD55So5pa55pyq5aOw5piO77yI5oyJICM4NyDo"
    "tbAgaW50ZXJuYWzvvIzpm7blj5jljJbvvInjgIIKICAgICIiIgogICAgc3RlcCA9IGdldGF0dHIoY2csICJmbHl3aGVlbF9z"
    "dGVwIiwgTm9uZSkKICAgIGlmIHN0ZXAgaXMgTm9uZToKICAgICAgICByZXR1cm4gTm9uZQogICAgdHJ5OgogICAgICAgIHBh"
    "eWxvYWQgPSB7InF1ZXJ5IjogKHF1ZXJ5IG9yICIiKVs6MjAwXSwgImV4cGVjdGVkX3N0YXRlIjogIkFDQ0VQVCIsCiAgICAg"
    "ICAgICAgICAgICAgICAiYWN0dWFsX3N0YXRlIjogdmVyZGljdCwKICAgICAgICAgICAgICAgICAgICJtaXNzaW5nIjogX21p"
    "c3NpbmdfdGV4dChtaXNzaW5nKSBvciByZWFzb24sCiAgICAgICAgICAgICAgICAgICAiZGV0YWlsIjogY29uZmxpY3RzIGlm"
    "IGNvbmZsaWN0cyBpcyBub3QgTm9uZSBlbHNlIG1pc3Npbmd9CiAgICAgICAgIyDlj6rlnKjnnJ/lo7DmmI7ml7bluKbplK7v"
    "vJrnvLrnnIHlhpnlhaXpnaLvvIjmnKrlo7DmmI7lr4bnuqfvvIlwYXlsb2FkIOmAkOmUruS4jeWPmO+8jAogICAgICAgICMg"
    "5LiL5ri4IGZseXdoZWVsX3N0ZXAg55qE57y66ZSu5Zue6JC96Lev5b6E54Wn5pen44CCCiAgICAgICAgaWYgc2Vuc2l0aXZp"
    "dHk6CiAgICAgICAgICAgIHBheWxvYWRbInNlbnNpdGl2aXR5Il0gPSBzZW5zaXRpdml0eQogICAgICAgIHIgPSBzdGVwKHBh"
    "eWxvYWQpCiAgICAgICAgaWYgaXNpbnN0YW5jZShyLCBkaWN0KToKICAgICAgICAgICAgcmV0dXJuIHIuZ2V0KCJ1bnJlc29s"
    "dmVkX2lkIikgb3Igci5nZXQoImlkIikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHJl"
    "dHVybiBOb25lCgoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLQojIOeVmeeXlSAvIOe7n+iuoSAvIOiHquaPj+i/sAojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCgojIOeUn+aViOadoeS7tu+8mmNn"
    "IOS4jiByZWMg57uZ5Ye65pe277yM5bCGIHJlYyDluo/liJfljJbkuLogSlNPTiDooYzov73liqDliLAgY2cucm9vdCDkuIsg"
    "TE9HX0ZJTEXvvJvov73liqDliY3oi6XmnKvlrZfoioLkuI3mmK/mjaLooYzvvIjkuIrkuIDmnaHooqvmiKrlnKjljYrooYzv"
    "vInvvIzlhYjooaXkuIDkuKrmjaLooYzlho3lhpnmnKzmnaHvvIzpgb/lhY3kuKTmnaHnspjov57miJDkuIDooYzkuI3lj6/o"
    "p6PmnpDvvJtPU0Vycm9yIOiiq+WQnuaOie+8jOi/lOWbniByZWPvvJsKZGVmIGxvZyhjZywgcmVjKToKICAgICIiImFwcGVu"
    "ZC1vbmx5IOeVmeeXle+8muavj+adoeWIpOWumuWPr+WuoeiuoeOAgiIiIgogICAgcCA9IG9zLnBhdGguam9pbihjZy5yb290"
    "LCBMT0dfRklMRSkKICAgIHRyeToKICAgICAgICBsaW5lID0ganNvbi5kdW1wcyhyZWMsIGVuc3VyZV9hc2NpaT1GYWxzZSkg"
    "KyAiXG4iCiAgICAgICAgIyBpc3N1ZSAjMjI177ya5YaZ5YWl56uv5Lmf6Ziy57KY6L+e4oCU4oCU6K+75Y+W56uv5a656ZSZ"
    "5Y+q6IO96K6p5Y+w6LSmKirlj6/or7sqKu+8m+aui+ihjOiLpeS4jeihpeaNouihjO+8jAogICAgICAgICMg5pys5p2h5Lya"
    "5LiO5q6L6KGM5ou85oiQ5LiA6KGM77yM5Lik5p2h55WZ55eV5LiA6LW36K+75LiN5Ye65p2l77yI5Lii55qE5pivKirmlrAq"
    "KuiusOW9le+8ieOAggogICAgICAgIGlmIGVuZHNfbWlkX2xpbmUocCk6CiAgICAgICAgICAgIGxpbmUgPSAiXG4iICsgbGlu"
    "ZQogICAgICAgIHdpdGggb3BlbihwLCAiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUo"
    "bGluZSkKICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgIHBhc3MKICAgIHJldHVybiByZWMKCgojIOeUn+aViOadoeS7tu+8"
    "mmNnIOe7meWHuuaXtu+8jOiLpSBjZy5yb290IOS4iyBMT0dfRklMRSDlj6/or7vvvIzliJnlrrnplJnpgJDooYzop6PmnpDv"
    "vIjnqbrooYwv5Z2P6KGML+mdnuWvueixoeihjOi3s+i/h++8jOingSBfcmVjb3Jkc++8ie+8m2xpbWl0IOecn+WAvOaXtui/"
    "lOWbniBvdXRbLWludChsaW1pdCk6XVs6Oi0xXe+8iGludChsaW1pdCk9MCDml7bkuLrlhajpg6jlgJLluo/vvInvvIxsaW1p"
    "dCDkuLrlgYflgLzvvIgwL05vbmUvIiLvvInml7bov5Tlm54gb3V0Wzo6LTFd77yb6Lev5b6E5LiN5Y+v55So5oiWIE9TRXJy"
    "b3Ig6L+U5ZueIFtd77ybCmRlZiBoaXN0b3J5KGNnLCBsaW1pdD0xMDApOgogICAgIiIi5pyA6L+R5Yay56qB5Yik5a6a55WZ"
    "55eV77yI5YCS5bqP77yJ44CCIiIiCiAgICBwID0gb3MucGF0aC5qb2luKGNnLnJvb3QsIExPR19GSUxFKQogICAgaWYgbm90"
    "IG9zLnBhdGguZXhpc3RzKHApOgogICAgICAgIHJldHVybiBbXQogICAgdHJ5OgogICAgICAgIG91dCA9IGxpc3QoX3JlY29y"
    "ZHMocCkpCiAgICBleGNlcHQgT1NFcnJvcjoKICAgICAgICByZXR1cm4gW10KICAgIHJldHVybiBvdXRbLWludChsaW1pdCk6"
    "XVs6Oi0xXSBpZiBsaW1pdCBlbHNlIG91dFs6Oi0xXQoKCiMg55Sf5pWI5p2h5Lu277ya5a656ZSZ6YCQ6KGM6Kej5p6Q6K6h"
    "5pWw77yI56m66KGML+Wdj+ihjC/pnZ7lr7nosaHooYzot7Pov4fvvIzop4EgX3JlY29yZHPvvJtPU0Vycm9yIOW/veeVpeOA"
    "gei3r+W+hOe8uuWkseWImeiuoeaVsOS4uiAw77yJ77yM5q+P6KGMIHRvdGFsIOWKoCAxIOW5tuaMiSByLmdldCgidmVyZGlj"
    "dCIp77yI57y66ZSu5Y2zIE5vbmUg6ZSu77yJ5LiOIGVtb3Rpb25hbC5iaWFzIOS4uuecn+WAvOaXtueahCBiIOe0r+WKoO+8"
    "m+WPpui/lOWbniB1bnBhcnNhYmxlID0g6K+75LiN5Ye65p2l55qE6KGM5pWw77yISlNPTiDlnY/ooYwg77yLIOmdnuWvueix"
    "oeihjO+8ie+8jOS9v+iviuaWremdouS4jeWboOWdj+ihjOiAjOWBh+aAp+WBpeW6t++8m+i/lOWbniB7J3JlY29yZHMnLCd1"
    "bnBhcnNhYmxlJywnYnlfdmVyZGljdCcsJ2J5X2JpYXMnLCdtYXhfc2NhbicsJ21heF9kZXB0aCcsJ21pbl9nYWluJ33vvIzl"
    "kI7kuInogIXlj5bmqKHlnZfluLjph48gTUFYX1NDQU4vTUFYX0RFUFRIL01JTl9HQUlO77ybCmRlZiBzdW1tYXJ5KGNnKToK"
    "ICAgICIiIuWGsueqgemdouaxh+aAu++8iOa1geW8j+iuoeaVsO+8jOS+myBoZWFsdGgg5a6h6K6h77yJ44CCIiIiCiAgICBw"
    "ID0gb3MucGF0aC5qb2luKGNnLnJvb3QsIExPR19GSUxFKQogICAgYnlfdmVyZGljdCwgYnlfYmlhcywgdG90YWwgPSB7fSwg"
    "e30sIDAKICAgIHN0YXRzID0geyJ1bnBhcnNhYmxlIjogMH0KICAgIHRyeToKICAgICAgICBmb3IgciBpbiBfcmVjb3Jkcyhw"
    "LCBzdGF0cyk6CiAgICAgICAgICAgIHRvdGFsICs9IDEKICAgICAgICAgICAgdiA9IHIuZ2V0KCJ2ZXJkaWN0IikKICAgICAg"
    "ICAgICAgYnlfdmVyZGljdFt2XSA9IGJ5X3ZlcmRpY3QuZ2V0KHYsIDApICsgMQogICAgICAgICAgICBiID0gKHIuZ2V0KCJl"
    "bW90aW9uYWwiKSBvciB7fSkuZ2V0KCJiaWFzIikKICAgICAgICAgICAgaWYgYjoKICAgICAgICAgICAgICAgIGJ5X2JpYXNb"
    "Yl0gPSBieV9iaWFzLmdldChiLCAwKSArIDEKICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgIHBhc3MKICAgIHJldHVybiB7"
    "InJlY29yZHMiOiB0b3RhbCwgInVucGFyc2FibGUiOiBzdGF0c1sidW5wYXJzYWJsZSJdLAogICAgICAgICAgICAiYnlfdmVy"
    "ZGljdCI6IGJ5X3ZlcmRpY3QsICJieV9iaWFzIjogYnlfYmlhcywKICAgICAgICAgICAgIm1heF9zY2FuIjogTUFYX1NDQU4s"
    "ICJtYXhfZGVwdGgiOiBNQVhfREVQVEgsCiAgICAgICAgICAgICJtaW5fZ2FpbiI6IE1JTl9HQUlOfQoKCiMg55Sf5pWI5p2h"
    "5Lu277ya5pegIHJlcXVpcmVkIOW9ouWPgu+8jOiwg+eUqOWNs+i/lOWbnuW8leeUqCBFTU9fQVZPSUQvRU1PX0FQUFJPQUNI"
    "44CBVkVSRElDVFPjgIFDTEFTSF9ISUdIL0NMQVNIX0xPV+OAgVNBTUVfQ09ORF9ISUdIL1NMT1RfSElHSC9DT05DTFVTSU9O"
    "X1NBTUXjgIFNQVhfREVQVEgvTUFYX05PREVTL01JTl9HQUlOIOetieaooeWdl+e6p+W4uOmHj+eahOiHquaPj+i/sOWtl+WF"
    "uO+8mwpkZWYgY2F0YWxvZygpOgogICAgIiIi6Ieq5o+P6L+w77ya5LiJ57qn5Yaz562WICsg5Zub5oCBICsg6YCS5b2S57qm"
    "5p2f77yI5L6bIE1DUCAvIOaWh+aho+WvueeFp+mqjOivge+8ieOAgiIiIgogICAgcmV0dXJuIHsKICAgICAgICAibGV2ZWxz"
    "IjogewogICAgICAgICAgICAiTDBfZW1vdGlvbiI6IHsKICAgICAgICAgICAgICAgICJ0aGVvcnkiOiAi5oOF57uqID0g5L+h"
    "5oGv5beu5LqM6Zi25Y+Y5YyWIGTCskQvZHTCsu+8iOaZuuiDveiuuiDCp+WNgeS4gO+8iSIsCiAgICAgICAgICAgICAgICAi"
    "b3V0cHV0cyI6IFsiYXBwcm9hY2hpbmciLCAic3RhYmxlIiwgImF2b2lkaW5nIl0sCiAgICAgICAgICAgICAgICAiY29uc3Ry"
    "YWludCI6ICLni6znq4vpgJrpgZPvvIzkuI3lj4LkuI7kv6Hku7sv6LWE5qC86K6h566X77yM5Y+q5YGa5rWB56iL6LCD5bqm"
    "IiwKICAgICAgICAgICAgICAgICJ0aHJlc2hvbGRzIjogeyJhdm9pZCI6IEVNT19BVk9JRCwgImFwcHJvYWNoIjogRU1PX0FQ"
    "UFJPQUNIfSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgIkwxX3JlZmxlY3QiOiB7CiAgICAgICAgICAgICAgICAidGhl"
    "b3J5IjogIuWPjemimCA9IOmihOa1i+S4juS6i+WunuWGsueqge+8iOadoeS7tuiuuuS4g+aTjeS9nO+8iSIsCiAgICAgICAg"
    "ICAgICAgICAiY2hlY2tzIjogWyJzZWxmX25lZ2F0aW9uIiwgImRpc2NpcGxpbmUiLCAiY29uZGl0aW9uX2NsYXNoIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgInNhbWVfY29uZGl0aW9uX2RpdmVyZ2VuY2UiXSwKICAgICAgICAgICAgICAgICJy"
    "ZWxhdGlvbnMiOiB7CiAgICAgICAgICAgICAgICAgICAgImNvbmRpdGlvbl9jbGFzaCI6ICLot6jkvqfmr5Tlr7nvvIjmlrDm"
    "raPihpTml6fotJ8gLyDmlrDotJ/ihpTml6fmraPvvIk9IOadoeS7tuS6kuaWpe+8iOWPjemimO+8iSIsCiAgICAgICAgICAg"
    "ICAgICAgICAgInNhbWVfY29uZGl0aW9uX2RpdmVyZ2VuY2UiOiAi5ZCM5L6n5q+U5a+577yI5paw5q2j4oaU5pen5q2jIC8g"
    "5paw6LSf4oaU5pen6LSf77yJIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIu+8"
    "iyBDQ0cg57uT6K665qe9ID0g5ZCM5p2h5Lu256m66Ze05YaF55qE5Y+W5YC85YiG5q2n77yI55+b55u+77yJIiwKICAgICAg"
    "ICAgICAgICAgIH0sCiAgICAgICAgICAgICAgICAiY29uY2x1c2lvbl9ub3JtYWxpemF0aW9uIjogIue7k+iuuuavlOWvueS4"
    "pOS+p+WQjOS4gOWll+epuueZveW9kuS4gOWMliIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAi77yIJyAnLmpvaW4oeC5zcGxpdCgpKe+8iSsg5Y6756m655m95ZCO6YCQ5a2XIgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICLnm7jlkIwg4oeSIOW/heWIpOmHjeWkje+8iEg477yJIiwKICAgICAgICAgICAgICAg"
    "ICJ2ZXJkaWN0cyI6IGxpc3QoVkVSRElDVFMpLAogICAgICAgICAgICAgICAgInRocmVzaG9sZHMiOiB7ImhpZ2giOiBDTEFT"
    "SF9ISUdILCAibG93IjogQ0xBU0hfTE9XLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgInNhbWVfY29uZGl0aW9u"
    "IjogU0FNRV9DT05EX0hJR0gsICJzbG90IjogU0xPVF9ISUdILAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgImNv"
    "bmNsdXNpb25fc2FtZSI6IENPTkNMVVNJT05fU0FNRX0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgICJMMl9yZWN1cnNp"
    "dmVfcmVmbGVjdCI6IHsKICAgICAgICAgICAgICAgICJ0aGVvcnkiOiAi6YCS5b2S5Y+X5rex5bqmL+iKgueCueaVsC/lvqrn"
    "jq8v5L+h5oGv5aKe55uK6Zeo5qeb57qm5p2f77yI5pm66IO96K66IDoyNzPvvIkiLAogICAgICAgICAgICAgICAgIm1heF9k"
    "ZXB0aCI6IE1BWF9ERVBUSCwgIm1heF9ub2RlcyI6IE1BWF9OT0RFUywKICAgICAgICAgICAgICAgICJtaW5fZ2FpbiI6IE1J"
    "Tl9HQUlOLAogICAgICAgICAgICAgICAgInN0b3BfcmVhc29ucyI6IFsicmVzb2x2ZWQiLCAiZ2Fpbl9iZWxvd190aHJlc2hv"
    "bGQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZGVwdGhfZXhjZWVkZWQiLCAibm9kZV9idWRnZXQiLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZnJvbnRpZXJfZXhoYXVzdGVkIl0sCiAgICAgICAgICAgIH0sCiAg"
    "ICAgICAgfSwKICAgICAgICAiYXV0b19mbHl3aGVlbCI6IHsKICAgICAgICAgICAgInRoZW9yeSI6ICLnn6Xor4bpo57ova7v"
    "vJror6/lt64g4oaSIOihpeadoeS7tiDihpIg57uT5p6E5pu05paw77yI5pm66IO96K66IDo3MjXvvIkiLAogICAgICAgICAg"
    "ICAjIEgxMeKRpe+8iDIwMjYtMDktMzDvvInvvJrlu7rljZXlj6rpmZAqKuecn+WGsueqgSoq77yIUkVKRUNU77yJ44CCREVG"
    "RVIg5pivCiAgICAgICAgICAgICMg44CM5p2h5Lu25LqS5palL+mDqOWIhuimhuebluOAgeW+heehruiupOOAje+8jEJMSU5E"
    "U1BPVCDmmK/jgIzmo4DmtYvliY3mj5DkuI3lrZjlnKgKICAgICAgICAgICAgIyDvvIjml6DoioLngrnlj6/kuI7mr5Tlr7nv"
    "vInjgI3igJTigJTkuKTogIXpg73kuI3mmK/jgIzlt7LliKTlrprlhrLnqoHjgI3vvIzoh6rliqjokL0gdW5yZXNvbHZlZAog"
    "ICAgICAgICAgICAjIOS8muaKiuW+heehruiupOmhueS4juaXoOazleavlOWvuemhueWGmeaIkOW+heWKnuW3peWNle+8iOS4"
    "lCBCTElORFNQT1Qg5Zyo56m65bqT5LiK5oGS5oiQ56uL77yMCiAgICAgICAgICAgICMg5Y2z5q+P5YaZ56ys5LiA5p2h5YaF"
    "5a655bCx5bu65LiA5byg5bel5Y2V77yJ44CC5Y+v5aSN5qC455qE546w5Zy677ya5pys6L2uCiAgICAgICAgICAgICMgYGNv"
    "bnNpc3RlbmN5LmNoZWNrKC4uLiwgbm9uX2FwcGxpY2FibGVfY29uZGl0aW9ucz1bIuaXoCJdKWAg5a6e5rWLCiAgICAgICAg"
    "ICAgICMgREVGRVIvc3RyZW5ndGg9MS4wIOKGkiDlu7rljZUgdW5yXzlhZjQ4MDMzODHvvIzogIzlkIzkuIDlhoXlrrnkuI3k"
    "vKDor6XliJfooagKICAgICAgICAgICAgIyDliJkgQUNDRVBULzAuMC/ml6DljZXigJTigJToh6rliqjlu7rljZXmiorjgIzo"
    "r6/liKTjgI3nm7TmjqXlm7rljJbmiJDkuoblvoXlip7jgIIKICAgICAgICAgICAgInRyaWdnZXJzX29uIjogbGlzdChGTFlX"
    "SEVFTF9UUklHR0VSUyksCiAgICAgICAgfSwKICAgICAgICAiZGlzY2lwbGluZV9kZXRlY3Rpb24iOiB7InRhZ3MiOiBsaXN0"
    "KERJU0NJUExJTkVfVEFHUyksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJpZF9wcmVmaXhlcyI6IFsiZGlz"
    "Y2lwbGluZV8iLCAid29ya19kaXNjaXBsaW5lIl19LAogICAgICAgICJob25lc3RfYm91bmRhcnkiOiAi5p2h5Lu257qn77yI"
    "57uT5p6E5YyW77yJ5Yay56qB5qOA5rWL77yM6Z2e6K+t5LmJ6JW05ZCr6K+B5piO77yb5peg5rOV5q+U5a+55pe2IEJMSU5E"
    "U1BPVCIsCiAgICB9"
)

def _embedded_before():
    """内嵌的修复前源（blob 3a6fea35…）。**不依赖 git**，CI 上必可得。"""
    try:
        return _b64.b64decode("".join(_BEFORE_B64.split())).decode("utf-8")
    except Exception:                 # noqa: BLE001
        return None

def _before_source():
    """取修复前的 consistency.py 源码文本 + 说明。

    issue #189 的判别力必须自证：守卫要有「改前真红」的原形。取源顺序：
      ① git log -S 定位引入提交取其父版本（本地：改动已提交，最权威）；
      ② 沿 --all 扫可达提交取第一个不含本件标记的 blob；
      ③ HEAD（本地：改动尚未提交，HEAD 即改前）；
      ④ **内嵌夹具**（blob 3a6fea35…，与本 PR 推送前基线逐字节一致）——CI 浅克隆
         （depth=1、HEAD 为 pull/<n>/merge 中间提交）时只有这一条路可达。
    每一级都要求文本**不含本件标记**；含标记说明取到了已修复版本，继续往下找。
    全失败才返回 (None, 原因)，由调用方判红（fail-closed，绝不假绿）。
    """
    try:
        log = _git("log", "-S", _MARK, "--format=%H", "--", _REL)
        shas = [x.strip() for x in log.stdout.split() if x.strip()]
        if shas:
            rev = shas[-1] + "^"
            how = "引入提交 %s 的父版本" % shas[-1][:8]
            got = _git("show", "%s:%s" % (rev, _REL))
            if got.returncode == 0 and _is_before(got.stdout):
                return got.stdout, how
        revs = _git("rev-list", "--all", "--max-count=200").stdout.split()
        for sha in revs:
            got = _git("show", "%s:%s" % (sha, _REL))
            if got.returncode == 0 and _is_before(got.stdout):
                return got.stdout, "可达提交 %s" % sha[:8]
        got = _git("show", "HEAD:%s" % _REL)
        if got.returncode == 0 and _is_before(got.stdout):
            return got.stdout, "HEAD（本改动尚未提交）"
    except Exception:                 # noqa: BLE001
        pass
    emb = _embedded_before()
    if _is_before(emb):
        return emb, "内嵌夹具（blob 3a6fea35，git 历史不可达时的兜底）"
    return None, "git 历史与内嵌夹具均取不到不含本件标记的版本"

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
