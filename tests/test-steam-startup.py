import importlib.util, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'runtime/tools'))
import steam
class StartupTest(unittest.TestCase):
 def test_launch_prepares_graphics_after_first_session_restart(self):
  import contextlib,steam_bionic,steam_fex,steam_proxy
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);binary=root/'steamrtarm64/steam';binary.parent.mkdir();binary.touch()
   previous=Path.cwd()
   try:
    with patch.object(steam,'client_running',return_value=False),patch.object(steam,'ensure_dependencies'),patch.object(steam,'links'),patch.object(steam_bionic,'configure'),patch.object(steam_proxy,'session',side_effect=contextlib.nullcontext),patch.object(steam,'runtime_installed',side_effect=[False,True]),patch.object(steam,'bootstrap_runtime',return_value=42) as first,patch.object(steam_fex,'configure') as graphics,patch.object(steam.subprocess,'run') as run:
     run.return_value.returncode=0
     self.assertEqual(steam.launch(root,['-gamepadui']),0)
     first.assert_called_once_with(binary,root,['-noipv6','-gamepadui'])
     graphics.assert_called_once_with(root)
     self.assertEqual(run.call_args.args[0],[str(binary),'-noipv6','-gamepadui'])
   finally:os.chdir(previous)
 def test_first_game_depots_trigger_one_normal_restart(self):
  client=MagicMock();client.wait.side_effect=[steam.subprocess.TimeoutExpired('steam',5),steam.subprocess.TimeoutExpired('steam',5),0]
  with patch.object(steam.subprocess,'Popen') as launch, patch.object(steam,'runtime_installed',side_effect=[False,True]), patch.object(steam,'send_client_command') as send:
   launch.return_value.__enter__.return_value=client
   self.assertEqual(steam.bootstrap_runtime(Path('/steam/client'),Path('/steam'),['-gamepadui']),42)
   send.assert_called_once_with(Path('/steam'),['-shutdown'])
   launch.assert_called_once_with(['/steam/client','-gamepadui'])
   client.terminate.assert_not_called();client.kill.assert_not_called()
 def test_exit_or_updater_restart_does_not_request_shutdown(self):
  for status in (0,42,1):
   client=MagicMock();client.wait.return_value=status
   with patch.object(steam.subprocess,'Popen') as launch, patch.object(steam,'send_client_command') as send:
    launch.return_value.__enter__.return_value=client
    self.assertEqual(steam.bootstrap_runtime(Path('/steam/client'),Path('/steam'),[]),status)
    send.assert_not_called()
 def test_busy_client_is_never_force_killed(self):
  client=MagicMock();client.wait.side_effect=[steam.subprocess.TimeoutExpired('steam',5),steam.subprocess.TimeoutExpired('steam',60),0]
  with patch.object(steam.subprocess,'Popen') as launch, patch.object(steam,'runtime_installed',return_value=True), patch.object(steam,'send_client_command') as send:
   launch.return_value.__enter__.return_value=client
   self.assertEqual(steam.bootstrap_runtime(Path('/steam/client'),Path('/steam'),[]),0)
   send.assert_called_once();client.terminate.assert_not_called();client.kill.assert_not_called()
 def test_helpers_wrappers_and_zombies_do_not_block_client_start(self):
  with tempfile.TemporaryDirectory() as temp:
   proc=Path(temp)/'proc';proc.mkdir();client=Path('/shared/steam')
   binary=b'/shared/steam/steamrtarm64/steam'
   commands=[binary,binary+b'webhelper',b'/bin/sh',binary,binary]
   for pid,command in enumerate(commands,1):
    p=proc/str(pid);p.mkdir();(p/'status').write_text('State:\t'+('Z (zombie)' if pid==4 else 'S (sleeping)')+'\n')
    (p/'cmdline').write_bytes(command+b'\0-steampath='+binary+b'\0')
   with patch.object(steam,'Path',side_effect=lambda value:proc if value=='/proc' else Path(value)):
    self.assertEqual(steam.client_processes(client),[1,5])
   (proc/'1/status').unlink()
   with patch.object(steam,'Path',side_effect=lambda value:proc if value=='/proc' else Path(value)):
    self.assertEqual(steam.client_processes(client),[5])
 def test_native_remote_works_without_sniper_and_skips_x86(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for version,machine in [('3',62),('4',183)]:
    remote=root/f'steamapps/common/SteamLinuxRuntime_{version}/pressure-vessel-arm64/bin/steam-runtime-steam-remote'
    remote.parent.mkdir(parents=True);remote.write_bytes(b'\x7fELF\x02\x01'+b'\0'*12+machine.to_bytes(2,'little'))
   with patch.object(steam.subprocess,'run') as run:
    steam.send_client_command(root,['steam://open/main','argument with spaces'])
    self.assertIn('SteamLinuxRuntime_4',run.call_args.args[0][0])
    self.assertEqual(run.call_args.args[0][1:],['steam://open/main','argument with spaces'])
   for remote in root.glob('**/steam-runtime-steam-remote'):remote.unlink()
   with self.assertRaisesRegex(RuntimeError,'no longer running'):
    steam.send_client_command(root,['-shutdown'])
 def test_fifo_forwarding_without_any_runtime_depot(self):
  import shlex
  with tempfile.TemporaryDirectory() as temp:
   home=Path(temp);(home/'.steam').mkdir();pipe=home/'.steam/steam.pipe';os.mkfifo(pipe)
   reader=os.open(pipe,os.O_RDONLY | os.O_NONBLOCK)
   try:
    with patch.object(steam.Path,'home',return_value=home):
     with patch.object(steam,'client_running',return_value=True):
      arguments=['steam://open/main',"space and 'quote'",'中文']
      steam.send_client_command(home,arguments)
      self.assertEqual(shlex.split(os.read(reader,4096).decode()),['~/.steam/root/ubuntu12_32/steam',*arguments])
      with self.assertRaises(ValueError):steam.send_client_command(home,['bad\ncommand'])
      with self.assertRaises(ValueError):steam.send_client_command(home,['x'*5000])
   finally:os.close(reader)
unittest.main()
