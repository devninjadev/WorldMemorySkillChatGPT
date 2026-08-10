from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from world_memory.bootstrap import ensure_runtime_dependencies  # noqa: E402


class DependencyBootstrapTests(unittest.TestCase):
    def test_missing_yfinance_dependencies_are_installed_to_isolated_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installed = False
            commands: list[list[str]] = []
            runtime_path: list[str] = []
            target = Path(directory) / "deps"

            def importer(_: str) -> object:
                if not installed:
                    raise AssertionError("imports must follow installation")
                return object()

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                nonlocal installed
                commands.append(command)
                installed = True
                return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")

            receipt = ensure_runtime_dependencies(
                required_modules=("yfinance", "pandas", "numpy"),
                requirements_path=SKILL_ROOT / "requirements.txt",
                target_dir=target,
                availability_checker=lambda _: object() if installed else None,
                importer=importer,
                runner=runner,
                runtime_path=runtime_path,
                executable="/runtime/python",
            )

            self.assertTrue(receipt["installed"])
            self.assertEqual(receipt["missing_after"], [])
            self.assertEqual(runtime_path[0], str(target))
            self.assertEqual(commands[0][:5], [
                "/runtime/python",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
            ])
            self.assertIn("--target", commands[0])
            self.assertIn("--timeout", commands[0])


if __name__ == "__main__":
    unittest.main()
