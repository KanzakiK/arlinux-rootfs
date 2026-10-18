"""Release seeds must not overwrite a restored Actions generation."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/build'))
spec=importlib.util.spec_from_file_location('component_seed',ROOT/'tools/build/github-component.py')
component=importlib.util.module_from_spec(spec)
spec.loader.exec_module(component)


class CacheSeedTest(unittest.TestCase):
    def test_restored_cache_wins_and_empty_cache_uses_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            framework=root/'framework'
            receipt=framework/'build/pipeline/component'/('a'*64)/'receipt.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{}')
            seed={'identity':'old'}
            request=dict(stage='component',cacheSeed=seed)
            visited=set()
            with patch.object(component,'import_dependency') as restore:
                component.restore_seed(root,framework,request,visited)
                restore.assert_not_called()
                receipt.unlink()
                component.restore_seed(root,framework,request,visited)
                restore.assert_called_once_with(root,seed,visited)
                restore.reset_mock()
                component.restore_seed(root,framework,dict(stage='component'),visited)
                restore.assert_not_called()


if __name__=='__main__':
    unittest.main()
