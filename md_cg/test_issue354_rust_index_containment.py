# -*- coding: utf-8 -*-
r"""#354 P0-3 / P1-8 守卫（Rust 检索面）：_index.json path 物理 containment 与
索引装载「坏件不连坐」。

缺陷（本件修复，2026-10-14）
----------------------------
【P0-3】rust/src/store.rs 的条目装载直接 root.join(path) 读盘，**零 containment**：
  · 绝对路径（D:\x / \x / \\server\share）—— std 的 Path::join 遇绝对路径**整体
    替换** root；
  · 相对穿越（../x、a/../../x）。
  实测（修前，真二进制 mdcg-eval --serve）：_index.json 里塞 ../sentinel.txt 与
  绝对路径 → info.docs=3（哨兵被当节点正文读入）、查询 zzsentinel 直接命中
  id=哨兵节点 —— 库根之外的**内容回显**（哨兵泄漏）。
【P1-8】装载面「一个坏件连坐整个装载」：
  · 坏 _index.json（读到/解析失败）→ 旧实现两处 ? 直接让整个装载 Err，进程非零
    退出，合法 _index_log 分片里的节点**全不可检索**；
  · 坏分片（非法 UTF-8 字节，撕裂写残字节）→ 旧实现 read_to_string 整片全有全无，
    整分片被 continue 丢弃，**其内的合法行连同账**（同分片连坐）。

本守卫三层
----------
  [A] 行为面（真二进制 mdcg-eval --serve，端到端）：
      A1-A3 穿越形态逐类（相对 ../、绝对、混合分隔符/空串/NUL/盘符相对）不得命中
            哨兵、不得计入 docs、越界条目须有 stderr 留痕；
      A4 零误伤：合法路径照常可检索（修 containment 不得把正常库读坏）；
      A5-A7 P1-8：坏 _index.json + 好分片 → 装载不连坐；坏分片内合法行仍重放；
            两源皆好 → 合并语义（同 id 分片覆盖）不变。
  [B] 源断言（结构性，行为面不可用时仍决定 rc）：闸在场、闸在**读盘之前**被调用、
      判据含 canonicalize 物理层（不是只比字符串前缀）、临时/坏件路径有留痕。
  [C] 定点变异：拆掉物理层 / 拆掉逐行容错 → 判据必须转红（改源 → cargo build →
      跑守卫转红 → 还原 → 重建），绝不在真实工作树留下未还原改动。

运行：
  python -X utf8 -m md_cg.test_issue354_rust_index_containment
  python -X utf8 -m md_cg.test_issue354_rust_index_containment --mutate
退出码：0 全绿 / 1 有失败。
环境：MDCG_EVAL_EXE 可指向别处的 mdcg-eval 可执行文件。
诚实边界：行为面需要 rust/target/release 下的可执行件（gitignored）——本守卫按仓内
既有口径**自建**（cargo build --release）；cargo 与产物俱不可得时行为面显式 SKIP
并打印构建命令（源断言面 [B] 照判、照决定 rc），不把「没测到」记成绿。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUST_DIR = os.path.join(_REPO, "rust")
_STORE_RS = os.path.join(_RUST_DIR, "src", "store.rs")

PASS = 0
FAIL = 0
FAILS = []
SKIPS = []
_SANDBOXES = []
#: 变异自证用：_SILENT 为真时 check() 只把失败项记进 _VIOL（不打印、不计入读数）。
_SILENT = False
_VIOL = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if _SILENT:
        if not cond:
            _VIOL.append(name)
        return bool(cond)
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


def skip(name, why):
    SKIPS.append(name)
    print("  [SKIP] %s  · %s" % (name, why))


def _exe_path():
    env = os.environ.get("MDCG_EVAL_EXE")
    if env:
        return env
    base = os.path.join(_RUST_DIR, "target", "release", "mdcg-eval")
    return base + ".exe" if os.name == "nt" else base


EXE = _exe_path()
_BUILD_CMD = "cargo build --release   （在 %s 下执行）" % _RUST_DIR


def _ensure_exe():
    """确保 mdcg-eval 在场；返回是否可用（不可用则行为面 SKIP，源断言面照判）。"""
    if os.path.isfile(EXE):
        return True
    if not shutil.which("cargo") or not os.path.isdir(_RUST_DIR):
        print("      （%s 不在场且 cargo 不可用）" % EXE)
        return False
    print("      自建：%s" % _BUILD_CMD)
    r = subprocess.run(["cargo", "build", "--release"], cwd=_RUST_DIR,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    if r.returncode != 0:
        print("      构建失败：%s" % (r.stderr or "")[-400:])
        return False
    return os.path.isfile(EXE)


def _mkroot(tag):
    t = tempfile.mkdtemp(prefix="i354idx_%s_" % tag)
    _SANDBOXES.append(t)
    root = os.path.join(t, "lib")
    os.makedirs(os.path.join(root, "knowledge"))
    return t, root


def _write(path, text):
    """写文本或字节（bytes 走二进制口径——坏 UTF-8 分支用）。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    if isinstance(text, (bytes, bytearray)):
        io.open(path, "wb").write(text)
    else:
        io.open(path, "w", encoding="utf-8", newline="").write(text)


