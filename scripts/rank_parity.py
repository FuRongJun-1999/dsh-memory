# -*- coding: utf-8 -*-
"""issue #29 端到端 rank 对拍：Python search_rrf vs Rust mdcg-eval --serve。

同一认知图上，两侧对同批 query 的 top-k 结果做**逐位比对**（非集合、
非 hit@k——那两类守卫看不见路内排序漂移）。

批次 15 升级：
  - `--dataset scripts/retrieval_dataset.json`：**两侧读同一份数据集文件**
    （语料+query 外置，共享数据集纪律）；缺省仍用内建合成语料（向后兼容）；
  - Rust 侧 env `MDCG_EN_ZH_MAP` 自动指向仓库内 en_zh_map.json（统一归一
    层词表，Python 导出物）——两侧同一词表、同一 `MDCG_UNIFY_QUERY` 开关；
  - `--ab`：unify on/off 各跑一遍 Python 侧，按 query tag 汇总 top-1 命中
    变化——统一归一层（统一翻译为中文→归一化到标准中文集→检索）的
    **转正证据面**。（CH-1 起该路径也按本 harness 钉住的口径运行并在头部
    自描述口径；此前它隐式吃 Python 产品缺省 legacy，读数口径不自描述——
    实测「beef noodles lunch」的 off 侧 top-1 由 `ds_en_02` 变 `ds_en_03`，
    变化条数仍 5/10，跨语修复结论不变。）

CH-1（2026-09-29）· 词法打分口径接线 —— **本 harness 的缺省口径 = jaccard**
（与评测面同判据：`md_cg/eval_common.py::use_jaccard`）。本脚本的判据是
「**两侧同口径下**逐位一致」；口径若不钉住，两侧各吃各自缺省，而**两侧缺省
本就不同**：

    | 侧     | 缺省                      | 出处（本 harness 不改成缺省）                    |
    |--------|---------------------------|--------------------------------------------------|
    | Python | `legacy`（|qb∩db|/|qb|）   | `md_cg/mdcg.py`：`SCORE_MODE = os.environ.get("MDCG_SCORE_MODE") or "legacy"`（产品缺省） |
    | Rust   | `jaccard`（|qb∩db|/|qb∪db|）| `rust/src/main.rs` `Cfg.jaccard: true`、`rust/src/engine.rs` `EngineConfig::default()` |

  ⇒ 此前本 harness 长期在拿**两套词法公式互相比较**（实测缺省态逐位 7/10、
  退出码 1；三条 DIFF 全是「同一批分数分配给不同节点」的伪差异，Python 侧
  切 jaccard 后 10/10/10）。现两侧都**显式钉住、不吃各自缺省**：

  * Python 侧：`md_cg/eval_common.py::use_jaccard()`——**既有单点**（全部
    bench 脚本都调它），本 harness 不新写第二套开关；
  * Rust 侧：argv 显式 `--score jaccard`（`--serve` 与评测 CLI 同一入参），
    并**回读**被拉起进程自报的实际口径（request `{"op":"info"}` →
    response 的 `score` 字段，由 `rust/src/serve.rs` 回带）——不假设
    「我传了就等于它按这个打分」；
  * 两侧实际口径不一致、或 `env MDCG_SCORE_MODE` 声明了与钉住值不同的口径，
    即打印**两侧口径 + 修复提示**并非 0 退出（3）——**禁止再次出现拿两套
    公式静默对拍**。
  * 口径的**唯一单点**是本文件的 `SCORE_MODE` 常量：改口径只改这一行（两侧
    同批显式钉同一值）；本 harness 不接受用 env 改口径（那会重新变成「两处
    开关」= 本缺陷形态），env 声明冲突即报错退出。

用法：
  cargo build --release（rust/ 下）
  python scripts/rank_parity.py --exe rust/target/release/mdcg-eval --ab
返回码 0 = 逐位一致 · 1 = 逐位劈叉 · 2 = rust 二进制缺失 ·
        3 = 两侧词法打分口径不一致（含 env 声明冲突）· 4 = rust 侧未报出口径
        （二进制过期，未含 CH-1 回读面）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── CH-1：本 harness 词法打分口径的**唯一单点** ──────────────────────────
# 改口径只改这一行（下面两侧都会按它显式钉住）；不接受用 env 改口径——那会
# 重新变成「两处开关」（本缺陷形态），env 声明冲突一律报错退出。
SCORE_MODE = "jaccard"

# 两侧**产品缺省**的事实声明（本 harness 不改它们，只把差异显式化）：
#   Python 缺省 legacy（md_cg/mdcg.py:SCORE_MODE）——线上主库检索口径；
#   Rust   缺省 jaccard（Cfg.jaccard / EngineConfig::default().jaccard）。
_PY_DEFAULT = "legacy"
_RUST_DEFAULT = "jaccard"

# 回读 Rust 侧实际口径用的请求（serve 协议在 rust/src/serve.rs）。
_RUST_INFO_REQ = {"op": "info"}

QUERIES = [
    "慈善跑 心理健康 发声 意识 意义",
    "newuser 探针结论",
    "灵枢 hotcache 设计",
    "The compiler wrote tests",
    "蜂群调度 依赖门禁",
    "数据库 迁移 备份 策略",
    "agent review verdict",
    "检索 门控 收敛",
    "安全 审计 令牌",
    "memory recall pipeline",
]


def build_cogmap(root, dataset=None):
    """建库：dataset 给定读数据集 nodes，否则用内建合成语料。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="parity", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    if dataset:
        for nd in dataset["nodes"]:
            cg.add(nd["id"],
                   f"# 功能名：{nd['title']}\n# 正文：{nd['body']}",
                   layer=nd.get("layer") or "knowledge")
        cg.flush()
        return len(dataset["nodes"])
    zh = ["蜂群调度器按 workers 上限领取任务", "依赖门禁在领取前检查上游终态",
          "热缓存在构造时按开关挂载", "冲突闸对无法比对的场景放行并留审计",
          "自证拒绝要求验证方与编译方不同主体", "检索门控把候选先按域收敛",
          "令牌验签失败必须拒绝启动", "写入管线在落盘后失效查询缓存",
          "评审队列的判据指纹随提案落盘", "心跳与存活判据必须同口径"]
    en = ["The compiler generates candidates from dialog",
          "Reviewers must be independent from compilers",
          "Hot cache speeds up repeated queries",
          "Dependency gate checks upstream final states",
          "Conflict gate defers unmatched comparisons",
          "Search fusion merges four retrieval paths",
          "Token verification is fail closed on mismatch",
          "Heartbeat freshness guards single instance",
          "Audit records store hashes not payloads",
          "Cold verification enqueues after writes"]
    n = 0
    for i in range(15):
        for kind, corpus in (("zh", zh), ("en", en)):
            body = corpus[(i + len(kind)) % len(corpus)]
            node = f"parity_{kind}_{i:02d}"
            cg.add(node, f"# 功能名：{kind} 样本 {i}\n# 正文：{body} 样本{i}",
                   layer="knowledge")
            n += 1
    cg.flush()
    return n


