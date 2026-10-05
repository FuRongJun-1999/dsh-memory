#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守卫：用户级注入件 zcode-user 的「渲染 ＋ 全文一致校验」面（2026-10-05 使用者裁决①）

背景：`~/.zcode/AGENTS.md` 此前是**手写指针**（矩阵 render:false，判据只有指向 / 陈化 /
工具名随端三检）——不含条款正文，故「手改正文」对守卫不可见；而它是本仓纪律唯一
「每会话必在」的注入通道（工作区级发现面自 cwd 向上搜到项目根，到不了子目录 zcode/）。
裁决①：把纪律**声明出口表**（18 条 response.direct 原文）与执行公约内嵌进本件，整件升级为
**可渲染、可机械守卫的产物**：
  · 矩阵 zcode-user：render: true + variant `zcode-user`（模板 zcode-user.md.tmpl）；
  · verify_discipline 指针分支新增**第四检**：extract 文本与 R.render(target, src, repo)
    逐字比对（仅归一末尾空白/换行），手改表行 / 指纹 / 指向 / 任意正文即判
    missing（field=全文）→ ok=False。

守卫断言（**行为断言**：跑真 CLI；USERPROFILE/HOME 指向临时家目录，全程不碰真 ~/.zcode）：
  P0 前提坐实：矩阵四字段（render / variant / pointer / pointer_body）+ 模板登记与在场；
     渲染件含指向字面量、指纹行、「声明出口表 18 行」，且无本机盘符路径 / 无裸 '{{'。
  G1 绿态：真渲染件（R.render 真渲染 → 写入假 home）→ verify 判绿（exit 0），第四检真执行
     且 pointer_checks.render_match=True。
  R1 红基线①：旧手写指针形态（优先取 .tmp/zcode_user_bak/before.md 备份；缺失时用内嵌
     净化副本[本机盘符路径 → `<仓根>`，供裸 clone / CI]）→ 必红，且红点唯一 = field=全文
     （旧三检对该形态不可见——这正是新增第四检要补的缺口）。
  M1 改一条声明表行 → 红，红点 = 全文检（旧三检不可见）。
  M2 改指纹一位     → 红：陈化面 stale=True ＋ 全文检。
  M3 删指向字面量   → 红：指向面 pointer_target ＋ 全文检。
  M4 删一段正文     → 红，红点 = 全文检（旧三检不可见）。
  Z1 还原真渲染件   → 回绿（证明红由夹具造成，非环境噪声）。

`--impl head`（修前对照，可选）：以 HEAD 版 verify_discipline.py 跑同一夹具——旧手写形态与
  真渲染件**同判绿**（旧三检对「手改正文」不可见），R1 的「必红」因本次第四检才成立。
`--mutate`（定点变异自证，可选）：把工作树 verify_discipline.py 的第四检判定行禁用后，
  M1/M4 必须**转绿**（第四检承重：旧三检对「手改正文」不可见），而 M2/M3 仍红
  （陈化面 / 指向面逐条保留，未被削弱）。锚点未命中 → ANCHOR-MISS → 退出码 2（fail-closed）。

退出码：0 = 全过（或变异组恰合）；1 = 断言失败；2 = 用法 / 环境错误。
"""
from __future__ import annotations

import argparse
import atexit
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
_LIVE = os.path.join(_HERE, "verify_discipline.py")
_DN = os.path.join(_HERE, "discipline_nodes.py")
_BEFORE = os.path.join(REPO, ".tmp", "zcode_user_bak", "before.md")
_TARGET = "zcode-user"

sys.path.insert(0, _HERE)
import render_discipline as R  # noqa: E402

_RESULTS = []


def _ok(cond, name, detail=""):
    cond = bool(cond)
    _RESULTS.append((name, cond, detail if not cond else ""))
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ((" —— " + str(detail).replace("\n", " | ")[:300]) if (detail and not cond) else ""))


# —— 红基线夹具②：旧手写指针形态的内嵌净化副本 ——
# 与 .tmp/zcode_user_bak/before.md 逐字同形，只把本机盘符路径（原件的仓根字面）替换为
# 中性占位 `<仓根>`——「仓库追踪面不得含本机路径」门禁（scripts/check_local_paths.py）所限。
# 语义与判据面不受影响：指向字面量 `zcode/AGENTS.md` 仍在，指纹行以真源现算填入（不陈旧），
# 故该形态在第四检下唯一红点 = field=全文。
_OLD_FORM_INLINE = """\
# 全局指示（用户级 · 本机）

