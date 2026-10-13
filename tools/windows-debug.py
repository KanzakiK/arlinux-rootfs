#!/usr/bin/env python3
"""Capture first-chance exceptions with a read-only Windows debug-event observer.

Run inside the guest. This uses the same Wine launch environment as arlinux-windows
and Windows debugging APIs without changing thread contexts. Logs may contain private
application data; review them before sharing. Detaching resumes the application.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True, help='Existing Wine data directory (contains pfx)')
    parser.add_argument('--output', type=Path, required=True, help='New private report directory')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--observer', type=Path, required=True, help='ARM64 exception-observer.exe built from the GE fork')
    parser.add_argument('--env', action='append', default=[], help='Diagnostic NAME=VALUE override (recorded; do not pass secrets)')
    parser.add_argument('--runtime', help='Installed runtime SHA-256; defaults to the active runtime')
    parser.add_argument('executable', type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('Use 1..600 seconds')
    overrides = {}
    for value in args.env:
        name, separator, setting = value.partition('=')
        if not separator or not name or '\x00' in value:
            parser.error('--env requires NAME=VALUE')
        overrides[name] = setting
    prefix = args.prefix.expanduser().resolve(strict=True)
    if not (prefix/'pfx').is_dir():
        parser.error('--prefix must contain an existing pfx directory')
    executable = args.executable.expanduser().resolve(strict=True)
    if not executable.is_file():
        parser.error('Expected an executable file')
    import sys
    sys.path.insert(0, '/usr/lib/arlinux')
    import windows
    runtime = windows.runtime(args.runtime) if args.runtime else windows.ensure_runtime()
    current = {'sha256': runtime.name}
    debugger = args.observer.expanduser().resolve(strict=True)
    if not debugger.is_file():
        parser.error('Observer executable not found')
    report = args.output.expanduser()
    report.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = report.resolve()
    env = windows.environment(runtime, prefix)
    windows.initialize(runtime, prefix, env)
    env.update(overrides)
    env['ARLINUX_EXCEPTION_LOG'] = 'Z:'+str(windows.host_path(report/'debugger.log')).replace('/', '\\')
    arguments = [str(args.seconds), 'Z:'+str(windows.host_path(executable)).replace('/', '\\')]
    if args.arguments:
        arguments.append(subprocess.list2cmdline([arguments[-1], *args.arguments]))
    metadata = {'runtime_sha256': current['sha256'], 'prefix': str(prefix),
                'executable': str(executable), 'arguments': args.arguments, 'started': time.time(),
                'observer_sha256': hashlib.sha256(debugger.read_bytes()).hexdigest(),
                'seconds': args.seconds, 'environment': overrides}
    with executable.open('rb') as binary:
        metadata['executable_sha256'] = hashlib.file_digest(binary, 'sha256').hexdigest()
    (report/'runtime.json').write_text((runtime/'bionic-runtime.json').read_text())
    timed_out = False
    try:
        result = windows.run(runtime, prefix, debugger, arguments, env=env,
                             capture=True, timeout=args.seconds+60)
        status = result.returncode
        (report/'launcher.log').write_text(result.stdout)
    except RuntimeError:
        timed_out, status = True, 124
    # The observer normally detaches after its time budget. Its zero exit code
    # is not evidence that the application exited successfully (or worked).
    observer_log = report/'debugger.log'
    lines = observer_log.read_text(errors='replace').splitlines() if observer_log.exists() else []
    if not any(line.startswith('process=') for line in lines):
        status = status or 5
        observer_log.touch(exist_ok=True)
    application_exits = [int(line.partition('=')[2]) for line in lines
                         if line.startswith('process_exit=')]
    metadata.update(exit_code=status, timed_out=timed_out, finished=time.time(),
                    application_exit_code=application_exits[-1] if application_exits else None,
                    detached='detach=1' in lines)
    (report/'report.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps({'report': str(report), 'exit_code': status, 'timed_out': timed_out}))
    return 124 if timed_out else status


if __name__ == '__main__':
    raise SystemExit(main())
