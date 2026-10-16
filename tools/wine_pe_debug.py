"""Remove PE debug data while preserving every section used at runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def pe_sections(path):
    data = path.read_bytes()
    if data[:2] != b'MZ':
        return None
    offset = struct.unpack_from('<I', data, 60)[0]
    if data[offset:offset + 4] != b'PE\0\0':
        return None
    machine, count = struct.unpack_from('<HH', data, offset + 4)
    symbols, symbol_count = struct.unpack_from('<II', data, offset + 12)
    optional_size = struct.unpack_from('<H', data, offset + 20)[0]
    strings = symbols + symbol_count * 18 if symbols else 0
    sections = {}
    debug = False
    for index in range(count):
        entry = offset + 24 + optional_size + index * 40
        name = data[entry:entry + 8].rstrip(b'\0')
        if name.startswith(b'/'):
            start = strings + int(name[1:])
            name = data[start:data.index(b'\0', start)]
        virtual_size, rva, size, raw = struct.unpack_from('<IIII', data, entry + 8)
        if name.startswith(b'.debug'):
            debug = True
            continue
        flags = struct.unpack_from('<I', data, entry + 36)[0]
        sections[name] = (virtual_size, rva, size, flags,
                          hashlib.sha256(data[raw:raw + min(size, virtual_size)]).hexdigest())
    return machine, sections, debug


def optimize(root, strip, remove_x64=True):
    files = root / 'files'
    before = sum(p.stat().st_size for p in files.rglob('*') if p.is_file() and not p.is_symlink())
    removed = stripped = 0
    if remove_x64:
        import shutil
        directory = files / 'lib/wine/x86_64-windows'
        if directory.is_dir():
            shutil.rmtree(directory)
    for path in sorted(files.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in ('.pdb', '.dbg'):
            path.unlink()
            removed += 1
            continue
        if path.suffix.lower() not in ('.dll', '.exe'):
            continue
        original = pe_sections(path)
        if original is None or not original[2]:
            continue
        subprocess.run([str(strip), '--strip-debug', str(path)], check=True)
        updated = pe_sections(path)
        if updated is None or updated[:2] != original[:2] or updated[2]:
            raise RuntimeError('Stripping changed runtime PE sections: ' + str(path))
        stripped += 1
    after = sum(p.stat().st_size for p in files.rglob('*') if p.is_file() and not p.is_symlink())
    print(f'PE debug stripped: {stripped}; debug files removed: {removed}; '
          f'files bytes: {before} -> {after}', flush=True)
    return dict(debugSymbols=False, standaloneX64Dlls=not remove_x64)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('--strip', type=Path, required=True)
    args = parser.parse_args()
    manifest = args.runtime / 'bionic-runtime.json'
    metadata = json.loads(manifest.read_text())
    metadata['packaging'] = optimize(args.runtime, args.strip)
    metadata['files'] = {}
    for path in sorted((args.runtime / 'files').rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                metadata['files'][path.relative_to(args.runtime).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest.write_text(json.dumps(metadata, indent=2) + '\n')
