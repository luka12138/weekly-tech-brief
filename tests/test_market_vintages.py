from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_vintages import freeze,verify,availability,restore,timestamp


class VintageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.vault=self.root/'vault'
        self.file=self.root/'raw.json';self.file.write_text('{"data":1}')
    def tearDown(self):self.tmp.cleanup()
    def test_backdating_rejected_equality_exclusive(self):
        p,m=freeze(self.root,[self.file],self.vault,'test')
        self.assertFalse(availability(self.vault,p,m['preserved_at'])['locally_preserved_before_cutoff'])
        past=(timestamp(m['preserved_at'])-timedelta(seconds=1)).isoformat()
        self.assertFalse(availability(self.vault,p,past)['locally_preserved_before_cutoff'])
        future=(timestamp(m['preserved_at'])+timedelta(seconds=1)).isoformat()
        self.assertTrue(availability(self.vault,p,future)['locally_preserved_before_cutoff'])
    def test_original_survives_source_revision_and_restores(self):
        p,m=freeze(self.root,[self.file],self.vault,'one');self.file.write_text('{"data":2}')
        q,n=freeze(self.root,[self.file],self.vault,'two')
        self.assertNotEqual(m['entries'][0]['sha256'],n['entries'][0]['sha256'])
        restored=self.root/'restore';restore(self.vault,p,restored)
        self.assertEqual((restored/'raw.json').read_text(),'{"data":1}')
        with self.assertRaises(FileExistsError):restore(self.vault,p,restored)
    def test_dedup_and_tamper_detection(self):
        other=self.root/'copy.json';other.write_bytes(self.file.read_bytes())
        p,m=freeze(self.root,[self.file,other],self.vault,'test')
        self.assertEqual(len(list((self.vault/'objects').glob('*/*'))),1)
        blob=next((self.vault/'objects').glob('*/*'));blob.write_text('tampered')
        with self.assertRaises(ValueError):verify(self.vault,p)
        with self.assertRaises(ValueError):restore(self.vault,p,self.root/'broken')
        self.assertFalse((self.root/'broken').exists())
    def test_path_traversal_rejected(self):
        p,m=freeze(self.root,[self.file],self.vault,'test');m['entries'][0]['path']='../escape'
        p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):verify(self.vault,p)


if __name__=='__main__':unittest.main()
