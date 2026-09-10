# -*- coding: utf-8 -*-
"""代码索引 + 回读端到端测试（P26 · 认知图的代码面）。

R1 改造的验收（对照 docs/认知图_索引与工程规范化_计划_v0.1.md）：

  ① 渲染即 CCG：`codeindex.render` 必须产出 CCG 6 行。否则
     `judge_qualification` 第一步的 ccg_completeness 会直接判 BLINDSPOT ——
     改造前本函数只产 `# path::name` / `# sig` 这类非 CCG 行，于是
     **所有代码节点恒定盲区**：存得进、判不了、检索不到。本测试用真实
     `op=read` 检索链路证伪该旧行为（ACCEPT，而非 BLINDSPOT）。
  ② 后缀注册化：`.py` 走精确 AST（precise=True / basis=compiler），
     `.ts/.js` 走弱提取并**诚实降级**（precise=False / basis=other）；
     没有提取器的后缀**显式报错**，不静默降级成 Python 解析。
  ③ 截断与覆盖缺口**不再静默**：返回 truncated/truncated_reason 与
     skipped_suffixes（扫到但没有提取器的后缀），否则「不漏召回」无法审计。
  ④ op=ref 回读：按 frontmatter.code_ref 取回源区间；索引侧与回读侧共用
     同一个 `codeindex.region_hash`，故 hash_match=False 即源已漂移
     （并能通过重跑 index_code 恢复）。
  ⑤ 幂等 + 不清空目录：按 node id 原子覆盖，重跑 ≡ 首跑；`corpus.reset_root`
     默认不删目录（对齐已裁决设计，靠等号断言守门而非 rmtree）。

运行：python -m md_cg.test_p26_refindex
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import codeindex, corpus, nodefile, tokens
from .mdcg import MdCG
from .mcp_server import call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p26")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def ccg_body(subject):
    return (f"# 功能名：{subject}\n"
            "# 生效条件：默认满足\n"
            f"# 子功能：对 {subject} 建立白箱资格判定\n"
            f"# 执行：检索 {subject} 相关条件证据\n"
            "# 验证方式：test\n"
            "# 不适用条件：无需例外\n"
            f"{subject} 的白箱执行正文。")


def find(items, name, path_end=None):
    for it in items:
        if it["name"] == name and (path_end is None or it["path"].endswith(path_end)):
            return it
    return None


ALPHA = ('"""能量计算模块。"""\n'
         'import math\n'
         '\n'
         '\n'
         'def compute_energy(mass, speed):\n'
         '    """计算动能。"""\n'
         '    return mass * speed * speed\n'
         '\n'
         '\n'
         'class Reactor:\n'
         '    """反应堆模型。"""\n'
         '\n'
         '    def ignite(self):\n'
         '        """点火。"""\n'
         '        self.state = "on"\n'
         '\n'
         '    def shutdown(self):\n'
         '        """停堆。"""\n'
         '        self.state = "off"\n')

BETA = ('/** 几何工具 */\n'
        'export function areaOfCircle(r) {\n'
        '  return Math.PI * r * r;\n'
        '}\n'
        '\n'
        'const helperScale = 1;\n'
        '\n'
        'export class Shape {\n'
        '}\n')

GAMMA = ('/** 采样工具 */\n'
         'export function sampleRate(freq) {\n'
         '  return freq * 2;\n'
         '}\n')

BADPY = 'def broken(:\n    pass\n'


def index_read(cg, code_dir, **extra):
    args = {"op": "index_code", "path": code_dir}
    args.update(extra)
    return call_tool(cg, "cg", args)


def ref_read(cg, **args):
    a = {"op": "ref"}
    a.update(args)
    return call_tool(cg, "cg", a)


def main():
    print("=" * 68)
    print("md 认知图 P26 验收 · 代码索引 + 回读（index_code / op=ref）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_refidx_")
    code_dir = os.path.join(tmp, "pkg")
    bad_dir = os.path.join(tmp, "broken")
    os.makedirs(code_dir)
    os.makedirs(bad_dir)
    with open(os.path.join(code_dir, "alpha.py"), "w", encoding="utf-8") as f:
        f.write(ALPHA)
    with open(os.path.join(code_dir, "beta.js"), "w", encoding="utf-8") as f:
        f.write(BETA)
    with open(os.path.join(code_dir, "gamma.ts"), "w", encoding="utf-8") as f:
        f.write(GAMMA)
    with open(os.path.join(code_dir, "data.txt"), "w", encoding="utf-8") as f:
        f.write("这不是代码")
    with open(os.path.join(bad_dir, "bad.py"), "w", encoding="utf-8") as f:
        f.write(BADPY)

    corpus.reset_root(ROOT)
    cg = MdCG(ROOT)
    alpha_path = os.path.join(code_dir, "alpha.py")

    try:
        # ===================================================== ① 前置：注册表
        print("\n【1】后缀注册表 / op 注册")
        check("tokens.ALL_OPS 收录 index_code 与 ref",
              "index_code" in tokens.ALL_OPS and "ref" in tokens.ALL_OPS)
        check("EXTRACTORS 覆盖常用代码后缀",
              all(s in codeindex.EXTRACTORS
                  for s in (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs")),
              ",".join(codeindex.SUFFIX))
        try:
            codeindex.extract("x = 1", "foo.xyz")
            unknown_raised = False
        except ValueError as exc:
            unknown_raised = "无提取器" in str(exc)
        check("无提取器后缀显式报错（不静默降级成 Python 解析）", unknown_raised)
        try:
            Principal(role="guest", ops_allow=("read",), theory_ok=True).require_op("ref")
            ref_denied = False
        except AccessDenied:
            ref_denied = True
        except Exception:  # noqa: BLE001
            ref_denied = False
        check("op=ref 受权限层约束（ops_allow 未含 ref 即拒）", ref_denied)

        # ===================================================== ② 索引 + 统计
        print("\n【2】index_code：索引结果与覆盖缺口")
        mt_before = {f: os.path.getmtime(os.path.join(code_dir, f))
                     for f in os.listdir(code_dir)}
        items, errors, stats = codeindex.index_dir(code_dir)
        check("直接抽取无错误", errors == [], str(errors))
        check("stats.files 只计命中后缀的文件", stats["files"] == 3,
              f"files={stats['files']}")
        check("skipped_suffixes 报出无提取器后缀（可审计）",
              ".txt" in stats["skipped_suffixes"], str(stats["skipped_suffixes"]))
        check("未触上限 → truncated=False", stats["truncated"] is False)

        out = index_read(cg, code_dir)
        check("op=index_code ok", out.get("ok"), str(out)[:120])
        check("indexed == 直接抽取条目数（无丢项）",
              out.get("indexed") == len(items),
              f"{out.get('indexed')} == {len(items)}")
        check("error_count == 0", out.get("error_count") == 0)
        mt_after = {f: os.path.getmtime(os.path.join(code_dir, f))
                    for f in os.listdir(code_dir)}
        check("只读契约：索引一轮后源文件 mtime 全不变", mt_before == mt_after)
        py_item = find(items, "compute_energy")
        check("条目带 lang/precise/hash", bool(py_item) and
              py_item.get("lang") == "py" and py_item.get("precise") is True
              and bool(py_item.get("hash")), str(py_item and py_item.get("hash")))

        # ===================================================== ③ 提取器分派
        print("\n【3】提取器分派：精确 vs 弱提取（诚实降级）")
        check("Python → AST 精确（basis=compiler）",
              py_item["precise"] is True and py_item["basis"] == "compiler")
        js_item = find(items, "areaOfCircle")
        ts_item = find(items, "sampleRate")
        check("JS → 弱提取（precise=False/basis=other）",
              js_item and js_item["precise"] is False and js_item["basis"] == "other")
        check("TS → 弱提取（precise=False/basis=other）",
              ts_item and ts_item["precise"] is False and ts_item["basis"] == "other")
        ignite = find(items, "ignite")
        check("类方法带父类归属（parent=Reactor）",
              ignite and ignite["parent"] == "Reactor", str(ignite and ignite["parent"]))

        # ===================================================== ④ 渲染即 CCG
        print("\n【4】render 产出 CCG（R1 核心修复）")
        rendered = codeindex.render(py_item)
        cpl = nodefile.ccg_completeness(rendered)
        check("render 的 CCG 5 要素齐全（complete=True）",
              cpl["complete"] is True, str(cpl["required_present"]))
        check("render 6 行全在（all_present=True）", cpl["all_present"] is True)
        check("render 不复制实现正文",
              "return mass * speed" not in rendered)

        # ===================================================== ⑤ 检索 + 资格
        print("\n【5】检索资格判定（旧行为：代码节点恒定 BLINDSPOT）")
        cg.flush()
        py_nid = codeindex.node_id(py_item)
        read = call_tool(cg, "cg", {"op": "read", "query": "compute_energy", "k": 10})
        hits = [r for r in read.get("results", []) if r["node"]["id"] == py_nid]
        check("代码节点可被检索到（存得进→查得到）", bool(hits),
              f"hits={len(hits)}")
        check("CCG 完整 + 基底已声明 → ACCEPT（不再恒定 BLINDSPOT）",
              bool(hits) and hits[0]["state"] == "ACCEPT",
              str(hits[0]["state"] if hits else None))

        js_nid = codeindex.node_id(js_item)
        read_js = call_tool(cg, "cg", {"op": "read", "query": "areaOfCircle", "k": 10})
        js_hits = [r for r in read_js.get("results", []) if r["node"]["id"] == js_nid]
        check("弱提取节点同样可判（state=ACCEPT）",
              bool(js_hits) and js_hits[0]["state"] == "ACCEPT",
              str(js_hits[0]["state"] if js_hits else None))

        # ===================================================== ⑥ code_ref
        print("\n【6】frontmatter.code_ref（指回源文件，不复制代码）")
        fm = (cg.get(py_nid) or {}).get("frontmatter") or {}
        cre = fm.get("code_ref") or {}
        check("code_ref 字段齐全",
              all(k in cre for k in ("path", "name", "kind", "lineno", "end",
                                     "lang", "precise", "hash", "root")),
              str(sorted(cre)))
        check("code_ref.path 是相对根路径",
              cre.get("path") == "alpha.py", str(cre.get("path")))
        check("code_ref.root 与索引根一致",
              os.path.normcase(cre.get("root") or "") ==
              os.path.normcase(os.path.abspath(code_dir)), str(cre.get("root")))
        check("verification_basis 落 frontmatter（compiler）",
              fm.get("verification_basis") == "compiler",
              str(fm.get("verification_basis")))
        check("tags 标记为代码节点",
              "code" in (fm.get("tags") or []), str(fm.get("tags")))

        # ===================================================== ⑦ op=ref + 漂移
        print("\n【7】op=ref 回读 + 漂移检测")
        rr = ref_read(cg, node_id=py_nid)
        check("ref 回读成功", rr.get("ok"), str(rr)[:120])
        check("回读到被索引的函数区间",
              "def compute_energy" in (rr.get("text") or "")
              and "return mass * speed" in (rr.get("text") or ""))
        check("索引侧与回读侧哈希一致（hash_match=True）",
              rr.get("hash_match") is True
              and rr.get("hash") == cre.get("hash"), str(rr.get("hash")))
        check("未漂移 → stale=False", rr.get("stale") is False)
        check("ref 转达 precise 语义（Python 精确）",
              rr.get("precise") is True)

        # 改源（保持行数不变，只换实现）→ 同一区间哈希应变化 → 漂移可检出
        with open(alpha_path, "w", encoding="utf-8") as f:
            f.write(ALPHA.replace("return mass * speed * speed",
                                  "return mass * speed * speed / 2"))
        rr2 = ref_read(cg, node_id=py_nid)
        check("源被改动 → hash_match=False（漂移可检出）",
              rr2.get("hash_match") is False, str(rr2.get("hash")))
        check("漂移 → stale=True", rr2.get("stale") is True)

        # 重跑 index_code 重建 → 漂移消除
        index_read(cg, code_dir)
        rr3 = ref_read(cg, node_id=py_nid)
        check("重跑 index_code → 漂移消除（hash_match 恢复 True）",
              rr3.get("hash_match") is True, str(rr3.get("hash")))

        # ===================================================== ⑧ ref 边界
        print("\n【8】op=ref 边界（缺 root / 无 code_ref / 节点不存在）")
        no_root = ref_read(cg, ref={"path": "alpha.py", "lineno": 1, "end": 1})
        check("ref 无 root → 明确报错（而非静默读错位置）",
              no_root.get("ok") is False and "root" in (no_root.get("error") or ""),
              str(no_root.get("error"))[:80])
        cg.add("p26_plain", ccg_body("普通知识卡片"))
        cg.flush()
        no_ref = ref_read(cg, node_id="p26_plain")
        check("非代码节点 → 报无 code_ref",
              no_ref.get("ok") is False and "code_ref" in (no_ref.get("error") or ""),
              str(no_ref.get("error"))[:80])
        missing = ref_read(cg, node_id="p26_absent")
        check("节点不存在 → 明确报错",
              missing.get("ok") is False and "不存在" in (missing.get("error") or ""),
              str(missing.get("error"))[:80])

        # ===================================================== ⑨ 截断不静默
        print("\n【9】截断必须显式上报（不静默不完整）")
        out_tr = index_read(cg, code_dir, max_files=1)
        check("触上限 → truncated=True", out_tr.get("truncated") is True,
              str(out_tr.get("truncated_reason")))
        check("truncated_reason 可归因（max_files）",
              "max_files" in (out_tr.get("truncated_reason") or ""),
              str(out_tr.get("truncated_reason")))
        check("截断时 note 明确警告不完整",
              "截断" in (out_tr.get("note") or ""), (out_tr.get("note") or "")[:60])

        # ===================================================== ⑩ 错误上报
        print("\n【10】语法错误文件进 errors（不吞错）")
        out_bad = index_read(cg, bad_dir)
        check("坏文件 error_count>=1", out_bad.get("error_count", 0) >= 1,
              str(out_bad.get("errors"))[:100])
        check("errors 指向具体文件",
              any("bad.py" in e for e in (out_bad.get("errors") or [])),
              str(out_bad.get("errors"))[:100])

        # ===================================================== ⑪ 幂等 + 不清空
        print("\n【11】幂等（重跑 ≡ 首跑）与 reset_root 不删目录")
        n1 = sum(1 for e in cg.index["nodes"].values() if e["layer"] == "knowledge")
        index_read(cg, code_dir)
        n2 = sum(1 for e in cg.index["nodes"].values() if e["layer"] == "knowledge")
        check("重跑 index_code：knowledge 节点数不变（原子覆盖）",
              n1 == n2, f"{n1} == {n2}")
        check("代码节点数 == 直接抽取条目数",
              n1 - 1 == len(items), f"{n1 - 1} - 1(plain) == {len(items)}")
        before = sum(len(fs) for _d, _s, fs in os.walk(ROOT))
        corpus.reset_root(ROOT)
        after = sum(len(fs) for _d, _s, fs in os.walk(ROOT))
        check("reset_root 默认不清空目录（重跑不变性靠等号断言守门）",
              before == after and before > 0, f"{before} == {after}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
