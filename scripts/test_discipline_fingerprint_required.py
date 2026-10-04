# -*- coding: utf-8 -*-
"""test_discipline_fingerprint_required —— N253 渲染产物「缺内嵌指纹」不得静默守卫

背景（2026-10-05 缺陷 N253，severity=high）：`scripts/verify_discipline.py` 的陈化判据
（`discipline-check.yml:4` 自陈的四项硬失败之一）在两条分支上口径不一致——
  · 指针分支 :207-211：`m_ptr` 为空即往 `missing` 记一条硬失败（`pointer_sha`）；
  · 渲染分支 :250-253：`res["stale"] = bool(m) and ...`——`m` 为空 ⇒ `stale=False` ⇒ `ok=True`，
    且 `missing` 一条不记。同一条件下指针型 zcode-user 判 `sha=None missing=1 ok=False`，
    渲染型（zcode、codebuddy-rules 等 8 个目标）判 `sha=None missing=0 ok=True`——同库两套口径，
    且渲染型没有任何判据强制指纹存在。
实测四种形态（本轮取证，见 S3：真实矩阵 + 真实产物 zcode/AGENTS.md 的拷贝，写进临时仓后跑
`verify_discipline.py --repo <tmp> --target zcode --json`）：删行 / 大写十六进制 /
空白插在「前16位」与「）：」之间（半角或全角）/ 16 位 hex 内含空白 →
皆 `artifact_sha=None stale=False ok=True missing=0`——「陈化」这一项对整个渲染面失效。
而渲染产物的指纹行是模板固定行（`full.md.tmpl:5` / `rules.mdc.tmpl:12` /
`compact.txt.tmpl:18` / `skill.md.tmpl:23`），缺失即「没走渲染链路」或「被人手改」，
两种情形都不该放行。修法：对 render 非 false 的目标同样记 `missing` 硬失败；仅
render:false 的真·手工投影豁免（其漂移由字段级逐字比对兜底）。

守卫断言面（真实矩阵 + 真实产物拷贝驱动，不依赖在役产物存在与否）：
  S1 前提坐实：真实矩阵下每个「render 非 false 且非 pointer」的目标都内嵌指纹且 == source_sha
  S2 对照腿：未破坏的真实产物拷贝 → ok=True（不误伤）
  S3 四种破坏形态 → ok=False 且 missing 含 artifact_sha 记录（修前 ok=True / missing=0）
  S4 陈旧指纹（与真源不等）→ stale=True / ok=False（既有判据保持）
  S5 良性变体（空白插在「：」与 hex 之间）→ 指纹仍被读到、陈化判据仍生效（未过度收紧）
  S6 真·手工投影豁免（render:false，合成矩阵）：无指纹**不**记硬失败；同一产物挂到
     render 目标则记硬失败（豁免只因 render:false，不因文本内容）
  S7 指针型不被削弱（合成矩阵 pointer:true）：无指纹仍记 pointer_sha 硬失败
  S8 在役链路不误伤：真实仓 `verify_discipline.py --allow-missing`（CI / npm gate 口径）→ exit 0

运行：python -X utf8 scripts/test_discipline_fingerprint_required.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_VD = os.path.join(HERE, "verify_discipline.py")
_MATRIX = os.path.join(REPO, "docs", "discipline", "harnesses.yaml")
_SOURCE = os.path.join(REPO, "docs", "工作纪律_认知图条目_v1.1.json")
_PRODUCT = os.path.join(REPO, "zcode", "AGENTS.md")

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  "
              + str(detail).replace("\n", " | ")[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _verify_json(repo, targets):
    """跑守卫 → (results 列表, 原始 stdout)。targets 为 target 名列表。"""
    argv = [sys.executable, "-X", "utf8", _VD, "--repo", repo, "--json"]
    for t in targets:
        argv += ["--target", t]
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env(), cwd=HERE, timeout=300)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return None, p.stdout + p.stderr
    return d["results"], p.stdout


def _fingerprint_keys(res):
    return [m.get("key") for m in res["missing"]]


def _mk_real_repo(tmp, product_text):
    """真实矩阵 + 真实真源 + 真实产物字节 → 临时仓（只该产物可被改写）。"""
    os.makedirs(os.path.join(tmp, "docs", "discipline"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "zcode"), exist_ok=True)
    shutil.copy(_MATRIX, os.path.join(tmp, "docs", "discipline", "harnesses.yaml"))
    shutil.copy(_SOURCE, os.path.join(tmp, "docs",
                                      os.path.basename(_SOURCE)))
    with open(os.path.join(tmp, "zcode", "AGENTS.md"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write(product_text)


_SYNTH_MATRIX = """\
version: 1
source: docs/工作纪律_认知图条目_v1.1.json
targets:
  n253-rendered:
    enabled: true
    transport: file
    path: art/rendered.md
    variant: full
  n253-manual:
    enabled: true
    render: false
    transport: file
    path: art/manual.md
    variant: full
  n253-pointer:
    enabled: true
    render: false
    pointer: true
    pointer_body: discipline/body.md
    transport: file
    path: art/pointer.md
    variant: full
