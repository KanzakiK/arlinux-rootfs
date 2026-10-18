"""Application updates must not reinstall unchanged distribution packages."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/build'))
from component_inputs import package_inputs


class PackageInputsTest(unittest.TestCase):
    def test_current_seed_refreshes_applications_without_invalidating_packages(self):
        def inputs(name, content):
            return package_inputs(dict(engine='recipe', gpu={'mesa': 'binary'}, sources={
                'runtime/tools': {name: content, 'build-desktop.sh': 'install packages'},
                'distributions/yibu': 'pinned package recipe'}))
        for name in ('windows.py', 'shared.py', 'windows-downloads.tsv', 'arlinux-windows.desktop', 'fontforge.png'):
            with self.subTest(name=name):
                self.assertEqual(inputs(name, 'before'), inputs(name, 'after'))
        for name in ('install-mesa-arch.sh', 'guest-sudo.c', 'bwrap-view.h', 'arlinux-steam'):
            with self.subTest(name=name):
                self.assertNotEqual(inputs(name, 'before'), inputs(name, 'after'))

    def test_package_recipe_gpu_and_base_sources_still_invalidate(self):
        baseline = dict(engine='recipe', gpu={'mesa': 'before'}, sources={'runtime/tools': {}, 'distribution': 'before'})
        self.assertNotEqual(package_inputs(baseline), package_inputs(dict(baseline, gpu={'mesa': 'after'})))
        self.assertNotEqual(package_inputs(baseline), package_inputs(dict(baseline, engine='changed recipe')))
        self.assertNotEqual(package_inputs(baseline), package_inputs(dict(baseline, sources={'runtime/tools': {}, 'distribution': 'after'})))


if __name__ == '__main__':
    unittest.main()
