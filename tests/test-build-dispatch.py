"""Verify the supported Linux CLI and reject removed parallel build flows."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildDispatchTest(unittest.TestCase):
    def call(self, *args):
        return subprocess.run(['bash', str(ROOT/'build.sh'), *args], cwd=ROOT,
                              text=True, capture_output=True)

    def test_product_help_uses_current_pipelines(self):
        for target, expected in [('rootfs', '--distribution')]:
            with self.subTest(target=target):
                result = self.call(target, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)

    def test_removed_device_preparation_paths_fail(self):
        for command in ('prepare', 'offline', 'build'):
            with self.subTest(command=command):
                result = self.call(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn('docs/BUILD.md', result.stderr)

    def test_no_arguments_only_prints_usage(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Canonical guide: docs/BUILD.md', result.stdout)


if __name__ == '__main__':
    unittest.main()
