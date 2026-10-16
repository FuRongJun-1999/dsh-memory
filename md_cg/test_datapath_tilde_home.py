# -*- coding: utf-8 -*-
r"""test_datapath_tilde_home.py · 波浪线展开判据的守卫（N117 分叉 + N167 先例，方案 a）

本守卫钉住三件事：

  ① **判据表**：`~` / `~/x` / `~\x`（Windows 分隔符形态，POSIX 上同判） / `~/a/../b`
     / `~//x` 展开到注入家目录。
  ② **过度收紧方向**（反向变异）：`~user` / `~abc` / `~ybyz/mem` / 合法相对路径 /
     绝对路径 / 空串 / 中段波浪线一律原样返回，**精确等于**「cwd 下同名相对路径」
     （不是「不以家目录开头」这种松判据——松判据在本次红态下也成立，等于无牙）。
  ③ **源码面「该判据只有一处实现」**：md_cg/ 与 scripts/ 下全部 .py（排除 `test_*.py`）
     中，同判据只允许出现在 `md_cg/datapath.py`；且 `_expand_home` 的调用点只有
     `_abs_host_path` 一处。反例（有牙自证）：临时目录里的人为第二处实现必须被报出，
     仅写在注释里的判据不得被报出。

**判据不自证**：期望值由本文件按注入的 HOME/USERPROFILE 与 `os.getcwd()` 自行拼出，
不调用 `_expand_home` 反推；`os.path.expanduser` 只用于「改前口径对照」的读数打印
与「守具有牙」的最低条件自检，不作为任何期望值的来源。

**方案 a 的实跑依据**（`~` 与 `~user` 的分界）：改前 python 侧走 `os.path.expanduser`，
同一台机器上 `posixpath.expanduser("~ybyz")` 与 `ntpath.expanduser("~ybyz")` 读数相反
（前者查不到账号即原样、后者不论账号是否存在都拼用户名）⇒ `~user` 形态两侧落点随
平台与账号而变。故把「两侧同留字面量」钉成不变量，才是可判定的口径。

隔离纪律：HOME / USERPROFILE / HOMEDRIVE / HOMEPATH 与四个 MDCG_* 覆盖键以 os.environ
副本注入、finally 逐键还原；家目录探针是 tempfile.mkdtemp 下的临时目录，测毕清理。
不触真实家目录、不触真实令牌库与真实状态根。

自检 floor：断言总数低于 FLOOR 视为失败——防「探针面失效 → 假绿」。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
import tempfile
import tokenize

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from .datapath import (ENV_AUX_ROOT, ENV_DATA_ROOT, ENV_MDCG_ROOT,
                       ENV_STATE_ROOT, _abs_host_path, _expand_home,
                       aux_root, data_root, mdcg_root, state_root)

# 断言总数下限（防假绿）。实测总数见 [6] 行的 total=（本批 35），留 ≥8 条余量。
FLOOR = 26
PASS, FAIL = 0, 0
BS = chr(92)                      # 反斜杠单字符（免去源文件里的转义歧义）

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_GUARD_KEYS = (ENV_STATE_ROOT, ENV_DATA_ROOT, ENV_MDCG_ROOT, ENV_AUX_ROOT,
               "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")

#: 同判据签名：「~/ 或 ~\ 前缀判据」与「裸 ~ 相等判据」两个条件同时成立。
_RE_PREFIX = re.compile(r"startswith\s*\(\s*['\"]~[\\/]['\"]\s*\)")
_RE_BARE = re.compile(r"==\s*['\"]~['\"]")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ok] " + name)
    else:
        FAIL += 1
        print("  [FAIL] " + name + "  " + detail)


def _code_of(src):
    """去掉 `#` 注释后的源码（字符串/文档串里的 `#` 由 tokenize 判定，不误切）。"""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
    return " ".join(t.string for t in toks if t.type != tokenize.COMMENT)


def _py_files(root):
    """root 下全部 .py（排除 test_*.py 与 .git/__pycache__/node_modules）。"""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "node_modules", "__pycache__")]
        for n in names:
            if n.endswith(".py") and not n.startswith("test_"):
                out.append(os.path.join(base, n))
    return sorted(out)


def tilde_judgement_sites(roots):
    """同判据实现点：命中 `_RE_PREFIX` 与 `_RE_BARE` 两个签名的 .py 路径。"""
    hits = []
    for root in roots:
        for path in _py_files(root):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    src = fh.read()
            except OSError:
                continue
            code = _code_of(src)
            if _RE_PREFIX.search(code) and _RE_BARE.search(code):
                hits.append(path)
    return sorted(hits)


def expand_home_call_sites(path):
    """path 内 `_expand_home(` 的**调用**行号（排除 `def _expand_home(` 自身）。"""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                              tokenize.INDENT, tokenize.DEDENT)]
    sites = []
    for i, t in enumerate(toks):
        if t.type != tokenize.NAME or t.string != "_expand_home":
            continue
        prev = toks[i - 1].string if i else ""
        nxt = toks[i + 1].string if i + 1 < len(toks) else ""
        if nxt == "(" and prev != "def":
            sites.append(t.start[0])
    return sites


def main():
    saved = {k: os.environ.get(k) for k in _GUARD_KEYS}
    tmp = tempfile.mkdtemp(prefix="mdcg_tilde_home_")
    # 家目录末段**必须等于 USERNAME**：ntpath.expanduser 只在
    # basename(USERPROFILE) == USERNAME 时才走 ~user 的猜测分支（其余情况原样
    # 返回）。注入成别的名字会让「改前口径」在 Windows 上不展开 ~user，本守卫
    # 随即失去牙（本文件 3d 就是这条最低条件的自检）。
    user_name = os.environ.get("USERNAME") or os.environ.get("USER") or "mdcg"
    home = os.path.join(tmp, user_name)
    cwd = os.getcwd()
    try:
        for k in _GUARD_KEYS:
            os.environ.pop(k, None)
        os.environ["HOME"] = home
        os.environ["USERPROFILE"] = home
        os.environ["USERNAME"] = user_name
        os.environ["HOMEDRIVE"] = ""
        os.environ["HOMEPATH"] = home

        # ---- 0. 注入生效自检：注入未生效则下面全部期望值失去意义 ----
        print("[0] 家目录注入自检")
        check("0a HOME/USERPROFILE 注入后 os.path.expanduser('~') == 注入值",
              os.path.expanduser("~") == home,
              "expanduser('~')=" + repr(os.path.expanduser("~")))

        # ---- 1. 判据表（正向：该展开的必须展开）----
        print("[1] 判据表：裸 ~ 与 ~/、~" + BS + " 前缀展开到注入家目录")
        forward = [
            ("裸 ~", "~", home),
            ("~/x", "~/x", os.path.join(home, "x")),
            ("~/（空余段）", "~/", home),
            ("~" + BS + "x（Windows 分隔符形态）", "~" + BS + "x",
             os.path.join(home, "x")),
            ("~/a/b", "~/a/b", os.path.join(home, "a", "b")),
            ("~/a/../b（归一）", "~/a/../b", os.path.join(home, "b")),
            ("~//x", "~//x", os.path.join(home, "x")),
            ("~" + BS + "user（分隔符形态，不是 ~user 形态）",
             "~" + BS + "user", os.path.join(home, "user")),
        ]
        for name, raw, expected in forward:
            check("1·" + name + " → 注入家目录", _abs_host_path(raw) == expected,
                  "实测=" + repr(_abs_host_path(raw)))
        # 1z：展开本身不做路径归一（当归一归 _abs_host_path）——多段余段原样拼接
        check("1z _expand_home 只展开不归一（余段原样拼接）",
              _expand_home("~/a/b") == home + os.sep + "a/b",
              "实测=" + repr(_expand_home("~/a/b")))

        # ---- 2. 过度收紧方向（反向变异：不得被当 home 处理）----
        print("[2] 过度收紧方向：非 home 形态精确等于 cwd 下同名相对路径")
        backward = ["~user", "~abc", "~ybyz/mem", "mem/x", "./mem", "../mem",
                    "/abs/x", "a/~b", "x~", "~~", ""]
        for raw in backward:
            got = _abs_host_path(raw)
            expected = (os.path.abspath(os.path.join(cwd, raw)) if raw
                        else os.path.abspath(""))
            check("2·" + repr(raw) + " 原样（等于 cwd 下同名路径）", got == expected,
                  "实测=" + repr(got) + " 期望=" + repr(expected))

        # ---- 3. 四个 env 入口实跑（覆盖键直设，paths.json 零参与）----
        print("[3] 四个 env 面：~/probe 落注入家目录；~user 形态落 cwd 下字面目录")
        for key, fn in ((ENV_STATE_ROOT, state_root), (ENV_DATA_ROOT, data_root),
                        (ENV_MDCG_ROOT, mdcg_root), (ENV_AUX_ROOT, aux_root)):
            os.environ[key] = "~/" + "probe"
            got = fn()
            check("3·" + key + "=~/probe → 注入家目录/probe",
                  got == os.path.join(home, "probe"), "实测=" + repr(got))
            os.environ[key] = "~ybyz" + "/" + "mem"
            got = fn()
            check("3·" + key + "=~ybyz/mem → 原样（cwd 下字面 ~ybyz 目录）",
                  got == os.path.join(cwd, "~ybyz", "mem"), "实测=" + repr(got))
            os.environ.pop(key, None)

        # ---- 3d. 守具有牙的最低条件：改前口径与新口径在本平台存在分歧 ----
        # 改前口径 = os.path.abspath(os.path.expanduser(p))（不改任何文件，纯读数）。
        # Windows 上 ~user 分歧（ntpath 不论账号是否存在都拼用户名）；
        # POSIX 上 ~\x 分歧（posixpath 把它当 ~user 查 pwd，查不到则原样保留）。
        print("[3d] 守具有牙的最低条件（改前口径 vs 新口径）")
        divergent = []
        for raw in ("~ybyz/mem", "~" + BS + "x", "~abc"):
            old = os.path.abspath(os.path.expanduser(raw))
            new = _abs_host_path(raw)
            print("     对照 " + repr(raw) + "：改前=" + repr(old) + " 改后=" + repr(new))
            if old != new:
                divergent.append(raw)
        check("3d 至少一个形态在新旧口径下读数不同（否则本平台无牙）",
              len(divergent) >= 1, "无分歧形态 ⇒ 守卫在本平台无牙")

        # ---- 4. 源码面唯一实现 + 反例 ----
        print("[4] 源码面「该判据只有一处实现」")
        sites = [os.path.relpath(p, REPO).replace(os.sep, "/")
                 for p in tilde_judgement_sites([os.path.join(REPO, "md_cg"),
                                                 os.path.join(REPO, "scripts")])]
        check("4a md_cg/ 与 scripts/ 下同判据恰一处，且是 md_cg/datapath.py",
              sites == ["md_cg/datapath.py"], "实测=" + repr(sites))
        calls = expand_home_call_sites(os.path.join(REPO, "md_cg", "datapath.py"))
        check("4b _expand_home 的调用点恰一处（_abs_host_path）",
              len(calls) == 1, "实测行号=" + repr(calls))

        fake = tempfile.mkdtemp(prefix="mdcg_tilde_fake_")
        try:
            # 反例①：人为加出的第二处实现 → 必须被报出
            with open(os.path.join(fake, "second_impl.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("import os\n\n"
                         "def expand_home_again(p):\n"
                         "    if p == \"~\":\n"
                         "        return os.path.expanduser(\"~\")\n"
                         "    if p.startswith(\"~/\") or p.startswith(\"~" + BS + BS + "\"):\n"
                         "        return os.path.expanduser(\"~\") + os.sep + p[2:]\n"
                         "    return p\n")
            # 反例②：仅注释/文档串里提到判据 → 不得被报出
            with open(os.path.join(fake, "comment_only.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("# 同判据先例：p == \"~\" 与 p.startswith(\"~/\")\n"
                         "VALUE = 1\n")
            fake_hits = [os.path.basename(p) for p in tilde_judgement_sites([fake])]
            check("4c 反例·第二处实现必须被报出",
                  fake_hits == ["second_impl.py"], "实测=" + repr(fake_hits))
            check("4d 反例·仅注释里的判据不得被报出",
                  "comment_only.py" not in fake_hits, "实测=" + repr(fake_hits))
        finally:
            shutil.rmtree(fake, ignore_errors=True)

        # ---- 6. 守卫自检 floor ----
        print("[6] 守卫自检")
        check("6a 断言总数 >= %d（防探针面失效假绿）" % FLOOR,
              PASS + FAIL >= FLOOR, "total=%d" % (PASS + FAIL))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== datapath tilde-home tests: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