def python_topk(root, queries, k=5):
    """返回 {query: [(id, score), ...]}。

    打分口径取自 `pin_python_score_mode()` 注入的模块级 `mdcg.SCORE_MODE`
    （CH-1：本函数**不自带**口径开关，吃的是那个单点注入的值）。
    """
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="parity", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))
    out = {}
    for q in queries:
        results, _meta = cg.search_rrf(q, k=k)
        out[q] = [(_x[0].get("id") or _x[0].get("path") or "", round(_x[1], 6))
                  for _x in results]
    return out


def pin_python_score_mode(want=SCORE_MODE):
    """Python 侧口径单点：经既有评测入口注入，并**读回**实际生效值。

    返回 `(实际口径, 冲突说明 | None)`。

    注入走 `md_cg/eval_common.py::use_jaccard()`（评测面既定单点，全部 bench
    脚本都调它），**不新写第二套开关**；非 jaccard 的钉住值直接落到模块级
    `SCORE_MODE`（取值仍只由本文件常量决定）。

    冲突 = env `MDCG_SCORE_MODE` 声明了与 `want` 不同的口径。此时既不能静默
    覆盖（= 无视操作者的显式声明），也不能静默照吃（= 两侧口径不同却继续
    对拍），故原样交回调用方报警退出。
    """
    from md_cg import eval_common
    import md_cg.mdcg as mdcg
    if want not in mdcg.SCORE_MODES:
        return None, "SCORE_MODE=%r 不在 %r 内" % (want, mdcg.SCORE_MODES)
    declared = (os.environ.get("MDCG_SCORE_MODE") or "").strip().lower()
    if declared and declared != want:
        return mdcg.SCORE_MODE, (
            "env MDCG_SCORE_MODE=%s 与 harness 钉住的口径 %s 冲突" % (declared, want))
    if want == "jaccard":
        eval_common.use_jaccard()
    else:
        mdcg.SCORE_MODE = want
    return mdcg.SCORE_MODE, None


def _close_proc(p):
    try:
        p.stdin.close()
        p.wait(timeout=5)
    except Exception:                       # noqa: BLE001 —— 清理面不再抛
        try:
            p.kill()
        except Exception:                   # noqa: BLE001
            pass


