import json
import tempfile
import unittest
from pathlib import Path
from releaseroom.store import Store,Conflict
from releaseroom.protocol import ConnectionState,PermanentStop
from releaseroom.artifact import DEFAULT

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name),{'opaque-human-id'})
        self.state=ConnectionState(self.store,'agent-id','room-id')
        self.state.frame({'event':'connection_state','data':{'connection_id':self.state.connection_id,'agent_id':'agent-id','generation':7,'cursor':0,'rooms':['room-id']}})
    def tearDown(self):self.temp.cleanup()
    def event(self,id=1,addressed=True,room='room-id',message_id='message-1'):
        return {'event':'message','id':id,'data':{'type':'message','room_id':room,'bridge_id':None,'channel_type':'channel_public','sequence':id,
          'payload':{'addressed':addressed,'sender':'opaque-human-id','sender_name':'A person','message_id':message_id,'body':'[releaseroom] request Change the CTA','timestamp':1793836800000,'thread_id':None,'attachments':[]}}}
    def test_ping_uses_processed_cursor_and_events_are_durable_and_deduplicated(self):
        self.state.frame(self.event());self.state.frame(self.event(id=2))
        self.assertEqual(self.state.frame({'event':'ping','data':{}}),{'type':'pong','cursor':2})
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM incoming').fetchone()[0],1)
        restored=ConnectionState(self.store,'agent-id','room-id')
        self.assertEqual(restored.connection_id,self.state.connection_id);self.assertEqual(restored.cursor,2)
        self.assertIn('expected_generation=7',restored.url('https://switch.example'))
    def test_unaddressed_and_other_room_messages_advance_cursor_without_work(self):
        self.state.frame(self.event(addressed=False));self.state.frame(self.event(id=2,room='different-room',message_id='message-2'))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM incoming').fetchone()[0],0)
        self.assertEqual(self.state.cursor,2)
    def test_takeover_stops_and_is_persisted(self):
        with self.assertRaises(PermanentStop):self.state.frame({'event':'evicted','data':{'code':'taken_over'}})
        self.assertTrue(ConnectionState(self.store,'agent-id','room-id').halted)
    def test_gap_fences_release_approval_until_context_recovery(self):
        row=self.store.propose('Update',DEFAULT,'opaque-human-id',0);row=self.store.test(row['id'])
        self.store.approve(row['id'],row['digest'],'opaque-human-id')
        self.state.frame({'event':'gap','data':{'resumed_at':10,'reason':'cursor_expired','rooms':['room-id']}})
        self.assertEqual(self.store.get(row['id'])['state'],'ready')
        with self.assertRaises(Conflict):self.store.approve(row['id'],row['digest'],'opaque-human-id')
    def test_malformed_sequence_and_lost_room_are_rejected(self):
        bad=self.event();bad['id']='1'
        with self.assertRaises(ValueError):self.state.frame(bad)
        with self.assertRaises(PermanentStop):self.state.frame({'event':'subscription_changed','data':{'rooms':[]}})

if __name__=='__main__':unittest.main()
