"""Exercise the real cross-file compiler commands with an isolated ccache."""
import ast
import configparser
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CompilerCacheTest(unittest.TestCase):
    def test_c_and_cpp_cross_compilers_reuse_identical_objects(self):
        config=configparser.ConfigParser()
        config.read(ROOT/'tools/build/linux-aarch64.ini')
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            env=dict(os.environ,CCACHE_DIR=str(directory/'cache'))
            for language,suffix in (('c','.c'),('cpp','.cpp')):
                with self.subTest(language=language):
                    compiler=ast.literal_eval(config['binaries'][language])
                    self.assertEqual(compiler[0],'ccache')
                    source=directory/('fixture'+suffix)
                    source.write_text('int answer(void) { return 42; }\n')
                    output=directory/(language+'.o')
                    command=[*compiler,'-c',str(source),'-o',str(output)]
                    subprocess.run(command,env=env,check=True,capture_output=True)
                    original=output.read_bytes()
                    output.unlink()
                    subprocess.run(command,env=env,check=True,capture_output=True)
                    self.assertEqual(output.read_bytes(),original)
            stats=dict(line.split() for line in subprocess.check_output(
                ['ccache','--print-stats'],env=env,text=True).splitlines())
            hits=sum(int(value) for name,value in stats.items() if name.endswith('cache_hit'))
            self.assertGreaterEqual(hits,2)
            print('Isolated C/C++ compiler-cache hits:',hits,flush=True)


if __name__=='__main__':
    unittest.main()
