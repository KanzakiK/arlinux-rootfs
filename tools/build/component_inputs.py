"""Content identities for independently dispatched distribution components."""
import hashlib
import json
import subprocess


def source_inputs(repo, revision, stage, plan):
    distribution = stage if stage in ('yibu', 'debian', 'arch', 'omarchy', 'plasma', 'lxqt') else 'yibu'
    if stage == 'vulkan-capture':
        paths = ('build.sh', 'tools/build/github-component.py', 'tools/build/component_inputs.py',
                 'tools/build/vulkan-capture-component.py', 'tools/build/pipeline_cache.py',
                 'third_party/gfxreconstruct', 'third_party/libhybris')
    elif stage in ('linux-mesa', 'linux-hybris'):
        paths = ('build.sh', 'tools/build/github-component.py', 'tools/build/component_inputs.py',
                 'tools/build/linux-gpu.sh', 'tools/build/linux-gpu-component.py',
                 'tools/build/linux-aarch64.ini', 'tools/build/pipeline_cache.py', 'third_party')
    else:
        paths = ('build.sh', 'tools', 'runtime', 'examples', 'third_party', 'distributions/'+distribution)
    records = subprocess.check_output(['git', '-C', str(repo), 'ls-tree', '-r', '-z', revision, '--', *paths])
    files = {}
    for record in records.split(b'\0'):
        if record:
            metadata, name = record.split(b'\t', 1)
            name = name.decode()
            # Workstation transport does not generate distribution contents.
            # Its downloads still verify the declared component/output hashes.
            if name in ('tools/build/github-products.py', 'tools/build/artifact_download.py'):
                continue
            files[name] = metadata.decode()
    return dict(sourceSha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
                runner=plan['stages'][stage]['runner'])


def request_identity(data):
    fields = {k: v for k, v in data.items() if k not in ('identity', 'cacheSeed')}
    if data.get('format') == 2:
        fields.pop('framework')
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def package_inputs(common):
    """Package preparation does not execute application Python or vendor downloads.

    seal-rootfs refreshes those files from the current seed after restoring the
    package snapshot. Keep installer shell scripts and native helper sources.
    """
    sources = dict(common['sources'])
    sources['runtime/tools'] = {name: value for name, value in sources['runtime/tools'].items()
        if not name.endswith(('.py', '.png', '.desktop'))
        and not (name.startswith('windows-') and name.endswith('.tsv'))}
    return dict(common, sources=sources)
