"""Small own-event appraisal, lifelong outcome memory, and regulation module.

Training targets are declared synthetic design targets, not human measurements.
Only explicit outcomes update long-term memory. Forward passes are read-only.
"""
from dataclasses import dataclass, asdict, replace
import math
import torch
from torch import nn

STRATEGIES=('NONE','CHECK_EVIDENCE','REAPPRAISE','SEEK_SUPPORT')
EVENT_FIELDS=('relevance','progress','certainty','control','novelty','safety','support','effort','agency')
EXTENDED_FIELDS=('aversion','comparison','vastness','devaluation')

@dataclass(frozen=True)
class OwnEvent:
    cue: str = 'general'
    relevance: float = 0.
    progress: float = 0.
    certainty: float = .5
    control: float = .5
    novelty: float = 0.
    safety: float = 0.
    support: float = 0.
    effort: float = 0.
    agency: float = 0.
    aversion: float = 0.
    comparison: float = 0.
    vastness: float = 0.
    devaluation: float = 0.

    def __post_init__(self):
        if not isinstance(self.cue,str) or not self.cue.strip() or len(self.cue)>80:
            raise ValueError('Event cue must be a nonempty string up to 80 characters')
        for name,value in asdict(self).items():
            if name=='cue': continue
            low=-1 if name in ('progress','safety','agency') else 0
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not low<=value<=1:
                raise ValueError(f'Invalid own-event {name}: expected [{low},1]')

