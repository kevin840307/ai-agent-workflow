import pathlib

def test_readme_contains_usage():
    readme_path = pathlib.Path(__file__).resolve().parents[1] / "README.md"
    content = readme_path.read_text(encoding="utf-8")
    assert "## Usage" in content
    assert "python validation.py" in content
