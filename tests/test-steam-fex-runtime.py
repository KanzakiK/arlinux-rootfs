import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import steam,steam_fex
class RuntimeSelectionTest(unittest.TestCase):
 def runtime(self,root,app,name,complete=True):
  runtime=root/'steamapps/common'/name
  platform=runtime/(name+'_platform_1.20261016.1');platform.mkdir(parents=True)
  if complete:(platform/'usr-mtree.txt.gz').touch()
  manifest=root/'steamapps'/('appmanifest_'+app+'.acf')
  manifest.write_text('"StateFlags" "4" "installdir" "'+name+'"')
  return runtime,platform
 def test_soldier_without_sniper_prepares_graphics(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);expected=self.runtime(root,'1391110','soldier')
   self.assertEqual(steam_fex.graphics_runtime(root),expected)
   self.runtime(root,'3127680','FEX-Emu')
   self.assertTrue(steam.runtime_installed(root))
 def test_prefers_complete_sniper_and_ignores_incomplete(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);soldier=self.runtime(root,'1391110','soldier')
   sniper=self.runtime(root,'1628350','sniper',False)
   self.assertEqual(steam_fex.graphics_runtime(root),soldier)
   (sniper[1]/'usr-mtree.txt.gz').touch()
   self.assertEqual(steam_fex.graphics_runtime(root),sniper)
 def test_incomplete_depots_do_not_trigger_restart(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);self.runtime(root,'1391110','soldier',False)
   self.runtime(root,'3127680','FEX-Emu')
   self.assertFalse(steam.runtime_installed(root))
   with self.assertRaises(steam_fex.IncompleteRuntime):steam_fex.graphics_runtime(root)
if __name__=='__main__':unittest.main()
