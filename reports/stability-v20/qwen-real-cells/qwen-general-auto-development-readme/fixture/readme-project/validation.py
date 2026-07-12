from pathlib import Path
text = Path('README.md').read_text(encoding='utf-8')
assert 'Usage' in text or 'usage' in text.lower(), 'README Usage section missing'
print('validation ok')
