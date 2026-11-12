# -*- coding: utf-8 -*-
# 功能名：写入硬上限必须量全部入参字段，而不是只量 content（issue #324）
# 生效条件：python -X utf8 -m md_cg.test_issue324_write_size_fields [--mutate]；被测面=md_cg/writepipe.py 的 oversize_response
# 子功能：A 组=超限必须被拒（content / node_id 128 契约 / node_id 超长 / tags / 其它字段）；K 组=正常与边界入参不误拦
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判长期压测与磁盘配额；不判 ledger 落盘条数；不覆盖 POSIX 腿；不判 add() 自身的 node_id 校验（本件只判写面闸）
"""issue #324 守卫：oversize_response 此前只量 content，其余字段无界。

病象（修前）：MAX_WRITE_BYTES 的判据只对入参的 content 一个字段计字节，
node_id / tags 等完全不受约束。单次请求把 ~1.25 MiB 入参放大写入三处落盘面
（_write_attempts.jsonl + hippocampus/inbox.jsonl + _audit.jsonl），实测盘上增量
4,994,888 B；且 _write_attempts.jsonl 是无上限增长账本 ⇒ 磁盘耗尽型 DoS。

判据方向：A 组要求「超限字段一律被拒」，K 组要求「正常与边界入参不误拦」——
两侧同时成立才说明是把判据补全，而不是把闸门拧紧误伤合法写入。
"""
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import writepipe as _wp  # noqa: E402

LIMIT = _wp.MAX_WRITE_BYTES
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _call(**a):
    return _wp.oversize_response(a.get("node_id") or "n324", a)


print("== K 组：正常与边界入参不误拦 ==")
_k1 = _call(node_id="n324", content="短正文", content_kind="text", layer="knowledge",
            tags=["a", "b"], verification_basis="test")
_check("K1 正常小入参 → 不拦（返回 None）", _k1 is None, _k1)
_k2 = _call(node_id="n324", content="x" * LIMIT, content_kind="text")
_check("K2 content 恰好 = 上限 → 不拦（边界含等号）", _k2 is None, _k2)
_k3 = _call(node_id="n324", content="x" * 10, content_kind="text",
            tags=["t"] * 1000)
_check("K3 字段面合计远低于上限 → 不拦（不因新增判据误伤正常 tags）", _k3 is None, _k3)

print("== A 组：超限字段一律被拒 ==")
_a1 = _call(node_id="n324", content="x" * (LIMIT + 1), content_kind="text")
_check("A1 content 超限 → 拒（#82.3 既有面不退化）",
       isinstance(_a1, dict) and _a1.get("gate") == "writelimit_size"
       and _a1.get("field") == "content", _a1)

_a2 = _call(node_id="n" * 200, content="短正文", content_kind="text")
_check("A2 node_id 200 字符（合规字符但超既有 1..128 契约）→ 拒",
       isinstance(_a2, dict) and _a2.get("field") == "node_id", _a2)
_a3 = _call(node_id="n" * 5000, content="短正文", content_kind="text")
_check("A3 node_id 5000 字符 → 拒（不靠字节和判据兜底）",
       isinstance(_a3, dict) and _a3.get("field") == "node_id", _a3)

_a4 = _call(node_id="n324", content="短正文", content_kind="text", tags=["z" * 1000] * 1300)
_check("A4 tags 合计 > 上限 → 拒（修前完全不受约束的那一路）",
       isinstance(_a4, dict) and _a4.get("field") and _a4["field"] != "content", _a4)

_a5 = _call(node_id="n324", content="短正文", content_kind="text",
            evidence="e" * (LIMIT + 10))
_check("A5 其它字段（evidence）超限 → 拒（判据不挑字段名）",
       isinstance(_a5, dict) and _a5.get("field") == "evidence", _a5)

_check("A6 反对照：同规模入参去掉超限字段后即放行（证明是字段面判据在起作用）",
       _call(node_id="n324", content="短正文", content_kind="text") is None, "")

# ---- issue #355（2026-10-16 DSH 端）：非 str content 的类型面覆盖 ----
# 修前两条字节判据都漏：isinstance 直取 0、总字节循环又把 content 排除在外 ⇒
# 大体积 dict 过闸后击穿库层裸异常（.split），尝试账本零痕迹。
_a9 = _call(node_id="n324", content={"k": "x" * 1500000}, content_kind="text")
_check("A9 dict content 1.5 MiB → 拒（非 str 不再漏过字节判据，#355）",
       isinstance(_a9, dict) and _a9.get("field") == "content"
       and "issue #355" in str(_a9.get("error")), _a9)
_a10 = _call(node_id="n324", content={"k": 1}, content_kind="text")
_check("A10 小体积 dict content → 结构化拒收（不等库层裸异常，#355）",
       isinstance(_a10, dict) and _a10.get("field") == "content"
       and "issue #355" in str(_a10.get("error")), _a10)
_a11 = _call(node_id="n324", content=None, content_kind="text")
_check("A11 content=None → 本闸不拦（缺参语义归别处，零变化）", _a11 is None, _a11)

print("== E 组：单点与真源复用 ==")
_src = inspect.getsource(_wp.oversize_response)
_check("E1 oversize_response 体内遍历了 content 以外的字段",
       "for _k, _v in a.items()" in _src, [l for l in _src.splitlines() if "items()" in l][:2])
_check("E2 字段面判据用 _utf8_len 量字节（不是只数字符）",
       "_utf8_len(" in _src and callable(getattr(_wp, "_utf8_len", None)), "")
_check("E3 node_id 契约**复用** mdcg._NODE_ID_RE（延迟 import，不另写第二份正则）",
       "from .mdcg import _NODE_ID_RE" in _src,
       [l for l in _src.splitlines() if "_NODE_ID_RE" in l][:2])

print("")
if FAILS:
    print("issue #324 结果：%d 失败" % len(FAILS))
else:
    print("issue #324 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
_Q = chr(34)
_M1_OLD = "    if total > MAX_WRITE_BYTES:"
_M1_NEW = "    if False:  # 变异：字段面总字节判据停用"
_M2_OLD = ("    if _RE is not None and (len(_nv) > 128 or not _RE.match(_nv)):")
_M2_NEW = "    if False:  # 变异：node_id 既有契约判据停用"
_M3_OLD = "len(_nv) > 128 or not _RE.match(_nv)"
_M3_NEW = "len(_nv) > 4096"

_MUTATIONS = (
    ("V1 字段面总字节判据停用（回到只量 content）",
     "md_cg/writepipe.py", _M1_OLD, _M1_NEW, ("A4", "A5")),
    ("V2 node_id 既有契约判据停用（超长 node_id 仍需被拒）",
     "md_cg/writepipe.py", _M2_OLD, _M2_NEW, ("A2", "A3")),
    ("V3 node_id 不用既有 128 契约、自写 4096 阈值（放过 200 字符的非法 id）",
     "md_cg/writepipe.py", _M3_OLD, _M3_NEW, ("A2",)),
    # ---- issue #355：类型面（修前守卫 V1-V3 全锚在 str 判据与 node_id 契约面，
    # 没有一条覆盖非 str content——把 isinstance 删掉守卫也不会红）----
    ("V4 摘掉非 str content 的类型面判据（回到 isinstance 直取 0，即 #355 修前）",
     "md_cg/writepipe.py",
     "    if c is not None and not isinstance(c, str):",
     "    if False:",
     ("A9", "A10")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss324_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue324_write_size_fields"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())