class DevelopmentalEmotion(nn.Module):
    capacity=64
    def __init__(self,names,extended=False):
        super().__init__()
        self.names=tuple(names);self.cues=[];self.extended=extended
        width=23 if extended else 19
        self.appraiser=nn.Sequential(nn.Linear(width,48),nn.Tanh(),nn.Linear(48,len(names)))
        self.regulator=nn.Sequential(nn.Linear(width,24),nn.Tanh(),nn.Linear(24,4))
        self.register_buffer('expected',torch.zeros(self.capacity))
        self.register_buffer('learned_control',torch.full((self.capacity,),.5))
        self.register_buffer('visits',torch.zeros(self.capacity))
        self.register_buffer('baseline',torch.full((len(names),),.025))
        self.register_buffer('persistence',torch.full((len(names),),.65))
        self.register_buffer('strategy_value',torch.zeros(4))
        self.register_buffer('strategy_visits',torch.zeros(4))
        self.register_buffer('updates',torch.tensor(0.))
        self.register_buffer('trained',torch.tensor(False))
        self.requires_grad_(False)

    def get_extra_state(self): return {'cues':list(self.cues)}
    def set_extra_state(self,state):
        cues=state['cues']
        if len(cues)>self.capacity or len(set(cues))!=len(cues) or any(not isinstance(c,str) for c in cues):
            raise ValueError('Invalid developmental memory')
        self.cues=list(cues)

    def features(self,event,needs):
        index=self.cues.index(event.cue) if event.cue in self.cues else None
        expected=self.expected[index] if index is not None else needs.new_tensor(0.)
        control=self.learned_control[index] if index is not None else needs.new_tensor(.5)
        base=needs.new_tensor([event.relevance,event.progress,event.certainty,event.control,
                              event.novelty,event.safety,event.support,event.effort,event.agency])
        if self.extended:base=torch.cat((base,needs.new_tensor([getattr(event,k) for k in EXTENDED_FIELDS])))
        return torch.cat((base,torch.stack((expected,control,base[1]-expected)),needs))

    def recovered_emotion(self,previous,elapsed_seconds):
        if isinstance(elapsed_seconds,bool) or not isinstance(elapsed_seconds,(int,float)) or not math.isfinite(elapsed_seconds) or elapsed_seconds<0:
            raise ValueError('Elapsed time must be finite and nonnegative')
        half_life=60+240*self.persistence
        rest_target=(.025+.2*self.baseline).clamp(0,1)
        decay=torch.exp(-math.log(2)*min(elapsed_seconds,2592000)/half_life)
        return rest_target+(previous-rest_target)*decay

    def appraise(self,event,needs,previous,deliberation=0.,regulate=True,elapsed_seconds=0.,depth=None,parts=None):
        previous=self.recovered_emotion(previous,elapsed_seconds)
        x=self.features(event,needs)
        def propose(e,features):
            raw=self.appraiser(features).sigmoid()
            # Zero personal relevance has a fixed low appraisal irrespective of words.
            return (1-e.relevance)*raw.new_full(raw.shape,.025)+e.relevance*raw
        proposal=propose(event,x)
        # v35.1 mixed feelings: news with a good side and a hard side. Each side is appraised too and the stronger reaction
        # for each feeling is kept, so joy and sadness can both rise instead of cancelling out in one reading.
        part_proposals=[propose(part,self.features(part,needs)) for part in parts or ()]
        for part_proposal in part_proposals:
            proposal=torch.maximum(proposal,part_proposal)
        if depth is not None:
            if not 0<=depth<=1: raise ValueError('Emotional depth must be in [0,1]')
            coarse=proposal.clone()
            groups=(('fear','stress','pain','vulnerability'),('joy','calm','connection','pride'),
                    ('anger','sadness','shame','guilt','envy'))
            if self.extended:groups=groups[:2]+(('anger','sadness','shame','guilt','envy','disgust','contempt'),('confusion','surprise','interest','awe'))
            for group in groups:
                indices=[self.names.index(name) for name in group]
                coarse[indices]=proposal[indices].mean()
            proposal=(1-depth)*coarse+depth*proposal
        logits=self.regulator(x)+.3*self.strategy_value
        strategy=int(logits.argmax()) if regulate and event.relevance>0 else 0
        carryover_check=regulate and strategy==0 and max(previous[self.names.index('fear')].item(),previous[self.names.index('stress')].item())>.6
        if carryover_check:strategy=1
        fear,stress=(self.names.index(n) for n in ('fear','stress'))
        confirmed_threat=event.safety<-.5 and event.certainty>.7
        if strategy==2 and (confirmed_threat or event.safety<0 or event.control<.5): strategy=1
        if strategy==3 and event.support<=0: strategy=1
        regulated=proposal.clone()
        if strategy==2:
            # Evidence-backed reappraisal reduces activation, not perceived facts.
            regulated[[fear,stress]]=regulated[[fear,stress]]*(1-.25*event.control*event.certainty)
        if strategy==3:
            regulated[stress]=regulated[stress]*(1-.15*event.support)
        rho=(self.persistence+.12*previous.square()).clamp(.35,.92)
        target=(regulated+.2*self.baseline).clamp(0,1)
        # Fast onset, slow recovery: a reaction to a new event arrives within the turn
        # (persona red-team: insults and losses barely registered), while decay keeps the
        # learned persistence, so moods still linger and fade gradually.
        # Only a real event-driven rise gets the fast onset; drift toward the resting tone does not.
        rho=torch.where(target>previous+.05,.45*rho,rho)
        emotion=(rho*previous+(1-rho)*target).clamp(0,1)
        selected_deliberation=max(deliberation,.65 if strategy==1 else .35 if strategy else 0.)
        offset=13 if self.extended else 9
        details={'event':asdict(event),'expected_progress':x[offset].item(),'learned_control':x[offset+1].item(),
                 'prediction_error':x[offset+2].item(),'strategy':STRATEGIES[strategy],
                 'strategy_index':strategy,'deliberation':selected_deliberation,
                 'unregulated_appraisal':proposal.detach().tolist(),
                 'regulated_appraisal':regulated.detach().tolist(),
                 'baseline':self.baseline.tolist(),'persistence':rho.detach().tolist(),
                 'lifetime_outcomes':int(self.updates.item())}
        details['elapsed_seconds']=elapsed_seconds
        details['emotional_depth']=depth
        details['carryover_arousal_check']=carryover_check
        if parts:
            details['mixed_parts']=[asdict(part) for part in parts]
            details['mixed_proposals']=[p.detach().tolist() for p in part_proposals]  # which part brings which feeling
        return regulated,emotion,selected_deliberation,details

    @torch.no_grad()
    def observe(self,details,quality,safe=False,control=None):
        if not math.isfinite(quality): raise ValueError('Invalid developmental outcome')
        if control is not None and (isinstance(control,bool) or not isinstance(control,(int,float)) or not math.isfinite(control) or not 0<=control<=1):
            raise ValueError('Observed control must be in [0,1]')
        event=OwnEvent(**details['event'])
        if event.relevance<=0: return
        if event.cue not in self.cues:
            if len(self.cues)<self.capacity: self.cues.append(event.cue)
            else:
                index=int(self.visits.argmin());self.cues[index]=event.cue
                self.expected[index]=0;self.learned_control[index]=.5;self.visits[index]=0
        index=self.cues.index(event.cue)
        # Rate declines gently with experience but stays nonzero: lifelong fluidity.
        rate=max(.025,.15/math.sqrt(1+self.visits[index].item()/20))
        outcome=max(-1.,min(1.,quality))
        self.expected[index].lerp_(self.expected.new_tensor(outcome),rate)
        if control is not None: self.learned_control[index].lerp_(self.expected.new_tensor(control),rate)
        self.visits[index]+=1;self.updates+=1
        strategy=details['strategy_index'];self.strategy_visits[strategy]+=1
        self.strategy_value[strategy].lerp_(self.expected.new_tensor(outcome),.05)
        desired=self.baseline.new_full(self.baseline.shape,.025)
        for name in ('joy','calm','pride'): desired[self.names.index(name)]+=.18*max(outcome,0)
        for name in ('fear','stress','sadness'): desired[self.names.index(name)]+=.18*max(-outcome,0)
        self.baseline.lerp_(desired,.01);self.baseline.clamp_(0,.35)
        recovery=.5 if safe and outcome>0 else .78 if outcome<0 else .65
        self.persistence.lerp_(self.persistence.new_full(self.persistence.shape,recovery),.02)
        self.persistence.clamp_(.35,.85)

    @torch.no_grad()
    def expect(self,cue,progress):
        """Learn what a kind of event usually brings: the cue's expected progress moves toward the appraised progress, at the
        same rate as outcomes (section 3 of docs/MATH.md). Only the expectation changes; baseline mood, persistence and
        strategy values move only on real outcomes (observe). v35.2: this is how a subject with a history puts Friday on edge,
        through the appraisal's threat term, instead of a number added to the state."""
        if not isinstance(progress,(int,float)) or not math.isfinite(progress): raise ValueError('Invalid expected progress')
        if cue not in self.cues:
            if len(self.cues)<self.capacity: self.cues.append(cue)
            else:
                index=int(self.visits.argmin());self.cues[index]=cue
                self.expected[index]=0;self.learned_control[index]=.5;self.visits[index]=0
        index=self.cues.index(cue)
        rate=max(.025,.15/math.sqrt(1+self.visits[index].item()/20))
        self.expected[index].lerp_(self.expected.new_tensor(max(-1.,min(1.,progress))),rate)
        self.visits[index]+=1

    def outcome_emotion(self,details,previous,needs,quality,safe=False,control=None):
        event=OwnEvent(**details['event'])
        if event.relevance<=0: return previous
        actual=replace(event,progress=max(-1.,min(1.,quality)),certainty=1.,novelty=0.,
                       safety=1. if safe else event.safety,
                       control=event.control if control is None else control)
        return self.appraise(actual,needs,previous,depth=details.get('emotional_depth'))[1]

