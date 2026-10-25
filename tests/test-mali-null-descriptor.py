import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
layer = root / 'third_party/libhybris/hybris/vulkan/layer_null_descriptor'
manifest = json.loads((layer / 'VkLayer_arlinux_null_desc.json').read_text())

assert manifest['layer']['name'] == 'VK_LAYER_ARLINUX_null_descriptor'
assert (layer / 'arlinux_null_descriptor.c').is_file()

assets = (root / 'tools/build/linux-assets.sh').read_text()
generic = assets.split('generic="$stage/$product/gpu-generic"', 1)[1]
assert 'libVkLayer_arlinux_null_descriptor.so' in generic
assert 'VkLayer_arlinux_null_desc.json' in generic

steam = (root / 'runtime/tools/arlinux-steam').read_text()
assert 'python3 /usr/lib/arlinux/steam.py --disable-gpu-vsync "$@"' in steam
