import unittest
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import load_config

class TestConfigLoader(unittest.TestCase):
    def test_load_valid_json(self):
        result = load_config('sample.json')
        self.assertEqual(result, {'a': 1})

    def test_load_check_type(self):
        result = load_config('sample.json')
        self.assertIsInstance(result, dict)