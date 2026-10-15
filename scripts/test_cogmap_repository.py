"""文档链接使用入库的规范仓库地址，fork / 无 Git 源码副本不能改变生成结果。

运行：python -m scripts.test_cogmap_repository（也由 scripts/run_tests.py 自动收集）。
所有 Git 操作只作用于临时合成仓库，不联网、不修改工作区。
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "cogmap_sync", Path(__file__).with_name("cogmap_sync.py"),
)
cogmap_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cogmap_sync)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cogmap-repository-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root_patch = patch.object(cogmap_sync, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.write_repository({"type": "git", "url": "git+https://github.com/example/project.git"})

    def write_repository(self, repository):
        (self.root / "package.json").write_text(
            json.dumps({"repository": repository}), encoding="utf-8",
        )

    def test_fork_origin_does_not_retarget_documentation(self):
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.root), "remote", "add", "origin",
             "https://github.com/contributor/fork.git"], check=True, capture_output=True,
        )
        self.assertEqual(cogmap_sync._repo_base(), "https://github.com/example/project")

    def test_source_archive_needs_no_git_metadata(self):
        self.assertFalse((self.root / ".git").exists())
        self.assertEqual(cogmap_sync._repo_base(), "https://github.com/example/project")

    def test_repository_metadata_is_the_source_of_truth(self):
        for url in (
            "https://github.com/new-owner/new-project",
            "git+https://github.com/new-owner/new-project.git",
            "git@github.com:new-owner/new-project.git",
            "ssh://git@github.com/new-owner/new-project.git",
        ):
            with self.subTest(url=url):
                self.write_repository(url)
                self.assertEqual(cogmap_sync._repo_base(), "https://github.com/new-owner/new-project")

    def test_bad_metadata_fails_instead_of_guessing_from_environment(self):
        for text in (
            "{", "{}", "[]", '{"repository": {}}', '{"repository": null}',
            '{"repository": "https://example.com/owner/project"}',
            '{"repository": "https://github.com.evil.example/owner/project"}',
        ):
            with self.subTest(text=text):
                (self.root / "package.json").write_text(text, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    cogmap_sync._repo_base()
        (self.root / "package.json").unlink()
        with self.assertRaises(SystemExit):
            cogmap_sync._repo_base()


if __name__ == "__main__":
    unittest.main()