def _node(path, nid, body):
    _write(path, "---\nid: \"%s\"\ntags: []\nimportance: 0.5\n---\n%s\n" % (nid, body))


def _index_json(root, nodes):
    _write(os.path.join(root, "_index.json"),
           json.dumps({"nodes": nodes}, ensure_ascii=False))


def _entry(path, layer="knowledge", imp=0.5):
    return {"path": path, "layer": layer, "tags": [], "importance": imp, "edges": []}


def _serve(root, reqs):
    """拉起 mdcg-eval --serve，逐条请求取响应；返回 (响应列表, stderr 文本)。"""
    env = dict(os.environ)
    env.pop("MDCG_TOKEN", None)
    p = subprocess.Popen([EXE, "--root", root, "--serve"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", env=env)
    out = []
    try:
        for r in reqs:
            try:
                p.stdin.write(json.dumps(r) + "\n")
                p.stdin.flush()
            except (BrokenPipeError, OSError):
                # 子进程已死（如装载失败 exit 1）：静默截断请求序列，剩下的槽位
                # 补 None——判据看的是**读数**，不该被调用方的管道异常顶掉
                out.append(None)
                continue
            line = p.stdout.readline()
            out.append(json.loads(line) if line.strip() else None)
    finally:
        try:
            p.stdin.close()
        except Exception:                                  # noqa: BLE001
            pass
        try:
            p.wait(timeout=20)
        except Exception:                                  # noqa: BLE001
            p.kill()
    err = p.stderr.read() if p.stderr else ""
    return out, err


def _hits(resp):
    return (resp or {}).get("hits") or []


# ============================ [A] 行为面：P0-3 ============================

TOKEN = "zzsentinel354"
SENT_ID = "哨兵节点354"


#: 探针查询：越界条目在场 / 不在场两种库都必须给出**逐位一致**的读数。
_PROBES = (TOKEN, "SENTINEL-LEAK-354", "zznormal354")


def _readings(root):
    """跑一组固定请求，把可观测面带成可比较的元组：((docs, 候选), [(id,path,score)...]...)。

    为什么用「有/无越界条目的两库读数对拍」而不是「查询必须零命中」：本引擎在词法
    全空时会走 LIKE 兜底池（合法节点照样返回），故「零命中」不是可用判据；而
    「越界条目不得改变任何读数」是自校准的强判据——修前哨兵被当正文读入时，其
    importance=0.99 + 正文命中会直接改写 top-1（实测 hits=[哨兵节点354]）。
    """
    out, err = _serve(root, [{"op": "info"}]
                      + [{"op": "search", "query": q, "k": 10} for q in _PROBES])
    info = out[0] or {}
    rows = []
    for r in out[1:]:
        rows.append(sorted((h.get("id"), h.get("path"), h.get("score"))
                           for h in _hits(r)))
    return (info.get("docs"), info.get("candidates")), rows, err


def _traversal_case(name, evil_paths, tag="trav"):
    t = tempfile.mkdtemp(prefix="i354idx_%s_" % tag)
    _SANDBOXES.append(t)
    sentinel = os.path.join(t, "sentinel.txt")
    _node(sentinel, SENT_ID, "# 正文：%s 沙箱外哨兵内容 SENTINEL-LEAK-354" % TOKEN)
    root_evil = os.path.join(t, "lib_evil")
    root_ctrl = os.path.join(t, "lib_ctrl")
    for root in (root_evil, root_ctrl):
        os.makedirs(os.path.join(root, "knowledge"))
        _node(os.path.join(root, "knowledge", "good.md"), "good",
              "# 正文：正常内容 zznormal354")
    nodes = {"good": _entry("knowledge/good.md")}
    for i, p in enumerate(evil_paths):
        # ABS 标记：换成真实存在的库外哨兵绝对路径（绝对路径条目在**修前**正是
        # 因为 Path::join 整体替换 root 而读到它；修后须在词法层即被拒）
        nodes["evil%d" % i] = _entry(sentinel if p == "ABS" else p, imp=0.99)
    _index_json(root_evil, nodes)
    _index_json(root_ctrl, {"good": _entry("knowledge/good.md")})
    head_e, rows_e, err_e = _readings(root_evil)
    head_c, rows_c, _err_c = _readings(root_ctrl)
    flat = [x for r in rows_e for x in r]
    check("%s：哨兵节点名不得出现在任何命中里（泄漏面）" % name,
          SENT_ID not in [x[0] for x in flat], flat[:4])
    check("%s：越界条目在场与不在场，检索读数必须逐位一致" % name,
          rows_e == rows_c, {"with": rows_e[:2], "without": rows_c[:2]})
    # 注意：候选数（candidates）本就含被拒条目（它们是索引里的真实条目，只是
    # 读不出正文），故这面只钉**已装载文档数**——泄漏面正是「越界文件被当正文读入」。
    check("%s：已装载文档数不得因越界条目改变" % name,
          head_e[0] == head_c[0], {"with": head_e, "without": head_c})
    check("%s：越界条目须有 stderr 留痕（可诊断，不是静默丢弃）" % name,
          "越界被拒" in err_e and "P0-3" in err_e, err_e.strip()[-160:])
    check("%s：合法节点照常可检索（零误伤）" % name,
          [h.get("id") for h in _hits(_serve(root_ctrl, [{"op": "search",
                                                          "query": "zznormal354",
                                                          "k": 10}])[0][0])] == ["good"],
          rows_e[-1] if rows_e else None)
    shutil.rmtree(t, ignore_errors=True)


def a_relative():
    print("== A1 P0-3：相对穿越（../ 与 a/../..）==")
    _traversal_case("A1", ["../sentinel.txt", "knowledge/../../sentinel.txt",
                           "..\\sentinel.txt"])


def a_absolute():
    print("== A2 P0-3：绝对路径 / 根相对 / UNC ==")
    _traversal_case("A2", ["ABS", os.sep + "definitely-not-here.txt",
                           "\\\\server\\share\\x.md"], tag="abs")


def a_pathological():
    print("== A3 P0-3：病理 path（空串 / NUL / 盘符相对 / 库内目录）不得崩不得读 ==")
    t, root = _mkroot("patho")
    nodes = {"good": _entry("knowledge/good.md"),
             "empty": _entry(""),
             "nul": _entry("knowledge/" + chr(0) + "x.md"),
             "drvrel": _entry("C:sentinel.txt"),
             "is_dir": _entry("knowledge")}
    _index_json(root, nodes)
    _node(os.path.join(root, "knowledge", "good.md"), "good", "# 正文：zznormal354")
    out, err = _serve(root, [{"op": "info"},
                             {"op": "search", "query": "zznormal354", "k": 10},
                             {"op": "search", "query": TOKEN, "k": 10}])
    check("A3 病态 path 不致进程崩溃（info 仍应答）",
          (out[0] or {}).get("ok") is True, out[0])
    check("A3 库内目录条目（knowledge）不得被当节点读入",
          [h.get("id") for h in _hits(out[1])] == ["good"],
          [h.get("id") for h in _hits(out[1])])
    check("A3 病态 path 不泄漏哨兵",
          SENT_ID not in [h.get("id") for h in _hits(out[2])], _hits(out[2]))
    check("A3 病态 path 亦须留痕（词法层即拒）",
          "越界被拒" in err, err.strip()[-160:])
    shutil.rmtree(t, ignore_errors=True)


def a_symlink_escape():
    print("== A4 P0-3：符号链接指向库外（物理层判据的判别面）==")
    t, root = _mkroot("link")
    outside = os.path.join(t, "outside")
    os.makedirs(outside)
    _node(os.path.join(outside, "secret.md"), SENT_ID,
          "# 正文：%s SENTINEL-LEAK-354" % TOKEN)
    link = os.path.join(root, "knowledge", "link.md")
    made = False
    try:
        os.symlink(os.path.join(outside, "secret.md"), link)
        made = True
    except (OSError, NotImplementedError) as e:            # noqa: BLE001
        skip("A4 符号链接穿越", "本机无法创建符号链接（需开发者模式/权限）：%s" % e)
    if made:
        _index_json(root, {"evil_link": _entry("knowledge/link.md", imp=0.99),
                           "good": _entry("knowledge/good.md")})
        _node(os.path.join(root, "knowledge", "good.md"), "good",
              "# 正文：zznormal354")
        out, err = _serve(root, [{"op": "info"},
                                 {"op": "search", "query": TOKEN, "k": 10}])
        check("A4 符号链接指向库外不得被读（词法看不出，物理层才拦得住）",
              SENT_ID not in [h.get("id") for h in _hits(out[1])], _hits(out[1]))
        check("A4 越界留痕", "越界被拒" in err, err.strip()[-160:])
    shutil.rmtree(t, ignore_errors=True)


# ============================ [A] 行为面：P1-8 ============================

def _shard(nid, path, t):
    return json.dumps({"id": nid, "_t": t, "_s": 1,
                       "e": _entry(path)}, ensure_ascii=False) + "\n"


def a_bad_index_json():
    print("== A5 P1-8：坏 _index.json 不得连坐好分片（旧实现整装载 Err）==")
    t, root = _mkroot("badidx")
    _write(os.path.join(root, "_index.json"), b'{"nodes": {BROKEN!!!')
    _write(os.path.join(root, "_index_log", "2000-good.log"),
           _shard("shard_node", "knowledge/shard_node.md", 2.0))
    _node(os.path.join(root, "knowledge", "shard_node.md"), "shard_node",
          "# 正文：zzshard354")
    out, err = _serve(root, [{"op": "info"},
                             {"op": "search", "query": "zzshard354", "k": 5}])
    check("A5 装载不因坏 _index.json 失败（进程存活且命中分片节点）",
          [h.get("id") for h in _hits(out[1])] == ["shard_node"],
          {"info": out[0], "hits": _hits(out[1]), "stderr": err.strip()[-200:]})
    check("A5 降级须留痕（点名本源）", "降级跳过本源" in err and "_index.json" in err,
          err.strip()[-200:])
    shutil.rmtree(t, ignore_errors=True)


def a_bad_shard_lines():
    print("== A6 P1-8：坏分片内的合法行不得被连坐丢弃 ==")
    t, root = _mkroot("badshard")
    _index_json(root, {"idx_node": _entry("knowledge/idx_node.md")})
    _node(os.path.join(root, "knowledge", "idx_node.md"), "idx_node", "# 正文：zzidx354")
    logd = os.path.join(root, "_index_log")
    good = _shard("n3", "knowledge/n3.md", 3.0)
    _write(os.path.join(logd, "1000-mixed.log"),
           good.encode("utf-8") + b'{"id":"bad",\xff\xfe"x":1}\n'
           + _shard("n4", "knowledge/n4.md", 4.0).encode("utf-8"))
    _node(os.path.join(root, "knowledge", "n3.md"), "n3", "# 正文：zzthree354")
    _node(os.path.join(root, "knowledge", "n4.md"), "n4", "# 正文：zzfour354")
    out, err = _serve(root, [{"op": "info"},
                             {"op": "search", "query": "zzthree354", "k": 5},
                             {"op": "search", "query": "zzfour354", "k": 5}])
    check("A6 坏行之前的合法行仍重放（n3）",
          [h.get("id") for h in _hits(out[1])] == ["n3"], _hits(out[1]))
    check("A6 坏行之后的合法行仍重放（n4——同一分片不连坐）",
          [h.get("id") for h in _hits(out[2])] == ["n4"], _hits(out[2]))
    shutil.rmtree(t, ignore_errors=True)


def a_sources_merge():
    print("== A7 P1-8 阴性面：两源俱好时合并语义不变（分片覆盖同 id）==")
    t, root = _mkroot("merge")
    _index_json(root, {"n1": _entry("knowledge/n1.md", imp=0.1)})
    _node(os.path.join(root, "knowledge", "n1.md"), "n1", "# 正文：zzone354")
    _write(os.path.join(root, "_index_log", "3000-up.log"),
           _shard("n1", "knowledge/n1.md", 3.0))
    out, err = _serve(root, [{"op": "info"},
                             {"op": "search", "query": "zzone354", "k": 5}])
    check("A7 同 id 分片覆盖后仍单条命中（合并语义不变）",
          [h.get("id") for h in _hits(out[1])] == ["n1"], _hits(out[1]))
    check("A7 无坏件不得出现任何降级/越界告警（零噪声）",
          "降级" not in err and "越界被拒" not in err, err.strip()[-160:])
    shutil.rmtree(t, ignore_errors=True)


# ============================ [B] 源断言 ============================

def _src():
    return io.open(_STORE_RS, encoding="utf-8", errors="replace").read()


def b_source_face():
    print("== B 源断言（行为面不可用时仍决定 rc）==")
    src = _src()
    check("B1 containment 闸在场（resolve_in_root）", "fn resolve_in_root(" in src)
    check("B2 闸在 read_doc 内被调用（读盘之前）",
          "resolve_in_root(root, croot, &e.path)" in src)
    check("B3 物理层判据在场：canonicalize（不是只比字符串前缀）",
          "std::fs::canonicalize(&cand)" in src and "starts_with(croot)" in src)
    check("B4 词法层：拒绝对/根相对/盘符前缀与 .. 组件",
          "Component::Prefix(_)" in src and "Component::RootDir" in src
          and "Component::ParentDir" in src)
    check("B5 越界分类与调用方处理（OutOfRoot 不读盘）",
          "PathGate::OutOfRoot" in src and "DocLoad::OutOfRoot" in src)
    check("B5b 物理层判据本体：包含性比较 + 过闸才放行",
          "if ccand == *croot || ccand.starts_with(croot)" in src
          and "PathGate::Allowed(cand)" in src)
    # 两条臂**分别**断言：任一条被改回 ? 传播都要转红（V3 首版只钉了「存在」，
    # 变异体走的是另一条臂 ⇒ 判据没打红——量具缺陷，已分列）
    check("B6a P1-8：_index.json **读失败**臂降级跳过（不再 ? 掉整装载）",
          "不可读，降级跳过本源" in src)
    check("B6b P1-8：_index.json **解析失败**臂降级跳过（不再 ? 掉整装载）",
          "解析失败，降级跳过本源" in src)
    check("B7 P1-8：分片逐行容错解码（from_utf8 单行判）",
          "std::str::from_utf8(chunk)" in src)
    check("B8 反陈化：标注 issue #354 与本缺陷面",
          "#354 P0-3" in src and "#354 P1-8" in src)


# ============================ 主流程 ============================

_BEHAVIOR = (a_relative, a_absolute, a_pathological, a_symlink_escape,
             a_bad_index_json, a_bad_shard_lines, a_sources_merge)


def _run_groups(behavior_ok):
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    del FAILS[:]
    del SKIPS[:]
    for g in _BEHAVIOR:
        if not behavior_ok:
            skip(g.__name__, "mdcg-eval 可执行件不可得（构建命令：%s）" % _BUILD_CMD)
            continue
        try:
            g()
        except Exception as exc:                           # noqa: BLE001
            check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-700:])
    b_source_face()
    return len(FAILS)


