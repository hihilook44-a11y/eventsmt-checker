"""Keep automatic short publication on a single hourly schedule."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ScheduleTests(unittest.TestCase):
    def test_hourly_source_check_runs_the_queue_once(self):
        check = (ROOT / ".github/workflows/check.yml").read_text()
        queue = (ROOT / ".github/workflows/private-queue.yml").read_text()
        self.assertIn("- cron: '43 * * * *'", check)
        self.assertIn("uses: ./.github/workflows/private-queue.yml", check)
        self.assertNotIn("  schedule:", queue)

if __name__ == "__main__":
    unittest.main()
