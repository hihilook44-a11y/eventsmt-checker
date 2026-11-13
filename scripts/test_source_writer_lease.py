"""Regression: public source ledger writers must not invalidate queue checkpoints."""
import unittest
from pathlib import Path

class SourceWriterLease(unittest.TestCase):
    def test_shared_lease_covers_source_state_write_and_releases_before_backup(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/check.yml').read_text()
        check, backup=text.split('\n  backup-private-queue:',1)
        acquire=check.index('scripts/queue_lease.py acquire')
        refresh=check.index('git reset --hard FETCH_HEAD')
        scan=check.index('run: python3 check.py')
        push=check.index('git push origin HEAD:main')
        release=check.index('scripts/queue_lease.py release')
        self.assertTrue(acquire < refresh < scan < push < release)
        self.assertEqual(check.count('--token "$RUNNER_TEMP/source-writer-lease"'),2)
        self.assertIn('if: ${{ always() }}',check[push:release])
        self.assertIn('uses: ./.github/workflows/private-queue.yml',backup)

if __name__=='__main__':unittest.main()
