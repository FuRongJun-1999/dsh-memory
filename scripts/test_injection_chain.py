#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注入面发现与防重复（Pi⑦⑤）自检。

依据：宿主注入件**不是单点读取**——它从启动目录逐级上溯读同名件，故「产物落在哪」不等于
「宿主只读到这一份」。四层覆盖：
  A 判据输入：路径归一化、槽位声明完备（承诺项必须有守卫）、指纹提取
  B 链走法  ：到盘根、stop 含入、目录级别名折叠（防重复的真实落点，junction 实证）
  C 裁决面  ：祖先链标注、path_dup / root_shadow 硬失败、防重复**反面**（同仓不同物理件只标注）
  D 真矩阵  ：本仓 harnesses.yaml 必须全绿（回归入口）

跑法：python scripts/test_injection_chain.py   （0 = 全绿，1 = 有失败）
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import render_discipline as R      # noqa: E402
import verify_discipline as V      # noqa: E402

_PASS, _FAIL, _SKIP = [], [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  ok    " + name)
    else:
        _FAIL.append(name)
        print("  FAIL  " + name + ("   <- " + str(detail)[:300] if detail else ""))


def skip(name, why):
    _SKIP.append(name)
    print("  skip  " + name + "   <- " + why)


def case(title):
    print("\n[" + title + "]")


def _write(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def _mx(slots, root_allow=None, chain_scope="filesystem", targets=None):
    return {"injection": {"version": 1, "slots": slots, "root_allow": root_allow or [],
                          "chain_scope": chain_scope},
            "targets": targets or {}}


def _junction(dest, target):
    """建目录 junction（Windows /J 不需管理员权限）；失败返回 False。"""
    try:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", dest, target], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and os.path.isdir(dest)


def _nc(path):
    return os.path.normcase(os.path.normpath(path))


def case_a():
    case("A 判据输入（归一化 / 槽位声明 / 指纹）")
    root_md = os.path.join(_REPO, "AGENTS.md")
    check("A1 norm_path 归一 `..` 脏路径",
          R.norm_path(os.path.join(_REPO, "docs", "..", "AGENTS.md")) == R.norm_path(root_md))
    if os.name == "nt":
        check("A2 norm_path 大小写不敏感（Windows）",
              R.norm_path(os.path.join(_REPO, "agents.MD")) == R.norm_path(root_md))
    check("A3 _under 按分量比较：前缀同名目录不误判", not R._under(_REPO + "-x", _REPO))
    check("A4 _under 含自身与子目录",
          R._under(_REPO, _REPO) and R._under(os.path.join(_REPO, "docs"), _REPO))

    mx = R.load_matrix(_REPO)
    conf = R.injection_conf(mx)
    slots = conf.get("slots") or {}
    targets = mx.get("targets", {})
    check("A5 真矩阵声明了注入面段", bool(conf))
    check("A6 槽位读取有序（codebuddy-session）",
          R.slot_files(mx, "codebuddy-session") == ["CODEBUDDY.md", "AGENTS.md"],
          R.slot_files(mx, "codebuddy-session"))
    check("A7 无文件竞争面的槽位显式声明为空（config 注入）",
          R.slot_files(mx, "system-prompt-key") == [])
    check("A8 未声明槽位返回空（不猜）", R.slot_files(mx, "不存在的槽位") == [])
    check("A9 指纹提取 / 无指纹判 None",
          R.artifact_sha("…… 前16位：0123456789abcdef ……") == "0123456789abcdef"
          and R.artifact_sha("无指纹的手工件") is None)

    # 承诺项守卫：新增 target 忘声明 slot → 静默不在发现面（= 无守卫的承诺）
    check("A10 每个 target 都声明了 slot",
          not [n for n, t in targets.items() if not t.get("slot")],
          [n for n, t in targets.items() if not t.get("slot")])
    check("A11 slot 已在 injection.slots 登记",
          not [n for n, t in targets.items() if t.get("slot") and t["slot"] not in slots],
          [n for n, t in targets.items() if t.get("slot") and t["slot"] not in slots])
    used = {t.get("slot") for t in targets.values()}
    check("A12 无死槽位声明（防漂移）", not [k for k in slots if k not in used],
          [k for k in slots if k not in used])
    bad_self = [n for n, t in targets.items() if t.get("transport") == "file"
                and os.path.basename(R.expand(t["path"], _REPO)) not in (slots.get(t.get("slot")) or [])]
    check("A13 每端产物名在其槽位清单内（否则遮蔽判定失真）", not bad_self, bad_self)


def case_b():
    case("B 链走法（盘根 / stop / 目录别名折叠）")
    base = tempfile.mkdtemp(prefix="dsh_inj_b_")
    junc = None
    try:
        repo = os.path.join(base, "repo")
        self_file = _write(os.path.join(repo, "a", "AGENTS.md"), "self\n")
        chain = R.ancestor_dirs(self_file)
        check("B1 起点 = 文件所在目录", chain[0] == os.path.join(repo, "a"))
        check("B2 顺序最近 → 最远", chain.index(repo) > chain.index(os.path.join(repo, "a")))
        check("B3 缺省一路到盘根", os.path.dirname(chain[-1]) == chain[-1], chain[-3:])
        scoped = R.ancestor_dirs(self_file, stop=repo)
        check("B4 stop 含入链并就地停止", scoped[-1] == repo and repo in scoped, scoped[-2:])

        # 防重复落点：junction 自指段让同一**物理**目录在**词法**链上出现两次
        junc = os.path.join(repo, "j")
        if not _junction(junc, repo):
            skip("B5/B6 目录别名折叠", "本环境 mklink /J 不可用")
        else:
            j2 = os.path.join(junc, "j")
            if R.norm_path(j2) != R.norm_path(repo):
                skip("B5/B6 目录别名折叠", "realpath 未解析 junction（环境不支持）")
            else:
                dirs, alias = R._walk_ancestors(os.path.join(j2, "AGENTS.md"))
                check("B5 同一物理目录在链上只查一次（别名被折叠）", len(alias) >= 1,
                      {"dirs": dirs[:4], "alias": alias[:3]})
                check("B6 折叠记录指向先出现的拼写",
                      bool(alias) and all(R.norm_path(a["dir"]) == R.norm_path(a["alias_of"]) for a in alias),
                      alias[:3])
    finally:
        if junc and os.path.isdir(junc):
            os.rmdir(junc)          # 只删链接，不动目标目录
        shutil.rmtree(base, ignore_errors=True)


def case_c():
    case("C 发现面与硬判据")
    base = tempfile.mkdtemp(prefix="dsh_inj_c_")
    try:
        repo = os.path.join(base, "repo")
        self_file = _write(os.path.join(repo, "a", "AGENTS.md"), "self\n")
        _write(os.path.join(repo, "AGENTS.md"), "repo-root\n")
        _write(os.path.join(base, "AGENTS.md"), "outside\n")
        t = {"enabled": True, "transport": "file", "slot": "zcode-session",
             "path": self_file}
        mx = _mx({"zcode-session": ["AGENTS.md"]}, targets={"t": t})

        ch = R.discover_injection_chain(t, repo, mx)
        by = {_nc(h["path"]): h for h in ch["hits"]}
        hit_repo = by.get(_nc(os.path.join(repo, "AGENTS.md")))
        hit_out = by.get(_nc(os.path.join(base, "AGENTS.md")))
        check("C1 槽位与竞争文件清单", ch["slot"] == "zcode-session" and ch["files"] == ["AGENTS.md"])
        check("C2 仓内命中标注 tier/同名/rank/self_rank",
              bool(hit_repo) and hit_repo["tier"] == "repo" and hit_repo["same_name"]
              and hit_repo["rank"] == 0 and hit_repo["self_rank"] == 0, hit_repo)
        check("C3 仓外命中被看见（宿主侧事实，不裁决）",
              bool(hit_out) and hit_out["tier"] == "outside", hit_out)
        check("C4 自身不入 hits",
              all(_nc(h["path"]) != _nc(self_file) for h in ch["hits"]), ch["hits"])
        ch2 = R.discover_injection_chain(t, repo, mx, scope="repo")
        check("C5 chain_scope=repo 只报仓内",
              bool(ch2["hits"]) and all(h["tier"] == "repo" for h in ch2["hits"]),
              [h["path"] for h in ch2["hits"]])
        check("C6 未声明槽位 → 整体跳过（不猜）",
              R.discover_injection_chain(dict(t, slot=None), repo, mx)["slot"] is None)
        check("C7 config-key 目标不参与链发现",
              R.discover_injection_chain(dict(t, transport="config-key"), repo, mx)["slot"] is None)

        dup = _mx({"zcode-session": ["AGENTS.md"]}, targets={
            "t1": {"enabled": True, "transport": "file", "slot": "zcode-session", "path": "a/AGENTS.md"},
            "t2": {"enabled": True, "transport": "file", "render": False, "slot": "zcode-session",
                   "path": os.path.join(repo, "a", "..", "a", "AGENTS.md")}})
        d = V.check_injection_matrix(dup, repo, ["t1", "t2"], probe_chain=False)
        check("C8 同一物理文件被两个 target 写 → 硬失败",
              (not d["ok"]) and len(d["path_dups"]) == 1, d)
        check("C9 点名 render:false 手工件（手改会被渲染覆盖）",
              bool(d["path_dups"]) and d["path_dups"][0]["manual"] == ["t2"], d["path_dups"])

        sh = _mx({"zcode-session": ["CODEBUDDY.md", "AGENTS.md"]}, root_allow=["AGENTS.md"],
                 targets={"t": dict(t, slot="zcode-session")})
        shadow_file = _write(os.path.join(repo, "CODEBUDDY.md"), "shadow\n")
        s = V.check_injection_matrix(sh, repo, ["t"], probe_chain=False)
        check("C10 仓根遮蔽本地私有件 → 硬失败", (not s["ok"]) and len(s["root_shadow"]) == 1, s)
        check("C11 指认赢家/输家",
              bool(s["root_shadow"]) and s["root_shadow"][0]["winner"] == "CODEBUDDY.md"
              and s["root_shadow"][0]["loser"] == "AGENTS.md", s["root_shadow"])
        os.remove(shadow_file)
        ok = V.check_injection_matrix(sh, repo, ["t"], probe_chain=False)
        check("C12 移除仓根遮蔽件即恢复绿", ok["ok"] and not ok["root_shadow"])

        # 防重复的**反面**：同仓同相对路径但物理不同 = 两份真实注入源 → 只标注，绝不折叠
        orig = R.git_identity
        try:
            R.git_identity = lambda p: ("G:/fake/.git", "AGENTS.md")
            ch3 = R.discover_injection_chain(t, repo, mx)
        finally:
            R.git_identity = orig
        wt = ch3["wt_dups"]
        check("C13 同仓不同物理件只标 wt_dups 不折叠（折叠会藏起真实重复源）",
              bool(wt) and _nc(wt[0]["path"]) == _nc(os.path.join(base, "AGENTS.md"))
              and _nc(wt[0]["alias_of"]) == _nc(os.path.join(repo, "AGENTS.md")), wt[:2])
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_d():
    case("D 真矩阵回归（本仓）")
    mx = R.load_matrix(_REPO)
    names = [n for n, t in mx.get("targets", {}).items() if t.get("enabled")]
    res = V.check_injection_matrix(mx, _REPO, names, probe_chain=False)
    check("D1 本仓注入面硬判据全绿", res["ok"],
          {"path_dups": res["path_dups"], "root_shadow": res["root_shadow"]})
    res2 = V.check_injection_matrix(mx, _REPO, names, probe_chain=True)
    check("D2 祖先链发现可跑（逐 target 走链）", res2["probed"] > 0, res2["probed"])
    check("D3 链发现不改变硬判据结论", res2["ok"] == res["ok"])


def main():
    print("注入面发现与防重复（Pi⑦⑤）自检 —— repo=%s" % _REPO)
    case_a()
    case_b()
    case_c()
    case_d()
    print("\n结果：通过 %d / 失败 %d / 跳过 %d" % (len(_PASS), len(_FAIL), len(_SKIP)))
    if _FAIL:
        print("失败项：" + "; ".join(_FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

