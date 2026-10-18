"""Atomic, resumable downloads of immutable build inputs, on Windows and Linux."""
import hashlib
from pathlib import Path
import re
import subprocess
import time


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def download(url,output,expected):
    if not re.fullmatch('[0-9a-f]{64}',expected):
        raise ValueError('Build download requires a pinned SHA-256')
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_file() and sha256_file(output)==expected:
        return output
    part=output.with_name(output.name+'.part')
    if output.is_file() and not part.exists():
        output.replace(part)
    error=''
    for attempt in range(8):
        result=subprocess.run(['curl','--silent','--show-error','--location','--fail',
            '--continue-at','-','--connect-timeout','20','--max-time','600',
            '--speed-time','90','--speed-limit','1024','--output',str(part),url],
            capture_output=True,text=True)
        if result.returncode==0 and part.is_file() and sha256_file(part)==expected:
            part.replace(output)
            return output
        error=result.stderr.strip() or 'SHA-256 mismatch'
        if result.returncode in (0,33):
            # The server rejected ranges, or a complete file was corrupted.
            part.unlink(missing_ok=True)
        if attempt<7:
            print(f'Retry immutable download {output.name}: {error[-200:]}',flush=True)
            time.sleep(min(2**attempt,16))
    raise RuntimeError('Cannot obtain verified build input '+str(output)+': '+error)
