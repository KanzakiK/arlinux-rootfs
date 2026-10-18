import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compact_cache', ROOT/'tools/build/compact-cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CompactionTest(unittest.TestCase):
    def test_architecture_stage_names_containing_underscores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            obsolete=root/'wine-pe-x86_64'/('b'*64)
            obsolete.mkdir(parents=True)
            record=dict(inputs='a'*64,generation='generation-'+'1'*32,references={})
            self.assertEqual(module.compact(root,{'wine-pe-x86_64': record}),1)
            self.assertFalse(obsolete.exists())

    def test_reference_to_parent_directory_keeps_its_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            stage=root/'stage'
            old=stage/('b'*64)/('generation-'+'2'*32)
            old.mkdir(parents=True)
            record=dict(inputs='a'*64,generation='generation-'+'1'*32,references={str(stage): {}})
            self.assertEqual(module.compact(root,{'stage': record}),0)
            self.assertTrue(old.is_dir())

    def test_prunes_obsolete_generations_but_keeps_live_and_referenced_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root/'stage'/('a'*64)/('generation-'+'1'*32)
            stale = root/'stage'/('a'*64)/('generation-'+'2'*32)
            obsolete = root/'stage'/('b'*64)
            referenced = root/'stage'/('c'*64)/'headers'
            unrelated = root/'other'/'keep'
            for path in (active, stale, obsolete, referenced, unrelated):
                path.mkdir(parents=True)
                (path/'file').write_text('build data')
            record = dict(inputs='a'*64, generation=active.name, references={str(referenced): {}})
            self.assertEqual(module.compact(root, {'stage': record}), 2)
            self.assertTrue((active/'file').is_file())
            self.assertTrue((referenced/'file').is_file())
            self.assertTrue((unrelated/'file').is_file())
            self.assertFalse(stale.exists())
            self.assertFalse(obsolete.exists())
            self.assertEqual(module.compact(root, {'stage': record}), 0)


if __name__ == '__main__':
    unittest.main()
