#!/usr/bin/env python3
"""Install the one canonical workflow wrapper in each component repository."""
import argparse
import base64
import json
from pathlib import Path
import subprocess


def api(path, payload=None, optional=False):
    command=['gh','api',path]
    if payload is not None:
        command+=['--method','PUT','--input','-']
    result=subprocess.run(command,input=json.dumps(payload) if payload is not None else None,
                          capture_output=True,text=True)
    if result.returncode:
        if optional:return None
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    directory=Path(__file__).resolve().parent
    plan=json.loads((directory/'github-components.json').read_text())
    workflow=(directory/'github-component.workflow.yml').read_bytes()
    for repository in sorted({s['repository'] for s in plan['stages'].values()}):
        metadata=api('repos/'+repository)
        if metadata['private']:
            raise ValueError('Free standard runner builds require a public component repository')
        path='repos/'+repository+'/contents/.github/workflows/'+plan['workflow']
        current=api(path,optional=True)
        if current and base64.b64decode(current['content'])==workflow:
            print('OK workflow '+repository,flush=True)
            continue
        if args.check:
            raise ValueError('Missing or stale standalone component workflow: '+repository)
        payload=dict(message='ci: enable standalone ARLinux component builds [skip ci]',
                     content=base64.b64encode(workflow).decode(),branch=metadata['default_branch'])
        if current:payload['sha']=current['sha']
        result=api(path,payload)
        print('Installed '+repository+' '+result['commit']['sha'],flush=True)


if __name__=='__main__':main()
