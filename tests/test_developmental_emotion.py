import copy
from pathlib import Path
import sys
import tempfile
import unittest
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from model import Config,Vocabulary,V14Agent,SPECIAL,ANCHORS,EMOTIONS,save_checkpoint,load_checkpoint,observed_outcome
from developmental_emotion import OwnEvent,DevelopmentalEmotion
from train_developmental_emotion import train_module,sequence_checks

class DevelopmentalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2);torch.manual_seed(14)
        cls.module=DevelopmentalEmotion(EMOTIONS)
        cls.metrics=train_module(cls.module)

    def setUp(self):
        torch.manual_seed(19)
        words=list(SPECIAL)+list(dict.fromkeys(ANCHORS+('hello','answer','world','help')))
        self.agent=V14Agent(Vocabulary(words),torch.randn(len(words),24),Config(d=24,heads=4,max_tokens=32,developmental_emotion=True))
        self.agent.development=copy.deepcopy(self.module);self.agent.eval()
        self.ids=torch.tensor(self.agent.vocab.encode('hello help'));self.needs=self.agent.deficits([.5]*7)
    def turn(self,event,state=None,**kwargs):
        return self.agent(self.ids,self.agent.initial_state() if state is None else state,self.needs,event=event,**kwargs)

    def test_trained_appraisal_and_lifelong_sequences(self):
        self.assertLess(self.metrics['after_appraisal_mse'],.01)
        result=sequence_checks(self.agent.development)
        self.assertTrue(all(result['checks'].values()),result)

    def test_mixed_news_keeps_both_feelings(self):
        # v35.1: a good side and a hard side read as one event cancel out; appraised as parts, both feelings rise.
        joy,sadness=EMOTIONS.index('joy'),EMOTIONS.index('sadness')
        good=OwnEvent(cue='conversation:understanding',relevance=.8,progress=.6,certainty=.8,control=.6,support=.3)
        hard=OwnEvent(cue='conversation:understanding',relevance=.8,progress=-.6,certainty=.8,control=.3,support=.3)
        whole=OwnEvent(cue='conversation:understanding',relevance=.8,progress=0.,certainty=.8,control=.45,support=.3)
        alone=self.turn(whole).proposal
        both=self.turn(whole,experience={'mixed':{'events':[good,hard]}})
        self.assertGreater(both.proposal[joy],alone[joy]+.05)
        self.assertGreater(both.proposal[sadness],alone[sadness]+.05)
        self.assertEqual(len(both.development['mixed_parts']),2)
        self.assertEqual(both.development['event']['progress'],0.)  # learning still sees the whole message

    def test_own_relevance_not_emotional_words_and_no_implicit_growth(self):
        zero=self.agent.initial_state();event=OwnEvent()
        neutral=self.turn(event,text='hello')
        emotional=self.turn(event,text='I am afraid, angry, and hurt')
        self.assertTrue(torch.equal(neutral.proposal,emotional.proposal))
        self.assertTrue(torch.all(neutral.state.emotion<.02))
        self.assertEqual(int(self.agent.development.updates),0)
        self.assertEqual(self.agent.development.cues,[])
        relevant=self.turn(OwnEvent(relevance=1,safety=-1,control=.1,certainty=.9))
        self.assertGreater(relevant.proposal[EMOTIONS.index('fear')],emotional.proposal[EMOTIONS.index('fear')]+.2)

    def test_outcome_growth_checkpoint_and_bounded_long_run(self):
        event=OwnEvent(cue='difficult-task',relevance=1,safety=-.5,certainty=.4,control=.2)
        state=self.agent.initial_state()
        for index in range(120):
            turn=self.turn(event,state)
            state=self.agent.commit_outcome(turn,self.needs,index>=40,-1 if index<40 else 1,control=.2 if index<40 else .9)
            self.assertTrue(torch.isfinite(state.emotion).all())
            self.assertTrue(((state.emotion>=0)&(state.emotion<=1)).all())
            self.assertLessEqual(state.fast.norm().item(),self.agent.cfg.fast_max+1e-5)
        expected=self.agent.development.expected.clone()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'engine.pth';save_checkpoint(self.agent,state,path)
            restored,restored_state=load_checkpoint(path)
            self.assertEqual(restored.development.cues,['difficult-task'])
            self.assertTrue(torch.equal(expected,restored.development.expected))
            self.assertTrue(torch.equal(state.emotion,restored_state.emotion))
            self.assertEqual(int(restored.development.updates),120)
        self.assertEqual(int(self.agent.development.updates),120)
        self.assertTrue(torch.equal(expected,self.agent.development.expected))

    def test_regulation_changes_processing_without_erasing_confirmed_threat(self):
        threat=OwnEvent(relevance=1,safety=-1,certainty=.2,control=.1)
        checked=self.turn(threat);unchecked=self.turn(threat,regulate=False)
        self.assertEqual(checked.development['strategy'],'CHECK_EVIDENCE')
        self.assertGreater(checked.deliberation,unchecked.deliberation)
        self.assertLess(checked.reflex_share,unchecked.reflex_share)
        confirmed=self.turn(OwnEvent(relevance=1,safety=-1,certainty=.95,control=.9))
        self.assertNotEqual(confirmed.development['strategy'],'REAPPRAISE')
        self.assertGreater(confirmed.proposal[EMOTIONS.index('fear')],.1)
        # Measured feedback credits the selected strategy, rather than assumed success.
        before=self.agent.development.strategy_visits.clone()
        self.agent.commit_outcome(checked,self.needs,True,1.,control=.9)
        self.assertEqual(int((self.agent.development.strategy_visits-before).sum()),1)

    def test_carried_fear_changes_processing_without_inventing_current_threat(self):
        state=self.agent.initial_state()
        state.emotion[EMOTIONS.index('fear')]=.9
        state.emotion[EMOTIONS.index('stress')]=.8
        checked=self.turn(OwnEvent(),state)
        unchecked=self.turn(OwnEvent(),state,regulate=False)
        self.assertTrue(checked.development['carryover_arousal_check'])
        self.assertEqual(checked.development['strategy'],'CHECK_EVIDENCE')
        self.assertGreater(checked.deliberation,unchecked.deliberation)
        self.assertEqual(checked.development['event']['safety'],0)
        self.assertEqual(checked.development['event']['progress'],0)

    def test_idle_recovery_precedes_cognition_and_is_not_applied_twice(self):
        state=self.agent.initial_state();state.emotion[EMOTIONS.index('fear')]=.9
        expected=self.agent.initial_state();expected.emotion=self.agent.development.recovered_emotion(state.emotion,600)
        timed=self.turn(OwnEvent(),state,elapsed_seconds=600)
        manual=self.turn(OwnEvent(),expected)
        self.assertTrue(torch.equal(timed.before.emotion,expected.emotion))
        self.assertTrue(torch.equal(timed.policy,manual.policy))
        self.assertTrue(torch.equal(timed.state.emotion,manual.state.emotion))
        self.assertTrue(timed.development['recovery_applied_before_perception'])

    def test_invalid_events_and_control_are_rejected_without_updates(self):
        for data in ({'relevance':float('nan')},{'certainty':2},{'cue':''},{'control':True}):
            with self.assertRaises(ValueError): OwnEvent(**data)
        turn=self.turn(OwnEvent(relevance=1))
        for control in (float('nan'),-1,True):
            with self.assertRaises(ValueError): self.agent.commit_outcome(turn,self.needs,True,1.,control)
        self.assertEqual(int(self.agent.development.updates),0)

    def test_elapsed_time_recovers_emotion_without_erasing_growth(self):
        state=self.agent.initial_state();state.emotion[EMOTIONS.index('fear')]=.9
        immediate=self.turn(OwnEvent(),state)
        later=self.turn(OwnEvent(),state,elapsed_seconds=1200)
        self.assertLess(later.state.emotion[EMOTIONS.index('fear')],immediate.state.emotion[EMOTIONS.index('fear')]/3)
        self.assertEqual(int(self.agent.development.updates),0)
        for duration in (-1,float('nan'),True):
            with self.assertRaises(ValueError): self.turn(OwnEvent(),state,elapsed_seconds=duration)

    def test_measured_success_updates_emotion_immediately(self):
        state=self.agent.initial_state();state.emotion[EMOTIONS.index('fear')]=.8
        turn=self.turn(OwnEvent(relevance=1,safety=-.5,certainty=.3,control=.2),state)
        after=self.agent.commit_outcome(turn,self.needs,True,1.,control=.9)
        self.assertLess(after.emotion[EMOTIONS.index('fear')],turn.state.emotion[EMOTIONS.index('fear')])
        self.assertGreater(after.emotion[EMOTIONS.index('joy')],turn.state.emotion[EMOTIONS.index('joy')])

if __name__=='__main__': unittest.main()
