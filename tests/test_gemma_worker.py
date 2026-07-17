import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


WORKER_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "gemma_worker.py"
SPEC = importlib.util.spec_from_file_location("gemma_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class ExtractionTests(unittest.TestCase):
    def test_strip_thinking_supports_think_and_thinking_tags(self):
        text = "<think>hidden</think><thinking>also hidden</thinking>```python\nx = 1\n```"
        self.assertEqual(worker.strip_thinking(text), "```python\nx = 1\n```")

    def test_extract_code_prefers_matching_language(self):
        text = "```javascript\nconsole.log(1)\n```\n```python\nx = 1\n```"
        self.assertEqual(worker.extract_code(text, "python"), "x = 1\n")

    def test_extract_code_accepts_common_language_alias(self):
        text = "```py\nx = 1\n```"
        self.assertEqual(worker.extract_code(text, "python"), "x = 1\n")

    def test_extract_code_rejects_explicitly_mismatched_language(self):
        text = "```javascript\nconsole.log(1)\n```"
        self.assertIsNone(worker.extract_code(text, "python"))

    def test_extract_code_accepts_crlf_fence(self):
        text = "```python\r\nx = 1\r\n```"
        self.assertEqual(worker.extract_code(text, "python"), "x = 1\r\n")

    def test_extract_code_accepts_untagged_fallback(self):
        text = "```\nx = 1\n```"
        self.assertEqual(worker.extract_code(text, "python"), "x = 1\n")


class ValidationTests(unittest.TestCase):
    def test_python_validation_accepts_valid_source(self):
        result = worker.validate_code("x = 1\n", "python", "example.py")
        self.assertEqual(result.status, "passed")

    def test_python_validation_rejects_invalid_source(self):
        result = worker.validate_code("def broken(:\n", "python", "example.py")
        self.assertEqual(result.status, "failed")
        self.assertIn("invalid syntax", result.message)

    def test_unknown_language_is_reported_as_skipped(self):
        result = worker.validate_code("anything", "madeup", "example.unknown")
        self.assertEqual(result.status, "skipped")

    def test_invalid_expect_pattern_is_reported_before_write(self):
        with self.assertRaisesRegex(ValueError, "invalid --expect regex"):
            worker.compile_expect_pattern("[")


class AtomicWriteTests(unittest.TestCase):
    def test_invalid_code_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "module.py"
            output.write_text("ORIGINAL\n")
            result = worker.validate_and_write(
                "def broken(:\n", output, "python", None, make_backup=True
            )
            self.assertEqual(result.status, "failed")
            self.assertEqual(output.read_text(), "ORIGINAL\n")
            self.assertFalse(output.with_suffix(".py.bak").exists())

    def test_valid_code_replaces_output_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "module.py"
            output.write_text("ORIGINAL\n")
            result = worker.validate_and_write(
                "x = 1\n", output, "python", None, make_backup=True
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(output.read_text(), "x = 1\n")
            self.assertEqual(output.with_suffix(".py.bak").read_text(), "ORIGINAL\n")

    def test_valid_code_preserves_existing_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "tool.py"
            output.write_text("ORIGINAL\n")
            output.chmod(0o755)
            result = worker.validate_and_write(
                "print('ok')\n", output, "python", None, make_backup=True
            )
            self.assertEqual(result.status, "passed")
            self.assertEqual(output.stat().st_mode & 0o777, 0o755)

    def test_backup_symlink_is_rejected_without_touching_victim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            output = root / "module.py"
            victim = root / "victim"
            backup = output.with_suffix(".py.bak")
            output.write_text("ORIGINAL\n")
            victim.write_text("SECRET\n")
            backup.symlink_to(victim)
            with self.assertRaisesRegex(ValueError, "backup path must not be a symlink"):
                worker.validate_and_write(
                    "x = 1\n", output, "python", None, make_backup=True
                )
            self.assertEqual(output.read_text(), "ORIGINAL\n")
            self.assertEqual(victim.read_text(), "SECRET\n")

    def test_expect_failure_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "module.py"
            output.write_text("ORIGINAL\n")
            pattern = worker.compile_expect_pattern(r"class TokenParser")
            result = worker.validate_and_write(
                "x = 1\n", output, "python", pattern, make_backup=True
            )
            self.assertEqual(result.status, "failed")
            self.assertEqual(output.read_text(), "ORIGINAL\n")


class CliErrorTests(unittest.TestCase):
    def test_malformed_config_exits_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "config.json"
            config.write_text("{bad")
            env = os.environ.copy()
            env["GEMMA_CODER_CONFIG"] = str(config)
            result = subprocess.run(
                [sys.executable, str(WORKER_PATH), "--task", "unused.md",
                 "--out", "unused.py"],
                env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid configuration", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
