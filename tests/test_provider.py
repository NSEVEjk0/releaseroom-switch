import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from releaseroom.artifact import DEFAULT,POLICY,canonical,sha,check
from releaseroom.cli import settings
from releaseroom.provider import BuilderProvider,Unavailable
from releaseroom.store import Store


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.store=Store(self.root/'state',{'human'})
        self.key=self.root/'model-key';self.key.write_text('fixture-key-only')

    def response(self,content=None):
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(content or DEFAULT)}}]}).encode())

    def test_near_key_goes_only_to_near_and_retains_output_and_budget_limits(self):
        calls=[]
        class Opener:
            def open(_,request,timeout):
                calls.append((request,timeout));return self.response()
        with patch('releaseroom.provider.build_opener',return_value=Opener()):
            for _ in range(8):
                provider=BuilderProvider(self.store,self.key,'nearai','z-ai/glm-5.3-flash')
                self.assertEqual(provider.propose('Update the invitation'),DEFAULT)
            with self.assertRaises(Unavailable):provider.propose('Ninth request')
        self.assertEqual(len(calls),8)
        request,timeout=calls[0];body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://cloud-api.near.ai/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-key-only')
        self.assertEqual(body['model'],'z-ai/glm-5.3-flash')
        self.assertEqual(body['max_tokens'],1200);self.assertFalse(body['stream']);self.assertEqual(timeout,50)
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(body['reasoning_effort'],'low')

    def test_failed_paid_attempt_consumes_budget_without_an_automatic_retry(self):
        class Opener:
            def open(_,request,timeout):raise URLError('fixture network failure')
        with patch('releaseroom.provider.build_opener',return_value=Opener()):
            for _ in range(8):
                with self.assertRaises(Unavailable):BuilderProvider(self.store,self.key,'nearai').propose('Change')
            with self.assertRaises(Unavailable):BuilderProvider(self.store,self.key,'nearai').propose('Change')

    def test_empty_reasoning_response_is_visible_and_never_retried_automatically(self):
        envelope={'choices':[{'message':{'content':'','reasoning_content':'private reasoning'},'finish_reason':'length'}],
                  'usage':{'prompt_tokens':200,'completion_tokens':1200,'total_tokens':1400}}
        calls=[]
        class Opener:
            def open(_,request,timeout):calls.append(request);return io.BytesIO(json.dumps(envelope).encode())
        with patch('releaseroom.provider.build_opener',return_value=Opener()):
            with self.assertRaisesRegex(ValueError,'No release was created'):
                BuilderProvider(self.store,self.key,'nearai').propose('Change the invitation')
        self.assertEqual(len(calls),1)
        self.assertEqual(self.store.list(),[])
        with self.store.connect() as db:
            evidence=db.execute("SELECT data FROM events WHERE kind='model_response_rejected'").fetchone()['data']
            self.assertEqual(db.execute('SELECT used FROM model_budget').fetchone()[0],1)
        self.assertEqual(json.loads(evidence)['finish_reason'],'length')
        self.assertNotIn('private reasoning',evidence)

    def test_context_envelope_preserves_model_content_and_cannot_change_the_checker(self):
        envelope={'default':{**DEFAULT,'cta':'Join the build night'},'policy':POLICY}
        class Opener:
            def __init__(_,content):_.content=content
            def open(_,request,timeout):return self.response(_.content)
        with patch('releaseroom.provider.build_opener',return_value=Opener(envelope)):
            proposal=BuilderProvider(self.store,self.key,'nearai').propose('Join the build night')
        self.assertEqual(proposal,envelope['default'])
        self.assertTrue(check(proposal)['passed'])
        with self.store.connect() as db:
            receipt=json.loads(db.execute("SELECT data FROM events WHERE kind='model_response_received'").fetchone()['data'])
        self.assertEqual(receipt['raw_proposal_sha256'],sha(canonical(envelope)))
        self.assertEqual(receipt['content_sha256'],sha(canonical(proposal)))
        changed={'default':DEFAULT,'policy':{**POLICY,'contrast_min':0}}
        for changed in (changed,{'default':DEFAULT,'policy':{**POLICY,'version':True}}):
            with patch('releaseroom.provider.build_opener',return_value=Opener(changed)):
                with self.assertRaises(ValueError):BuilderProvider(self.store,self.key,'nearai').propose('Change the checker')
        unknown={'default':{**DEFAULT,'shell':'untrusted'},'policy':POLICY}
        with patch('releaseroom.provider.build_opener',return_value=Opener(unknown)):
            self.assertFalse(check(BuilderProvider(self.store,self.key,'nearai').propose('Unknown field'))['passed'])

    def test_provider_evidence_binds_accepted_content_without_recording_credentials_or_prompt(self):
        envelope={'id':'fixture-response','model':'z-ai/glm-5.3-flash',
                  'usage':{'prompt_tokens':100,'completion_tokens':60,'total_tokens':160,'private':'do-not-record'},
                  'choices':[{'message':{'content':json.dumps(DEFAULT)}}]}
        class Opener:
            def open(_,request,timeout):return io.BytesIO(json.dumps(envelope).encode())
        prompt='Private example request that must not appear in the event.'
        with patch('releaseroom.provider.build_opener',return_value=Opener()):
            BuilderProvider(self.store,self.key,'nearai').propose(prompt)
        with self.store.connect() as db:
            events=db.execute("SELECT data FROM events WHERE kind='model_response_received'").fetchall()
        self.assertEqual(len(events),1)
        receipt=json.loads(events[0]['data'])
        self.assertEqual(receipt['request_sha256'],sha(prompt.encode()))
        self.assertEqual(receipt['content_sha256'],sha(canonical(DEFAULT)))
        self.assertEqual(receipt['response_sha256'],sha(json.dumps(envelope).encode()))
        self.assertEqual(receipt['usage'],{'prompt_tokens':100,'completion_tokens':60,'total_tokens':160})
        self.assertNotIn(prompt,events[0]['data'])
        self.assertNotIn(self.key.read_text(),events[0]['data'])
        self.assertNotIn('do-not-record',events[0]['data'])

    def test_near_configuration_does_not_fall_back_to_a_vultr_credential(self):
        with patch.dict(os.environ,{'RELEASEROOM_STATE_DIR':str(self.root/'settings'),
            'RELEASEROOM_MODEL_PROVIDER':'nearai','RELEASEROOM_VULTR_KEY_FILE':str(self.key)},clear=True):
            _,_,provider=settings();self.assertFalse(provider.available)
        with patch.dict(os.environ,{'RELEASEROOM_STATE_DIR':str(self.root/'legacy'),
            'RELEASEROOM_VULTR_KEY_FILE':str(self.key)},clear=True):
            _,_,provider=settings();self.assertEqual(provider.provider,'vultr');self.assertTrue(provider.available)

    def test_oversized_or_non_object_responses_do_not_become_proposals(self):
        class Opener:
            def __init__(_,response):_.response=response
            def open(_,request,timeout):return _.response
        for response in [io.BytesIO(b'x'*65537),self.response(['wrong shape'])]:
            with patch('releaseroom.provider.build_opener',return_value=Opener(response)):
                with self.assertRaises(ValueError):BuilderProvider(self.store,self.key,'nearai').propose('Change')

    def test_unknown_provider_and_invalid_key_are_rejected_before_a_request(self):
        with self.assertRaises(ValueError):BuilderProvider(self.store,self.key,'https://other-host.invalid')
        self.key.write_text('   \n')
        with self.assertRaises(Unavailable):BuilderProvider(self.store,self.key,'nearai').propose('Change')


if __name__=='__main__':unittest.main()
