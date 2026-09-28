#!/usr/bin/env bash
# Linux 验证脚本（Docker 容器内跑）：cargo + python 十套 + encoding 守卫。
# 用法：docker run --rm -v <repo>:/work -w /work rust:bookworm bash scripts/linux_verify.sh [full|core]
# CARGO_TARGET_DIR 默认 /tmp/target——与 Windows 侧 target/ 隔离，互不污染。
set -u
set -o pipefail
MODE="${1:-core}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/target}"
export PYTHONUTF8=1

pass=0; fail=0
note() { echo "[$1] $2"; }
record() { # record <label> <exit>
  if [ "$2" -eq 0 ]; then pass=$((pass+1)); note "PASS" "$1"; else fail=$((fail+1)); note "FAIL" "$1"; fi
}

echo "=== 环境 ==="
python3 --version; cargo --version

echo "=== rust: cargo test ==="
( cd hive && cargo test --quiet 2>&1 | tail -4 )
record "cargo test" $?

if [ "$MODE" = "full" ]; then
  echo "=== rust: cargo build --release（smoke 前置）==="
  ( cd hive && cargo build --release --quiet 2>&1 | tail -3 )
  record "cargo build --release" $?
  # smoke_test 的 EXE 探测点硬编码 <repo>/hive/target/release/hive——把隔离编译
  # 产物拷到该处（target/ 在 .gitignore 内，不污染 git 工作区）
  if [ -f "$CARGO_TARGET_DIR/release/hive" ]; then
    mkdir -p hive/target/release
    cp "$CARGO_TARGET_DIR/release/hive" hive/target/release/hive
  fi
fi

echo "=== python 套件 ==="
# 批次 22（issue #31 发版门禁）：补齐批次 14-22 新守卫——门控生产路径/
# 读缓存/MdStore 预计算逐位对照/p43 回流守恒。依赖 gitignored 本地语料的
# 套件（p44/md_access_parity）不入清单（容器内必缺，由 run_tests SKIP 面
# 在有语料的机器覆盖）。
for t in test_hive_ingest test_p38_concurrent_flush test_p39_verify_flow \
         test_interop test_subproc_encoding \
         test_p29_session_ingest_export test_p2 test_p2_mcp test_p3 \
         test_p43_pooling test_retr_gates_prodpath \
         test_readcache_prodpath test_mdstore_search_parity \
         test_rejected_redact test_rejected_credential_forms test_ccg_form_parity test_wisdom_md_store \
         test_neg_condition_hits test_token_lowercase_form test_srcindex; do
  out=$(python3 -m "md_cg.$t" 2>&1 | tail -1); rc=$?
  record "md_cg.$t" $rc
  echo "    -> $out"
done

for t in hive/test_orch.py hive/test_exec_tools.py hive/test_serve_entry.py \
         hive/test_result_anchor_chain.py; do
  out=$(python3 "$t" 2>&1 | tail -1); rc=$?
  record "$t" $rc
  echo "    -> $out"
done

echo "=== 断言判别力自证（退出码 0 = 变异后如预期转红）==="
# 自证型守卫的「变异必须转红」模式并进验证入口：判别力靠人工核验一次会陈化，
# 前车之鉴是批次76 的「整条命中档」删掉后 31 条断言原样全绿（独立复核 2026-09-28）。
for spec in "test_neg_condition_hits --head-baseline" \
            "test_neg_condition_hits --branch-baseline" \
            "test_policy_required_ccg --head-baseline" \
            "test_token_lowercase_form --head-baseline"; do
  set -- $spec
  out=$(python3 -m "md_cg.$1" "$2" 2>&1 | tail -1); rc=$?
  record "md_cg.$1 $2" $rc
  echo "    -> $out"
done
# hive 面自证（批次81 并入）：锚面折小写 / 身份面不折的两侧口径由 [F] 组钉死，
# 变异（关掉折小写）须恰好命中 7 项，否则红基线失效即报红
for spec in "hive.test_result_anchor_chain --head-baseline"; do
  set -- $spec
  out=$(python3 -m "$1" "$2" 2>&1 | tail -1); rc=$?
  record "$1 $2" $rc
  echo "    -> $out"
done

if [ "$MODE" = "full" ]; then
  echo "=== smoke（D-2 Linux 口径：SIGTERM 收尾）==="
  HIVE_EXE="$CARGO_TARGET_DIR/release/hive" python3 -m hive.hive_mcp.smoke_test 2>&1 | tail -3
  record "smoke_test (linux)" $?
fi

echo "=== 汇总: $pass pass / $fail fail ==="
[ "$fail" -eq 0 ]
