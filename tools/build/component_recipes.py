"""Load independently owned component recipes; releases have stable names."""
import json
from pathlib import Path


def load_plan(directory=None):
    directory = Path(directory) if directory else Path(__file__).resolve().parent
    stages, products = {}, {}
    for path in sorted((directory/'components').glob('*.json')):
        spec = json.loads(path.read_text())
        names = spec.pop('products', [])
        stages[path.stem] = spec
        for name in names:
            products.setdefault(name, []).append(path.stem)
    return dict(format=1, workflow='arlinux-component.yml', workspace='/opt/arlinux', cacheLimitGiB=10,
                stages=stages, products={name: values[0] if len(values) == 1 else values
                                        for name, values in products.items()})
