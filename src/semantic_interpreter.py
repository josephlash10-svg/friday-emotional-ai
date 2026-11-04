"""Trained event classification over frozen contextual language features."""
import re
from pathlib import Path
import torch
from torch import nn
from conversation_evidence import declarations,relationship,correction_topics,reported_speech,belief_revision,interpersonal_report
from developmental_emotion import EVENT_FIELDS,EXTENDED_FIELDS

LABELS=(('ordinary','none',0),('correction','intent',0),('correction','answer',-.5),
        ('correction','external_fact',0),('feedback','intent',.8),('feedback','answer',.8),
        ('feedback','answer',-.8),('introduction','identity',0),('relationship','relationship',.3),
        ('preference','preference',0),('self_question','identity',0))

# v35 (2026-11-03): the own-event heads read the frozen language model's last hidden state, which missed sad news said
# casually: in the live chat "only like two more sunday dinners. i cried in the supply closet" read as joy and closeness.
# Heads trained on that state plus the MiniLM sentence vector (src/train_meaning_appraisal.py) read it as sad, and fit
# the held-out natural, formal and extended sets better. They ship as release/appraisal-heads.pth and are kept off the
# module tree, so checkpoints (which hold someone's memories) are unchanged; without the file or the MiniLM model,
# Friday uses the heads in its checkpoint.
MEANING_SCALE=4.  # the MiniLM vector is unit length; the layer-normed LM features have unit variance per dimension
HEADS_FILE=Path(__file__).resolve().parents[1]/'release/appraisal-heads.pth'

def meaning_head_modules(width):
    return (nn.Sequential(nn.Linear(width,64),nn.Tanh(),nn.Linear(64,9)),nn.Sequential(nn.Linear(width,64),nn.Tanh(),nn.Linear(64,4)))

def combined_features(features,vector):
    return torch.cat((features,MEANING_SCALE*vector.to(features.dtype)))

def attach_meaning_heads(interpreter,path=HEADS_FILE):
    """Load the shipped heads onto the interpreter (as a plain attribute). Returns the version or None."""
    import os
    if os.environ.get('FRIDAY_MEANING','').lower()=='off' or not Path(path).exists():return None
    saved=torch.load(path,map_location='cpu',weights_only=True)
    core,extended=meaning_head_modules(saved['width'])
    core.load_state_dict(saved['core']);extended.load_state_dict(saved['extended'])
    core.eval();extended.eval();core.requires_grad_(False);extended.requires_grad_(False)
    object.__setattr__(interpreter,'_meaning_heads',(core,extended,saved['version']))
    return saved['version']

def meaning_heads_for(interpreter,text,features):
    """(core head, extended head, combined features) when the shipped heads and a MiniLM vector are both available."""
    heads=getattr(interpreter,'_meaning_heads',None)
    if heads is None:return None
    import meaning_recall
    vectors=meaning_recall.index().embed([text])
    if vectors is None:return None
    return heads[0],heads[1],combined_features(features,vectors[0])

