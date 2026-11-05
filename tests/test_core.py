import json
import tempfile
import unittest
from pathlib import Path
from releaseroom.artifact import DEFAULT,check,canonical,sha
from releaseroom.store import Store,Conflict,Forbidden

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.now=1793836800;self.store=Store(self.root,{"human-reviewer"},clock=lambda:self.now)
    def tearDown(self):self.temp.cleanup()
    def candidate(self,revision=0,content=None):
        r=self.store.propose("Update the community launch page.",content or DEFAULT.copy(),"human-reviewer",revision)
        return self.store.test(r['id'])
    def test_checked_approved_release_publishes_the_exact_artifact_once(self):
        r=self.candidate();self.assertEqual(r['state'],'ready')
        self.store.approve(r['id'],r['digest'],'human-reviewer');receipt=self.store.publish(r['id'])
        data=(self.root/'staging/releases'/r['id']/'index.html').read_bytes()
        self.assertEqual(sha(data),receipt['artifact_sha256'])
        self.assertEqual(json.loads((self.root/'staging/current.json').read_text())['digest'],r['digest'])
        self.assertEqual(self.store.publish(r['id']),receipt)
        with self.assertRaises(Conflict):self.store.approve(r['id'],r['digest'],'human-reviewer')
    def test_changed_content_invalidates_old_approval(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        fresh=self.store.propose("Change the call to action.",{**DEFAULT,'cta':'Build with us'},'human-reviewer',1)
        with self.assertRaises(Conflict):self.store.publish(r['id'])
        self.assertEqual(self.store.get(r['id'])['state'],'superseded')
        self.assertEqual(fresh['revision'],2)
    def test_agent_sender_and_short_fingerprint_cannot_approve(self):
        r=self.candidate()
        with self.assertRaises(Forbidden):self.store.approve(r['id'],r['digest'],'agent-builder')
        with self.assertRaises(Conflict):self.store.approve(r['id'],r['digest'][:8],'human-reviewer')
    def test_artifact_tampering_rejects_approval_and_publication(self):
        r=self.candidate();path=self.root/'artifacts'/r['id']/'index.html';path.write_text('modified')
        with self.assertRaises(Conflict):self.store.approve(r['id'],r['digest'],'human-reviewer')
        self.assertFalse((self.root/'staging/current.json').exists())
    def test_test_evidence_tampering_rejects_release(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        report={**r['report'],'tests':[]}
        with self.store.connect() as db:db.execute('UPDATE releases SET report=? WHERE id=?',(canonical(report).decode(),r['id']))
        with self.assertRaises(Conflict):self.store.publish(r['id'])
    def test_expired_or_revoked_reviewer_approval_cannot_publish(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer');self.now+=901
        with self.assertRaises(Conflict):self.store.publish(r['id'])
        self.now-=901;self.store.reviewers=set()
        with self.assertRaises(Forbidden):self.store.publish(r['id'])
    def test_unreadable_contrast_and_arbitrary_destination_are_blocked(self):
        r=self.candidate(content={**DEFAULT,'foreground':'#eff3e9','link':'https://attacker.invalid'})
        self.assertEqual(r['state'],'blocked');self.assertFalse(r['report']['passed'])
        with self.assertRaises(Conflict):self.store.approve(r['id'],'0'*64,'human-reviewer')
    def test_stale_request_revision_and_unknown_sender_are_rejected(self):
        self.candidate()
        with self.assertRaises(Conflict):self.store.propose('Another request',DEFAULT,'human-reviewer',0)
        with self.assertRaises(Forbidden):self.store.propose('Another request',DEFAULT,'unknown-user',1)
    def test_content_is_escaped_in_staging_and_unknown_keys_are_rejected(self):
        r=self.candidate(content={**DEFAULT,'headline':'<script>alert(1)</script>'})
        data=(self.root/'artifacts'/r['id']/'index.html').read_text()
        self.assertIn('&lt;script&gt;',data);self.assertNotIn('<script>',data)
        self.assertFalse(check({**DEFAULT,'shell':'rm -rf /'})['passed'])
    def test_claimed_publication_blocks_concurrent_changes_and_recovers(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        with self.store.connect() as db:db.execute("UPDATE releases SET state='publishing' WHERE id=?",(r['id'],))
        with self.assertRaises(Conflict):self.store.publish(r['id'])
        with self.assertRaises(Conflict):self.store.propose('Change again',DEFAULT,'human-reviewer',1)
        receipt=self.store.publish(r['id'],recover=True)
        self.assertEqual(receipt['digest'],r['digest'])
    def test_expired_interruption_resets_and_requires_new_human_approval(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        with self.store.connect() as db:db.execute("UPDATE releases SET state='publishing' WHERE id=?",(r['id'],))
        self.now+=1000
        self.assertEqual(self.store.recover_pending()['reset'],1)
        self.assertIsNone(self.store.get(r['id'])['approval'])
        with self.assertRaises(Conflict):self.store.publish(r['id'])
        self.store.approve(r['id'],r['digest'],'human-reviewer')
        self.assertEqual(self.store.publish(r['id'])['digest'],r['digest'])
    def test_pointer_written_before_database_commit_is_not_exposed_by_recovery(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        with self.store.connect() as db:db.execute("UPDATE releases SET state='publishing' WHERE id=?",(r['id'],))
        path=self.root/'staging/current.json';path.parent.mkdir(parents=True);path.write_text(json.dumps({'release_id':r['id'],'digest':r['digest']}))
        self.store.recover_pending()
        self.assertFalse(path.exists());self.assertEqual(self.store.get(r['id'])['state'],'ready')
    def test_revocation_during_staging_write_blocks_final_commit(self):
        r=self.candidate();self.store.approve(r['id'],r['digest'],'human-reviewer')
        original=self.store._atomic
        def revoke(path,data):
            original(path,data)
            if path.name=='manifest.json':self.store.reviewers=set()
        self.store._atomic=revoke
        with self.assertRaises(Forbidden):self.store.publish(r['id'])
        self.assertFalse((self.root/'staging/current.json').exists())
    def test_pinned_git_object_tampering_rejects_approval(self):
        r=self.candidate();commit=r['git_commit'];path=self.root/'artifact.git/objects'/commit[:2]/commit[2:]
        path.write_bytes(b'bad object')
        with self.assertRaises((Conflict,ValueError)):self.store.approve(r['id'],r['digest'],'human-reviewer')

if __name__=='__main__':unittest.main()
