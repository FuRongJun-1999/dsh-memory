# -*- coding: utf-8 -*-
r"""官方口径 · 灵枢臂端到端复算（reader harness，task-32）。

目标：产出**与官方同口径**的灵枢臂读数——官方提示词 + 官方判分器 + 官方布局。

口径四件（全部照官方，不得自造）：
  ① 提示词：直接 import 官方 probe_runner 的 CHAIN_SYS / build_prompt / build_closed_prompt
     （本文件不含其文本副本；守卫以「本文件源码里不出现 CHAIN_SYS 文本」+「与官方对象逐字相等」双证）。
  ② 常量：K / MATERIAL_CHARS / CHAIN_K / CHAIN_MATERIAL_CHARS 一律取官方模块属性。
  ③ 判分器：官方 probe_judge.py 原文（本脚本只把工作根指到本脚本的 stage）。
  ④ 布局：runs/chain_<arm>/{sut/out/<qid>.json, retrieval/<qid>.json, manifest.json}。

只补官方仓明说「不在本库内」的两块（README §8：common.py 与 adapters/*.py 由使用者自备）：
  · common.LLM —— DeepSeek 官方 API，模型 deepseek-flash；密钥在运行时从 Windows
    Machine 作用域注册表读；不写文件、不打印、不进 argv、不进异常文本；
    只在内存请求头里出现 Bearer。
  · adapters.lingshu_adapter.LingshuAdapter —— 把 corpus 灌进本仓 md_cg（ingest 形态照
    官方 runner），并按 build_prompt 要的字段组材料。

隔离：MDCG_ROOT / MDCG_AUX_ROOT / MDCG_MASTER_KEY 一律指向本次 stage 之下的沙箱；
     stage 是官方仓的字节镜像副本（工具逐字节相同，守卫按 sha256 断言），零仓写。

用法：
  python -X utf8 scripts/bench_chain_reader.py --limit 20             # 小样（默认）
  python -X utf8 scripts/bench_chain_reader.py --limit 20 --judge     # 小样 + 官方判分器读数
  python -X utf8 scripts/bench_chain_reader.py --llm-dry-run --limit 2    # 零网络冒烟
  python -X utf8 scripts/bench_chain_reader.py --limit 0 --allow-full     # 全量（须显式批准）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DEFAULT = HERE.parent
#: 官方基准仓与布局镜像的默认落点：**只在环境变量缺省时用**，且不含本机绝对路径
#: （追踪面门禁 `scripts/check_local_paths.py` 禁止本机路径；两处均以运行期求值的
#: 家目录/临时目录为根，源码里不出现机器前缀）。真实路径请用环境变量覆盖：
#:   MEMBENCH_CHAIN_BENCH / ITERREADER_DIR
BENCH_DEFAULT = Path(os.environ.get(
    "MEMBENCH_CHAIN_BENCH",
    os.path.join(tempfile.gettempdir(), "bench")))
ART_DIR = Path(os.environ.get(
    "ITERREADER_DIR",
    os.path.join(os.path.expanduser("~"), "_team", "iterreader")))
STAGE_DEFAULT = ART_DIR / "stage"
GEN_MODEL = "deepseek-flash"
API_BASE = "https://api.deepseek.com"
KEY_ENV = "DEEPSEEK_API_KEY"
KEY_REG_PATH = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
TOOLS = ("probe_runner.py", "probe_judge.py")
#: created_at 的事实时点映射（task-31 根因）：seq 单调映射到过去时间轴。
#: 2026-01-01T00:00:00Z 起、每 seq 一天——确定性、可复算，且恒在过去。
SEQ_EPOCH = 1767225600
SEQ_STEP = 86400
OUT_DATA = (("corpus", "corpus.json"), ("keys", "keys.json"), ("keys", "synth_log.json"))


def log(*a) -> None:
    print(*a, flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_machine_key(name: str = KEY_ENV) -> str:
    """从 Machine 作用域注册表读密钥。返回内存字符串；调用方不得打印或落盘。"""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_REG_PATH) as k:
        v, _t = winreg.QueryValueEx(k, name)
    v = (v or "").strip()
    if not v:
        raise SystemExit("Machine 注册表里的 %s 为空" % name)
    return v


class DeepSeekLLM:
    """官方 runner 契约：.chat(messages) -> str，另有 .tokens / .calls 计数。

    密钥只在内存请求头里出现；异常文本经 _scrub 洗过再抛，防密钥随栈外泄。
    """
    def __init__(self, key: str, model: str = GEN_MODEL, base: str = API_BASE,
                 thinking: bool = True, timeout: int = 300, temperature=None):
        self._key = key
        self.model = model
        self.base = base.rstrip("/")
        self.thinking = thinking
        self.timeout = timeout
        self.temperature = temperature
        self.tokens = 0
        self.calls = 0

    def _scrub(self, s) -> str:
        t = str(s)
        return t.replace(self._key, "<KEY>") if self._key else t

    def chat(self, messages) -> str:
        body = {"model": self.model, "messages": messages, "max_tokens": 4096}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.thinking:
            body["thinking"] = {"type": "enabled"}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._key},
            method="POST")
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                o = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if e.code == 400 and self.thinking and "thinking" in detail:
                self.thinking = False
                return self.chat(messages)
            raise RuntimeError("HTTP %s: %s" % (e.code, self._scrub(detail)))
        except Exception as e:
            raise RuntimeError(self._scrub(type(e).__name__ + ": " + str(e)))
        u = (o or {}).get("usage") or {}
        self.tokens += int(u.get("total_tokens") or 0)
        ch = ((o or {}).get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        return msg.get("content") or ""


class StubLLM:
    """零网络替身（守卫用）：返回契约合法的最小 JSON，计数照累。"""
    model = "stub"

    def __init__(self, key: str = ""):
        self._key = key
        self.tokens = 0
        self.calls = 0

    def chat(self, messages) -> str:
        self.calls += 1
        self.tokens += 7
        qid = ""
        for m in messages:
            if m.get("role") == "user":
                for line in str(m.get("content") or "").splitlines():
                    if line.startswith("## 问题（"):
                        qid = line.split("（", 1)[1].rstrip("）").strip()
        return json.dumps({"qid": qid, "value": None, "state": "absent",
                           "at_seq": None, "chain": [], "basis": [],
                           "confidence": "unknown"}, ensure_ascii=False)


class LingshuAdapter:
    """官方 runner 契约：.ingest(chapters) -> dict；.retrieve(query, k) -> [dict]。

    ingest 形态照官方 runner：chapters 已被 runner 改写为 text = 井号 + 空格 + cid + 换行 + 正文；
    retrieve 返回 build_prompt 需要的 {cid, text, score}，cid 即 corpus 的 doc#seq，
    使模型能把 basis.file 填成片段头里的 doc#seq。
    """
    def __init__(self, repo: str | Path = REPO_DEFAULT, root: str | None = None,
                 created_at_mode: str = "write_time"):
        # created_at_mode: "write_time"＝缺省写入时刻（官方首轮口径，基线 A）；
        #                  "fact_time" ＝按语料 seq 映射到过去时间轴（B 组，task-31 根因）。
        # 只动 adapter：md_cg 的 add() 本就接受 created_at 透传（extra.pop），零实现改动。
        self.created_at_mode = created_at_mode
        sys.path.insert(0, str(repo))
        from md_cg.mdcos import MdCGOS
        self._MdCGOS = MdCGOS
        self.root = root or os.environ["MDCG_ROOT"]
        self.cg = MdCGOS(self.root)
        self._cid_by_title = {}
        self._cid_of_node = {}
        self.n_chunks = 0

    @staticmethod
    def _nid(cid: str) -> str:
        return "c_" + hashlib.sha1(cid.encode("utf-8")).hexdigest()[:16]

    def ingest(self, chapters) -> dict:
        t0 = time.time()
        chars = 0
        for ch in chapters:
            cid = ch.get("cid") or ch.get("title")
            text = ch.get("text") or ""
            nid = self._nid(cid)
            kw = {"consistency": False}
            if self.created_at_mode == "fact_time":
                seq = int(ch.get("seq") or 1)
                kw["created_at"] = SEQ_EPOCH + (seq - 1) * SEQ_STEP
            self.cg.add(nid, text, layer="knowledge",
                        tags=[str(cid), str(ch.get("doc") or "")], **kw)
            self._cid_of_node[nid] = str(cid)
            chars += len(text)
        self.n_chunks = len(chapters)
        return {"chunks": len(chapters), "chars": chars,
                "elapsed": round(time.time() - t0, 1)}

    def _cid_of(self, nid: str, text: str) -> str:
        """取 corpus 的 doc#seq：优先 ingest 期映射；否则解析正文首行标题。

        ask 阶段是**新实例**（官方 runner 只重灌 bm25/versionblind），故必须能
        从正文首行解析——runner 另把 _cid_by_title 交给我们作对照（官方契约）。
        """
        c = self._cid_of_node.get(nid)
        if c:
            return c
        first = (text or "").lstrip().splitlines()[:1]
        if first:
            t = first[0].strip()
            if t.startswith("# "):
                t = t[2:].strip()
                if t:
                    return t
        return nid

    def retrieve(self, query: str, k: int = 6):
        res, meta = self.cg.search(query, k=int(k))
        out = []
        for it in res or []:
            node = it[0] if isinstance(it, (tuple, list)) else it
            score = it[1] if isinstance(it, (tuple, list)) and len(it) > 1 else None
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            out.append({"cid": self._cid_of(nid, node.get("content") or ""),
                        "text": node.get("content") or "",
                        "score": score})
        return out


def build_stage(bench: Path, stage: Path, fresh: bool = True) -> dict:
    """把官方仓的工具与已发布数据按官方布局镜像到 stage（只读官方源，零改官方）。"""
    tools_src = bench / "chain" / "tools"
    stage_tools = stage / "chain" / "tools"
    out_dir = stage_tools / "out"
    if fresh and stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    for d in (stage_tools, out_dir,
              stage / "membench" / "dist" / "记忆系统对比_v1.0" / "harness" / "adapters",
              stage / "membench" / "dist" / "记忆系统对比_v1.0" / "runs"):
        d.mkdir(parents=True, exist_ok=True)
    fps = {}
    for name in TOOLS:
        src, dst = tools_src / name, stage_tools / name
        shutil.copyfile(src, dst)
        fps[name] = {"src_sha256": sha256_file(src), "dst_sha256": sha256_file(dst),
                     "identical": sha256_file(src) == sha256_file(dst)}
    for sub, name in OUT_DATA:
        src, dst = bench / "chain" / sub / name, out_dir / name
        shutil.copyfile(src, dst)
        fps[name] = {"src_sha256": sha256_file(src), "dst_sha256": sha256_file(dst),
                     "identical": sha256_file(src) == sha256_file(dst)}
    return {"stage": str(stage), "out_dir": str(out_dir), "files": fps}


def install_harness(llm, stage: Path, adapter_cls=LingshuAdapter) -> None:
    # adapter_cls 是**零参可调用**（官方 runner 的契约是 LingshuAdapter()）
    """把官方明说不在本库内的两块以内存模块注入 sys.modules（不落盘、不改官方）。"""
    common = types.ModuleType("common")
    common.LLM = (lambda: llm)
    common.GEN_MODEL = getattr(llm, "model", GEN_MODEL)
    common.RUNS = stage / "membench" / "dist" / "记忆系统对比_v1.0" / "runs"
    sys.modules["common"] = common
    pkg = types.ModuleType("adapters")
    pkg.__path__ = []
    mod = types.ModuleType("adapters.lingshu_adapter")
    mod.LingshuAdapter = adapter_cls
    sys.modules["adapters"] = pkg
    sys.modules["adapters.lingshu_adapter"] = mod
    pkg.lingshu_adapter = mod


def load_official(stage: Path, bench: Path):
    """返回 (官方 runner, 官方 judge)，两者都从 stage 的字节镜像导入。"""
    tools = str(stage / "chain" / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import probe_runner as PR
    import probe_judge as PJ
    return PR, PJ


def augment_manifest(d: Path, model: str, created_at_mode: str = "") -> dict:
    """官方 manifest 上只增别名键（failures / model / created_at_mode / note），官方键一个不动。

    created_at_mode 是**口径标记**：A 组 write_time（基线）与 B 组 fact_time 必须可分。
    """
    p = d / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m.setdefault("failures", m.get("errors", 0))
    m.setdefault("model", model)
    if created_at_mode:
        m["created_at_mode"] = created_at_mode
        m["note"] = ("口径：created_at = %s（write_time=缺省写入时刻/官方首轮口径；"
                     "fact_time=按语料 seq 映射过去时间轴）"
                     % ("缺省写入时刻" if created_at_mode == "write_time" else "事实生效时点"))
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="官方口径 灵枢臂端到端复算 reader harness")
    ap.add_argument("--bench", default=str(BENCH_DEFAULT), help="官方基准仓根（只读）")
    ap.add_argument("--stage", default=str(STAGE_DEFAULT), help="官方布局镜像根（产物落此）")
    ap.add_argument("--arm", default="lingshu")
    ap.add_argument("--limit", type=int, default=20,
                    help="只跑前 N 题（默认 20；0=全量，须 --allow-full）")
    ap.add_argument("--allow-full", action="store_true", help="显式批准全量 642 题")
    ap.add_argument("--judge", action="store_true", help="跑官方判分器并打印该臂读数")
    ap.add_argument("--llm-dry-run", action="store_true", help="零网络：用替身 LLM 走通全链路")
    ap.add_argument("--model", default=GEN_MODEL)
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--ingest-only", action="store_true")
    ap.add_argument("--keep-stage", action="store_true", help="复用已有 stage（增量）")
    ap.add_argument("--created-at-mode", choices=("write_time", "fact_time"),
                    default="write_time",
                    help="A 组=write_time（缺省写入时刻，官方首轮口径）；B 组=fact_time（按 seq 映射过去时间轴）")
    a = ap.parse_args(argv)

    if a.limit == 0 and not a.allow_full:
        raise SystemExit("拒绝全量：642 题需 Lead 明确批准，须显式加 --allow-full")
    bench, stage = Path(a.bench), Path(a.stage)
    if not (bench / "chain" / "tools" / "probe_runner.py").exists():
        raise SystemExit("官方仓路径不含 chain/tools/probe_runner.py：%s" % bench)

    sand = stage / "sandbox"
    (sand / "mdcg").mkdir(parents=True, exist_ok=True)
    # 注意：目录名不要用 aux / con / nul 等 Windows 保留设备名（mkdir 会 WinError 267）
    (sand / "auxroot").mkdir(parents=True, exist_ok=True)
    os.environ["MDCG_ROOT"] = str(sand / "mdcg")
    os.environ["MDCG_AUX_ROOT"] = str(sand / "auxroot")
    if not os.environ.get("MDCG_MASTER_KEY"):
        os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
    os.environ.setdefault("MDCG_RUN_TAG", "_chain")

    info = build_stage(bench, stage, fresh=not a.keep_stage)
    key = read_machine_key()          # 无条件读（dry-run 也走同一条路径：泄漏扫描面必须非空）
    llm = StubLLM(key) if a.llm_dry_run else DeepSeekLLM(
        key, model=a.model, thinking=not a.no_thinking)
    mode = a.created_at_mode
    adapter_factory = (lambda: LingshuAdapter(created_at_mode=mode))
    install_harness(llm, stage, adapter_cls=adapter_factory)
    PR, PJ = load_official(stage, bench)
    log("[口径] CHAIN_SYS 长度=%d ｜ K=%d MATERIAL_CHARS=%d CHAIN_K=%d CHAIN_MATERIAL_CHARS=%d"
        % (len(PR.CHAIN_SYS), PR.K, PR.MATERIAL_CHARS, PR.CHAIN_K, PR.CHAIN_MATERIAL_CHARS))
    log("[stage] %s ｜ 工具与数据同官方逐字节：%s"
        % (info["stage"], all(v["identical"] for v in info["files"].values())))
    log("[口径] keys_fp（官方现算）= %s" % PR.keys_fp(PR.load_keys()))

    d = PR.run_dir(a.arm)
    t0 = time.time()
    do_ingest, do_ask = PR.do_ingest, PR.do_ask
    if not a.keep_stage:
        do_ingest(a.arm, d, 0)
    if not a.ingest_only:
        m = do_ask(a.arm, d, a.limit)
        m = augment_manifest(d, getattr(llm, "model", a.model), mode)
        log("[产物] %s" % d)
        log("[读数] 题数=%s ok=%s failures=%s llm_calls=%s tokens=%s elapsed=%ss"
            % (m.get("n_questions"), m.get("ok"), m.get("failures"),
               m.get("llm_calls"), getattr(llm, "tokens", m.get("llm_tokens")),
               m.get("elapsed")))
    if a.judge:
        fp = PJ.keys_fp()
        rows = PJ.judge_arms([a.arm])
        row = (rows or [{}])[0]
        mf = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        log("[官方判分] keys_fp(judge)=%s ｜ manifest=%s" % (fp, mf.get("keys_fp")))
        fields = ("arm", "present", "history", "chain", "chain_row_recall", "stale",
                  "future", "subject_confusion", "four_state", "reason", "verbatim", "n",
                  "n_expected", "sampled", "complete")
        if row:
            log("[官方判分·readings] %s" % json.dumps(
                {k: row.get(k) for k in fields}, ensure_ascii=False))
        ex = d.parent.parent / "out" / "readings_excluded.json"
        exc = Path(PJ.OUT) / "readings_excluded.json"
        try:
            er = json.loads(exc.read_text(encoding="utf-8"))
        except Exception:
            er = []
        for r in er:
            if r.get("arm") == a.arm:
                log("[官方判分·excluded] %s" % json.dumps(
                    {k: r.get(k) for k in fields + ("exclude_reason",)}, ensure_ascii=False))
        if not row and not er:
            log("[官方判分] 两侧皆无该臂记录（异常）")
    log("[耗时] %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())