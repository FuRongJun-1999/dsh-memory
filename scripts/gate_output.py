# -*- coding: utf-8 -*-
"""输出单元门禁 gate_output.py（工作纪律第 19 条 / issue #663 之三）。

判据（fail-closed）：
  O1 交付物已登记 echo 页（docs/output/echo_registry.json 里每条都在，文件存在）
  O2 echo 页携带版本锚三元（理论 / 架构 / 本投影），且与登记表一致
  O3 echo 页三问齐全、正文 <=200 字、第二问有可指认判据（复用 echo_page.check）
  O4 本季（90 天内）至少一份 D_out 读数存在（docs/output/dout/*.json）

自证（--selftest）：四条变异必须各自变红
  删 echo 页 / 改坏版本锚 / 第二问换形容词 / 清空 D_out 读数

用法：
  python scripts/gate_output.py [--repo <仓根>] [--json]
  python scripts/gate_output.py --selftest
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import echo_page  # noqa: E402

REGISTRY = "docs/output/echo_registry.json"
DOUT_DIR = "docs/output/dout"
SEASON_DAYS = 90


def load_registry(repo):
    p = os.path.join(repo, REGISTRY)
    if not os.path.isfile(p):
        return None, "登记表不存在: " + REGISTRY
    try:
        return json.load(io.open(p, encoding="utf-8")), None
    except Exception as exc:                       # noqa: BLE001
        return None, "登记表解析失败: %s" % exc


def check_anchors_against_record(txt, rec):
    m = echo_page.ANCHOR_RE.search(txt)
    if not m:
        return False, "缺版本锚三元"
    want = rec.get("anchors") or {}
    got = {"理论": m.group(1), "架构": m.group(2), "本投影": m.group(3)}
    for k in ("理论", "架构", "本投影"):
        if not want.get(k):
            return False, "登记表缺 %s 版本锚" % k
        if got[k] != str(want[k]):
            return False, "版本锚不一致：%s 页内=%s 登记=%s" % (k, got[k], want[k])
    return True, "版本锚三元一致"


def latest_dout(repo):
    d = os.path.join(repo, DOUT_DIR)
    if not os.path.isdir(d):
        return None
    best, best_mt = None, 0.0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            data = json.load(io.open(p, encoding="utf-8"))
        except Exception:                          # noqa: BLE001
            continue
        mt = os.path.getmtime(p)
        if mt > best_mt:
            best, best_mt = (p, data), mt
    return best


def run(repo):
    res = {"ok": True, "checks": [], "problems": []}

    def add(cid, ok, detail):
        res["checks"].append({"id": cid, "ok": ok, "detail": detail})
        if not ok:
            res["ok"] = False
            res["problems"].append("%s %s" % (cid, detail))

    reg, err = load_registry(repo)
    if reg is None:
        add("O1", False, err)
        return res
    items = reg.get("deliverables") or []
    if not items:
        add("O1", False, "登记表为空：至少一条交付物")
        return res

    for it in items:
        name = it.get("id") or "?"
        echo_rel = it.get("echo")
        src_rel = it.get("source")
        ok = bool(echo_rel) and bool(src_rel)
        if not ok:
            add("O1", False, "%s 缺 echo/source 字段" % name)
            continue
        ep = os.path.join(repo, echo_rel.replace("/", os.sep))
        sp = os.path.join(repo, src_rel.replace("/", os.sep))
        if not os.path.isfile(ep):
            add("O1", False, "%s echo 页不存在: %s" % (name, echo_rel))
            continue
        if not os.path.isfile(sp):
            add("O1", False, "%s 真源不存在: %s" % (name, src_rel))
            continue
        add("O1", True, "%s echo=%s" % (name, echo_rel))

        txt = io.open(ep, encoding="utf-8").read()
        ok2, why = check_anchors_against_record(txt, it)
        add("O2", ok2, "%s %s" % (name, why))

        chk = echo_page.check(txt)
        add("O3", chk["ok"], "%s 正文 %d/%d 字，三问 %d/3%s"
            % (name, chk["chars"], chk["max_chars"], len(chk["sections"]),
               ("；" + "；".join(chk["problems"])) if chk["problems"] else ""))

    latest = latest_dout(repo)
    if latest is None:
        add("O4", False, "无 D_out 读数（%s/*.json）" % DOUT_DIR)
    else:
        p, data = latest
        age = (time.time() - os.path.getmtime(p)) / 86400.0
        fresh = age <= SEASON_DAYS
        add("O4", fresh, "最近读数 %s（%.1f 天前，D_out=%s%s）"
            % (os.path.basename(p), age, data.get("D_out"),
               "，proxy" if data.get("proxy") else ""))
    return res


def selftest(repo):
    """四条变异各自必须变红。"""
    base = tempfile.mkdtemp(prefix="gateout_")
    cases = []
    plan = [
        ("O1", "删 echo 页", lambda root: os.remove(os.path.join(root, "docs/output/echo/ui-minimal.md"))),
        ("O2", "改坏版本锚", None),
        ("O3", "第二问换形容词", None),
        ("O4", "清空 D_out 读数", lambda root: [os.remove(os.path.join(root, "docs/output/dout", n))
                                                for n in os.listdir(os.path.join(root, "docs/output/dout"))
                                                if n.endswith(".json")]),
    ]
    for cid, label, fn in plan:
        root = os.path.join(base, cid.lower())
        shutil.copytree(os.path.join(repo, "docs", "output"), os.path.join(root, "docs", "output"))
        # 把真源也镜像进去：否则 O1（真源不存在）会先红，掩盖 O2/O3 的目标变异
        reg0, _ = load_registry(repo)
        for it in (reg0 or {}).get("deliverables") or []:
            rel = it.get("source")
            if not rel:
                continue
            srcp = os.path.join(repo, rel.replace("/", os.sep))
            dstp = os.path.join(root, rel.replace("/", os.sep))
            if os.path.isfile(srcp):
                os.makedirs(os.path.dirname(dstp), exist_ok=True)
                shutil.copyfile(srcp, dstp)
        if fn:
            fn(root)
        else:
            ep = os.path.join(root, "docs/output/echo/ui-minimal.md")
            txt = io.open(ep, encoding="utf-8").read()
            if cid == "O2":
                txt = re.sub(r"本投影\s*=\s*\S+", "本投影=v0.0.0-bad", txt)
            else:
                txt = re.sub(r"(##\s*2[^\n]*\n)([\s\S]*?)(\n##\s*3)", r"\1它很稳定、很强大\n\3", txt)
            io.open(ep, "w", encoding="utf-8", newline="").write(txt)
        r = run(root)
        failed = [c["id"] for c in r["checks"] if not c["ok"]]
        cases.append({"mutation": label, "expect": cid, "failed": failed,
                      "ok": cid in failed})
        if not (cid in failed):
            print("  [FAIL] 变异「%s」未让 %s 变红（实际红：%s）" % (label, cid, failed or "无"))
    ok = all(c["ok"] for c in cases)
    for c in cases:
        print("  [%s] %s → 期望红 %s，实际红 %s"
              % ("OK" if c["ok"] else "FAIL", c["mutation"], c["expect"], c["failed"] or "无"))
    print("selftest: %d/%d 条变异被捕获" % (sum(1 for c in cases if c["ok"]), len(cases)))
    shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="输出单元门禁（第 19 条）")
    ap.add_argument("--repo", default=os.path.dirname(HERE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    if args.selftest:
        return selftest(repo)
    res = run(repo)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for c in res["checks"]:
            print("[%s] %s %s" % ("PASS" if c["ok"] else "FAIL", c["id"], c["detail"]))
        print("VERDICT: %s" % ("PASS" if res["ok"] else "FAIL"))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
