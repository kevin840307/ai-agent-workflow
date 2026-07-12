from pathlib import Path
import json
import importlib.util
Path('sample.json').write_text(json.dumps({'a': 1}), encoding='utf-8')
spec = importlib.util.spec_from_file_location('config_loader', Path('config_loader.py'))
assert Path('config_loader.py').exists(), 'config_loader.py is missing'
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.load_config('sample.json') == {'a': 1}
print('validation ok')
