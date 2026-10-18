import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/build'))
from wine_graph import ComponentCache,ComponentComplete

spec=importlib.util.spec_from_file_location('github_component',ROOT/'tools/build/github-component.py')
component=importlib.util.module_from_spec(spec)
spec.loader.exec_module(component)


class CapsuleTest(unittest.TestCase):
    def test_receipt_links_modes_and_corruption_survive_real_capsule_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            framework=root/'framework'
            pipeline=framework/'build/pipeline'
            cache=ComponentCache(pipeline,target='bionic-deps')
            def build(output):
                output.mkdir()
                binary=output/'binary'
                binary.write_bytes(b'compiled ELF fixture')
                binary.chmod(0o755)
                (output/'absolute-link').symlink_to(binary)
                headers=root/'generated-source'
                headers.mkdir()
                (headers/'abi.h').write_text('matching ABI')
                tools=root/'tools'
                tools.mkdir()
                (tools/'include').symlink_to(headers)
                (output/'build-state.json').write_text(json.dumps({'tools':str(tools)}))
            with self.assertRaises(ComponentComplete):
                cache.stage('bionic-deps',{'source':'one'},build)
            data=dict(format=1,stage='bionic-deps',identity='a'*64,
                      framework='b'*40,android='c'*40,dependencies=[])
            env=dict(ARLINUX_WORKSPACE=str(root),GITHUB_REPOSITORY='taowen/arlinux-rootfs')
            with patch.dict(os.environ,env),patch.object(component,'run') as runner, \
                 patch.object(component.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
                component.publish(data,framework)
                self.assertEqual(runner.call_args_list[0].args[:3],('gh','release','create'))
                self.assertEqual(runner.call_args.args[-1].name,'component.json')
            manifest=root/'export/component.json'
            record=json.loads(manifest.read_text())
            self.assertEqual(record['format'],1)
            self.assertTrue(record['parts'])
            shutil.move(pipeline,root/'original-pipeline')
            shutil.move(root/'tools',root/'original-tools')
            shutil.move(root/'generated-source',root/'original-source')
            real_download=component.download
            def download(url,output,expected):
                source=root/'export'/Path(urlparse(url).path).name
                return real_download(source.as_uri(),output,expected)
            reference=dict(identity='a'*64,manifestUrl='https://example.invalid/component.json',
                           manifestSha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
            with patch.object(component,'download',download):
                component.import_dependency(root,reference)
            restored=ComponentCache(pipeline,target='wine-graphics',require_dependencies=True)
            output=restored.stage('bionic-deps',{'source':'one'},lambda _:self.fail('Unexpected rebuild'))
            self.assertTrue(os.access(output/'binary',os.X_OK))
            self.assertEqual(os.readlink(output/'absolute-link'),str(output/'binary'))
            (output/'binary').write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'dependency artifact'):
                restored.stage('bionic-deps',{'source':'one'},lambda _:self.fail('Unexpected rebuild'))


if __name__=='__main__':unittest.main()