def rust_reported_score(proc):
    """回读被拉起进程**实际生效**的词法口径（serve `info` 的 `score` 字段）。

    读不到即抛 RuntimeError：本 harness 拒绝在「不知道对方按哪套公式打分」的
    形态下继续对拍（那正是本缺陷）。二进制过期（未含 CH-1 回读面）走此路。
    """
    proc.stdin.write(json.dumps(dict(_RUST_INFO_REQ)) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"rust serve 在 info 请求上关闭输出：{err[:500]}")
    resp = json.loads(line)
    if not resp.get("ok"):
        raise RuntimeError("rust serve info 失败：%s"
                           % json.dumps(resp, ensure_ascii=False)[:300])
    mode = resp.get("score")
    if not mode:
        raise RuntimeError("rust serve 未报出词法口径（info 无 score 字段）")
    return str(mode).strip().lower()


def rust_open(exe, root, score=SCORE_MODE):
    """拉起 Rust serve 实例：argv **显式**钉住口径 + 回读其自报口径。

    返回 `(Popen, 自报口径)`。`--score` 与评测 CLI 同一入参（serve 亦接受），
    故不依赖 `Config::default()`。
    """
    env = dict(os.environ)
    env.pop("MDCG_TOKEN", None)          # 对拍面与本测试无关，防部署 env 干扰
    # 统一归一层：Rust 侧词表显式指到仓库内导出物（与 Python 同一份）；
    # MDCG_UNIFY_QUERY 由调用进程 env 原样透传（三态由外层控制；缺省 = 未设 = 关）
    env.setdefault("MDCG_EN_ZH_MAP",
                   os.path.join(_REPO, "md_cg", "semantic", "en_zh_map.json"))
    p = subprocess.Popen([exe, "--root", root, "--serve", "--score", score],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", env=env)
    try:
        mode = rust_reported_score(p)
    except Exception:                       # noqa: BLE001 —— 关进程后原样上抛
        _close_proc(p)
        raise
    return p, mode


def rust_topk(proc, queries, k=5):
    """在已打开的 serve 实例上跑批次 query，返回 {query: [(id, score), ...]}。"""
    out = {}
    try:
        for q in queries:
            req = json.dumps({"op": "search", "query": q, "k": k}) + "\n"
            proc.stdin.write(req)
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                err = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"rust serve 输出关闭：{err[:500]}")
            resp = json.loads(line)
            hits = resp.get("hits") or resp.get("results") or []
            pairs = []
            for h in hits:
                if isinstance(h, dict):
                    pairs.append((h.get("id") or h.get("node") or "",
                                  h.get("score")))
                else:
                    pairs.append((str(h), None))
            out[q] = pairs
    finally:
        _close_proc(proc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(
        _REPO, "rust", "target", "release", "mdcg-eval.exe"
        if os.name == "nt" else "mdcg-eval"))
    ap.add_argument("--root", default=None, help="复用已建库（缺省新建临时库）")
    ap.add_argument("--dataset", default=None,
                    help="共享数据集 JSON（nodes+queries 两侧同源；缺省内建合成语料）")
    ap.add_argument("--ab", action="store_true",
                    help="统一归一层 A/B：unify on/off 各跑 Python 侧，"
                         "按 tag 汇总 top-1 变化（转正证据）")
    args = ap.parse_args()

    if not os.path.isfile(args.exe):
        print(f"rust 二进制不存在：{args.exe}（先 cd rust && cargo build --release）")
        return 2

    dataset = None
    if args.dataset:
        with open(args.dataset, encoding="utf-8") as f:
            dataset = json.load(f)
    queries = [x["q"] for x in dataset["queries"]] if dataset else QUERIES

    # ---- CH-1 ①：Python 侧口径由单点显式钉住（不吃产品缺省 legacy）----
    py_mode, py_conflict = pin_python_score_mode()
    if py_mode is None:                     # 单点常量坏掉：harness 自身故障
        print(f"!! harness 词法口径单点不可用：{py_conflict}")
        return 3

    # ---- A/B 转正证据（仅 Python 侧；Rust 侧对拍在当前开关态做）----
    if args.ab and dataset:
        tags = {x["q"]: x["tag"] for x in dataset["queries"]}
        root_ab = tempfile.mkdtemp(prefix="mdcg_parity_ab_")
        n = build_cogmap(root_ab, dataset)
        hits = {}
        for mode, env_on in (("unify=0", False), ("unify=1", True)):
            if env_on:
                # 2026-09-30 缺省翻关后：**未设 = 关**，故「开」这一臂必须显式设 1
                # （此前靠 pop 吃「默认开」——翻缺省后 pop 会让两臂都成关态、
                #  A/B 恒零差异，属翻缺省连带的静默失效）。
                os.environ["MDCG_UNIFY_QUERY"] = "1"
            else:
                os.environ["MDCG_UNIFY_QUERY"] = "0"
            from md_cg import hotcache as _hc
            _hc.get.cache_clear() if hasattr(_hc.get, "cache_clear") else None
            top = python_topk(root_ab, queries)
            for q, r in top.items():
                hits.setdefault(q, {})[mode] = r[0][0] if r else None
        os.environ.pop("MDCG_UNIFY_QUERY", None)
        # CH-1：A/B 与对拍同口径（同一 harness 只有一套口径单点；此前该路径
        # 隐式吃 legacy 缺省，读数口径不自描述）。
        print(f"A/B（{n} 节点，top-1 变化；口径 {py_mode}（本 harness 钉住））：")
        changed = 0
        for q in queries:
            a0, a1 = hits[q]["unify=0"], hits[q]["unify=1"]
            if a0 != a1:
                changed += 1
                print(f"  [{tags[q]}] {q}\n      off -> {a0}\n      on  -> {a1}")
        print(f"top-1 变化 {changed}/{len(queries)}"
              f"（跨语 tag 应由 off 的空转/错位变为 on 的正确命中）")
        return 0

    if args.root:
        root = args.root
        n = sum(len(files) for _, _, files in os.walk(root))
    else:
        root = tempfile.mkdtemp(prefix="mdcg_parity_")
        n = build_cogmap(root, dataset)

    # ---- CH-1 ②：Rust 侧 argv 显式钉住口径 + 回读进程自报口径 ----
    try:
        proc, rs_mode = rust_open(args.exe, os.path.join(root, "graph"), SCORE_MODE)
    except RuntimeError as exc:
        print(f"!! rust 侧词法口径不可读：{exc}")
        print(f"   修复：cd rust && cargo build --release"
              f"（本 harness 需含 CH-1 `serve info.score` 回读面的构建）")
        return 4

    # ---- CH-1 ②：两侧实际口径对照；不一致即变响，不静默对拍 ----
    if py_conflict or py_mode != rs_mode:
        print("!! 词法打分口径不一致：两侧不在同一套公式上，拒绝静默对拍")
        print(f"   python 侧实际口径 = {py_mode}"
              + (f"（{py_conflict}）" if py_conflict else "")
              + f"；harness 钉住口径 = {SCORE_MODE}")
        print(f"   rust   侧实际口径 = {rs_mode}（argv 显式 --score {SCORE_MODE}）")
        print(f"   缺省值事实：python 缺省 {_PY_DEFAULT}（md_cg/mdcg.py:SCORE_MODE）/ "
              f"rust 缺省 {_RUST_DEFAULT}（rust/src/engine.rs Config::default().jaccard）"
              f" —— 两侧缺省本就不同，故两侧都必须显式钉住并回读。")
        if py_conflict:
            print("   修复：清掉 env MDCG_SCORE_MODE（本 harness 的口径唯一单点是 "
                  "scripts/rank_parity.py 的 SCORE_MODE 常量，不支持用 env 改口径）")
        else:
            print("   修复：检查两侧钉住链是否被改回各自缺省"
                  "（Python=eval_common.use_jaccard()，Rust=--score 入参 + serve info 回读）")
        _close_proc(proc)
        return 3

    print(f"语料节点 ~{n} · queries={len(queries)} · exe={args.exe}"
          f" · unify={os.environ.get('MDCG_UNIFY_QUERY', '0(默认关)')}"
          f" · score={py_mode}=rust {rs_mode}（两侧显式钉住）")

    py = python_topk(root, queries)
    rs = rust_topk(proc, queries)

    order_ok = set_ok = top1_ok = total = 0
    for q in queries:
        a = py.get(q) or []
        b = rs.get(q) or []
        ids_a = [x[0] for x in a]
        ids_b = [x[0] for x in b]
        total += 1
        if ids_a[:1] == ids_b[:1]:
            top1_ok += 1
        if set(ids_a) == set(ids_b):
            set_ok += 1
        if ids_a == ids_b:
            order_ok += 1
        else:
            print(f"  [DIFF] {q}")
            print(f"    py  ={a}")
            print(f"    rust={b}")
    print(f"逐位一致 {order_ok}/{total} · 集合一致 {set_ok}/{total} · "
          f"top-1 一致 {top1_ok}/{total}")
    return 0 if order_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
