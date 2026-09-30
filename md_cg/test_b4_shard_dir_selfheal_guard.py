# -*- coding: utf-8 -*-
# 功能名：B4 分片目录缺失自愈的**独立**判别力守卫（长驻进程内 `_index_log/` 被删后 append 必自愈、必留痕、read_all 不回归）
# 生效条件：`md_cg/fsutil.py` 的 `ShardedLog`（`__init__` 首建 / `append` 打开前复查）经唯一实现点 `ensure_shard_dir` 保证分片目录存在时；本守卫以真实 `MdCG` 实例在沙箱库根上端到端跑，**不读在役库**。
# 子功能：①端到端自愈（写 1 条 → rmtree `_index_log/` → 再写 3 条全成功 + 目录重建 + 分片记录与读面可见）；②可观测（记账 + 有界样本 + stderr 告警，重建失败也记账）；③`read_all` 既有语义（非目录 → `[]`）；④单点（AST：全文件 `ensure_shard_dir` 只有 1 份定义，`ShardedLog` 内 2 处调用点全是委托、无裸 makedirs 副本）
# 执行：python -X utf8 -m md_cg.test_b4_shard_dir_selfheal_guard（`scripts/run_tests.py md_cg` 按 `md_cg/test_*.py` 自动收集）
# 验证方式：本文件三段（A 自愈 / B 留痕 / C 既有语义 + D 单点 + E 失败结构化）；定点变异自证 = `%TEMP%\mutate_b4_guard.py`（M1 抽掉 `append` 的 `ensure_shard_dir` 调用 → 必红；M2 抽掉 `note_shard_dir_rebuild` 调用 → 必红；逐变异 finally 回写原文）
# 不适用条件：①只在「句柄为 None 的重开点」复查——已持有打开句柄期间目录被删不在本守卫面内（Windows 上被打开的文件无法删除，生产写点 `MdCG.flush` 每批写完即 close ⇒ 必经重开点）；②跨进程并发唯一性/自愈不在本面；③不覆盖 MCP 出口渲染（另有 test_b4_shard_dir_selfheal.py 的 E 组）
"""B4 守卫（独立复核版）：分片目录缺失自愈 —— 判别力守卫 + 定点变异自证。

病灶（修复前，长驻进程内 `_index_log/` 被删）：
``ShardedLog`` 只在 ``__init__`` 里 ``makedirs``，``append`` 首次 ``open`` 前不
复查目录 ⇒ 目录被删后**每次** append 都在 ``open`` 抛 ``FileNotFoundError``、
目录永不重建、索引静默落后于已落盘的正文 ``.md``。

修复（单点）：``md_cg/fsutil.py:663`` ``ensure_shard_dir`` 是分片目录存在性的
**唯一**实现，两处调用点均为委托——``fsutil.py:706``（``__init__``, "init"，首建
不记账）与 ``fsutil.py:724``（``append``, "append"，打开前复查、记账 + 告警）。

本文件的三条硬断言（对应派单 ①②③）与两条加固（单点 / 失败结构化）：
  A 自愈端到端：删目录后再写三条全成功，目录重建、分片记录与读面都可见
  B 容忍 ≠ 静默：自愈被记账（+1）、样本指向本库、stderr 有告警
  C 既有语义：``read_all`` 对不存在的目录 / 非目录路径仍返回 ``[]``
  D 单点：``ensure_shard_dir`` 只有一份定义，``ShardedLog`` 内只有两处委托调用
  E 重建失败：结构化 ``ShardDirError``（code 可机读）且失败也记账 + 告警

沙箱（派单硬约束 1）：临时根 ``tempfile.mkdtemp``；``MDCG_ROOT`` /
``MDCG_AUX_ROOT`` / ``MDCG_MASTER_KEY`` 全在沙箱内（且必须在任何 md_cg 子模块
import 之前设好——``crypto`` 的密钥路径在 import 期求值）；跑完 rmtree，
**绝不碰在役库与在役 serve**。
"""
import ast
import contextlib
import io
import os
import shutil
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前设好。
_SANDBOX = tempfile.mkdtemp(prefix="b4_guard_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import fsutil, mdcg                                    # noqa: E402

_FSUTIL_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fsutil.py")

_OK = []
_BAD = []


def _check(name, cond, detail=""):
    """一条断言 = 一个可定点变异的判据；失红时原样打印断言名与读数。"""
    if cond:
        _OK.append(name)
        print("  ok  %s" % name)
    else:
        _BAD.append(name)
        print("  RED %s    [%s]" % (name, detail))


def main():
    log_dir = None
    try:
        # ================= A 自愈端到端（派单 ①） =================
        print("== A 自愈端到端：删掉库根 _index_log/ 后再写三条 ==")
        root = os.path.join(_SANDBOX, "lib_a")
        cg = mdcg.MdCG(root, autoflush=1)         # autoflush=1 ⇒ 每写必 flush
        log_dir = os.path.join(root, "_index_log")

        fsutil.reset_shard_dir_stats()
        err1 = None
        try:
            cg.add("b4g_n1", "B4G 第一条（删目录前）", layer="knowledge")
        except Exception as exc:                              # noqa: BLE001
            err1 = "%s: %s" % (type(exc).__name__, exc)
        _check("B4G-A1 首建：写第一条成功且分片目录由 __init__ 建出",
               err1 is None and os.path.isdir(log_dir),
               repr(err1) + " isdir=%s" % os.path.isdir(log_dir))
        # 首建是正常路径，不该记账（记账面要能区分「病态自愈」与「建库」）
        _check("B4G-A2 首建不记账（where=init ⇒ 重建计数仍 0）",
               fsutil.shard_dir_stats()[0] == 0,
               "rebuilds=%d" % fsutil.shard_dir_stats()[0])
        # 长驻进程形态：flush 已 close 句柄但**保留** ShardedLog 实例
        shard_before = getattr(getattr(cg, "_log", None), "path", None)
        _check("B4G-A3 前置：ShardedLog 实例在（句柄已 close、实例仍在）",
               shard_before is not None
               and os.path.isfile(shard_before)
               and getattr(cg._log, "_fh", "x") is None,
               "path=%r" % (shard_before,))

        shutil.rmtree(log_dir)
        _check("B4G-A4 前置：库根 _index_log/ 确已删除",
               not os.path.isdir(log_dir), "isdir=%s" % os.path.isdir(log_dir))

        fsutil.reset_shard_dir_stats()
        stderr_buf = io.StringIO()
        errs = []
        with contextlib.redirect_stderr(stderr_buf):
            for i, nid in enumerate(("b4g_n2", "b4g_n3", "b4g_n4"), 1):
                try:
                    cg.add(nid, "B4G 删目录后第%d条（标记%d）" % (i, i),
                           layer="knowledge")
                except Exception as exc:                      # noqa: BLE001
                    errs.append("%s → %s: %s" % (nid, type(exc).__name__, exc))
        _check("B4G-A5 删目录后再写三条：全部成功（无异常）",
               not errs, "; ".join(errs))
        _check("B4G-A6 分片目录被重建",
               os.path.isdir(log_dir), "isdir=%s" % os.path.isdir(log_dir))
        _check("B4G-A7 重建后分片路径照常（仍是 self._log.path 同一分片名）",
               bool(shard_before) and os.path.isfile(shard_before),
               "path=%r isfile=%s" % (shard_before,
                                      os.path.isfile(shard_before)))

        # ---- 读面：分片重放面（read_all）与节点读面（新实例 get） ----
        recs = fsutil.ShardedLog.read_all(log_dir)
        got_ids = set(r.get("id") for r in recs if isinstance(r, dict))
        want = {"b4g_n2", "b4g_n3", "b4g_n4"}
        _check("B4G-A8 删目录后三条记录真落进重建的分片（read_all 含 n2/n3/n4）",
               want.issubset(got_ids), "ids=%s" % sorted(got_ids))

        cg2 = mdcg.MdCG(root, autoflush=1)        # 全新实例 = 后续读面
        got = cg2.get("b4g_n4")
        _check("B4G-A9 后续读面读到新节点（新实例 get 返回正文含标记3）",
               isinstance(got, dict) and "标记3" in (got.get("content") or ""),
               repr(got and got.get("content"))[:80])

        # ================= B 容忍 ≠ 静默（派单 ②） =================
        print("== B 自愈可观测：记账 / 样本 / stderr 告警 ==")
        rebuilds, samples, failures, _fsamples = fsutil.shard_dir_stats()
        _check("B4G-B1 自愈被记账（reset 后重建计数恰 +1）",
               rebuilds == 1, "rebuilds=%d failures=%d" % (rebuilds, failures))
        abs_dir = os.path.abspath(log_dir)
        _check("B4G-B2 记账样本指向本库分片目录且调用点标签为 append",
               any(p == abs_dir and w == "append" for p, w in samples),
               "samples=%r" % (samples,))
        err_text = stderr_buf.getvalue()
        _check("B4G-B3 自愈有 stderr 告警（不是静默吞掉）",
               "分片目录缺失，已重建" in err_text
               and "调用点 append" in err_text
               and os.path.basename(log_dir) in err_text,
               repr(err_text[:120]))

        # ================= C read_all 既有语义不回归（派单 ③） =================
        print("== C read_all 对非目录仍返回空列表（既有语义） ==")
        missing = os.path.join(_SANDBOX, "no_such_shard_dir")
        _check("B4G-C1 read_all(不存在的目录) == []",
               fsutil.ShardedLog.read_all(missing) == [],
               repr(fsutil.ShardedLog.read_all(missing))[:60])
        fpath = os.path.join(_SANDBOX, "shard_is_a_file.txt")
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write("占位：路径是文件不是目录\n")
        _check("B4G-C2 read_all(路径是文件) == []",
               fsutil.ShardedLog.read_all(fpath) == [],
               repr(fsutil.ShardedLog.read_all(fpath))[:60])

        # ================= D 单点（判据只有一份实现，第二处必须委托） =================
        print("== D 单点：ensure_shard_dir 只有一份定义 + 两处委托调用 ==")
        with open(_FSUTIL_SRC, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        defs = [n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "ensure_shard_dir"]
        _check("B4G-D1 全 fsutil.py 内 `def ensure_shard_dir` 只有 1 份",
               len(defs) == 1, "defs=%d" % len(defs))

        cls = [n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "ShardedLog"]
        calls = {}
        naked_mkdir = []
        if cls:
            for m in cls[0].body:
                if not isinstance(m, ast.FunctionDef):
                    continue
                for node in ast.walk(m):
                    if isinstance(node, ast.Call):
                        fn = node.func
                        if isinstance(fn, ast.Name) and fn.id == "ensure_shard_dir":
                            where = None
                            if len(node.args) >= 2 and isinstance(
                                    node.args[1], ast.Constant):
                                where = node.args[1].value
                            calls.setdefault(m.name, []).append(where)
                        if isinstance(fn, ast.Attribute) and fn.attr in (
                                "makedirs", "mkdir"):
                            naked_mkdir.append("%s:%s" % (m.name, fn.attr))
        _check("B4G-D2 ShardedLog.__init__ 委托 ensure_shard_dir(...,\"init\")",
               "init" in calls.get("__init__", []), "calls=%r" % (calls,))
        _check("B4G-D3 ShardedLog.append 委托 ensure_shard_dir(...,\"append\")",
               "append" in calls.get("append", []), "calls=%r" % (calls,))
        _check("B4G-D4 ShardedLog 内无裸 makedirs/mkdir 副本",
               not naked_mkdir, "naked=%r" % (naked_mkdir,))

        # ================= E 重建失败：结构化 + 也留痕（加固） =================
        print("== E 重建失败：结构化 ShardDirError（code 可机读）+ 失败也记账 ==")
        e_dir = os.path.join(_SANDBOX, "lib_e", "_index_log")
        os.makedirs(os.path.dirname(e_dir), exist_ok=True)
        elog = fsutil.ShardedLog(e_dir)           # init 首建
        elog.append({"id": "b4g_e1"})
        elog.close()                              # 复现「句柄为 None 的重开点」
        shutil.rmtree(e_dir)
        with open(e_dir, "w", encoding="utf-8") as fh:
            fh.write("占位：用文件占住分片目录路径\n")   # makedirs 必失败
        f_before = fsutil.shard_dir_stats()[2]
        ebuf = io.StringIO()
        eerr = None
        with contextlib.redirect_stderr(ebuf):
            try:
                elog.append({"id": "b4g_e2"})
            except Exception as exc:                          # noqa: BLE001
                eerr = exc
        _check("B4G-E1 重建失败抛结构化 ShardDirError（不是裸 OSError 族）",
               isinstance(eerr, fsutil.ShardDirError),
               "%s: %s" % (type(eerr).__name__, str(eerr)[:80]))
        _check("B4G-E2 仍是 OSError 子类 + code 可机读 + message 首字段含 [code]",
               isinstance(eerr, OSError)
               and getattr(eerr, "code", None) == fsutil.SHARD_DIR_ERR_CODE
               and str(eerr).startswith("[%s]" % fsutil.SHARD_DIR_ERR_CODE),
               "code=%r" % (getattr(eerr, "code", None),))
        f_after = fsutil.shard_dir_stats()[2]
        _check("B4G-E3 重建失败也记账 + 告警（异常可能被上层兜底吞掉）",
               f_after == f_before + 1 and "重建失败" in ebuf.getvalue(),
               "failures %d→%d stderr=%r" % (f_before, f_after,
                                             ebuf.getvalue()[:100]))

    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)

    print("\n==== B4 独立守卫：%d 通过%s ====" % (
        len(_OK), "，%d 失败：%s" % (len(_BAD), "; ".join(_BAD)) if _BAD else ""))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())
