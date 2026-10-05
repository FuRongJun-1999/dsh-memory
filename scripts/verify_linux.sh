#!/usr/bin/env bash
# 批次 33：Linux（Docker python:3.12）验证脚本——与 Windows 全量回归同口径。
# 用法：docker run --rm -v <repo>:/work -w /work python:3.12 bash scripts/verify_linux.sh
# 注：gate 串的 check_publish_artifact 段需 npm（容器无 node 时该段自判环境错误跳过）。
set -u
cd /work
pip install --quiet pyyaml 2>/dev/null || true
export PYTHONUTF8=1

echo "=== env ==="
python --version
uname -s

echo "=== python suites ==="
fail=0; pass=0
# N254（2026-10-05）：本脚本此前只有 set -u（无 set -e、无跨段聚合），末句是 echo → 进程
# 退出码**恒 0**；消费退出码的宿主（docker run … && 下一步）把「全失败」读成「成功」。
# 现复用同目录 scripts/linux_verify.sh:12-15 的既有单点 record，并以脚本末行
# `[ "$fail" -eq 0 ]` 传播退出码（下面 python 套件段就地累加的是同两个计数器）。
note() { echo "[$1] $2"; }
record() { # record <label> <exit>
  if [ "$2" -eq 0 ]; then pass=$((pass+1)); note "PASS" "$1"; else fail=$((fail+1)); note "FAIL" "$1"; fi
}
for t in test_hive_ingest test_p38_concurrent_flush test_p39_verify_flow \
         test_interop test_p29_session_ingest_export test_p2 test_p2_mcp \
         test_p3 test_p43_pooling test_retr_gates_prodpath test_retr_s1 \
         test_retr_s1b test_retr_s3 test_retr_s4 test_retr_s5 test_retr_s6 \
         test_retr_s7 test_readcache_prodpath test_mdstore_search_parity \
         test_govern_directread test_verify_dirty_reconcile \
         test_branch_discard_tombstone test_tail_watermark_race \
         test_links_concurrent_write \
         test_wisdom_md_store test_session_isolation test_access_hints \
         test_interop_judgment test_identity_attribution test_branches \
         test_p32_backfill test_i32_hotcache_env_key test_conformance \
         test_p47_session_view test_security_audit test_security_audit_b26 \
         test_security_audit_v21 test_p13_encryption \
         test_tasks test_reach test_transfer test_ccg_perturb \
         test_blindspot_tickets test_en_pipeline test_semantic_canonical \
         test_p1x_ref_root; do
  if python -m md_cg.$t >/dev/null 2>&1; then
    pass=$((pass+1))
  else
    echo "FAIL md_cg.$t"; fail=$((fail+1))
  fi
done
echo "python_suite pass=$pass fail=$fail"

echo "=== hive/scripts ==="
# N254：本段此前只 echo 退出码、不进聚合 → 该段全挂也不影响退出码。改用 record。
python hive/test_orch.py >/dev/null 2>&1;            record "hive/test_orch.py" $?
python hive/test_exec_tools.py >/dev/null 2>&1;      record "hive/test_exec_tools.py" $?
python hive/test_serve_entry.py >/dev/null 2>&1;     record "hive/test_serve_entry.py" $?
python scripts/test_judgment_manifest.py >/dev/null 2>&1; record "scripts/test_judgment_manifest.py" $?

echo "=== gate（Linux 口径：四段；cpa 需 npm，无则跳过） ==="
if command -v npm >/dev/null 2>&1; then
  python scripts/check_publish_artifact.py >/dev/null 2>&1; record "check_publish_artifact" $?
else
  echo "cpa=SKIP（容器无 npm——打包清单段由主机验证）"
  # SKIP 不判负，与 run_tests 的缺依赖自判 SKIP 同口径（不计 pass 也不计 fail）
fi
# A2（2026-10-05 使用者裁决）：认知图投影判据体必须在全部自动化面真的执行——此前无
# --cg-root 时 verify 静默 [SKIP] 退 0（判据体从未执行）。容器内没有本机认知图库，故先
# 用仓内既有 discipline_nodes.py 建最小库（root 不存在则建），再把路径显式交给验证腿。
python scripts/cogmap_sync.py check >/dev/null 2>&1 && \
python scripts/link_check.py >/dev/null 2>&1 && \
python scripts/workspace_index.py --check >/dev/null 2>&1 && \
python scripts/discipline_nodes.py --init --write --cg-root .tmp/discipline-cg >/dev/null 2>&1 && \
python scripts/verify_discipline.py --allow-missing --cg-root .tmp/discipline-cg >/dev/null 2>&1
record "gate4 (cogmap/link/index/discipline)" $?

echo "=== 汇总: $pass pass / $fail fail ==="
[ "$fail" -eq 0 ]
