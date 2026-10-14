import importlib.util,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('steam_bionic',root/'runtime/tools/steam_bionic.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class AdapterTest(unittest.TestCase):
 def test_registration_and_preservation(self):
  with tempfile.TemporaryDirectory() as temp:
   steam=Path(temp);tool=module.register(steam);self.assertEqual(module.register(steam),tool)
   self.assertIn('/run %verb%',(tool/'toolmanifest.vdf').read_text());self.assertIn(module.TOOL,(tool/'compatibilitytool.vdf').read_text())
   (tool/'arlinux-backend.json').write_text('{}')
   with self.assertRaises(RuntimeError):module.register(steam)
 def test_launch_arguments_identity_and_exit(self):
  calls=[]
  fake=types.SimpleNamespace(ensure_runtime=lambda:Path('/runtime'),run=lambda *a,**k:(calls.append((a,k)) or types.SimpleNamespace(returncode=101)))
  with patch.dict(sys.modules,windows=fake),patch.dict(os.environ,{'STEAM_COMPAT_DATA_PATH':'/arlinux-shared/steam/compatdata/2758540','SteamAppId':'2758540','LD_LIBRARY_PATH':'/wrong/libc'},clear=True):
   self.assertEqual(module.launch('waitforexitandrun',['/games/我的小鲨鱼.exe','argument with spaces']),101)
  self.assertEqual(calls[0][0][2:],('/games/我的小鲨鱼.exe',['argument with spaces']));self.assertEqual(calls[0][1]['env'],{'SteamAppId':'2758540'})
 def test_invalid_operations_and_prefix(self):
  with patch.dict(sys.modules,windows=types.SimpleNamespace()),patch.dict(os.environ,{},clear=True):
   for verb,args in [('bogus',['game']),('run',[]),('run',['game'])]:
    with self.assertRaises(ValueError):module.launch(verb,args)
  with patch.dict(sys.modules,windows=types.SimpleNamespace()),patch.dict(os.environ,{'STEAM_COMPAT_DATA_PATH':'/compat','SteamAppId':'1; command'},clear=True):
   with self.assertRaises(ValueError):module.launch('run',['game'])
unittest.main()
