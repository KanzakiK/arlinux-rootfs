import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('coordinator',Path(__file__).resolve().parents[1]/'tools/build/github-products.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CoordinatorTest(unittest.TestCase):
    def test_reuses_active_run_and_ignores_previous_failure_after_dispatch(self):
        for resume in (True,False):
            with self.subTest(resume=resume),tempfile.TemporaryDirectory() as temporary:
                plan={'workflow':'arlinux-component.yml','stages':{'test':{'repository':'owner/component'}}}
                coordinator=module.Coordinator(plan,'f'*40,'a'*40,Path(temporary),poll=0)
                import hashlib,json
                request=dict(format=1,stage='test',framework='f'*40,android='a'*40,dependencies=[])
                identity=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
                title='arlinux/test/'+identity
                old=dict(databaseId=1,displayTitle=title,status='completed',conclusion='failure',url='old')
                active=dict(databaseId=2,displayTitle=title,status='in_progress',conclusion=None,url='new')
                done=dict(active,status='completed',conclusion='success')
                initial=[active,old] if resume else [old]
                with patch.object(coordinator,'existing',side_effect=[None,{'identity':identity}]), \
                     patch.object(coordinator,'runs',side_effect=[initial,[old],[done,old]]), \
                     patch.object(module,'gh') as dispatch:
                    self.assertEqual(coordinator.component('test',[])['identity'],identity)
                    self.assertEqual(dispatch.call_count,0 if resume else 1)
                    if not resume:
                        self.assertIn('--repo',dispatch.call_args.args)


if __name__=='__main__':unittest.main()
