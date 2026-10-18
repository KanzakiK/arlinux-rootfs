"""Keep only live build generations when saving a hosted cache."""
import json
import os
from pathlib import Path
import re
import shutil


def compact(root, records):
    root = Path(root).resolve()
    references = [Path(path).resolve() for record in records.values()
                  for path in record.get('references', {})]
    removed = 0
    def discard(path):
        nonlocal removed
        if path.is_symlink() or not path.is_dir():
            return
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('Cache cleanup escapes pipeline directory')
        if any(reference.is_relative_to(resolved) or resolved.is_relative_to(reference)
               for reference in references):
            return
        shutil.rmtree(path)
        removed += 1
    for name, record in records.items():
        if not re.fullmatch('[a-z0-9-]+', name):
            raise ValueError('Unsafe cache stage name')
        stage = root/name
        if not stage.is_dir() or stage.is_symlink():
            continue
        for identity in stage.iterdir():
            if not re.fullmatch('[0-9a-f]{64}', identity.name) or identity.is_symlink():
                continue
            if identity.name != record['inputs']:
                discard(identity)
            elif identity.is_dir():
                for generation in identity.iterdir():
                    if (re.fullmatch('generation-[0-9a-f]{32}', generation.name)
                            and generation.name != record['generation']):
                        discard(generation)
    return removed


def main():
    framework = Path(os.environ['ARLINUX_FRAMEWORK'])
    stage = json.loads(os.environ['ARLINUX_COMPONENT_REQUEST'])['stage']
    if stage in ('yibu', 'debian', 'arch', 'omarchy', 'plasma', 'lxqt'):
        receipt = framework/'build/artifacts/rootfs'/stage/'default.json'
        records = json.loads(receipt.read_text())['stages']
    elif stage == 'windows-fonts':
        return
    else:
        receipt = framework/'build/artifacts/components'/(stage+'.json')
        records = json.loads(receipt.read_text())['records']
    print('Removed obsolete cache directories:', compact(framework/'build/pipeline', records), flush=True)


if __name__ == '__main__':
    main()
