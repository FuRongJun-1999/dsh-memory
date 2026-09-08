# -*- coding: utf-8 -*-
"""md_cg · P3 验收（#2 进程/权限 + #3 设备驱动）

运行：python -m md_cg.test_p3
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from .mdcos import MdCGSecure
from .security import Principal, TenantRegistry, AccessDenied
from .sources import JsonlSource, DSHSessionSource, Ingestor

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


CCG = ("# 功能名：{n}\n# 生效条件：问{n}\n# 子功能：{n}\n# 执行：{n}\n"
       "# 验证方式：test\n# 不适用条件：其它\n\n{n} 的内容\n")


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p3_")
    try:
        # ================= #2 权限模型 =================
        print("\n【#2-1】Principal / 密级")
        pub = Principal(tenant="public", actor="web", clearance="public")
        priv = Principal(tenant="private", actor="owner", clearance="private",
                         can_admin=True)
        check("public 只能看 public", pub.allows("public") and not pub.allows("internal"),
              f"clearance={pub.clearance}")
        check("private 能看 internal 与 private",
              priv.allows("internal") and priv.allows("private") and not priv.allows("secret"))

        print("\n【#2-2】写隔离")
        cg_pub = MdCGSecure(root, principal=pub)
        cg_pub.add("pub1", CCG.format(n="公开知识"), sensitivity="public")
        check("public 可写 public", cg_pub.get("pub1") is not None)
        denied = None
        try:
            cg_pub.add("pub2", CCG.format(n="内部知识"), sensitivity="internal")
        except AccessDenied as e:
            denied = str(e)
        check("public 写 internal 被拒", denied is not None, denied)
        denied2 = None
        try:
            MdCGSecure(root, principal=priv).add(
                "s1", CCG.format(n="机密"), sensitivity="secret")
        except AccessDenied as e:
            denied2 = str(e)
        check("clearance<secret 写 secret 被拒", denied2 is not None, denied2)

        print("\n【#2-3】读隔离（search / get 一致）")
        cg_priv = MdCGSecure(root, principal=priv)
        cg_priv.add("int1", CCG.format(n="内部条目"), sensitivity="internal")
        cg_priv.add("prv1", CCG.format(n="私有条目"), sensitivity="private")
        pub_again = MdCGSecure(root, principal=Principal(
            tenant="public", actor="web", clearance="public"))
        check("public 读不到 internal 节点", pub_again.get("int1") is None)
        check("public 读不到 private 节点", pub_again.get("prv1") is None)
        res_pub, _ = pub_again.search("条目", k=10)
        check("public 检索结果全部 public",
              all(r[0]["id"] == "pub1" for r in res_pub) and res_pub,
              f"{[r[0]['id'] for r in res_pub]}")
        res_priv, _ = cg_priv.search("条目", k=10)
        check("private 检索能看到 private 节点",
              any(r[0]["id"] == "prv1" for r in res_priv),
              f"{[r[0]['id'] for r in res_priv]}")
        rec = pub_again.recall("条目", budget_tokens=500)
        check("recall 同样受密级过滤",
              all(p["id"] == "pub1" for p in rec["pack"]),
              f"{[p['id'] for p in rec['pack']]}")

        print("\n【#2-4】管理隔离")
        adm_denied = None
        try:
            pub_again.forget("pub1", "试试")
        except AccessDenied as e:
            adm_denied = str(e)
        check("无 can_admin 的 forget 被拒", adm_denied is not None, adm_denied)

        print("\n【#2-5】租户注册表（公开/私有物理隔离）")
        reg_path = os.path.join(root, "_tenants.json")
        reg = TenantRegistry(reg_path)
        pub_root = os.path.join(root, "public-root")
        priv_root = os.path.join(os.path.expanduser("~"), ".mdcg", "private-root")
        reg.register("public", pub_root, clearance_cap="public",
                     description="开源仓库内：仅公开知识")
        reg.register("private", priv_root, clearance_cap="private",
                     description="仓库外：私有记忆")
        check("租户 root 注册", reg.root_of("public") == os.path.abspath(pub_root)
              and reg.root_of("private") == os.path.abspath(priv_root))
        p2 = reg.principal_for("public", clearance="secret")
        check("调用方 clearance 被租户上限夹紧", p2.clearance == "public", p2.clearance)
        check("公开根在仓库内 / 私有根在仓库外",
              os.path.abspath(pub_root).startswith(os.path.abspath(root))
              and not os.path.abspath(priv_root).startswith(os.path.abspath(root)))

        print("\n【#2-6】审计带 tenant/session")
        audits = cg_priv.audit_records()
        check("审计含 tenant", all("tenant" in a for a in audits), str(audits[-1])[:90])
        check("审计含 session", all("session" in a for a in audits), str(audits[-1])[:90])
        who = cg_priv.whoami()
        check("whoami 报告可见/总节点数", "nodes_visible" in who and "nodes_total" in who,
              json.dumps({k: who[k] for k in ("nodes_visible", "nodes_total")}))
        h = cg_priv.health_os()
        check("health_os 报告 security", "security" in h and "sensitivity_counts" in h["security"],
              json.dumps(h["security"], ensure_ascii=False)[:110])

        # ================= #3 设备驱动 =================
        print("\n【#3-1】JsonlSource")
        jl = os.path.join(root, "events.jsonl")
        with open(jl, "w", encoding="utf-8") as f:
            for i, (role, text) in enumerate([
                ("user", "跑测试"),
                ("tool-output", "Traceback (most recent call last):\nModuleNotFoundError: No module named 'zzz'"),
                ("assistant", "pip install zzz"),
                ("assistant", "再跑一次"),
            ]):
                f.write(json.dumps({"time": 1780000000000 + i * 1000, "seq": i,
                                    "role": role, "text": text,
                                    "session": "s1"}, ensure_ascii=False) + "\n")
        src = JsonlSource(jl)
        evs = list(src.events())
        check("JsonlSource 解析事件", len(evs) == 4, f"{len(evs)} 条")
        check("JsonlSource 保留 role/seq", evs[1]["role"] == "tool-output"
              and evs[1]["seq"] == 1, json.dumps(evs[1], ensure_ascii=False)[:80])

        print("\n【#3-2】DSHSessionSource（DSH 真实格式）")
        dsh_dir = os.path.join(root, "dsh-sess")
        os.makedirs(dsh_dir, exist_ok=True)
        dsh = os.path.join(dsh_dir, "session.jsonl")
        rows = [
            {"type": "session", "version": 0, "id": "session-abc", "createdAt": 1780000000000,
             "cwd": "D:/proj", "delegationDepth": 0, "agentPreset": "standard"},
            {"type": "user/message", "seq": 1, "time": 1780000001000,
             "data": {"content": [{"type": "text", "text": "帮我跑测试"}]}},
            {"type": "tool/call", "seq": 2, "time": 1780000002000,
             "data": {"turn": 1, "step": 1, "callId": "c1", "name": "bash",
                      "arguments": "{\"cmd\":\"npm test\"}"}},
            {"type": "tool/result", "seq": 3, "time": 1780000003000,
             "data": {"message": {"source": {"kind": "tool", "callId": "c1"},
                                  "content": [{"type": "tool-result", "toolCallId": "c1",
                                               "content": [{"type": "text",
                                                            "text": "Error: boom"}]}]}}},
            {"type": "assistant/message", "seq": 4, "time": 1780000004000,
             "data": {"turn": 1, "step": 1,
                      "message": {"role": "assistant", "content": [
                          {"type": "reasoning", "text": "想想"},
                          {"type": "text", "text": "npm install --save-dev foo"}]}}},
        ]
        with open(dsh, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        dsrc = DSHSessionSource(dsh)
        devs = list(dsrc.events())
        roles = [e["role"] for e in devs]
        check("DSH 源解析出 4 条消息事件", len(devs) == 4, f"{len(devs)} 条 roles={roles}")
        check("DSH 事件角色映射正确",
              roles == ["user", "command", "tool-output", "assistant"], str(roles))
        check("DSH reasoning 默认丢弃",
              "想想" not in (devs[-1]["text"] or ""), devs[-1]["text"][:60])
        check("DSH session/cwd 透传", devs[0]["session"] == "session-abc"
              and devs[0]["cwd"] == "D:/proj", f"{devs[0].get('session')} {devs[0].get('cwd')}")

        print("\n【#3-3】Ingestor 增量摄取 + 幂等 + 自动 fix-pair")
        ing_root = tempfile.mkdtemp(prefix="mdcg_ing_")
        try:
            ing_cg = MdCGSecure(ing_root, principal=Principal(
                tenant="private", actor="ing", clearance="private", can_admin=True))
            ing = Ingestor(ing_cg)
            r1 = ing.ingest(dsrc)
            check("摄取写入节点", r1["written"] == 4, json.dumps(
                {k: r1[k] for k in ("new_events", "written")}, ensure_ascii=False))
            check("watermark 已记录", ing.watermark(dsrc.key()).get("seq") == 4,
                  json.dumps(ing.watermark(dsrc.key()), ensure_ascii=False))
            check("自动 fix-pair 挖掘触发", "fix_pairs" in r1 and r1["fix_pairs"]["pairs"],
                  json.dumps(r1.get("fix_pairs", {}).get("pairs"), ensure_ascii=False)[:100])
            r2 = ing.ingest(dsrc)
            check("重复摄取幂等（无新增）", r2["new_events"] == 0 and r2["written"] == 0,
                  json.dumps({k: r2[k] for k in ("new_events", "written")}))
            # 追加一条新事件 → 只增量摄取它
            with open(dsh, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user/message", "seq": 5, "time": 1780000005000,
                                    "data": {"content": [{"type": "text", "text": "继续"}]}},
                                   ensure_ascii=False) + "\n")
            r3 = ing.ingest(dsrc)
            check("增量只摄取新事件", r3["new_events"] == 1 and r3["written"] == 1,
                  json.dumps({k: r3[k] for k in ("new_events", "written")}))
            # 敏感度：会话默认 private
            any_id = r1["ids"][0]
            node = ing_cg.get(any_id)
            check("会话节点默认敏感度 private",
                  (node["frontmatter"].get("sensitivity") == "private"), str(
                      node["frontmatter"].get("sensitivity")))
            check("会话节点落 contextual 层",
                  node["frontmatter"].get("layer") == "contextual",
                  str(node["frontmatter"].get("layer")))
            # 公开调用方看不到会话记忆
            pub_view = MdCGSecure(ing_root, principal=Principal(
                tenant="public", actor="web", clearance="public"))
            check("public 调用方看不到私有会话记忆",
                  pub_view.get(any_id) is None and not pub_view.search("测试", k=5)[0])
        finally:
            shutil.rmtree(ing_root, ignore_errors=True)

        print("\n【#3-4】真实 DSH 会话（可选：zstd 可用时）")
        try:
            import zstandard  # noqa: F401
            files = DSHSessionSource.discover(limit=3)
            if files:
                ok = 0
                for p in files:
                    try:
                        n = len(list(DSHSessionSource(p).events()))
                        ok += 1 if n > 0 else 0
                    except Exception:      # noqa: BLE001
                        pass
                check("真实 DSH 会话可解析", ok > 0, f"{ok}/{len(files)} 个会话有事件")
            else:
                check("真实 DSH 会话可解析", True, "本机无会话文件（跳过）")
        except ImportError:
            check("真实 DSH 会话可解析", True, "zstandard 不可用（优雅跳过）")

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
