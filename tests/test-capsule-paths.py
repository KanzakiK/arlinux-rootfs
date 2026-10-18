"""Streaming extraction must reject archive paths before writing outside the workspace."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zstandard

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/build'))
spec=importlib.util.spec_from_file_location('component_paths',ROOT/'tools/build/github-component.py')
component=importlib.util.module_from_spec(spec)
spec.loader.exec_module(component)


class CapsulePathsTest(unittest.TestCase):
    def test_parent_traversal_and_escaping_links_are_rejected(self):
        for link in (False,True):
            with self.subTest(link=link),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary)
                workspace=directory/'workspace'
                workspace.mkdir()
                raw=io.BytesIO()
                with tarfile.open(fileobj=raw,mode='w') as output:
                    member=tarfile.TarInfo('link' if link else '../escaped')
                    if link:
                        member.type=tarfile.SYMTYPE
                        member.linkname='../escaped'
                    else:
                        member.size=4
                    output.addfile(member,None if link else io.BytesIO(b'data'))
                part=directory/'capsule.part'
                part.write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
                digest=hashlib.sha256(part.read_bytes()).hexdigest()
                manifest=directory/'component.json'
                manifest.write_text(json.dumps(dict(identity='a'*64,dependencies=[],
                    archiveSha256=digest,parts=[dict(name=part.name,url=part.as_uri(),sha256=digest)])))
                reference=dict(identity='a'*64,manifestUrl=manifest.as_uri(),
                    manifestSha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
                with self.assertRaises((ValueError,tarfile.FilterError)):
                    component.import_dependency(workspace,reference)
                self.assertFalse((directory/'escaped').exists())


if __name__=='__main__':
    unittest.main()
