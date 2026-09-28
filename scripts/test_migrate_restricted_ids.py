# -*- coding: utf-8 -*-
"""test_migrate_restricted_ids —— N220 迁移目标复查 + override 条件守卫

背景（2026-09-28 缺陷 N220，medium；legacy 归属，首轮复测）：
  scripts/migrate_restricted.py 的 `--ids` 入口直取清单**不复查目标**密级与层，
  且恒定 `override=True`——`protect.guard_write` 的层保护闸（anchor/self）与写保护
  标记被无条件绕开：运维/外部工具生成的一份 id 清单，一次
  `--ids anchor_node,internal_node,private_node --apply` 即把保护层节点与共享档
  节点一并改写为 restricted（层保护本应抛 ProtectionError，非远程可达但**不可逆**）。
  dry-run 还按 `content[:40]` 回显正文（私有档内容倒进终端/CI 日志），并把 `--ids`
  指定节点一律计成「扫描到 private 节点」（计数与来源不符）。

守卫断言面（临时库 + 哑 Principal + 哑正文；MDCG_ROOT 全指临时目录）：
  T1 前提：直调 cg.add 覆写 anchor 节点被层保护闸拦下（ProtectionError）
  T2 dry-run：不回显正文（哑正文片段不出现在 stdout）+ 清单计数=1/跳过=2
  T3 apply 无 --force：保护层 anchor 与共享档 internal 节点**原封不动**
  T4 apply 无 --force：真 private 档照常迁移（private → restricted）
  T5 apply 无 --force：immutable 标记的 private 节点拒改并显式报出（修前被覆写）
  T6 apply --force：immutable 的 private 节点可迁（旧行为仅在显式 --force 下保留）
  T7 索引中不存在的 id 显式 SKIP（不静默、不崩）
  T8 全量扫描（无 --ids）标签与计数正确

运行：python -X utf8 scripts/test_migrate_restricted_ids.py
"""
import atexit
import gc
import importlib.util
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_MR = os.path.join(HERE, "scripts", "migrate_restricted.py")

#: 哑正文（只在 dry-run 泄露断言里用，不打印）
ANCHOR_BODY = "锚点保护层正文·含敏感线索"
PRIVATE_BODY = "私有档正文 SECRETBODY"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:400])


class _Tee:
    """同时收集 stdout 供泄露断言（守卫自有缓冲，不落盘）。"""

    def __init__(self):
        self.buf = []

    def write(self, s):
        self.buf.append(s)

    def flush(self):
        pass

    def text(self):
        return "".join(self.buf)


def _cleanup(path):
    """临时库退场清洁（机制说明）：库层 `mdcg._atexit_flush_all` 在进程退出时对仍
    存活实例补 close() → 把 `_index.json{,.lock}` 写回已删的临时根（仓库既有守卫
    md_cg/test_n202_session_notes_visibility.py:95-101 同款实测）。atexit 为 LIFO，
    本钩子在**任何 MdCG 实例创建之前**注册 → 退出时最后执行，故最终状态清净。"""
    for _ in range(10):
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(0.2)
    return not os.path.exists(path)


