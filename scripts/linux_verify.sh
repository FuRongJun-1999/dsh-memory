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
         test_neg_condition_hits test_token_lowercase_form test_srcindex \
         test_logref test_p28_refcheck test_n225_nonobject_load \
         test_issue52_scan_condition_first; do
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
# N203 面（批次85 并入）：定点变异把落库判据改回「id 撞即跳」，须**恰好**命中 13 项
# （多一项少一项都报红）；锚点漂移＝退出码 2（fail-closed，不静默失效）。
# 注：缺 zstandard 时本守卫自判 SKIP 退出 0（对齐 run_tests 裸 clone 不假红口径）——
# 容器有 zstandard 时才真正跑出判别力，缺依赖时与其它日志面守卫同样静默跳过。
# P28 面（批次86 并入）：定点变异把 ref 巡检的快路径探测数据改回「水位条目」，
# 须**恰好**命中 3 项（A1 漏报 / B1 误报 / C1 篡改静默）；锚点漂移同样退出码 2。
# 同批次的【13】口径钉子（id 位置化 / 幂等判据由区间哈希承担 + 文档措辞·指纹·行级
# 引用同源）与【14】常驻循环止血（repeat_guard）两段**钉的是别的语义**，在该变异下
# 仍绿——故不入红项表（「恰好」二字靠这一点成立）；它们各自的判别力由就地定点探针
# 实测（改 node_id 成内容寻址 ⇒ F1/F2 红；改 §3.1 措辞 ⇒ F6 红；挪文档行级引用
# ⇒ F7 红；去掉 repeat_guard ⇒ G1/G3 红）。
# N225 面（批次87 并入）：三处定点变异——关掉装载面类型闸（_load_index 非对象视同
# 损坏）⇒ 恰好 25 项（A 组 20 + 端到端 D 组 5）；关掉 compact 面类型闸 ⇒ 恰好 16 项
# （B 组）；去掉分片日志坏行过滤 ⇒ 恰好 15 项（C 组 10 + D 组 5）。端到端面走独立
# 子进程，内存变异不跨进程，故由守卫经 PYTHONPATH 上的 sitecustomize 注入同一处
# 变异并以 stderr 标记自证（标记缺失即 D 组判红）。锚点漂移同样退出码 2。
# N225 补强批（2026-09-29）：原 E 组五条「源文本在场」断言（整组换空组仍 PASS，
# 零判别力）已整组删除，改由行为断言并按「一组一判据」重排——八处定点变异各自
# 恰好命中：装载面类型闸 ⇒ 25（A20+D5）；compact 面类型闸 ⇒ 16（B）；分片日志非
# 对象行过滤 ⇒ 14（C9+D5，C 组原 10 项中的「重放面 tombstone 语义」归 G 组）；
# 载荷坏型闸（e 非 dict 且非 None 跳过）⇒ 6（E）；载荷闸口径过宽（把 e is None 的
# tombstone 也当坏载荷）⇒ 2（G）；排序键归一（坏型槽记 0）⇒ 5（F）；tombstone 重放
# （e is None ⇒ pop）⇒ 2（G，与上条从过窄/过宽两侧钉同一口径）；read_jsonl 原样
# 产出 ⇒ 2（H）。锚点漂移同样退出码 2。
# issue #52 面（2026-10-03 并入）：八处定点变异（三处契约点名：条件过滤移回截断
# 之后 / 去掉 truncated 上报 / 截断选序改回字典序；另加 _scan 切片回退 / 默认值改
# 全量 / _sec 闸绕过 / 快照回退删分支 / layer 过滤失效）各自**恰好**命中预期条数
# （24/15/3/4/4/3/1/2），且无空转断言；锚点漂移＝退出码 2。另有 --legacy-baseline
# 重建修前形态（切片先于条件 + 无截断上报），断言须转红——抓得住 #52 本身。
for spec in "test_neg_condition_hits --head-baseline" \
            "test_neg_condition_hits --branch-baseline" \
            "test_policy_required_ccg --head-baseline" \
            "test_token_lowercase_form --head-baseline" \
            "test_logref --head-baseline" \
            "test_p28_refcheck --head-baseline" \
            "test_n225_nonobject_load --branch-baseline" \
            "test_issue52_scan_condition_first --branch-baseline" \
            "test_issue52_scan_condition_first --legacy-baseline"; do
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
