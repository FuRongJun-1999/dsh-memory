# -*- coding: utf-8 -*-
"""蜂巢工作记忆 · 任务产物版本化 v0.1（git 载体）

设计定稿与共同记忆面：docs/hive/蜂巢工作记忆_项目计划.md（三决策点、对接边界、运行手册）。

三级闸（写入 → 提交 → 合并，回退免费）：
  snapshot  commit 凭证 = result.json 终态 ok:true（第 5 条「未验证不写入」的任务级落码）
  merge     主代理显式执行（两阶段审查机械化）；冲突诚实报错不自动解决
  revert    任意提交点免费回退（生成反向提交，历史不丢）

位置约束（设计裁决）：git 操作面只在主代理侧（本文件）；worker/执行器/rust
零 git 依赖——执行器保持「读 spec.json 写 result.json」无状态契约，rust 保持纯 std（D-005）。
snapshot/merge 是主代理串行操作面（非 worker 并发面）：合并权归主代理，
worker 的写权限被结构性限制在自己的 job 目录内（位置效应落码）。

用法（输出统一单行 JSON，对齐 hive CLI 风格）：
    python hive/wm.py init     [--wm DIR]
    python hive/wm.py snapshot --job JOB_DIR --wm DIR [--artifacts A1,A2] [--branch B]
    python hive/wm.py progress [--job JOB_DIR] [--wm DIR --job-id ID] [--limit N]
    python hive/wm.py merge    --branch B --wm DIR
    python hive/wm.py log      --wm DIR [--branch B] [--limit N]
    python hive/wm.py revert   --commit SHA --wm DIR
    python hive/wm.py status   --wm DIR

分支命名：task/<job_id>（默认取 result.json 的 job_id 字段，缺失用目录名）。
提交物白名单：spec.json + result.json（必须）+ progress.jsonl + log.txt（可选）
              + --artifacts（可选）。
内容推送 GitHub 前须过第 14 条双清单；默认只存本地 / 推私有仓。

进展面（v0.4 §5.3 满上下文换人续跑，2026-09-16）：
  worker（exec.py）在自己 job 目录追加 progress.jsonl（start/tool/final/handoff/
  error 五类条目）——worker 零 git 依赖，进展只写自家目录。主代理两处消费：
  ① snapshot 时按白名单纳入（本条），② progress 子命令读回以组装续跑提示词。
  达预算交回（result.need_continue=true）时，progress 子命令聚合透出 handoff 卡；
  是否续跑由主代理裁决，wm 不自动续跑（与 exec.py 同契约）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

#: 进展卡文件名（与 hive/exec.py PROGRESS_FILE 同源契约，改一处须同步另一处）
PROGRESS_FILE = "progress.jsonl"

WM_DEFAULT = os.environ.get("HIVE_WM_DIR")
if not WM_DEFAULT:
    WM_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wm-repo")


class WmError(Exception):
    """git 操作失败（带 stderr 摘要）。"""


# 生效条件：wm 与 args 传入时以 ["git", "-C", wm, *args] 调用 subprocess.run（capture_output=True、text=True、encoding="utf-8"、errors="replace"、shell=False、env=dict(os.environ, PYTHONUTF8="1")）并返回该 CompletedProcess，non-zero 与 stderr 不在本符号判定。
def _git(wm: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        ["git", "-C", wm, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, shell=False,
    )


# 生效条件：wm 与 args 传入时转交 _git(wm, *args)，其 returncode != 0 时抛 WmError（消息取 r.stderr 为真值、为空串则回落 r.stdout，strip 后截 300 字符），returncode == 0 时返回 r.stdout。
def _git_ok(wm: str, *args: str) -> str:
    r = _git(wm, *args)
    if r.returncode != 0:
        raise WmError(f"git {' '.join(args[:2])} 失败: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


# 生效条件：path 能按 encoding="utf-8" 打开时返回 json.load(f) 的结果；path 打不开或内容非合法 JSON 时由 open/json.load 抛出，本符号不捕获、不校验。
def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 三级闸命令

# 生效条件：wm 下 .git 为目录时直接返回 {"ok": True, "wm": wm, "note": "已是 git 仓（幂等）"}；否则 os.makedirs(wm, exist_ok=True) 后依次 git init -b main、config user.name/ user.email/core.quotepath、写 README.md、add README.md、commit，返回 {"ok": True, "wm": wm, "branch": "main"}。
def cmd_init(wm: str) -> dict:
    """建工作记忆仓（幂等）；本地配置不依赖全局 git 身份。"""
    os.makedirs(wm, exist_ok=True)
    if os.path.isdir(os.path.join(wm, ".git")):
        return {"ok": True, "wm": wm, "note": "已是 git 仓（幂等）"}
    _git_ok(wm, "init", "-b", "main")
    _git_ok(wm, "config", "user.name", "hive-wm")
    _git_ok(wm, "config", "user.email", "wm@hive.local")
    _git_ok(wm, "config", "core.quotepath", "false")  # 中文文件名可读
    with open(os.path.join(wm, "README.md"), "w", encoding="utf-8") as f:
        f.write(
            "# 蜂巢工作记忆\n\n"
            "任务产物版本化仓（三级闸：snapshot→merge→revert）。\n"
            "内容推送 GitHub 前须过第 14 条双清单；默认只存本地/推私有仓。\n"
            "设计定稿：docs/hive/蜂巢工作记忆_项目计划.md\n"
        )
    _git_ok(wm, "add", "README.md")
    _git_ok(wm, "commit", "-m", "init 工作记忆仓")
    return {"ok": True, "wm": wm, "branch": "main"}


# 生效条件：job 下 result.json 非 os.path.isfile 时先返回凭证不足错误，result.json 可读但 result.get("ok") is not True 时返回带 verdict（str(result.get("error",""))[:200]）的错误，job 下 spec.json 非 os.path.isfile 时返回规格缺失错误；通过后 job_id 取 str(result.get("job_id") or os.path.basename(job))（result.job_id 为 None/空串时回落 basename(job)），job_id 含 / \ 或为 . .. 时返回非法 job_id 错误（路径段校验，防穿越删库），branch 为真值时用 branch、假值时回落 f"task/{job_id}"，artifacts 为真值时先按逗号切分（strip 后非空段）、相对名拼 job 做存在性预检，任一源非 os.path.isfile 即在任何 staging 写入前返回 artifacts 缺失错误（v10 N83：不拷半份）；随后 rmtree/makedirs(wm/jobs/<job_id>) 并拷 spec.json、result.json、log.txt 与 PROGRESS_FILE（两者各自 os.path.isfile 为真才拷、PROGRESS_FILE 缺失即 has_progress=False 不报错）、拷 artifacts/ 并收集 basename；然后 checkout -B branch、add jobs、commit（model 取 result.get("model") 为假值回落 "?"，duration_s 为真值才附）、rev-parse --short HEAD 四步包于内层 try/finally——finally 无条件 checkout main（v2 N10：提交链任一步抛 WmError 也不残留 HEAD 于 task 分支），checkout main 失败时若 try 内有正传播异常则抛消息合并且 from 原异常的 WmError、无则直接抛 WmError（均含 HEAD 可能残留提示）；staging 拷贝起至提交链整体包于外层 try/except——任一步异常先 rmtree 清理已拷入的 wm/jobs/<job_id>/（不留绕闸残留）再原样重抛；全部成功返回 ok True 与 job_id/branch/commit/artifacts/progress/message。
def cmd_snapshot(job: str, wm: str, artifacts: str | None = None,
                 branch: str | None = None) -> dict:
    """凭证闸：result.ok=true 才许提交；白名单拷贝产物后 commit 到任务分支。

    串行契约：快照结束还原 HEAD 到 main（v2 N10：提交链失败也还原——
    try/finally，不残留 task 分支）；并发多任务由主代理串行调度。
    """
    job = os.path.abspath(job)
    result_path = os.path.join(job, "result.json")
    spec_path = os.path.join(job, "spec.json")
    if not os.path.isfile(result_path):
        return {"ok": False, "error": f"凭证不足: {result_path} 不存在（任务未完成不许提交）"}
    result = _read_json(result_path)
    if result.get("ok") is not True:
        return {
            "ok": False,
            "error": f"凭证不足: result.ok={result.get('ok')!r}（第 5 条：未验证不写入）",
            "verdict": str(result.get("error", ""))[:200],
        }
    if not os.path.isfile(spec_path):
        return {"ok": False, "error": f"{spec_path} 不存在（任务规格缺失，不可复现）"}

    job_id = str(result.get("job_id") or os.path.basename(job))
    if job_id in (".", "..") or "/" in job_id or "\\" in job_id:
        return {"ok": False, "error": (
            f"非法 job_id {job_id!r}：须为单一路径段（含 / \\ .. 即拒，"
            f"防穿越删库——result.json 产物不可信）")}
    branch = branch or f"task/{job_id}"

    # artifacts 存在性预检（v10 N83 止血，2026-09-25）：校验先于任何 staging
    # 写入。旧序（拷 spec/result/log 后才校验）在 artifacts 缺失早退时把
    # jobs/<job_id>/ 残留留在工作区——后续任一正常快照的 `git add jobs`
    # 全量扫入残留并随其 merge 进 main：失败任务产物绕过自己的凭证闸/
    # 专属分支/三级闸合并审查直达 main（确定性触发，无需攻击者）。
    art_srcs: list[str] = []
    if artifacts:
        for a in [x.strip() for x in artifacts.split(",") if x.strip()]:
            src = a if os.path.isabs(a) else os.path.join(job, a)
            if not os.path.isfile(src):
                return {"ok": False, "error": f"artifacts 缺失: {src}"}
            art_srcs.append(src)

    dest = os.path.join(wm, "jobs", job_id)
    try:
        # staging：白名单拷贝进 wm 仓（product = spec + result + log + artifacts）
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest)
        shutil.copy2(spec_path, os.path.join(dest, "spec.json"))
        shutil.copy2(result_path, os.path.join(dest, "result.json"))
        log_path = os.path.join(job, "log.txt")
        if os.path.isfile(log_path):
            shutil.copy2(log_path, os.path.join(dest, "log.txt"))
        # 进展卡（v0.4 §5.3）：worker 写的交接面随快照入库，续跑/复盘才有据可依。
        # 可选件——短任务（无工具轮次）不产生 progress，缺省不报错。
        prog_path = os.path.join(job, PROGRESS_FILE)
        has_progress = os.path.isfile(prog_path)
        if has_progress:
            shutil.copy2(prog_path, os.path.join(dest, PROGRESS_FILE))
        art_names: list[str] = []
        if art_srcs:
            os.makedirs(os.path.join(dest, "artifacts"), exist_ok=True)
            for src in art_srcs:
                name = os.path.basename(src)
                shutil.copy2(src, os.path.join(dest, "artifacts", name))
                art_names.append(name)

        # 提交链（v2 N10，2026-09-25）：任一步失败（典型：重复快照已合并任务 →
        # nothing to commit 退出码 1 → _git_ok 抛 WmError）也必须在 finally 里把
        # HEAD 还原到 main——否则 HEAD 永久残留在 task/<job_id>，后续 snapshot 的
        # checkout -B 会以残留分支为祖先，合并新任务即把旧任务产物静默带进 main
        # （绕过旧任务分支自己的三级闸合并审查）。还原失败同样不吞：合并留痕
        # 抛 WmError（正传播中的原异常经 from 链保留、消息并入）。
        head = ""
        try:
            _git_ok(wm, "checkout", "-B", branch)
            _git_ok(wm, "add", "jobs")
            model = result.get("model") or "?"
            dur = result.get("duration_s")
            msg = f"task {job_id} verdict=ok model={model}" + (f" duration_s={dur}" if dur else "")
            _git_ok(wm, "commit", "-m", msg)
            head = _git_ok(wm, "rev-parse", "--short", "HEAD").strip()
        finally:
            r = _git(wm, "checkout", "main")
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip()[:200]
                prev = sys.exc_info()[1]
                if prev is not None:
                    raise WmError(f"{prev}；且快照后还原 main 失败（HEAD 可能残留于"
                                  f" {branch}）: {detail}") from prev
                raise WmError(f"快照后还原 main 失败（HEAD 可能残留于 {branch}）: {detail}")
    except Exception:
        # 失败清理（v10 N83）：本次快照未走完（拷贝 OSError / 提交链 WmError），
        # 已拷入的 staging 撤销——不留任何绕闸残留（后续 `git add jobs`
        # 扫不到），分支历史与 main 均不受本次失败影响。
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return {"ok": True, "job_id": job_id, "branch": branch, "commit": head,
            "artifacts": art_names, "progress": has_progress, "message": msg}


# ---------------------------------------------------------------- 进展面读取

# 生效条件：lines 逐行 strip，空行跳过且不计 total，非空行 total+1 并尝试 json.loads，抛 json.JSONDecodeError 的行不入 entries；返回 entries 在 limit > 0 时取 entries[-limit:]，limit <= 0（含 0）时返回全部 entries，并附非空行总数 total。
def _parse_progress(lines, limit: int) -> tuple[list[dict], int]:
    """解析进展卡行流：返回 (尾部 limit 条, 总行数)。坏行跳过不炸（诚实降级）。"""
    entries: list[dict] = []
    total = 0
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        total += 1
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return (entries[-limit:] if limit > 0 else entries), total


# 生效条件：path 按 encoding="utf-8"、errors="replace" 打开成文件对象并连同 limit 交给 _parse_progress，故 limit > 0 返回尾部 limit 条、limit <= 0 返回全部，附非空行总数；path 打不开由 open 抛出。
def _read_progress(path: str, limit: int) -> tuple[list[dict], int]:
    """读工作区进展卡文件（委托 _parse_progress）。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        return _parse_progress(f, limit)


