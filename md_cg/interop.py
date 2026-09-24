# -*- coding: utf-8 -*-
"""互验工具库（批次10，互验定稿 §7 的 python 落地）。

三断言（§7.5）：
  A1  verifier_instance != subject_instance          —— 是两个人
  A2  verifier_fingerprint != subject_fingerprint    —— 指纹不同
  A3  verifier_fingerprint == 本轮冻结值             —— 看同一把尺子（承重墙）
任一不成立 → 验证结论作废。

verdict 脱敏硬门禁（§7.3）：入库即公开，只允许结构化事实（指纹/断言/计数/
SHA/迭代 id/时间戳/符号化路径）；禁止 spec 正文/prompt/result.content/
API 信息/本机绝对路径——违规抛 InteropSanityError。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 判据面实现（2026-09-24 修复）：包内模块；出货包不含 scripts/，且 DSH 沙箱
# 禁子进程管道，故**进程内**调用。MDCG_JUDGMENT_MANIFEST 可指向外部实现文件
# （自定义判据面时用；按文件路径加载，需提供 collect()/digest()）。
MANIFEST_ENV = "MDCG_JUDGMENT_MANIFEST"

_FORBIDDEN_RES = [
    (re.compile(r"[A-Za-z]:[\\\\/]"), "本机绝对路径（盘符）"),
    (re.compile(r"/Users/|/home/"), "本机绝对路径（unix 家目录）"),
    (re.compile(r"https?://[^\s\"']*(api|key|token)", re.I), "API 端点/凭证 URL"),
    (re.compile(r"sk[-_][A-Za-z0-9]{8,}"), "疑似 API key"),
    # issue #37 J5 扩面（纵深防御的真实宽度对齐声明）：
    (re.compile(r"\\\\[A-Za-z0-9_$.-]+\\"), "本机绝对路径（UNC）"),
    (re.compile(r"/Volumes/"), "本机绝对路径（macOS 挂载）"),
    (re.compile(r"(?:^|[\s\"'(=,])/(?:etc|usr|var|opt|root|tmp|private)/"),
     "本机绝对路径（unix）"),
    (re.compile(r"(?:^|[\s\"'(=,])~/"), "家目录缩写 ~"),
    (re.compile(r"\$HOME"), "家目录变量"),
    (re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
                r"|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}"
                r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})"),
     "公开密钥形态"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer 凭证"),
    (re.compile(r"\b(?:user_prompt|result\.content|spec_body|system_prompt)"
                r"\b\s*[::=]", re.I), "prompt/content 文本形态"),
]
_FORBIDDEN_KEYS = {"prompt", "content", "spec", "api_key", "base", "model",
                   "system_prompt", "user_prompt", "content_head"}


class InteropSanityError(ValueError):
    """verdict 脱敏门禁违规（入库即公开，违规内容不得落盘）。"""


def _manifest_module():
    """取判据面实现模块，优先级：

      ① `MDCG_JUDGMENT_MANIFEST` 外部实现（自定义判据面）
      ② **源码树的 `scripts/judgment_manifest.py`**——验证器侧（hive runner /
         serve 心跳）用它算 digest，A3 要求两侧**同一份实现**；源码树在时
         必须用它，否则两侧判据面构成一旦分叉，digest 必不相等（A3 全红）。
      ③ 包内 `md_cg/judgment_manifest.py`——出货包不含 `scripts/`，
         安装态回落此处（构成与 ② 同步维护）。
    """
    override = (os.environ.get(MANIFEST_ENV) or "").strip()
    if override:
        if not os.path.isfile(override):
            raise RuntimeError(
                f"{MANIFEST_ENV} 指向的文件不存在：{override}")
        return _load_manifest_file(override)
    src = os.path.join(HERE, "scripts", "judgment_manifest.py")
    if os.path.isfile(src):
        return _load_manifest_file(src)
    from . import judgment_manifest as mod
    return mod


def _load_manifest_file(path):
    """按路径加载判据面实现（需提供 collect()/digest()）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_mdcg_judgment_manifest_ext", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("collect", "digest"):
        if not callable(getattr(mod, fn, None)):
            raise RuntimeError(f"{path} 不是合法判据面实现（缺 {fn}()）")
    return mod


def _manifest(action: str):
    """判据面清单/指纹（进程内，无子进程）。

    历史（2026-09-24 修复）：0.4.x 以 `subprocess.run([python, scripts/
    judgment_manifest.py, ...])` 取清单——出货包不含 scripts/，安装态必抛
    FileNotFoundError（判据面是运行时依赖，不是可选工具）；且 DSH 文件沙箱
    禁止子进程管道（CreatePipe → WinError 5），该写法在受限宿主里连空库都跑不动。
    现改为直接调用包内模块，语义（PATTERNS/排序/digest 算法）与原脚本逐字一致。
    """
    mod = _manifest_module()
    manifest = mod.collect()
    if action == "--digest":
        return mod.digest(manifest)
    return json.dumps(manifest, ensure_ascii=False)