def _load_mr():
    spec = importlib.util.spec_from_file_location("migrate_restricted_guard", _MR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sensitivity(cg, nid):
    return (cg.get(nid) or {}).get("frontmatter", {}).get("sensitivity")


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    pri = dict(actor="migrate-restricted", clearance="secret", can_write=True,
               can_admin=True, role="designer", auth_mode="test")

    tmp = tempfile.mkdtemp(prefix="n220_guard_")
    # 先注册退场清洁（早于任何 MdCG 实例创建 → atexit LIFO 保证最后执行）
    atexit.register(lambda: _cleanup(tmp))
    root = os.path.join(tmp, "lib")
    # Windows 下库句柄未释放会让临时目录删不掉（静默残留）——显式收尾
    handles = []
    try:
        cg = MdCGSecure(root, principal=Principal(**pri))
        handles.append(cg)
        cg.add("anchor_node", ANCHOR_BODY, layer="anchor", sensitivity="internal")
        cg.add("internal_node", "共享档正文", layer="knowledge",
               sensitivity="internal")
        cg.add("private_node", PRIVATE_BODY, layer="knowledge",
               sensitivity="private")
        cg.add("frozen_private", "冻结私有正文", layer="knowledge",
               sensitivity="private", immutable=True)
        cg.flush()

        print("[0] 前提：层保护闸在场（否则本守卫无意义）")
        try:
            cg.add("anchor_node", "覆写尝试", layer="anchor", sensitivity="internal")
            check("T1 直调 cg.add 覆写 anchor 被层保护拦下", False, "未被拦下")
        except Exception as exc:  # noqa: BLE001
            check("T1 直调 cg.add 覆写 anchor 被层保护拦下",
                  type(exc).__name__ == "ProtectionError", "%s: %s" % (type(exc).__name__, exc))

        mr = _load_mr()
        ids = "anchor_node,internal_node,private_node,frozen_private,ghost_id"

        print("[1] dry-run：不回显正文 + 来源标签正确")
        tee = _Tee()
        old = sys.stdout
        sys.stdout = tee
        try:
            rc = mr.main(["--root", root, "--ids", ids])
        finally:
            sys.stdout = old
        out = tee.text()
        check("T2 dry-run exit 0", rc == 0, rc)
        check("T2 不回显锚点保护层正文（修前 content[:40] 回显）",
              ANCHOR_BODY not in out and PRIVATE_BODY not in out, out[:400])
        check("T2 不回显任何私有档正文片段",
              "SECRETBODY" not in out, out[:400])
        check("T2 标签按来源（指定 --ids）与计数（清单 1 / 跳过 4）",
              "指定 --ids 节点 5 个" in out and "清单: 1  跳过: 4" in out,
              out[:600])

        print("[2] apply 无 --force：越权目标原封不动")
        tee = _Tee()
        old = sys.stdout
        sys.stdout = tee
        try:
            rc = mr.main(["--root", root, "--apply", "--ids", ids])
        finally:
            sys.stdout = old
        out = tee.text()
        check("T3 apply exit 0", rc == 0, rc)
        cg2 = MdCGSecure(root, principal=Principal(**pri))
        handles.append(cg2)
        fm = cg2.get("anchor_node")["frontmatter"]
        check("T3 保护层 anchor 节点密级不变（internal）",
              fm.get("sensitivity") == "internal"
              and fm.get("layer") == "anchor", fm.get("sensitivity"))
        check("T3 共享档 internal 节点密级不变",
              _sensitivity(cg2, "internal_node") == "internal",
              _sensitivity(cg2, "internal_node"))
        check("T4 真 private 档照常迁移（→ restricted）",
              _sensitivity(cg2, "private_node") == "restricted",
              _sensitivity(cg2, "private_node"))
        check("T5 immutable 的 private 拒改并显式报出",
              _sensitivity(cg2, "frozen_private") == "private"
              and "frozen_private" in out and "SKIP" in out, out[:800])
        check("T7 索引中不存在的 id 显式 SKIP 不崩",
              "ghost_id" in out and "SKIP" in out, out[-400:])
        check("T3 跳过计数=4（anchor/internal/frozen/ghost）",
              "迁移: 1  跳过: 4" in out, out[-400:])

        print("[3] apply --force：仅显式承认时保留旧行为")
        tee = _Tee()
        old = sys.stdout
        sys.stdout = tee
        try:
            rc = mr.main(["--root", root, "--apply", "--force",
                          "--ids", "frozen_private"])
        finally:
            sys.stdout = old
        cg3 = MdCGSecure(root, principal=Principal(**pri))
        handles.append(cg3)
        check("T6 --force 下 immutable 的 private 可迁（→ restricted）",
              rc == 0 and _sensitivity(cg3, "frozen_private") == "restricted",
              (rc, _sensitivity(cg3, "frozen_private")))

        print("[4] 全量扫描（无 --ids）")
        tee = _Tee()
        old = sys.stdout
        sys.stdout = tee
        try:
            rc = mr.main(["--root", root])
        finally:
            sys.stdout = old
        check("T8 全量扫描标签与计数（扫描到 private 0 个）",
              rc == 0 and "扫描到 private 节点 0 个" in tee.text(), tee.text()[:300])
    finally:
        for h in handles:
            try:
                h.close()                       # 释放库句柄，否则 Windows 删不掉临时目录
            except Exception:                   # noqa: BLE001
                pass
        if not _cleanup(tmp):
            print("  [WARN] 临时目录未能清理：%s（退场 atexit 钩子会再试一次）" % tmp)

    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
