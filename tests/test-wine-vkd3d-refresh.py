import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh', ROOT / 'tools/build/refresh-wine-vkd3d.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RefreshTests(unittest.TestCase):
    def test_wrong_wine_never_runs_patch(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, 'run') as run:
            source = Path(directory)
            (source / 'VERSION').write_text('Wine version 11.6\n')
            with self.assertRaisesRegex(RuntimeError, 'matching Wine'):
                module.refresh(source)
            run.assert_not_called()

    def test_series_is_verified_and_records_all_patches(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, 'run') as run:
            source = Path(directory)
            (source / 'VERSION').write_text('Wine version 11.19\n')
            record = module.refresh(source)
            self.assertEqual(run.call_count, 8)
            self.assertEqual(record['vkd3dCommit'], 'fed0c3418f815b0bc07533f6fc6f4aa06e8712c3')
            self.assertEqual(json.loads((source / 'arlinux-vkd3d.json').read_text()), record)
            module.refresh(source)
            self.assertEqual(run.call_count, 8)

    def test_failed_patch_does_not_write_success_stamp(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, 'run', side_effect=RuntimeError('patch failed')):
            source = Path(directory)
            (source / 'VERSION').write_text('Wine version 11.19\n')
            with self.assertRaisesRegex(RuntimeError, 'patch failed'):
                module.refresh(source)
            self.assertFalse((source / 'arlinux-vkd3d.json').exists())


if __name__ == '__main__':
    unittest.main()
