# -*- coding: utf-8 -*-
"""统一配置层 · 值域/类型校验器（**生成件**，勿手改）。
由 `md_cg/config_render.py::render_validator` 生成。真源 = `md_cg/config_registry.py`（+ 生成件 `config_registry_bulk.py`）。
"""
from __future__ import annotations

import sys

from . import autonomy_modes as _am
from . import sleep as _sl

# 这两个键的**名字**取自既有真源表（既有守卫禁止第二处 env 名字面量；
# 见 md_cg/test_sleep_p1.py::g8 / md_cg/test_autonomy_modes.py::g_g）。
_ENV_SLEEP_MERGE = _sl.SLEEP_ENV_KEYS["merge"]
_ENV_AUTONOMY_MODE = _am.AUTONOMY_ENV_KEYS["mode"]

#: 参数名/env 名 → 校验规则（只登记已知约束，未列者不臆造）
RULES = {
    'AEIS_DB': {'type': 'str'},
    'AEIS_WORKSPACE': {'type': 'str'},
    'IMGSKILL_BACKEND': {'enum': ['auto', 'magick', 'pillow'], 'type': 'str'},
    'IMGSKILL_PILLOW': {'bool_like': True, 'type': 'bool'},
    'MDCG_ACTOR': {'type': 'str'},
    _ENV_AUTONOMY_MODE: {'enum': ['plan', 'confirm', 'full'], 'type': 'str'},
    'MDCG_AUTO_EVOLVE': {'bool_like': True, 'type': 'bool'},
    'MDCG_AUTO_SCRUB': {'bool_like': True, 'type': 'bool'},
    'MDCG_AUTO_TIDY': {'bool_like': True, 'type': 'bool'},
    'MDCG_BUCKET_MIN_SIM': {'max': 1.0, 'min': 0.0, 'type': 'float'},
    'MDCG_BUCKET_TOPK': {'type': 'str'},
    'MDCG_CHAIN_TYPES': {'type': 'str'},
    'MDCG_CLEARANCE': {'enum': ['public', 'internal', 'restricted', 'private', 'secret'],
 'type': 'str'},
    'MDCG_CN_GRAMS': {'bool_like': True, 'type': 'bool'},
    'MDCG_D_META': {'bool_like': True, 'type': 'bool'},
    'MDCG_EN_ATOMS': {'bool_like': True, 'type': 'bool'},
    'MDCG_EXPLORE_BUDGET_MAX': {'type': 'str'},
    'MDCG_EXPLORE_BUDGET_WINDOW': {'type': 'str'},
    'MDCG_EXPORT_ROOT': {'bool_like': True, 'type': 'bool'},
    'MDCG_FRESHNESS': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S1B_BUCKET': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S1_DOMAIN': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S2_COND': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S3_SPREAD': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S4_LAYER': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S5_NEG': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S6_CROSSCHECK': {'bool_like': True, 'type': 'bool'},
    'MDCG_GATE_S7_POSTINGS': {'bool_like': True, 'type': 'bool'},
    'MDCG_HEARTBEAT_LEDGER': {'bool_like': True, 'type': 'bool'},
    'MDCG_HOTCACHE': {'bool_like': True, 'type': 'bool'},
    'MDCG_HOTCACHE_MAX_NODES': {'min': 1, 'type': 'int'},
    'MDCG_HOTCACHE_MAX_QUERIES': {'min': 1, 'type': 'int'},
    'MDCG_INGEST_ROOT': {'bool_like': True, 'type': 'bool'},
    'MDCG_LAYER_BOOST': {'type': 'str'},
    'MDCG_MCP_SURFACE': {'enum': ['kernel', 'full'], 'type': 'str'},
    'MDCG_NEG_LAMBDA': {'max': 1.0, 'min': 0.0, 'type': 'float'},
    'MDCG_NEG_SIM': {'max': 1.0, 'min': 0.0, 'type': 'float'},
    'MDCG_POOLING': {'bool_like': True, 'type': 'bool'},
    'MDCG_PROPOSAL_EMOTION': {'bool_like': True, 'type': 'bool'},
    'MDCG_REACH': {'bool_like': True, 'type': 'bool'},
    'MDCG_REACH_DIFFUSE': {'bool_like': True, 'type': 'bool'},
    'MDCG_REACH_TTL': {'min': 0.0, 'type': 'float'},
    'MDCG_READ_CACHE': {'bool_like': True, 'type': 'bool'},
    'MDCG_RECONCILE': {'bool_like': True, 'type': 'bool'},
    'MDCG_RETRIEVAL_PIPELINE': {'bool_like': True, 'type': 'bool'},
    'MDCG_S7_FRESHNESS': {'bool_like': True, 'type': 'bool'},
    'MDCG_SCORE_MODE': {'enum': ['legacy', 'jaccard'], 'type': 'str'},
    'MDCG_SEMANTIC': {'bool_like': True, 'type': 'bool'},
    'MDCG_SLEEP': {'bool_like': True, 'type': 'bool'},
    'MDCG_SLEEP_GITDIR': {'type': 'str'},
    'MDCG_SLEEP_INTERVAL': {'type': 'str'},
    _ENV_SLEEP_MERGE: {'enum': ['auto', 'ask', 'never'], 'type': 'str'},
    'MDCG_SLEEP_SCRUB_APPLY': {'bool_like': True, 'type': 'bool'},
    'MDCG_SLEEP_SHADOW': {'type': 'str'},
    'MDCG_SLEEP_WINDOW': {'type': 'str'},
    'MDCG_SPREAD_DECAY': {'max': 1.0, 'min': 0.0, 'type': 'float'},
    'MDCG_SPREAD_GAIN': {'max': 1.0, 'min': 0.0, 'type': 'float'},
    'MDCG_SPREAD_HOPS': {'min': 1, 'type': 'int'},
    'MDCG_STATUS_HEAD': {'bool_like': True, 'type': 'bool'},
    'MDCG_SUSTAIN': {'bool_like': True, 'type': 'bool'},
    'MDCG_SUSTAIN_AUTOHEAL': {'bool_like': True, 'type': 'bool'},
    'MDCG_TEMPORAL_GAMMA': {'min': 0.0, 'type': 'float'},
    'MDCG_TENANT': {'type': 'str'},
    'MDCG_TOOL_FACE': {'bool_like': True, 'type': 'bool'},
    'MDCG_UNIFY_QUERY': {'bool_like': True, 'type': 'bool'},
    'MDCG_WRITELIMIT': {'bool_like': True, 'type': 'bool'},
    'PREDICTION_META_DIM': {'type': 'str'},
    'PREDICTION_META_PROXY': {'type': 'str'},
    'dsh-memory-main::md_cg/admission.py::R1_MAX_SHARE': {'type': 'float'},
    'dsh-memory-main::md_cg/admission.py::R1_MIN_ONE': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::R2_MIN_RECENT': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::R2_MIN_TOTAL': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::R3_MIN_ROLLBACKS': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::R4_MAX_RATE': {'type': 'float'},
    'dsh-memory-main::md_cg/admission.py::R4_SUBWINDOWS': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::R4_SUBWINDOW_D': {'type': 'float'},
    'dsh-memory-main::md_cg/admission.py::TTL_DEFAULT': {'type': 'float'},
    'dsh-memory-main::md_cg/admission.py::WINDOW_LONG_D': {'type': 'int'},
    'dsh-memory-main::md_cg/admission.py::WINDOW_SHORT_D': {'type': 'int'},
    'dsh-memory-main::md_cg/auditview.py::DEFAULT_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/autonomy.py::BUDGET_MAX_ENV': {'type': 'str'},
    'dsh-memory-main::md_cg/autonomy.py::BUDGET_WINDOW_DEFAULT': {'type': 'float'},
    'dsh-memory-main::md_cg/autonomy.py::BUDGET_WINDOW_ENV': {'type': 'str'},
    'dsh-memory-main::md_cg/autonomy.py::GAIN_COOLDOWN': {'type': 'float'},
    'dsh-memory-main::md_cg/autonomy.py::GAIN_WINDOW': {'type': 'int'},
    'dsh-memory-main::md_cg/autonomy.py::_GAIN_STUCK': {'type': 'str'},
    'dsh-memory-main::md_cg/autonomy_modes.py::E_WEIGHT': {'type': 'str'},
    'dsh-memory-main::md_cg/autonomy_modes.py::_SETTLEMENT': {'type': 'str'},
    'dsh-memory-main::md_cg/backfill.py::BATCH_DEFAULT': {'type': 'str'},
    'dsh-memory-main::md_cg/backfill.py::FIX_BATCH_DEFAULT': {'type': 'str'},
    'dsh-memory-main::md_cg/backfill.py::_CAP_TEMPLATE_LINES': {'type': 'str'},
    'dsh-memory-main::md_cg/chain.py::DEFAULT_EDGE_WEIGHT': {'type': 'float'},
    'dsh-memory-main::md_cg/chain.py::EDGE_WEIGHTS': {'type': 'str'},
    'dsh-memory-main::md_cg/chain.py::MAX_DEPTH_DEFAULT': {'type': 'int'},
    'dsh-memory-main::md_cg/chain.py::MAX_DEPTH_HARD': {'type': 'int'},
    'dsh-memory-main::md_cg/chain.py::MAX_NODES_DEFAULT': {'type': 'int'},
    'dsh-memory-main::md_cg/codeindex.py::MAX_DOC': {'type': 'int'},
    'dsh-memory-main::md_cg/coldverify.py::BATCH_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/coldverify.py::POLL_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/conformance.py::DUP_GROUP_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/conformance.py::THRESHOLDS': {'type': 'str'},
    'dsh-memory-main::md_cg/consistency.py::MAX_DEPTH': {'type': 'int'},
    'dsh-memory-main::md_cg/consistency.py::MAX_NODES': {'type': 'int'},
    'dsh-memory-main::md_cg/consistency.py::MAX_SCAN': {'type': 'int'},
    'dsh-memory-main::md_cg/consistency.py::MIN_GAIN': {'type': 'float'},
    'dsh-memory-main::md_cg/consistency.py::SEPARATION_REL': {'type': 'str'},
    'dsh-memory-main::md_cg/consolidate.py::DEFAULT_MAX_TOKENS': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::INDUCE_MAX_NODES': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::INDUCE_MAX_TERMS': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::INDUCE_MIN_CLUSTER': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::INDUCE_MIN_JACCARD': {'type': 'float'},
    'dsh-memory-main::md_cg/consolidate.py::MAX_BODY_CHARS': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::MAX_TERMS': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::MAX_TERM_LEN': {'type': 'int'},
    'dsh-memory-main::md_cg/consolidate.py::MAX_TOKENS_ENV': {'type': 'str'},
    'dsh-memory-main::md_cg/crosscheck.py::CROSSCHECK_BATCH': {'type': 'str'},
    'dsh-memory-main::md_cg/d_meta.py::DEFAULT_WINDOW': {'type': 'int'},
    'dsh-memory-main::md_cg/d_meta.py::_CACHE_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/docindex.py::DEFAULT_SENSITIVITY': {'type': 'str'},
    'dsh-memory-main::md_cg/docindex.py::MAX_DOC': {'type': 'int'},
    'dsh-memory-main::md_cg/docindex.py::MAX_LEVEL': {'type': 'int'},
    'dsh-memory-main::md_cg/docindex.py::MAX_SUMMARY': {'type': 'int'},
    'dsh-memory-main::md_cg/docindex.py::MIN_BODY': {'type': 'int'},
    'dsh-memory-main::md_cg/evidence.py::MAX_ITEMS': {'type': 'int'},
    'dsh-memory-main::md_cg/evidence.py::MAX_TEXT': {'type': 'int'},
    'dsh-memory-main::md_cg/forgetting.py::DETERMINISTIC_BASIS': {'type': 'str'},
    'dsh-memory-main::md_cg/forgetting.py::IMPORTANCE_MIN': {'type': 'float'},
    'dsh-memory-main::md_cg/forgetting.py::LONGTERM_KEEP': {'type': 'int'},
    'dsh-memory-main::md_cg/forgetting.py::MAX_BITS': {'type': 'float'},
    'dsh-memory-main::md_cg/forgetting.py::MAX_COMPARE': {'type': 'int'},
    'dsh-memory-main::md_cg/forgetting.py::MERGE_SOURCES_KEEP': {'type': 'int'},
    'dsh-memory-main::md_cg/forgetting.py::NOVELTY_MIN': {'type': 'float'},
    'dsh-memory-main::md_cg/forgetting.py::SOURCE_WEIGHT': {'type': 'str'},
    'dsh-memory-main::md_cg/freshness.py::FRESHNESS_ENV': {'type': 'str'},
    'dsh-memory-main::md_cg/freshness.py::REFRESH_PARAMS': {'type': 'str'},
    'dsh-memory-main::md_cg/fsutil.py::_NONOBJECT_SAMPLE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/fsutil.py::_SHARD_DIR_SAMPLE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/fsutil.py::_TRANSIENT_READ_SAMPLE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/fsutil.py::_TRANSIENT_READ_WARN_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/goal_gen.py::DEFAULT_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/goal_gen.py::S2_PENDING_MIN': {'type': 'int'},
    'dsh-memory-main::md_cg/goal_gen.py::S3_CCG_MIN': {'type': 'int'},
    'dsh-memory-main::md_cg/goal_gen.py::S4_BLINDSPOT_MIN': {'type': 'int'},
    'dsh-memory-main::md_cg/goal_gen.py::S6_MISSING_MIN': {'type': 'int'},
    'dsh-memory-main::md_cg/hotcache.py::MAX_NODES': {'type': 'int'},
    'dsh-memory-main::md_cg/hotcache.py::MAX_QUERIES': {'type': 'int'},
    'dsh-memory-main::md_cg/hotcache.py::QUERY_TTL': {'type': 'float'},
    'dsh-memory-main::md_cg/imgskill.py::_ALPHA_FMT': {'type': 'str'},
    'dsh-memory-main::md_cg/imgskill.py::_GAMMA_RANGE': {'type': 'str'},
    'dsh-memory-main::md_cg/imgskill.py::_MAGICK_TIMEOUT': {'type': 'float'},
    'dsh-memory-main::md_cg/imgskill.py::_SIGMA_MAX': {'type': 'float'},
    'dsh-memory-main::md_cg/insight.py::C1_WINDOW_MIN': {'type': 'float'},
    'dsh-memory-main::md_cg/insight.py::CER_MIN_SAMPLES': {'type': 'int'},
    'dsh-memory-main::md_cg/insight.py::V1_MIN_EVIDENCE': {'type': 'int'},
    'dsh-memory-main::md_cg/interop.py::_GIT_TIMEOUT_S': {'type': 'int'},
    'dsh-memory-main::md_cg/lifecycle.py::HISTORY_KEEP': {'type': 'int'},
    'dsh-memory-main::md_cg/links.py::CAP_ALIGNED': {'type': 'float'},
    'dsh-memory-main::md_cg/links.py::CAP_INCOMPLETE': {'type': 'float'},
    'dsh-memory-main::md_cg/links.py::CAP_ISOLATED': {'type': 'float'},
    'dsh-memory-main::md_cg/links.py::CAP_MISALIGNED': {'type': 'float'},
    'dsh-memory-main::md_cg/links.py::DECAY_DAYS': {'type': 'float'},
    'dsh-memory-main::md_cg/mcp_server.py::READ_MAX_BYTES': {'type': 'int'},
    'dsh-memory-main::md_cg/mcp_server.py::READ_MAX_LINES': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcg.py::DEFAULT_RECENT_WINDOW': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcg.py::GLOBAL_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcg.py::LAYER_BOOST_DEFAULT': {'type': 'str'},
    'dsh-memory-main::md_cg/mdcg.py::NEG_COVERAGE_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcg.py::NEG_MIN_TERM': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcg.py::OBSERVATION_WINDOW_SEC': {'type': 'float'},
    'dsh-memory-main::md_cg/mdcg.py::SYNONYM_GROUPS_WEIGHTED': {'type': 'str'},
    'dsh-memory-main::md_cg/mdcg.py::TIER_SPREAD': {'type': 'str'},
    'dsh-memory-main::md_cg/mdcg.py::_NORM_WORD_MEMO_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcos.py::DEFAULT_BUDGET': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcos.py::DEFAULT_MAX_ITEM_TOKENS': {'type': 'int'},
    'dsh-memory-main::md_cg/mdcos.py::TEMPORAL_GAMMA_ENV': {'type': 'str'},
    'dsh-memory-main::md_cg/mdcos.py::TERMINAL_DECISION_STATUS': {'type': 'str'},
    'dsh-memory-main::md_cg/mdcos.py::_LEDGER_WINDOW': {'type': 'int'},
    'dsh-memory-main::md_cg/metacognition.py::MIN_SAMPLES': {'type': 'int'},
    'dsh-memory-main::md_cg/mreview/bundle.py::GROUP_BATCH': {'type': 'str'},
    'dsh-memory-main::md_cg/mreview/candidates.py::COLD_IMPORTANCE_MIN': {'type': 'float'},
    'dsh-memory-main::md_cg/mreview/govern.py::BATCH_DEFAULT': {'type': 'str'},
    'dsh-memory-main::md_cg/mreview/locate.py::MIN_FLOW_SENTENCES': {'type': 'int'},
    'dsh-memory-main::md_cg/mreview/locate.py::SNIPPET_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/mreview/pipeline.py::TERMINAL_STATES': {'type': 'str'},
    'dsh-memory-main::md_cg/nodefile.py::ELEMENT_TERM_MIN': {'type': 'int'},
    'dsh-memory-main::md_cg/nodefile.py::FULL_TIME_WINDOW_MAX': {'type': 'float'},
    'dsh-memory-main::md_cg/nodefile.py::FULL_TIME_WINDOW_MIN': {'type': 'float'},
    'dsh-memory-main::md_cg/nodefile.py::FULL_TIME_WINDOW_TEXT': {'type': 'str'},
    'dsh-memory-main::md_cg/pooling.py::POOL_INDEX': {'type': 'str'},
    'dsh-memory-main::md_cg/pooling.py::POOL_KNOWLEDGE': {'type': 'str'},
    'dsh-memory-main::md_cg/pooling.py::POOL_NEGATIVE': {'type': 'str'},
    'dsh-memory-main::md_cg/pooling.py::_RATIO_EPS': {'type': 'float'},
    'dsh-memory-main::md_cg/predict.py::EDGE_BOOST': {'type': 'float'},
    'dsh-memory-main::md_cg/predict.py::HIT_HISTORY_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/predict.py::LEARN_MAX_STEPS': {'type': 'int'},
    'dsh-memory-main::md_cg/predict.py::MAX_BRANCHES_DEFAULT': {'type': 'int'},
    'dsh-memory-main::md_cg/predict.py::MAX_BRANCHES_HARD': {'type': 'int'},
    'dsh-memory-main::md_cg/predict.py::MIN_SAMPLES': {'type': 'int'},
    'dsh-memory-main::md_cg/predict.py::PREFERENCE_THRESHOLD': {'type': 'float'},
    'dsh-memory-main::md_cg/predict.py::SEMANTIC_MIN_SIM': {'type': 'float'},
    'dsh-memory-main::md_cg/predict.py::SEMANTIC_TOP_K': {'type': 'int'},
    'dsh-memory-main::md_cg/progressive.py::MIN_DISCRIM': {'type': 'float'},
    'dsh-memory-main::md_cg/provenance.py::DEFAULT_FIND_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/provenance.py::MAX_FIND_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/provenance.py::_LOCK_TIMEOUT': {'type': 'float'},
    'dsh-memory-main::md_cg/reach.py::DIFFUSE_MAX_FACTOR': {'type': 'int'},
    'dsh-memory-main::md_cg/reach.py::_FRESH_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/reconcile.py::SAMPLE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/refindex.py::MAX_CHECK': {'type': 'int'},
    'dsh-memory-main::md_cg/refine.py::CALIBRATE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/refine.py::EXCERPT_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/refine.py::GATE_MIN_PASS_RATE': {'type': 'float'},
    'dsh-memory-main::md_cg/scrub.py::CONTAMINATION': {'type': 'str'},
    'dsh-memory-main::md_cg/scrub.py::DEFAULT_HOPS': {'type': 'int'},
    'dsh-memory-main::md_cg/scrub.py::MAX_ASSOC_SCAN': {'type': 'int'},
    'dsh-memory-main::md_cg/scrub.py::MAX_BINS_REPORT': {'type': 'int'},
    'dsh-memory-main::md_cg/scrub.py::MAX_OFFSET': {'type': 'float'},
    'dsh-memory-main::md_cg/scrub.py::STRATUM_WEIGHTS': {'type': 'str'},
    'dsh-memory-main::md_cg/security.py::DEFAULT_SENSITIVITY': {'type': 'str'},
    'dsh-memory-main::md_cg/security.py::SENSITIVITY_ORDER': {'type': 'str'},
    'dsh-memory-main::md_cg/self_state.py::RECENT_WINDOW': {'type': 'int'},
    'dsh-memory-main::md_cg/sleep.py::DEFAULT_LOCK_TIMEOUT': {'type': 'float'},
    'dsh-memory-main::md_cg/sleep.py::_GIT_TIMEOUT_S': {'type': 'int'},
    'dsh-memory-main::md_cg/sources.py::SESSION_SENSITIVITY': {'type': 'str'},
    'dsh-memory-main::md_cg/srcindex.py::CHUNK': {'type': 'int'},
    'dsh-memory-main::md_cg/state_events.py::_BAD_ROW_SAMPLE_CAP': {'type': 'int'},
    'dsh-memory-main::md_cg/statushdr.py::MAX_IDS': {'type': 'int'},
    'dsh-memory-main::md_cg/stg.py::_CAP_HINT': {'type': 'str'},
    'dsh-memory-main::md_cg/subgraph.py::MAX_DEPTH_HARD': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::MAX_NODES_DEFAULT': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::RECON_MAX_ANCHORS': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::RECON_MAX_NODES': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::RECON_MIN_SCORE': {'type': 'float'},
    'dsh-memory-main::md_cg/subgraph.py::RECON_NEIGHBOR_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::SEP_MAX_COND_OVERLAP': {'type': 'float'},
    'dsh-memory-main::md_cg/subgraph.py::SEP_MAX_NODES': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::SEP_MAX_PAIRS': {'type': 'int'},
    'dsh-memory-main::md_cg/subgraph.py::SEP_MIN_JACCARD': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_BEAT_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_EVOLVE_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_FRESH_TIMEOUT': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_HEAL_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_SCRUB_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::DEFAULT_TIDY_INTERVAL': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::HEAL_BACKOFF_MAX': {'type': 'float'},
    'dsh-memory-main::md_cg/sustain.py::HEARTBEAT_KEEP_SHARDS': {'type': 'int'},
    'dsh-memory-main::md_cg/sustain.py::TICK_INTERVAL_ATTRS': {'type': 'str'},
    'dsh-memory-main::md_cg/sustain.py::TICK_STALE_MIN_S': {'type': 'float'},
    'dsh-memory-main::md_cg/theory.py::ESCAPE_OPS': {'type': 'str'},
    'dsh-memory-main::md_cg/tokens.py::CORE_PRIVATE_SENSITIVITIES': {'type': 'str'},
    'dsh-memory-main::md_cg/tokens.py::TOKEN_LOCK_TIMEOUT': {'type': 'float'},
    'dsh-memory-main::md_cg/tool_face.py::GENERIC_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/tool_face.py::OP_SPECIFIC_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/trust.py::HISTORY_KEEP': {'type': 'int'},
    'dsh-memory-main::md_cg/trust.py::MAX_DEPS': {'type': 'int'},
    'dsh-memory-main::md_cg/trust.py::MAX_NODES_DEFAULT': {'type': 'int'},
    'dsh-memory-main::md_cg/trust.py::OBSERVED_WINDOW_FIELD': {'type': 'str'},
    'dsh-memory-main::md_cg/trust.py::_MS_EPOCH_THRESHOLD': {'type': 'float'},
    'dsh-memory-main::md_cg/units.py::DEFAULT_MAX_TOKENS': {'type': 'int'},
    'dsh-memory-main::md_cg/units.py::RESERVED_DEVICE_NAMES': {'type': 'str'},
    'dsh-memory-main::md_cg/units.py::TERMINAL_STATES': {'type': 'str'},
    'dsh-memory-main::md_cg/units.py::_MAX_CP': {'type': 'int'},
    'dsh-memory-main::md_cg/vision_evidence.py::BATCH_DEFAULT': {'type': 'str'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/chat_engine.py::AMBIGUOUS_SENSES': {'type': 'str'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/chat_engine.py::_CONVERGE_LIMIT': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/code_test_runner.py::TIMEOUT': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/cspmn.py::GPU_THRESHOLD': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/csre.py::MAX_DEPTH': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/danmaku_audit.py::FISHING_SENSES': {'type': 'str'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/danmaku_bridge.py::RATE_LIMIT_SECONDS': {'type': 'float'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/navigate.py::MIN_ACCEPT_SCORE': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/navigate.py::SEED_MIN_ACCEPT_SCORE': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/pattern_separation.py::SIM_THRESHOLD': {'type': 'float'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/semantic_translate.py::_ROUTE_CACHE_TTL': {'type': 'float'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/verify_answer.py::_MAX_LEN': {'type': 'int'},
    'dsh-memory-main::md_cg/whitebox_kb/wisdom/verify_answer.py::_MIN_LEN': {'type': 'int'},
    'dsh-memory-main::md_cg/writelimit.py::CONVERGE_WINDOW': {'type': 'float'},
    'dsh-memory-main::md_cg/writelimit.py::MAX_APPLY': {'type': 'int'},
    'dsh-memory-main::md_cg/writelimit.py::MAX_CONTENT': {'type': 'int'},
    'dsh-memory-main::md_cg/writelimit.py::MIN_SKELETON': {'type': 'int'},
    'dsh-memory-main::md_cg/writelimit.py::RATE_MAX': {'type': 'int'},
    'dsh-memory-main::md_cg/writelimit.py::RATE_WINDOW': {'type': 'float'},
    'dsh-memory-main::scripts/bootstrap_watchdog.py::DEGRADE_LIMIT': {'type': 'int'},
    'dsh-memory-main::scripts/check_publish_artifact.py::BATCH_MAX': {'type': 'int'},
    'dsh-memory-main::scripts/check_publish_artifact.py::TEXT_SIZE_LIMIT': {'type': 'int'},
    'dsh-memory-main::scripts/check_publish_artifact.py::UNSCANNED_ESCAPE': {'type': 'str'},
    'dsh-memory-main::scripts/check_publish_smoke.py::HANDSHAKE_TIMEOUT': {'type': 'int'},
    'dsh-memory-main::scripts/check_publish_smoke.py::NPM_TIMEOUT': {'type': 'int'},
    'dsh-memory-main::scripts/dsh_log_index.py::CHUNK_MAX': {'type': 'int'},
    'dsh-memory-main::scripts/gen_id_charset_blocks.py::MAX_CP': {'type': 'int'},
    'dsh-memory-main::scripts/mdcg_verify_render_meta.py::ACTIVE_WINDOW_S': {'type': 'int'},
    'dsh-memory-main::scripts/probe_b_state_events_v4.py::SNIPPET_MAX': {'type': 'int'},
    'dsh-memory-main::scripts/probe_c_ledger_integrity.py::BIG_LIMIT': {'type': 'int'},
    'dsh-memory-main::scripts/probe_d_retirement_discipline.py::ANCHOR_WINDOW': {'type': 'str'},
    'dsh-memory-main::scripts/retr_time_coverage.py::FULL_WINDOW_HI': {'type': 'float'},
    'dsh-memory-main::scripts/review_reconcile.py::MAX_FILES': {'type': 'int'},
    'dsh-memory-main::scripts/review_reconcile.py::MAX_ITEMS': {'type': 'int'},
    'dsh-memory-main::scripts/review_reconcile.py::MAX_NODES': {'type': 'int'},
    'dsh-memory-main::scripts/sync_zcode_session.py::WINDOW_LIMIT': {'type': 'int'},
    'dsh-memory-main::scripts/sync_zcode_session.py::WINDOW_TAIL_SCAN': {'type': 'int'},
    'dsh-memory-main::scripts/verify_injection_zcode_user.py::MIN_SENTINEL': {'type': 'int'},
    'dsh-memory-main::scripts/verify_open_encoding.py::_FLOORS': {'type': 'str'},
    'dsh-memory-main::scripts/zcode_window_hook.py::REMINDER_TMPL': {'type': 'str'},
    'dsh-memory-main::scripts/zcode_window_hook.py::WINDOW_ACK_KEY': {'type': 'str'},
}


_TRUE = ("1", "true", "True", "yes", "y", "on", "On")
_FALSE = ("0", "false", "False", "no", "n", "off", "Off")


def coerce(name, raw):
    """把配置面取值（TOML 已带类型；env 恒为字符串）归一到规则类型。

    返回 (ok, value_or_None, err)。**不猜测**：无法归一即报错（fail-closed）。
    """
    r = RULES.get(name)
    if r is None:
        return True, raw, None
    t = r["type"]
    if isinstance(raw, bool):
        return True, raw, None
    if t == "bool" and r.get("bool_like"):
        s = str(raw)
        if s in _TRUE:
            return True, True, None
        if s in _FALSE:
            return True, False, None
        return False, None, f"{name}: 非布尔字面量 {raw!r}"
    try:
        if t == "int":
            v = int(raw)
        elif t == "float":
            v = float(raw)
        else:
            v = str(raw)
    except (TypeError, ValueError) as e:
        return False, None, f"{name}: 类型应为 {t}，得到 {raw!r}（{e}）"
    return True, v, None


def validate(name, raw):
    """值域/类型校验（唯一入口）。返回 (ok, coerced, err)。"""
    ok, v, err = coerce(name, raw)
    if not ok:
        return ok, v, err
    r = RULES.get(name)
    if r is None:
        return True, v, None
    if "enum" in r and v not in r["enum"]:
        return False, None, f"{name}: 取值 {v!r} 不在 {r['enum']}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "min" in r and v < r["min"]:
            return False, None, f"{name}: {v} < 下限 {r['min']}"
        if "max" in r and v > r["max"]:
            return False, None, f"{name}: {v} > 上限 {r['max']}"
    return True, v, None


CASES = (
    # (name, 输入, 期望 ok)
    ("MDCG_MCP_SURFACE", "kernel", True),
    ("MDCG_MCP_SURFACE", "nope", False),
    ("MDCG_CLEARANCE", "internal", True),
    ("MDCG_CLEARANCE", "top-secret", False),
    ("MDCG_BUCKET_MIN_SIM", "0.34", True),
    ("MDCG_BUCKET_MIN_SIM", "1.7", False),
    ("MDCG_SPREAD_HOPS", "2", True),
    ("MDCG_SPREAD_HOPS", "0", False),
    (_ENV_AUTONOMY_MODE, "full", True),
    (_ENV_AUTONOMY_MODE, "god", False),
    (_ENV_SLEEP_MERGE, "auto", True),
    (_ENV_SLEEP_MERGE, "later", False),
    ("MDCG_HOTCACHE", "1", True),
    ("MDCG_HOTCACHE", "0", True),
    ("MDCG_HOTCACHE", "maybe", False),
)


def self_test():
    """内置用例自证（`--self-test` / pytest 收集）。返回失败数。"""
    bad = 0
    for name, raw, want in CASES:
        ok, _, err = validate(name, raw)
        if ok != want:
            bad += 1
            print(f"  FAIL {name}={raw!r} 期望 ok={want} 实得 {ok} ({err})")
    return bad


def test_config_validate_self_test():
    """pytest 收集入口。"""
    assert self_test() == 0


def main(argv):
    if "--self-test" in argv or not argv:
        bad = self_test()
        print(f"self-test: {'OK' if bad == 0 else str(bad) + ' FAIL'}")
        return 0 if bad == 0 else 1
    name = None
    val = None
    for i, a in enumerate(argv):
        if a == "--name" and i + 1 < len(argv):
            name = argv[i + 1]
        if a == "--value" and i + 1 < len(argv):
            val = argv[i + 1]
    if not name:
        print("用法：python -X utf8 -m md_cg.config_validate "
              "[--self-test | --name X --value V]")
        return 2
    ok, v, err = validate(name, val)
    print(f"{name} = {v!r}" if ok else f"拒绝：{err}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
