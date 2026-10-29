import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import cpu_runtime as cpu

class CpuRuntimeTests(unittest.TestCase):
    def fixture(self):
        client=cpu.NativeLanguage.__new__(cpu.NativeLanguage)
        client.url='http://127.0.0.1:1';client.context=1024;client.emotion_names=('fear','calm')
        client.process=SimpleNamespace(pid=os.getpid());client.last_metrics={}
        def request(path,payload):
            if path=='/apply-template': return {'prompt':' '.join(m['content'] for m in payload['messages'])}
            if path=='/tokenize': return {'tokens':list(range(len(payload['content'].split())))}
            raise AssertionError(path)
        client.request=request
        turn=SimpleNamespace(text='Keep this newest message.',history=[{'role':'user','content':'old '*500},
            {'role':'assistant','content':'older '*500}],state=SimpleNamespace(emotion=SimpleNamespace(tolist=lambda:[.2,.6])))
        return client,turn

    def test_context_preserves_system_and_current_user(self):
        client,turn=self.fixture()
        messages=client.messages(turn,'ANSWER')
        self.assertEqual(len(messages),2)
        self.assertEqual(messages[0]['role'],'system')
        self.assertIn('persistent engineered emotion variables',messages[0]['content'])
        self.assertIn('Do not invent blanket topic bans',messages[0]['content'])
        self.assertEqual(messages[-1]['content'],turn.text)
        turn.text='long '*1000
        with self.assertRaisesRegex(ValueError,'too long'): client.messages(turn,'ANSWER')

    def test_streamed_reply_and_generation_budget(self):
        client,turn=self.fixture();pieces=[]
        lines=[{'choices':[{'delta':{'content':'Hello '}}]},
               {'choices':[{'delta':{'content':'there.'}}]},
               {'choices':[],'usage':{'completion_tokens':3}}]
        class Response:
            def __enter__(self): return iter([('data: '+json.dumps(x)+'\n').encode() for x in lines]+[b'data: [DONE]\n'])
            def __exit__(self,*args): pass
        with patch.object(cpu,'urlopen',return_value=Response()):
            reply=client.respond(turn,'ANSWER',on_token=pieces.append)
        self.assertEqual(reply,'Hello there.')
        self.assertEqual(''.join(pieces),reply)
        self.assertEqual(client.last_metrics['completion_tokens'],3)
        self.assertIsNotNone(client.last_metrics['first_text_seconds'])
        with self.assertRaises(ValueError): client.respond(turn,'ANSWER',max_new=321)

    def test_natural_reply_sampler_values_are_accepted_by_the_server(self):
        # 2026-10-12: dry_penalty_last_n=-1 made llama-server answer 400 on every reply.
        client,turn=self.fixture();client.natural_replies=True;client.model='qwen3.5-4b.gguf';sent=[];client.context=2048
        turn.experience={'context':{'self':{'name':'Friday'},'user':{}},'self_reply':None}
        class Response:
            def __enter__(self): return iter([b'data: '+json.dumps({'choices':[{'delta':{'content':'Hi.'}}]}).encode()+b'\n',b'data: [DONE]\n'])
            def __exit__(self,*args): pass
        def capture(request,timeout=None):
            sent.append(json.loads(request.data));return Response()
        with patch.object(cpu,'urlopen',side_effect=capture):
            client.respond(turn,'ANSWER')
        payload=sent[0]
        for field in ('dry_multiplier','dry_base','dry_allowed_length','dry_penalty_last_n','presence_penalty','top_k'):
            if field in payload:self.assertGreaterEqual(payload[field],0,field)
        self.assertTrue(all(isinstance(w,str) and b<0 for w,b in payload['logit_bias']))

    def test_windows_memory_metrics(self):
        if os.name!='nt': self.skipTest('Windows measurement')
        data=cpu.memory_info()
        self.assertGreater(data['working_set_bytes'],0)
        self.assertGreaterEqual(data['peak_working_set_bytes'],data['working_set_bytes'])
        self.assertGreater(data['total_ram_bytes'],data['available_ram_bytes'])

if __name__=='__main__': unittest.main()