def freeze(iter_id: str, out_dir: str = None) -> dict:
    """第 0 步：记录本轮判据面冻结凭证（A3 的比对基准）。

    out_dir 缺省 = hive/interop/<iter_id>/；显式传入时视为最终目录（不拼 iter_id）。
    注意（issue #37 J6）：verify_runner 固定读 repo 标准位置——显式 out_dir
    冻结的凭证**不被 runner 识别**（仅适用于单测/离线留痕），此处显式警告。
    """
    if out_dir is not None:
        sys.stderr.write("[interop] 警告：显式 out_dir 的冻结凭证不被 "
                         "verify_runner 识别（runner 固定读 hive/interop/"
                         "<iter_id>/frozen.json）——仅适用于单测/离线留痕\n")
    manifest = json.loads(_manifest(""))
    credential = {
        "iter_id": iter_id,
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "digest": _manifest("--digest"),
        "files": manifest["files"],
        # 判据面是源码树概念：安装态（出货包）只有 md_cg/test_*.py 一组可得。
        # 缺失组随凭证落盘 → A3 两侧布局不一致时可判因，而不是只见「指纹不符」。
        "missing_patterns": manifest.get("missing_patterns") or [],
    }
    if out_dir is None:
        out_dir = os.path.join(HERE, "hive", "interop", iter_id)
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "frozen.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(credential, f, ensure_ascii=False, indent=2)
    credential["_path"] = fp
    return credential


def assert_a3(frozen: dict, verifier_fingerprint: str) -> dict:
    """A3（承重墙）：验证者声明的判据面指纹 == 本轮冻结值。"""
    ok = verifier_fingerprint == frozen.get("digest")
    return {"assertion": "A3", "ok": ok,
            "frozen": frozen.get("digest"), "actual": verifier_fingerprint}


def assert_a1(verifier_instance: str, subject_instance: str) -> dict:
    return {"assertion": "A1",
            "ok": bool(verifier_instance and subject_instance
                       and verifier_instance != subject_instance),
            "verifier": verifier_instance, "subject": subject_instance}


def assert_a2(verifier_fingerprint: str, subject_fingerprint: str) -> dict:
    """A2（辅助断言）：两实例指纹不同。**subject_fp 为派发方自报值，本断言不核验
    其真伪**（issue #37 J2：复用 #27 的 self-reported 分层标注）——设计定稿
    （§7.5）明示 A1/A2 起两进程即自动成立、不构成保证，防线在 A3（冻结值）。
    """
    ok = bool(verifier_fingerprint and subject_fingerprint
              and verifier_fingerprint != subject_fingerprint)
    return {"assertion": "A2", "ok": ok,
            "verifier": verifier_fingerprint, "subject": subject_fingerprint,
            "subject_fp_source": "self-reported"}


