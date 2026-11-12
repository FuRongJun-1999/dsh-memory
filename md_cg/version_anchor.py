# -*- coding: utf-8 -*-
"""版本锚（version anchor）——I18 的代码落点。

为什么需要（issue #6 提案，2026-10-18 采纳）：
    I17 规定「任何投影不得自称权威」，那么每个投影必须能回溯到
    「信息 ＋ 条件空间 ＋ 证据链」三元组。**版本锚就是那个回溯入口**——
    缺版本锚的对外材料，读者无法判断它对应哪一版理论、哪一版架构，
    也就无法回溯。这不是排版问题，是可回溯性的前提。

三条纪律：
1. **三元齐全**：理论版本、架构版本、本投影版本，缺一不可记为不完整。
2. **机器可读**：格式固定，便于校验（conformance / CI 可红）。
3. **不猜**：解析不到就是缺，不用「看起来像版本号」去**猜**——猜出来的锚比没有更糟。

格式（Markdown 引用块内一行，字段用全角竖线分隔）：

    > **版本锚**：理论=智能论 3.4 ｜ 架构=灵枢记忆系统统一架构 v1.2 ｜ 投影=变更说明 v1

也接受 YAML 式三行：

    version_anchor:
      theory: 智能论 3.4
      architecture: 灵枢记忆系统统一架构 v1.2
      projection: 变更说明 v1
"""

import re

__all__ = ["FIELDS", "parse_anchor", "check_anchor", "ANCHOR_LINE_RE"]

#: 三元字段（键名 → 中文别名，都接受）
FIELDS = ("theory", "architecture", "projection")
_ALIASES = {
    "theory": ("theory", "理论", "理论版本"),
    "architecture": ("architecture", "架构", "架构版本"),
    "projection": ("projection", "投影", "本投影", "投影版本"),
}

#: 单行形态：  > **版本锚**：理论=… ｜ 架构=… ｜ 投影=…
ANCHOR_LINE_RE = re.compile(r"版本锚\*\*\s*[：:]\s*(.+)$", re.M)
_KV_RE = re.compile(r"([^=＝｜|]+?)\s*[=＝]\s*([^｜|]+)")


def _canon(name):
    n = str(name or "").strip()
    for key, alts in _ALIASES.items():
        if n in alts:
            return key
    return None


def parse_anchor(text):
    """从文本中解析版本锚。

    返回 {"found": bool, "anchor": {field: value}, "missing": [field...]}。
    两种形态都支持；解析不到即 missing，**不做推测性填充**。
    """
    text = str(text or "")
    anchor = {}

    m = ANCHOR_LINE_RE.search(text)
    if m:
        for k, v in _KV_RE.findall(m.group(1)):
            key = _canon(k)
            if key and key not in anchor:
                val = v.strip().strip("*_ ")
                if val:
                    anchor[key] = val

    # YAML 式三行形态（仅在上面的单行形态没解析全时补充）
    if len(anchor) < len(FIELDS):
        for key, alts in _ALIASES.items():
            if key in anchor:
                continue
            for alt in alts:
                ym = re.search(r"^\s*" + re.escape(alt) + r"\s*[：:]\s*(.+?)\s*$",
                               text, re.M)
                if ym and ym.group(1).strip():
                    anchor[key] = ym.group(1).strip().strip("\"'*_ ")
                    break

    missing = [f for f in FIELDS if not anchor.get(f)]
    return {"found": bool(anchor), "anchor": anchor, "missing": missing}


#: 历史材料标记：早于 I18 施行、且作者已难追溯的对外材料。
#: 它们**不补锚**（推定版本等于造锚），但在检查结果里显式区分于「应补未补」。
LEGACY_MARK = "legacy_no_anchor"


def check_anchor(text):
    """I18 判定：三元齐全才算通过。返回 (ok, detail)。

    detail["legacy"] 为真表示该材料自带历史标记——不算通过，但也不算待修。
    这两件事必须分开：**「明示未标注」与「忘了标注」责任不同**。
    """
    rep = parse_anchor(text)
    ok = rep["found"] and not rep["missing"]
    legacy = LEGACY_MARK in str(text or "")
    return ok, {"anchor": rep["anchor"], "missing": rep["missing"],
                "found": rep["found"], "legacy": legacy}


def scan_dir(directory, suffix=".md"):
    """扫描目录下的对外材料，分类为 ok／legacy／todo。

    「todo」是应补未补的，需要人决定；「legacy」是明示历史材料，不催。
    """
    import os
    rows = {"ok": [], "legacy": [], "todo": []}
    d = str(directory)
    if not os.path.isdir(d):
        return {"error": "目录不存在：%s" % d, **rows}
    for name in sorted(os.listdir(d)):
        if not name.endswith(suffix):
            continue
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            rows["todo"].append({"file": name, "why": "read_error: %s" % exc})
            continue
        ok, detail = check_anchor(text)
        if ok:
            rows["ok"].append(name)
        elif detail.get("legacy"):
            rows["legacy"].append(name)
        else:
            rows["todo"].append({"file": name, "missing": detail["missing"]})
    return rows


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--check" not in argv:
        print("用法：python -m md_cg.version_anchor --check <目录>  [--json]")
        return 2
    d = argv[argv.index("--check") + 1]
    rows = scan_dir(d)
    if "--json" in argv:
        import json as _j
        print(_j.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("ok=%d legacy=%d todo=%d" % (len(rows["ok"]), len(rows["legacy"]),
                                           len(rows["todo"])))
        for item in rows["todo"]:
            print("  TODO ", item)
    return 0 if not rows["todo"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