class SemanticInterpreter(nn.Module):
    def __init__(self,width,hidden=96):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(width,hidden),nn.Tanh(),nn.Linear(hidden,len(LABELS)))
        self.register_buffer('trained',torch.tensor(False));self.requires_grad_(False)
    def enable_own_event(self,width,extended=False):
        self.extended=extended
        self.event_head=nn.Sequential(nn.Linear(width,64),nn.Tanh(),nn.Linear(64,9))
        if extended:self.extended_event_head=nn.Sequential(nn.Linear(width,64),nn.Tanh(),nn.Linear(64,4))
        self.register_buffer('event_trained',torch.tensor(False))
        self.requires_grad_(False)
    def forward(self,features): return self.net(features)
    @torch.no_grad()
    def interpret(self,decoder,text,experience=None):
        if not bool(self.trained): raise RuntimeError('Semantic interpreter has not been trained')
        features=decoder.meaning_features(text)
        latent=self.net[:2](features)
        logits=self.net[2](latent)
        raw_top=int(logits.argmax());memory_support=[]
        if experience is not None:
            for lesson in experience.data['lessons']:
                if lesson['scope']=='external_fact' or lesson.get('status')=='tentative_interpretation' or lesson.get('semantic_class')!=raw_top: continue
                key=lesson.get('semantic_key')
                if not key or len(key)!=len(latent): continue
                similarity=torch.nn.functional.cosine_similarity(latent,latent.new_tensor(key),dim=0).item()
                if similarity>.75:
                    logits[raw_top]+=min(1.5,2*(similarity-.5))*lesson['confidence']
                    memory_support.append(lesson['id'])
                    break
        probabilities=logits.softmax(-1)
        index=int(probabilities.argmax());kind,scope,valence=LABELS[index]
        scope_confidence=probabilities[index].item()
        confidence=min(1.,sum(probabilities[i].item() for i,label in enumerate(LABELS) if label[0]==kind))
        if confidence<.65: kind,scope,valence='ordinary','none',0.
        if kind=='self_question' and not re.search(r'\b(?:i|me|my|mine|you|your|us|we|our|friday|own|feelings?|emotions?)\b',text,re.I):
            # A world question is not an identity question merely because it
            # starts with "What is". Scope is validated against the utterance.
            kind,scope,valence='ordinary','none',0.
        if re.fullmatch(r'(?:no[, ]+)?(?:not like that|not that|you missed it|that is wrong|that\x27s wrong)[.! ]*',text.lower().strip()):
            kind,scope,valence='correction','intent',0.
            confidence=.99;scope_confidence=.4
        if re.search(r'\b(?:i was being sarcastic|that was sarcasm|i was joking|i meant it ironically)\b',text.lower()):
            kind,scope,valence='correction','intent',0.
            confidence=scope_confidence=.99
        attribute=value=lesson=''
        subject='agent' if re.search(r'\b(?:you|your)\b',text.lower()) else 'user'
        if reported_speech(text):subject='other'
        if belief_revision(text):subject='user'
        if interpersonal_report(text):subject='user'
        topics=correction_topics(text)
        if kind=='correction' and 'excluded_topic' in topics:
            # An explicit contrast resolves which interpretation is being revised.
            scope='intent';confidence=scope_confidence=.99
        known_name=experience.data['user'].get('name',{}).get('value') if experience else None
        profile=declarations(text,known_name)
        relation=relationship(text)
        if profile:
            kind,scope,valence='introduction','identity',0.
            confidence=scope_confidence=.99
            attribute,value=profile[0]['attribute'],profile[0]['value']
        if relation:
            kind,scope,valence='relationship','relationship',.3
            confidence=scope_confidence=.99;value=relation
        if kind=='relationship' and not relation:value=''
        if kind=='preference' and re.search(r'\b(?:prefer|replies|wording|answers|respond|language|format|concise|brief)\b',text,re.I):
            attribute='reply_style';value=text[:120]
        elif kind=='preference':kind,scope,valence='ordinary','none',0.
        if kind=='correction': lesson=text[:200]
        result={'kind':kind,'scope':scope,'subject':subject,'confidence':confidence,'valence':valence,
                'evidence':text[:400],'summary':text[:160],'lesson':lesson,'attribute':attribute,'value':value,
                'interpreter':'trained_semantic_head','memory_support':memory_support,'scope_confidence':scope_confidence,
                '_semantic_key':latent.tolist(),'_semantic_class':index}
        reading=self.own_event_reading(text,features)
        if reading is not None:
            result['_own_event'],how=reading
            if how:result['appraisal_features']=how
            # v35.1: news that carries two feelings at once (mixed_feelings.py).
            import mixed_feelings
            mixed=mixed_feelings.detect(text,result['_own_event'],
                                        lambda part:(self.own_event_reading(part,decoder.meaning_features(part)) or (None,))[0])
            if mixed:result['_mixed']=mixed
        return result

    def own_event_reading(self,text,features):
        """(appraisal of what the text means to Friday, which features it read) or None without trained heads."""
        if not (hasattr(self,'event_head') and bool(self.event_trained)):return None
        meaning=meaning_heads_for(self,text,features)
        if meaning is not None and self.extended:
            core_head,extended_head,both=meaning
            numbers=core_head(both).sigmoid();numbers[[1,5,8]]=2*numbers[[1,5,8]]-1
            extra=extended_head(both).sigmoid()
            numbers[0]=torch.maximum(numbers[0],.7*extra.max())
            return dict(zip(EVENT_FIELDS+EXTENDED_FIELDS,torch.cat((numbers,extra)).tolist())),'language_model+meaning'
        numbers=self.event_head(features).sigmoid()
        numbers[[1,5,8]]=2*numbers[[1,5,8]]-1
        if self.extended:
            extra=self.extended_event_head(features).sigmoid()
            # A strong own appraisal itself has personal relevance; this
            # estimate is distinct from accepting the user's report as fact.
            numbers[0]=torch.maximum(numbers[0],.7*extra.max())
            numbers=torch.cat((numbers,extra))
        fields=EVENT_FIELDS+EXTENDED_FIELDS if self.extended else EVENT_FIELDS
        return dict(zip(fields,numbers.tolist())),None
