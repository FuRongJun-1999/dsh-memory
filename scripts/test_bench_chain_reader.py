# -*- coding: utf-8 -*-
r"""守卫 · 官方口径灵枢臂 harness（task-32）。

判据：
  A 提示词**逐字取自官方**：与官方 probe_runner.py 的 CHAIN_SYS / build_prompt 逐字相等，
    且本仓 harness 源码里**不出现**该提示词文本（证明没有自造副本）。
  B 密钥零外泄：把哨兵假密钥灌进同一条读取路径，扫描 stdout/stderr 与**全部产物文件**零命中。
  C 官方布局与 manifest 字段齐备（sut/out/<qid>.json、retrieval/<qid>.json、manifest.json，
    后者含 arm/keys_fp/limit/llm_calls/failures/model + 官方原键 arm/errors/generator/...）。
  D keys_fp 与官方**现算**值一致（probe_judge.keys_fp()），且等于本套答案键的已发布值。
运行：
  python -X utf8 -m scripts.test_bench_chain_reader                    # 期望 0 退出
  python -X utf8 -m scripts.test_bench_chain_reader --mutate=keys_fp    # 期望 1（D 红）
  python -X utf8 -m scripts.test_bench_chain_reader --mutate=prompt     # 期望 1（A 红）
  python -X utf8 -m scripts.test_bench_chain_reader --mutate=leak       # 期望 1（B 红）
变异说明：mutate 注入的是**病灶等价物**（写死错 keys_fp / 换自造提示词 / 把假密钥写进产物），
         期望对应判据转红——用于自证判据有判别力，非空跑。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: 官方基准仓落点：**只在环境变量缺省时用**，且不含本机绝对路径
#: （追踪面门禁 `scripts/check_local_paths.py` 禁止本机路径）。真实路径用
#: 环境变量 `MEMBENCH_CHAIN_BENCH` 覆盖；缺省取运行期临时目录（下方有 SKIP 分支兜住）。
BENCH = Path(os.environ.get(
    "MEMBENCH_CHAIN_BENCH",
    os.path.join(tempfile.gettempdir(), "bench")))
SENTINEL = "sk-GUARD-SENTINEL-DO-NOT-LEAK-0123456789"
KEYS_FP_EXPECTED = "bda3d94b7f29526a"

PASS = FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (label, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(label)
        print("[FAIL] %s  · %s" % (label, detail))


def _load_official(bench: Path, name: str):
    """从**官方仓原址**按文件路径加载模块（不经 stage、不经 sys.path 缓存）。"""
    p = bench / "chain" / "tools" / name
    spec = importlib.util.spec_from_file_location("_official_" + name[:-3], p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_harness(stage: Path):
    """在受控条件下跑一次 harness（dry-run、哨兵密钥），返回 (rc, stdout, stderr)。"""
    import bench_chain_reader as B
    B.read_machine_key = lambda name="DEEPSEEK_API_KEY": SENTINEL
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = B.main(["--llm-dry-run", "--limit", "2", "--stage", str(stage)])
    return rc, buf.getvalue(), err.getvalue()


def scan_sentinel(text: str, files) -> list:
    hits = [("<stdout>" if i == 0 else "<stderr>") for i, t in enumerate([text]) if SENTINEL in t]
    for p in files:
        try:
            if SENTINEL in p.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(p))
        except OSError:
            pass
    return hits


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = ""
    for a in argv:
        if a.startswith("--mutate="):
            mutate = a.split("=", 1)[1]
    if not (BENCH / "chain" / "tools" / "probe_runner.py").exists():
        print("[SKIP] 官方仓不在位：%s（守卫无法比对官方提示词）" % BENCH)
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="bench_chain_guard_"))
    try:
        rc, out, err = run_harness(tmp)
        ok(rc == 0, "harness 冒烟在零网络 dry-run 下跑通（rc=0）", "rc=%s" % rc)
        runs = tmp / "membench" / "dist" / "记忆系统对比_v1.0" / "runs" / "chain_lingshu"
        mf_p = runs / "manifest.json"
        mf = json.loads(mf_p.read_text(encoding="utf-8")) if mf_p.exists() else {}

        # ---- A 提示词逐字取自官方 ----
        off = _load_official(BENCH, "probe_runner.py")
        staged = _load_official(tmp, "probe_runner.py") if (tmp / "chain" / "tools" / "probe_runner.py").exists() else None
        src = (REPO / "scripts" / "bench_chain_reader.py").read_text(encoding="utf-8")
        sysmod = sys.modules.get("probe_runner")
        got_sys_text = getattr(sysmod, "CHAIN_SYS", None)
        if mutate == "prompt":
            got_sys_text = "你是被评测的记忆理解系统。自造提示词（变异注入）。"
        ok(got_sys_text == off.CHAIN_SYS,
           "A1 运行期 CHAIN_SYS 与官方 probe_runner.CHAIN_SYS 逐字相等",
           "len=%s vs 官方 %s" % (len(got_sys_text or ""), len(off.CHAIN_SYS)))
        if staged is not None:
            ok(staged.CHAIN_SYS == off.CHAIN_SYS and staged.build_prompt.__code__.co_code
               == off.build_prompt.__code__.co_code,
               "A2 stage 内 probe_runner 的 CHAIN_SYS 与 build_prompt 字节码同官方")
        ok(off.CHAIN_SYS[:24] not in src,
           "A3 本仓 harness 源码**不含**官方提示词文本（无自造副本）")

        # ---- B 密钥零外泄 ----
        files = [p for p in tmp.rglob("*") if p.is_file()]
        if mutate == "leak":
            (tmp / "LEAKED.txt").write_text("key=" + SENTINEL, encoding="utf-8")
            files.append(tmp / "LEAKED.txt")
        hits = scan_sentinel(out + err, files)
        ok(not hits, "B 哨兵密钥零外泄（stdout/stderr + %d 个产物文件）" % len(files),
           "命中 %r" % hits[:3])

        # ---- C 官方布局 + manifest 字段 ----
        sut = sorted((runs / "sut" / "out").glob("*.json")) if (runs / "sut" / "out").exists() else []
        ret = sorted((runs / "retrieval").glob("*.json")) if (runs / "retrieval").exists() else []
        ok(len(sut) == 2 and len(ret) == 2, "C1 官方布局齐备（sut/out 与 retrieval 各 2 个）",
           "sut=%d retrieval=%d" % (len(sut), len(ret)))
        need = ("arm", "keys_fp", "limit", "llm_calls", "failures", "model")
        have = [k for k in need if k in mf]
        ok(len(have) == len(need), "C2 manifest 含六件（arm/keys_fp/limit/llm_calls/failures/model）",
           "缺 %r" % [k for k in need if k not in mf])
        ok(all(k in mf for k in ("errors", "generator", "n_questions", "phase")),
           "C3 官方原键未被顶掉（errors/generator/n_questions/phase）",
           "键数=%d" % len(mf))
        ok(mf.get("created_at_mode") in ("write_time", "fact_time"),
           "C4 created_at_mode 口径标记在场（A/B 可分）", "=%r" % mf.get("created_at_mode"))

        # ---- D keys_fp 与官方现算一致 ----
        off_j = _load_official(BENCH, "probe_judge.py")
        ok(Path(off_j.__file__).parent != runs, "D0 判分器取自官方原址（非 stage 副本旁证）")
        keys = json.loads((tmp / "chain" / "tools" / "out" / "keys.json").read_text(encoding="utf-8"))
        fp_live = off_j.keys_fp(keys)
        got_fp = "deadbeef" if mutate == "keys_fp" else mf.get("keys_fp")
        ok(got_fp == fp_live == KEYS_FP_EXPECTED,
           "D keys_fp 三方一致（manifest == 官方现算 == 已发布值）",
           "manifest=%s live=%s 期望=%s" % (got_fp, fp_live, KEYS_FP_EXPECTED))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nbench_chain_reader 守卫：%d pass / %d fail%s"
          % (PASS, FAIL, ("（变异=%s）" % mutate) if mutate else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())