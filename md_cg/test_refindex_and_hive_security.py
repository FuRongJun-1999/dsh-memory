# -*- coding: utf-8 -*-
"""守卫 · refindex 嵌套相对路径防误删 & Hive/Interop 安全加固回归套件。

覆盖四项独立安全与数据完整性修复：
  [A] md_cg/refindex.py（_nested_dup_scan / prune_nested）：
      相对 ref["path"] 必须基于 ref["root"] 解析，绝不相对进程 CWD——
      不同目录同名文件（repo/README.md vs repo/docs/README.md）不得误删，
      真嵌套重复（repo + docs/guide.md vs repo/docs + guide.md）须准确检出并只删内层；
      越根相对路径 / 盘符相对路径跳过不误判。
  [B] hive/wm.py（job_id / commonpath 限缩 + git 选项注入防护）：
      拒绝 Windows 盘符相对路径（Z:sample_dir / C:victim）、`.`/`..`、段级 `.`/`..`、
      控制字符、前导 `-`、Windows 保留设备名，并经 os.path.commonpath 保证不越出 wm/jobs；
      snapshot/merge/revert/log 拒绝 `-` 开头选项注入（如 `--output=<file>`、`--orphan`）。
  [C] hive/exec_cmd.py（HIVE_RESULT_ANCHOR 剥离）：
      HIVE_RESULT_ANCHOR 加入 ENV_SECRET_FAMILIES，子进程绝不继承 HMAC 完整性锚，
      同时 _write_result 仍从本进程 os.environ 正常回写 result_anchor（正例零回归）。
  [D] md_cg/interop.py + hive/verify_runner.py（iter_id 严格白名单 + 目录逃逸防护）：
      freeze / dispatch_verify_job / write_verdict_to_repo / verify_runner.main
      统一拒绝 `.` / `..` / 含 `..` / 尾点 / 分隔符 / `:` / 前导 `-` / Windows 保留名，
      且经 realpath + commonpath 限缩在 hive/interop/ 内；合法 iter_id 零回归。

运行：
    python -X utf8 -m md_cg.test_refindex_and_hive_security
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# 隔离前置：实验根一律落系统临时目录，绝不触碰真实 ~/.mdcg
_TMP_ROOT = tempfile.mkdtemp(prefix="refidx_hive_sec_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP_ROOT, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP_ROOT, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP_ROOT, "cgroot")
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _env_k in ("MDCG_SESSION", "DSH_SESSION_ID", "MDCG_TOKEN"):
    os.environ.pop(_env_k, None)

from md_cg import interop, refindex  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402


def _load_hive_module(mod_name: str, filename: str):
    path = os.path.join(_REPO, "hive", filename)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wm = _load_hive_module("_sec_hive_wm", "wm.py")
_ec = _load_hive_module("_sec_hive_exec_cmd", "exec_cmd.py")
_vr = _load_hive_module("_sec_hive_verify_runner", "verify_runner.py")

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  <- {str(detail)[:220]}" if detail else ""))


def _mk_ref_node(cg, nid: str, kind: str, root: str, path: str, content: str = "body"):
    tag = kind.split("_")[0]
    cg.add(nid, content, layer="contextual", tags=[tag],
           **{kind: {"root": root, "path": path, "lineno": 1, "end": 2, "hash": "h"}})


def _group_a_refindex() -> None:
    print("\n== [A] md_cg/refindex.py: 相对 ref['path'] 基于 ref['root'] 解析 ==")
    base = tempfile.mkdtemp(prefix="sec_a_ref_", dir=_TMP_ROOT)
    outer = os.path.join(base, "repo")
    inner = os.path.join(outer, "docs")
    unrelated_cwd = os.path.join(base, "other_cwd")
    os.makedirs(inner, exist_ok=True)
    os.makedirs(unrelated_cwd, exist_ok=True)

    outer_readme = os.path.join(outer, "README.md")
    inner_readme = os.path.join(inner, "README.md")
    guide = os.path.join(inner, "guide.md")
    outside_doc = os.path.join(base, "outside.md")
    for p, txt in (
        (outer_readme, "# outer readme\n"),
        (inner_readme, "# inner docs readme\n"),
        (guide, "# shared guide\n"),
        (outside_doc, "# outside\n"),
    ):
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)

    cg = MdCGOS(os.path.join(base, "cgdb"), actor="sec_test")
    # 不同物理文件但相对名相同（修前两者都 realpath("README.md") → CWD/README.md 误删内层）
    _mk_ref_node(cg, "doc_outer_readme", "doc_ref", outer, "README.md", "outer readme")
    _mk_ref_node(cg, "doc_inner_readme", "doc_ref", inner, "README.md", "inner readme")
    # 真正嵌套重复：外层 docs/guide.md 与内层 guide.md 指向同一物理文件
    _mk_ref_node(cg, "doc_outer_guide", "doc_ref", outer, "docs/guide.md", "guide outer")
    _mk_ref_node(cg, "doc_inner_guide", "doc_ref", inner, "guide.md", "guide inner")
    # 越根相对路径 & 盘符相对路径：不得误撞任何合法文件
    _mk_ref_node(cg, "doc_inner_escape", "doc_ref", inner, "../README.md", "escape")
    _mk_ref_node(cg, "doc_inner_drive", "doc_ref", inner, "Z:README.md", "drive rel")
    # 不同 kind（code_ref）指向同一物理文件：不得算重复
    _mk_ref_node(cg, "code_inner_guide", "code_ref", inner, "guide.md", "code guide")

    prev_cwd = os.getcwd()
    try:
        os.chdir(unrelated_cwd)
        plan, stats = refindex._nested_dup_scan(cg)
        ids_in_plan = [item["node_id"] for item in plan]
        check("A1a 不同物理文件（outer/README.md vs inner/README.md）不进清退计划",
              "doc_inner_readme" not in ids_in_plan and "doc_outer_readme" not in ids_in_plan,
              str(plan))
        check("A1b 真嵌套重复（docs/guide.md vs guide.md）准确检出且只标内层",
              ids_in_plan == ["doc_inner_guide"], str(plan))
        check("A1c plan.path 为真实物理路径而非 CWD 假路径",
              len(plan) == 1
              and os.path.normcase(plan[0]["path"]) == os.path.normcase(os.path.realpath(guide)),
              str(plan))
        check("A1d 越根相对路径 / 盘符相对路径 / 不同 kind 均不误判",
              "doc_inner_escape" not in ids_in_plan
              and "doc_inner_drive" not in ids_in_plan
              and "code_inner_guide" not in ids_in_plan,
              str(plan))

        dry = refindex.prune_nested(cg, dry_run=True)
        app = refindex.prune_nested(cg, dry_run=False)
        check("A2a dry_run 与 apply 计划逐项一致且只删真重复内层节点",
              [x["node_id"] for x in dry["plan"]] == ["doc_inner_guide"]
              and [x["node_id"] for x in app["plan"]] == ["doc_inner_guide"]
              and app.get("deleted_ids") == ["doc_inner_guide"],
              f"dry={dry} app={app}")
        check("A2b apply 后 distinct 内层 README.md 与外层节点均完好保留",
              cg.get("doc_outer_readme") is not None
              and cg.get("doc_inner_readme") is not None
              and cg.get("doc_outer_guide") is not None
              and cg.get("doc_inner_guide") is None,
              "distinct file was deleted or true dup survived")

        # CWD 切到 outer 根目录再测：仍不得误伤同名 README.md
        os.chdir(outer)
        plan_outer_cwd, _ = refindex._nested_dup_scan(cg)
        check("A3 CWD 位于 outer 根目录时仍零误报（found=0）",
              plan_outer_cwd == [], str(plan_outer_cwd))

        # 正向兼容：既有绝对路径 ref 仍能正确检出嵌套重复
        _mk_ref_node(cg, "doc_abs_outer", "doc_ref", outer, guide, "abs outer")
        _mk_ref_node(cg, "doc_abs_inner", "doc_ref", inner, guide, "abs inner")
        plan_abs, _ = refindex._nested_dup_scan(cg)
        check("A4 兼容既有绝对路径 ref（检出 doc_abs_inner）",
              [x["node_id"] for x in plan_abs] == ["doc_abs_inner"],
              str(plan_abs))
    finally:
        os.chdir(prev_cwd)


def _mk_wm_job(parent: str, folder: str, job_id_in_result: str | None = None,
               with_progress: bool = True) -> str:
    d = os.path.join(parent, folder)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "m", "user_prompt": "sec"}, f, ensure_ascii=False)
    res = {"ok": True, "content": "ok", "model": "m"}
    if job_id_in_result is not None:
        res["job_id"] = job_id_in_result
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    if with_progress:
        with open(os.path.join(d, _wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "start", "task": folder}, ensure_ascii=False) + "\n")
    return d


def _group_b_wm() -> None:
    print("\n== [B] hive/wm.py: job_id/commonpath 加固 & git 选项注入防护 ==")
    base = tempfile.mkdtemp(prefix="sec_b_wm_", dir=_TMP_ROOT)
    wm_repo = os.path.join(base, "wm")
    init_r = _wm.cmd_init(wm_repo)
    check("B0 wm 仓初始化成功", init_r.get("ok") is True, str(init_r))

    # 造仓外受害目录 + 受害 progress.jsonl（若存在盘符相对逃逸，此处可能被删或读）
    victim_dir = os.path.join(base, "victim_dir")
    os.makedirs(victim_dir, exist_ok=True)
    victim_sentinel = os.path.join(victim_dir, "keep.txt")
    with open(victim_sentinel, "w", encoding="utf-8") as f:
        f.write("MUST_SURVIVE\n")
    with open(os.path.join(victim_dir, _wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "handoff", "content": "SECRET_OUTSIDE_WM"}) + "\n")

    # 恶意 job_id 矩阵（含 Windows 盘符相对路径 `Z:sample_dir` / `C:victim_dir`）
    drive_letter = os.path.splitdrive(os.path.abspath(base))[0] or "C:"
    bad_jids = [
        "Z:sample_dir",
        f"{drive_letter}victim_dir",
        "../../victim_dir",
        "..\\..\\victim_dir",
        ".",
        "..",
        ".hidden",
        "a..b",
        "h_.._x",
        "h_._x",
        "job_trailing.",
        "-evil",
        "--orphan",
        "job\x00null",
        "job\nline",
        "job\x1fctrl",
        " leading",
        "trailing ",
        "has space",
        "CON",
        "NUL.txt",
        "h_PRN_1",
        "h_AUX_2",
        "COM1",
        "LPT9",
    ]
    prev_cwd = os.getcwd()
    try:
        os.chdir(base)
        snap_all_rejected = True
        snap_bad_detail = ""
        for idx, jid in enumerate(bad_jids):
            jd = _mk_wm_job(base, f"bad_snap_{idx}", job_id_in_result=jid)
            r = _wm.cmd_snapshot(jd, wm_repo)
            if r.get("ok") is not False or "非法 job_id" not in (r.get("error") or ""):
                snap_all_rejected = False
                snap_bad_detail = f"jid={jid!r} -> {r}"
                break
        check("B1a cmd_snapshot 拒绝全部恶意 job_id（含 Z:sample_dir / 盘符相对 / 保留名 / 前导 - / 控制字符）",
              snap_all_rejected, snap_bad_detail)
        check("B1b 仓外受害目录未被 rmtree 误删", os.path.isfile(victim_sentinel))

        prog_all_rejected = True
        prog_bad_detail = ""
        for jid in bad_jids:
            r = _wm.cmd_progress(wm=wm_repo, job_id=jid)
            blob = json.dumps(r, ensure_ascii=False)
            if (r.get("ok") is not False or "非法 job_id" not in (r.get("error") or "")
                    or "SECRET_OUTSIDE_WM" in blob):
                prog_all_rejected = False
                prog_bad_detail = f"jid={jid!r} -> {blob[:180]}"
                break
        check("B2 cmd_progress 拒绝全部恶意 job_id 且零仓外内容泄露",
              prog_all_rejected, prog_bad_detail)
    finally:
        os.chdir(prev_cwd)

    # commonpath 越界兜底自证：即使绕过字符校验，realpath 越出 wm/jobs 也必须被拦截
    with mock.patch.object(_wm, "_validate_job_id", return_value=None):
        dest_esc, err_esc = _wm._resolve_under_jobs(wm_repo, "../../victim_dir")
    check("B3 _resolve_under_jobs 经 os.path.commonpath 拦截越界真实路径",
          dest_esc is None and err_esc is not None and "非法 job_id" in err_esc,
          f"dest={dest_esc!r} err={err_esc!r}")

    # Git 选项注入防护：snapshot / merge / revert / log
    out_probe = os.path.join(base, "git_opt_pwn.txt")
    r_log_opt = _wm.cmd_log(wm_repo, branch=f"--output={out_probe}")
    check("B4a cmd_log 拒绝 `--output=...` 选项注入且不写盘",
          r_log_opt.get("ok") is False and not os.path.exists(out_probe),
          str(r_log_opt))
    r_log_dash = _wm.cmd_log(wm_repo, branch="--all")
    check("B4b cmd_log 拒绝 `--all` 选项注入",
          r_log_dash.get("ok") is False, str(r_log_dash))

    r_merge_opt = _wm.cmd_merge("--allow-unrelated-histories", wm_repo)
    check("B4c cmd_merge 拒绝前导 `-` 选项注入",
          r_merge_opt.get("ok") is False, str(r_merge_opt))

    r_rev_opt1 = _wm.cmd_revert("--no-commit", wm_repo)
    r_rev_opt2 = _wm.cmd_revert("main..HEAD", wm_repo)
    check("B4d cmd_revert 拒绝前导 `-` 与范围表达式 `..`",
          r_rev_opt1.get("ok") is False and r_rev_opt2.get("ok") is False,
          f"r1={r_rev_opt1} r2={r_rev_opt2}")

    ok_job = _mk_wm_job(base, "job_valid_01", job_id_in_result="job_valid_01")
    r_snap_opt = _wm.cmd_snapshot(ok_job, wm_repo, branch="--orphan")
    check("B4e cmd_snapshot 拒绝 `--orphan` 分支选项注入且无 staging 残留",
          r_snap_opt.get("ok") is False
          and not os.path.exists(os.path.join(wm_repo, "jobs", "job_valid_01")),
          str(r_snap_opt))

    # 正向对照：完整 snapshot → progress → log → merge → revert 闭环零回归
    snap_ok = _wm.cmd_snapshot(ok_job, wm_repo)
    check("B5a 正向对照：合法 job_id 快照成功",
          snap_ok.get("ok") is True and bool(snap_ok.get("commit")), str(snap_ok))
    prog_ok = _wm.cmd_progress(wm=wm_repo, job_id="job_valid_01")
    check("B5b 正向对照：分支两级 progress 读取成功",
          prog_ok.get("ok") is True and prog_ok.get("source") == "wm_branch",
          str(prog_ok))
    log_ok = _wm.cmd_log(wm_repo, branch="task/job_valid_01", limit=5)
    check("B5c 正向对照：cmd_log(branch=...) 正常返回提交",
          log_ok.get("ok") is True and len(log_ok.get("log") or []) >= 1, str(log_ok))
    merge_ok = _wm.cmd_merge("task/job_valid_01", wm_repo)
    check("B5d 正向对照：cmd_merge 正常合并到 main",
          merge_ok.get("ok") is True and bool(merge_ok.get("commit")), str(merge_ok))
    rev_ok = _wm.cmd_revert(merge_ok.get("commit") or "", wm_repo)
    check("B5e 正向对照：cmd_revert(真实 SHA) 正常回退 merge commit",
          rev_ok.get("ok") is True and bool(rev_ok.get("commit")), str(rev_ok))
    uni_job = _mk_wm_job(base, "uni_job", job_id_in_result="h_甲_任务_单元_0001")
    snap_uni = _wm.cmd_snapshot(uni_job, wm_repo)
    check("B5f 正向对照：中文四槽合法 job_id 快照成功",
          snap_uni.get("ok") is True, str(snap_uni))


def _group_c_exec_cmd() -> None:
    print("\n== [C] hive/exec_cmd.py: HIVE_RESULT_ANCHOR 不得泄露给子进程 ==")
    # 使用 FAKE_TOKEN_MARKERS 中的 dummy/placeholder 占位，避免触碰 R1 真凭据规则
    dummy_anchor = "dummy-anchor-placeholder-hmac-0001"
    check("C1 is_secret_env_name('HIVE_RESULT_ANCHOR') == True（大小写不敏感）",
          _ec.is_secret_env_name("HIVE_RESULT_ANCHOR") is True
          and _ec.is_secret_env_name("hive_result_anchor") is True)
    stripped = _ec.strip_secret_env({
        "HIVE_RESULT_ANCHOR": dummy_anchor,
        "PATH": "/usr/bin",
        "PYTHONUTF8": "1",
    })
    check("C2 strip_secret_env 剥离 HIVE_RESULT_ANCHOR 且保留非敏感键",
          "HIVE_RESULT_ANCHOR" not in stripped
          and stripped.get("PATH") == "/usr/bin"
          and stripped.get("PYTHONUTF8") == "1",
          str(stripped))

    # 端到端行为判据：父进程持有 HIVE_RESULT_ANCHOR → 子命令看不到，但 result.json 仍正常回写锚
    job_dir = tempfile.mkdtemp(prefix="sec_c_ec_", dir=_TMP_ROOT)
    spec = {
        "model": "cmd",
        "user_prompt": "anchor-scrub-check",
        "command": [
            sys.executable, "-c",
            "import os; print('CHILD_ANCHOR=' + repr(os.environ.get('HIVE_RESULT_ANCHOR')))",
        ],
        "env": {
            "HIVE_RESULT_ANCHOR": "dummy-forged-anchor-placeholder",
            "SAFE_FLAG": "visible_ok",
        },
    }
    with open(os.path.join(job_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)

    with mock.patch.dict(os.environ, {"HIVE_RESULT_ANCHOR": dummy_anchor}):
        rc = _ec.run_cmd(job_dir)
    with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as f:
        res = json.load(f)
    step_out = (res.get("steps") or [{}])[0].get("stdout_head") or ""
    check("C3a 端到端：子命令看不到继承或 spec.env 注入的 HIVE_RESULT_ANCHOR",
          rc == _ec.EXIT_OK
          and "CHILD_ANCHOR=None" in step_out
          and dummy_anchor not in step_out
          and "dummy-forged-anchor-placeholder" not in step_out,
          f"rc={rc} step_out={step_out!r}")
    check("C3b 端到端正向对照：exec_cmd._write_result 仍从父进程回写 result_anchor",
          res.get("ok") is True and res.get("result_anchor") == dummy_anchor,
          str({k: res.get(k) for k in ("ok", "result_anchor")}))


def _group_d_interop_runner() -> None:
    print("\n== [D] md_cg/interop.py & hive/verify_runner.py: iter_id 严格校验 ==")
    base = tempfile.mkdtemp(prefix="sec_d_interop_", dir=_TMP_ROOT)
    fake_repo = os.path.join(base, "repo")
    interop_base = os.path.join(fake_repo, "hive", "interop")
    os.makedirs(interop_base, exist_ok=True)
    # 放诱饵 frozen.json 在 hive/（`..` 目标）与 hive/interop/（`.` 目标）
    decoy_parent = os.path.join(fake_repo, "hive", "frozen.json")
    decoy_self = os.path.join(interop_base, "frozen.json")
    for p in (decoy_parent, decoy_self):
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"iter_id": "decoy", "digest": "a" * 64, "frozen_at": "2026-01-01T00:00:00Z"}, f)

    bad_ids = [
        ".",
        "..",
        "../escape",
        "..\\escape",
        "a/b",
        "a\\b",
        "Z:escape",
        "C:escape",
        "-flag",
        ".hidden",
        "iter..bad",
        "iter_dot.",
        "CON",
        "nul.json",
        "AUX",
        "iter\x00null",
        "",
        "a" * 81,
    ]

    # D1: freeze() 拒绝全部非法 iter_id 且不落盘
    freeze_ok = True
    freeze_detail = ""
    with mock.patch.object(interop, "HERE", fake_repo):
        for bad in bad_ids:
            try:
                interop.freeze(bad)
                freeze_ok = False
                freeze_detail = f"freeze({bad!r}) did not raise"
                break
            except ValueError:
                pass
    check("D1a interop.freeze() 拒绝 `.`/`..`/盘符/分隔符/前导 `-`/保留名等全部非法 iter_id",
          freeze_ok, freeze_detail)
    # 显式 out_dir 时也同样拒绝非法 iter_id
    explicit_rejected = False
    try:
        interop.freeze("..", out_dir=os.path.join(base, "explicit_out"))
    except ValueError:
        explicit_rejected = True
    check("D1b interop.freeze(out_dir=...) 同样拒绝非法 iter_id",
          explicit_rejected and not os.path.exists(os.path.join(base, "explicit_out")))

    # D2: write_verdict_to_repo() 拒绝全部非法 iter_id 且绝不在 hive/ 或 hive/interop/ 写 verdict.json
    valid_v = interop.make_verdict(
        iter_id="iter_ok_01",
        verifier_instance="verifier",
        verifier_fingerprint="a" * 64,
        subject_instance="main",
        subject_fingerprint="b" * 64,
        suite_origin="verifier-worktree",
        frozen_at="2026-01-01T00:00:00Z",
        verdict="pass",
        passed=7,
        failed=0,
    )
    w_ok = True
    w_detail = ""
    for bad in bad_ids:
        try:
            interop.write_verdict_to_repo({**valid_v, "iter_id": bad}, repo=fake_repo)
            w_ok = False
            w_detail = f"write_verdict_to_repo({bad!r}) did not raise"
            break
        except (ValueError, interop.InteropSanityError):
            pass
    check("D2 interop.write_verdict_to_repo() 拒绝全部非法 iter_id 且无逃逸落盘",
          w_ok
          and not os.path.exists(os.path.join(fake_repo, "hive", "verdict.json"))
          and not os.path.exists(os.path.join(interop_base, "verdict.json")),
          w_detail)

    # D3: dispatch_verify_job() 拒绝非法 iter_id 且不写 job spec
    disp_jobs = os.path.join(base, "disp_jobs")
    os.makedirs(disp_jobs, exist_ok=True)
    disp_rejected = True
    for bad in (".", "..", "../escape", "Z:escape"):
        try:
            interop.dispatch_verify_job(disp_jobs, bad, "b" * 64)
            disp_rejected = False
            break
        except ValueError:
            pass
    check("D3 dispatch_verify_job() 拒绝非法 iter_id 且不生成投递目录",
          disp_rejected and os.listdir(disp_jobs) == [])

    # D4: verify_runner.main() 拒绝 `.`/`..` 等非法 iter_id（即使 HIVE_ROLE=verifier 且诱饵 frozen.json 存在）
    vr_ok = True
    vr_detail = ""
    with mock.patch.object(_vr, "REPO", fake_repo), \
            mock.patch.dict(os.environ, {
                "HIVE_ROLE": "verifier",
                "HIVE_INSTANCE": "verifier",
                "SUBJECT_FP": "b" * 64,
            }):
        for bad in bad_ids:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = _vr.main(["verify_runner.py", bad, "--smoke"])
            out = buf.getvalue()
            if rc != 2 or "iter_id 非法" not in out:
                vr_ok = False
                vr_detail = f"bad={bad!r} rc={rc} out={out[:160]!r}"
                break
    check("D4 verify_runner.main() 对 `.`/`..` 等全部非法 iter_id 返回 rc=2 且不触碰诱饵目录",
          vr_ok
          and not os.path.exists(os.path.join(fake_repo, "hive", "verdict.json"))
          and not os.path.exists(os.path.join(interop_base, "verdict.json")),
          vr_detail)

    # D5: 正向对照（合法 iter_id 全链通过）
    good_id = "iter_sec_valid-1.0"
    with mock.patch.object(interop, "HERE", fake_repo):
        cred = interop.freeze(good_id)
    expected_frz = os.path.realpath(os.path.join(interop_base, good_id, "frozen.json"))
    check("D5a 正向对照：interop.freeze(合法 iter_id) 落于 hive/interop/<iter_id>/frozen.json",
          os.path.isfile(expected_frz) and os.path.normcase(cred["_path"]) == os.path.normcase(expected_frz),
          str(cred.get("_path")))

    w_res = interop.write_verdict_to_repo({**valid_v, "iter_id": good_id}, repo=fake_repo)
    expected_vrd = os.path.realpath(os.path.join(interop_base, good_id, "verdict.json"))
    check("D5b 正向对照：write_verdict_to_repo(合法 iter_id) 正常落盘",
          w_res.get("ok") is True and os.path.isfile(expected_vrd), str(w_res))

    os.remove(expected_vrd)
    stub_ok = {"ok": True, "note": "positive-control"}
    with mock.patch.object(_vr, "REPO", fake_repo), \
            mock.patch.object(_vr, "_run", side_effect=[(0, "3 passed", ""), (0, "4 passed", "")]), \
            mock.patch.object(_vr, "assert_a1", return_value=dict(stub_ok)), \
            mock.patch.object(_vr, "assert_a2", return_value=dict(stub_ok)), \
            mock.patch.object(_vr, "assert_a3", return_value=dict(stub_ok)), \
            mock.patch.dict(os.environ, {
                "HIVE_ROLE": "verifier",
                "HIVE_INSTANCE": "verifier",
                "SUBJECT_FP": "b" * 64,
            }):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_ok = _vr.main(["verify_runner.py", good_id])
    check("D5c 正向对照：verify_runner.main(合法 iter_id) 正常产出 verdict.json",
          rc_ok == 0 and os.path.isfile(expected_vrd),
          f"rc={rc_ok} out={buf.getvalue()[:160]!r}")


def main() -> int:
    try:
        _group_a_refindex()
        _group_b_wm()
        _group_c_exec_cmd()
        _group_d_interop_runner()
    finally:
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
    print(f"\n结果：PASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