# 生效条件：job 为真值且（wm 或 job_id 为真值）时返回 "二选一" 错误；仅 job 为真值（wm/job_id 均假值）时读 os.path.abspath(job)/PROGRESS_FILE，非 os.path.isfile 则返回 source="job" 的进展卡缺失错误；wm 与 job_id 均为真值（job 假值）时先校验 job_id 为单一路径段（in (".","..") 或含 / \\ 即返回非法 job_id 错误，防穿越越权读——与 cmd_snapshot 同款），通过后先试 wm/jobs/<job_id>/PROGRESS_FILE（os.path.isfile 为真即读，source="wm"），否则 git show task/<job_id>:jobs/<job_id>/PROGRESS_FILE，其 returncode != 0 返回 source="wm" 的缺失错误，成功则按 r.stdout.splitlines() 解析（source="wm_branch"）；job 假值且 wm/job_id 中任一为假值（含仅传 wm、仅传 job_id、全不传）走 else 返回 "需 --job JOB_DIR 或 --wm DIR --job-id ID"；limit 默认 50，limit > 0 取尾部 limit 条、limit <= 0 取全部，返回 ok True 与 source/path/ref/count/total/kinds（str(e.get("kind") or "?") 计数）及 entries 中倒序第一个 kind=="handoff" 的条目（无则为 None）。
def cmd_progress(job: str | None = None, wm: str | None = None,
                 job_id: str | None = None, limit: int = 50) -> dict:
    """读进展卡（换人续跑的交接面）。

    两种来源（恰需其一）：
      --job JOB_DIR               运行中/未快照的 job 目录（worker 直写处）
      --wm DIR --job-id ID        已快照入库的进展

    已快照来源自动走**两级查找**（取证 2026-09-16）：cmd_snapshot 提交后把
    HEAD 还原到 main，产物只存在于 `task/<job_id>` 分支——工作区直读必然落空。
    故 ①先看工作区 `<wm>/jobs/<ID>/progress.jsonl`（分支被 merge 或手工
    checkout 后的形态），②落空则 `git show task/<ID>:jobs/<ID>/progress.jsonl`
    从分支读。两级皆空才判缺（避免「已快照」被误报成「无进展」）。

    返回 entries（尾部 limit 条）+ handoff 聚合卡 + 逐类计数 + ref（读取出
    处，诊断可见），供主代理组装续跑提示词；续跑与否仍由主代理裁决
    （auto_continue 恒 false）。
    """
    if job and (wm or job_id):
        return {"ok": False, "error": "二选一：--job 或 --wm+--job-id，不可并用"}
    if job:
        path = os.path.join(os.path.abspath(job), PROGRESS_FILE)
        if not os.path.isfile(path):
            return {"ok": False, "source": "job", "path": path,
                    "error": f"进展卡不存在: {path}",
                    "hint": "短任务（无工具轮次）不产生进展卡属正常；"
                            "若预期有进展，核对 job 目录与 --job-id"}
        entries, total = _read_progress(path, limit)
        ref, source = path, "job"
    elif wm and job_id:
        # 路径段校验（v8 N67，2026-09-25）：--job-id 拼进工作区路径
        # （os.path.join）与 git ref（task/<id>:jobs/<id>/...）两处，
        # `../../victim` 可越权读 wm 仓外任意 JSONL 并全文回显——
        # 与 cmd_snapshot 同款四行模板（姊妹面防御一致）。
        if job_id in (".", "..") or "/" in job_id or "\\" in job_id:
            return {"ok": False, "error": (
                f"非法 job_id {job_id!r}：须为单一路径段（含 / \\ .. 即拒，"
                f"防穿越越权读——progress 面 job_id 不可信）")}
        wm = os.path.abspath(wm)
        path = os.path.join(wm, "jobs", job_id, PROGRESS_FILE)
        if os.path.isfile(path):
            entries, total = _read_progress(path, limit)
            ref, source = path, "wm"
        else:
            branch = f"task/{job_id}"
            rel = f"jobs/{job_id}/{PROGRESS_FILE}"
            r = _git(wm, "show", f"{branch}:{rel}")
            if r.returncode != 0:
                return {
                    "ok": False, "source": "wm", "path": path,
                    "error": f"进展卡不存在: 工作区与分支 {branch} 均无 {rel}",
                    "hint": "核对 --job-id 是否拼写正确、或该 job 是否已 snapshot；"
                            "短任务（无工具轮次）不产生进展卡属正常",
                }
            entries, total = _parse_progress(r.stdout.splitlines(), limit)
            ref, source = f"{branch}:{rel}", "wm_branch"
    else:
        return {"ok": False, "error": "需 --job JOB_DIR 或 --wm DIR --job-id ID"}
    kinds: dict[str, int] = {}
    for e in entries:
        k = str(e.get("kind") or "?")
        kinds[k] = kinds.get(k, 0) + 1
    handoff = next((e for e in reversed(entries) if e.get("kind") == "handoff"), None)
    return {"ok": True, "source": source, "path": path, "ref": ref,
            "count": len(entries), "total": total, "kinds": kinds,
            "handoff": handoff, "entries": entries}