def main():
    behavior_ok = _ensure_exe()
    if not behavior_ok:
        print("!! 行为面 SKIP：%s 不在场且无法自建 —— 构建命令：%s"
              % (EXE, _BUILD_CMD))
    n = _run_groups(behavior_ok)
    print()
    print("issue354 Rust 索引面守卫（P0-3 containment / P1-8 坏件不连坐）："
          "%d 通过，%d 失败，%d 跳过" % (PASS, n, len(SKIPS)))
    return 1 if n else 0


# ============================ [C] 定点变异自证 ============================

_MUTATIONS = (
    # 锚点用 ` 占位反引号（本文件构造时替换）——Rust 注释里的 markdown 反引号
    # 必须逐字进锚点，否则 ANCHOR-MISS 会让变异自证静默失效。
    ("V1 拆掉物理层 containment（只留词法层）",
     "    let Ok(ccand) = std::fs::canonicalize(&cand) else {\n"
     "        return PathGate::Unresolvable;\n"
     "    };\n"
     "    // `starts_with` 按**组件**比较，故 `<root>/../lib2` 一类的兄弟前缀不会被误判；\n"
     "    // `ccand == croot` 单列是因为 `Path::starts_with(自身)` 恒真，但显式写出更清楚。\n"
     "    if ccand == *croot || ccand.starts_with(croot) {\n"
     "        PathGate::Allowed(cand)\n"
     "    } else {\n"
     "        PathGate::OutOfRoot\n"
     "    }\n",
     "    PathGate::Allowed(root.join(p))",
     "B3", "B5b"),
    ("V2 坏行改判为整分片中断（回到坏行连坐）",
     "                let Ok(s) = std::str::from_utf8(chunk) else {\n"
     "                    continue; // 非法 UTF-8 行：只作废本行（不连坐同分片其余行）\n"
     "                };\n",
     "                let Ok(s) = std::str::from_utf8(chunk) else {\n"
     "                    break; // 变异：坏行连坐整分片\n"
     "                };\n",
     "A6"),
    ("V3 _index.json 解析失败臂改回 ? 传播（回到整装载 Err）",
     "                Err(e) => eprintln!(\n"
     "                    \"[store] _index.json 解析失败，降级跳过本源（issue #354 P1-8）：{}：{e}\",\n"
     "                    idx_json.display()\n"
     "                ),\n",
     "                Err(e) => return Err(format!(\"解析 _index.json 失败: {e}\")),\n",
     "B6b", "A5"),
)


