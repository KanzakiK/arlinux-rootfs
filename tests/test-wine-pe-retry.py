"""Exercise PE build retries with a lightweight compiler/configure fixture."""
from pathlib import Path
import fcntl
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/build/wine-pe.sh'
REVISION = '46af030d975f331ff6304a34a6b91c6147285c6d'


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.source = self.root / 'source'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                        FIXTURE_ROOT=str(self.root), FIXTURE_SOURCE=str(self.source))
        self.write('repo/tools/build/wine-pe.sh', SCRIPT.read_text())
        self.write('source/dlls/combase/parameterized.c', 'fixture')
        self.write('source/VERSION', 'Wine fixture')
        self.write('source/tools/make_requests', '')
        self.write('source/configure', '''#!/bin/sh
printf '%s\\n' "$PWD" >> "$FIXTURE_ROOT/configures"
touch Makefile
''', executable=True)
        self.write('repo/tools/build/refresh-wine-vkd3d.py', '''import pathlib,sys
(pathlib.Path(sys.argv[1])/'arlinux-vkd3d.json').write_text('{}')
''')
        self.write('repo/tools/build/prepare-wine-dcomp.sh', '''#!/bin/sh
printf '{}' > "$1/arlinux-dcomp.json"
''')
        self.write('repo/tools/patches/wine-dcomp-content-lifetime.patch', 'fixture')
        (self.repo/'tools/patches/wine-staging-vkd3d').mkdir()
        for name in ('clang', 'ld.lld'):
            self.write('bin/'+name, 'fixture compiler')
        self.write('bin/gcc', '#!/bin/sh\necho fixture-gcc\n', executable=True)
        self.write('bin/pkg-config', '#!/bin/sh\necho 1.0\n', executable=True)
        self.write('bin/git', f'''#!/bin/sh
case "$*" in
  *rev-parse*) echo {REVISION} ;;
  *archive*) tar -cf - -C "$FIXTURE_SOURCE" . ;;
  *) exit 1 ;;
esac
''', executable=True)
        self.write('bin/make', '''#!/bin/sh
if [ "$1" = --version ]; then echo fixture-make; exit; fi
if [ "$1" = -C ]; then cd "$2"; shift 2; fi
case "$PWD:$*" in
  */core:*install*)
    for arg do case "$arg" in DESTDIR=*) dest=${arg#DESTDIR=} ;; esac; done
    mkdir -p "$dest/usr/local/lib/wine/aarch64-windows"
    echo dll > "$dest/usr/local/lib/wine/aarch64-windows/dcomp.dll" ;;
  */core:*)
    if [ -e "$FIXTURE_ROOT/fail-once" ]; then
        rm "$FIXTURE_ROOT/fail-once"; exit 7
    fi ;;
esac
''', executable=True)

    def write(self, name, content, executable=False):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if executable:
            path.chmod(0o755)

    def build(self, name):
        return subprocess.run(['bash', str(self.repo/'tools/build/wine-pe.sh'),
                               str(self.source), str(self.bin), str(self.root/name)],
                              env=self.env, text=True, capture_output=True)

    def test_failed_compile_resumes_without_reconfigure(self):
        (self.root/'fail-once').touch()
        first = self.build('output')
        self.assertEqual(first.returncode, 7, first.stderr)
        second = self.build('output')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len((self.root/'configures').read_text().splitlines()), 2)
        third = self.build('second-output')
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(len((self.root/'configures').read_text().splitlines()), 2)
        self.assertTrue((self.root/'second-output/files/lib/wine/aarch64-windows/dcomp.dll').is_file())

    def test_concurrent_build_with_same_inputs_is_rejected(self):
        result = self.build('first')
        self.assertEqual(result.returncode, 0, result.stderr)
        stage, = (self.repo/'build/wine-pe').iterdir()
        with (stage/'build.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            blocked = self.build('second')
        self.assertEqual(blocked.returncode, 2)
        self.assertIn('Build already running', blocked.stderr)
        self.assertFalse((self.root/'second').exists())

    def test_changed_patch_uses_new_build(self):
        self.assertEqual(self.build('first').returncode, 0)
        self.write('repo/tools/patches/wine-dcomp-content-lifetime.patch', 'changed')
        result = self.build('second')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len((self.root/'configures').read_text().splitlines()), 4)


if __name__ == '__main__':
    unittest.main()
