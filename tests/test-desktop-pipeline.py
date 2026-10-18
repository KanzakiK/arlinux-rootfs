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
            first = pipeline.key(cache.records)
            cache.stage('bridge', {'source': 'v2'}, build)
            self.assertNotEqual(first, pipeline.key(cache.records))

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


spec_wine = importlib.util.spec_from_file_location('wine_pipeline',
    Path(__file__).resolve().parents[1] / 'tools/build/wine-pipeline.py')
wine_pipeline = importlib.util.module_from_spec(spec_wine)
spec_wine.loader.exec_module(wine_pipeline)


class WineGraphTest(unittest.TestCase):
    def test_source_chain_passes_matching_native_and_pe_inputs_and_reuses_stages(self):
        import json
        import tarfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = pipeline.Cache(root / 'cache')
            (root / 'tools').mkdir()
            (root / 'arial.ttf').write_text('fixture font')
            (root / 'tools/wine_fonts.py').write_text(
                "from pathlib import Path\nFILES = ('arial.ttf',)\n"
                "def source_directory(): return Path(__file__).resolve().parents[1]\n")
            env, calls = {}, []
            paths = {name: root / name for name in ('wineSource', 'mingw', 'ndk', 'bionicPrefix', 'addons')}
            common = dict(sources={}, wineSources={'commit': 'pinned'}, pulseRecipe={})
            def invoke(*command):
                calls.append(command)
                recipe = Path(command[1]).name
                out = Path(command[-1])
                if recipe == 'pulseaudio.sh':
                    out = Path(env['ARLINUX_PULSE_WORK']) / 'prefix'
                    out.mkdir(parents=True)
                elif recipe == 'package-wine-pe.py':
                    source = out.parent / 'dummy'
                    source.write_text('PE modules')
                    with tarfile.open(out, 'w:gz') as archive:
                        archive.add(source, arcname='pe-module')
                    for name in ('wine', 'fex', 'dxvk'):
                        (out.parent / f'pe-{name}-source.tar.gz').write_text(name)
                elif recipe == 'wine-pe.sh':
                    tools = out / 'tools'
                    tools.mkdir(parents=True)
                    (tools / 'winegcc').write_text('matching compiler')
                    (out / 'files/lib/wine').mkdir(parents=True)
                    (out / 'build-state.json').write_text(json.dumps({'tools': str(tools)}))
                elif recipe == 'wine-bionic.sh':
                    out.mkdir()
                    for name in ('source', 'core'):
                        (out / name).mkdir()
                        (out / name / 'abi').write_text('native ABI')
                    (out / 'build-state.json').write_text(json.dumps({n: str(out/n) for n in ('source', 'core')}))
                    Path(env['BIONIC_ARCHIVE']).write_text('Bionic Wine archive')
                    self.assertEqual(env['BIONIC_VULKAN_DRIVER'], 'system')
                    self.assertEqual(env['BIONIC_OPENGL'], 'zink')
                    self.assertTrue(Path(env['BIONIC_PULSE_PREFIX']).is_dir())
                    self.assertTrue(Path(env['BIONIC_SYSTEM_VULKAN_ADAPTER']).is_file())
                    self.assertTrue((Path(command[-2]) / 'pe-module').is_file())
                else:
                    out.mkdir()
                    (out / 'prefix').mkdir()
                    if recipe == 'bionic-vulkan.py':
                        (out / 'libvulkan_android_desktop.so').touch()
            archive = wine_pipeline.build_wine(cache, root, root, paths.copy(), common, invoke, env)
            self.assertEqual(archive.read_text(), 'Bionic Wine archive')
            self.assertTrue((archive.parent / 'pe-fex-source.tar.gz').is_file())
            self.assertEqual(len(calls), 9)
            self.assertNotIn('BIONIC_ARCHIVE', env)
            again = wine_pipeline.build_wine(cache, root, root, paths.copy(), common, invoke, env)
            self.assertEqual(archive, again)
            self.assertEqual(len(calls), 9)


if __name__ == '__main__':
    unittest.main()
