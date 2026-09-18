# 环二待裁定队列 · 预落地报告（机生成）

生成时间：2026-09-18T17:18:47

- 候选数：30（内部复核 ACCEPT 且无外部回执）
- 若全部落地：新增条件注释 **137** 条，涉及 18 个文件
- 已在主干的同名条件（跳过）：449 条
- 同一函数被不同候选给出不同条件：**86 处**（预落地解法：后批次胜，被弃用的条件列于末尾供复核）
- 影子应用后测试（本轮实跑）：compiler 8/8 · hive 5/5 · md_cg 88/88（3 跳过）· scripts 2/2 均通过

> 注：本报告不代表已落地。按设计双判据，落地仍需**外部 PASS ∩ 内部 ACCEPT**；内部 via=internal 不当外部 PASS。

## 涉及文件

- compiler/condition_vm.py（1 条）
- hive/exec_cmd.py（9 条）
- hive/hive_mcp/smoke_test.py（7 条）
- md_cg/bench6_common.py（8 条）
- md_cg/bench_en_atoms_public.py（8 条）
- md_cg/bench_lme_zh.py（12 条）
- md_cg/cond_compose.py（8 条）
- md_cg/export.py（9 条）
- md_cg/identity.py（1 条）
- md_cg/lexicon/build_cedict_en_zh.py（9 条）
- md_cg/migrate_aeis.py（7 条）
- md_cg/migrate_roleplay.py（7 条）
- md_cg/mreview/bundle.py（8 条）
- md_cg/mreview/candidates.py（9 条）
- md_cg/semantic/en_normalizer.py（8 条）
- md_cg/subgraph.py（19 条）
- md_cg/tasks.py（5 条）
- md_cg/writelimit.py（2 条）

## 冲突清单（前 20 条：保留值 / 被弃值 / 后批次）

- md_cg/bench_lme_zh.py::_llm：保留 环境变量 DEEPSEEK_API_KEY 为真值（缺省或空串即抛 RuntimeError「需要 DEEPSEEK_A 　弃用 messages 传入且环境变量 DEEPSEEK_API_KEY 为真值（未设/空串等假值时直接抛 RuntimeEr 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::_load_json：保留 p 经 os.path.isfile(p) 判定为普通文件时按 utf-8 打开并返回 json.load(f)；os. 　弃用 p 传入且 os.path.isfile(p) 为真时返回该路径 json.load 的结果，否则返回 {}。 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::_load_manual：保留 无参调用即返回 (_load_json(MAN_ZH), _load_json(MAN_Q))，每个元素在模块级常量 M 　弃用 无入参，以模块级常量 MAN_ZH 与 MAN_Q 为路径分别读入并返回（中文层, 中文查询词）二元组。 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::_cond_of：保留 z 为真值且 re.search(r"条件=([^；;]+)") 命中，并按 [|｜] 切分后至少有一段以 ":" /  　弃用 z 为非空字符串且能匹配到「条件=…」片段时返回由 _COND_KEYS 内键名派生的条件 dict；z 为 None/ 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::_load_cache：保留 模块级常量 CACHE 经 os.path.isfile(CACHE) 判定为普通文件时按 utf-8 打开并返回 js 　弃用 无入参，模块级常量 CACHE 路径上 os.path.isfile(CACHE) 为真时返回其 json.load 内 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::_save_cache：保留 以 c 为输入即 os.makedirs(DIR, exist_ok=True) 后按 utf-8 把 c 以 ensu 　弃用 c 传入即对模块级常量 DIR 建目录（exist_ok=True）并将 c 以 json.dump 写入常量 CACH 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::zh_layer：保留 cache 命中 "L2:"+turn["id"] 时直接返回该缓存值；否则用 ZH_PROMPT 拼 json.dum 　弃用 turn 与 cache 传入，cache 中已有 "L2:"+turn["id"] 时直接返回该缓存值；未命中时用 t 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::zh_question：保留 cache 命中 "Q2:"+q["qid"] 时直接返回该缓存值；否则以 ZH_Q_PROMPT+q["questio 　弃用 q 与 cache 传入，cache 中已有 "Q2:"+q["qid"] 时直接返回缓存值（不读取 q["questi 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::build_pool：保留 模块级常量 POOL 为普通文件时直接返回其中非空行的 json.loads 列表（此时不读 n_q、n_distrac 　弃用 n_q 与 n_distract 传入，os.path.isfile(POOL) 为真时直接返回 POOL 中各非空行的 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::build：保留 以 ec.build_eval_cg(None, root, corpus or POOL, ec.lm_turn_te 　弃用 root 与 pool 传入后以 corpus or POOL 为数据源调用 ec.build_eval_cg（corp 　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::calib：保留 作为 build 的内层函数闭包使用 zh_of/zh_only，ctx 未被使用；zh_of 为真值且 zh_of.g 　弃用 r 传入（ctx 未被使用），闭包中 zh_of 为真值时按 zh_of.get(r["id"]) 取中文层 z 并以  　（iter-168-batch-c168-fix）
- md_cg/bench_lme_zh.py::work：保留 对 r 调 zh_layer(r, cache)（cache 为闭包变量）成功时返回 (r["id"], 中文层, No 　弃用 r 含 "id" 且 zh_layer(r, cache) 正常返回时返回 (r["id"], 中文层, None)；z 　（iter-168-batch-c168-fix）
- hive/exec_cmd.py::_write_result：保留 job_dir 与 obj 给出后无任何前置判断，直接用 UTF-8 打开 job_dir/result.json.tm 　弃用 给定 job_dir 与 obj 时，把 obj 以 ensure_ascii=False 写入 job_dir/res 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_fail：保留 以 job_dir 与 msg 构造 {"ok": False, "error": msg, "model": "cmd 　弃用 给定 job_dir 与 msg 时，把 {"ok":False,"error":msg,"model":"cmd"}  　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_norm_steps：保留 spec["commands"] 为非空 list 时逐项归一（dict 原样收、list 包成 {"command": 　弃用 spec["commands"] 为非空 list 时逐项归一（dict 原样收、list 包成 {"command": 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_dump_step：保留 对 ("stdout", out) 与 ("stderr", err) 各自把全文写入 job_dir/step_<id 　弃用 给定 job_dir、idx、out、err、rec 时，对 stdout/stderr 各写 job_dir/step 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_run_step：保留 argv 直接取 step["command"]（缺键即 KeyError）；cwd 取 step.get("cwd") 　弃用 step["command"] 作 argv 执行，cwd=step["cwd"] or default_cwd 补成绝 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_render：保留 以 steps 与 elapsed 生成首行「确定性执行：{len(steps)} 步，用时 {elapsed:.2f} 　弃用 给定 steps 与 elapsed 时，首行为「确定性执行：{len(steps)} 步，用时 {elapsed:.2 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::_delegate：保留 spec 为 None 时从 job_dir/spec.json 读取（OSError/ValueError 时置 {} 　弃用 spec 为 None 时从 job_dir/spec.json 读入（OSError/ValueError 则置 {} 　（iter-210-batch-c210-fix）
- hive/exec_cmd.py::run_cmd：保留 job_dir/spec.json 读取抛 OSError/ValueError 即 _fail(..., EXIT_S 　弃用 job_dir/spec.json 读取失败（OSError/ValueError）或 _norm_steps 返回 e 　（iter-210-batch-c210-fix）
