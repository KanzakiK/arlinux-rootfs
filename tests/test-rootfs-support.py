"""Rootfs consumes immutable compatibility support without building Android code."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rootfs_pipeline',
    Path(__file__).resolve().parents[1] / 'tools/build/desktop-pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class SupportTest(unittest.TestCase):
    def test_only_matching_runtime_build_cache_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            framework = Path(temporary)
            cache = pipeline.Cache(framework / 'build/pipeline')
            def build(out):
                out.mkdir()
                (out / 'helper').write_text('current compiled support')
            support = cache.stage('runtime-support', {'recipe': 'current'}, build)
            artifact = framework / 'build/artifacts/wine/runtime.json'
            artifact.parent.mkdir(parents=True)
            record = dict(format=1, support=str(support), supportSources={'abi': 'current'}, stages=cache.records)
            artifact.write_text(json.dumps(record))
            with patch.object(pipeline, 'support_sources', return_value={'abi': 'current'}):
                self.assertEqual(pipeline.compatibility_support(framework)[0], support)
                (support / 'helper').write_text('broken helper')
                with self.assertRaisesRegex(ValueError, 'receipt'):
                    pipeline.compatibility_support(framework)
            with patch.object(pipeline, 'support_sources', return_value={'abi': 'newer'}):
                with self.assertRaisesRegex(ValueError, 'stale'):
                    pipeline.compatibility_support(framework)


if __name__ == '__main__':
    unittest.main()