# 生效条件：wm 上 rev-parse --abbrev-ref HEAD 的结果 strip 后不等于 "main" 时返回 f"当前在 {cur}，merge 须在 main 上执行"错误；等于 "main" 时执行 git merge --no-ff branch，returncode != 0 时返回 conflict=("CONFLICT" in (r.stdout+r.stderr).strip())、error 为该拼接 strip 后截 500 字符，returncode == 0 时 rev-parse --short HEAD 并返回 {"ok": True, "merged": branch, "commit": head}。
def cmd_merge(branch: str, wm: str) -> dict:
    """主代理显式合并任务分支到 main；冲突诚实报错不自动解决。"""
    cur = _git_ok(wm, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if cur != "main":
        return {"ok": False, "error": f"当前在 {cur}，merge 须在 main 上执行（主代理操作契约）"}
    r = _git(wm, "merge", "--no-ff", branch, "-m", f"merge {branch} into main")
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        return {
            "ok": False,
            "conflict": "CONFLICT" in out,
            "error": out[:500],
            "hint": "处理权归主代理：人工/LLM 裁决后 git add + git commit 收口，"
                    "或 git -C <wm> merge --abort 放弃本次合并",
        }
    head = _git_ok(wm, "rev-parse", "--short", "HEAD").strip()
    return {"ok": True, "merged": branch, "commit": head}


# 生效条件：wm 上 rev-parse --abbrev-ref HEAD 的结果 strip 后不等于 "main" 时返回 f"当前在 {cur}，revert 须在 main 上执行"错误；等于 "main" 时用 rev-list --parents -n1 sha 的字段数 > 2 判断 merge 并据此在 git revert --no-edit 上附加 ("-m","1")，执行 git revert ... sha，returncode != 0 时返回 conflict=("CONFLICT" in (r.stdout+r.stderr).strip()) 与截 500 字符 error，成功则 rev-parse --short HEAD 并返回 {"ok": True, "reverted": sha, "commit": head}。
def cmd_revert(sha: str, wm: str) -> dict:
    """回退到任意提交点（生成反向提交，历史不丢=全记）；冲突同样诚实。

    merge commit（--no-ff 的任务合并）自动加 -m 1：保留主线侧、撤销分支引入的
    变更——即「撤销某次任务合并」的工作记忆语义。
    """
    cur = _git_ok(wm, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if cur != "main":
        return {"ok": False, "error": f"当前在 {cur}，revert 须在 main 上执行"}
    # rev-list --parents -n1 <sha> → "<sha> <p1> [p2 ...]"；>2 个字段 = merge
    parents = _git_ok(wm, "rev-list", "--parents", "-n1", sha).split()
    args = ("revert", "--no-edit") + (("-m", "1") if len(parents) > 2 else ()) + (sha,)
    r = _git(wm, *args)
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        return {"ok": False, "conflict": "CONFLICT" in out,
                "error": out[:500], "hint": "git -C <wm> revert --abort 可放弃"}
    head = _git_ok(wm, "rev-parse", "--short", "HEAD").strip()
    return {"ok": True, "reverted": sha, "commit": head}


# 生效条件：wm 上执行 git log --oneline f"-n{limit}" ref，其中 ref 取 branch 为真值时的 branch、branch 为假值（None/空串）时回落 "main"（limit=0 时即 -n0），返回 {"ok": True, "ref": ref, "log": out.splitlines() 中的非空行}。
def cmd_log(wm: str, branch: str | None = None, limit: int = 20) -> dict:
    ref = branch or "main"
    out = _git_ok(wm, "log", "--oneline", f"-n{limit}", ref)
    return {"ok": True, "ref": ref, "log": [ln for ln in out.splitlines() if ln.strip()]}


# 生效条件：wm 上依次执行 rev-parse --abbrev-ref HEAD（strip 为 branch）、status --porcelain、log --oneline -n3，返回 {"ok": True, "wm": wm, "branch": cur, "dirty_entries": dirty 中非空行数, "recent": recent 中的非空行}。
def cmd_status(wm: str) -> dict:
    cur = _git_ok(wm, "rev-parse", "--abbrev-ref", "HEAD").strip()
    dirty = _git_ok(wm, "status", "--porcelain")
    recent = _git_ok(wm, "log", "--oneline", "-n3")
    return {
        "ok": True, "wm": wm, "branch": cur,
        "dirty_entries": len([x for x in dirty.splitlines() if x.strip()]),
        "recent": [ln for ln in recent.splitlines() if ln.strip()],
    }


# ---------------------------------------------------------------- CLI

# 生效条件：argv 为 None 时 argparse 取 sys.argv，解析出的 args.cmd 为 "init"/"snapshot"/"progress"/"merge"/"log"/"revert" 时分别调用 cmd_init(args.wm)/cmd_snapshot(args.job,args.wm,args.artifacts,args.branch)/cmd_progress(args.job,args.wm,args.job_id,args.limit)/cmd_merge(args.branch,args.wm)/cmd_log(args.wm,args.branch,args.limit)/cmd_revert(args.commit,args.wm)，其余 cmd 走 else 调 cmd_status(args.wm)（init/snapshot/merge/log/revert/status 的 --wm 未给出时用模块级 WM_DEFAULT，各子命令 required 参数缺失由 argparse 直接退出）；任一调用抛 WmError 时打印 {"ok": False, "error": str(e)} 并返回 EXIT_FAIL，否则打印 out 且 out.get("ok") 为真返回 EXIT_OK、假返回 EXIT_FAIL。
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wm", description="蜂巢工作记忆（任务产物版本化）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--wm", default=WM_DEFAULT)

    p = sub.add_parser("snapshot")
    p.add_argument("--job", required=True)
    p.add_argument("--wm", default=WM_DEFAULT)
    p.add_argument("--artifacts", default=None, help="逗号分隔的产物文件（相对 job 或绝对）")
    p.add_argument("--branch", default=None, help="默认 task/<job_id>")

    p = sub.add_parser("progress")
    p.add_argument("--job", default=None, help="job 目录（运行中/未快照）")
    p.add_argument("--wm", default=None, help="已快照来源：工作记忆仓")
    p.add_argument("--job-id", default=None, dest="job_id",
                   help="已快照来源：job id（配 --wm）")
    p.add_argument("--limit", type=int, default=50, help="取尾部 N 条，0=全量")

    p = sub.add_parser("merge")
    p.add_argument("--branch", required=True)
    p.add_argument("--wm", default=WM_DEFAULT)

    p = sub.add_parser("log")
    p.add_argument("--wm", default=WM_DEFAULT)
    p.add_argument("--branch", default=None)
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("revert")
    p.add_argument("--commit", required=True)
    p.add_argument("--wm", default=WM_DEFAULT)

    p = sub.add_parser("status")
    p.add_argument("--wm", default=WM_DEFAULT)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            out = cmd_init(args.wm)
        elif args.cmd == "snapshot":
            out = cmd_snapshot(args.job, args.wm, args.artifacts, args.branch)
        elif args.cmd == "progress":
            out = cmd_progress(args.job, args.wm, args.job_id, args.limit)
        elif args.cmd == "merge":
            out = cmd_merge(args.branch, args.wm)
        elif args.cmd == "log":
            out = cmd_log(args.wm, args.branch, args.limit)
        elif args.cmd == "revert":
            out = cmd_revert(args.commit, args.wm)
        else:
            out = cmd_status(args.wm)
    except WmError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return EXIT_FAIL
    print(json.dumps(out, ensure_ascii=False))
    return EXIT_OK if out.get("ok") else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())