"""


def _mk_synth_repo(tmp, rendered, manual, pointer):
    os.makedirs(os.path.join(tmp, "docs", "discipline"))
    os.makedirs(os.path.join(tmp, "art"))
    with open(os.path.join(tmp, "docs", "discipline", "harnesses.yaml"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write(_SYNTH_MATRIX)
    with open(os.path.join(tmp, "docs", "工作纪律_认知图条目_v1.1.json"), "w",
              encoding="utf-8", newline="") as fh:
        json.dump({"subgraph": {"nodes": []}}, fh)
    for rel, body in (("art/rendered.md", rendered), ("art/manual.md", manual),
                      ("art/pointer.md", pointer)):
        with open(os.path.join(tmp, rel), "w", encoding="utf-8", newline="") as fh:
            fh.write(body)


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not (os.path.isfile(_MATRIX) and os.path.isfile(_SOURCE)
            and os.path.isfile(_PRODUCT)):
        skip("S1–S5", "真实矩阵/真源/产物缺失（外部 clone 未渲染？）")
        return 0
    product = open(_PRODUCT, encoding="utf-8").read()
    m = re.search(r"前16位[）：:]*\s*([0-9a-f]{16})", product)
    check("S0 前提：参照产物内嵌指纹为小写 16 位 hex（否则本守卫的取样无效）",
          m is not None, product[:200])
    if m is None:
        print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
        return 1
    sha = m.group(1)
    line = "> 真源指纹（SHA256 前16位）：" + sha
    check("S0 前提：参照产物含模板固定指纹行 %r" % line, line in product)

    print("[1] 真实矩阵 + 真实产物拷贝：四种破坏形态不得静默")
    with tempfile.TemporaryDirectory() as tmp:
        _mk_real_repo(tmp, product)
        res, raw = _verify_json(tmp, ["zcode"])
        if not res:
            check("S2 对照腿：未破坏产物 ok=True", False, raw)
        else:
            r = res[0]
            check("S2 对照腿：未破坏产物 ok=True / 指纹已读",
                  r["ok"] is True and r.get("artifact_sha") == sha
                  and r.get("stale") in (False, None), r)
            check("S2 对照腿：缺指纹记录为空（新判据不误伤）",
                  "artifact_sha" not in _fingerprint_keys(r), _fingerprint_keys(r))

        mutations = [
            ("删行", product.replace(line + "\n", "")),
            ("大写十六进制", product.replace(sha, sha.upper())),
            ("空白插在「前16位」与「）：」之间（全角）",
             product.replace("前16位）：", "前16位\u3000）：")),
            ("空白插在「前16位」与「）：」之间（半角）",
             product.replace("前16位）：", "前16位 ）：")),
            ("16 位 hex 内含空白", product.replace(sha, sha[:8] + " " + sha[8:])),
        ]
        for label, text in mutations:
            _mk_real_repo(tmp, text)
            res, raw = _verify_json(tmp, ["zcode"])
            if not res:
                check("S3 %s → ok=False 且记指纹缺失" % label, False, raw)
                continue
            r = res[0]
            check("S3 %s → ok=False 且记指纹缺失（修前 ok=True/missing=0）" % label,
                  r["ok"] is False and "artifact_sha" in _fingerprint_keys(r),
                  dict(ok=r["ok"], sha=r.get("artifact_sha"), keys=_fingerprint_keys(r)))

        # S4 既有判据保持：指纹在但与真源不等 → stale
        _mk_real_repo(tmp, product.replace(sha, "0" * 16))
        res, raw = _verify_json(tmp, ["zcode"])
        r = res[0] if res else {}
        check("S4 陈旧指纹（≠ 真源）→ stale=True / ok=False",
              r.get("stale") is True and r.get("ok") is False, r)

        # S5 未过度收紧：空白插在「：」与 hex 之间，指纹仍可读 → 陈化判据仍生效
        _mk_real_repo(tmp, product.replace("前16位）：" + sha, "前16位）： " + sha))
        res, raw = _verify_json(tmp, ["zcode"])
        r = res[0] if res else {}
        check("S5 良性变体（「：」后空白）→ 指纹仍读到、ok=True",
              r.get("artifact_sha") == sha and r.get("ok") is True, r)

    print("[2] 豁免边界：只有 render:false 的真·手工投影可无指纹")
    with tempfile.TemporaryDirectory() as tmp:
        nofp = "普通手工件正文，无内嵌指纹行。\n"
        _mk_synth_repo(tmp, rendered=nofp, manual=nofp, pointer=nofp)
        res, raw = _verify_json(tmp, ["n253-rendered", "n253-manual", "n253-pointer"])
        if not res:
            check("S6 合成矩阵腿", False, raw)
        else:
            by = {r["target"]: r for r in res}
            check("S6 render 目标无指纹 → 记硬失败 ok=False",
                  by["n253-rendered"]["ok"] is False
                  and "artifact_sha" in _fingerprint_keys(by["n253-rendered"]),
                  by["n253-rendered"])
            check("S6 render:false 手工投影无指纹 → 豁免（不记硬失败，ok=True）",
                  by["n253-manual"]["ok"] is True
                  and "artifact_sha" not in _fingerprint_keys(by["n253-manual"]),
                  by["n253-manual"])
            check("S7 指针型无指纹 → 仍记 pointer_sha 硬失败（既有判据未被削弱）",
                  by["n253-pointer"]["ok"] is False
                  and "pointer_sha" in _fingerprint_keys(by["n253-pointer"]),
                  by["n253-pointer"])

    print("[3] 在役链路不误伤：真实仓 --allow-missing")
    p = subprocess.run([sys.executable, "-X", "utf8", _VD, "--allow-missing"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env(), cwd=REPO, timeout=300)
    out = p.stdout or ""
    check("S8 真实仓 exit 0", p.returncode == 0, out[-500:])
    check("S8 结论行「N/N 目标一致」", "目标一致" in out, out[-300:])
    # S1 前提坐实：每次真实仓跑批里，凡渲染型目标（非 pointer）都内嵌指纹且 == 真源
    res, raw = _verify_json(REPO, [])
    if not res:
        check("S1 前提坐实：渲染型目标皆内嵌指纹", False, raw)
    else:
        rendered = [r for r in res if not r["skipped"]
                    and r.get("pointer_checks") is None]
        bad = [r["target"] for r in rendered
               if r.get("artifact_sha") != r.get("source_sha")]
        check("S1 前提坐实：真实仓 %d 个在役渲染目标指纹皆 == 真源" % len(rendered),
              bool(rendered) and not bad, bad)

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
