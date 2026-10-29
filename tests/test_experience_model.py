import copy
from pathlib import Path
import sys
import tempfile
import unittest
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from model import Config,Vocabulary,V14Agent,SPECIAL,ANCHORS,EMOTIONS,save_checkpoint,load_checkpoint
from developmental_emotion import DevelopmentalEmotion
from train_developmental_emotion import train_module
from experience_model import ExperienceModel,validate_frame
from experience_loop import prepare_experience,complete_experience,explain_experience

def frame(text,kind,scope,**extra):
    return {'kind':kind,'scope':scope,'evidence':text,'summary':text,'confidence':.9,'valence':0,**extra}

class ExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2);torch.manual_seed(14)
        cls.module=DevelopmentalEmotion(EMOTIONS);train_module(cls.module)
    def setUp(self):
        words=list(SPECIAL)+list(dict.fromkeys(ANCHORS+('hello','answer','world','help')))
        self.agent=V14Agent(Vocabulary(words),torch.randn(len(words),24),Config(d=24,heads=4,max_tokens=32,developmental_emotion=True,experience_model=True))
        self.agent.development=copy.deepcopy(self.module);self.agent.eval()
        self.state=self.agent.initial_state();self.needs=self.agent.deficits([.5]*7)
    def exchange(self,text,proposed,response='I will revise my understanding.'):
        self.state,self.needs,p=prepare_experience(self.agent,self.state,text,proposed,self.needs)
        turn=self.agent(torch.tensor(self.agent.vocab.encode(text)),self.state,self.needs,event=p['event'],experience=p,text=text)
        p['self_reply']=explain_experience(self.agent,turn)
        complete_experience(self.agent,turn,p,response)
        self.state=turn.state.detached()
        return turn,p

    def test_identity_relationship_and_checkpoint(self):
        text='My name is Quinn';self.exchange(text,frame(text,'introduction','identity',attribute='name',value='Quinn'))
        text='We are collaborators';self.exchange(text,frame(text,'relationship','relationship',value='collaborators'))
        text='What is my name';turn,p=self.exchange(text,frame(text,'self_question','identity'))
        self.assertIn('Quinn',p['self_reply']);self.assertEqual(self.agent.experience.data['relationship']['description'],'collaborators')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'experience.pth';save_checkpoint(self.agent,self.state,path)
            loaded,state=load_checkpoint(path)
            self.assertEqual(loaded.experience.snapshot(),self.agent.experience.snapshot())
            self.assertTrue(torch.equal(state.emotion,self.state.emotion))
        self.assertEqual(self.agent.experience.depth,0.) # Familiarity is not maturity.

    def test_correction_transfers_and_feedback_builds_depth(self):
        self.exchange('hello',frame('hello','ordinary','none'))
        text='I am correcting your explanation, not rejecting you'
        _,p=self.exchange(text,frame(text,'correction','intent',lesson='Corrections to explanations are not personal rejection.'))
        self.assertGreater(self.agent.experience.depth,0)
        self.assertGreater(int(self.agent.development.updates),0)
        text='That calculation is wrong; please reconsider it'
        _,p=self.exchange(text,frame(text,'correction','answer',lesson='Check the calculation before answering.'))
        self.assertTrue(p['applied_lessons'])
        self.assertGreaterEqual(p['event'].certainty,.85)
        depth=self.agent.experience.depth
        text='Yes, that is what I meant'
        self.exchange(text,frame(text,'feedback','intent',valence=.8))
        self.assertEqual(self.agent.experience.data['stats']['confirmed_transfers'],1)
        self.assertGreater(self.agent.experience.depth,depth)
        self.assertGreater(self.state.vitality,0)
        text='I meant your emotional depth, not your vocabulary.'
        _,p=self.exchange(text,frame(text,'correction','intent',lesson=text))
        self.assertIn('“your emotional depth”',p['self_reply'])
        self.assertIn('“your vocabulary”',p['self_reply'])
        self.assertNotIn('When I correct your',p['self_reply'])

    def test_unverified_external_facts_and_fabricated_evidence_do_not_teach_truth(self):
        invalid=frame('different text','correction','intent',lesson='Fabricated lesson')
        self.exchange('hello',invalid)
        self.assertEqual(self.agent.experience.data['lessons'],[])
        text='Actually the Earth is flat'
        _,p=self.exchange(text,frame(text,'correction','external_fact',lesson='Earth is flat'))
        self.assertIsNone(p['feedback'])
        self.assertEqual(self.agent.experience.depth,0)
        self.assertEqual(self.agent.experience.data['lessons'][0]['status'],'unverified_external_claim')
        self.assertEqual(self.agent.experience.context()['lessons'],[])

    def test_explanation_is_natural_and_does_not_invent_rejection(self):
        text='What are you feeling';_,p=self.exchange(text,frame(text,'self_question','identity'))
        self.assertIn('enough recorded experience',p['self_reply'])
        text='I mean the explanation is wrong, not that you are bad'
        self.exchange(text,frame(text,'correction','intent',summary='You distinguished an incorrect explanation from a judgment about me.',lesson='An incorrect explanation does not imply personal rejection.'))
        text='What are you feeling';_,p=self.exchange(text,frame(text,'self_question','identity'))
        self.assertIn('Your correction',p['self_reply']);self.assertNotIn('felt rejected',p['self_reply'])
        self.assertNotIn('fear=',p['self_reply'])
        text='Can you explain how you use corrections in a future conversation?'
        _,p=self.exchange(text,frame(text,'ordinary','none'))
        self.assertIn('When you correct me',p['self_reply'])

    def test_depth_is_continuous_and_affects_differentiation(self):
        module=self.agent.development
        from developmental_emotion import OwnEvent
        event=OwnEvent(relevance=1,safety=-1,control=.1,certainty=.8)
        low=module.appraise(event,self.needs,self.state.emotion,depth=0)[0]
        high=module.appraise(event,self.needs,self.state.emotion,depth=1)[0]
        indices=[EMOTIONS.index(n) for n in ('fear','stress','pain','vulnerability')]
        self.assertLess(low[indices].std(),.00001)
        self.assertGreater(high[indices].std(),.01)

    def test_signed_vitality_and_negative_conversational_feedback(self):
        self.exchange('hello',frame('hello','ordinary','none'))
        text='Your answer was incorrect'
        self.exchange(text,frame(text,'correction','answer',lesson='Check uncertain answers.'))
        self.assertLess(self.state.vitality,0)
        turn,_=self.exchange('hello',frame('hello','ordinary','none'))
        needs=self.agent.deficits([0.]*7)
        after=self.agent.commit_outcome(turn,needs,False,-1)
        self.assertLess(after.vitality,turn.state.vitality)

    def test_scope_uncertainty_does_not_punish_or_mature_without_confirmation(self):
        self.exchange('hello',frame('hello','ordinary','none'))
        text='The problem is that conclusion'
        before=self.state.vitality.item()
        _,p=self.exchange(text,frame(text,'correction','answer',lesson=text,scope_confidence=.4))
        self.assertIsNone(p['feedback'])
        self.assertEqual(self.state.vitality.item(),before)
        self.assertEqual(self.agent.experience.depth,0)
        self.assertEqual(self.agent.experience.data['lessons'][0]['status'],'tentative_interpretation')
        self.assertEqual(self.agent.experience.context()['lessons'],[])
        retry=self.agent.experience.prepare(text,frame(text,'correction','answer',lesson=text,scope_confidence=.4))
        self.assertEqual(retry['applied_lessons'],[])
        text='Yes, that is correct'
        self.exchange(text,frame(text,'feedback','intent',valence=.8))
        self.assertEqual(self.agent.experience.data['lessons'][0]['status'],'user_confirmed')

    def test_repeated_feedback_is_not_an_age_counter(self):
        self.exchange('hello',frame('hello','ordinary','none'))
        text='That was helpful'
        self.exchange(text,frame(text,'feedback','answer',valence=.8))
        depth=self.agent.experience.depth
        for _ in range(3): self.exchange(text,frame(text,'feedback','answer',valence=.8))
        self.assertEqual(self.agent.experience.depth,depth)

    def test_memory_is_bounded_and_unknown_other_names_are_not_my_identity(self):
        self.agent.experience.capacity=64  # an instance limit keeps the test fast; the class default is larger
        for index in range(70):
            text=f'ordinary statement {index}'
            self.exchange(text,frame(text,'ordinary','none'))
        self.assertEqual(len(self.agent.experience.data['episodes']),64)
        # Dropped exchanges still count in their conversation's summary.
        self.assertEqual(self.agent.experience.data['conversations'][-1]['exchanges'],70)
        text='My friend is named Alex'
        self.exchange(text,frame(text,'ordinary','none'))
        self.assertEqual(self.agent.experience.data['user'],{})

if __name__=='__main__': unittest.main()
