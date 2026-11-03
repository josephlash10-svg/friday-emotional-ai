"""V14 emotional hybrid. Import is read-only; --self-test needs no project data.

Phases follow docs/V14 Emotional Hybrid Blueprint.docx. Legacy Vantage checkpoints
are not migrated. Outcome learning requires externally supplied measurements.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re
import hashlib
import copy
import time
from self_awareness import reflect
from developmental_emotion import DevelopmentalEmotion,OwnEvent
from experience_model import ExperienceModel
from experience_loop import prepare_experience,complete_experience,explain_experience,interpret_turn,start_recall
from semantic_interpreter import SemanticInterpreter
from typing import Callable
import torch
from torch import Tensor, nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
LEGACY_CHECKPOINTS = (ROOT/'vantage_brain.pth', ROOT/'state/legacy/vantage_brain.pth')
EMOTIONS = ('anger','sadness','fear','joy','shame','connection','stress','calm',
            'confusion','surprise','pain','disgust','contempt','guilt','pride',
            'interest','awe','envy','vulnerability')
ANCHORS = ('angry','sad','scared','happy','ashamed','love','overwhelmed','calm',
           'confused','surprised','hurt','disgust','contempt','guilt','proud',
           'curious','wonder','jealous','vulnerable')
ACTIONS = ('ANSWER','CLARIFY','COMFORT','VERIFY','SET_BOUNDARY')
NEEDS = ('competence','uncertainty_management','affiliation','safety','resources',
         'care_effectiveness','task_coherence')
SPECIAL = ('<pad>','<unk>','<bos>','<eos>')

@dataclass
class Config:
    d: int = 96
    heads: int = 4
    decoder_layers: int = 2
    max_tokens: int = 128
    alpha: float = .3
    floor: float = 1.
    bleed: float = .2
    intensity: float = 8.
    rho_max: float = .95
    interaction_max: float = .1
    fast_decay: float = .9
    fast_rate: float = .05
    fast_max: float = 2.
    scar_rate: float = .02
    scar_threshold: float = .65
    scar_max: float = 1.
    heal_rate: float = .01
    chaos_max: float = 0.
    noise_max: float = .25
    lr: float = .0005
    lr_max: float = .001
    surge: float = 0.
    homeo_weight: float = 1.
    cost_weight: float = .1
    discount: float = .95
    vitality_decay: float = .8
    pretrained_decoder: str | None = None
    allow_download: bool = False
    soft_tokens: int = 4
    context_tokens: int = 384
    contextual_appraisal: bool = False
    developmental_emotion: bool = False
    experience_model: bool = False
    semantic_interpreter: bool = False
    contextual_own_event: bool = False
    semantic_hidden: int = 96
    extended_own_appraisal: bool = False

    def __post_init__(self):
        if self.soft_tokens < 1 or self.context_tokens < 8:
            raise ValueError('Invalid language context settings')
        if self.d <= 0 or self.d % self.heads or self.d % 2 or self.max_tokens < 4:
            raise ValueError('d must be positive, even, divisible by heads; max_tokens >= 4')
        if not 0 <= self.alpha <= .5 or not 0 <= self.rho_max < 1:
            raise ValueError('Invalid gate or persistence bound')
        if not 0 <= self.fast_decay < 1 or not 0 <= self.heal_rate <= 1:
            raise ValueError('Invalid memory decay')
        if not 0 <= self.vitality_decay < 1 or not 0 <= self.discount <= 1:
            raise ValueError('Invalid vitality decay or discount')
        if self.lr <= 0 or self.lr_max < self.lr or self.surge < 0:
            raise ValueError('Invalid optimizer settings')
        if min(self.fast_rate,self.scar_rate,self.chaos_max,self.interaction_max) < 0:
            raise ValueError('Update strengths must be nonnegative')
        if min(self.fast_max,self.scar_max,self.noise_max) <= 0:
            raise ValueError('Norm bounds must be positive')

def clipnorm(x: Tensor, bound: float):
    return x * (bound / x.norm().clamp_min(1e-8)).clamp(max=1.)

class Vocabulary:
    def __init__(self, words):
        self.words = list(words)
        if tuple(self.words[:4]) != SPECIAL or len(set(self.words)) != len(self.words):
            raise ValueError('Vocabulary must start with unique V14 special tokens')
        self.ids = {w:i for i,w in enumerate(self.words)}

    @staticmethod
    def tokens(text):
        return re.findall(r"[a-z]+(?:'[a-z]+)?|[0-9]+|[^\w\s]", text.lower())

    def encode(self,text):
        return [self.ids.get(w,1) for w in self.tokens(text)] or [1]

    def decode(self,ids):
        return re.sub(r'\s+([.,!?;:])',r'\1',' '.join(self.words[i] for i in ids if i>=4))

def load_glove(path,limit,d):
    vectors,width,needed = {},None,set(ANCHORS)
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            parts=line.rstrip().split()
            if len(parts)<10: continue
            word=parts[0].lower()
            if word in SPECIAL or word in vectors: continue
            if len(vectors)>=limit and word not in needed: continue
            try: vec=torch.tensor([float(v) for v in parts[1:]])
            except ValueError: continue
            width=width or vec.numel()
            if vec.numel()!=width: continue
            vectors[word]=vec; needed.discard(word)
            if len(vectors)>=limit and not needed: break
    if needed: raise ValueError(f'Missing fixed anchors: {sorted(needed)}')
    vocab=Vocabulary(list(SPECIAL)+list(vectors))
    gen=torch.Generator().manual_seed(14)
    semantic=torch.cat([torch.zeros(4,width),torch.stack(list(vectors.values()))])
    if width!=d:
        semantic=semantic @ (torch.randn(width,d,generator=gen)/math.sqrt(d))
    semantic[1:4]=torch.randn(3,d,generator=gen)*.05
    return vocab,semantic

@dataclass
class State:
    emotion: Tensor
    gut: Tensor
    fast: Tensor
    vitality: Tensor
    def detached(self):
        return State(*(v.detach().clone() for v in (self.emotion,self.gut,self.fast,self.vitality)))

@dataclass
class Turn:
    ids: Tensor
    before: State
    needs: Tensor
    state: State
    proposal: Tensor
    mood: Tensor
    task: Tensor
    affect: Tensor
    policy: Tensor
    reflex_share: Tensor
    value: Tensor
    target: str
    deliberation: float
    text: str = ''
    history: tuple = ()
    development: dict | None = None
    experience: dict | None = None

class LocalDecoder(nn.Module):
    """Causal prototype trained from scratch, not a pretrained language model."""
    def __init__(self,size,cfg):
        super().__init__()
        self.embedding=nn.Embedding(size,cfg.d)
        nn.init.normal_(self.embedding.weight,std=.02)
        self.position=nn.Embedding(cfg.max_tokens+1,cfg.d)
        layer=nn.TransformerEncoderLayer(cfg.d,cfg.heads,4*cfg.d,dropout=0.,batch_first=True)
        self.transformer=nn.TransformerEncoder(layer,cfg.decoder_layers,enable_nested_tensor=False)
        self.output=nn.Linear(cfg.d,size,bias=False)
        self.output.weight=self.embedding.weight
    def forward(self,ids,condition):
        x=torch.cat([condition.view(1,1,-1),self.embedding(ids)],dim=1)
        x=x+self.position(torch.arange(x.size(1),device=x.device))[None]
        mask=torch.ones(x.size(1),x.size(1),device=x.device,dtype=torch.bool).triu(1)
        return self.output(self.transformer(x,mask=mask))[:,1:]

class PretrainedDecoder(nn.Module):
    def __init__(self,cfg):
        super().__init__()
        from transformers import AutoTokenizer,AutoModelForCausalLM
        opts={'local_files_only':not cfg.allow_download}
        self.tokenizer=AutoTokenizer.from_pretrained(cfg.pretrained_decoder,**opts)
        self.lm=AutoModelForCausalLM.from_pretrained(cfg.pretrained_decoder,dtype=torch.float32,**opts)
        if self.tokenizer.eos_token_id is None: raise ValueError('Decoder must define EOS')
        self.cfg=cfg
        self.lm.requires_grad_(False)
        self.lm.eval()
        self.width=self.lm.get_input_embeddings().embedding_dim
        self.bridge=nn.Linear(cfg.d,cfg.soft_tokens*self.width)
        # Start close to the language model's normal embedding scale.
        nn.init.normal_(self.bridge.weight,std=.001)
        nn.init.zeros_(self.bridge.bias)
        if cfg.contextual_appraisal: self.enable_contextual_appraisal()
    def enable_contextual_appraisal(self):
        if not hasattr(self,'context_projection'):
            self.context_projection=nn.Linear(self.width,self.cfg.d).to(self.bridge.weight.device)
        self.cfg.contextual_appraisal=True
    def contextual_features(self,text,history):
        # Only the available prompt is encoded; no action/response label enters this pass.
        prompt=self.prompt_ids(text,history,None,0)
        ids=torch.tensor([prompt],device=self.bridge.weight.device)
        with torch.no_grad():
            hidden=self.lm.base_model(input_ids=ids,use_cache=False,return_dict=True).last_hidden_state[0,-1]
            hidden=F.layer_norm(hidden,(self.width,))
        return torch.tanh(self.context_projection(hidden))
    @torch.no_grad()
    def meaning_features(self,text):
        prompt=self.prompt_ids(text,(),None,0)
        ids=torch.tensor([prompt],device=self.bridge.weight.device)
        hidden=self.lm.base_model(input_ids=ids,use_cache=False,return_dict=True).last_hidden_state[0,-1]
        return F.layer_norm(hidden,(self.width,))
    def train(self,mode=True):
        super().train(mode)
        self.lm.eval()  # Frozen weights must also keep dropout disabled.
        return self
    def prompt_ids(self,text,history,action,reserve):
        guidance={None:'Understand the user message in its conversation context.',
                  'ANSWER':'Answer clearly and helpfully.', 'CLARIFY':'Ask a useful clarifying question.',
                  'COMFORT':'Respond with empathy and practical support.',
                  'VERIFY':'Be careful about uncertainty and verify assumptions.',
                  'SET_BOUNDARY':'Set a clear, respectful boundary.'}[action]
        messages=[{'role':'system','content':'You are a helpful assistant. '+guidance}]
        messages.extend({'role':m['role'],'content':m['content']} for m in history)
        messages.append({'role':'user','content':text})
        if self.tokenizer.chat_template:
            rendered=self.tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
            prompt=self.tokenizer.encode(rendered,add_special_tokens=False)
        else:
            prompt=self.tokenizer.encode('\n'.join(m['role']+': '+m['content'] for m in messages)+'\nassistant:',add_special_tokens=False)
        limit=getattr(self.lm.config,'max_position_embeddings',getattr(self.lm.config,'n_positions',2048))
        budget=min(self.cfg.context_tokens,limit-self.cfg.soft_tokens-reserve)
        if budget<1: raise ValueError('Response exceeds language model context window')
        return prompt[-budget:] or [self.tokenizer.eos_token_id]
    def forward(self,ids,condition,text,history,action,use_bridge=True):
        # ids[:,0] is a training/generation sentinel, not a real prompt token.
        prompt=self.prompt_ids(text,history,action,self.cfg.max_tokens-1)
        prompt=torch.tensor([prompt],device=ids.device)
        prefix=self.bridge(condition).view(1,self.cfg.soft_tokens,self.width)
        if not use_bridge: prefix=torch.zeros_like(prefix)
        x=torch.cat([prefix,self.lm.get_input_embeddings()(prompt),
                     self.lm.get_input_embeddings()(ids[:,1:])],dim=1)
        start=self.cfg.soft_tokens+prompt.size(1)-1
        # Last prompt position predicts the first response; loss never scores prompt tokens.
        return self.lm(inputs_embeds=x,use_cache=False).logits[:,start:]
    def generate_tokens(self,condition,text,history,action,max_new,temperature,sample):
        prompt=self.prompt_ids(text,history,action,self.cfg.max_tokens-1)
        prompt=torch.tensor([prompt],device=condition.device)
        prefix=self.bridge(condition).view(1,self.cfg.soft_tokens,self.width)
        x=torch.cat([prefix,self.lm.get_input_embeddings()(prompt)],dim=1)
        output=self.lm(inputs_embeds=x,use_cache=True)
        tokens=[]
        for index in range(max_new):
            logits=output.logits[0,-1]
            token=torch.multinomial((logits/max(temperature,.01)).softmax(-1),1).item() if sample else logits.argmax().item()
            if token==self.tokenizer.eos_token_id: break
            tokens.append(token)
            if index+1<max_new:
                output=self.lm(input_ids=torch.tensor([[token]],device=condition.device),
                               past_key_values=output.past_key_values,use_cache=True)
        return tokens

class V14Agent(nn.Module):
    def __init__(self,vocab,semantic,cfg):
        super().__init__()
        self.vocab,self.cfg=vocab,cfg
        self.chat_history=[]
        k,m,d=len(EMOTIONS),len(NEEDS),cfg.d
        if semantic.shape!=(len(vocab.words),d): raise ValueError('Embedding shape mismatch')
        self.semantic=nn.Embedding.from_pretrained(semantic,freeze=True)
        self.register_buffer('anchors',F.normalize(semantic[[vocab.ids[w] for w in ANCHORS]],dim=-1))
        self.register_buffer('scars',torch.zeros_like(semantic))
        self.register_buffer('counts',torch.zeros(len(vocab.words)))
        self.register_buffer('scar_ready',torch.tensor(False))
        self.register_buffer('lower',torch.full((m,),.4))
        self.register_buffer('upper',torch.full((m,),.6))
        self.register_buffer('need_weights',torch.ones(m)/m)
        self.register_buffer('base_inertia',torch.tensor([.2,.3,.2,.7,.5,.8,.4,.6,.3,0.,.4,.5,.5,.4,.6,.4,.2,.5,.3]))
        self.gut_cell=nn.GRUCell(d+k+m,d)
        self.gut_readout=nn.Linear(d,k)
        self.threshold=nn.Parameter(torch.full((k,),2.))
        self.resonance=nn.Parameter(torch.zeros(k))
        self.gain=nn.Linear(k,k); self.inject=nn.Linear(k,k,bias=False)
        nn.init.zeros_(self.gain.weight); nn.init.constant_(self.gain.bias,4.)
        nn.init.zeros_(self.inject.weight)
        self.gate=nn.Linear(d,d,bias=False)
        self.q,self.key,self.value=(nn.Linear(d,d) for _ in range(3))
        self.attn_out=nn.Linear(d,d); self.attn_norm=nn.LayerNorm(d)
        self.ff=nn.Sequential(nn.Linear(d,4*d),nn.GELU(),nn.Linear(4*d,d))
        self.ff_norm=nn.LayerNorm(d)
        self.fast_key,self.fast_value=nn.Linear(d,d),nn.Linear(d,d)
        self.logic,self.mood_projection=nn.Linear(d,d),nn.Linear(d,d,bias=False)
        self.affect_norm=nn.LayerNorm(d)
        self.slow,self.reflex=nn.Linear(d,len(ACTIONS)),nn.Linear(d,len(ACTIONS))
        self.action_embedding=nn.Embedding(len(ACTIONS),d)
        self.critic=nn.Linear(d,1)
        self.predictor=nn.Linear(2*d+k+m+len(ACTIONS),m)
        self.scar_writer=nn.Linear(d+k+m+1,d)
        # Fixed shared comparison coordinates avoid an untrained scoring projection.
        self.decoder=PretrainedDecoder(cfg) if cfg.pretrained_decoder else LocalDecoder(len(vocab.words),cfg)
        if cfg.developmental_emotion: self.development=DevelopmentalEmotion(EMOTIONS,cfg.extended_own_appraisal)
        if cfg.experience_model: self.experience=ExperienceModel()
        if cfg.semantic_interpreter:
            if not cfg.pretrained_decoder: raise ValueError('Semantic interpreter requires the frozen language encoder')
            self.interpreter=SemanticInterpreter(self.decoder.width,cfg.semantic_hidden)
            if cfg.contextual_own_event:self.interpreter.enable_own_event(self.decoder.width,cfg.extended_own_appraisal)
    @property
    def device(self): return self.scars.device
    def initial_state(self):
        d=self.cfg.d
        return State(torch.zeros(len(EMOTIONS),device=self.device),torch.zeros(d,device=self.device),
                     torch.zeros(d,d,device=self.device),torch.tensor(0.,device=self.device))
    def deficits(self,levels):
        q=torch.as_tensor(levels,dtype=torch.float32,device=self.device)
        if q.shape!=self.lower.shape or not torch.isfinite(q).all() or (q<0).any() or (q>1).any():
            raise ValueError(f'Need levels require {len(NEEDS)} finite numbers in [0,1]')
        return (self.lower-q).clamp_min(0)+(q-self.upper).clamp_min(0)
    def position(self,length):
        d=self.cfg.d; pos=torch.arange(length,device=self.device)[:,None]
        scale=torch.exp(torch.arange(0,d,2,device=self.device)*(-math.log(10000)/d))
        pe=torch.zeros(length,d,device=self.device)
        pe[:,0::2],pe[:,1::2]=torch.sin(pos*scale),torch.cos(pos*scale)
        return pe
    def forward(self,ids,state,needs,target='user',deliberation=0.,explore=False,text=None,history=(),event=None,regulate=True,elapsed_seconds=0.,experience=None):
        validate_history(history)
        if ids.ndim!=1 or not 0<len(ids)<=self.cfg.max_tokens: raise ValueError('Invalid input length/shape')
        if not 0<=deliberation<=1: raise ValueError('Deliberation must be in [0,1]')
        cfg,d=self.cfg,self.cfg.d
        recovery_applied=cfg.developmental_emotion and elapsed_seconds>0
        original_elapsed=elapsed_seconds
        if recovery_applied:
            state=replace(state,emotion=self.development.recovered_emotion(state.emotion,elapsed_seconds))
            elapsed_seconds=0.
        text=self.vocab.decode(ids.tolist()) if text is None else text
        # Phase 1: target, position and bounded experience recall, applied once.
        clean=self.semantic(ids)
        context={'user':1.,'system':2.,'world':.5}[target]*(clean+self.position(len(ids)))+self.scars[ids]
        if cfg.pretrained_decoder and cfg.contextual_appraisal:
            context=context+self.decoder.contextual_features(text,history)
        task=clean.mean(0)
        # Phase 2: anchors, actual observed corpus counts, and recurrent appraisal.
        scores=F.normalize(clean,dim=-1) @ self.anchors.T
        scores=scores-cfg.floor*scores.mean(-1,keepdim=True)
        weights=1/torch.log(2+self.counts[ids]); weights=weights/(weights.sum()+1e-8)
        raw=(scores*weights[:,None]).sum(0)
        gut=self.gut_cell(torch.cat([context.mean(0),state.emotion,needs]),state.gut)
        final=raw+cfg.bleed*torch.tanh(self.gut_readout(gut))
        proposal=torch.sigmoid(cfg.intensity*(2*torch.sigmoid(self.resonance))*final-self.threshold)
        # Phase 3: complementary persistence and bounded nonlinear interference.
        rho=(self.base_inertia+.4*state.emotion.square()).clamp(0,cfg.rho_max)
        pre=rho*state.emotion+(1-rho)*proposal
        emotion=(pre*torch.sigmoid(self.gain(pre))+cfg.interaction_max*torch.tanh(self.inject(pre))).clamp(0,1)
        development=None
        if cfg.developmental_emotion:
            if not bool(self.development.trained): raise RuntimeError('Developmental appraisal must be trained before use')
            if event is None:
                # Only measured deficits can make an ordinary turn self-relevant.
                level=float(needs.mean().detach())
                event=OwnEvent(cue='need-state',relevance=min(1.,2.5*level),progress=-min(1.,2.5*level))
            if isinstance(event,dict): event=OwnEvent(**event)
            if not isinstance(event,OwnEvent): raise ValueError('event requires an OwnEvent or JSON object')
            proposal,emotion,deliberation,development=self.development.appraise(event,needs,state.emotion,deliberation,regulate,elapsed_seconds,
                experience.get('depth') if experience else None)
        # Phase 5: signed gate, Q/K modulation, unchanged values, fast memory.
        p=emotion.pow(3); mood=(p @ self.anchors)/(p.sum()+1e-8)
        modulated=context*(1+cfg.alpha*torch.tanh(self.gate(mood)))
        n,heads,width=len(ids),cfg.heads,d//cfg.heads
        q=self.q(modulated).view(n,heads,width).transpose(0,1)
        key=self.key(modulated).view(n,heads,width).transpose(0,1)
        value=self.value(context).view(n,heads,width).transpose(0,1)
        attention=((q @ key.transpose(-2,-1))/math.sqrt(width)).softmax(-1)
        h=(attention @ value).transpose(0,1).reshape(n,d)
        h=self.attn_norm(context+self.attn_out(h)); h=self.ff_norm(h+self.ff(h)).mean(0)
        fk,fv=F.normalize(self.fast_key(h),dim=0),F.normalize(self.fast_value(h),dim=0)
        fast=clipnorm(cfg.fast_decay*state.fast+cfg.fast_rate*torch.outer(fv,fk),cfg.fast_max)
        noise=torch.zeros_like(h)
        if explore and cfg.chaos_max:
            noise=clipnorm(cfg.chaos_max*emotion[EMOTIONS.index('confusion')]*torch.randn_like(h),cfg.noise_max)
        affect=self.affect_norm(self.logic(h)+fast @ h+self.mood_projection(mood)+noise)
        # Phase 4: resolve both action paths before smooth arbitration.
        mu=(emotion[[EMOTIONS.index(e) for e in ('stress','fear','pain')]]*emotion.new_tensor([1.2,.8,1.5])/3.5).sum()
        share=torch.sigmoid(8*(mu-.75)-2*deliberation)
        policy=share*self.reflex(gut).softmax(-1)+(1-share)*self.slow(affect).softmax(-1)
        if development:
            development['elapsed_seconds']=original_elapsed
            development['recovery_applied_before_perception']=recovery_applied
        return Turn(ids,state,needs,State(emotion,gut,fast,state.vitality),proposal,mood,task,
                    affect,policy,share,self.critic(affect).squeeze(),target,deliberation,
                    text,tuple(dict(m) for m in history),development,experience)
    def response_ids(self,text):
        if self.cfg.pretrained_decoder:
            tok=self.decoder.tokenizer
            return [tok.eos_token_id]+tok.encode(text,add_special_tokens=False)[:self.cfg.max_tokens-2]+[tok.eos_token_id]
        return [2]+self.vocab.encode(text)[:self.cfg.max_tokens-2]+[3]
    def language_logits(self,turn,action,ids,use_bridge=True):
        condition=turn.affect+self.action_embedding(torch.as_tensor(action,device=self.device))
        if self.cfg.pretrained_decoder:
            return self.decoder(ids,condition,turn.text,turn.history,ACTIONS[int(action)],use_bridge)
        return self.decoder(ids,condition)
    def predicted_needs(self,turn,action,response=''):
        wording=self.semantic(torch.tensor(self.vocab.encode(response),device=self.device)).mean(0)
        onehot=F.one_hot(torch.as_tensor(action,device=self.device),len(ACTIONS)).float()
        return torch.sigmoid(self.predictor(torch.cat([turn.affect,wording,turn.state.emotion,turn.needs,onehot])))
    @torch.no_grad()
    def generate(self,turn,action,max_new=64,temperature=.8,sample=False):
        if self.cfg.pretrained_decoder:
            condition=turn.affect+self.action_embedding(torch.as_tensor(action,device=self.device))
            tokens=self.decoder.generate_tokens(condition,turn.text,turn.history,ACTIONS[int(action)],
                       min(max_new,self.cfg.max_tokens-1),temperature,sample)
            return self.decoder.tokenizer.decode(tokens,skip_special_tokens=True).strip()
        eos=self.decoder.tokenizer.eos_token_id if self.cfg.pretrained_decoder else 3
        ids=[eos if self.cfg.pretrained_decoder else 2]
        for _ in range(min(max_new,self.cfg.max_tokens-1)):
            logits=self.language_logits(turn,action,torch.tensor([ids],device=self.device))[0,-1]
            if not self.cfg.pretrained_decoder:
                logits=logits.clone(); logits[:3]=-torch.inf
            token=torch.multinomial((logits/max(temperature,.01)).softmax(-1),1).item() if sample else logits.argmax().item()
            if token==eos: break
            ids.append(token)
        return (self.decoder.tokenizer.decode(ids[1:],skip_special_tokens=True).strip()
                if self.cfg.pretrained_decoder else self.vocab.decode(ids[1:]))
    @torch.no_grad()
    def candidates(self,turn,action,count=2,validator:Callable|None=None,task_scorer:Callable|None=None):
        # Phase 6: fixed common coordinates, 60/40 mixing, externally checked candidates.
        target=.6*turn.mood+.4*turn.task
        target=F.normalize(turn.task if target.norm()<1e-8 else target,dim=0)
        best,score_best='',-math.inf
        for i in range(count):
            text=self.generate(turn,action,sample=i>0)
            if not text or (validator and not validator(text)): continue
            vec=self.semantic(torch.tensor(self.vocab.encode(text),device=self.device)).mean(0)
            align=F.cosine_similarity(vec,target,dim=0).item()
            seq=torch.tensor([self.response_ids(text)],device=self.device)
            loss=F.cross_entropy(self.language_logits(turn,action,seq[:,:-1])[0],seq[0,1:]).item()
            score=(float(task_scorer(text)) if task_scorer else 0.)+.1*align+.2*math.exp(-loss)
            if score>score_best: best,score_best=text,score
        return best or '[No candidate passed the configured checks.]'
    def regularization(self):
        return self.gate.weight.square().mean()+self.gain.weight.square().mean()+self.inject.weight.square().mean()
    @torch.no_grad()
    def record_counts(self,examples):
        counts=Counter(w for e in examples for key in ('input','response') for w in self.vocab.tokens(e[key]))
        self.counts.zero_()
        for word,count in counts.items():
            if word in self.vocab.ids: self.counts[self.vocab.ids[word]]=count
    def scar_direction(self,turn,delta,reward):
        return F.normalize(self.scar_writer(torch.cat([turn.affect,turn.state.emotion,delta,
                           turn.affect.new_tensor([reward])])),dim=0)
    @torch.no_grad()
    def commit_outcome(self,turn,next_needs,safe=False,reward=0.,control=None):
        # Phase 7: signed vitality; Phase 1 memory writes for the following turn.
        state=turn.state.detached()
        scale=torch.maximum(self.lower,1-self.upper).clamp_min(1e-8)
        estimate=(1-2*(self.need_weights*(next_needs/scale).clamp(0,1)).sum()/(self.need_weights.sum()+1e-8)).clamp(-1,1)
        state.vitality=self.cfg.vitality_decay*state.vitality+(1-self.cfg.vitality_decay)*estimate
        if self.cfg.developmental_emotion and turn.development is not None:
            self.development.observe(turn.development,reward,safe,control)
            state.emotion=self.development.outcome_emotion(turn.development,state.emotion,next_needs,reward,safe,control)
        eligible=torch.unique(turn.ids[turn.ids>=4])
        if bool(self.scar_ready) and len(eligible):
            intensity=.5*(state.emotion[EMOTIONS.index('pain')]+state.emotion[EMOTIONS.index('fear')])
            amount=self.cfg.scar_rate*(intensity-self.cfg.scar_threshold).clamp_min(0)
            direction=self.scar_direction(turn,next_needs-turn.needs,reward)
            rows=self.scars[eligible]+amount*direction
            rows=rows*(self.cfg.scar_max/rows.norm(dim=-1,keepdim=True).clamp_min(1e-8)).clamp(max=1.)
            if safe and state.vitality>.6: rows=rows*(1-self.cfg.heal_rate)
            self.scars[eligible]=rows
        return state

def supervised_loss(agent,example,state,history=()):
    needs=agent.deficits(example.get('levels',[.5]*len(NEEDS)))
    ids=torch.tensor(agent.vocab.encode(example['input'])[-agent.cfg.max_tokens:],device=agent.device)
    turn=agent(ids,state,needs,example.get('target','user'),example.get('deliberation',0.),
               text=example['input'],history=example.get('history',history))
    action=ACTIONS.index(example['action'])
    seq=torch.tensor([agent.response_ids(example['response'])],device=agent.device)
    loss=F.cross_entropy(agent.language_logits(turn,action,seq[:,:-1])[0],seq[0,1:])
    loss=loss-.3*turn.policy[action].clamp_min(1e-8).log()+1e-4*agent.regularization()
    if 'emotion' in example:
        names=list(example['emotion'])
        if not names or any(e not in EMOTIONS for e in names): raise ValueError('Unknown or empty emotion labels')
        labels=torch.tensor([example['emotion'][e] for e in names],device=agent.device)
        if not torch.isfinite(labels).all() or (labels<0).any() or (labels>1).any(): raise ValueError('Invalid emotion labels')
        loss=loss+.2*F.mse_loss(turn.proposal[[EMOTIONS.index(e) for e in names]],labels)
    if 'next_levels' in example:
        if 'levels' not in example:
            raise ValueError('Consequence labels require measured initial levels too')
        future=agent.deficits(example['next_levels'])
        loss=loss+.2*F.mse_loss(agent.predicted_needs(turn,action,example['response']),future)
        if 'scar_direction' in example:
            label=torch.tensor(example['scar_direction'],device=agent.device)
            if label.shape!=turn.affect.shape or not torch.isfinite(label).all() or label.norm()<1e-8:
                raise ValueError('Scar direction requires a finite nonzero d-vector')
            direction=agent.scar_direction(turn,future-needs,float(example.get('task_reward',0)))
            loss=loss+.2*F.mse_loss(direction,F.normalize(label,dim=0))
    return loss,turn

def train_examples(agent,examples,epochs,tbptt=1):
    agent.record_counts(examples)
    optimizer=torch.optim.AdamW((p for p in agent.parameters() if p.requires_grad),lr=agent.cfg.lr)
    agent.train()
    for epoch in range(epochs):
        state,episode,pending,losses,history=agent.initial_state(),None,[],[],[]
        def flush():
            nonlocal pending,state
            if not pending: return
            optimizer.zero_grad(); torch.stack(pending).mean().backward()
            nn.utils.clip_grad_norm_(agent.parameters(),1.)
            optimizer.step(); state=state.detached(); pending=[]
        for index,example in enumerate(examples):
            key=example.get('episode',f'independent-{index}')
            if key!=episode: flush(); state=agent.initial_state(); episode=key; history=[]
            loss,turn=supervised_loss(agent,example,state,history)
            history.extend([{'role':'user','content':example['input']},{'role':'assistant','content':example['response']}])
            state=turn.state; pending.append(loss); losses.append(loss.detach().item())
            # Surge is bounded, disabled by default, and uses a verified action label.
            if agent.cfg.surge:
                prob=turn.policy[ACTIONS.index(example['action'])].detach().item()
                rate=min(agent.cfg.lr_max,agent.cfg.lr+agent.cfg.surge*(1-prob)**2)
                for group in optimizer.param_groups: group['lr']=rate
            if len(pending)>=tbptt: flush()
        flush(); print(f'Epoch {epoch+1}: loss {sum(losses)/len(losses):.4f}')
    if any('scar_direction' in e and 'next_levels' in e for e in examples): agent.scar_ready.fill_(True)
    agent.eval()

def load_examples(path):
    """Read literal TRAINING_DATA from Python or JSONL; never execute dataset code."""
    text=path.read_text(encoding='utf-8-sig')
    if path.suffix.lower()=='.py':
        tree=ast.parse(text,filename=str(path))
        definitions=[node for node in tree.body if isinstance(node,ast.Assign)
                     and any(isinstance(t,ast.Name) and t.id=='TRAINING_DATA' for t in node.targets)]
        if len(definitions)!=1: raise ValueError('Dataset must define one literal TRAINING_DATA list')
        examples=ast.literal_eval(definitions[0].value)
    else:
        examples=[json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(examples,list) or not examples: raise ValueError('Training data must be a nonempty list')
    for index,e in enumerate(examples):
        if not isinstance(e,dict) or any(not isinstance(e.get(key),str) or not e[key].strip() for key in ('input','response','action')):
            raise ValueError(f'Record {index}: input, response and action are required')
        if e['action'] not in ACTIONS: raise ValueError(f'Record {index}: unknown action')
        validate_history(e.get('history',[]))
    return examples

def validate_history(history):
    if not isinstance(history,(list,tuple)) or any(not isinstance(m,dict) or m.get('role') not in ('user','assistant')
        or not isinstance(m.get('content'),str) for m in history):
        raise ValueError('History requires user/assistant messages with string content')

@torch.no_grad()
def evaluate_examples(agent,examples,use_bridge=True):
    """Held-out supervised diagnostics; no updates to weights, counts or memory."""
    agent.eval(); correct,total_loss,tokens=0,0.,0
    appraisal_error,appraisal_labels,contrasts=0.,0,{}
    state,episode,history=agent.initial_state(),None,[]
    for index,e in enumerate(examples):
        key=e.get('episode',f'independent-{index}')
        if key!=episode: state=agent.initial_state(); episode=key; history=[]
        needs=agent.deficits(e.get('levels',[.5]*len(NEEDS)))
        ids=torch.tensor(agent.vocab.encode(e['input'])[-agent.cfg.max_tokens:],device=agent.device)
        turn=agent(ids,state,needs,e.get('target','user'),e.get('deliberation',0.),text=e['input'],history=e.get('history',history))
        action=ACTIONS.index(e['action']); correct+=int(turn.policy.argmax().item()==action)
        for name,label in e.get('emotion',{}).items():
            if name not in EMOTIONS or not math.isfinite(float(label)) or not 0<=label<=1:
                raise ValueError('Invalid held-out appraisal label')
            appraisal_error+=(turn.proposal[EMOTIONS.index(name)].item()-label)**2
            appraisal_labels+=1
        if 'contrast_group' in e:
            channel=e['contrast_channel']; rank=e['contrast_rank']
            if channel not in EMOTIONS or rank not in ('high','low'): raise ValueError('Invalid contrast metadata')
            key=(e['contrast_group'],channel)
            bucket=contrasts.setdefault(key,{})
            if rank in bucket: raise ValueError('Duplicate contrast rank')
            bucket[rank]=turn.proposal[EMOTIONS.index(channel)].item()
        seq=torch.tensor([agent.response_ids(e['response'])],device=agent.device)
        logits=agent.language_logits(turn,action,seq[:,:-1],use_bridge=use_bridge)[0]
        total_loss+=F.cross_entropy(logits,seq[0,1:],reduction='sum').item()
        tokens+=len(seq[0])-1; state=turn.state.detached()
        history.extend([{'role':'user','content':e['input']},{'role':'assistant','content':e['response']}])
    result={'examples':len(examples),'action_accuracy':correct/len(examples),
            'response_token_nll':total_loss/tokens,'response_perplexity':math.exp(min(50,total_loss/tokens))}
    if appraisal_labels: result.update(appraisal_label_mse=appraisal_error/appraisal_labels,appraisal_labels=appraisal_labels)
    if contrasts:
        if any(set(v)!= {'high','low'} for v in contrasts.values()): raise ValueError('Contrasts require both ranks')
        margins=[v['high']-v['low'] for v in contrasts.values()]
        result.update(contrast_pairs=len(margins),contrast_order_accuracy=sum(m>1e-6 for m in margins)/len(margins),
                      contrast_mean_margin=sum(margins)/len(margins))
    return result

def observed_outcome(agent,turn,observation):
    next_needs=agent.deficits(observation['levels'])
    if not isinstance(observation.get('safe',False),bool) or not isinstance(observation.get('terminal',True),bool):
        raise ValueError('safe and terminal must be JSON booleans')
    task_reward,cost=float(observation['task_reward']),float(observation.get('cost',0))
    if not math.isfinite(task_reward) or not math.isfinite(cost) or cost<0: raise ValueError('Invalid reward/cost')
    reward=(task_reward+agent.cfg.homeo_weight*(agent.need_weights*(turn.needs.square()-next_needs.square())).sum().item()
            -agent.cfg.cost_weight*cost)
    return next_needs,reward

def learn_outcome(agent,turn,action,response,observation,joint_language=False):
    """On-policy intent update; callers must sample action from turn.policy.

    Joint token learning requires a raw sample, not a ranked/greedy candidate.
    The original chat interface uses intent-only learning and a terminal one-step return.
    """
    next_needs,reward=observed_outcome(agent,turn,observation)
    current=agent(turn.ids,turn.before.detached(),turn.needs,turn.target,turn.deliberation,text=turn.text,history=turn.history,
                  event=turn.development['event'] if turn.development else None,
                  elapsed_seconds=turn.development['elapsed_seconds'] if turn.development and not turn.development.get('recovery_applied_before_perception') else 0.,experience=turn.experience)
    with torch.no_grad():
        bootstrap=0.
        if not observation.get('terminal',True):
            if not observation.get('next_input'):
                raise ValueError('Nonterminal learning requires the actual next_input')
            future_ids=torch.tensor(agent.vocab.encode(observation['next_input'])[-agent.cfg.max_tokens:],device=agent.device)
            future_history=list(turn.history)+[{'role':'user','content':turn.text},{'role':'assistant','content':response}]
            future=agent(future_ids,current.state.detached(),next_needs,turn.target,turn.deliberation,
                         text=observation['next_input'],history=future_history)
            bootstrap=agent.cfg.discount*future.value
        target=current.value.new_tensor(reward)+bootstrap
        advantage=target-current.value
    log_prob=current.policy[action].clamp_min(1e-8).log()
    if joint_language:
        seq=torch.tensor([agent.response_ids(response)],device=agent.device)
        logits=agent.language_logits(current,action,seq[:,:-1])[0]
        log_prob=log_prob+logits.log_softmax(-1).gather(1,seq[0,1:,None]).sum()
    loss=-log_prob*advantage+.5*(current.value-target).square()
    loss=loss+.2*F.mse_loss(agent.predicted_needs(current,action,response),next_needs)+1e-4*agent.regularization()
    if not hasattr(agent,'outcome_optimizer'):
        agent.outcome_optimizer=torch.optim.AdamW((p for p in agent.parameters() if p.requires_grad),lr=agent.cfg.lr)
    optimizer=agent.outcome_optimizer
    optimizer.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(agent.parameters(),1.); optimizer.step()
    state=agent.commit_outcome(turn,next_needs,bool(observation.get('safe',False)),reward,observation.get('control'))
    return state,next_needs,{'reward':reward,'loss':loss.detach().item()}

def save_checkpoint(agent,state,path):
    if path.resolve() in {p.resolve() for p in LEGACY_CHECKPOINTS}: raise ValueError('Legacy checkpoint is protected')
    path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_suffix(path.suffix+'.tmp')
    model=agent.state_dict()
    if agent.cfg.pretrained_decoder:
        model={key:value for key,value in model.items() if not key.startswith('decoder.lm.')}
    torch.save({'version':14,'config':asdict(agent.cfg),'words':agent.vocab.words,
                'language_contract':3 if agent.cfg.contextual_appraisal else 2,'history':agent.chat_history,
                'state_updated_at':getattr(agent,'state_updated_at',None),
                'experience':agent.experience.snapshot() if agent.cfg.experience_model else None,
                'frozen_base':frozen_base_fingerprint(agent) if agent.cfg.pretrained_decoder else None,
                'model':model,'state':asdict(state.detached()),
                'outcome_optimizer':agent.outcome_optimizer.state_dict() if hasattr(agent,'outcome_optimizer') else None},temporary)
    temporary.replace(path)

def frozen_base_fingerprint(agent):
    # Hash local source weights once per process; adapters must use the same frozen base.
    if hasattr(agent,'_base_fingerprint'): return agent._base_fingerprint
    directory=Path(agent.cfg.pretrained_decoder)
    if not directory.is_dir():
        from transformers.utils.hub import cached_file
        directory=Path(cached_file(agent.cfg.pretrained_decoder,'config.json',local_files_only=True)).parent
    files=[directory/'config.json']+sorted(directory.glob('*.safetensors'))
    if len(files)==1: files+=sorted(directory.glob('pytorch_model*.bin'))
    if len(files)<2: raise ValueError('Frozen decoder source weights are unavailable')
    result={}
    for file in files:
        digest=hashlib.sha256()
        with file.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''): digest.update(block)
        result[file.name]=digest.hexdigest()
    agent._base_fingerprint=result
    return result

def load_checkpoint(path):
    checkpoint=torch.load(path,map_location='cpu',weights_only=True,mmap=True)
    if checkpoint.get('version')!=14: raise ValueError('Only V14 checkpoints are compatible')
    cfg=Config(**checkpoint['config']); vocab=Vocabulary(checkpoint['words'])
    if cfg.pretrained_decoder and checkpoint.get('language_contract') not in (2,3):
        raise ValueError('Old pretrained bridge checkpoint: use a new V14 language checkpoint')
    agent=V14Agent(vocab,checkpoint['model']['semantic.weight'].clone(),cfg)
    if checkpoint.get('frozen_base') is not None:
        if frozen_base_fingerprint(agent)!=checkpoint['frozen_base']:
            raise ValueError('Frozen language source weights changed; restore the original model files')
        missing,unexpected=agent.load_state_dict(checkpoint['model'],strict=False)
        expected={key for key in agent.state_dict() if key.startswith('decoder.lm.')}
        if set(missing)!=expected or unexpected: raise ValueError('Incomplete V14 adapter checkpoint')
    else: agent.load_state_dict(checkpoint['model'])
    agent.chat_history=checkpoint.get('history',[]); validate_history(agent.chat_history)
    agent.state_updated_at=checkpoint.get('state_updated_at')
    if cfg.experience_model: agent.experience=ExperienceModel(checkpoint.get('experience'))
    if checkpoint.get('outcome_optimizer') is not None:
        agent.outcome_optimizer=torch.optim.AdamW((p for p in agent.parameters() if p.requires_grad),lr=cfg.lr)
        agent.outcome_optimizer.load_state_dict(copy.deepcopy(checkpoint['outcome_optimizer']))
    return agent,State(**checkpoint['state']).detached()

def self_test():
    import tempfile
    torch.manual_seed(14)
    vocab=Vocabulary(list(SPECIAL)+list(dict.fromkeys(ANCHORS+('hello','answer','help','world'))))
    agent=V14Agent(vocab,torch.randn(len(vocab.words),24),Config(d=24,heads=4,max_tokens=32))
    agent.eval(); initial=agent.initial_state(); needs=agent.deficits([.5]*7)
    ids=torch.tensor(vocab.encode('hello help')); turn=agent(ids,initial,needs)
    assert len(turn.state.emotion)==19 and turn.state.vitality.ndim==0
    assert torch.all((turn.state.emotion>=0)&(turn.state.emotion<=1))
    assert torch.allclose(turn.policy.sum(),torch.tensor(1.))
    assert 0<turn.state.fast.norm()<=agent.cfg.fast_max
    assert torch.equal(1+agent.cfg.alpha*torch.tanh(agent.gate(torch.zeros(24))),torch.ones(24))
    a=torch.tensor([[2,vocab.ids['hello'],vocab.ids['world']]])
    b=a.clone(); b[0,-1]=vocab.ids['help']
    assert torch.allclose(agent.language_logits(turn,0,a)[:,:2],agent.language_logits(turn,0,b)[:,:2],atol=1e-6),'Future-token leakage'
    example={'input':'hello help','response':'answer world','action':'ANSWER','levels':[.5]*7,'next_levels':[.55]*7}
    loss,_=supervised_loss(agent,example,initial); loss.backward()
    for name in ('gut_cell.weight_ih','gut_readout.weight','gate.weight','reflex.weight','slow.weight','gain.weight','inject.weight','fast_key.weight'):
        grad=dict(agent.named_parameters())[name].grad
        assert grad is not None and grad.norm()>0,f'Disconnected gradient: {name}'
    agent.zero_grad()
    low=agent.deficits([0.]*7)
    assert (agent.need_weights*(low.square()-needs.square())).sum()>0
    for _ in range(100):
        turn=agent(ids,initial,needs); initial=turn.state.detached()
        assert initial.fast.norm()<=agent.cfg.fast_max+1e-5
        assert torch.all((initial.emotion>=0)&(initial.emotion<=1))
    agent.scar_ready.fill_(True)
    turn.state.emotion[EMOTIONS.index('pain')]=1.; turn.state.emotion[EMOTIONS.index('fear')]=1.
    agent.commit_outcome(turn,needs); assert agent.scars[ids].norm()>0
    before=agent.scars.clone(); turn.state.vitality=torch.tensor(1.); turn.state.emotion.zero_()
    agent.commit_outcome(turn,needs,safe=True); assert agent.scars[ids].norm()<before[ids].norm()
    state,_,stats=learn_outcome(agent,agent(ids,agent.initial_state(),needs),0,'answer',{'levels':[.5]*7,'task_reward':1.,'terminal':True})
    assert math.isfinite(stats['loss'])
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'test.pth'; save_checkpoint(agent,state,path)
        restored,rs=load_checkpoint(path)
        assert torch.equal(restored.scars,agent.scars) and torch.equal(rs.fast,state.fast)
    print('V14 self-test passed: bounds, causal decoder, gradients, outcome learning, memory, checkpoint round-trip')

def last_activity(agent):
    """When Friday last talked with them: the newest stored exchange, or the start of this chat if that is newer."""
    import time_sense
    episodes=agent.experience.data['episodes'] if agent.cfg.experience_model else []
    times=[getattr(agent,'conversation_started_at',None) or 0.]
    if episodes:
        try:times.append(time_sense.parse(episodes[-1]['time_utc']))
        except (KeyError,ValueError,TypeError):pass
    return max(times) or None

def start_new_conversation_if_due(agent,now=None):
    """After 3 hours of silence the saved chat history belongs to an earlier conversation. Kept as "this conversation" it
    made Friday open with "hope the food was good" two days after a food run, and answer a two-day-old question
    (10-day simulation, 2026-10-29). Earlier conversations stay in the stored record and its summaries, with dates."""
    import time_sense
    now=time.time() if now is None else now
    last=last_activity(agent)
    if last is not None and now-last>time_sense.NEW_CONVERSATION_GAP:
        agent.chat_history=[];agent.conversation_started_at=now
        return True
    if getattr(agent,'conversation_started_at',None) is None:agent.conversation_started_at=now
    return False

def opening_facts(agent,state):
    """What Friday actually knows and feels at the moment the chat opens (for speaking first)."""
    import time_sense
    facts={}
    now=time.time()
    if agent.cfg.experience_model:
        experience=agent.experience;data=experience.data
        name=data['user'].get('name',{}).get('value')
        if name:facts['their_name']=name
        if data['relationship'].get('source')=='user_description':facts['how_they_describe_you_two']=data['relationship']['description'][:120]
        episodes=data['episodes']
        facts['earlier_exchanges_on_record']=len(episodes)
        facts['right_now']=time_sense.now_words(now)
        if episodes:
            last=episodes[-1]
            try:
                ended=time_sense.parse(last['time_utc'])
                facts['time_since_you_last_talked']=time_sense.gap_words(now-ended)
                facts['last_conversation_ended']=time_sense.when_words(ended,now)
                fresh=now-ended<=time_sense.NEW_CONVERSATION_GAP
            except (KeyError,ValueError,TypeError):fresh=False
            if fresh:facts['the_last_thing_they_said_to_you']=last['input'][:160]
            else:
                earlier,_=experience.conversation_split(now)
                if earlier:
                    top=sorted(earlier[-1]['highlights'],key=lambda h:h['score'],reverse=True)[:3]
                    facts['last_time_they_told_you_about']=[h['text'] for h in sorted(top,key=lambda h:h['time_utc'])]
            events=experience.events_near(now,back=3,ahead=3)
            if events:facts['their_events_around_now']=events
        else:facts['first_time_meeting']=True
    current=state.emotion
    if agent.cfg.developmental_emotion and getattr(agent,'state_updated_at',None):
        current=agent.development.recovered_emotion(state.emotion,max(0.,time.time()-agent.state_updated_at))
    top=sorted(zip(EMOTIONS,current.tolist()),key=lambda p:p[1],reverse=True)[:2]
    facts['your_mood_right_now']=[('faint ' if v<.1 else 'mild ' if v<.3 else 'moderate ' if v<.6 else 'strong ')+n for n,v in top]
    return facts

def main(ui=None):
    import sys
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--train',type=Path,help='Python TRAINING_DATA list or JSONL records')
    parser.add_argument('--evaluate',type=Path,help='Held-out dataset; prints metrics without training')
    parser.add_argument('--epochs',type=int,default=5)
    parser.add_argument('--tbptt',type=int,default=1)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--glove',type=Path,default=ROOT/'data/embeddings/glove.42B.300d.txt')
    parser.add_argument('--vocab-limit',type=int,default=10000)
    parser.add_argument('--pretrained-decoder',help='Local causal LM directory or model name')
    parser.add_argument('--allow-download',action='store_true')
    parser.add_argument('--contextual-appraisal',action='store_true',help='Train contextual meaning features into V14 appraisal; upgrades the loaded language checkpoint')
    parser.add_argument('--compare-bridge',action='store_true',help='Evaluate with learned soft conditioning and with zero soft vectors')
    parser.add_argument('--cpu-chat',action='store_true',help='Use the native ARM CPU language runtime for replies')
    parser.add_argument('--threads',type=int,default=4,help='CPU threads for the V14 core')
    parser.add_argument('--native-threads',type=int,help='Native language writing threads (default: chosen from the core count)')
    parser.add_argument('--native-model',type=Path,help='Optional local GGUF override; default is state/native-language.json')
    parser.add_argument('--native-context',type=int,help='Optional native context window override')
    parser.add_argument('--trace',action='store_true',help='Show controller action/state after each reply')
    parser.add_argument('--speak-first',action='store_true',help='Friday opens the conversation instead of waiting for you')
    args=parser.parse_args()
    if args.threads<1 or (args.native_threads is not None and args.native_threads<1): parser.error('Thread counts must be positive')
    if args.cpu_chat and (args.train or args.evaluate): parser.error('CPU chat is an inference mode; train/evaluate V14 separately')
    torch.set_num_threads(args.threads)
    if args.train and args.evaluate: parser.error('Train and evaluate in separate runs')
    if args.self_test: self_test(); return
    args.checkpoint=args.checkpoint or ROOT/('state/checkpoints/v14-language.pth' if args.pretrained_decoder or args.cpu_chat else 'state/checkpoints/v14.pth')
    if args.epochs<1 or args.tbptt<1 or args.vocab_limit<4: parser.error('Invalid training/vocabulary settings')
    if args.checkpoint.resolve() in {p.resolve() for p in LEGACY_CHECKPOINTS}: parser.error('Use a separate V14 checkpoint')
    torch.manual_seed(14)
    if args.cpu_chat:
        if not args.checkpoint.exists(): parser.error('The trained V14 checkpoint is missing; restore or train it before CPU chat')
        import os
        os.environ['HF_HUB_DISABLE_PROGRESS_BARS']='1'
        if not ui:print('Loading the V14 emotional engine...',flush=True)
    if args.checkpoint.exists():
        agent,state=load_checkpoint(args.checkpoint)
        if args.pretrained_decoder and agent.cfg.pretrained_decoder!=args.pretrained_decoder:
            parser.error('Checkpoint uses a different decoder; choose a separate checkpoint')
    else:
        cfg=Config(pretrained_decoder=args.pretrained_decoder,allow_download=args.allow_download,
                   contextual_appraisal=args.contextual_appraisal)
        vocab,semantic=load_glove(args.glove,args.vocab_limit,cfg.d)
        agent=V14Agent(vocab,semantic,cfg); state=agent.initial_state()
    if args.contextual_appraisal:
        if not agent.cfg.pretrained_decoder: parser.error('Contextual appraisal requires a pretrained backbone')
        if not agent.cfg.contextual_appraisal:
            if not args.train: parser.error('Train the contextual appraisal adapter before using it')
            agent.decoder.enable_contextual_appraisal()
            if hasattr(agent,'outcome_optimizer'): del agent.outcome_optimizer
    if args.train:
        examples=load_examples(args.train)
        train_examples(agent,examples,args.epochs,args.tbptt)
        save_checkpoint(agent,agent.initial_state(),args.checkpoint); return
    if args.evaluate:
        examples=load_examples(args.evaluate)
        results=evaluate_examples(agent,examples)
        if args.compare_bridge:
            if not agent.cfg.pretrained_decoder: parser.error('Bridge comparison requires a pretrained decoder')
            results={'bridge_enabled':results,'zero_soft_vectors':evaluate_examples(agent,examples,use_bridge=False)}
        print(json.dumps(results,indent=2)); return
    agent.eval()
    native=None
    if args.cpu_chat:
        from cpu_runtime import NativeLanguage
        brain=None
        if ui:
            from launcher_ui import LoadingBar,server_log_probe
            ui['soul'].finish('emotions and memories online')
            brain=LoadingBar('Brain','brain',60,probe=server_log_probe(ROOT/'state/logs/native-language.log')).start()
            brain.reach(.03,'starting the language model')
        else:print('Starting the native CPU language model...',flush=True)
        try: native=NativeLanguage(model=args.native_model,context=args.native_context,threads=args.native_threads,emotion_names=EMOTIONS)
        except (RuntimeError,ValueError) as error:
            if brain:brain.fail('failed: '+str(error)[:60])
            parser.error(str(error))
        if brain:brain.finish('language online')
        else:print('Native CPU language is ready; V14 emotional state and intent remain active.')
    if ui:
        print()
        print('  Type to talk.  :quit saves and exits.  :help lists engine commands.')
        print()
    else:
        print('V14 commands: :levels JSON-list, :event JSON-object, :observe JSON-object, :state, :self, :reflect, :growth, :trace on/off, :reset, :save, :quit')
        if not agent.cfg.pretrained_decoder: print('Local decoder is a prototype; train response examples before expecting fluency.')
        print('External need levels are unmeasured until :levels. Verbal feedback learns automatically; :observe supplies measured outcomes.' if agent.cfg.experience_model else 'Need levels are unmeasured until :levels. Outcome learning requires :observe.')
    needs=agent.deficits([.5]*len(NEEDS)); measured=False; pending=None; last_turn=None; own_event=None
    trace=args.trace
    if agent.cfg.experience_model:
        start_new_conversation_if_due(agent)
        if native:agent.experience.enable_meaning()  # recall by meaning (M1); loads in the background, falls back to words
    if args.speak_first and native:
        # Friday opens the conversation from its actual memory and current mood.
        try:
            print('Friday > ',end='',flush=True)
            import conversation_checks as cc
            theirs=[e['input'] for e in agent.experience.data['episodes']] if agent.cfg.experience_model else []
            # "Since your wedding is in three days": it was their sister's (v33 rerun). The opening is printed whole, so fix it first.
            greeting=native.opening(opening_facts(agent,state),on_token=lambda piece:print(cc.swap_event_owner(cc.swap_possessive(piece,theirs),theirs),end='',flush=True))
            greeting=cc.swap_event_owner(cc.swap_possessive(greeting,theirs),theirs)
            print()
            agent.chat_history.append({'role':'assistant','content':greeting})
        except (RuntimeError,ValueError) as error:print(f'(Friday could not open the conversation: {error})')
    while True:
        try:
            text=input('You > ').strip()
            if text==':help':
                print('Commands: :state, :self, :reflect, :growth, :trace on/off, :save, :reset, :quit  (advanced: :levels, :event, :observe with JSON)');continue
            if text in (':quit','quit','exit'): save_checkpoint(agent,state,args.checkpoint); break
            if text==':save': save_checkpoint(agent,state,args.checkpoint); print('V14 saved.'); continue
            if text in (':trace on',':trace off'):
                trace=text.endswith('on');print('Controller trace '+('on.' if trace else 'off.'));continue
            if text==':state':
                elapsed=max(0.,time.time()-(agent.state_updated_at or time.time()))
                current=agent.development.recovered_emotion(state.emotion,elapsed) if agent.cfg.developmental_emotion else state.emotion
                print(json.dumps({'emotion':dict(zip(EMOTIONS,current.tolist())),
                                  'as_of_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                                  'elapsed_recovery_seconds':elapsed,
                                  'vitality':state.vitality.item(),'needs_measured':measured,
                                  'needs_source':'external measurements' if measured else 'conversational estimates' if agent.cfg.experience_model else 'unmeasured'},indent=2))
                continue
            if text==':self':
                print(json.dumps(agent.experience.context(),indent=2) if agent.cfg.experience_model else 'Shared experience is not installed.')
                continue
            if text==':reflect':
                if last_turn is None: print('No appraisal yet. Send a message first, or use :state.')
                else: print(json.dumps(reflect(last_turn,EMOTIONS,ACTIONS),indent=2))
                continue
            if text==':growth':
                if not agent.cfg.developmental_emotion: print('Developmental appraisal is not installed in this checkpoint.')
                else:
                    dev=agent.development
                    print(json.dumps({'outcomes':int(dev.updates),'cues':dev.cues,
                        'expected_progress':dev.expected[:len(dev.cues)].tolist(),
                        'learned_control':dev.learned_control[:len(dev.cues)].tolist(),
                        'baseline':dict(zip(EMOTIONS,dev.baseline.tolist())),
                        'persistence':dict(zip(EMOTIONS,dev.persistence.tolist())),
                        'experience':agent.experience.data['stats'] if agent.cfg.experience_model else None,
                        'education':agent.experience.data.get('education') if agent.cfg.experience_model else None,
                        'emotional_depth':agent.experience.depth if agent.cfg.experience_model else None},indent=2))
                continue
            if text.startswith(':event '):
                if not agent.cfg.developmental_emotion: raise ValueError('Train/install developmental appraisal first')
                own_event=OwnEvent(**json.loads(text[7:])); print('Own-event appraisal queued for the next message.');continue
            if text==':reset':
                agent.chat_history=[]
                state=agent.initial_state(); pending=None; measured=False; last_turn=None; own_event=None
                agent.state_updated_at=time.time()
                needs=agent.deficits([.5]*len(NEEDS)); print('Episode reset; scars retained.'); continue
            if text.startswith(':levels '): needs=agent.deficits(json.loads(text[8:])); measured=True; pending=None; continue
            if text.startswith(':observe '):
                if pending is None or not measured: raise ValueError('Supply :levels, then a turn, before an outcome')
                observation=json.loads(text[9:])
                if native:
                    needs,reward=observed_outcome(agent,pending[0],observation)
                    elapsed=max(0.,time.time()-(agent.state_updated_at or time.time()))
                    current=replace(state,emotion=agent.development.recovered_emotion(state.emotion,elapsed)) if agent.cfg.developmental_emotion else state
                    observed_turn=replace(pending[0],state=current)
                    state=agent.commit_outcome(observed_turn,needs,observation.get('safe',False),reward,observation.get('control'))
                    stats={'reward':reward,'updated':'memory, vitality, and developmental outcome statistics; CPU chat keeps policy weights fixed'}
                else: state,needs,stats=learn_outcome(agent,*pending,observation)
                agent.state_updated_at=time.time()
                pending=None; print(stats); continue
            if not text: continue
            if text.startswith(':'):
                raise ValueError('Unknown or incomplete command. :levels, :event, and :observe require JSON arguments; :self shows shared experience.')
            pending=None
            prepared=None
            if agent.cfg.experience_model:start_new_conversation_if_due(agent)  # the window was left open overnight
            elapsed=max(0.,time.time()-(agent.state_updated_at or time.time()))
            if native and agent.cfg.experience_model:
                if agent.cfg.developmental_emotion:
                    state=replace(state,emotion=agent.development.recovered_emotion(state.emotion,elapsed))
                    agent.state_updated_at=time.time()
                recall=start_recall(agent,text)  # embeds on a worker thread while the language model interprets the message
                frame=interpret_turn(agent,native,text)
                state,needs,prepared=prepare_experience(agent,state,text,frame,needs,measured,recall)
            with torch.no_grad():
                ids=torch.tensor(agent.vocab.encode(text)[-agent.cfg.max_tokens:])
                elapsed=max(0.,time.time()-(agent.state_updated_at or time.time())) if hasattr(agent,'state_updated_at') else 0.
                turn=agent(ids,state,needs,text=text,history=agent.chat_history,
                           event=own_event or (prepared['event'] if prepared else None),elapsed_seconds=elapsed,
                           experience=prepared)
                own_event=None
                if prepared: prepared['self_reply']=explain_experience(agent,turn)
                action=turn.policy.argmax().item() if native else torch.multinomial(turn.policy,1).item()
                if native:
                    print(f'V14 [{ACTIONS[action]}] > ' if trace else 'Friday > ',end='',flush=True)
                    response=native.respond(turn,ACTIONS[action],on_token=lambda piece:print(piece,end='',flush=True))
                    print()
                else: response=agent.candidates(turn,action)
            agent.chat_history.extend([{'role':'user','content':text},{'role':'assistant','content':response}])
            agent.chat_history=agent.chat_history[-40:]
            if prepared: complete_experience(agent,turn,prepared,response)
            state=turn.state.detached(); pending=(turn,action,response)
            agent.state_updated_at=time.time()
            last_turn=turn
            if native:
                from chat_log import append_turn
                append_turn(ROOT,text,response,ACTIONS[action],turn,EMOTIONS,native.last_metrics,measured)
                save_checkpoint(agent,state,args.checkpoint)
            active=sorted(zip(EMOTIONS,state.emotion.tolist()),key=lambda p:p[1],reverse=True)[:3]
            if not native: print(f'V14 [{ACTIONS[action]}] > {response}')
            if trace or not native:print('State:',', '.join(f'{e}={v:.2f}' for e,v in active),f'| vitality={state.vitality.item():.2f}')
        except (ValueError,KeyError,RuntimeError,TypeError) as error: print(f'Input error: {error}')
        except (EOFError,KeyboardInterrupt): save_checkpoint(agent,state,args.checkpoint); break

if __name__=='__main__': main()
