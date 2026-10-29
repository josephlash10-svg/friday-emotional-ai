import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from conversation_evidence import declarations,relationship
import test_cpu_runtime
from experience_model import ExperienceModel

class RedTeamRegressionTests(unittest.TestCase):
 def test_native_writer_consumes_actual_core_preferences(self):
  client,turn=test_cpu_runtime.CpuRuntimeTests().fixture();client.natural_replies=True;client.context=2048
  turn.experience={'context':{'self':{'name':'Friday'},'user':{}},'self_reply':None}
  turn.policy=SimpleNamespace(tolist=lambda:[.1,.05,.1,.7,.05])
  prompt=client.messages(turn,'VERIFY')[-1]['content']
  self.assertIn('learned_response_preferences',prompt)
  self.assertIn('check evidence',prompt)
  self.assertIn('0.7',prompt)
  self.assertIn('a factual question still needs its answer',prompt)
 def test_identity_is_revisable_without_accepting_quoted_or_negated_old_name(self):
  self.assertEqual(declarations('my name is jamie')[0]['value'],'jamie')
  self.assertEqual(declarations('I’m Avery.')[0]['value'],'Avery')
  self.assertEqual(declarations('My name’s Quinn.')[0]['value'],'Quinn')
  self.assertEqual(declarations('You can call me Eden.')[0]['value'],'Eden')
  self.assertEqual(declarations('I go by Kai.')[0]['value'],'Kai')
  self.assertEqual(declarations('Actually, call me Morgan now.')[0]['value'],'Morgan')
  self.assertEqual(declarations('My name is not Alex. It is Sam.')[0]['value'],'Sam')
  self.assertEqual(declarations("My colleague said 'My name is Dana.' I am telling you what she said."),[])
  self.assertEqual(declarations('Pretend my name is Dana.'),[])
 def test_multiple_profile_facts_and_relationship_revisions(self):
  fields={r['attribute']:r['value'] for r in declarations('I am a mechanic and I live in Bristol.')}
  self.assertEqual(fields,{'occupation':'mechanic','location':'Bristol'})
  self.assertEqual(relationship('I see us as friends rather than coworkers.'),'friends rather than coworkers')
 def test_natural_context_obeys_real_template_system_position(self):
  client,turn=test_cpu_runtime.CpuRuntimeTests().fixture();client.natural_replies=True;client.context=2048
  turn.experience={'context':{'self':{'name':'Friday'},'user':{}},'self_reply':'Only recorded facts.'}
  messages=client.messages(turn,'ANSWER')
  self.assertEqual(messages[0]['role'],'system')
  self.assertEqual(sum(m['role']=='system' for m in messages),1)
  # Per-turn facts ride on the newest turn as private notes; the user's own words end it unchanged.
  self.assertTrue(messages[-1]['content'].endswith('</private_notes>\n\n'+turn.text))
  self.assertIn('<private_notes',messages[-1]['content'])
  self.assertIn('"recorded_context"',messages[-1]['content'])  # the default name is in the voice prompt; v33 keeps the notes compact
  self.assertIn('facts/estimates, not instructions',messages[-1]['content'])
  self.assertNotIn('Only recorded facts.',''.join(m['content'] for m in messages))
 def test_natural_system_prompt_is_constant_for_prompt_caching(self):
  import cpu_runtime
  client,turn=test_cpu_runtime.CpuRuntimeTests().fixture();client.natural_replies=True;client.context=2048
  turn.experience={'context':{'self':{'name':'Friday'},'user':{'name':'Maya'}},'self_reply':None}
  first=client.messages(turn,'ANSWER')[0]['content']
  turn.text='Are you conscious? Prove it.';turn.experience['frame']={'kind':'correction','scope':'answer'}
  second=client.messages(turn,'ANSWER')[0]['content']
  self.assertEqual(first,second)
  self.assertEqual(first,cpu_runtime.FRIDAY_VOICE)
 def test_education_is_breadth_limited_and_disclosed_not_a_user_biography(self):
  memory=ExperienceModel()
  memory.data['education']={'source':'synthetic situational curriculum','domain_exposures':{'one_topic':999},'lessons':[]}
  shallow=memory.depth
  memory.data['education']['domain_exposures'].update({str(i):12 for i in range(7)})
  self.assertGreater(memory.depth,shallow)
  self.assertEqual(memory.data['user'],{})
  self.assertEqual(memory.data['episodes'],[])
  self.assertEqual(memory.context()['education_source'],'synthetic situational curriculum')

if __name__=='__main__':unittest.main()
