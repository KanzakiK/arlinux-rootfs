#!/usr/bin/env python3
"""Dispatch independent repository workflows from Windows or Linux, without WSL."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
from threading import Event
import urllib.request


def gh(*args, optional=False):
    result = subprocess.run(['gh', *map(str,args)], capture_output=True, text=True)
    if result.returncode:
        if optional:
            return None
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def api(path, optional=False):
    value = gh('api', path, optional=optional)
    return json.loads(value) if value else None


def download(url, output, expected):
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as source, output.open('wb') as dest:
        import shutil
        shutil.copyfileobj(source,dest)
    with output.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest() != expected:
            raise ValueError('Downloaded component does not match its SHA-256')


class Coordinator:
    def __init__(self, plan, framework, android, state, poll=30):
        self.plan,self.framework,self.android,self.state,self.poll = plan,framework,android,state,poll
        state.mkdir(parents=True,exist_ok=True)
        self.stopped = Event()

    def runs(self, repository):
        return json.loads(gh('run','list','--repo',repository,'--workflow',self.plan['workflow'],
            '--limit','100','--json','databaseId,displayTitle,status,conclusion,url'))

    def existing(self, request):
        repository = self.plan['stages'][request['stage']]['repository']
        tag = 'arlinux-'+request['stage']+'-'+request['identity'][:24]
        release = api(f'repos/{repository}/releases/tags/{tag}',optional=True)
        if not release:
            return None
        asset = next((a for a in release['assets'] if a['name']=='component.json'),None)
        if not asset:
            return None
        digest = asset.get('digest','')
        if not digest.startswith('sha256:'):
            raise ValueError('GitHub did not supply the component manifest SHA-256')
        manifest = self.state/request['identity']/'component.json'
        download(asset['browser_download_url'],manifest,digest[7:])
        record = json.loads(manifest.read_text())
        for name in ('stage','identity','framework','android','dependencies'):
            if record.get(name) != request[name]:
                raise ValueError('Component release differs from the requested inputs: '+name)
        names={a['name'] for a in release['assets']}
        if any(part['name'] not in names for part in record['parts']):
            return None
        return dict(repository=repository,identity=request['identity'],
            manifestUrl=asset['browser_download_url'],manifestSha256=digest[7:])

    def component(self, stage, dependencies):
        request = dict(format=1,stage=stage,framework=self.framework,android=self.android,
                       dependencies=dependencies)
        request['identity']=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        repository=self.plan['stages'][stage]['repository']
        result=self.existing(request)
        if result:
            print('OK published '+repository+'/'+stage,flush=True)
            return result
        payload=json.dumps(request,sort_keys=True)
        # A standalone workflow_dispatch creates a run in the component repo.
        # Do not replace this with workflow_call: caches must belong to that repo.
        title='arlinux/'+stage+'/'+request['identity']
        previous_runs=self.runs(repository)
        run=next((r for r in previous_runs if r['displayTitle']==title and r['status']!='completed'),None)
        ignored={r['databaseId'] for r in previous_runs if r['status']=='completed'}
        if not run:
            gh('workflow','run',self.plan['workflow'],'--repo',repository,'-f','request='+payload)
            print('START '+repository+'/'+stage,flush=True)
        else:
            print('RESUME '+repository+'/'+stage+' '+run['url'],flush=True)
        deadline=time.monotonic()+7*60*60
        previous=None
        while time.monotonic()<deadline:
            if self.stopped.is_set():
                raise RuntimeError('Local coordinator stopped; remote workflows remain available to resume')
            runs=self.runs(repository)
            run=next((r for r in runs if r['displayTitle']==title and r['databaseId'] not in ignored),None)
            if run:
                status=run['status']+'/'+str(run['conclusion'])
                if status!=previous:
                    print(stage+': '+status+' '+run['url'],flush=True)
                    previous=status
                if run['status']=='completed':
                    if run['conclusion']!='success':
                        raise RuntimeError(stage+' failed: '+run['url'])
                    result=self.existing(request)
                    if not result:
                        raise ValueError('Successful workflow did not publish its verified capsule')
                    return result
            self.stopped.wait(self.poll)
        raise TimeoutError('Component workflow timed out: '+stage)

    def run(self, products, parallel):
        required=set()
        def visit(stage):
            if stage in required:
                return
            for dependency in self.plan['stages'][stage]['dependencies']:
                visit(dependency)
            required.add(stage)
        for product in products:
            visit(self.plan['products'][product])
        completed={}
        pending=set(required)
        active={}
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            while pending or active:
                for stage in sorted(pending):
                    dependencies=self.plan['stages'][stage]['dependencies']
                    if all(name in completed for name in dependencies) and len(active)<parallel:
                        future=executor.submit(self.component,stage,[completed[n] for n in dependencies])
                        active[future]=stage
                        pending.remove(stage)
                if not active:
                    raise ValueError('Component dependency graph contains a cycle')
                done,_=wait(active,return_when=FIRST_COMPLETED)
                for future in done:
                    stage=active.pop(future)
                    try:
                        completed[stage]=future.result()
                    except BaseException:
                        self.stopped.set()
                        raise
                    (self.state/'progress.json').write_text(json.dumps(completed,indent=2)+'\n')
        return {product:completed[self.plan['products'][product]] for product in products}


def fetch_product(reference, output):
    import zstandard
    with tempfile.TemporaryDirectory(prefix='arlinux-product-') as temporary:
        directory=Path(temporary)
        manifest=directory/'component.json'
        download(reference['manifestUrl'],manifest,reference['manifestSha256'])
        record=json.loads(manifest.read_text())
        if record['identity']!=reference['identity']:
            raise ValueError('Product identity mismatch')
        archive=directory/'capsule.tar.zst'
        with archive.open('wb') as dest:
            for part in record['parts']:
                file=directory/part['name']
                download(part['url'],file,part['sha256'])
                with file.open('rb') as source:
                    import shutil
                    shutil.copyfileobj(source,dest)
        with archive.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()!=record['archiveSha256']:
                raise ValueError('Product capsule SHA-256 mismatch')
        product=('rootfs/'+record['stage']) if record['stage'] in ('yibu','debian','arch','omarchy','plasma','lxqt') else 'wine'
        prefix='framework/build/artifacts/'+product+'/'
        output.mkdir(parents=True,exist_ok=True)
        with archive.open('rb') as source,zstandard.ZstdDecompressor().stream_reader(source) as decoded:
            with tarfile.open(fileobj=decoded,mode='r|') as capsule:
                for member in capsule:
                    if not member.name.startswith(prefix) or not member.isfile():
                        continue
                    name=member.name[len(prefix):]
                    if '/' in name or '\\' in name or name in ('','.','..'):
                        raise ValueError('Unsafe product archive member')
                    with (output/name).open('wb') as dest:
                        import shutil
                        shutil.copyfileobj(capsule.extractfile(member),dest)
        (output/'github-component.json').write_text(json.dumps(record,indent=2)+'\n')
        if product.startswith('rootfs/'):
            receipt=json.loads((output/'default.json').read_text())
            with (output/'default.zip').open('rb') as source:
                digest=hashlib.file_digest(source,'sha256').hexdigest()
            if digest!=receipt['desktopSha256']:
                raise ValueError('Rootfs build receipt does not match the downloaded product')
        else:
            archive=output/'arlinux-wine-bionic.tar.gz'
            with archive.open('rb') as source:
                digest=hashlib.file_digest(source,'sha256').hexdigest()
            expected=(output/(archive.name+'.sha256')).read_text().split()[0]
            if digest!=expected:
                raise ValueError('Wine checksum does not match the downloaded product')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework-ref',default='main')
    parser.add_argument('--distribution', choices=('yibu','debian','arch','omarchy','plasma','lxqt'), default='yibu')
    parser.add_argument('--product',choices=('wine','rootfs','audio','all'),default='all')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parallel',type=int,default=8)
    parser.add_argument('--plan',action='store_true')
    args=parser.parse_args()
    framework=Path(__file__).resolve().parents[2]
    plan=json.loads((framework/'tools/build/github-components.json').read_text())
    if args.plan:
        print(json.dumps(plan,indent=2))
        return
    framework_sha=api('repos/taowen/arlinux-rootfs/commits/'+args.framework_ref)['sha']
    products=['wine','rootfs'] if args.product=='all' else [args.product]
    if args.distribution != 'yibu':
        plan['products']['rootfs'] = args.distribution
    state=args.output/'github-state'
    coordinator=Coordinator(plan,framework_sha,None,state)
    result=coordinator.run(products,args.parallel)
    for name,reference in result.items():
        fetch_product(reference,args.output/name)
    (args.output/'products.json').write_text(json.dumps(dict(format=1,
        framework=framework_sha,products=result),indent=2)+'\n')


if __name__=='__main__':
    main()