def sanity_check_verdict(verdict: dict) -> None:
    """脱敏硬门禁：递归扫描 verdict 全部键与字符串值，违规即抛。"""
    def walk(obj, path="$"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in _FORBIDDEN_KEYS:
                    raise InteropSanityError(
                        f"{path}.{k}: 禁止字段（spec 正文/prompt/API 信息不得入库）")
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            for i, (pat, why) in enumerate(_FORBIDDEN_RES):
                if pat.search(obj):
                    raise InteropSanityError(
                        f"{path}: 疑似 {why}（命中 {i} 号规则）")

    walk(verdict)


# issue #37 J5：黑名单天然漏——补「字符集 + 形状」白名单校验（与本仓
# 「能机械判的绝不猜」纪律同源）。verdict 的结构是固定契约，任何越权字段
# 或坏形状（指纹非十六进制、计数非整数、枚举外值）在落盘前即拒。
_ALLOWED_TOP = {"iter_id", "verifier_instance", "verifier_fingerprint",
                "subject_instance", "subject_fingerprint", "suite_origin",
                "frozen_at", "verdict", "passed", "failed", "details",
                "valid", "assertions_ok", "failure_reason"}
_SHAPE_FP = re.compile(r"[0-9a-f]{12,64}")


def shape_check_verdict(verdict: dict) -> None:
    """形状白名单：顶层字段集 ⊆ 契约集；指纹=12-64 位十六进制；枚举与计数
    类型受检。与 sanity_check_verdict（脱敏黑名单）互补，构成双门禁。"""
    extra = set(verdict) - _ALLOWED_TOP
    if extra:
        raise InteropSanityError(f"未知顶层字段（越权）: {sorted(extra)}")
    for k in ("verifier_fingerprint", "subject_fingerprint"):
        v = verdict.get(k)
        if v and not _SHAPE_FP.fullmatch(str(v)):
            raise InteropSanityError(
                f"{k}: 非指纹形状（期望 12-64 位十六进制）: {str(v)[:24]!r}")
    if verdict.get("verdict") not in ("pass", "fail"):
        raise InteropSanityError(
            f"verdict 非法枚举: {verdict.get('verdict')!r}")
    if verdict.get("failure_reason") not in (
            None, "suite_failed", "assertions_failed", "both"):
        raise InteropSanityError(
            f"failure_reason 非法枚举: {verdict.get('failure_reason')!r}")
    for k in ("passed", "failed"):
        v = verdict.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise InteropSanityError(f"{k}: 非非负整数: {v!r}")


def make_verdict(iter_id: str, verifier_instance: str, verifier_fingerprint: str,
                 subject_instance: str, subject_fingerprint: str,
                 suite_origin: str, frozen_at: str, verdict: str,
                 passed: int, failed: int, details=None) -> dict:
    """§7.3 契约构造 + 脱敏门禁（违规即抛，绝不落盘）。"""
    v = {
        "iter_id": iter_id,
        "verifier_instance": verifier_instance,
        "verifier_fingerprint": verifier_fingerprint,
        "subject_instance": subject_instance,
        "subject_fingerprint": subject_fingerprint,
        "suite_origin": suite_origin,
        "frozen_at": frozen_at,
        "verdict": verdict,
        "passed": passed,
        "failed": failed,
        "details": details or [],
    }
    sanity_check_verdict(v)
    return v


# ---------------------------------------------------------------- 批次11：时序原语

def dispatch_verify_job(verifier_jobs_dir: str, iter_id: str,
                        subject_fingerprint: str, timeout_s: int = 1800) -> dict:
    """§7.4 步骤3（★非阻塞★）：把验证任务作为普通蜂巢 job 投到验证实例的
    jobs 目录——文件协议即接口，写 spec.json 即完成投递，立即返回不等待
    （进度靠验证实例心跳的 iter_id/progress 拉取，不阻塞轮询）。

    subject_fingerprint 经 spec.env 传给验证执行器（主实例候选的判据面指纹，
    A2 的比对输入）。
    """
    jobs = os.path.abspath(verifier_jobs_dir)
    runner = os.path.join(HERE, "hive", "verify_runner.py")
    spec = {
        "model": "cmd",
        "user_prompt": f"互验执行 iter={iter_id}",
        "command": [sys.executable, runner, iter_id],
        "timeout_s": max(5, min(3600, timeout_s)),
        "env": {"SUBJECT_FP": subject_fingerprint, "ITER_ID": iter_id},
    }
    from .fsutil import ShardedLog  # noqa: F401  确认依赖在位
    jd = os.path.join(jobs, f"h{int(time.time() * 1000)}_disp")
    os.makedirs(jd, exist_ok=True)
    with open(os.path.join(jd, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    with open(os.path.join(jd, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"state": "pending"}, f)
    out = {"ok": True, "dispatched": jd, "iter_id": iter_id,
           "note": "非阻塞投递完成——进度靠验证实例心跳拉取，不轮询不等待"}
    # hive/ 是源码树子系统（出货包不含）：投递本身成功，但没有可执行 runner 时
    # 消费端会静默失败 → 显式报警，不假装这一票能跑（2026-09-24 补齐）。
    if not os.path.isfile(runner):
        out["warning"] = (f"验证 runner 不存在：{runner}——投递已落盘，但本次"
                          "验证不会被消费（hive/ 为源码树子系统，安装态需另行提供）")
    return out


def write_verdict_to_repo(verdict: dict, repo: str = HERE,
                          do_commit: bool = False) -> dict:
    """§7.3 留痕：verdict 写 hive/interop/<iter_id>/（受版本控制目录，
    **不用** hive/jobs/——该目录 .gitignore 且含运行态）。

    脱敏门禁在 make_verdict 已过；此处落盘前再过一次（纵深）——issue #37 J5
    后为 sanity（脱敏黑名单）+ shape（形状白名单）双门禁。do_commit=True 时
    git add+commit（**不自动 push**——推送由使用者/编排触发，§7.3 双清单
    人工确认环节保留）。
    """
    sanity_check_verdict(verdict)
    shape_check_verdict(verdict)
    it = verdict.get("iter_id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", it):
        raise ValueError(f"iter_id 非法（入库路径组成部分）: {it!r}")
    out_dir = os.path.join(repo, "hive", "interop", it)
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "verdict.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    out = {"ok": True, "path": fp}
    if do_commit:
        import subprocess
        r1 = subprocess.run(["git", "add", os.path.relpath(fp, repo)],
                            cwd=repo, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        r2 = subprocess.run(
            ["git", "commit", "-q", "-m",
             f"interop(verifier): iter={it} verdict={verdict.get('verdict')} "
             f"passed={verdict.get('passed')} failed={verdict.get('failed')}"],
            cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        out["committed"] = r2.returncode == 0
        if r2.returncode != 0:
            out["commit_err"] = (r2.stderr or r1.stderr)[:200]
    return out
