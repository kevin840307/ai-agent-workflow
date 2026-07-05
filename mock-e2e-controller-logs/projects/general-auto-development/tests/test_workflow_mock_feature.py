import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
