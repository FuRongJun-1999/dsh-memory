# -*- coding: utf-8 -*-
"""守卫族「执行面」元守卫（issue #129）。

判据：本仓每一个守卫（`scripts/check_*.py`，以及 NAMED_GUARDS 里登记的具名守卫）
都必须在**至少一个执行面**上被引用；否则必须登记在 EXCEPTIONS 并写明理由。

执行面（三者任一即可，机器可判）：
  ① `package.json` 的 `gate` / `prepublishOnly` 脚本串里点名；
  ② `.github/workflows/*.yml` 任一 workflow 里点名；
  ③ **被 `scripts/run_tests.py` 收集的配对测试**：`scripts/test_<stem>.py` 落在它的
     glob 面内（CI 的 python-tests 会跑 run_tests.py）—— 这是本元守卫相对 #129 报告
     的口径修正：**有配对测试即算被执行**，不能只看 gate/CI 字面点名。

退出码（机器可判，**绝不静默退 0**）：
  0  全部守卫有执行面，或已在登记表内且写明理由
  1  存在**未登记的孤儿守卫**（既无执行面、又不在登记表）
  2  环境/解析错误（fail-closed：读不到 package.json / workflows / 收集面）
  3  登记表格式错误（缺理由或缺复核人）
  4  gate/CI 点名的仓内脚本路径在磁盘上不存在（#179 反向判据）

用法：
  python -X utf8 scripts/check_guard_coverage.py                 # 人读覆盖矩阵
  python -X utf8 scripts/check_guard_coverage.py --json          # 机器读
  python -X utf8 scripts/check_guard_coverage.py --selftest      # 合成语料自检
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 「具名守卫」：不在 scripts/check_*.py 命名面内、但同属须有执行面的判据件。
NAMED_GUARDS = (
    "scripts/cogmap_sync.py",
    "scripts/workspace_index.py",
    "scripts/verify_discipline.py",
    "scripts/judgment_manifest.py",
    "scripts/interop_gate.py",
    "scripts/link_check.py",
)

# run_tests.py 的收集 glob（与之同源；改动 run_tests.py 的收集面须同步此处）。
COLLECT_GLOBS = (
    "scripts/test_*.py",
    "md_cg/test_*.py",
    "hive/test_*.py",
)

# 「执行面」在 package.json 里的脚本键。**正反两向必须共用这一个常量**：
# 正向（gather_surfaces 判「守卫有没有执行面」）与反向（missing_named_paths 判
# 「点名件在不在盘上」）若各写一份键列表，两向判据面必然漂移。
# 实况（#179 落地时）：反向判据扫的是**全部** scripts 键，于是 #161 有意
# fail-closed 的 prepare 文案里的 `lib/index.js`（构建产物、被 .gitignore 忽略、
# 干净克隆上必然不存在）被判成「被 gate/CI 点名」，本守卫在干净克隆上恒退 4，
# 并把配对测试 scripts/test_check_guard_coverage.py 一并拖红。
SURFACE_SCRIPT_KEYS = ("gate", "prepublishOnly", "test")

# 孤儿登记表：文件名 -> {"reason": 为何暂无执行面, "owner": 复核人, "review": 复核日期}
# 规则：**新增孤儿必须改这里**，从而在 code review 里可见；数量不得增加。
EXCEPTIONS: dict[str, dict[str, str]] = {
    # 2026-10-12 首次登记（issue #129）。规则：**新增孤儿必须改这里**，
    # 使「又多了一个没人跑的守卫」在 code review 里可见；登记数不得增加。
    "check_placeholder_leak.py": {
        # 2026-10-13 重标定（issue #200 建议 4）：原「实测 36.2s」测于 2026-10-12，
        # 本机同日重测（中位 3 次）：tracked 0.38s / 全盘 0.62s —— 已**不是**全仓
        # 最贵守卫；真正最贵的两个（check_publish_smoke 64.8s /
        # check_publish_artifact 30.9s）**都已接入 CI**。成本依机器而变，故此处
        # 记「测量日期 + 口径 + 读数」，不再记单点绝对值。
        "reason": "成本依据已过时（issue #200 建议 4）：原记「全仓最贵守卫（实测 "
                  "36.2s）」测于 2026-10-12；2026-10-13 本机重测中位 tracked 0.38s / "
                  "全盘 0.62s，已非最贵。其判据是「占位符泄漏」，非发布阻塞项。"
                  "待设计者定：接 gate / 接 CI / 降频独立 workflow。",
        "owner": "设计者（待裁）",
        "review": "2026-10-13",
    },
    "check_registry_tarball.py": {
        "reason": "需先产出 registry tarball 才有判据对象；裸 clone / CI 上无该输入，"
                  "直接接 CI 会因缺输入而 fail-closed 变红。待定：是否在 CI 里先构建 tarball。",
        "owner": "设计者（待裁）",
        "review": "2026-10-12",
    },
    "interop_gate.py": {
        "reason": "其唯一消费方（冻结凭证）在生产零调用点（另见 issue #126），"
                  "当前接入 CI 无实际判据作用。**应先解 #126，再接执行面**。",
        "owner": "设计者（待裁）",
        "review": "2026-10-12",
    },
}

EXIT_MEANING = {
    0: "全部守卫有执行面，或已登记例外",
    1: "存在未登记的孤儿守卫",
    2: "环境/解析错误（fail-closed）",
    3: "登记表格式错误",
    4: "gate/CI 点名的仓内脚本路径不存在（点名缺失）",
}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def gather_guards(repo: str) -> list[str]:
    """收集守卫清单（仓内相对路径，/ 分隔，已排序）。"""
    out: list[str] = []
    d = os.path.join(repo, "scripts")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.startswith("check_") and name.endswith(".py"):
                out.append("scripts/" + name)
    for rel in NAMED_GUARDS:
        if os.path.isfile(os.path.join(repo, rel)) and rel not in out:
            out.append(rel)
    return sorted(set(out))


def gather_surfaces(repo: str) -> dict:
    """解析执行面。任一项读不到即抛 OSError（fail-closed）。"""
    pj_path = os.path.join(repo, "package.json")
    if not os.path.isfile(pj_path):
        raise OSError("package.json 不存在：" + pj_path)
    pj = json.loads(_read(pj_path))
    scripts = pj.get("scripts") or {}
    gate_text = " ".join(
        str(scripts.get(k, "")) for k in SURFACE_SCRIPT_KEYS
    )

    wf_dir = os.path.join(repo, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        raise OSError("workflows 目录不存在：" + wf_dir)
    ci_text = ""  # 只取 run: 步骤命令行（不认注释 / paths: / name:）
    wf_names = []
    for name in sorted(os.listdir(wf_dir)):
        if name.endswith((".yml", ".yaml")):
            wf_names.append(name)
            _in_run = False
            _run_ind = -1
            for _ln in _read(os.path.join(wf_dir, name)).splitlines():
                _s = _ln.strip()
                _ind = len(_ln) - len(_ln.lstrip())
                if _in_run and _s and _ind > _run_ind:
                    if not _s.startswith("#"):
                        ci_text += _s + "\n"
                    continue
                _in_run = False
                if _s.startswith("run:") or _s.startswith("- run:"):
                    ci_text += _s + "\n"
                    _run_ind = _ind
                    _in_run = _s.endswith("|") or _s.endswith(">") or _s.endswith("|-")
    if not wf_names:
        raise OSError("workflows 目录为空：" + wf_dir)

    collected_tests: set[str] = set()
    for rel in COLLECT_GLOBS:
        d, _, pat = rel.rpartition("/")
        base = os.path.join(repo, d) if d else repo
        if not os.path.isdir(base):
            continue
        pre, _, suf = pat.partition("*")
        for name in os.listdir(base):
            if name.startswith(pre) and name.endswith(suf):
                collected_tests.add((d + "/" if d else "") + name)

    return {
        "gate_text": gate_text,
        "ci_text": ci_text,
        "workflows": wf_names,
        "collected_tests": collected_tests,
    }


# [issue-129 patch] 整词匹配 + run-only 执行面
def _word(text: str, token: str) -> bool:
    """token 在 text 中以整词出现（两侧不得是名字字符）。"""
    _wc = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    i = text.find(token)
    while i != -1:
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(token)] if (i + len(token)) < len(text) else ""
        if before not in _wc and after not in _wc:
            return True
        i = text.find(token, i + 1)
    return False


def classify(guard: str, sf: dict) -> tuple[str, str]:
    """返回 (状态, 依据串)。状态 ∈ covered_direct / covered_test / orphan。"""
    base = os.path.basename(guard)
    stem = base[:-3]  # 去掉 .py
    if _word(sf["gate_text"], base) or _word(sf["gate_text"], stem):
        return "covered_direct", "package.json gate/prepublishOnly 点名"
    if _word(sf["ci_text"], base) or _word(sf["ci_text"], stem):
        return "covered_direct", "CI workflow run 步骤点名"
    paired = "scripts/test_" + stem + ".py"
    if paired in sf["collected_tests"]:
        return "covered_test", "配对测试 " + paired + " 被 run_tests.py 收集（CI 跑它）"
    return "orphan", "无执行面"


# [issue-179 patch] 反向判据：被 gate/CI 点名的仓内脚本路径必须在磁盘上存在。
# 解析保守：只收「含 >=1 个斜杠且以 .py/.js/.mjs/.cjs 结尾」的仓内相对 token；
# 以 / . ~ 开头或含 .. 的形态一律不收（绝对路径 / 包路径 / 通配面都不瞎猜）。
_NAMED_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./~-])"
    r"([A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)+\.(?:py|js|mjs|cjs))"
    r"(?![A-Za-z0-9_.-])"
)


def named_paths_in(text: str) -> set:
    """抽出一段文本里被点名的仓内脚本路径（去重）。"""
    out = set()
    for m in _NAMED_PATH_RE.finditer(text or ""):
        tok = m.group(1)
        if ".." in tok:
            continue
        out.add(tok)
    return out


def _workflow_run_text(repo: str) -> str:
    """只取 .github/workflows/*.yml|yaml 的 run: 步骤命令行（容缺：无目录 -> 空串）。"""
    wf_dir = os.path.join(repo, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        return ""
    out = []
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        in_run = False
        run_ind = -1
        for ln in _read(os.path.join(wf_dir, name)).splitlines():
            s = ln.strip()
            ind = len(ln) - len(ln.lstrip())
            if in_run and s and ind > run_ind:
                if not s.startswith("#"):
                    out.append(s)
                continue
            in_run = False
            if s.startswith("run:") or s.startswith("- run:"):
                out.append(s)
                run_ind = ind
                in_run = s.endswith("|") or s.endswith(">") or s.endswith("|-")
    return "\n".join(out)


def missing_named_paths(repo_root: str) -> list:
    """被 gate/CI 点名、却不在磁盘上的仓内脚本路径（排序去重）。

    这是 #129 元守卫缺失的反向那半：既有判据只遍历「盘上已存在的守卫」，
    故「点名了但文件没了」当场不可见（#179）。本函数只判**存在性**，
    不判该守卫跑得绿不绿（check_line_anchors 的红基线是另一回事）。

    判据面 = **执行面**（`SURFACE_SCRIPT_KEYS` 三个键 + workflow 的 run: 步骤），
    与正向判据同源。为什么不能扫 package.json 的**全部** scripts 键：非执行面脚本
    （prepare / build / lint…）的**文案**里出现的路径并不是「被 gate/CI 点名」，
    却会被当判据对象。实例：#161 让 prepare 在干净克隆上**有意** fail-closed，
    其错误文案里含 `lib/index.js`（构建产物、被 .gitignore 忽略、干净克隆上必然
    不存在）⇒ 本守卫恒退 4，且把配对测试一并拖红（见 #179 的原始建议：反向判据
    只解析「gate/prepublishOnly 与 workflow 点名的所有路径」）。
    """
    pj_path = os.path.join(repo_root, "package.json")
    if not os.path.isfile(pj_path):
        raise OSError("package.json 不存在：" + pj_path)
    pj = json.loads(_read(pj_path))
    scripts = pj.get("scripts") or {}
    named = set()
    for k in SURFACE_SCRIPT_KEYS:
        named |= named_paths_in(str(scripts.get(k, "")))
    named |= named_paths_in(_workflow_run_text(repo_root))
    missing = []
    for rel in sorted(named):
        if not os.path.exists(os.path.join(repo_root, rel.replace("/", os.sep))):
            missing.append(rel)
    return missing


def build(repo: str) -> dict:
    guards = gather_guards(repo)
    sf = gather_surfaces(repo)
    rows = []
    orphans = []
    bad_registry = []
    for g in guards:
        state, why = classify(g, sf)
        base = os.path.basename(g)
        reg = EXCEPTIONS.get(base)
        if state == "orphan" and reg is None:
            orphans.append(base)
        if reg is not None:
            miss = [k for k in ("reason", "owner", "review") if not reg.get(k)]
            if miss:
                bad_registry.append(base + " 缺字段 " + ",".join(miss))
        rows.append({
            "guard": g,
            "state": state,
            "why": why,
            "registered_exception": bool(reg),
            "exception_reason": (reg or {}).get("reason", ""),
        })
    return {
        "repo": repo,
        "guards": rows,
        "n_guards": len(guards),
        "n_covered": sum(1 for r in rows if r["state"].startswith("covered")),
        "n_exception": sum(1 for r in rows if r["registered_exception"]),
        "orphans": orphans,
        "bad_registry": bad_registry,
        "workflows": sf["workflows"],
        "n_collected_tests": len(sf["collected_tests"]),
        "missing_named": missing_named_paths(repo),
    }


def render(info: dict) -> None:
    print("  守卫族「执行面」覆盖矩阵（元守卫 · issue #129）")
    print("  仓：%s" % info["repo"])
    print("  执行面：package.json gate + %d 个 workflow + %d 个被收集的测试文件"
          % (len(info["workflows"]), info["n_collected_tests"]))
    print("")
    print("  %-36s %-14s %s" % ("守卫", "状态", "依据"))
    for r in info["guards"]:
        mark = {"covered_direct": "覆盖(直接)", "covered_test": "覆盖(配对测试)",
                "orphan": "孤儿"}[r["state"]]
        extra = ""
        if r["registered_exception"]:
            extra = "  [已登记例外] " + r["exception_reason"][:40]
        print("  %-36s %-14s %s%s" % (r["guard"], mark, r["why"][:56], extra))
    print("")
    print("  小计：守卫 %d ｜ 有执行面 %d ｜ 登记例外 %d ｜ 未登记孤儿 %d ｜ 点名缺失 %d"
          % (info["n_guards"], info["n_covered"], info["n_exception"], len(info["orphans"]),
             len(info["missing_named"])))
    if info["bad_registry"]:
        print("  [登记表格式错误] " + "；".join(info["bad_registry"]))
    for m in info["missing_named"]:
        print("  [点名缺失] %s —— 被 gate/CI 点名但盘上不存在；该执行面已失去判据对象" % m)
    if info["missing_named"]:
        print("  FAIL：点名缺失 %d 项 —— %s" % (len(info["missing_named"]),
                                               "；".join(info["missing_named"])))
    for o in info["orphans"]:
        print("  [孤儿] %s —— 既无执行面又未登记；请接进 gate/CI，或登记理由" % o)


def exit_code(info: dict) -> int:
    if info["bad_registry"]:
        return 3
    if info["orphans"]:
        return 1
    if info["missing_named"]:
        return 4  # #179：被 gate/CI 点名的仓内脚本路径在盘上不存在
    return 0


def selftest() -> int:
    """合成语料自检：不依赖本仓现状，验证判据有判别力。"""
    fails = []
    # 1) 合成一个仓：guard 有配对测试 -> covered_test
    import tempfile
    root = tempfile.mkdtemp(prefix="guardcov_")
    os.makedirs(os.path.join(root, "scripts"))
    os.makedirs(os.path.join(root, ".github", "workflows"))
    open(os.path.join(root, "package.json"), "w", encoding="utf-8").write(
        json.dumps({"scripts": {"gate": "python scripts/check_alpha.py"}}))
    open(os.path.join(root, ".github", "workflows", "w.yml"), "w", encoding="utf-8").write(
        "run: python scripts/check_beta.py\n")
    for n in ("check_alpha.py", "check_beta.py", "check_gamma.py", "check_delta.py"):
        open(os.path.join(root, "scripts", n), "w", encoding="utf-8").write("# x\n")
    open(os.path.join(root, "scripts", "test_check_gamma.py"), "w", encoding="utf-8").write("# x\n")

    info = build(root)
    st = {os.path.basename(r["guard"]): r["state"] for r in info["guards"]}
    if st.get("check_alpha.py") != "covered_direct":
        fails.append("alpha 应判 covered_direct，实为 %s" % st.get("check_alpha.py"))
    if st.get("check_beta.py") != "covered_direct":
        fails.append("beta 应判 covered_direct，实为 %s" % st.get("check_beta.py"))
    if st.get("check_gamma.py") != "covered_test":
        fails.append("gamma(有配对测试) 应判 covered_test，实为 %s" % st.get("check_gamma.py"))
    if st.get("check_delta.py") != "orphan":
        fails.append("delta(无执行面) 应判 orphan，实为 %s" % st.get("check_delta.py"))
    if exit_code(info) != 1:
        fails.append("含孤儿时应退 1，实为 %d" % exit_code(info))
    if "check_delta.py" not in info["orphans"]:
        fails.append("orphans 未包含 delta")

    # 2) 登记表缺字段 -> 退 3
    saved = dict(EXCEPTIONS)
    try:
        EXCEPTIONS["check_delta.py"] = {"reason": "x"}
        info2 = build(root)
        if exit_code(info2) != 3:
            fails.append("登记表缺字段应退 3，实为 %d" % exit_code(info2))
        EXCEPTIONS["check_delta.py"] = {"reason": "r", "owner": "o", "review": "d"}
        info3 = build(root)
        if exit_code(info3) != 0:
            fails.append("登记完整后应退 0，实为 %d" % exit_code(info3))
        if info3["orphans"]:
            fails.append("登记后仍报孤儿：%s" % info3["orphans"])
    finally:
        EXCEPTIONS.clear()
        EXCEPTIONS.update(saved)

    # 3) fail-closed：无 package.json -> OSError
    bad = tempfile.mkdtemp(prefix="guardcov_bad_")
    try:
        build(bad)
        fails.append("缺 package.json 应抛 OSError（fail-closed），实为未抛")
    except OSError:
        pass

    for f in fails:
        print("  [FAIL] " + f)
    print("")
    if fails:
        print("  自检：%d 项失败" % len(fails))
        return 1
    print("  自检：全部通过（判据有判别力：覆盖/配对测试/孤儿/登记/ fail-closed 五面）")
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="守卫族执行面元守卫（issue #129）")
    ap.add_argument("--repo", default=REPO, help="仓路径（默认本文件所在仓）")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    ap.add_argument("--selftest", action="store_true", help="合成语料自检，不看本仓")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    try:
        info = build(a.repo)
    except OSError as ex:
        print("  VERDICT=FAIL(环境)：%s" % ex)
        return 2
    except Exception as ex:  # 解析面异常同样 fail-closed
        print("  VERDICT=FAIL(解析)：%s: %s" % (type(ex).__name__, ex))
        return 2

    code = exit_code(info)
    if a.json:
        info2 = dict(info)
        info2["exit_code"] = code
        info2["exit_meaning"] = EXIT_MEANING[code]
        print(json.dumps(info2, ensure_ascii=False, indent=1))
    else:
        render(info)
    print("")
    print("  退出码 %d：%s" % (code, EXIT_MEANING[code]))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
