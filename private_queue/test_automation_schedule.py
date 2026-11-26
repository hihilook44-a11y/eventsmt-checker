"""Keep automatic short publication on a single hourly schedule."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ScheduleTests(unittest.TestCase):
    def test_hourly_source_check_runs_the_queue_once(self):
        check = (ROOT / '.github/workflows/check.yml').read_text()
        queue = (ROOT / '.github/workflows/private-queue.yml').read_text()
        schedules = re.findall(r"^\s*-\s*cron:\s*['\"]([^'\"]+)['\"]\s*$", check, re.M)
        self.assertEqual(len(schedules), 1, 'source check must have exactly one schedule')
        parts = schedules[0].split()
        self.assertEqual(len(parts), 5)
        self.assertTrue(parts[0].isdigit() and 0 <= int(parts[0]) <= 59)
        self.assertEqual(parts[1:], ['*', '*', '*', '*'], 'source check must run hourly')
        self.assertEqual(check.count('uses: ./.github/workflows/private-queue.yml'), 1)
        self.assertNotIn('  schedule:', queue)

if __name__ == '__main__':
    unittest.main()
