"""The component DAG used by local builds and GitHub Actions jobs."""
import json
from pathlib import Path
from pipeline_cache import Cache


PLAN = json.loads(Path(__file__).with_name('github-components.json').read_text())
DEPENDENCIES = {name: tuple(stage['dependencies']) for name, stage in PLAN['stages'].items()
                if stage['product'] in ('wine', 'vendor')}


def required_stages(target):
    result = set()
    def visit(name):
        for dependency in DEPENDENCIES[name]:
            visit(dependency)
        result.add(name)
    if target:
        visit(target)
    else:
        result.update(DEPENDENCIES)
    return tuple(name for name in DEPENDENCIES if name in result)


class ComponentComplete(Exception):
    def __init__(self, name):
        self.name = name


class ComponentCache(Cache):
    def __init__(self, root, rebuild=False, target=None, require_dependencies=False):
        super().__init__(root, rebuild)
        self.target = target
        self.required = set(required_stages(target))
        self.require_dependencies = require_dependencies

    def selected(self, name):
        return name in self.required

    def stage(self, name, inputs, build):
        if not self.selected(name):
            return None
        if self.require_dependencies and name != self.target:
            def missing(_):
                raise RuntimeError('Missing or invalid dependency artifact: ' + name)
            output = super().stage(name, inputs, missing)
        else:
            output = super().stage(name, inputs, build)
        if name == self.target:
            descriptor = self.root.parent / 'artifacts/components' / (name + '.json')
            descriptor.parent.mkdir(parents=True, exist_ok=True)
            descriptor.write_text(json.dumps(dict(format=1, stage=name,
                output=str(output), records=self.records), sort_keys=True)+'\n')
            raise ComponentComplete(name)
        return output
