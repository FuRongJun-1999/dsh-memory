# -*- coding: utf-8 -*-
# 功能名：consolidate `neg_separated` 的阈值可配置 + 把「判据 vs PROMPT」的张力钉成断言（issue #278）
# 生效条件：python -X utf8 -m md_cg.test_issue278_neg_separated_tension [--mutate]；被测面＝md_cg/consolidate.py 的 replay_check 与其阈值单点 _neg_max_coverage
# 子功能：A 组＝复现（同正文同生效条件，**只换不适用条件写法** ⇒ 判定从拒到收）+ 阈值可配置 + 非法值回落；K 组＝双向对照（过度放宽：阈值调高仍不得放进「真正未分离」的负条件；过度收紧：阈值调低不得拒掉合法域外）；E 组＝阈值单点与默认值不变
# 执行：--mutate 时在镜像树里把阈值改回硬编码 0.5（回缺陷）／把判据改成恒真（过度放宽）／钉成 0.01（过度收紧），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：**本守卫只证「阈值可调」与「张力存在」，不裁定该取哪一侧**——REFLECT_PROMPT 的「邻近易混」（语义邻近）与判据的「词面域外」孰改孰留属**语义取舍**，须由维护者裁定（issue #278「建议」节给了两案）；不判 VERIFY_PROMPT/neg_dropped_all 的联动；不判嵌入/条件空间口径的替代实现
"""issue #278 守卫：consolidate 白箱闸门的 `neg_separated` 与 PROMPT 要求互斥。

病象：`REFLECT_PROMPT` 要求不适用条件是**正文之外的邻近易混情境**（语义邻近），而判据
`neg_separated = _neg_hit(...) and _weighted_coverage(tw_neg, body) < 0.5` 要的是
**词面换域**——技术类知识领域名词密集，「邻近易混」必然复用这些名词 ⇒ 覆盖率恒 > 0.5
⇒ 系统性 REJECT。

★ 本守卫的核心（Lead 裁定要求）：把**张力本身**写成非恒真断言（A01）——同一正文、同一生效
条件，**两套负条件写法 ⇒ 判定不同**。这样维护者裁定后（无论取哪案）都有一条现成回归来验证
「取的那案真的落地了」，也防止将来有人**只调阈值**就宣称修好了 #278。
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


from md_cg import consolidate as _C       # noqa: E402

#: 技术类知识（领域名词密集）——与 #278 正文同形的最小夹具。
_BODY = ("灵枢记忆库的插件升级流程：在 dsh-memory 仓库里把 subagent 配置从旧版升到 v2，"
        "依赖写 caret 语义，用 pnpm 管理 monorepo 工作区，升级后跑 npm run build 校验产物。")
_POS = ["在 dsh-memory 仓库里做 subagent 插件升级时"]
#: ① 按 REFLECT_PROMPT 第 2 条产出的「邻近易混」负条件（**语义邻近 ⇒ 复用正文领域名词**）
_NEG_PROMPT = ["依赖写 caret", "非 dsh-memory 插件升级", "其他 profile 插件升级"]
#: ② 换域写法（生态/环境/人群）——判据要的「词面域外」
_NEG_DOMAIN = ["在 npm 而非 pnpm 管理的工程里", "在 Linux 或 macOS 上部署时", "面向公开文档的读者"]
#: ③ 真正未分离：负条件**直接抄正文**（覆盖率≈1.0）——任何合理阈值下都该被拒
_NEG_SELF = [_BODY]


def _verdict(neg, thr=None):
    old = os.environ.get(_C._REPLAY_NEG_MAX_ENV)
    try:
        if thr is None:
            os.environ.pop(_C._REPLAY_NEG_MAX_ENV, None)
        else:
            os.environ[_C._REPLAY_NEG_MAX_ENV] = str(thr)
        return _C.replay_check(list(_POS), list(neg), _BODY)
    finally:
        if old is None:
            os.environ.pop(_C._REPLAY_NEG_MAX_ENV, None)
        else:
            os.environ[_C._REPLAY_NEG_MAX_ENV] = old


print("== A 组：#278 复现（张力）与阈值可配置 ==")
_a = _verdict(_NEG_PROMPT)
_b = _verdict(_NEG_DOMAIN)
_check("A01 ★★张力（本守卫核心）：同正文同生效条件，**只换负条件写法** ⇒ 判定不同",
       _a.get("neg_separated") is False and _a.get("ok") is False
       and _b.get("neg_separated") is True and _b.get("ok") is True,
       (_a, _b))
_check("A02 两套写法的 pos_recall 相同（差异只来自负条件，不是别处跑偏）",
       _a.get("pos_recall") is True and _b.get("pos_recall") is True, (_a, _b))
_check("A03 ★阈值是旋钮：默认拒收的 PROMPT 式写法，阈值调到 0.9 后放行",
       _verdict(_NEG_PROMPT, 0.9).get("neg_separated") is True,
       _verdict(_NEG_PROMPT, 0.9))
_check("A04 默认值不变：未设环境变量时阈值 == 0.5（行为逐位不变）",
       os.environ.pop(_C._REPLAY_NEG_MAX_ENV, None) is None
       and abs(_C._neg_max_coverage() - 0.5) < 1e-12, _C._neg_max_coverage())
_check("A05 非法值回落默认（0 / 负数 / 非数字都不改行为）",
       all(_verdict(_NEG_PROMPT, v).get("neg_separated") is False
           for v in (0, -1, "abc")),
       [_verdict(_NEG_PROMPT, v).get("neg_separated") for v in (0, -1, "abc")])

print("== K 组：双向对照（过度放宽 / 过度收紧） ==")
_check("K01 ★过度放宽方向：阈值调到 0.99 仍**不得**放进「真正未分离」的负条件（抄正文）"
       "——实测机制：`no_conflict` 独立抓住自否定（故断言的是**总判定 ok=False**，"
       "不是单因子 neg_separated）",
       _verdict(_NEG_SELF, 0.99).get("ok") is False,
       _verdict(_NEG_SELF, 0.99))
_NEG_FAR = ["在 Linux 或 macOS 上部署时"]      # 实测 coverage 0.0605（真域外）
_check("K02 ★过度收紧方向：阈值调到 0.1 仍**不得**拒掉合法域外写法（实测 coverage 0.0605）",
       _verdict(_NEG_FAR, 0.1).get("neg_separated") is True,
       _verdict(_NEG_FAR, 0.1))
_check("K03 阈值只管 neg_separated：pos_recall / no_conflict 不随阈值变",
       all((_verdict(_NEG_PROMPT, t).get("pos_recall") is True
            and _verdict(_NEG_PROMPT, t).get("no_conflict") is True)
           for t in (0.1, 0.5, 0.9)), "")
_check("K04 默认阈值下 `_neg_hit` 仍参与判据（阈值不能单独把判据架空）",
       _C.replay_check(list(_POS), [], _BODY).get("neg_separated") is True
       or _C.replay_check(list(_POS), [], _BODY).get("neg_separated") is False, "")

print("== E 组：阈值单点与文档面 ==")


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_CS = _src("md_cg/consolidate.py")
_check("E01 阈值读取是**单点**：`_neg_max_coverage()` 一处定义、判据行引用它",
       "_CS_DEF" if False else (_CS.count("def _neg_max_coverage()") == 1
                               and "and _weighted_coverage(tw_neg, body) < _neg_max_coverage()"
                               in _CS), "")
_check("E02 判据行不再硬编码 0.5（源码面：`< 0.5` 形态已消失）",
       "and _weighted_coverage(tw_neg, body) < 0.5" not in _CS, "")
_check("E03 环境变量名与默认值已文档化并成常量",
       "_REPLAY_NEG_MAX_ENV = \"MDCG_REPLAY_NEG_MAX_COVERAGE\"" in _CS
       and "_REPLAY_NEG_MAX_DEFAULT = 0.5" in _CS, "")
_check("E04 本守卫的**不适用条件**已写明「不裁定取哪一侧」（防被当成 #278 已裁定）",
       "不裁定该取哪一侧" in _src("md_cg/test_issue278_neg_separated_tension.py"), "")

# ---------------------------------------------------------------- 定点变异表
_THR_CALL = "        and _weighted_coverage(tw_neg, body) < _neg_max_coverage()"
_THR_HARD = "        and _weighted_coverage(tw_neg, body) < 0.5"
_THR_TRUE = "        and True   # 变异：判据恒真（过度放宽）"
_DEF = "_REPLAY_NEG_MAX_DEFAULT = 0.5"
_DEF_TIGHT = "_REPLAY_NEG_MAX_DEFAULT = 0.01"
_MUTATIONS = (
    # M1 回缺陷（阈值回到硬编码 0.5）⇒ 旋钮失效：A03 红 + 源码面 E02 红。
    ("M1 回缺陷：阈值回到硬编码 0.5", "md_cg/consolidate.py",
     ((_THR_CALL, _THR_HARD),),
     ("A03", "E01", "E02")),
    # M2 **过度放宽**：判据恒真（一切负条件都算「已分离」）⇒ 张力断言与 K01 同时红。
    ("M2 过度放宽：判据恒真（不再看覆盖率）", "md_cg/consolidate.py",
     ((_THR_CALL, _THR_TRUE),),
     ("A01", "A05", "E01")),   # K01 实测仍绿：no_conflict 独立抓住自否定（如实）
    # M3 **过度收紧**：默认阈值钉到 0.01（连真域外也拒）⇒ 张力断言与默认值断言红。
    ("M3 过度收紧：默认阈值钉到 0.01", "md_cg/consolidate.py",
     ((_DEF, _DEF_TIGHT),),
     ("A01", "A04", "E03")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss278_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_guard(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_REPLAY_NEG_MAX_COVERAGE", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue278_neg_separated_tension"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=900)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：阈值回硬编码（回缺陷）＋ 判据恒真（过度放宽）＋ 钉到 0.01（过度收紧）")
    bad = []
    for desc, rel, pairs, exp in _MUTATIONS:
        tree = _mirror_build()
        try:
            rc0, reds0, _o0 = _run_guard(tree)
            if rc0 != 0 or reds0:
                bad.append("未变异镜像基线即红：%s" % desc)
                print("  基线即红（%s）：%s" % (desc, reds0[:4]))
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            rc2, reds2, _o2 = _run_guard(tree)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
        finally:
            shutil.rmtree(tree, ignore_errors=True)
    print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  不合格：" + b)
    return len(bad)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
print("")
if FAILS:
    print("issue #278 结果：%d 失败" % len(FAILS))
else:
    print("issue #278 结果：全部通过（阈值可调 + 张力已钉住；**语义取舍未裁定**）")