> 本文件是**手写指针**，不是纪律本体——不含任何条款正文，故不会与真源漂移。
> 纪律本体 = `<仓根>/zcode/AGENTS.md`（由 `docs/工作纪律_认知图条目_v1.1.json` 渲染）。

## 当工作目录是灵枢仓库（`<仓根>` 或其后代）时

**会话起始第一件事——包含上下文压缩 / 长会话续接之后**：用 Read 工具读 `<仓根>/zcode/AGENTS.md`（18 条工作纪律 + 执行公约 + 声明出口表）。

为什么需要这一步：`zcode/AGENTS.md` 位于仓库**子目录**，而 ZCode 的指令文件发现面是「用户级 `~/.zcode/AGENTS.md` + 工作区级 `<仓根>/AGENTS.md`，且工作区那份自 cwd **向上**搜到项目根」——向上搜索永远到不了子目录。因此它不会被自动注入；本文件（用户级）就是把它拉进上下文的那个钩子。

随后按纪律执行：

- **0.1** 调 `cg(op=route, intent=<任务意图>)` 再动手，禁止跳过直接改码/跑命令。工具面若无 mdcg 工具，按第 7 条切等价兜底（进程内直调 `md_cg.mcp_server`）并声明降级，不得静默跳过。
- **0.2** 命中纪律须在回复中输出该条 `response.direct` 原文（未声明即视为未执行）。**压缩只保留留下执行痕迹的条目——声明就是痕迹。**
- **0.4 / 16** 违规即归档（第 4 条归因 + 第 16 条写入灵枢，六要素成文 + 读回确认）；隐瞒违规是更严重的违规。
- **8** 中文思考

- **触发**：中文区域｜中文项目开发过程
- **动作**：判定复杂度(情绪: 新奇/挑战/曾受批评 + 信息差: 不确定度)→复杂?「我们需要」深思考+确认 | 简单?「让我」快速执行; 推理开篇即中文锚点; 全程中文, 仅代码/标识符/引用保留原文
- **不适用**：需要英文编写的场景｜英文环境｜英文文档｜国际接口
- **声明**：按工作纪律第8条: 中文思考——中文书写; 复杂(新奇/挑战/曾受批评/高信息差)→「我们需要」交流确认互补盲区; 简单→「让我」快速执行不空耗; 每段推理开篇用中文短语锚定语言。

- **17** 改状态类任务派发蜂巢并留痕；只读判定（跑门禁/测试/回归看结论）可直跑，须输出一行「L1 直跑：<命令> — 风险/频次/可逆性」。
- **18** 查工作区文件先读仓根 `WORKSPACE_INDEX.md`，不以重复全盘浏览代替。

其它工作目录不受本段约束。

---

