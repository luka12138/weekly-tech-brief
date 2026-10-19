import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backup_weekly_data import backup


class WeeklyBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'source';self.src.mkdir();self.dst=self.root/'backup'
        (self.src/'fixture.json').write_text('{"fixture":true}')

    def test_incremental_copy_and_no_delete(self):
        _,r=backup(self.src,self.dst);self.assertEqual(r['copied'],1)
        (self.dst/'unrelated-user-file.txt').write_text('preserve')
        _,r=backup(self.src,self.dst);self.assertEqual(r['copied'],0);self.assertEqual(r['verified_existing'],1)
        self.assertTrue((self.dst/'unrelated-user-file.txt').exists())

    def test_corrupt_backup_is_not_silently_overwritten(self):
        backup(self.src,self.dst);(self.dst/'fixture.json').write_text('corruption')
        with self.assertRaisesRegex(ValueError,'corruption'):
            backup(self.src,self.dst)
        self.assertEqual((self.dst/'fixture.json').read_text(),'corruption')

    def test_disconnected_destination_not_recreated(self):
        with self.assertRaisesRegex(ValueError,'disconnected'):
            backup(self.src,self.root/'unmounted-drive'/'weekly')
        self.assertFalse((self.root/'unmounted-drive').exists())

    def test_recursive_backup_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'independent'):
            backup(self.src,self.src/'backup')
