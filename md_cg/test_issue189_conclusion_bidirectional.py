# -*- coding: utf-8 -*-
"""issue #189 守卫：同条件结论比对须**双向达标**（单向覆盖的子串盲区）。

现象：同生效条件 + 同结论槽下，旧结论「不启用缓存」再写「启用缓存」，
`consistency.check` 返回 ACCEPT/无冲突 —— 因为判据只量「新结论的词在旧结论里
出现多少」，新结论整段是旧结论的子串时恒为 1.0，被当成重复。反方向能检出，
判据不对称 ⇒ 撤销禁令、去掉否定词、末位数字少一位这三类常见更正落进盲区。

本守卫钉两件事：
  C1-C3 缺陷三例必须判 DEFER，且 `conclusion_overlap` 读数钉值；
  K1-K7 既有七例（逐字重复 / 纯空白 / 反方向 / 数字在中间 / 同槽不同值 /
        不同结论槽 / 不同生效条件）判定与读数**一字不变**。

用法：
    python -X utf8 -m md_cg.test_issue189_conclusion_bidirectional
    python -X utf8 -m md_cg.test_issue189_conclusion_bidirectional --mutate=<名>
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SRC = os.path.join(_HERE, "consistency.py")

_FAILS = []


def _check(name, ok, detail=""):
    if not ok:
        _FAILS.append(name)
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name,
                          "" if ok else "  · " + str(detail)[:150]))


def _ccg(fn, exe, cond="生产环境", sb="服务参数"):
    """标准六要素写法；两节点只差 `# 执行`（或 `# 生效条件`/`# 子功能`）。"""
    return ("# 功能名：%s" + chr(10) + "# 生效条件：%s" + chr(10) +
            "# 子功能：%s" + chr(10) + "# 执行：%s" + chr(10) +
            "# 验证方式：test" + chr(10) + "# 不适用条件：无" + chr(10)) % (
                fn, cond, sb, exe)


def _write_pair(old, new):
    """隔离库写两条节点，返回 (第二次响应, 第一次响应)。"""
    d = tempfile.mkdtemp(prefix="i189_")
    env = {"MDCG_ROOT": d + "/brain", "MDCG_STATE_ROOT": d + "/state",
           "MDCG_AUX_ROOT": d + "/auxstore", "MDCG_DATA_ROOT": d + "/data",
           "MDCG_EXPORT_ROOT": d, "MDCG_TOKEN_FILE": d + "/auxstore/tokens.json"}
    with patch.dict(os.environ, env), contextlib.redirect_stderr(io.StringIO()):
        from md_cg import tokens
        from md_cg.mdcos import MdCGSecure
        from md_cg.mcp_server import call_tool
        tf = env["MDCG_TOKEN_FILE"]
        tok = tokens.issue("designer", actor="guard189", path=tf)["token"]
        g = MdCGSecure(env["MDCG_ROOT"],
                       principal=tokens.verify_token(tok, path=tf), autoflush=1)
        w = lambda nid, c: call_tool(g, "cg", {"op": "write", "node_id": nid,
                                               "content": c, "layer": "knowledge",
                                               "content_kind": "text"})
        r1 = w("old", old)
        r2 = w("new", new)
        g.close()
    return r2, r1


def _div(r2):
    c = r2.get("consistency") or {}
    div = [x for x in (c.get("conflicts") or [])
           if x.get("type") == "same_condition_divergence"]
    return c, div


# (名, 旧结论, 新结论, 期望判定, 期望 conclusion_overlap 或 None=无分歧)
DEFECT = [
    ("C1 去否定词（不启用缓存→启用缓存）", _ccg("缓存开关", "不启用缓存"),
     _ccg("缓存开关", "启用缓存"), "DEFER", 0.4),
    ("C2 撤销禁令（禁止直接推送到 main 分支→直接推送到 main 分支）",
     _ccg("推送规则", "禁止直接推送到 main 分支"),
     _ccg("推送规则", "直接推送到 main 分支"), "DEFER", 0.6976),
    ("C3 末位数字少一位（超时 300→超时 30）", _ccg("请求超时", "超时 300"),
     _ccg("请求超时", "超时 30"), "DEFER", 0.5833),
]

KEEP = [
    ("K1 逐字重复仍 ACCEPT（该合并，不判分歧）", _ccg("缓存开关", "启用缓存"),
     _ccg("缓存开关", "启用缓存"), "ACCEPT", None),
    ("K2 仅空白差异仍 ACCEPT（归一化后逐字相同）", _ccg("缓存开关", "启用缓存"),
     _ccg("缓存开关", "启用  缓存"), "ACCEPT", None),
    ("K3 反方向（旧⊂新）仍 DEFER 且读数不变", _ccg("缓存开关", "启用缓存"),
     _ccg("缓存开关", "不启用缓存"), "DEFER", 0.4),
    ("K4 数字在中间仍 DEFER 且读数不变", _ccg("重试次数", "最多重试 3 次后放弃"),
     _ccg("重试次数", "最多重试 5 次后放弃"), "DEFER", 0.7424),
    ("K5 同槽不同值仍 DEFER 且读数不变", _ccg("缓存开关", "启用缓存"),
     _ccg("缓存开关", "禁用缓存"), "DEFER", 0.375),
    ("K6 不同结论槽不判分歧", _ccg("缓存开关", "启用缓存"),
     _ccg("缓存开关", "启用缓存", sb="存储参数"), "ACCEPT", None),
    ("K7 不同生效条件不判分歧", _ccg("缓存开关", "启用缓存", cond="生产环境"),
     _ccg("缓存开关", "启用缓存", cond="测试环境"), "ACCEPT", None),
    # K8 是唯一能证明「正向未达标时不算反向」这条守卫**不是空转**的用例：
    # 正向 0.4333 < 0.95（本来就判分歧），反向 0.2548 更低 —— 若无条件取 min，
    # 读数会被压成 0.2548。实测其余 14 个自然用例的「反向 >= 正向」，V4 对它们
    # 全无影响。报告把这例称为「偶然检出」（遗留项 3），此处把该读数钉住。
    ("K8 正向未达标时读数不被反向压低（偶然检出例）",
     _ccg("删除权限", "不允许在生产库上直接删除日志"),
     _ccg("删除权限", "允许在生产库上直接删除日志"), "DEFER", 0.4333),
]


def run_cases(group, cases):
    print("[%s]" % group)
    for name, old, new, exp_v, exp_c in cases:
        r2, r1 = _write_pair(old, new)
        c, div = _div(r2)
        got_v = c.get("verdict")
        got_c = round(div[0]["conclusion_overlap"], 4) if div else None
        ok = (got_v == exp_v) and (got_c == exp_c)
        # DEFER 只提示不拦截：两节点都必须落库（否则「提示」变成了「拒绝」）
        landed = bool(r1.get("committed")) and bool(r2.get("committed"))
        _check(name, ok and landed,
               "verdict=%s(期望%s) concl=%s(期望%s) 两节点落库=%s"
               % (got_v, exp_v, got_c, exp_c, landed))


def main():
    print("=" * 66)
    print("issue #189 守卫：同条件结论比对须双向达标")
    print("=" * 66)
    run_cases("C 缺陷面（修前 ACCEPT/无冲突，修后 DEFER）", DEFECT)
    print()
    run_cases("K 保持不变面（判定与读数一字不变）", KEEP)
    print()
    n_ok = len(DEFECT) + len(KEEP) - len(_FAILS)
    print("==== #189 结果：%d 通过 / %d 失败 ===="
          % (n_ok, len(_FAILS)))
    if _FAILS:
        print("失败项：" + " ｜ ".join(_FAILS))
    return 1 if _FAILS else 0


# ---------------------------------------------------------------- 变异
# 每条变异都让**指定**用例转红；只断言「变红了」而不指定红项，会让
# 「恰好因为别的原因变红」蒙混过关。
_MUT = [
    ("V1 撤掉反向（回到单向覆盖 = 本件病象）",
     ["                    if concl >= CONCLUSION_SAME:",
      "                        concl = min(concl, _cov(",
      "                            expand_query_terms_weighted(_norm_ws(e_body)),",
      "                            _norm_ws(n_concl)))"],
     [], ("C1", "C2", "C3")),
    ("V2 反向写成正向（量自己而非旧结论）",
     ["                            _norm_ws(n_concl)))"],
     ["                            _norm_ws(e_body)))"], ("C1", "C2", "C3")),
    ("V3 min 写成 max",
     ["                        concl = min(concl, _cov("],
     ["                        concl = max(concl, _cov("], ("C1", "C2", "C3")),
    ("V4 去掉「正向达标才算反向」守卫（无条件反向）",
     ["                    if concl >= CONCLUSION_SAME:"],
     ["                    if True:  # 变异"], ("K8",)),
]


def _mutate(name):
    hits = [m for m in _MUT if m[0].startswith(name) or m[0].split()[0] == name]
    if not hits:
        print("未知变异名：%s" % name)
        print("可用：" + " ｜ ".join(m[0].split()[0] for m in _MUT))
        return 2
    label, old_lines, new_lines, exp_red = hits[0]
    orig = io.open(_SRC, encoding="utf-8", newline="").read()
    # 锚点跨行时必须按**文件实际行尾**拼接：consistency.py 是 CRLF，用 chr(10) 拼
    # 会得到 0 处命中（V1 第一版就是这么假红的——报「锚点不唯一」而非「变异无效」）。
    _nl = chr(13) + chr(10) if (chr(13) + chr(10)) in orig else chr(10)
    old = _nl.join(old_lines)
    new = _nl.join(new_lines)
    if orig.count(old) != 1:
        print("[%s] 锚点不唯一（%d 处）——源码已漂移，请先核对" % (label, orig.count(old)))
        return 2
    mutated = orig.replace(old, new)
    if mutated == orig:
        print("[%s] 变异未改变源码" % label)
        return 2
    # 同尺寸变异落在同一 mtime 秒内时 CPython 会复用旧 .pyc ⇒ 必须禁写并清缓存
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    cache = os.path.join(_HERE, "__pycache__")
    try:
        io.open(_SRC, "w", encoding="utf-8", newline="").write(mutated)
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith("consistency."):
                    os.remove(os.path.join(cache, f))
        p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                            "md_cg.test_issue189_conclusion_bidirectional"],
                           cwd=_REPO, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           shell=False, timeout=900)
    finally:
        io.open(_SRC, "w", encoding="utf-8", newline="").write(orig)
        back = io.open(_SRC, encoding="utf-8", newline="").read()
    out = (p.stdout or "") + (p.stderr or "")
    fails = []
    for ln in out.splitlines():
        if ln.strip().startswith("失败项："):
            fails = [x.strip() for x in ln.split("失败项：", 1)[1].split("｜")]
    red = p.returncode != 0 and any(x.startswith(exp_red) for x in fails)
    print("[%s] rc=%s 红项=%s" % (label, p.returncode, fails or "(无)"))
    print("  还原一致=%s ｜ 期望红项 %s ⇒ %s"
          % (back == orig, list(exp_red), "PASS" if red else "FAIL"))
    return 0 if red else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.startswith("--mutate")]
    if args:
        val = args[0].split("=", 1)[1] if "=" in args[0] else ""
        sys.exit(_mutate(val))
    sys.exit(main())
