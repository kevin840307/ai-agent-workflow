from pathlib import Path
assert Path('workflow_mock_feature.py').exists() or Path('config_loader.py').exists(), 'expected generated helper missing'
print('validation ok')
