# -*- coding: utf-8 -*-
"""review_reconcile · 条件卡 ↔ 真源 `doc_ref` 对账器（计划 §3.5 fence 真源绑定）

背景：`md_cg/docindex.py` 的「往返列」把条件卡钉在真源（`root` + `path`）+ 定位
（`anchor` / `heading_path`）+ 行位（`lineno` / `end`）+ 校验（`hash`）上。列有了，
**还得有人盯着它**：真源被重排、章节被改名、文件被删，卡片不会自己知道。本脚本
就是那个对账的人。

三个子命令（**默认只读**；只有 `rebuild --apply` 会写库）：

  check              正向：卡片 → 真源。逐条校验列形状 → 探真源存在性与区间哈希
                     → 按稳定键回真源重算行位。分类报告：
                       malformed       列形状坏（缺列 / 类型错 / 行位越界）
                       unresolved      卡片未记 root，无法定位
                       dangling        真源文件不在
                       missing_section 文件在，但该章节（键 `path#heading_path`）已消失
                       drift           键在，行位或内容变了 → 需要 rebuild
                       errors          读取/抽取异常
  at <path:line>     反向：真源某一行 → 绑定它的卡片（`docindex.locate` 取最内层）。
                     这是「任一条件卡可定位真源精确行」的反向可验证面。
  rebuild            真源重排后重建行位。**不另写一套切分**——委托平台唯一实现
                     `refindex.rebuild`（按 ref 记录的原 layer 逐节点重建）；
                     默认 dry-run 只报告，`--apply` 才落盘。

设计纪律（与 docindex 的列定义同源，不在此处重新发明）：
  · **键不含行位**：`docindex.binding_key = path#heading_path`。重排只动行位、不动键，
    故重建是「同 id 覆写」而非产生新代节点——这正是行位可以安全从键里剔出去的理由。
  · **不猜不补**：缺列、类型错、字符集坏一律如实报告，不补默认值、不静默跳过。
  · **root 必须显式**（`--root` 或 `MDCG_ROOT`）：猜错会读/写到另一个库。

用法：
  set MDCG_ROOT=<认知图根>
  python scripts/review_reconcile.py check  --docs-root "d:/.../dsh-memory"
  python scripts/review_reconcile.py at "docs/mdcg/xxx.md:120" --docs-root "d:/.../dsh-memory"
  python scripts/review_reconcile.py rebuild --docs-root "d:/.../dsh-memory" --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from md_cg import docindex, refindex            # noqa: E402
from md_cg.mdcos import MdCGSecure              # noqa: E402
from md_cg.security import Principal            # noqa: E402

MAX_NODES = 20000     # check 的节点扫描上限（超出即 truncated，不静默）
MAX_FILES = 500
MAX_ITEMS = 2000

#: check 的分类桶（顺序固定：报告与测试断言都按它取）
BUCKETS = ("malformed", "unresolved", "dangling", "missing_section", "drift", "errors")


# 生效条件：p 为假值时返回当前目录的归一绝对路径；否则 os.path.normcase(os.path.abspath(str(p)))——与 refindex._norm_root 同一判据（大小写/分隔符差异不得影响「同一大域」判定），此处内联以免脚本依赖库内私有名。
def _norm_root(p):
    return os.path.normcase(os.path.abspath(str(p or "")))


# 生效条件：args.root（或 else 读取 MDCG_ROOT 环境变量）为真值且经 os.path.isdir 判定为目录时返回该 root；两者皆假时 sys.exit 报错；为真值但不是目录时 sys.exit 报错——缺根即退出，不回落到当前目录。
def _root(args):
    root = getattr(args, "root", None) or os.environ.get("MDCG_ROOT", "")
    if not root:
        sys.exit("错误：未指定存储根（--root 或环境变量 MDCG_ROOT）。\n"
                 "root 必须与被对账的认知图一致——猜错会对到另一个空库。")
    if not os.path.isdir(root):
        sys.exit("错误：root 不存在：%s" % root)
    return root


# 生效条件：以写死权限的 Principal(actor="review-reconcile", role="designer", auth_mode="local-cli") 构造 MdCGSecure；write 为真时 can_write 与 can_admin 均为 True（重建是库维护通道，须落盘），为假时两者均 False（check / at 严格只读）。
def _cg(args, write=False):
    p = Principal(actor="review-reconcile", clearance="secret",
                  can_write=bool(write), can_admin=bool(write),
                  role="designer", auth_mode="local-cli")
    return MdCGSecure(_root(args), principal=p)


# 生效条件：读取 fp（UTF-8，errors='replace'）后交 docindex.extract(source, path=rel)，返回 (items, "")；open 抛 OSError 时返回 (None, "读取失败：…")；extract 抛 ValueError 时返回 (None, "抽取失败：…")；恒不抛。
def _extract(fp, rel):
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError as exc:
        return None, "读取失败：%s" % exc
    try:
        return docindex.extract(src, path=rel), ""
    except ValueError as exc:
        return None, "抽取失败：%s" % exc


# 生效条件：ref 的 root/path 拼出源文件后经 _extract（结果按 fp 缓存进 cache），再以 docindex.binding_key(ref) 在条目里找同键项；命中返回 (item, "")；文件读取失败返回 (None, 错误文本)；文件在但同键条目不存在返回 (None, "")——调用方须区分「读不了」与「章节没了」，故两种情况错误文本不同（"" 表示正常未命中）。
def _recompute(ref, cache):
    rel = ref.get("path") or ""
    fp = os.path.join(ref.get("root") or "", rel)
    if fp not in cache:
        cache[fp] = _extract(fp, rel)
    items, err = cache[fp]
    if err:
        return None, err
    key = docindex.binding_key(ref)
    for it in (items or []):
        if docindex.binding_key(it) == key:
            return it, ""
    return None, ""


# 生效条件：cg.index["nodes"] 非空时逐 id（仅 exhaustive 为假时按 tags 含 "doc" 预筛）经 cg.get 取节点，kind == "doc_ref" 且 ref 非空时收入结果，doc_root 非 None 时再要求 ref["root"] 与 doc_root 归一同根；nodes 为空时返回空列表；节点数超过 MAX_NODES 时结果对象附 truncated=True。
def _cards(cg, exhaustive=False, doc_root=None):
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    out, truncated = [], len(nodes) > MAX_NODES
    for nid in sorted(nodes)[:MAX_NODES]:
        meta = nodes.get(nid) or {}
        if not exhaustive and "doc" not in (meta.get("tags") or []):
            continue
        try:
            node = cg.get(nid)
        except Exception:                              # 对账不抛：坏节点如实跳过
            continue
        kind, ref = refindex.ref_of(node)
        if kind != "doc_ref" or not ref:
            continue
        if doc_root is not None and _norm_root(ref.get("root")) != _norm_root(doc_root):
            continue
        out.append((nid, ref, docindex.binding_of(node)))
    return out, truncated


# 生效条件：遍历 _cards 结果，逐卡先 validate_binding（不 ok 记入 malformed 并 continue），再 probe_ref 按 status 分派 dangling/unresolved/errors；status 为 ok/stale 时回真源 _recompute 取当前条目，取不到且无错误记 missing_section，取到后经 docindex.binding_of({"doc_ref": {**item, "root": ref["root"]}}) 重算列并用 binding_drift 比对，有差异记入 drift 并附 new_lineno/new_end/hash_match；返回 {ok, root, docs_root, cards, truncated, 六桶, counts, hint}，ok 为六桶全空。
def _check(cg, args):
    doc_root = getattr(args, "docs_root", None) or None
    cards, truncated = _cards(cg, exhaustive=getattr(args, "all", False),
                              doc_root=doc_root)
    buckets = {k: [] for k in BUCKETS}
    cache = {}
    for nid, ref, binding in cards:
        base = {"node_id": nid, "path": ref.get("path"),
                "lineno": ref.get("lineno"), "end": ref.get("end")}
        v = docindex.validate_binding(binding)
        if not v["ok"]:
            buckets["malformed"].append({**base, "issues": v["issues"]})
            continue
        probe = refindex.probe_ref(ref)
        st = probe.get("status")
        if st == "dangling":
            buckets["dangling"].append({**base, "error": probe.get("error", "")})
            continue
        if st == "unresolved":
            buckets["unresolved"].append({**base, "error": probe.get("error", "")})
            continue
        if st == "error":
            buckets["errors"].append({**base, "error": probe.get("error", "")})
            continue
        item, err = _recompute(ref, cache)
        if err:
            buckets["errors"].append({**base, "error": err})
            continue
        if item is None:
            buckets["missing_section"].append({**base,
                                               "key": docindex.binding_key(ref)})
            continue
        fresh = docindex.binding_of({"doc_ref": {**item,
                                                "root": ref.get("root") or ""}})
        drift = docindex.binding_drift(binding, fresh)
        if drift:
            buckets["drift"].append({**base, "drift": drift,
                                     "new_lineno": fresh.get("lineno"),
                                     "new_end": fresh.get("end"),
                                     "hash_match": st == "ok"})
    ok = not any(buckets.values())
    out = {"ok": ok, "mode": "check", "root": _root(args), "docs_root": doc_root,
           "cards": len(cards), "truncated": truncated,
           "counts": {k: len(v) for k, v in buckets.items()}, **buckets}
    if buckets["drift"]:
        out["hint"] = ("行位/内容已漂移：跑 `rebuild --apply` 重建（同 id 覆写，"
                       "键不含行位故不产生新代节点）")
    if buckets["missing_section"]:
        out["hint2"] = ("章节消失：键 path#heading_path 在真源已不存在——"
                        "改名/删除需人工裁决（reconciler 不猜新键）")
    return out


# 生效条件：spec 以 rpartition(":") 拆成 path 与 lineno（lineno 不可转 int 或 path 为空时返回含 ok=False/error 的结果）；fp 为绝对路径时原样使用、否则以 docs_root 拼接；rel 为 fp 相对 docs_root 的 "/" 形式路径；经 _extract 抽取后 locate(items, lineno) 取覆盖该行的最内层条目，无覆盖返回 ok=False；命中后以 binding_key 在全部 doc 卡（不过滤 docs_root）中找同键卡，逐卡给出 in_sync（stored 行位+hash 与当前条目全等）；返回 {ok, at, rel, lineno, section, key, cards, in_sync_count}。
def _at(cg, args):
    spec = args.at
    path, sep, ln = spec.rpartition(":")
    if not sep or not path:
        return {"ok": False, "mode": "at",
                "error": "定位串应为 <path>:<line>，实为 %r" % spec}
    try:
        lineno = int(ln)
    except (TypeError, ValueError):
        return {"ok": False, "mode": "at", "error": "行号不是整数：%r" % ln}

    docs_root = (args.docs_root or _HERE)
    fp = path if os.path.isabs(path) else os.path.join(docs_root, path)
    try:
        rel = os.path.relpath(fp, docs_root).replace("\\", "/")
    except ValueError:                                  # 跨盘符：退回原样
        rel = path.replace("\\", "/")
    if rel.startswith("../"):
        rel = path.replace("\\", "/")

    items, err = _extract(fp, rel)
    if err:
        return {"ok": False, "mode": "at", "at": spec, "rel": rel, "error": err}
    item = docindex.locate(items, lineno)
    if item is None:
        return {"ok": False, "mode": "at", "at": spec, "rel": rel, "lineno": lineno,
                "error": "该行不属于任何已索引章节（落在 frontmatter / 围栏 / "
                         "小节合并区间之外）"}
    key = docindex.binding_key(item)
    cards, _tr = _cards(cg, exhaustive=False, doc_root=None)
    hits = []
    for nid, ref, binding in cards:
        if docindex.binding_key(ref) != key:
            continue
        in_sync = (binding.get("lineno") == item["lineno"]
                   and binding.get("end") == item["end"]
                   and binding.get("hash") == item["hash"])
        hits.append({"node_id": nid, "path": binding.get("path"),
                     "stored": [binding.get("lineno"), binding.get("end")],
                     "in_sync": in_sync})
    return {"ok": True, "mode": "at", "at": spec, "rel": rel, "lineno": lineno,
            "section": {"heading_path": item["heading_path"],
                        "lineno": item["lineno"], "end": item["end"]},
            "key": key, "cards": hits, "in_sync_count":
                sum(1 for h in hits if h["in_sync"]),
            "bound": bool(hits)}


# 生效条件：docs_root 缺省回落 _HERE；未传 --apply 时只跑 _check 并返回 {ok:True, dry_run:True, before:{counts…}, hint}；传 --apply 时在库内 ref 根中筛出与 docs_root 归一同根者（无匹配则返回 ok=False 并拒绝重建——fail-closed，不拿整个库当目标），再调 refindex.rebuild(only_roots=匹配集, ledger=Ledger(cg.root)) 落盘并 cg.close()，随后复跑 _check 返回 before/after 与 rebuild 产物；ok 取 after.ok。
def _rebuild(cg, args):
    docs_root = args.docs_root or _HERE
    before = _check(cg, args)
    before_ok = before["ok"]
    if not getattr(args, "apply", False):
        return {"ok": True, "mode": "rebuild", "dry_run": True,
                "docs_root": docs_root, "before": before["counts"],
                "cards": before["cards"],
                "hint": "只读预演：加 --apply 才落盘重建"}
    roots = sorted({(ref.get("root") or "") for _n, ref, _b
                    in _cards(cg, exhaustive=True)[0]})
    only = [r for r in roots if _norm_root(r) == _norm_root(docs_root)]
    if not only:
        return {"ok": False, "mode": "rebuild", "dry_run": False,
                "docs_root": docs_root, "before": before["counts"],
                "error": "库内没有与 docs-root 归一同根的 doc_ref 根，拒绝重建"
                         "（fail-closed）；请用 --docs-root 指向真源根"}
    out = refindex.rebuild(cg, ledger=refindex.Ledger(_root(args)),
                           only_roots=only, max_files=MAX_FILES,
                           max_items=MAX_ITEMS)
    cg.close()                                          # 显式收尾：落盘派生索引
    after = _check(cg, args)
    return {"ok": bool(after["ok"]), "mode": "rebuild", "dry_run": False,
            "docs_root": docs_root, "roots": only, "rebuild": out,
            "before": before["counts"], "before_ok": before_ok,
            "after": after["counts"]}


# 生效条件：_root 就绪后按 args.cmd 分派——"check" 调 _check、"at" 调 _at、"rebuild" 调 _rebuild；三者结果经 args.json 为真时以 json.dumps(ensure_ascii=False, indent=1) 整份打印，否则按人读格式打印汇总；返回 0 仅当结果的 ok 为真，否则返回 1；finally 中执行 cg.close()。
def _execute(cg, args):
    if args.cmd == "check":
        out = _check(cg, args)
    elif args.cmd == "at":
        out = _at(cg, args)
    else:
        out = _rebuild(cg, args)

    if getattr(args, "json", False):
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        _report(out, args)
    return 0 if out.get("ok") else 1


# 生效条件：按 out["mode"] 分派打印——"check" 打卡片数/六桶计数/漂移与悬空前 5 条/提示与判定；"at" 打章节、键、命中卡与其 in_sync（无命中卡片时明示「该章节未建卡」）；其余（含 mode 缺失）按 rebuild 形态打 dry_run、before→after 计数、roots、rebuild.indexed/errors；恒不抛（mode 未识别时退化为 rebuild 形态，不用 KeyError 掩盖真实输出）。
def _report(out, args):
    mode = out.get("mode")
    if mode == "check":
        print("对账：卡片 %d 条 · root=%s · docs_root=%s%s" % (
            out["cards"], out.get("root"), out.get("docs_root") or "(全部)",
            " · 已截断" if out.get("truncated") else ""))
        for k in BUCKETS:
            n = out["counts"].get(k, 0)
            print("  %-16s %d" % (k, n))
        for k in ("drift", "missing_section", "dangling", "malformed", "errors"):
            for row in out[k][:5]:
                print("    · [%s] %s L%s-%s %s" % (
                    k, row.get("node_id"), row.get("lineno"), row.get("end"),
                    row.get("drift") or row.get("issues") or row.get("error")
                    or row.get("key") or ""))
        for hk in ("hint", "hint2"):
            if out.get(hk):
                print("  %s" % out[hk])
        print("  判定：%s" % ("一致" if out["ok"] else "不一致"))
        return
    if mode == "at":
        s = out["section"]
        print("真源 %s（L%s）→ 章节 %s [L%s-%s]" % (
            out["rel"], out["lineno"], "/".join(s["heading_path"]),
            s["lineno"], s["end"]))
        print("  键：%s" % out["key"])
        if not out["cards"]:
            print("  绑定卡片：0 条（该章节未建卡）")
        for h in out["cards"]:
            print("    · %s stored=L%s-%s in_sync=%s" % (
                h["node_id"], h["stored"][0], h["stored"][1], h["in_sync"]))
        return
    print("重建：dry_run=%s · docs_root=%s" % (out.get("dry_run"), out.get("docs_root")))
    if out.get("error"):
        print("  错误：%s" % out["error"])
        return
    print("  before：%s" % json.dumps(out.get("before"), ensure_ascii=False))
    if not out.get("dry_run"):
        rb = out.get("rebuild") or {}
        print("  roots=%s indexed=%s errors=%s truncated=%s" % (
            out.get("roots"), rb.get("indexed"), len(rb.get("errors") or []),
            rb.get("truncated")))
        print("  after：%s" % json.dumps(out.get("after"), ensure_ascii=False))
    if out.get("hint"):
        print("  %s" % out["hint"])


# 生效条件：argv 为 None（默认）时由 argparse 解析 sys.argv、否则解析传入的 argv（子命令 dest="cmd" 为 required；common 父解析器提供 --root/--docs-root/--all/--json，at 另需定位串 at，rebuild 另带 --apply）；解析成功后构造 cg=_cg(args, write=cmd=="rebuild" and --apply 为真) 并返回 _execute(cg, args)，finally 中执行 cg.close()。
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="条件卡 ↔ 真源 doc_ref 对账器（默认只读）")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="存储根目录（默认环境变量 MDCG_ROOT）")
    common.add_argument("--docs-root", dest="docs_root",
                        help="真源文档根（check/rebuild 用于限域；at 用于拼路径）")
    common.add_argument("--all", action="store_true",
                        help="check 穷举全部节点（默认只扫 tags 含 doc 的索引节点）")
    common.add_argument("--json", action="store_true", help="打印原始 JSON 结果")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="正向对账：卡片 → 真源", parents=[common])
    s = sub.add_parser("at", help="反向定位：真源某行 → 卡片", parents=[common])
    s.add_argument("at", help="定位串 <path>:<line>，如 docs/a.md:120")
    s = sub.add_parser("rebuild", help="真源重排后重建行位", parents=[common])
    s.add_argument("--apply", action="store_true",
                   help="落盘重建（缺省只读预演）")
    args = ap.parse_args(argv)

    cg = _cg(args, write=(args.cmd == "rebuild" and getattr(args, "apply", False)))
    try:
        return _execute(cg, args)
    finally:
        cg.close()


if __name__ == "__main__":
    sys.exit(main())
