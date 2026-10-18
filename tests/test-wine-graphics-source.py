"""Exercise the actual Mesa staging code without compiling the graphics stack."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class MesaSourceTest(unittest.TestCase):
    def test_staging_preserves_dangling_source_symlink(self):
        recipe = Path(__file__).resolve().parents[1] / 'tools/build/wine-bionic-graphics.sh'
        code = recipe.read_text().split("<<'PY'\n", 1)[1].split("prefix = base / 'prefix'", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'source', root / 'output'
            output.mkdir()
            for name in ('src/util/detect_os.h', 'include/vulkan/vk_android_native_buffer.h',
                         'src/util/u_process.c'):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#if defined(__ANDROID__)\n#endif\n')
            link = source / '.github/copilot-instructions.md'
            link.parent.mkdir()
            link.symlink_to('AGENTS.md')
            subprocess.run([sys.executable, '-c', code, str(source), str(output),
                            str(root), str(root), str(root), 'system', 'zink'], check=True)
            staged = output / 'mesa/.github/copilot-instructions.md'
            self.assertTrue(staged.is_symlink())
            self.assertEqual(os.readlink(staged), 'AGENTS.md')
            self.assertIn('#if 0', (output / 'mesa/src/util/detect_os.h').read_text())


    def test_staging_keeps_share_pkgconfig_protocols(self):
        recipe = Path(__file__).resolve().parents[1] / 'tools/build/wine-bionic-graphics.sh'
        code = recipe.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native, output, protocols = root/'native', root/'output', root/'protocols'
            (output/'prefix/lib/pkgconfig').mkdir(parents=True)
            (native/'share/pkgconfig').mkdir(parents=True)
            (native/'lib/pkgconfig').mkdir(parents=True)
            protocols.mkdir()
            text = 'Name: Xproto\nVersion: 7.0.33\n'
            (native/'share/pkgconfig/xproto.pc').write_text(text)
            (native/'lib/pkgconfig/x11.pc').write_text('Name: X11\nVersion: 1.8.10\n')
            (protocols/'arlinux-wsi-protocols.pc').write_text('prefix=${pcfiledir}\n')
            subprocess.run([sys.executable, '-c', code, str(root/'unused'), str(output),
                            str(native), str(root/'ndk'), str(protocols), 'none', 'none'], check=True)
            self.assertEqual((output/'prefix/lib/pkgconfig/xproto.pc').read_text(), text)
            self.assertTrue((output/'prefix/lib/pkgconfig/x11.pc').is_file())


if __name__ == '__main__':
    unittest.main()
