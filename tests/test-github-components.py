import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/build'))
from wine_graph import ComponentCache, ComponentComplete, required_stages
from pipeline_cache import source_state


class ComponentTest(unittest.TestCase):
    def test_parallel_pe_parts_and_product_boundaries(self):
        self.assertNotIn('wine-pe', required_stages('fex'))
        for arch in ('aarch64','x86_64','i386'):
            selected = required_stages('wine-pe-'+arch)
            self.assertNotIn('fex', selected)
            self.assertFalse(any('wine-pe-'+other in selected for other in
                ('aarch64','x86_64','i386') if other != arch))
        plan=json.loads((ROOT/'tools/build/github-components.json').read_text())
        self.assertEqual(plan['stages']['yibu']['dependencies'], ['linux-mesa','linux-hybris'])
        self.assertFalse(any('wine' in d for d in plan['stages']['yibu']['dependencies']))
        self.assertEqual(plan['stages']['yibu']['runner'], 'ubuntu-24.04-arm')
        self.assertGreaterEqual(len({s['repository'] for s in plan['stages'].values()}),8)
        self.assertNotIn('workflow_call', (ROOT/'tools/build/github-component.workflow.yml').read_text())
        spec=importlib.util.spec_from_file_location('workflow_installer',ROOT/'tools/build/install-github-workflows.py')
        installer=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        rendered=installer.render_workflow(plan,(ROOT/'tools/build/github-component.workflow.yml').read_text()).decode()
        self.assertNotIn('@@',rendered)
        arm=[n for n,s in plan['stages'].items() if s['runner']=='ubuntu-24.04-arm']
        self.assertIn(json.dumps(arm,separators=(',',':')),rendered)
        self.assertEqual(rendered.count('uses: actions/checkout@'),1)
        plan['stages']['yibu']['runner']='paid-larger-runner'
        with self.assertRaisesRegex(ValueError,'free standard runner'):
            installer.render_workflow(plan,rendered)

    def test_missing_dependency_cannot_silently_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=ComponentCache(Path(directory)/'pipeline', target='wine-graphics', require_dependencies=True)
            with self.assertRaisesRegex(RuntimeError,'dependency artifact'):
                cache.stage('bionic-deps', {'input':'one'}, lambda _: self.fail('Unexpected rebuild'))
            self.assertIsNone(cache.stage('wine-pe', {}, lambda _: self.fail('Unexpected PE compilation')))

    def test_selected_component_records_verified_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cache=ComponentCache(root/'pipeline', target='bionic-deps')
            def build(output):
                output.mkdir()
                (output/'library').write_bytes(b'compiled')
            with self.assertRaises(ComponentComplete):
                cache.stage('bionic-deps', {'input':'one'}, build)
            record=json.loads((root/'artifacts/components/bionic-deps.json').read_text())
            expected=hashlib.sha256(b'compiled').hexdigest()
            self.assertEqual(record['records']['bionic-deps']['outputs']['library']['sha256'],expected)

    def test_committing_deletions_preserves_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):
                subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
            git('init','-q')
            (root/'one').write_text('source')
            git('add','one')
            git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','initial')
            (root/'one').unlink()
            before=source_state(root)
            git('add','-u')
            git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','delete')
            self.assertEqual(before,source_state(root))


if __name__=='__main__':
    unittest.main()
