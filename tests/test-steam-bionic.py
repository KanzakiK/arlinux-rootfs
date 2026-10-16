import importlib.util,os,sys,tempfile,types,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'runtime/tools'))
spec=importlib.util.spec_from_file_location('steam_bionic',root/'runtime/tools/steam_bionic.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class AdapterTest(unittest.TestCase):
 def test_discovery_helpers_do_not_open_steamworks_session(self):
  for identity in [None, '0', '000']:
   calls=[]
   fake=types.SimpleNamespace(ensure_runtime=lambda:Path('/runtime'),run=lambda *a,**k:(calls.append((a,k)) or types.SimpleNamespace(returncode=0)))
   environment={'STEAM_COMPAT_DATA_PATH':'/compat'}
   if identity is not None:environment['SteamAppId']=identity
   with patch.dict(sys.modules,windows=fake,steamworks=None,windows_webview=types.SimpleNamespace(prepare_game=lambda r,p,e,env:env)),patch.dict(os.environ,environment,clear=True):
    self.assertEqual(module.launch('run',['/helper.exe','--probe']),0)
   self.assertEqual(calls[0][0][2:],('/helper.exe',['--probe']))
 def test_registration_and_preservation(self):
  with tempfile.TemporaryDirectory() as temp:
   steam=Path(temp);tool=module.register(steam);self.assertEqual(module.register(steam),tool)
   self.assertIn('/run %verb%',(tool/'toolmanifest.vdf').read_text());self.assertIn(module.TOOL,(tool/'compatibilitytool.vdf').read_text())
   (tool/'arlinux-backend.json').write_text('{}')
   with self.assertRaises(RuntimeError):module.register(steam)
 def test_launch_arguments_identity_and_exit(self):
  calls=[]
  fake=types.SimpleNamespace(ensure_runtime=lambda:Path('/runtime'),run=lambda *a,**k:(calls.append((a,k)) or types.SimpleNamespace(returncode=101)))
  with patch.dict(sys.modules,windows=fake,steamworks=types.SimpleNamespace(session=lambda *a:nullcontext('/launcher.exe')),windows_webview=types.SimpleNamespace(prepare_game=lambda r,p,e,env:env)),patch.dict(os.environ,{'STEAM_COMPAT_DATA_PATH':'/arlinux-shared/steam/compatdata/2758540','SteamAppId':'2758540','LD_LIBRARY_PATH':'/wrong/libc'},clear=True):
   self.assertEqual(module.launch('waitforexitandrun',['/games/我的小鲨鱼.exe','argument with spaces']),101)
  self.assertEqual(calls[0][0][2:],('/launcher.exe',['/games/我的小鲨鱼.exe','argument with spaces']));self.assertEqual(calls[0][1]['env'],{'SteamAppId':'2758540'})
 def test_diagnostics_reach_host_without_guest_driver_paths(self):
  calls=[]
  fake=types.SimpleNamespace(ensure_runtime=lambda:Path('/runtime'),run=lambda *a,**k:(calls.append(k) or types.SimpleNamespace(returncode=0)))
  environment={'STEAM_COMPAT_DATA_PATH':'/compat','SteamAppId':'1782460','WINEDEBUG':'+rawinput','ARLINUX_EXCEPTION_LOG':'1','LD_LIBRARY_PATH':'/guest/glibc','VK_ICD_FILENAMES':'/guest/icd.json','WINEDLLOVERRIDES':'d3d11=b'}
  with patch.dict(sys.modules,windows=fake,steamworks=types.SimpleNamespace(session=lambda *a:nullcontext('/launcher.exe')),windows_webview=types.SimpleNamespace(prepare_game=lambda r,p,e,env:env)),patch.dict(os.environ,environment,clear=True):
   self.assertEqual(module.launch('waitforexitandrun',['/games/Hell Clock.exe']),0)
  self.assertEqual(calls[0]['env'],{'SteamAppId':'1782460','WINEDEBUG':'+rawinput','ARLINUX_EXCEPTION_LOG':'1'})
 def test_expendabros_uses_d3d11_and_preserves_explicit_renderer(self):
  calls=[]
  fake=types.SimpleNamespace(ensure_runtime=lambda:Path('/runtime'),run=lambda *a,**k:(calls.append(a) or types.SimpleNamespace(returncode=0)))
  with patch.dict(sys.modules,windows=fake,steamworks=types.SimpleNamespace(session=lambda *a:nullcontext('/launcher.exe')),windows_webview=types.SimpleNamespace(prepare_game=lambda r,p,e,env:env)),patch.dict(os.environ,{'STEAM_COMPAT_DATA_PATH':'/compat','SteamAppId':'312990'},clear=True):
   for args in (['/games/Expendabros.exe'],['/games/Expendabros.exe','-force-opengl'],['/games/Other.exe']):
    self.assertEqual(module.launch('run',args),0)
  self.assertEqual(calls[0][3],['/games/Expendabros.exe','-force-d3d11'])
  self.assertEqual(calls[1][3],['/games/Expendabros.exe','-force-opengl'])
  self.assertEqual(calls[2][3],['/games/Other.exe'])
 def test_invalid_operations_and_prefix(self):
  with patch.dict(sys.modules,windows=types.SimpleNamespace()),patch.dict(os.environ,{},clear=True):
   for verb,args in [('bogus',['game']),('run',[]),('run',['game'])]:
    with self.assertRaises(ValueError):module.launch(verb,args)
  with patch.dict(sys.modules,windows=types.SimpleNamespace()),patch.dict(os.environ,{'STEAM_COMPAT_DATA_PATH':'/compat','SteamAppId':'1; command'},clear=True):
   with self.assertRaises(ValueError):module.launch('run',['game'])
 def test_default_migration_preserves_explicit_choices(self):
  from steam import keyvalues
  config='"InstallConfigStore" { "Software" { "Valve" { "Steam" { "Other" "unchanged" "CompatToolMapping" { "0" { "name" "proton_11" } "2758540" { "name" "arlinux-proton-arm64" "priority" "250" } "10" { "name" "proton_11" } "11" { "name" "third-party" } "12" { "name" "SteamLinuxRuntime_fex" } } } } } }'
  updated=module.default_config(config)
  mapping=keyvalues(updated)['InstallConfigStore']['Software']['Valve']['Steam']['CompatToolMapping']
  self.assertEqual(mapping['0']['name'],module.TOOL)
  self.assertEqual(mapping['2758540']['name'],module.TOOL)
  self.assertEqual(mapping['2758540']['priority'],'250')
  self.assertEqual(mapping['10']['name'],'proton_11')
  self.assertEqual(mapping['11']['name'],'third-party')
  self.assertEqual(mapping['12']['name'],'SteamLinuxRuntime_fex')
  self.assertIn('"Other" "unchanged"',updated)
  self.assertEqual(module.default_config(updated),updated)
 def test_native_windows_default_uses_bionic_without_changing_game_choices(self):
  from steam import keyvalues
  base='"InstallConfigStore" { "Software" { "Valve" { "Steam" { "CompatToolMapping" { "0" { "name" "%s" } "2758540" { "name" "native" } "10" { "name" "third-party" } } } } } }'
  for name in ('native','Native','NATIVE'):
   with self.subTest(name=name):
    updated=module.default_config(base%name)
    mapping=keyvalues(updated)['InstallConfigStore']['Software']['Valve']['Steam']['CompatToolMapping']
    self.assertEqual(mapping['0']['name'],module.TOOL)
    self.assertEqual(mapping['2758540']['name'],'native')
    self.assertEqual(mapping['10']['name'],'third-party')
    self.assertEqual(module.default_config(updated),updated)
 def test_helltaker_default_preserves_explicit_native_choice(self):
  from steam import keyvalues
  base='"InstallConfigStore" { "Software" { "Valve" { "Steam" { "CompatToolMapping" { %s } } } } }'
  for entry,expected in [('',module.TOOL),('"0" { "name" "native" }',module.TOOL),('"1289310" { "name" "SteamLinuxRuntime_fex" }','SteamLinuxRuntime_fex')]:
   updated=module.default_config(base%entry)
   mapping=keyvalues(updated)['InstallConfigStore']['Software']['Valve']['Steam']['CompatToolMapping']
   self.assertEqual(mapping['1289310']['name'],expected)
   self.assertEqual(module.default_config(updated),updated)
 def test_first_install_has_default_before_first_login(self):
  from steam import keyvalues
  with tempfile.TemporaryDirectory() as temp:
   steam=Path(temp)
   module.configure(steam)
   config=steam/'config/config.vdf'
   mapping=keyvalues(config.read_text())['InstallConfigStore']['Software']['Valve']['Steam']['CompatToolMapping']
   self.assertEqual(mapping['0']['name'],module.TOOL)
   self.assertFalse((steam/'config/config.vdf.before-arlinux-bionic').exists())
   first=config.read_bytes();module.configure(steam);self.assertEqual(config.read_bytes(),first)
 def test_missing_mapping_and_configuration_backup(self):
  from steam import keyvalues
  original='"InstallConfigStore" { "Software" { "Valve" { "Steam" { "Other" "unchanged" } } } }'
  with tempfile.TemporaryDirectory() as temp:
   steam=Path(temp);(steam/'config').mkdir();config=steam/'config/config.vdf';config.write_text(original)
   module.configure(steam)
   self.assertEqual((steam/'config/config.vdf.before-arlinux-bionic').read_text(),original)
   self.assertEqual(keyvalues(config.read_text())['InstallConfigStore']['Software']['Valve']['Steam']['CompatToolMapping']['0']['name'],module.TOOL)
   updated=config.read_bytes();module.configure(steam);self.assertEqual(config.read_bytes(),updated)
unittest.main()
