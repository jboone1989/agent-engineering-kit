"""Pure contract tests of GitHub publication helpers; never access a real account."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from enforce_checks import payload

AGENT_RUNTIME_CHECKS = (
    "Enforce module boundaries", "Full regression", "Platform boundary suite", "pytest"
)
from publish_public import command


class PublishingToolsTests(unittest.TestCase):
    def test_public_only_repo_command(self):
        args = command("octocat", "agent-engineering-kit", Path("/tmp/source"))
        self.assertEqual(args[:4], ["gh", "repo", "create", "octocat/agent-engineering-kit"])
        self.assertIn("--public", args)
        self.assertIn("--push", args)
        self.assertNotIn("--private", args)

    def test_requires_four_actual_jobs(self):
        data = payload("AEK CI", "main", AGENT_RUNTIME_CHECKS)
        self.assertEqual(data["enforcement"], "active")
        self.assertEqual(data["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        self.assertEqual([x["context"] for x in data["rules"][0]["parameters"]["required_status_checks"]], list(AGENT_RUNTIME_CHECKS))
        self.assertTrue(data["rules"][0]["parameters"]["strict_required_status_checks_policy"])
        self.assertEqual(data["bypass_actors"], [])

    def test_missing_or_duplicated_checks_rejected(self):
        with self.assertRaises(ValueError):
            payload("AEK", "main", ())
        with self.assertRaises(ValueError):
            payload("AEK", "main", ("pytest", "pytest"))
        with self.assertRaises(ValueError):
            payload("AEK", "main", (" ",))


if __name__ == "__main__":
    unittest.main()
