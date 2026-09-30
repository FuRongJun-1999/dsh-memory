# -*- coding: utf-8 -*-
"""test_publish_smoke_guard —— 出货面冒烟腿（scripts/check_publish_smoke.py）的守卫。

背景（为什么另立守卫）：本腿的职责是拦住「**仓库里在、包里不在**」这一类缺陷
（实测两次：#38 的 `scripts/` 与 `hive/` 整目录未出货、issue #48 的仓根
`utf8_boot.py` 未被 `files` 收录 ⇒ 0.6.1 装机即挂）。但本腿自己会不会陈化？
一个「断言出货清单含某个文件」的判据，若锚点漂移或断言被删，同样会静默失效
——故本守卫按 md_cg/test_neg_condition_hits.py 同口径，为**每一处判据**配一个
**定点变异**，变异后必须转红且**恰好**命中预期项数；锚点漂移报 ANCHOR-MISS
并退出码 2（fail-closed，不静默放行）。**不以 git HEAD 为基线源**——基线绑提交
即失效（本仓已有两次教训），故基线与变异都在**临时副本**上现做。

两组断言：
  [A] 静态锚点组（缺省跑；快、不触网、不起 npm）——11 条：
      C1  gate 链含本腿（`package.json` 的 `scripts.gate`）
      C2  本腿位序：紧随 `check_publish_artifact` 之后（不是塞在链尾）
      C3  `scripts/check_publish_smoke.py` 存在且可读
      C4  锚点·出货清单**点名**缺件 + 打印「修法：files 加 utf8_boot.py」
      C5  锚点·缺省工具面 `DEFAULT_TOOLS = ("cg", "stg")` 与相等断言
      C6  锚点·剔除继承环境：`startswith("MDCG_")` 与 `startswith("DEEPSEEK_")`
      C7  锚点·沙箱两分支：`MDCG_GATE_SANDBOX_DIR`（给定即保留）+ 缺省清理
      C8  锚点·复用 npm 解析单点（`cpa.resolve_npm()`，不写第二套方言）
      C9  锚点·真握手三条（initialize / notifications/initialized / tools/list）
      C10 锚点·沙箱内注入 `MDCG_ROOT` 与 `MDCG_AUX_ROOT`（两根本体）
      C11 单点未被绕过：`check_publish_artifact._npm_pack_json` 走 `resolve_npm()`
  [B] 定点变异自证（`--mutate`；真跑 npm，慢）：
      B1 静态面：11 处定点变异逐条应用，每处**恰好**命中预期红项（集合相等，多
         一项少一项都判红）；锚点漂移 → ANCHOR-MISS → 退出码 2。
      B2 行为面：在**临时副本**上先跑出绿（rc=0 / fails=[] / tools=['cg','stg']），
         再从 `package.json` 的 `files` 里删掉 `"utf8_boot.py"` → 本腿必须变红
         （rc=1）且**恰好**命中 4 项（S1 清单缺件 / S2 装机目录缺件 / S4 握手起不来 /
         S5 无从取 tools），并打印点名缺件的修法行。

运行（scripts/ 非包，直跑）：
  python -X utf8 scripts/test_publish_smoke_guard.py             # [A]（全量套件里的形态）
  python -X utf8 scripts/test_publish_smoke_guard.py --mutate    # [A]+[B]
退出码：0 全绿｜1 有红｜2 ANCHOR-MISS（变异锚点漂移，fail-closed）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

SMOKE_REL = ("scripts", "check_publish_smoke.py")
CPA_REL = ("scripts", "check_publish_artifact.py")
#: 静态面断言直接依赖的三个文件（变异副本按此清单复制，缺一即无从施加变异）。
_STATIC_FILES = ("package.json",) + tuple("/".join(r) for r in (SMOKE_REL, CPA_REL))

#: 行为面变异的预期红项（点名，集合相等才算「恰好」）——与 check_publish_smoke 的
#: 判据名逐字一致；任一处改名而本表未同步，B2 即红（这正是守卫要抓的漂移）。
BEHAVIOR_EXPECTED_REDS = {
    "S1 出货清单含仓根 utf8_boot.py",
    "S2 装好的目录含 utf8_boot.py",
    "S4 真握手成功（initialize → serverInfo；tools/list → tools）",
    "S5 tools 面 == 缺省面 ['cg','stg']",
}
MISSING_HINT = "修法：files 加 utf8_boot.py"

ANCHOR_CHECK_NAMES = (
    "C4 锚点·出货清单点名缺件与修法行",
    "C5 锚点·缺省工具面 DEFAULT_TOOLS",
    "C6 锚点·剔除继承的 MDCG_*/DEEPSEEK_*",
    "C7 锚点·沙箱两分支（给定保留 / 缺省清理）",
    "C8 锚点·复用 npm 解析单点",
    "C9 锚点·真握手三条 JSON-RPC",
    "C10 锚点·沙箱内注入 MDCG_ROOT/MDCG_AUX_ROOT",
)

_PASS = []
_FAIL = []
_MISS = []


class AnchorMiss(Exception):
    """变异锚点在真源里找不到——实现改了却没同步本表（fail-closed）。"""


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _read(root, *rel):
    with open(os.path.join(root, *rel), encoding="utf-8") as fh:
        return fh.read()


def _write(root, *rel, text):
    p = os.path.join(root, *rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# 生效条件：root 为含 package.json 的目录时返回 scripts.gate 字符串（缺失返回空串）；
# 文件不可读/JSON 非法时抛异常由调用方收敛。
def _gate_spec(root):
    pj = json.loads(_read(root, "package.json"))
    return ((pj.get("scripts") or {}).get("gate") or "")


def _gate_legs(root):
    return [s.strip() for s in _gate_spec(root).split("&&") if s.strip()]


# 生效条件：root 为复制出来的候选根（含 package.json 与两份 scripts）时，返回
# [(id, name, ok, detail)] —— 逐项静态判据，纯文本/JSON 读面，不起进程。
def _static_checks(root):
    res = []

    def add(cid, name, cond, detail=""):
        res.append((cid, name, bool(cond), detail))

    try:
        legs = _gate_legs(root)
    except (OSError, ValueError) as exc:
        legs = []
        add("C1", "C1 gate 链含出货面冒烟腿", False, "package.json 不可读/非法：%r" % (exc,))
        add("C2", "C2 冒烟腿紧随 check_publish_artifact 之后", False, "同上")
    else:
        smoke_idx = [i for i, s in enumerate(legs) if "scripts/check_publish_smoke.py" in s]
        pub_idx = [i for i, s in enumerate(legs) if "scripts/check_publish_artifact.py" in s]
        add("C1", "C1 gate 链含出货面冒烟腿", len(smoke_idx) == 1,
            "腿数=%d smoke_idx=%s" % (len(legs), smoke_idx))
        add("C2", "C2 冒烟腿紧随 check_publish_artifact 之后",
            bool(smoke_idx and pub_idx and smoke_idx[0] == pub_idx[0] + 1),
            "smoke_idx=%s pub_idx=%s legs=%s" % (smoke_idx, pub_idx, legs))

    src = None
    try:
        src = _read(root, *SMOKE_REL)
    except OSError as exc:
        add("C3", "C3 冒烟脚本存在且可读", False, "%s（%r）" % (os.path.join(*SMOKE_REL), exc))
    else:
        add("C3", "C3 冒烟脚本存在且可读", True)

    if src is None:
        for nm in ANCHOR_CHECK_NAMES:
            cid = nm.split(" ", 1)[0]
            add(cid, nm, False, "冒烟脚本不可读，锚点无从校验")
    else:
        add("C4", ANCHOR_CHECK_NAMES[0],
            ('"utf8_boot.py" in shipped' in src) and (MISSING_HINT in src),
            "点名缺件与修法行须同在（缺件点名=出货清单判据的机器读面）")
        add("C5", ANCHOR_CHECK_NAMES[1],
            ('DEFAULT_TOOLS = ("cg", "stg")' in src) and ("tools == list(DEFAULT_TOOLS)" in src),
            "")
        add("C6", ANCHOR_CHECK_NAMES[2],
            ('startswith("MDCG_")' in src) and ('startswith("DEEPSEEK_")' in src), "")
        add("C7", ANCHOR_CHECK_NAMES[3],
            ("MDCG_GATE_SANDBOX_DIR" in src)
            and ("shutil.rmtree(sandbox, ignore_errors=True)" in src), "")
        add("C8", ANCHOR_CHECK_NAMES[4],
            ("cpa.resolve_npm()" in src) and ("_load_publish_artifact" in src), "")
        add("C9", ANCHOR_CHECK_NAMES[5],
            ('"initialize"' in src) and ('"notifications/initialized"' in src)
            and ('"tools/list"' in src), "")
        add("C10", ANCHOR_CHECK_NAMES[6],
            ('env["MDCG_ROOT"] = mem_root' in src)
            and ('env["MDCG_AUX_ROOT"] = aux_dir' in src), "")

    try:
        cpa = _read(root, *CPA_REL)
    except OSError as exc:
        add("C11", "C11 单点未被绕过（_npm_pack_json 走 resolve_npm）", False,
            "%s（%r）" % (os.path.join(*CPA_REL), exc))
    else:
        add("C11", "C11 单点未被绕过（_npm_pack_json 走 resolve_npm）",
            ("def resolve_npm()" in cpa)
            and ('[resolve_npm(), "pack", "--dry-run", "--json"]' in cpa), "")
    return res


def _replace_anchor(root, *rel, old, new):
    """把 root/rel 文本里的 old 换成 new；old 不存在 → AnchorMiss（fail-closed）。"""
    text = _read(root, *rel)
    if old not in text:
        raise AnchorMiss("%s 中找不到变异锚点：%r" % (os.path.join(*rel), old[:80]))
    _write(root, *rel, text=text.replace(old, new))


def _mut_gate_drop(root):
    text = _read(root, "package.json")
    old = "&& python scripts/check_publish_smoke.py"
    if old not in text:
        raise AnchorMiss("package.json 的 gate 串里找不到本腿（%r）" % old)
    _write(root, "package.json", text=text.replace(old, "", 1))


def _mut_gate_move_last(root):
    legs = _gate_legs(root)
    smoke = [s for s in legs if "scripts/check_publish_smoke.py" in s]
    if len(smoke) != 1:
        raise AnchorMiss("gate 串里本腿不是恰好一条：%s" % smoke)
    rest = [s for s in legs if s not in smoke]
    text = _read(root, "package.json")
    old = " && ".join(legs)
    new = " && ".join(rest + smoke)
    if old not in text:
        raise AnchorMiss("gate 串与 legs 切分不一致（锚点不可定位）")
    _write(root, "package.json", text=text.replace(old, new, 1))


def _mut_drop_smoke_file(root):
    p = os.path.join(root, *SMOKE_REL)
    if not os.path.isfile(p):
        raise AnchorMiss("冒烟脚本不存在，无法做「删文件」变异：%s" % p)
    os.remove(p)


# 定点变异表：[A] 组每条判据配一处变异；expected 为**恰好**应当转红的 C-id 集合。
# 说明：删 gate 腿会同时打红 C1 与 C2（腿没了 → 位序也无从成立），删脚本文件会打红
# C3 与全部锚点（源不可读时锚点断言必须红，不许静默放行）——两处「多红」是**语义必然**，
# 写死在 expected 里，多一项少一项都算漂移。
def _static_mutations():
    def rep(*rel, old, new):
        return lambda root, rel=rel, old=old, new=new: _replace_anchor(root, *rel, old=old, new=new)

    return (
        ("删 gate 腿", _mut_gate_drop, {"C1", "C2"}),
        ("把 gate 腿挪到链尾", _mut_gate_move_last, {"C2"}),
        ("删冒烟脚本文件", _mut_drop_smoke_file, {"C3"} | {n.split(" ", 1)[0] for n in ANCHOR_CHECK_NAMES}),
        ("去掉缺件修法行", rep(*SMOKE_REL, old=MISSING_HINT, new="修法见文档"),
         {"C4"}),
        ("改缺省工具面字面量", rep(*SMOKE_REL, old='DEFAULT_TOOLS = ("cg", "stg")',
                                 new='DEFAULT_TOOLS = ("cg", "stg", "full")'), {"C5"}),
        ("漏剔 DEEPSEEK_*", rep(*SMOKE_REL, old='startswith("DEEPSEEK_")',
                                new='startswith("DEEPSEEK_X")'), {"C6"}),
        ("沙箱保留分支改名", rep(*SMOKE_REL, old="MDCG_GATE_SANDBOX_DIR",
                                 new="SMOKE_SANDBOX_ENV"), {"C7"}),
        ("不再复用 npm 单点", rep(*SMOKE_REL, old="cpa.resolve_npm()", new='"npm.cmd"'), {"C8"}),
        ("握手不再发 tools/list", rep(*SMOKE_REL, old='"tools/list"', new='"tools/list_x"'), {"C9"}),
        ("凭据根不指沙箱", rep(*SMOKE_REL, old='env["MDCG_AUX_ROOT"] = aux_dir',
                               new='env["MDCG_AUX_ROOT"] = state_dir'), {"C10"}),
        ("_npm_pack_json 绕过单点",
         rep(*CPA_REL, old='[resolve_npm(), "pack", "--dry-run", "--json"]',
             new='["npm.cmd" if os.name == "nt" else "npm", "pack", "--dry-run", "--json"]'),
         {"C11"}),
    )


# 生效条件：src 为仓库根、dst 为新建的目标目录时，按 git 追踪面（git ls-files -z）逐件
# 复制到 dst，再补拷包内非追踪件 lib/（R4 允许面，npm pack 的既有出货件）与本腿自身的
# 源文件（_STATIC_FILES，未提交前是未追踪件——守卫**不以 git 提交为基线**，故须显式补拷，
# 否则「新腿刚落地、还没 git add」时守卫自己先红）；返回复制件数。
# 不复制 .git/node_modules——本副本只用于「真 pack + 真装」的定点变异，不需要历史与依赖。
def _materialize_repo(src, dst):
    proc = subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                          cwd=src, env=_env(), timeout=300)
    if proc.returncode != 0:
        raise AnchorMiss("git ls-files 失败 rc=%s（无法材料化副本）" % proc.returncode)
    rels = [r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r]
    if not rels:
        raise AnchorMiss("git ls-files 为空（副本材料化无从谈起）")
    os.makedirs(dst, exist_ok=True)
    for rel in list(rels) + [r for r in _STATIC_FILES if r not in rels]:
        s = os.path.join(src, *rel.split("/"))
        if not os.path.isfile(s):
            continue
        d = os.path.join(dst, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
    lib = os.path.join(src, "lib")
    if os.path.isdir(lib):
        shutil.copytree(lib, os.path.join(dst, "lib"), dirs_exist_ok=True)
    return len(rels)


def _run_smoke(root, sandbox):
    """在 root 的副本里跑它自己的冒烟脚本 → (rc, SMOKE_JSON|None, stdout)。"""
    script = os.path.join(root, *SMOKE_REL)
    if not os.path.isfile(script):
        raise AnchorMiss("副本里没有冒烟脚本：%s" % script)
    env = _env()
    env["MDCG_GATE_SANDBOX_DIR"] = sandbox
    proc = subprocess.run([sys.executable, "-X", "utf8", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=root, timeout=1800)
    out = proc.stdout or ""
    summary = None
    for line in out.splitlines():
        if line.startswith("SMOKE_JSON "):
            try:
                summary = json.loads(line[len("SMOKE_JSON "):])
            except ValueError:
                summary = None
    return proc.returncode, summary, out + (proc.stderr or "")


# 生效条件：无入参，读取仓库根 package.json 的 files 白名单并断言含 "utf8_boot.py"，
# 返回去掉该后的文件列表（供变异副本写入）；缺项即 AnchorMiss（免变异空转）。
def _files_without_utf8_boot(root):
    pj = json.loads(_read(root, "package.json"))
    files = pj.get("files")
    if not isinstance(files, list) or "utf8_boot.py" not in files:
        raise AnchorMiss("package.json 的 files 里没有 utf8_boot.py（变异无从施加）")
    return pj, [f for f in files if f != "utf8_boot.py"]


def _static_group():
    """[A] 静态锚点组：对**真实仓库根**逐条断言（缺省跑法，快）。"""
    print("== [A] 静态锚点组（真实仓库根 %s）==" % HERE)
    checks = _static_checks(HERE)
    for _cid, name, good, detail in checks:
        ok(good, name, detail)
    print("  微结：%d 条断言，%d 红" % (len(checks), sum(1 for c in checks if not c[2])))
    return checks


def _mutate_static_group():
    """[B1] 静态面定点变异：每处变异恰好命中预期红项集合。"""
    print("== [B1] 静态面定点变异（临时副本；锚点漂移 → ANCHOR-MISS）==")
    checked = 0
    for name, mutator, expected in _static_mutations():
        tmp = tempfile.mkdtemp(prefix="smoke_guard_static_")
        try:
            for rel in _STATIC_FILES:
                _write(tmp, *rel.split("/"), text=_read(HERE, *rel.split("/")))
            try:
                mutator(tmp)
            except AnchorMiss as exc:
                _MISS.append("%s：%s" % (name, exc))
                print("  ANCHOR-MISS %s ← %s" % (name, exc))
                continue
            reds = {cid for cid, _n, good, _d in _static_checks(tmp) if not good}
            checked += 1
            ok(reds == expected, "变异「%s」恰好命中预期红项 %s" % (name, sorted(expected)),
               "实得 %s" % sorted(reds))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("  微结：[B1] 应用 %d 处变异，%d 处锚点漂移" % (checked, len(_MISS)))
    return checked


def _mutate_behavior_group():
    """[B2] 行为面定点变异：临时副本上真 pack/真装/真握手，绿→红两侧都给读数。"""
    print("== [B2] 行为面定点变异（临时副本：材料化 → 真 pack → 真装 → 真握手）==")
    if shutil.which("npm") is None and shutil.which("npm.cmd") is None:
        _MISS.append("[B2] 本机探不到 npm，行为面自证无从进行（fail-closed）")
        print("  ANCHOR-MISS [B2] 本机探不到 npm —— 行为面自证无从进行")
        return
    tmp = tempfile.mkdtemp(prefix="smoke_guard_behav_")
    try:
        _behavior_body(tmp)
    except AnchorMiss as exc:
        _MISS.append("[B2] %s" % exc)
        print("  ANCHOR-MISS [B2] %s" % exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _behavior_body(tmp):
    copy_root = os.path.join(tmp, "repo")
    n = _materialize_repo(HERE, copy_root)
    print("  副本=%s（复制追踪件 %d 件 + lib/）" % (copy_root, n))
    sandbox = os.path.join(tmp, "sandbox")

    # —— 绿侧（未变异副本）——
    rc, summary, out = _run_smoke(copy_root, os.path.join(sandbox, "green"))
    ok(rc == 0 and summary is not None and summary.get("fails") == []
       and summary.get("tools") == ["cg", "stg"],
       "B2 绿侧：未变异副本 rc=0 / fails=[] / tools=['cg','stg']",
       "rc=%s summary=%s" % (rc, json.dumps(summary, ensure_ascii=False)[:300]))
    print("     绿侧读数：清单条目=%s · 装好目录含 utf8_boot=%s · serverInfo=%s · tools=%s"
          % (None if summary is None else summary.get("manifest_entries"),
             None if summary is None else summary.get("installed_has_utf8_boot"),
             json.dumps(None if summary is None else summary.get("serverInfo"),
                        ensure_ascii=False),
             json.dumps(None if summary is None else summary.get("tools"),
                        ensure_ascii=False)))

    # —— 变异：files 里删掉 "utf8_boot.py" ——
    pj, files = _files_without_utf8_boot(copy_root)
    pj["files"] = files
    _write(copy_root, "package.json", text=json.dumps(pj, ensure_ascii=False, indent=2) + "\n")
    rc, summary, out = _run_smoke(copy_root, os.path.join(sandbox, "red"))
    fails = set((summary or {}).get("fails") or [])
    ok(rc == 1, "B2 红侧：变异后本腿 rc=1（修前形态：腿不会红）", "rc=%s" % rc)
    ok(fails == BEHAVIOR_EXPECTED_REDS,
       "B2 红侧：恰好命中预期红项 %d 处" % len(BEHAVIOR_EXPECTED_REDS),
       "实得 %s" % sorted(fails))
    ok(MISSING_HINT in out, "B2 红侧：点名缺件并打印修法行「%s」" % MISSING_HINT)
    ok((summary or {}).get("manifest_entries", 0) > 0
       and (summary or {}).get("has_utf8_boot") is False,
       "B2 红侧：出货清单仍可读且 utf8_boot 已不在清单",
       json.dumps(summary, ensure_ascii=False)[:200])
    print("     红侧读数：清单条目=%s · 清单含 utf8_boot=%s · 装好目录含 utf8_boot=%s · 握手 rc=%s"
          % ((summary or {}).get("manifest_entries"), (summary or {}).get("has_utf8_boot"),
             (summary or {}).get("installed_has_utf8_boot"),
             (summary or {}).get("handshake_rc")))
    print("     红项点名：%s" % "；".join(sorted(fails)))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    do_mutate = "--mutate" in sys.argv[1:]
    _static_group()
    if do_mutate:
        _mutate_static_group()
        _mutate_behavior_group()
    else:
        print("== [B] 定点变异自证：未启用（加 --mutate 跑；真跑 npm，约 1 分钟）==")

    print("\n%d 通过，%d 失败，%d 锚点漂移" % (len(_PASS), len(_FAIL), len(_MISS)))
    if _MISS:
        print("ANCHOR-MISS：" + "；".join(_MISS))
        return 2
    if _FAIL:
        print("失败项：")
        for f in _FAIL:
            print("   - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
