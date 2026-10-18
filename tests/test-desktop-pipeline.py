"""Run on Linux: python3 tests/test-desktop-pipeline.py."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('desktop_build',
    Path(__file__).resolve().parents[1] / 'tools/build/desktop-pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
from pipeline_cache import key as cache_key


class CacheTest(unittest.TestCase):
    def test_reuse_parameters_and_corrupt_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = pipeline.Cache(Path(temporary))
            calls = []
            def build(out):
                calls.append(out)
                out.mkdir()
                (out / 'component').write_text('current source')
            first = cache.stage('bridge', {'compiler': 'one', 'source': 'one'}, build)
            self.assertEqual(cache.stage('bridge', {'compiler': 'one', 'source': 'one'}, build), first)
            self.assertEqual(len(calls), 1)
            (first / 'component').write_text('stale or damaged')
            repaired = cache.stage('bridge', {'compiler': 'one', 'source': 'one'}, build)
            self.assertEqual(len(calls), 2)
            self.assertEqual((repaired / 'component').read_text(), 'current source')
            changed = cache.stage('bridge', {'compiler': 'two', 'source': 'one'}, build)
            self.assertNotEqual(changed, first)
            self.assertEqual(len(calls), 3)

    def test_embedded_absolute_paths_remain_valid_and_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = pipeline.Cache(Path(temporary) / 'cache')
            compiler = Path(temporary) / 'compiler'
            compiler.write_text('compiler v1')
            calls = []
            def build(out):
                import json
                calls.append(out)
                out.mkdir()
                (out / 'prefix.pc').write_text(str(out))
                (out / 'build-state.json').write_text(json.dumps({'compiler': str(compiler)}))
            first = cache.stage('compiler', {}, build)
            self.assertEqual(Path((first / 'prefix.pc').read_text()), first)
            self.assertTrue(first.is_dir())
            cache.stage('compiler', {}, build)
            self.assertEqual(len(calls), 1)
            compiler.write_text('compiler v2')
            second = cache.stage('compiler', {}, build)
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(first, second)

    def test_failed_stage_does_not_replace_verified_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = pipeline.Cache(Path(temporary))
            def good(out):
                out.mkdir()
                (out / 'binary').write_text('verified')
            original = cache.stage('bridge', {}, good)
            def failed(out):
                out.mkdir()
                (out / 'partial').touch()
                raise RuntimeError('compiler failed')
            cache.rebuild = True
            with self.assertRaisesRegex(RuntimeError, 'compiler failed'):
                cache.stage('bridge', {}, failed)
            self.assertEqual((original / 'binary').read_text(), 'verified')
            self.assertFalse((original / 'partial').exists())

    def test_dependency_output_change_invalidates_downstream(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = pipeline.Cache(Path(temporary))
            def build(out):
                out.mkdir()
                (out / 'library').write_text('v1')
            cache.stage('bridge', {'source': 'v1'}, build)
            first = cache_key(cache.records)
            cache.stage('bridge', {'source': 'v2'}, build)
            self.assertNotEqual(first, cache_key(cache.records))

    def test_prepared_source_under_ignored_build_is_not_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            source = repo / 'build/wine-source'
            source.mkdir(parents=True)
            (source / 'header.h').write_text('v1')
            first = pipeline.source_state(source)
            (source / 'header.h').write_text('v2')
            self.assertTrue(first)
            self.assertNotEqual(first, pipeline.source_state(source))

    def test_dirty_and_new_sources_invalidate_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            source = repo / 'header.h'
            source.write_text('v1')
            subprocess.run(['git', '-C', str(repo), 'add', 'header.h'], check=True)
            first = pipeline.source_state(repo)
            source.write_text('v2')
            second = pipeline.source_state(repo)
            self.assertNotEqual(first, second)
            (repo / 'new.patch').write_text('new dependency')
            self.assertNotEqual(second, pipeline.source_state(repo))



if __name__ == '__main__':
    unittest.main()
