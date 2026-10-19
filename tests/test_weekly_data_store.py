import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from weekly_data_store import create_run, ingest, seal, select_issue_version, verify_run, put, get, classify, archive_artifacts, restore_artifacts


class WeeklyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Path(self.tmp.name)
        self.jobs=[{'id':'request_1','method':'wss','args':['TEST','sec_name','tradeDate=20261016']}]
        self.receipt={'request':self.jobs[0],'started_at':'2026-10-19T01:00:01Z','retrieved_at':'2026-10-19T01:00:02Z',
                      'result':{'ErrorCode':0,'Codes':['TEST'],'Fields':['SEC_NAME'],'Times':['2026-10-16'],'Data':[['test fixture']]}}

    def run_with_data(self,purpose='late_rerun'):
        run=create_run(self.store,'2026-10-19',self.jobs,purpose=purpose)
        ingest(self.store,run,self.receipt);seal(self.store,run)
        return run

    def test_same_payload_different_times_deduplicates(self):
        run=create_run(self.store,'2026-10-19',self.jobs)
        a=ingest(self.store,run,self.receipt)
        run2=create_run(self.store,'2026-10-19',self.jobs)
        r=copy.deepcopy(self.receipt);r['retrieved_at']='2026-10-19T01:01:00Z'
        b=ingest(self.store,run2,r)
        self.assertEqual(a['result_ref'],b['result_ref'])
        self.assertNotEqual(a['retrieved_at'],b['retrieved_at'])

    def test_only_one_selected_version_and_no_diagnostic_promotion(self):
        run=self.run_with_data();selection=select_issue_version(self.store,run)
        self.assertEqual(selection,select_issue_version(self.store,run))
        with self.assertRaisesRegex(ValueError,'different content'):
            select_issue_version(self.store,self.run_with_data())
        with self.assertRaisesRegex(ValueError,'Diagnostic'):
            select_issue_version(self.store,self.run_with_data('diagnostic'))

    def test_failed_empty_partial_never_equal_success(self):
        for result,status in [({'ErrorCode':-1,'Data':[]},'api_error'),({'ErrorCode':0,'Data':[[None]]},'empty'),
                              ({'ErrorCode':0,'Data':[[1,None]]},'partial')]:
            self.assertEqual(classify(result),status)
        self.assertEqual(classify({'ErrorCode':0,'Data':[[0]]}),'nonempty')

    def test_corruption_detected_on_readback(self):
        ref=put(self.store,{'example':'fixture'});p=self.store/'objects'/ref['sha256'][:2]/(ref['sha256']+'.json')
        p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash/size'):
            get(self.store,ref)

    def test_mismatched_request_and_sealed_write_rejected(self):
        run=create_run(self.store,'2026-10-19',self.jobs)
        bad=copy.deepcopy(self.receipt);bad['request']['args'][0]='OTHER'
        with self.assertRaisesRegex(ValueError,'match'):
            ingest(self.store,run,bad)
        ingest(self.store,run,self.receipt);seal(self.store,run)
        with self.assertRaisesRegex(ValueError,'sealed'):
            ingest(self.store,run,self.receipt)

    def test_replay_idempotent_but_changed_receipt_rejected(self):
        run=create_run(self.store,'2026-10-19',self.jobs)
        ingest(self.store,run,self.receipt);ingest(self.store,run,self.receipt)
        bad=copy.deepcopy(self.receipt);bad['result']['Data']=[['revised']]
        with self.assertRaisesRegex(ValueError,'different content'):
            ingest(self.store,run,bad)

    def test_unfinished_run_cannot_be_sealed(self):
        run=create_run(self.store,'2026-10-19',self.jobs)
        with self.assertRaisesRegex(ValueError,'Unfinished'):
            seal(self.store,run)

    def test_artifact_restore_readback_and_no_overwrite(self):
        run=self.run_with_data();source=self.store/'input';source.mkdir()
        f=source/'report.pdf';f.write_bytes(b'%PDF-fixture\x00binary')
        manifest=archive_artifacts(self.store,run,source,[f],'test')
        destination=self.store/'restored'
        result=restore_artifacts(self.store,manifest,destination)
        self.assertTrue(result['all_hashes_verified'])
        self.assertEqual(f.read_bytes(),(destination/'report.pdf').read_bytes())
        with self.assertRaises(FileExistsError):restore_artifacts(self.store,manifest,destination)

    def test_restore_rejects_traversal_and_corruption_before_writing(self):
        run=self.run_with_data();source=self.store/'input';source.mkdir()
        f=source/'data.json';f.write_text('{}')
        manifest=archive_artifacts(self.store,run,source,[f],'test')
        original=json.loads(manifest.read_text());bad=copy.deepcopy(original)
        bad['entries'][0]['path']='../escape';edited=self.store/'bad.json';edited.write_text(json.dumps(bad))
        destination=self.store/'restored'
        with self.assertRaisesRegex(ValueError,'Unsafe'):restore_artifacts(self.store,edited,destination)
        self.assertFalse(destination.exists())
        digest=original['entries'][0]['sha256'];(self.store/'objects'/digest[:2]/(digest+'.bin')).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'hash/size'):restore_artifacts(self.store,manifest,destination)
        self.assertFalse(destination.exists())

    def test_duplicate_requests_and_invalid_times_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate API'):
            create_run(self.store,'2026-10-19',self.jobs+[{**self.jobs[0],'id':'request_2'}])
        run=create_run(self.store,'2026-10-19',self.jobs)
        bad=copy.deepcopy(self.receipt);bad['retrieved_at']='2026-10-19T00:59:00Z'
        with self.assertRaisesRegex(ValueError,'chronology'):
            ingest(self.store,run,bad)
