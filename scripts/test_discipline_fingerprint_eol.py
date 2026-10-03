# -*- coding: utf-8 -*-
"""test_discipline_fingerprint_eol —— 真源指纹跨平台一致性守卫（2026-10-03）。

背景：真源指纹曾按**检出形态的字节**直接摘要——autocrlf=true 的 Windows 工作区
（CRLF）与 Linux/CI 的 LF 检出对**同一提交**算出两个值（CRLF 版 e1e9112a409894aa /
LF 版 7bebb1c66a86f35b），陈化判据因此跨平台分裂：本机恒绿、CI 恒红（discipline-check
长期红）。修复＝ render_discipline.source_sha 在摘要前做 EOL 归一（CRLF/裸 CR → LF）；
verify_discipline 复用该单点（R.source_sha），故一处修复两面生效。

本守卫钉三件事：
  ① 归一生效：CRLF / 裸 CR / LF 混合形态的同一内容经 source_sha 得同一指纹
     （monkeypatch 临时真源，直接测实现）；
  ② 判别力：EOL 参与摘要的朴素算法与现行实现在对照样本上必分歧——若有人删掉
     归一，① 组与本组同时转红（两平台均成立，非仅 Windows 臂）；
  ③ 陈化面：7 个渲染产物内嵌的真源指纹 == 当前 source_sha（跨平台同判）。
"""
import hashlib
import io
import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import render_discipline as R  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name, ok, detail=""):
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        print("  PASS " + name)
    else:
        _FAIL += 1
        print("  FAIL " + name + ("  " + detail if detail else ""))


def _sha(b):
    return hashlib.sha256(b).hexdigest()[:16]


# 生效条件：b 为 bytes 时返回其 EOL 归一（CRLF/裸 CR → LF）后的 sha256 前 16 位；本条是
# **参考实现**（与被测实现分开写，避免自证循环），供对照断言用。
def _ref_sha_norm(b):
    return _sha(b.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


print("== ① 归一生效：CRLF / 裸 CR / LF 混合形态同一指纹（monkeypatch 临时真源）==")
_SAMPLE = b"{\r\n\"a\": 1,\r\"b\": 2\n}\n"  # CRLF + 裸 CR + LF 三形态混合
_fd, _tmp = tempfile.mkstemp(suffix=".json", prefix="disc_eol_")
os.close(_fd)
with open(_tmp, "wb") as fh:
    fh.write(_SAMPLE)
_orig = R.source_path
try:
    R.source_path = lambda repo: _tmp
    v = R.source_sha(".")
finally:
    R.source_path = _orig
    os.unlink(_tmp)
check("①a 混合形态归一后 = 全 LF 参考值（归一被删此处必红）",
      v == _ref_sha_norm(_SAMPLE), "got=%s want=%s" % (v, _ref_sha_norm(_SAMPLE)))

print("== ② 判别力：朴素算法（EOL 参与摘要）与现行实现必分歧 ==")
_raw = io.open(R.source_path(_REPO), "rb").read()
_cur = R.source_sha(_REPO)
_crlf_form = _raw if b"\r\n" in _raw else _raw.replace(b"\n", b"\r\n")
check("②a 现行指纹 == 参考归一值（与工作区检出形态无关）",
      _cur == _ref_sha_norm(_raw), "cur=%s ref=%s" % (_cur, _ref_sha_norm(_raw)))
check("②b CRLF 形态朴素摘要 != 现行指纹（两平台均成立）",
      _sha(_crlf_form) != _cur, "plain_crlf=%s cur=%s" % (_sha(_crlf_form), _cur))

print("== ③ 陈化面：7 个渲染产物内嵌指纹 == 当前真源指纹 ==")
_prods = [
    os.path.join("zcode", "AGENTS.md"),
    os.path.join("codex", "AGENTS.md"),
    os.path.join("claude", "CLAUDE.md"),
    os.path.join("codebuddy", "CODEBUDDY.md"),
    os.path.join(".codebuddy", "rules", "lingshu-discipline", "RULE.mdc"),
    os.path.join("claude", "lingshu-memory", "skills", "linglu-discipline", "SKILL.md"),
    os.path.join("codex", "lingshu-memory", "skills", "linglu-discipline", "SKILL.md"),
]
_pat = re.compile("前16位[）：:]* *([0-9a-f]{16})")  # 与 verify_discipline 的单点口径一致（覆盖 full/skill 两形态）
for rel in _prods:
    fp = os.path.join(_REPO, rel)
    txt = io.open(fp, encoding="utf-8", errors="replace").read()
    m = _pat.search(txt)
    check("③ %s 内嵌指纹 == 真源指纹" % rel.replace(os.sep, "/"),
          bool(m) and m.group(1) == _cur,
          "found=%s cur=%s" % (m.group(1) if m else None, _cur))

print("")
print("test_discipline_fingerprint_eol: %d 通过，%d 失败" % (_PASS, _FAIL))
if _FAIL:
    raise SystemExit(1)
print("ALL OK：指纹跨平台归一生效、判别力在、7 产物陈化面一致")
