# -*- coding: utf-8 -*-
"""N123 攻击复现守卫：derive 子令牌 TTL 无上限夹紧 + 过期不沿派生链传播。

缺陷（v15 留档 + 引擎域/检索域复测三度成立）：
  ① derive() 子令牌 expires_at=(now+ttl) 不与父 expires_at 取 min——
     父 ttl=0.5s、子 ttl=999999 时子比父多活 11.5 天；
  ② verify_token 只查自身记录 expires_at——父令牌过期后子令牌仍以原密级通过。
攻击面：持 delegable designer 令牌面（宿主进程/提示注入驱动 derive）先派生
长 TTL 子令牌再令父令牌自然到期——授权回收被时间维度旁路（revoke 有级联
tokens.py:523-526，唯过期没有，「派生只能收窄」缺时间维度）。

修复方向：子 expires_at=min(请求值, 父 expires_at)（父无界取请求值）
+ verify_token 沿 parent 链传播过期校验（防环；父记录缺失告警不阻断）。

运行：python -m md_cg.test_n123_derive_expiry_chain
纪律：全程 MDCG_TOKEN_FILE / path= 指向系统临时目录哑令牌文件，不触真实令牌库。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

from . import tokens
from .tokens import TOKEN_FILE_ENV, TokenError

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def denied(fn, *a, **kw):
    """执行 fn，返回 (是否被拒, 错误文本)。"""
    try:
        fn(*a, **kw)
        return False, ""
    except TokenError as e:
        return True, str(e)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = tempfile.mkdtemp(prefix="mdcg_n123_")
    tf = os.path.join(root, "_tokens.json")
    # 哑环境兜底：即使代码内部遗漏 path= 也绝不回落到真实 ~/.mdcg 令牌库
    old_env = os.environ.get(TOKEN_FILE_ENV)
    os.environ[TOKEN_FILE_ENV] = tf
    try:
        # ========== 攻击复现 ①：derive 长 TTL 子令牌不被父界夹紧 ==========
        print("\n[1] derive 夹紧：子 expires_at = min(请求值, 父 expires_at)")
        d = tokens.issue("designer", actor="n123-designer", ttl=3600.0, path=tf)
        child = tokens.derive(d["token"], "record", actor="n123-child",
                              ttl=999999.0, path=tf)
        dexp = d["expires_at"]
        cexp = child["expires_at"]
        check("子令牌过期时间不超过父令牌", cexp is not None and dexp is not None
              and float(cexp) <= float(dexp) + 1e-6,
              f"child-parent={float(cexp) - float(dexp):.1f}s（旧代码 +999639s）")
        check("夹紧开口 clamped 标注 expires_at",
              "expires_at" in (child.get("clamped") or []),
              f"clamped={child.get('clamped')}")

        # ========== 攻击复现 ②：父过期后子令牌沿链拒验（免 sleep：手工置父已过期） ==========
        print("\n[2] verify 沿链传播：父记录过期 → 子令牌拒绝")
        data = json.load(open(tf, encoding="utf-8"))
        data["tokens"][d["token_id"]]["expires_at"] = time.time() - 1.0
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        ok_p, why_p = denied(tokens.verify_token, d["token"], path=tf)
        ok_c, why_c = denied(tokens.verify_token, child["token"], path=tf)
        check("父令牌过期被拒（基线，旧代码即拦）", ok_p, why_p[:60])
        check("父过期后子令牌沿链拒验（N123 核心断言）", ok_c, why_c[:60])

        # ========== 攻击复现 ③：真实自然到期端到端 ==========
        print("\n[3] 端到端：父 ttl=0.4 自然到期 → 长 TTL 子令牌（ttl=999999）失效")
        d3 = tokens.issue("designer", actor="n123-e2e", ttl=0.4, path=tf)
        c3 = tokens.derive(d3["token"], "record", actor="n123-e2e-child",
                           ttl=999999.0, path=tf)
        check("派生时子界已被父夹紧",
              float(c3["expires_at"]) <= float(d3["expires_at"]) + 1e-6,
              f"child={c3['expires_at']:.1f} parent={d3['expires_at']:.1f}")
        time.sleep(0.7)
        ok_p3, why_p3 = denied(tokens.verify_token, d3["token"], path=tf)
        ok_c3, why_c3 = denied(tokens.verify_token, c3["token"], path=tf)
        check("父自然到期被拒", ok_p3, why_p3[:60])
        check("子令牌随父到期失效（修复前：verify OK 继续用）", ok_c3, why_c3[:60])

        # ========== 正向 ④：父无界时取请求值（不误夹成无界/不过度收窄） ==========
        print("\n[4] 父无界：子 TTL 取请求值")
        d4 = tokens.issue("designer", actor="n123-bounded", path=tf)  # 无 ttl
        check("父无界 expires_at=None", d4["expires_at"] is None)
        c4 = tokens.derive(d4["token"], "record", actor="n123-bounded-child",
                           ttl=60.0, path=tf)
        now = time.time()
        check("父无界时子 expires_at=now+60（取请求值）",
              c4["expires_at"] is not None
              and 58.0 <= float(c4["expires_at"]) - now <= 62.0,
              f"delta={float(c4['expires_at']) - now:.1f}s")
        check("父无界夹紧不开口",
              "expires_at" not in (c4.get("clamped") or []),
              f"clamped={c4.get('clamped')}")
        # 子短于父：取请求值不延长
        c4b = tokens.derive(d4["token"], "record", actor="n123-short", ttl=1.0,
                            path=tf)
        check("子短于父取请求值", c4b["expires_at"] is not None
              and float(c4b["expires_at"]) - now <= 2.0)
        # 子无 ttl：沿用父（旧行为保持——父无界即无界）
        c4c = tokens.derive(d4["token"], "record", actor="n123-inherit", path=tf)
        check("子未指定 ttl 沿用父界（无界父→无界子）",
              c4c["expires_at"] is None, f"expires_at={c4c['expires_at']}")

        # ========== 正向 ⑤：子自身先到期仍按自身拒（不因沿链放宽） ==========
        print("\n[5] 子自身过期仍拦截")
        d5 = tokens.issue("designer", actor="n123-self", ttl=3600.0, path=tf)
        c5 = tokens.derive(d5["token"], "record", actor="n123-self-child",
                           ttl=0.05, path=tf)
        time.sleep(0.15)
        ok_c5, why_c5 = denied(tokens.verify_token, c5["token"], path=tf)
        ok_d5, _ = denied(tokens.verify_token, d5["token"], path=tf)
        check("子自身先到期被拒", ok_c5 and not ok_d5, why_c5[:60])

        # ========== 加固 ⑥：存量库三层链 + 防环 ==========
        print("\n[6] 存量库三层链传播 + parent 环防护")
        # 三层链：gp（无界）→ p（已过期）→ gc；修复前 verify(gc) 只看自身 → OK
        d6 = tokens.issue("designer", actor="n123-gp", path=tf)
        p6 = tokens.derive(d6["token"], "orchestr", actor="n123-p", path=tf)
        # 手工构造第三层（正常 derive 封口 delegable=False，模拟存量库/手工库）
        data6 = json.load(open(tf, encoding="utf-8"))
        prec = data6["tokens"][p6["token_id"]]
        gc_id = "tk_n123gc01"
        data6["tokens"][gc_id] = dict(prec, role="record", actor="n123-gc",
                                      delegable=False, parent=p6["token_id"],
                                      expires_at=time.time() + 999999.0)
        data6["tokens"][p6["token_id"]]["expires_at"] = time.time() - 1.0
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(data6, f, ensure_ascii=False)
        gc_token = tokens.make_token("record", gc_id, "x" * 43)
        # 摘要需匹配：直接改库中 hash
        data6 = json.load(open(tf, encoding="utf-8"))
        data6["tokens"][gc_id]["hash"] = tokens._hash("x" * 43)
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(data6, f, ensure_ascii=False)
        t0 = time.monotonic()
        ok_gc, why_gc = denied(tokens.verify_token, gc_token, path=tf)
        cost = time.monotonic() - t0
        check("中间层过期 → 孙令牌沿链拒验", ok_gc, why_gc[:60])
        check("沿链校验无死循环（<2s）", cost < 2.0, f"{cost:.3f}s")
        # 防环：A.parent=B 且 B.parent=A，均未过期 → 应通过且不挂
        data6 = json.load(open(tf, encoding="utf-8"))
        a_id, b_id = "tk_n123loopA", "tk_n123loopB"
        data6["tokens"][a_id] = {"role": "designer", "actor": "loop-a",
                                 "tenant": "default", "clearance": "secret",
                                 "can_write": True, "can_admin": True,
                                 "layers_allow": ["*"], "ops_allow": ["*"],
                                 "delegable": False, "parent": b_id,
                                 "issued_by": "loop", "issued_at": now,
                                 "expires_at": None, "revoked_at": None,
                                 "label": "", "hash": tokens._hash("la" * 16)}
        data6["tokens"][b_id] = {"role": "record", "actor": "loop-b",
                                 "tenant": "default", "clearance": "internal",
                                 "can_write": True, "can_admin": False,
                                 "layers_allow": None, "ops_allow": None,
                                 "delegable": False, "parent": a_id,
                                 "issued_by": "loop", "issued_at": now,
                                 "expires_at": None, "revoked_at": None,
                                 "label": "", "hash": tokens._hash("lb" * 16)}
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(data6, f, ensure_ascii=False)
        t0 = time.monotonic()
        try:
            tokens.verify_token(tokens.make_token("designer", a_id, "la" * 16),
                                path=tf)
            loop_ok = True
        except TokenError:
            loop_ok = True          # 拒绝也可（fail-closed），关键是不挂
        cost = time.monotonic() - t0
        check("parent 环不挂死（防环）", loop_ok and cost < 2.0, f"{cost:.3f}s")
    finally:
        if old_env is None:
            os.environ.pop(TOKEN_FILE_ENV, None)
        else:
            os.environ[TOKEN_FILE_ENV] = old_env
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