def design_targets(x,names):
    """Explicit synthetic appraisal specification used to train the tiny module."""
    relevance,progress,certainty,control,novelty,safety,support,effort,agency=x[:9]
    offset=13 if len(x)==23 else 9
    expected,learned_control,error=x[offset:offset+3]
    importance=(.65+.35*(x[offset+3:].mean()/ .4).clamp(0,1))
    if len(x)!=23:importance=importance*relevance
    effective_control=.6*control+.4*learned_control
    threat=((-safety).clamp_min(0)+.55*(-expected).clamp_min(0)+.2*(1-certainty)).clamp(0,1)
    loss=(-progress).clamp_min(0);gain=progress.clamp_min(0)
    values={'fear':threat*(1-.55*effective_control),'stress':(.6*threat+.4*loss+.25*effort)*(1-.3*effective_control),
            'sadness':loss*(1-.65*effective_control),'anger':loss*effective_control*agency.clamp_min(0),
            'joy':gain*(.7+.3*certainty),'calm':(.65*effective_control+.35*safety.clamp_min(0))*(1-threat),
            'confusion':(1-certainty)*(.4+.6*novelty),'interest':novelty*(1-.5*threat),
            'surprise':error.abs().clamp(0,1)*novelty,'pain':.5*loss*(1-effective_control),
            'shame':loss*(-agency).clamp_min(0)*(1-certainty),'guilt':loss*(-agency).clamp_min(0)*certainty,
            'connection':support,'pride':gain*(-agency).clamp_min(0),
            'vulnerability':threat*(1-effective_control)}
    if len(x)==23:
        aversion,comparison,vastness,devaluation=x[9:13]
        # Distinct own appraisals, not an inference from the user's emotion label.
        # Devaluation concerns an evidenced pattern of conduct, not human worth.
        values.update(disgust=aversion*certainty,
                      envy=comparison*(.5+.5*certainty)*(1-.5*gain),
                      awe=vastness*(.5+.5*novelty)*(1-.5*threat),
                      contempt=devaluation*certainty*agency.clamp_min(0))
    target=torch.stack([(.025+importance*values.get(name,x.new_tensor(0.))).clamp(0,1) for name in names])
    strategy=1 if threat>.35 and certainty<.6 else 2 if threat>.2 and safety>=0 and control>=.5 else 3 if loss>.4 and support>.4 else 0
    return target,strategy
