# -*- coding: utf-8 -*-
"""test_datapath_root.py · 数据根解析与「迁出插件包」回归（issue #18 相邻问题）

被测不变量（任一被破坏即红）：
  ① state_root() 三档：MDCG_STATE_ROOT > $DSH_HOME/.dsh-memory > ~/.dsh/.dsh-memory
  ② paths_file()：用户级优先；用户级不存在时**兼容读**旧包内位置；都不存在返回新位置
  ③ default_data_root() 必在**插件包目录之外**——这是「pnpm 更新不丢数据」的充要条件
  ④ migrate_legacy_data()：默认根生效时把旧包内数据复制到用户级根（只复制不删除、
     不覆盖已有、不搬 paths.json、幂等）；数据根为**显式配置**时不动作
  ⑤ set_user_root() 永远写用户级新位置，且把旧件既有取值带入（不丢用户设置）

隔离纪律：插件根以 monkeypatch 换成临时假包（**不动本机 <仓>/data 与真实状态根**），
状态根/数据根一律经 MDCG_STATE_ROOT / MDCG_DATA_ROOT 指向临时目录。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from . import datapath as dp

_ENV_KEYS = ("MDCG_STATE_ROOT", "MDCG_DATA_ROOT", "MDCG_ROOT", "DSH_HOME")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _inside(parent: str, child: str) -> bool:
    p = os.path.normcase(os.path.abspath(parent))
    c = os.path.normcase(os.path.abspath(child))
    return c == p or c.startswith(p + os.sep)


class DatapathRootTest(unittest.TestCase):
    # 生效条件：每个用例前建临时假包与临时状态根、清空四个相关环境变量并把 plugin_root monkeypatch 到假包；异常即用例失败，不污染真实仓与真实状态根。
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="datapath-root-")
        self.pkg = os.path.join(self.tmp, "pkg")        # 假插件包
        self.state = os.path.join(self.tmp, "state")    # 假用户级状态根
        os.makedirs(os.path.join(self.pkg, "md_cg"), exist_ok=True)
        self._orig_plugin_root = dp.plugin_root
        dp.plugin_root = lambda: self.pkg               # 隔离：不碰真实仓
        self._env = {k: os.environ.get(k) for k in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["MDCG_STATE_ROOT"] = self.state

    # 生效条件：每个用例后恢复 plugin_root 与四个环境变量原值并删临时目录（ignore_errors，不掩盖用例结果）。
    def tearDown(self):
        dp.plugin_root = self._orig_plugin_root
        for key, val in self._env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 生效条件：给定相对 package 内路径拼绝对路径（写入旧位置假数据用）。
    def _pkg_path(self, *parts: str) -> str:
        return os.path.join(self.pkg, *parts)

    # 生效条件：给定相对数据根路径拼用户级默认数据根下的绝对路径（断言新落点用）。
    def _new_root_path(self, *parts: str) -> str:
        return os.path.join(dp.default_data_root(), *parts)

    # 生效条件：在旧包内位置造假数据（mdcg/mem.md、ledger.jsonl、paths.json），返回该目录。
    def _seed_legacy(self, mem: str = "MEM-1") -> str:
        legacy = dp.legacy_data_root()
        os.makedirs(os.path.join(legacy, "mdcg"), exist_ok=True)
        with open(os.path.join(legacy, "mdcg", "mem.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(mem)
        with open(os.path.join(legacy, "ledger.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"op":"write"}\n')
        with open(dp.legacy_paths_file(), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        return legacy

    # ① state_root 优先级三档
    def test_state_root_priority(self):
        self.assertEqual(dp.state_root(), os.path.abspath(self.state))
        os.environ.pop("MDCG_STATE_ROOT")
        dsh = os.path.join(self.tmp, "dsh-home")
        os.environ["DSH_HOME"] = dsh
        self.assertEqual(dp.state_root(), os.path.join(os.path.abspath(dsh), ".dsh-memory"))
        os.environ.pop("DSH_HOME")
        self.assertEqual(dp.state_root(),
                         os.path.join(os.path.expanduser("~"), ".dsh", ".dsh-memory"))

    # ③ 默认数据根必须在插件包目录之外（本 issue 的核心不变量）
    def test_default_data_root_outside_package(self):
        root = dp.default_data_root()
        self.assertEqual(root, os.path.join(os.path.abspath(self.state), "data"))
        self.assertFalse(_inside(self.pkg, root),
                         f"默认数据根不得落在插件包内（包={self.pkg} 根本={root}）")

    # ② paths_file 用户级优先 + 旧件兼容读
    def test_paths_file_priority(self):
        self.assertEqual(dp.paths_file(), os.path.join(os.path.abspath(self.state), "paths.json"))
        self.assertEqual(dp.paths_file_source(), "user")
        self._seed_legacy()
        self.assertEqual(dp.paths_file(), dp.legacy_paths_file())    # 新件不存在 → 兼容读旧件
        self.assertEqual(dp.paths_file_source(), "legacy")
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "paths.json"), "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        self.assertEqual(dp.paths_file(), os.path.join(os.path.abspath(self.state), "paths.json"))
        self.assertEqual(dp.paths_file_source(), "user")

    # ④ 默认根生效：复制（不删除/不搬配置/不覆盖/幂等）
    def test_migrate_copies_legacy_data(self):
        legacy = self._seed_legacy()
        first = dp.migrate_legacy_data()
        self.assertTrue(first["ran"], first)
        self.assertGreaterEqual(first["copied"], 1)
        self.assertEqual(_read(self._new_root_path("mdcg", "mem.md")), "MEM-1")
        self.assertTrue(os.path.isfile(self._new_root_path("ledger.jsonl")))
        self.assertFalse(os.path.exists(self._new_root_path("paths.json")),
                         "paths.json 属配置，不随数据面迁移")
        self.assertTrue(os.path.isfile(os.path.join(legacy, "mdcg", "mem.md")),
                        "迁移只复制不删除（旧目录由更新自行移除）")
        second = dp.migrate_legacy_data()
        self.assertFalse(second["ran"], second)
        self.assertIn("已有数据", second["reason"])
        # 不覆盖：旧件改了内容，新件保持不变
        with open(os.path.join(legacy, "mdcg", "mem.md"), "w", encoding="utf-8") as fh:
            fh.write("MEM-2")
        dp.migrate_legacy_data()
        self.assertEqual(_read(self._new_root_path("mdcg", "mem.md")), "MEM-1")

    # ④ 数据根为显式配置 → 不动作（不越权搬运用户的真源）
    def test_migrate_skips_when_root_explicit(self):
        self._seed_legacy()
        explicit = os.path.join(self.tmp, "explicit")
        os.environ["MDCG_DATA_ROOT"] = explicit
        got = dp.migrate_legacy_data()
        self.assertFalse(got["ran"], got)
        self.assertIn("显式配置", got["reason"])
        self.assertFalse(os.path.exists(os.path.join(explicit, "mdcg")))
        self.assertFalse(os.path.exists(self._new_root_path("mdcg")),
                         "显式配置时用户级根不得被写入")

    # ④ 旧位置不存在（多为更新时已随包目录被替换）→ 如实说明，不报成功
    def test_migrate_reports_missing_legacy(self):
        got = dp.migrate_legacy_data()
        self.assertFalse(got["ran"], got)
        self.assertIn("不存在", got["reason"])

    # ⑤ set_user_root 永远写新位置，并带入旧件既有取值
    def test_set_user_root_writes_user_level(self):
        legacy = self._seed_legacy()
        with open(dp.legacy_paths_file(), "w", encoding="utf-8") as fh:
            json.dump({"data_root": "D:/old", "extra": "keep"}, fh)
        written = dp.set_user_root("E:/new", "data_root")
        self.assertEqual(written, os.path.join(os.path.abspath(self.state), "paths.json"))
        with open(written, encoding="utf-8") as fh:
            got = json.load(fh)
        self.assertEqual(got["data_root"], "E:/new")
        self.assertEqual(got["extra"], "keep", "旧件既有键须带入，不丢用户设置")
        self.assertIn("_comment", got)
        with open(dp.legacy_paths_file(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["data_root"], "D:/old", "旧件只读，不被改写")
        self.assertEqual(dp.paths_file_source(), "user")
        self.assertEqual(dp.mdcg_root(), os.path.abspath(os.path.join("E:/new", "mdcg")))
        self.assertTrue(os.path.isdir(legacy))          # 迁移职责不在 set_user_root

    # describe(): 留痕字段齐备（启动日志与心跳消费）
    def test_describe_exposes_sources(self):
        self._seed_legacy()
        got = dp.describe()
        for key in ("plugin_root", "state_root", "data_root", "mdcg_root",
                    "default_data_root", "is_default", "source", "paths_file",
                    "paths_file_source", "legacy_data_root", "legacy_data_exists",
                    "data_root_exists", "mdcg_root_exists"):
            self.assertIn(key, got, f"describe() 缺字段 {key}")
        self.assertEqual(got["paths_file_source"], "legacy")
        self.assertTrue(got["legacy_data_exists"])
        self.assertTrue(got["is_default"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