def _rebuild():
    r = subprocess.run(["cargo", "build", "--release"], cwd=_RUST_DIR,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    return r.returncode == 0, (r.stderr or "")[-400:]


def _mutate():
    bad = []
    if not os.path.isfile(_STORE_RS):
        print("  SOURCE-MISSING：%s" % _STORE_RS)
        return 1
    if not shutil.which("cargo"):
        print("  NO-CARGO：变异自证需要 cargo（改源后必须重建，否则跑的还是旧二进制）")
        return 1
    with io.open(_STORE_RS, encoding="utf-8", newline="") as f:
        pristine = f.read()
    global _SILENT
    for name, anchor, repl, *want in _MUTATIONS:
        with io.open(_STORE_RS, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        ok_build = False
        try:
            with io.open(_STORE_RS, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            ok_build, blog = _rebuild()
            if not ok_build:
                print("  BUILD-FAIL %s：%s" % (name, blog))
                bad.append(name + "(构建失败)")
                continue
            _SILENT = True
            del _VIOL[:]
            _run_groups(True)
            reds = list(_VIOL)
            hit = [w for w in want if any(x.startswith(w) for x in reds)]
            print("  %-4s %-46s 红项=%-3d 命中=%s"
                  % ("OK" if len(hit) == len(want) else "BAD", name, len(reds),
                     ",".join(hit) if hit else "无"))
            if len(hit) != len(want):
                print("       期望红：%s；实红：%s" % (list(want), reds[:8]))
                bad.append(name)
        finally:
            _SILENT = False
            with io.open(_STORE_RS, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(_STORE_RS, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _rebuild()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


def _cleanup():
    for t in _SANDBOXES:
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        rc = _mutate()
        _cleanup()
        sys.exit(rc)
    rc = main()
    _cleanup()
    sys.exit(rc)
