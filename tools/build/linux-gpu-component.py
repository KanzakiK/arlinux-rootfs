#!/usr/bin/env python3
"""Expose the existing Linux GPU recipes as independently cached components."""
import argparse
import json
from pathlib import Path
import platform
import subprocess

from pipeline_cache import Cache,digest,inventory,source_state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=('mesa','hybris'),required=True)
    args=parser.parse_args()
    framework=Path(__file__).resolve().parents[2]
    name='linux-'+args.component
    inputs=dict(component=args.component,engine=digest(__file__),
        recipe=inventory(framework/'tools/build/linux-gpu.sh'),
        cross=inventory(framework/'tools/build/linux-aarch64.ini'),
        protocols=inventory(framework/'third_party/libhybris/arlinux/graphics-protocols'),
        sources={p:source_state(framework/p) for p in
            ('third_party/mesa','third_party/libhybris','third_party/android-headers')},
        architecture=platform.machine(),
        tools={tool:subprocess.check_output([tool,'--version'],text=True)
               for tool in ('aarch64-linux-gnu-gcc','meson','ninja','pkg-config')})
    cache=Cache(framework/'build/pipeline')
    def build(output):
        subprocess.run(['bash',str(framework/'tools/build/linux-gpu.sh'),args.component],check=True)
        output.mkdir()
        prefix=framework/('build/linux/mesa' if args.component=='mesa' else 'build/linux/libhybris/install')
        receipt=framework/('build/linux/gpu.'+args.component+'.outputs.json')
        (output/'build-state.json').write_text(json.dumps(dict(prefix=str(prefix),receipt=str(receipt)))+'\n')
    output=cache.stage(name,inputs,build)
    descriptor=framework/'build/artifacts/components'/f'{name}.json'
    descriptor.parent.mkdir(parents=True,exist_ok=True)
    descriptor.write_text(json.dumps(dict(format=1,stage=name,output=str(output),records=cache.records),sort_keys=True)+'\n')


if __name__=='__main__':main()
