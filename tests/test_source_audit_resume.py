import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_sources import reusable_audit, sha256_file


class AuditResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = self.root / 'report.md'
        self.report.write_text('same report', encoding='utf-8')
        self.path = self.root / 'audit.json'
        self.urls = ['https://example.com']
        self.claims = [{'claim_id': 'E1', 'source_urls': self.urls, 'keywords': ['test']}]
        self.data = {'generated_at': datetime.now(timezone.utc).isoformat(),
                     'report_sha256': sha256_file(self.report), 'baseline_sha256': None,
                     'product_graph_sha256': None, 'audited_urls': self.urls,
                     'sources': [{'url': self.urls[0], 'reachable': False, 'error': 'timeout'}],
                     'claim_checks': [{**self.claims[0], 'matched': False, 'failed': True}]}

    def check(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        return reusable_audit(self.path, self.report, None, None, self.urls, self.claims)

    def test_loading_a_failure_never_marks_it_successful(self):
        old = self.check()
        self.assertFalse(old['sources'][0]['reachable'])
        self.assertTrue(old['claim_checks'][0]['failed'])

    def test_changed_report_blocks_resume(self):
        self.report.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.check()

    def test_stale_or_future_records_block_resume(self):
        for delta in (timedelta(minutes=-16), timedelta(minutes=1)):
            self.data['generated_at'] = (datetime.now(timezone.utc) + delta).isoformat()
            with self.assertRaisesRegex(ValueError, '15 minutes'):
                self.check()

    def test_changed_urls_or_claims_block_resume(self):
        self.data['audited_urls'] = []
        with self.assertRaisesRegex(ValueError, 'URL inventory'):
            self.check()
        self.data['audited_urls'] = self.urls
        self.data['claim_checks'][0]['keywords'] = ['other']
        with self.assertRaisesRegex(ValueError, 'claim definitions'):
            self.check()
