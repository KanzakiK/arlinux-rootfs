"""Exercise the actual Mesa staging code without compiling the graphics stack."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class MesaSourceTest(unittest.TestCase):
    def test_msys_metadata_is_adapted_without_changing_native_cache(self):
        recipe = Path(__file__).resolve().parents[1] / 'tools/build/wine-bionic-graphics.sh'
        code = recipe.read_text().split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native, output, protocols = root / 'native', root / 'output', root / 'protocols'
            (native / 'lib/pkgconfig').mkdir(parents=True)
            (output / 'prefix/lib/pkgconfig').mkdir(parents=True)
            protocols.mkdir()
            (protocols / 'arlinux-wsi-protocols.pc').write_text('prefix=${pcfiledir}\n')
            la = native / 'lib/libX11.la'
            original = f"libdir='{native}/lib'\ndependency_libs='{native}/lib/libxcb.la'\n"
            la.write_text(original)
            (native / 'lib/libX11.so').write_text('fixture ELF')
            (native / 'lib/pkgconfig/x11.pc').write_text(f'prefix={native}\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\n')
            subprocess.run([sys.executable, '-c', code, str(root / 'unused'), str(output),
                            str(native), str(root), str(protocols), 'none', 'none'], check=True)
            self.assertEqual(la.read_text(), original)
            self.assertIn(str(output / 'prefix/lib/libxcb.la'), (output / 'prefix/lib/libX11.la').read_text())
            self.assertEqual((output / 'prefix/lib/libX11.so').resolve(), native / 'lib/libX11.so')
            pc = (output / 'prefix/lib/pkgconfig/x11.pc').read_text()
            self.assertIn('libdir=' + str(output / 'prefix/lib'), pc)
            self.assertIn('includedir=${prefix}/include', pc)

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


if __name__ == '__main__':
    unittest.main()
