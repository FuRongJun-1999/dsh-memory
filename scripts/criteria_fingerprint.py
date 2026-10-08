# -*- coding: utf-8 -*-
"""判据面指纹（口径与编外实例逐字一致，已由反解 + 命中验证：5a2778a -> c5a3280201a4499f）。

# 功能名：判据面指纹复算
# 生效条件：需要比对「判据面文件集合」在两端是否同一（互验断言 A3 的机械输入）时；任一修订号可用
# 子功能：集合=md_cg 下所有 test_*.py + scripts/run_tests.py；算法=sha256(按仓库相对路径升序拼接各文件**行尾归一后**的字节)，取值前 16 个十六进制字符
# 执行：python -X utf8 scripts/criteria_fingerprint.py [--commit <rev>] [--json]（--commit 用 git archive 抽树计算，不改工作树）
# 验证方式：--commit 5a2778a 应得 199d99ef460d0ad3（行尾归一后的**跨环境稳定值**；见下「EOL 口径」——旧文档值 c5a3280201a4499f 是 core.autocrlf=true 下的 EOL artifact，在 core.autocrlf=false 的克隆里旧脚本同样算出 199d99ef460d0ad3）；--commit main 同值即表示两端判据面逐字节同一（行尾不再使两腿/两机分裂）
# 不适用条件：本脚本不入判据集合（名字非 test_*、且非 run_tests.py），但它**落在 scripts/ 下**——若将来口径扩为「scripts 下所有 .py」则会使集合变化，须同步两端

EOL 口径（S4b 裁定 = 归一；只动行尾两个字节序列，不改其余任何字节）：

  · **为什么要归一**：判据面的内容 = **判据文本**，行尾（CRLF/LF）是 checkout 的本地
    artifact、不是判据内容。实测（本机 `core.autocrlf=true`，git 2.55）三条事实：
      ① 工作树的 EOL 是**混合**的（273 件里 29 件 CRLF / 244 件 LF——被工具重写过的文件
         行尾与 git 检出不一致）⇒ 旧脚本工作树腿 = `6918af00a470f00d`；
      ② **`git archive` 也听 `core.autocrlf`**（非只 checkout）⇒ 旧脚本 `--commit` 腿在这台
         机器上把 273 件全转成 CRLF = `d560fa6dbf3d599a`；两条腿因此天生不等，而差异**纯由
         行尾状态造成**，不含任何内容差异；
      ③ 同一克隆（autocrlf=false，LF 面）里旧脚本两腿**相等** = `82e33bec15273d6c`；
         把该克隆翻成 autocrlf=true + 面全 CRLF，旧脚本两腿**又相等**但换成 `d560fa6dbf3d599a`
         ——同一个修订号、同一份内容，值随机器检出配置而变 ⇒ 判据不可复现、跨端互验 A3 报假不一致。
  · **归一怎么做**：`_lf()` 把每个文件字节里的全部 `b"\\r\\n"` 换成 `b"\\n"`；其余字节逐位保留
    （不做 strip / 不改编码 / 不动行内空白）。归一在 `fingerprint()` 的**唯一取字节点**做 ⇒
    工作树腿与 `--commit` 抽树腿**走同一条口径**（`--commit` 腿在 autocrlf=true 下本是 CRLF，
    只归一工作树腿会让两腿在干净克隆里仍分裂——那只是把缺陷挪位，不是修）。
    实测归一后上述两种环境得**同一个值** `1c8f564ce29d3679`（= HEAD 内容全 LF 归一）。
  · **代价 / 已知取舍（明示，不藏）**：ⓐ 若有人**故意**把行尾由 LF 改成 CRLF 并当作「内容
    改动」，归一后该改动**不会**使指纹改变——本脚本视其为正确（行尾不是判据内容）；确需把行尾
    也算进判据时，须另行报告「归一前 / 归一后」两个值（本班按归一实施，未加双值输出）。
    ⓑ 归一使**冻结向量取值换代**：`5a2778a` 由 EOL artifact 值 `c5a3280201a4499f`（autocrlf=true）
    换为跨环境稳定值 `199d99ef460d0ad3`——跨端取值若不带上本口径改动，两端值必分裂，须同步。
    ⓒ `md_cg/test_reach_meta_exits.py` 的 **git blob 自带 CRLF**（工作树与 blob 皆 CRLF），
    故归一在「LF 面」上对它亦非 no-op——这是归一使 `82e33bec…`→`1c8f564c…` 的唯一来源件。
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile

TARGET_REL = "scripts/run_tests.py"
TRUNC = 16
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_rels():
    """git 追踪面（仓根相对 · posix 分隔）集合；git 不可用/非仓 ⇒ None（调用方降级）。

    判据面须锚在**追踪面**而非文件系统面：若本地工作树里有未追踪的
    `md_cg/test_*.py`（草稿/临时夹具），文件系统面会把它算进指纹，而
    `--commit`（git archive 抽树）那条腿没有它 ⇒ 两端指纹「假不一致」。
    按「是否被 git 追踪」这个**性质**判，不逐个硬编码排除目录。
    """
    try:
        proc = subprocess.run(["git", "-C", _REPO, "ls-files", "-z"],
                              capture_output=True, check=True)
    except Exception:                                  # noqa: BLE001 —— 兜底见下
        return None
    return {p.replace("\\", "/") for p in
            proc.stdout.decode("utf-8", "replace").split("\0") if p}


# 生效条件：给定 root 时，递归收集 root/md_cg 下文件名以 test_ 开头且以 .py 结尾的文件（跳过 __pycache__ 目录），并在 os.path.exists(root/TARGET_REL) 为真时追加模块级常量 TARGET_REL，返回去重排序后的以 "/" 分隔的相对路径列表；
# root 就是**本仓工作树**时，再按「git 追踪面」过滤（非追踪件不入判据面）；降级（明示）：该情形下 git 不可用 ⇒ 退回原文件系统走查并打印 `[降级]`，读数须按降级看待。`--commit` 腿传的是 git archive 抽出的临时树（≠ 本仓根），保持原走查语义 —— 那条腿本来就是追踪面，不得再被本仓追踪面误筛。
def files_from_worktree(root):
    at_repo = os.path.abspath(root) == _REPO
    tracked = _tracked_rels() if at_repo else None
    if at_repo and tracked is None:
        print("[降级] git 不可用：判据面退化为文件系统走查"
              "（可能与 CI 干净克隆不一致）")
    out = []
    for base, dirs, names in os.walk(os.path.join(root, "md_cg")):
        dirs[:] = [d for d in sorted(dirs) if d != "__pycache__"]
        for fn in sorted(names):
            if fn.startswith("test_") and fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(base, fn), root).replace(os.sep, "/")
                if tracked is not None and rel not in tracked:
                    continue        # 非追踪件不入判据面
                out.append(rel)
    if os.path.exists(os.path.join(root, TARGET_REL)) and (
            tracked is None or TARGET_REL in tracked):
        out.append(TARGET_REL)
    return sorted(set(out))


# 生效条件：对给定 commit 执行 git archive --format=tar 的 returncode 为 0 时，把 stdout 作为 tar 解包到 tempfile.mkdtemp 新建的目录并返回该目录路径，returncode 非 0 时抛 SystemExit；
def worktree_of(commit):
    """把某修订抽到临时目录（git archive + tarfile，纯 Python，不改 .git/工作树）。"""
    r = subprocess.run(["git", "archive", "--format=tar", commit], capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git archive 失败：" + r.stderr.decode("utf-8", "replace")[:200])
    tmp = tempfile.mkdtemp(prefix="criteria_")
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        # P1-8（批次 24，外部审查报告）：filter="data" 拒绝绝对路径/.. 穿越/
        # 外部符号链接成员（Py3.12+ 官方过滤墙），堵归档解包越界写
        tf.extractall(tmp, filter="data")
    return tmp


# 生效条件：data 为 bytes 时返回把全部 b"\r\n" 换成 b"\n" 后的副本（只改行尾两个字节序列，
# 其余字节逐位保留 ⇒ 不改变判据内容语义）；非 bytes 由 bytes.replace 语义抛错，不兜底。
def _lf(data: bytes) -> bytes:
    """行尾归一 CRLF→LF（口径与理由见文件头「EOL 口径」段）。"""
    return data.replace(b"\r\n", b"\n")


# 生效条件：给定 root 时，逐个以二进制读取 files_from_worktree(root) 返回的每个文件、经 `_lf()` 行尾归一后更新 sha256，返回 {"files": 该列表长度, "value": 摘要 hexdigest 的前 TRUNC 位}；
def fingerprint(root):
    files = files_from_worktree(root)
    h = hashlib.sha256()
    for f in files:
        with open(os.path.join(root, f), "rb") as fh:
            h.update(_lf(fh.read()))
    return {"files": len(files), "value": h.hexdigest()[:TRUNC]}


# 生效条件：无必需形参；--commit 为非空串时 root 取 worktree_of(--commit)，为空串时取 --root（argparse 缺省 "."），--json 为真时打印 json.dumps(fp) 否则打印 CRITERIA_FINGERPRINT 单行文本，均返回 0，且 fp["commit"] 在 --commit 为空串时回落为 "<worktree>"、非空串时为该参数值；
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default="")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = a.root
    if a.commit:
        root = worktree_of(a.commit)
    fp = fingerprint(root)
    fp["commit"] = a.commit or "<worktree>"
    if a.json:
        print(json.dumps(fp, ensure_ascii=False))
    else:
        print("CRITERIA_FINGERPRINT files=" + str(fp["files"]) + " value=" + fp["value"]
              + " commit=" + fp["commit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())