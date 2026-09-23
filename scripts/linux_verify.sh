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
         test_wisdom_md_store; do
  out=$(python3 -m "md_cg.$t" 2>&1 | tail -1); rc=$?
  record "md_cg.$t" $rc
  echo "    -> $out"
done

for t in hive/test_orch.py hive/test_exec_tools.py hive/test_serve_entry.py; do
  out=$(python3 "$t" 2>&1 | tail -1); rc=$?
  record "$t" $rc
  echo "    -> $out"
done

if [ "$MODE" = "full" ]; then
  echo "=== smoke（D-2 Linux 口径：SIGTERM 收尾）==="
  HIVE_EXE="$CARGO_TARGET_DIR/release/hive" python3 -m hive.hive_mcp.smoke_test 2>&1 | tail -3
  record "smoke_test (linux)" $?
fi

echo "=== 汇总: $pass pass / $fail fail ==="
[ "$fail" -eq 0 ]