**机械守卫**（`python scripts/verify_discipline.py --target zcode-user`）：
本指针须指向纪律本体 `<仓根>/zcode/AGENTS.md`（正斜杠相对路径即判据面比对的字面量），
并内嵌真源 `docs/工作纪律_认知图条目_v1.1.json` 的指纹（SHA256 前16位）：%s。
改真源后须同步此行（判据侧按「陈化」硬失败）；本件不含条款正文，故字段级比对不适用。
"""


def _env(home, pythonpath=None):
    e = dict(os.environ, PYTHONUTF8="1", USERPROFILE=home, HOME=home)
    if pythonpath:
        # 仅变异体需要：变异副本住临时目录，discipline_nodes.library_layers() 的
        # 「由 __file__ 推仓根」在其上失效（md_cg 不可导入）——显式补 PYTHONPATH 指向本仓。
        # 在役腿不带此变量，保持与四自动化面同形。
        e["PYTHONPATH"] = pythonpath
    return e


def _cg_root():
    """投影腿执行面（A2）：root 缺失即 fail-closed，故现建一个最小库当合法 root。"""
    d = tempfile.mkdtemp(prefix="zcu_cg_lib_")
    p = subprocess.run([sys.executable, "-X", "utf8", _DN, "--init", "--write",
                        "--cg-root", d], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1"), cwd=_HERE, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("最小认知图库建失败（rc=%s）：%s"
                           % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-300:]))
    atexit.register(shutil.rmtree, d, True)
    return d


def _write_home_artifact(home, text):
    """把夹具写到假 home 的 ~/.zcode/AGENTS.md（真用户件全程只读、绝不触碰）。"""
    p = os.path.join(home, ".zcode", "AGENTS.md")
    d = os.path.dirname(p)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


def _verify(vd, home, cg_root, pythonpath=None):
    """跑真 CLI：verify --target zcode-user → (result, 退出码, 原始输出)。"""
    argv = [sys.executable, "-X", "utf8", vd, "--repo", REPO, "--json",
            "--target", _TARGET, "--allow-missing", "--no-chain",
            "--cg-root", cg_root]
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env(home, pythonpath), cwd=REPO, timeout=300)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return None, p.returncode, (p.stdout or "") + (p.stderr or "")
    rs = d.get("results") or []
    return (rs[0] if rs else None), p.returncode, p.stdout


def _keys(res):
    return [m.get("key") for m in (res or {}).get("missing", [])]


def _target_and_render():
    mx = R.load_matrix(REPO)
    t = dict(mx["targets"][_TARGET])
    t["_name"] = _TARGET
    return t, R.render(t, R.load_source(REPO), REPO)


def _old_form():
    """红基线夹具②：旧手写指针形态——真夹具优先（.tmp 备份），缺失时用内嵌净化副本。

    夹具在**指纹面归一到当前真源**：旧件内嵌的 sha 会随真源演进而陈旧，若不归一，R1 会
    同时踩陈化面与全文面（红基线失焦、且随真源演进变成假红）；归一后红点唯一 = 全文检。
    """
    if os.path.isfile(_BEFORE):
        text, src = io.open(_BEFORE, encoding="utf-8").read(), "备份 " + _BEFORE
    else:
        text, src = _OLD_FORM_INLINE % R.source_sha(REPO), "内嵌净化副本（无 .tmp 备份：裸 clone / CI）"
    text = re.sub(r"前16位[）：:]*\s*[0-9a-f]{16}", "前16位）：" + R.source_sha(REPO), text)
    return text, src


def _battery(vd, home, cg, live, old_form):
    del _RESULTS[:]
    t, _live = _target_and_render()
    sha = R.source_sha(REPO)

    # —— P0 前提坐实 ——
    _ok(t.get("render") is True and t.get("variant") == _TARGET
        and t.get("pointer") is True and t.get("pointer_body") == "zcode/AGENTS.md"
        and R._TEMPLATES.get(_TARGET) == "zcode-user.md.tmpl",
        "P0 矩阵前提：render:true / variant=zcode-user / pointer:true / pointer_body / 模板登记",
        {k: t.get(k) for k in ("render", "variant", "pointer", "pointer_body")})
    tpl = os.path.join(REPO, "docs", "discipline", "templates", "zcode-user.md.tmpl")
    _ok(os.path.isfile(tpl), "P0 模板文件在场", tpl)
    _ok(("（SHA256 前16位）：" + sha) in live and live.count("zcode/AGENTS.md") >= 1,
        "P0 渲染件含指纹行 + 指向字面量", "")
    _ok(len([l for l in live.splitlines() if re.match(r"^\| \d+ \| ", l)]) == 18,
        "P0 渲染件内嵌声明出口表 18 行", "")
    _ok(not re.search(r"[A-Za-z]:[\\/]", live) and "{{" not in live,
        "P0 渲染件无本机盘符路径、无裸 '{{'", "")

    # —— G1 绿态 ——
    _write_home_artifact(home, live)
    r, rc, raw = _verify(vd, home, cg)
    _ok(r is not None and r.get("ok") is True and rc == 0,
        "G1 真渲染件 → verify 判绿（exit 0）", raw[-300:])
    _ok(bool(r) and (r.get("pointer_checks") or {}).get("render_match") is True,
        "G1 第四检真执行且判「全文一致」（pointer_checks.render_match=True）", r)

    # —— R1 红基线①：旧手写指针形态 ——
    _ok("手写指针" in old_form and old_form.rstrip() != live.rstrip(),
        "R1 前提：夹具确为「旧手写指针形态」（含该标记、且 ≠ 当前渲染件）", "")
    _write_home_artifact(home, old_form)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is False and rc != 0,
        "R1 红基线①：旧手写指针形态 → 必红（修前该形态判绿）", raw[-300:])
    _ok(_keys(r) == ["render_match"],
        "R1 红点唯一 = 全文检（旧三检对该形态不可见——新增第四检补的正是这个缺口）",
        _keys(r))
    _ok(bool(r) and any(m.get("field") == "全文" for m in r["missing"]),
        "R1 missing 记录 field=「全文」", (r or {}).get("missing"))

    # —— M1 改一条声明表行 ——
    m1 = live.replace("按工作纪律第18条: 工作区索引优先",
                      "按工作纪律第18条（手改探针）: 工作区索引优先", 1)
    _ok(m1 != live, "M1 前提：声明表第 18 行在场且已改", "")
    _write_home_artifact(home, m1)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is False, "M1 改一条声明表行 → 红", raw[-250:])
    _ok(_keys(r) == ["render_match"], "M1 红点 = 全文检（旧三检不可见）", _keys(r))

    # —— M2 改指纹一位 ——
    flip = "0" if sha[-1] != "0" else "1"
    m2 = live.replace(sha, sha[:-1] + flip)
    _ok(sha in live and m2 != live, "M2 前提：指纹已改一位", sha)
    _write_home_artifact(home, m2)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is False and r.get("stale") is True,
        "M2 改指纹一位 → 红（陈化面 stale=True 仍在）", (r or {}).get("artifact_sha"))
    _ok(_keys(r) == ["render_match"], "M2 红点 = 全文检（配合陈化面）", _keys(r))

    # —— M3 删指向字面量 ——
    m3 = live.replace("zcode/AGENTS.md", "")
    _ok(m3 != live, "M3 前提：指向字面量 zcode/AGENTS.md 已删", "")
    _write_home_artifact(home, m3)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is False
        and _keys(r) == ["pointer_target", "render_match"],
        "M3 删指向字面量 → 红（指向面 pointer_target ＋ 全文检）", _keys(r))

    # —— M4 删一段正文 ——
    victim = "其它工作目录不受本段约束。"
    m4 = live.replace(victim, "")
    _ok(victim in live and m4 != live, "M4 前提：待删正文段在场且已删", victim)
    _write_home_artifact(home, m4)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is False and _keys(r) == ["render_match"],
        "M4 删一段正文 → 红（仅全文检可见，旧三检不可见）", _keys(r))

    # —— Z1 还原回绿 ——
    _write_home_artifact(home, live)
    r, rc, raw = _verify(vd, home, cg)
    _ok(bool(r) and r.get("ok") is True, "Z1 还原真渲染件 → 回绿（红由夹具造成，非环境噪声）", raw[-250:])


# ================================================================ 定点变异自证
# 把工作树 verify_discipline.py 的第四检判定行禁用——M1/M4（旧三检不可见的形态）必须转绿，
# 证明第四检承重；M2/M3 仍红，证明陈化面 / 指向面逐条保留（未因新增而放宽）。
_MUT_ANCHOR = "            render_match = rendered.rstrip() == text.rstrip()"
_MUT_REPLACE = "            render_match = True  # MUT: 第四检失效（自证用）"


def _materialize_head(tmp):
    """HEAD 版 verify_discipline.py（不含本次第四检）→ 临时实现目录（同目录配当前渲染器依赖）。"""
    p = subprocess.run(["git", "show", "HEAD:scripts/verify_discipline.py"],
                       cwd=REPO, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write("[zcu_embed] git show HEAD:scripts/verify_discipline.py 失败 rc=%s\n"
                         % p.returncode)
        raise SystemExit(2)
    d = os.path.join(tmp, "head_impl")
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "verify_discipline.py"), "wb") as f:
        f.write(p.stdout)
    for fn in ("render_discipline.py", "discipline_nodes.py"):
        shutil.copyfile(os.path.join(_HERE, fn), os.path.join(d, fn))
    return os.path.join(d, "verify_discipline.py")


def _head_mode(tmp, home, cg):
    """红基线对照腿：修前（HEAD 版）对旧手写形态与真渲染件**同样判绿**——即本次修复的盲区。"""
    print("!! 修前对照（HEAD 版 verify_discipline）：旧手写指针形态与真渲染件同判绿——"
          "R1 的「必红」是本次第四检才成立\n")
    vd = _materialize_head(tmp)
    old, _src = _old_form()
    live = _target_and_render()[1]
    del _RESULTS[:]
    _write_home_artifact(home, old)
    r, rc, raw = _verify(vd, home, cg, pythonpath=REPO)
    _ok(bool(r) and r.get("ok") is True and rc == 0,
        "修前对照：旧手写指针形态判绿（旧三检对「手改正文」不可见——缺口坐实）", raw[-250:])
    _write_home_artifact(home, live)
    r, rc, raw = _verify(vd, home, cg, pythonpath=REPO)
    _ok(bool(r) and r.get("ok") is True,
        "修前对照：真渲染件同样判绿（新旧形态不可区分＝本次要补的盲区）", raw[-250:])
    bad = [n for n, okc, _d in _RESULTS if not okc]
    print("\n修前对照 %d/%d 达标" % (len(_RESULTS) - len(bad), len(_RESULTS)))
    return 0 if not bad else 1


def _materialize_mutant(tmp):
    src = io.open(_LIVE, encoding="utf-8").read()
    if _MUT_ANCHOR not in src:
        sys.stderr.write("[zcu_embed] ANCHOR-MISS：第四检判定行不在工作树源码中：%s\n" % _MUT_ANCHOR)
        raise SystemExit(2)
    d = os.path.join(tmp, "mut_impl")
    os.makedirs(d, exist_ok=True)
    for fn in ("render_discipline.py", "discipline_nodes.py"):
        shutil.copyfile(os.path.join(_HERE, fn), os.path.join(d, fn))
    path = os.path.join(d, "verify_discipline.py")
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src.replace(_MUT_ANCHOR, _MUT_REPLACE, 1))
    return path


def _mutate_mode(tmp, home, cg):
    print("!! 定点变异自证：禁用第四检后，M1/M4 必须转绿（承重证明），M2/M3 仍红（既有判据保留）\n")
    vd = _materialize_mutant(tmp)
    _live_t, live = _target_and_render()
    sha = R.source_sha(REPO)

    m1 = live.replace("按工作纪律第18条: 工作区索引优先",
                      "按工作纪律第18条（手改探针）: 工作区索引优先", 1)
    m4 = live.replace("其它工作目录不受本段约束。", "")
    m2 = live.replace(sha, sha[:-1] + ("0" if sha[-1] != "0" else "1"))
    m3 = live.replace("zcode/AGENTS.md", "")

    def _mv(fixture):
        _write_home_artifact(home, fixture)
        return _verify(vd, home, cg, pythonpath=REPO)

    del _RESULTS[:]
    r, _rc, raw = _mv(m1)
    _ok(bool(r) and r.get("ok") is True,
        "变异体 M1（改表行）→ 转绿：第四检是它唯一的承重判据", raw[-250:])

    r, _rc, raw = _mv(m4)
    _ok(bool(r) and r.get("ok") is True,
        "变异体 M4（删正文）→ 转绿：第四检是它唯一的承重判据", raw[-250:])

    r, _rc, raw = _mv(m2)
    _ok(bool(r) and r.get("ok") is False and r.get("stale") is True and _keys(r) == [],
        "变异体 M2（改指纹）→ 仍红且红点归陈化面（stale=True，无全文检记录）：既有判据未削弱",
        {"stale": (r or {}).get("stale"), "keys": _keys(r), "raw": raw[-200:]})

    r, _rc, raw = _mv(m3)
    _ok(bool(r) and r.get("ok") is False and _keys(r) == ["pointer_target"],
        "变异体 M3（删指向）→ 仍红且红点归指向面（pointer_target）：既有判据未削弱",
        {"keys": _keys(r), "raw": raw[-200:]})

    bad = [n for n, okc, _d in _RESULTS if not okc]
    print("\n定点变异 %d/%d 恰合" % (len(_RESULTS) - len(bad), len(_RESULTS)))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="zcode-user 用户级注入件渲染＋全文一致校验守卫")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证（禁用第四检后 M1/M4 须转绿）")
    ap.add_argument("--impl", default="", help="head = 修前对照（HEAD 版 verify 对旧形态判绿）")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tmp = tempfile.mkdtemp(prefix="zcu_embed_")
    try:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        cg = _cg_root()
        if args.mutate:
            return _mutate_mode(tmp, home, cg)
        if args.impl == "head":
            return _head_mode(tmp, home, cg)
        live = _target_and_render()[1]
        old_form, old_src = _old_form()
        print("红基线夹具②来源：" + old_src + "\n")
        _battery(_LIVE, home, cg, live, old_form)
        bad = [n for n, okc, _d in _RESULTS if not okc]
        print("\n断言 %d 通过 / %d 失败" % (len(_RESULTS) - len(bad), len(bad)))
        if bad:
            print("失败项：" + "；".join(bad))
        return 0 if not bad else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
