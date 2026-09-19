# -*- coding: utf-8 -*-
"""时间覆盖只读统计（阶段二 批 0 · A）。

遍历认知图库 LAYERS 全部 8 层目录下的 *.md，用 nodefile.loads 取 frontmatter，统计：
  n_total        合法 md 节点总数
  n_eff_start    包含 md_cg.trust.FROM_ALIASES 任一键
  n_eff_end      包含 md_cg.trust.UNTIL_ALIASES 任一键
  n_obs_window   condition_space.time_window 或 temporal 非空
  n_believed     包含 trust.BELIEVED_FIELD（仅记录，不判定语义）

root 缺省读环境变量 MDCG_ROOT；缺失即 stderr 报错并 exit 2（fail-closed，不猜路径）。

用法：
  python scripts/retr_time_coverage.py [--root DIR] [--out FILE]
"""
import argparse
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import nodefile      # noqa: E402
from md_cg import trust         # noqa: E402
from md_cg.mdcg import LAYERS   # noqa: E402


# 生效条件：x 为 None / 空字符串 / 空列表 / 空字典时返回 False，否则返回 True。
def _nonempty(x):
    return x not in (None, "", [], {})


# 全时窗哨兵上界：condition_space.time_window 默认全时窗的右端点（取证自真实节点）。
FULL_WINDOW_HI = 9999999999.0


# 生效条件：v 为「全时窗哨兵」形态（两元序列且覆盖 [0, 9999999999]，或字符串
# 「全时窗/任意时刻」）时返回 True；其它形态返回 False。
def _is_full_window(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            lo, hi = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return False
        return lo <= 0 and hi >= FULL_WINDOW_HI
    if isinstance(v, str):
        return v.strip() in ("全时窗", "任意时刻")
    return False


# 生效条件：fm 为 dict 且 aliases 为字符串或字符串可迭代对象时，返回 fm 是否包含其中
# 任一键（aliases 为单字符串按单元素处理；fm 非 dict 时不含任何键）。
def _contains_alias(fm, aliases):
    if isinstance(aliases, str):
        aliases = (aliases,)
    return any(k in fm for k in aliases)


# 生效条件：fm 为 dict 时提取 condition_space.time_window 与 temporal，返回是否至少
# 其一为**非全时窗哨兵**的观测时窗；两者均缺省/为空/仅哨兵时返回 False。
# 取证：节点 condition_space.time_window 的默认值即全时窗哨兵 [0.0, 9999999999.0]，
# 直接按「非空」判会得到 100% 假命中，故须排除哨兵后才是真实观测时窗覆盖。
def _has_obs_window(fm):
    cs = fm.get("condition_space")
    candidates = []
    if isinstance(cs, dict):
        candidates.append(cs.get("time_window"))
    candidates.append(fm.get("temporal"))
    for v in candidates:
        if _nonempty(v) and not _is_full_window(v):
            return True
    return False


# 生效条件：root 为目录且 layers 为层名可迭代对象时，返回 root 下这些层目录内递归
# 遍历到的 *.md 文件数；层目录不存在时该层计 0。
def _count_layer_nodes(root, layers):
    total = 0
    for layer in layers:
        layer_dir = os.path.join(root, layer)
        if not os.path.isdir(layer_dir):
            continue
        for _dirpath, _dirnames, files in os.walk(layer_dir):
            total += sum(1 for fn in files if fn.endswith(".md"))
    return total


# 生效条件：argv 为 None 或参数序列时解析命令行并逐层统计；MDCG_ROOT/--root 缺省或
# 非目录返回 2，统计成功写 JSON 并返回 0。
def main(argv=None):
    parser = argparse.ArgumentParser(description="时间覆盖只读统计")
    parser.add_argument("--root", default=(os.environ.get("MDCG_ROOT") or "").strip())
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    if not args.root:
        print("错误：未提供认知图库根：设环境变量 MDCG_ROOT 或传 --root DIR",
              file=sys.stderr)
        return 2

    root = os.path.abspath(os.path.expanduser(args.root))
    if not os.path.isdir(root):
        print("错误：MDCG_ROOT 不是目录：%s" % root, file=sys.stderr)
        return 2

    per_layer = {layer: {"n_total": 0, "n_eff_start": 0, "n_eff_end": 0,
                         "n_obs_window": 0, "n_believed": 0} for layer in LAYERS}
    failed_loads = 0

    for layer in LAYERS:
        layer_dir = os.path.join(root, layer)
        if not os.path.isdir(layer_dir):
            continue
        for dirpath, _dirnames, files in os.walk(layer_dir):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    fm, _content = nodefile.loads(text)
                    if not isinstance(fm, dict):
                        raise ValueError("non-dict frontmatter")
                except Exception:
                    failed_loads += 1
                    continue

                row = per_layer[layer]
                row["n_total"] += 1
                if _contains_alias(fm, trust.FROM_ALIASES):
                    row["n_eff_start"] += 1
                if _contains_alias(fm, trust.UNTIL_ALIASES):
                    row["n_eff_end"] += 1
                if _has_obs_window(fm):
                    row["n_obs_window"] += 1
                if _contains_alias(fm, trust.BELIEVED_FIELD):
                    row["n_believed"] += 1

    total = sum(row["n_total"] for row in per_layer.values())
    eff_start = sum(row["n_eff_start"] for row in per_layer.values())
    eff_end = sum(row["n_eff_end"] for row in per_layer.values())
    obs_window = sum(row["n_obs_window"] for row in per_layer.values())
    believed = sum(row["n_believed"] for row in per_layer.values())

    rates = {
        "eff_start": (eff_start / total) if total else 0.0,
        "eff_end": (eff_end / total) if total else 0.0,
        "obs_window": (obs_window / total) if total else 0.0,
        "believed": (believed / total) if total else 0.0,
    }

    out = {
        "meta": {
            "at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "root": root,
            "n_total": total,
            "rates": {k: round(v, 6) for k, v in rates.items()},
            "n_failed_loads": failed_loads,
        },
        "total": {
            "n_total": total,
            "n_eff_start": eff_start,
            "n_eff_end": eff_end,
            "n_obs_window": obs_window,
            "n_believed": believed,
        },
        "per_layer": per_layer,
    }

    date = _dt.date.today().strftime("%Y%m%d")
    default_out = os.path.join(REPO, "data", "external", "eval_results",
                               "time_coverage_%s.json" % date)
    out_path = args.out or default_out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
