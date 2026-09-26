# -*- coding: utf-8 -*-
"""test_reconcile_v0.py · 启动对账 reconcile v0 守卫（v0.3 T9 落地，落地清单 P0-3）

现场：两段式写对账（`twophase.reconcile`）只清「有 intent 无 outcome」的写入账；
索引（派生态）vs 盘面真源（节点 .md）之间没有全量 diff——非合作写者直写文件
（缺索引条目）、外部删文件（多索引条目/幽灵）、直改正文（哈希漂移）三类背离
零告警零修复，派生态与真源静默撕裂（T9 自稳定缺口）。

修复（本守卫的红绿锚点）：`md_cg/reconcile.py` 新增 `reconcile_state(cg)`——
  · 三类 diff：多索引条目（摘除，`_unstage` 同口径）/ 缺索引条目（`_node_entry`
    重建补入）/ 哈希·路径漂移（以盘面为真源重建，增量 upsert 不触发全量
    rebuild）；
  · T9 边界：真源自身损坏（读失败 / 非 UTF-8 字节 / frontmatter 无闭合）只
    stderr 告警 + `_reconcile.jsonl` 留痕，**不自动改写**——不据损坏文件建
    条目，也不因读不出摘除既有条目（瞬态读失败被当「文件没了」= N134 同型
    放大损伤）；
  · 开关 `MDCG_RECONCILE=0` 关闭（缺省开）；干净库零输出零写盘、二次扫描
    幂等全零；
  · 承接面：`mcp_server.main()` 两段式对账之后新增 `cg.reconcile_state()`
    （失败不阻塞启动）。
先例修复（本守卫顺带锚定）：`mdcg._scan_nodes` 原只捕 OSError——一个非 UTF-8
坏文件会炸穿整库装载/重建（init 先于对账，守卫若不补，损坏库永远跑不到对账）；
补 `(OSError, UnicodeDecodeError)` 跳过，与 T9 边界同口径。

**指纹双形态**（历史事实，非本守卫发明）：add 写路径入索引的 content_hash 按
封存原文（无尾换行正文 ≠ rebuild 路径 loads 读回的带尾换行形态，实测两形态
并存）——diff 两侧双形态都认，否则无尾换行节点每次启动都误报漂移（假阳性
洪水）。[1b] 断言双形态下零误报，防未来有人「统一」掉一半。

隔离纪律：临时 tempfile.mkdtemp 库 + 哑 Principal（designer），不触真实
root/令牌库/数据目录；MDCG_RECONCILE 进出还原；测毕 rmtree。
自检 floor：断言总数低于 FLOOR 视为失败——防「探针面失效 → 假绿」。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from . import nodefile, reconcile
from .mdcg import MdCG
from .security import Principal

FLOOR = 26           # 断言总数下限（防假绿）
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _run(cg, apply=True):
    """跑一次对账并抓 stderr → (report, stderr 文本)。"""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rep = reconcile.reconcile_state(cg, apply=apply)
    return rep, err.getvalue()


def _disk_hash_of(cg, nid):
    e = cg.index["nodes"][nid]
    with open(os.path.join(cg.root, e["path"]), encoding="utf-8") as f:
        return nodefile.content_hash(nodefile.loads(f.read())[1])


def main():
    saved_sw = os.environ.get(reconcile.ENV_SWITCH)
    tmp = tempfile.mkdtemp(prefix="mdcg_recon_v0_")
    try:
        pr = Principal(actor="recon_guard", clearance="secret",
                       can_write=True, can_admin=True, role="designer")
        cg = MdCG(os.path.join(tmp, "cg"))
        # a1 刻意**无尾换行**（add 指纹形态）；a2 带尾换行（rebuild 指纹形态）
        cg.add("a1", "hello recon body", layer="knowledge")
        cg.add("a2", "world recon body\n", layer="knowledge")
        cg.flush()

        # ---- [1] 干净库：三类全零 + 双形态零误报 + 零输出零写盘 ----
        print("[1] 干净库零误报（含指纹双形态）")
        rep, err = _run(cg)
        check("1a 三类 diff 全零（多/缺/漂移）",
              not rep["ghost_entries"] and not rep["missing_entries"]
              and not rep["hash_drift"], f"rep={rep}")
        check("1b 无尾换行节点零误报（add 形态指纹被双形态接受集收容）",
              "a1" in cg.index["nodes"] and not rep["hash_drift"],
              f"drift={rep['hash_drift']}")
        check("1c rebuild 后（rebuild 形态指纹）再次对账仍零漂移",
              (cg.rebuild_index() or {}).get("nodes", {}).get("a1") is not None
              and _run(cg)[0]["hash_drift"] == [],
              f"drift={_run(cg)[0]['hash_drift']}")
        check("1d 干净库零 stderr 输出（diff 非空才发声）",
              err == "", f"stderr={err[:120]!r}")
        check("1e 干净库零写盘（无留痕文件）",
              not os.path.isfile(reconcile.trace_path(cg)),
              f"trace={reconcile.trace_path(cg)}")

        # ---- [2] 多索引条目（幽灵）：外部直删 a2 文件 ----
        print("[2] 多索引条目：外部删文件 → 检出+摘除收敛+告警留痕")
        os.remove(os.path.join(cg.root, cg.index["nodes"]["a2"]["path"]))
        rep, err = _run(cg)
        check("2a diff 检出 ghost=[a2]", rep["ghost_entries"] == ["a2"],
              f"ghost={rep['ghost_entries']}")
        check("2b 自动修复：条目摘除且 tombstone 落账（unstaged=1）",
              "a2" not in cg.index["nodes"]
              and rep["repaired"]["unstaged"] == 1, f"rep={rep}")
        check("2c stderr 告警点名", "幽灵条目" in err, f"stderr={err[:160]!r}")
        check("2d 留痕落盘（_reconcile.jsonl）",
              os.path.isfile(reconcile.trace_path(cg)),
              f"trace={reconcile.trace_path(cg)}")
        rep2, err2 = _run(cg)
        check("2e 幂等：二次扫描三类全零且零输出",
              not (rep2["ghost_entries"] or rep2["missing_entries"]
                   or rep2["hash_drift"]) and err2 == "",
              f"rep={rep2} stderr={err2[:80]!r}")

        # ---- [3] 缺索引条目：非合作写者直写文件 ----
        print("[3] 缺索引条目：直写 .md 不经索引 → 检出+补入收敛")
        fm = {"id": "x1", "layer": "knowledge", "importance": 0.4,
              "created_at": 123.0}
        with open(os.path.join(cg.root, "knowledge", "x1.md"), "w",
                  encoding="utf-8") as f:
            f.write(nodefile.dumps(fm, "ghost writer body"))
        rep, err = _run(cg)
        g = cg.get("x1")
        check("3a diff 检出 missing=[x1]", rep["missing_entries"] == ["x1"],
              f"missing={rep['missing_entries']}")
        check("3b 自动修复：条目以 _node_entry 补入（staged=1）且 get 可读",
              rep["repaired"]["staged"] == 1 and g is not None
              and "ghost writer body" in (g or {}).get("content", ""),
              f"rep={rep} get={(g or {}).get('content', '')[:40]!r}")
        check("3c 补入条目 content_hash 与盘面重算一致",
              cg.index["nodes"]["x1"]["content_hash"] == _disk_hash_of(cg, "x1"),
              f"idx={cg.index['nodes']['x1']['content_hash']} "
              f"disk={_disk_hash_of(cg, 'x1')}")

        # ---- [4] 内容漂移：外部直改 a1 正文 ----
        print("[4] 哈希漂移：直改正文 → 检出+以盘面重建收敛")
        p1 = os.path.join(cg.root, cg.index["nodes"]["a1"]["path"])
        with open(p1, encoding="utf-8") as f:
            txt = f.read()
        with open(p1, "w", encoding="utf-8") as f:
            f.write(txt.replace("hello recon body", "DRIFTED recon body"))
        rep, err = _run(cg)
        g1 = cg.get("a1")
        check("4a diff 检出 drift=[a1]", rep["hash_drift"] == ["a1"],
              f"drift={rep['hash_drift']}")
        check("4b 自动修复：检索面读到盘面新正文（盘面为真源）",
              g1 is not None and "DRIFTED recon body" in (g1 or {}).get(
                  "content", ""),
              f"get={(g1 or {}).get('content', '')[:40]!r}")
        check("4c 修复后索引指纹 == 盘面重算指纹",
              cg.index["nodes"]["a1"]["content_hash"]
              == _disk_hash_of(cg, "a1"),
              f"idx={cg.index['nodes']['a1']['content_hash']}")

        # ---- [5] 真源损坏：只告警不改写（T9 边界）----
        print("[5] 真源损坏两面：无闭合 frontmatter + 非 UTF-8 字节")
        cg.add("a3", "body three", layer="knowledge")
        cg.add("a4", "body four\n", layer="knowledge")
        cg.flush()
        with open(os.path.join(cg.root, "knowledge", "bad1.md"), "w",
                  encoding="utf-8") as f:
            f.write("---\n" + 'id: bad1\n')          # 无闭合 → 结构非法
        p4 = os.path.join(cg.root, cg.index["nodes"]["a4"]["path"])
        with open(p4, "wb") as f:
            f.write(b"---\xff\xfe\x00binary garbage")  # 非 UTF-8 字节
        rep, err = _run(cg)
        kinds = sorted(p["kind"] for p in rep["unwritable_source"])
        check("5a 损坏检出两面（decode_error + frontmatter_unterminated）",
              kinds == ["decode_error", "frontmatter_unterminated"],
              f"kinds={kinds}")
        check("5b 损坏文件不建条目（bad1 不入索引——不据损坏真源写派生态）",
              "bad1" not in cg.index["nodes"]
              and "bad1" not in rep["missing_entries"],
              f"missing={rep['missing_entries']}")
        check("5c 读不出的既有条目不摘除（a4 保留——瞬态/损坏 ≠ 文件没了）",
              "a4" in cg.index["nodes"]
              and "a4" not in rep["ghost_entries"]
              and "a4" in rep.get("kept_unreadable", []),
              f"ghost={rep['ghost_entries']} kept={rep.get('kept_unreadable')}")
        check("5d stderr 告警含 T9 边界口径（只告警不改写）",
              "真源损坏" in err and "不改写" in err.replace("（", "("),
              f"stderr={err[:200]!r}")
        with open(reconcile.trace_path(cg), encoding="utf-8") as f:
            trace_txt = f.read()
        check("5e 留痕记录损坏清单（trace 含 problems）",
              "decode_error" in trace_txt
              and "frontmatter_unterminated" in trace_txt,
              f"trace={trace_txt[:200]!r}")

        # ---- [6] 开关：MDCG_RECONCILE=0 关闭 ----
        print("[6] 关闭开关 MDCG_RECONCILE=0（缺省开）")
        open(os.path.join(cg.root, "knowledge", "x9.md"), "w",
             encoding="utf-8").write(
            nodefile.dumps({"id": "x9", "layer": "knowledge"}, "off switch body"))
        os.environ[reconcile.ENV_SWITCH] = "0"
        rep_off, _e = _run(cg)
        check("6a 开关关：skipped=True 不触盘", rep_off.get("skipped") is True,
              f"rep={rep_off}")
        check("6b 开关关：diff 在场也不修（x9 不入索引）",
              "x9" not in cg.index["nodes"], f"nodes={list(cg.index['nodes'])}")
        os.environ.pop(reconcile.ENV_SWITCH, None)
        rep_on, _e = _run(cg)
        check("6c 缺省开：开关还原后 x9 补入收敛",
              rep_on["missing_entries"] == ["x9"]
              and cg.get("x9") is not None,
              f"missing={rep_on['missing_entries']}")

        # ---- [7] dry-run：只 diff 不修 ----
        print("[7] dry-run（apply=False）只报告不改写")
        p1 = os.path.join(cg.root, cg.index["nodes"]["a1"]["path"])
        with open(p1, encoding="utf-8") as f:
            _txt = f.read()                      # 先读后写（"w" 打开即截断）
        with open(p1, "w", encoding="utf-8") as f:
            f.write(_txt.replace("DRIFTED recon body", "DRIFT2 recon body"))
        rep_dry, _e = _run(cg, apply=False)
        check("7a dry-run 检出漂移但不修（applied=False，索引条目仍旧指纹——"
              "get 直读盘面本就见新正文，dry-run 不修的是索引面）",
              rep_dry["hash_drift"] == ["a1"] and rep_dry["applied"] is False
              and cg.index["nodes"]["a1"]["content_hash"]
              != _disk_hash_of(cg, "a1"),
              f"rep={rep_dry}")
        rep_fix, _e = _run(cg)
        check("7b 正式对账收敛漂移（检索面见 DRIFT2）",
              "DRIFT2 recon body" in (cg.get("a1") or {}).get("content", ""),
              f"get={(cg.get('a1') or {}).get('content', '')[:40]!r}")

        # ---- [8] 损坏在场重开：装载不炸（_scan_nodes 守卫）+ 收敛保持 ----
        print("[8] 损坏真源在场重开库（装载路径守卫）")
        root = cg.root
        cg.close()
        cg2 = MdCG(root)
        check("8a 非 UTF-8 坏文件在场，重开装载不炸（_scan_nodes 跳过）",
              isinstance(cg2.index.get("nodes"), dict),
              "重开抛 UnicodeDecodeError 即假绿")
        check("8b 重开后补入条目可见（x1）、摘除不复活（a2）",
              cg2.get("x1") is not None and "a2" not in cg2.index["nodes"],
              f"x1={cg2.get('x1') is not None} a2={'a2' in cg2.index['nodes']}")
        cg2.close()

        # ---- [9] 承接面源断言：mcp_server main 启动序列接线 ----
        print("[9] 承接面源断言")
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "mcp_server.py"), encoding="utf-8") as fh:
            msrc = fh.read()
        _anchor = msrc.find("cg.reconcile_writes()")
        win = msrc[_anchor:msrc.find("_start_sustain", _anchor)]
        check("9a mcp_server.main() 两段式对账之后新增 reconcile_state 接线",
              "cg.reconcile_state()" in win, "main() 缺启动对账 v0 承接")
        check("9b 接线以 try/except 包裹（对账失败不阻塞启动）",
              "except Exception" in win and "不阻塞启动" in win,
              "缺容错承接")
        with open(os.path.join(here, "mdcg.py"), encoding="utf-8") as fh:
            dsrc = fh.read()
        check("9c MdCG.reconcile_state 委托在位（延迟导入 reconcile）",
              "def reconcile_state" in dsrc
              and "reconcile.reconcile_state" in dsrc, "缺委托方法")
        with open(os.path.join(here, "mdcg.py"), encoding="utf-8") as fh:
            check("9d _scan_nodes 捕 (OSError, UnicodeDecodeError)（装载路径 "
                  "T9 守卫）",
                  "except (OSError, UnicodeDecodeError):" in dsrc,
                  "装载路径缺解码守卫")

        # ---- [10] 守卫自检 ----
        print("[10] 守卫自检")
        check(f"10a 断言总数 ≥ {FLOOR}（防探针面失效假绿）",
              PASS + FAIL >= FLOOR, f"total={PASS + FAIL}")
    finally:
        if saved_sw is None:
            os.environ.pop(reconcile.ENV_SWITCH, None)
        else:
            os.environ[reconcile.ENV_SWITCH] = saved_sw
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== reconcile v0 tests: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
