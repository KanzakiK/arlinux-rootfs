import importlib.util
from pathlib import Path
import tempfile
import sys
import hashlib
import json
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/build'))
spec=importlib.util.spec_from_file_location('coordinator',Path(__file__).resolve().parents[1]/'tools/build/github-products.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CoordinatorTest(unittest.TestCase):
    def test_cancelled_duplicate_does_not_hide_active_or_successful_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan={'workflow':'component.yml','stages':{'test':{'repository':'owner/component'}}}
            coordinator=module.Coordinator(plan,'f'*40,None,Path(temporary),poll=0)
            request=dict(format=2,stage='test',framework='f'*40,android=None,dependencies=[],sourceInputs={})
            title='arlinux/test/'+module.request_identity(request)
            active=dict(databaseId=1,displayTitle=title,status='in_progress',conclusion=None,url='active')
            cancelled=dict(active,databaseId=2,status='completed',conclusion='cancelled',url='duplicate')
            done=dict(active,status='completed',conclusion='success')
            result={'identity':'verified'}
            with patch.object(coordinator,'existing',side_effect=[None,result]), \
                 patch.object(coordinator,'runs',side_effect=[[active],[cancelled,active],[cancelled,done]]), \
                 patch.object(module,'source_inputs',return_value={}):
                self.assertEqual(coordinator.component('test',[]),result)

    def test_concurrent_coordinators_dispatch_identical_request_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as temporary:
            plan={'workflow':'component.yml','stages':{'test':{'repository':'owner/component'}}}
            state=Path(temporary)
            coordinators=[module.Coordinator(plan,'f'*40,None,state,poll=0) for _ in range(2)]
            result={'identity':'verified'}
            done=dict(databaseId=1,displayTitle='',status='completed',conclusion='success',url='run')
            def runs(repository):
                done['displayTitle']='arlinux/test/'+module.request_identity(dict(
                    format=2,stage='test',framework='f'*40,android=None,dependencies=[],sourceInputs={}))
                return [done] if dispatch.call_count else []
            with patch.object(module.Coordinator,'existing',side_effect=[None,result,result]), \
                 patch.object(module.Coordinator,'runs',side_effect=runs), \
                 patch.object(module,'gh') as dispatch, patch.object(module,'api',return_value=[]), \
                 patch.object(module,'source_inputs',return_value={}):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures=[executor.submit(c.component,'test',[]) for c in coordinators]
                    self.assertEqual([f.result() for f in futures],[result,result])
                self.assertEqual(dispatch.call_count,1)

    def test_local_product_cache_is_verified_before_skipping_download(self):
        import zstandard
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'source'
            source.mkdir()
            (source/'default.zip').write_bytes(b'complete built rootfs fixture')
            (source/'default.json').write_text(json.dumps({'desktopSha256':hashlib.sha256((source/'default.zip').read_bytes()).hexdigest()}))
            archive=root/'capsule.tar'
            with tarfile.open(archive,'w') as target:
                for file in source.iterdir():
                    target.add(file,arcname='framework/build/artifacts/rootfs/yibu/'+file.name)
            part=root/'capsule-000.zst.part'
            part.write_bytes(zstandard.ZstdCompressor().compress(archive.read_bytes()))
            manifest=root/'component.json'
            manifest.write_text(json.dumps(dict(identity='a'*64,stage='yibu',
                archiveSha256=hashlib.sha256(part.read_bytes()).hexdigest(),
                parts=[dict(name=part.name,url=part.as_uri(),sha256=hashlib.sha256(part.read_bytes()).hexdigest())])))
            reference=dict(identity='a'*64,manifestUrl=manifest.as_uri(),
                           manifestSha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
            output=root/'output'
            module.fetch_product(reference,output)
            with patch.object(module,'download',side_effect=RuntimeError('Download required')):
                module.fetch_product(reference,output)
                (output/'default.zip').write_bytes(b'corrupt')
                with self.assertRaisesRegex(RuntimeError,'Download required'):
                    module.fetch_product(reference,output)

    def test_reuses_active_run_and_ignores_previous_failure_after_dispatch(self):
        for resume in (True,False):
            with self.subTest(resume=resume),tempfile.TemporaryDirectory() as temporary:
                plan={'workflow':'arlinux-component.yml','stages':{'test':{'repository':'owner/component'}}}
                coordinator=module.Coordinator(plan,'f'*40,'a'*40,Path(temporary),poll=0)
                import hashlib,json
                request=dict(format=2,stage='test',framework='f'*40,android='a'*40,dependencies=[],sourceInputs={'fixture':'sources'})
                identity=module.request_identity(request)
                title='arlinux/test/'+identity
                old=dict(databaseId=1,displayTitle=title,status='completed',conclusion='failure',url='old')
                active=dict(databaseId=2,displayTitle=title,status='in_progress',conclusion=None,url='new')
                done=dict(active,status='completed',conclusion='success')
                initial=[active,old] if resume else [old]
                with patch.object(coordinator,'existing',side_effect=[None,{'identity':identity}]), \
                     patch.object(coordinator,'runs',side_effect=[initial,[old],[done,old]]), \
                     patch.object(module,'gh') as dispatch,patch.object(module,'api',return_value=[]), patch.object(module,'source_inputs',return_value={'fixture':'sources'}):
                    self.assertEqual(coordinator.component('test',[])['identity'],identity)
                    self.assertEqual(dispatch.call_count,0 if resume else 1)
                    if not resume:
                        self.assertIn('--repo',dispatch.call_args.args)


if __name__=='__main__':unittest.main()
