import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from releaseroom.artifact import DEFAULT
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

    def test_failed_paid_attempt_consumes_budget_without_an_automatic_retry(self):
        class Opener:
            def open(_,request,timeout):raise URLError('fixture network failure')
        with patch('releaseroom.provider.build_opener',return_value=Opener()):
            for _ in range(8):
                with self.assertRaises(URLError):BuilderProvider(self.store,self.key,'nearai').propose('Change')
            with self.assertRaises(Unavailable):BuilderProvider(self.store,self.key,'nearai').propose('Change')

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
