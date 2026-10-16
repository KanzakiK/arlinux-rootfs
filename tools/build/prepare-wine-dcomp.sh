#!/usr/bin/env bash
# Prepare the shared, checksum-pinned DirectComposition source for all Wine builds.
set -euo pipefail
[[ $# == 1 ]] || { echo 'Usage: prepare-wine-dcomp.sh PRIVATE_WINE_SOURCE' >&2; exit 2; }
source_dir="$(realpath "$1")"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
[[ "$(cat "$source_dir/VERSION")" == 'Wine version 11.19' ]] || exit 2
commit=318eda0d8fa08ee94faadf6dc5ad85870339b327
# Reusing a prepared source tree must never apply the patch twice or hide edits.
if [[ -f "$source_dir/arlinux-dcomp.json" ]]; then
    python3 - "$source_dir" "$repo/tools/patches/wine-dcomp-content-lifetime.patch" <<'VERIFY'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]); record=json.loads((root/'arlinux-dcomp.json').read_text())
assert record['commit']=='318eda0d8fa08ee94faadf6dc5ad85870339b327', 'Different DComp source revision'
assert record['patchSHA256']==hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(), 'DComp patch changed; use a fresh source tree'
for name, expected in record['files'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected, 'DComp source changed: '+name
VERIFY
    exit 0
fi
while read -r checksum name; do
    curl --fail --location --retry 3 \
        "https://raw.githubusercontent.com/giang17/wine/$commit/$name" \
        --output "$source_dir/$name"
    (cd "$source_dir" && printf '%s  %s\n' "$checksum" "$name" | sha256sum --check)
done <<'FILES'
bbb898c34121c4124ec444b706c4aeda706b81f704561360bcad8de576489e87 dlls/dcomp/device.c
48d2c35335d4d376f9076c22b5aa4b31f903aeb7fb2db9b76eec0b973da2204f dlls/dcomp/dcomp.spec
7c41e7afa89b2095e0a0facaff7dfd4a263becd545d72ca36e90e5e0f19eb844 include/dcomp.idl
8ab749290bca4c353dd40fc65d686239b9512329d1ff87cffe457ac7d4999ccc include/wine/dcomp_layer.h
52ba56d76cec87605416204ebd630b20eb66da4441c20b52b3300e44cc3ff7bc include/wine/winedxgi.idl
FILES
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-dcomp-content-lifetime.patch"
printf 'MODULE = dcomp.dll\nIMPORTS = dxguid uuid user32 gdi32 d2d1\nSOURCES = device.c\n' \
    > "$source_dir/dlls/dcomp/Makefile.in"
python3 - "$source_dir/include/Makefile.in" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
anchor = '\twine/list.h \\\n'
assert text.count(anchor) == 1
path.write_text(text.replace(anchor, anchor + '\twine/dcomp_layer.h \\\n'))
PY
python3 - "$source_dir" "$repo/tools/patches/wine-dcomp-content-lifetime.patch" <<'PYEND'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1])
record={'repository':'https://github.com/giang17/wine',
        'commit':'318eda0d8fa08ee94faadf6dc5ad85870339b327',
        'patchSHA256':hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(),
        'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
                 ['dlls/dcomp/device.c','dlls/dcomp/Makefile.in','include/dcomp.idl',
                  'include/wine/dcomp_layer.h','include/wine/winedxgi.idl']}}
(root/'arlinux-dcomp.json').write_text(json.dumps(record,indent=2)+'\n')
PYEND
