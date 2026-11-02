"""Persistent, evidence-backed experience model and conversational learning.

The language model proposes interpretations. Exact source spans are required
before any proposal can update identity, lessons, or conversational feedback.
Confidence is a heuristic, not a calibrated probability of truth.
"""
import copy
import datetime
import math
import re
import threading
import time
from dataclasses import replace
from developmental_emotion import OwnEvent
from conversation_evidence import declarations,correction_topics,speaker_terms,belief_revision,interpersonal_report,content_words
import time_sense

KINDS=('ordinary','correction','feedback','introduction','relationship','preference','self_question')
SCOPES=('intent','answer','relationship','preference','external_fact','identity','none')
SUBJECTS=('agent','user','other','unspecified')

def validate_frame(text, proposed):
    neutral={'kind':'ordinary','scope':'none','summary':'Uncertain interpretation of this message.',
             'evidence':'','confidence':0.,'valence':0.,'attribute':'','value':'','lesson':'','subject':'unspecified'}
    if not isinstance(proposed,dict): return neutral
    if proposed.get('kind') not in KINDS or proposed.get('scope') not in SCOPES: return neutral
    evidence=proposed.get('evidence','')
    if not isinstance(evidence,str) or not evidence.strip() or evidence not in text: return neutral
    try:
        confidence=float(proposed.get('confidence',0));valence=float(proposed.get('valence',0))
    except (ValueError,TypeError): return neutral
    if not math.isfinite(confidence) or not 0<=confidence<=1 or not math.isfinite(valence) or not -1<=valence<=1: return neutral
    out={**neutral,'kind':proposed['kind'],'scope':proposed['scope'],'evidence':evidence[:400],
         'confidence':confidence,'valence':valence}
    out['subject']=proposed.get('subject','unspecified') if proposed.get('subject','unspecified') in SUBJECTS else 'unspecified'
    scope_confidence=proposed.get('scope_confidence',confidence)
    out['scope_uncertain']=isinstance(scope_confidence,(float,int)) and scope_confidence<.65
    for name in ('summary','attribute','value','lesson'):
        value=proposed.get(name,'')
        if not isinstance(value,str): return neutral
        out[name]=value[:240]
    if out['kind']=='correction' and not out['lesson']: return neutral
    if confidence<.65: return {**out,'kind':'ordinary','scope':'none','lesson':'','attribute':'','value':''}
    return out

class ExperienceModel:
    # Raw exchanges kept word for word. It was 64, about five days of talking (10-day simulation, 2026-10-29); the
    # oldest still drop first, but every exchange also leaves a trace in its conversation's summary, which is kept.
    capacity=400
    lesson_capacity=64
    conversation_capacity=300
    highlights_per_conversation=8
    def __init__(self,snapshot=None):
        self.data={'version':1,'self':{'name':'Friday','nature':'computational emotional agent'},
                   'user':{},'relationship':{'description':'conversation partners','source':'initial design'},
                   'goals':{'understanding':.8,'usefulness':.7,'continuity':.5},
                   'lessons':[],'episodes':[],'last_significant':None,
                   'stats':{'interactions':0,'corrections':0,'feedback':0,'confirmed_transfers':0},
                   'needs':[.5]*7,'conversations':[],'events':[]}
        if snapshot is not None:
            if not isinstance(snapshot,dict) or snapshot.get('version')!=1: raise ValueError('Unsupported experience memory')
            if len(snapshot.get('episodes',[]))>self.capacity or len(snapshot.get('lessons',[]))>self.lesson_capacity:
                raise ValueError('Experience memory exceeds capacity')
            self.data=copy.deepcopy(snapshot)
            if 'conversations' not in self.data:self._backfill()
            if 'people' not in self.data:
                self.data['people']={}
                for episode in self.data['episodes']:
                    try:self._note_people(episode['input'],time_sense.parse(episode['time_utc']))
                    except (KeyError,ValueError,TypeError):pass

    def snapshot(self): return copy.deepcopy(self.data)

    # --- Conversations, events and feelings over time (v33) ---------------------------------------------------------
    def _backfill(self):
        """Memories saved before v33 have episodes but no conversation summaries or events: rebuild them from the episodes."""
        self.data['conversations'],self.data['events']=[],[]
        for episode in self.data['episodes']:
            try:said=time_sense.parse(episode['time_utc'])
            except (KeyError,ValueError,TypeError):continue
            self._note_conversation(episode,said);self._note_events(episode['input'],said)
            # Profile facts said before the "Im" fix never reached the profile (live chat 2026-10-29: the job was lost).
            for found in declarations(episode['input'],self.data['user'].get('name',{}).get('value')):
                self.data['user'].setdefault(found['attribute'],{'value':found['value'],'evidence':found['evidence']})

    @staticmethod
    def _highlight_score(episode):
        text=episode['input'];lower=text.lower().replace('’',"'")
        words=content_words(text)
        if len(words)<2:return 0.
        before,after=episode.get('before',{}),episode.get('after',{})
        salience=max((abs(v-before.get(k,0)) for k,v in after.items()),default=0)
        score=min(.5,.06*len(words))+2*salience
        if re.search(r"\b(?:i|i'm|im|i've|my|me|we|our)\b",lower):score+=.25
        if time_sense.announced_events(text,time.time()):score+=.3
        if '?' in text and not re.search(r"\b(?:my|i'm|im|i)\b",lower):score-=.4  # a question about Friday, not news about them
        return score

    def _note_conversation(self,episode,said):
        """Fold one exchange into its conversation's summary: when, how many exchanges, the most telling things they
        said, and how Friday's feelings moved. Episodes can then be dropped without losing what a conversation was about."""
        conversations=self.data.setdefault('conversations',[])
        current=conversations[-1] if conversations else None
        if current is None or said-time_sense.parse(current['end_utc'])>time_sense.NEW_CONVERSATION_GAP:
            current={'id':(current['id']+1) if current else 1,'start_utc':episode['time_utc'],'end_utc':episode['time_utc'],
                     'exchanges':0,'highlights':[],'feelings':[]}
            conversations.append(current);del conversations[:-self.conversation_capacity]
        current['end_utc']=episode['time_utc'];current['exchanges']+=1
        score=self._highlight_score(episode)
        if score>.2:
            current['highlights'].append({'time_utc':episode['time_utc'],'text':episode['input'][:140],'score':round(score,3)})
            if len(current['highlights'])>self.highlights_per_conversation:
                current['highlights'].remove(min(current['highlights'],key=lambda h:h['score']))
        before,after=episode.get('before',{}),episode.get('after',{})
        for name,value in after.items():
            change=value-before.get(name,0)
            if change<.05:continue
            known=next((f for f in current['feelings'] if f['emotion']==name),None)
            if known and known['change']>=change:continue
            if known:current['feelings'].remove(known)
            current['feelings'].append({'emotion':name,'change':round(change,3),'time_utc':episode['time_utc'],'about':episode['input'][:100]})
        current['feelings']=sorted(current['feelings'],key=lambda f:f['change'],reverse=True)[:4]

    def _note_events(self,text,said):
        """Remember dated events they announce, so "tomorrow" can become "last night" when they come back."""
        events=self.data.setdefault('events',[])
        for event in time_sense.announced_events(text,said):
            head=event['what'].split()[-1].lower()
            day=datetime.date.fromisoformat(event['date'])
            same=next((e for e in events if e['what'].split()[-1].lower()==head and abs((datetime.date.fromisoformat(e['date'])-day).days)<=7),None)
            if same:
                # The newest statement of the date wins; the more specific name ("their sister's wedding") is kept.
                same.update(date=event['date'],part=event['part'],said_utc=time_sense.stamp(said),evidence=event['evidence'])
                if len(event['what'])>len(same['what']):same['what']=event['what']
            else:events.append({**event,'said_utc':time_sense.stamp(said)})
        today=time_sense.local_date(said)
        self.data['events']=[e for e in events if (datetime.date.fromisoformat(e['date'])-today).days>-30][-40:]

    def conversation_split(self,now=None):
        """(earlier conversations, the current one or None). A conversation is current until 3 hours of silence."""
        now=time.time() if now is None else now
        conversations=self.data.get('conversations',[])
        if conversations and now-time_sense.parse(conversations[-1]['end_utc'])<=time_sense.NEW_CONVERSATION_GAP:
            return conversations[:-1],conversations[-1]
        return conversations,None

    def events_near(self,now=None,back=4,ahead=14):
        """Their dated events from a few days ago to two weeks ahead, with where each stands now."""
        now=time.time() if now is None else now
        today=time_sense.local_date(now)
        near=[e for e in self.data.get('events',[]) if -back<=(datetime.date.fromisoformat(e['date'])-today).days<=ahead]
        rows=[]
        for event in sorted(near,key=lambda e:e['date']):
            row=time_sense.event_status(event,now)
            # Without this, Friday asked "how did the concert go?" on three days running, and a flag on the event wasn't
            # enough (third rerun): once they've told you how it went, the event is done and isn't listed.
            if self._told_about(event):continue
            rows.append(row)
        return rows

    def _told_about(self,event):
        """When they first mentioned the event on a later day than it happened, or None."""
        head=event['what'].split()[-1].lower();day=datetime.date.fromisoformat(event['date'])
        for episode in self.data['episodes']:
            try:said=time_sense.parse(episode['time_utc'])
            except (KeyError,ValueError,TypeError):continue
            if time_sense.local_date(said)>day and re.search(r'\b'+re.escape(head)+r'\b',episode['input'].lower()):
                return said
        return None

    def conversation_overview(self,now=None,limit=6,per=3):
        """The last few conversations, oldest first: when, and the most telling things they said."""
        now=time.time() if now is None else now
        earlier,current=self.conversation_split(now)
        rows=[]
        for conversation in (earlier+([current] if current else []))[-limit:]:
            top=sorted(conversation['highlights'],key=lambda h:h['score'],reverse=True)[:per]
            rows.append({'when':time_sense.when_words(time_sense.parse(conversation['start_utc']),now),
                         'they_said':[h['text'][:100] for h in sorted(top,key=lambda h:h['time_utc'])]})
        return rows

    def feeling_history(self,now=None,limit=5):
        """The biggest rises in Friday's own feelings across recent conversations: what, when, and during what."""
        now=time.time() if now is None else now
        rows=[dict(f) for c in self.data.get('conversations',[])[-12:] for f in c.get('feelings',[])]
        rows=sorted(rows,key=lambda f:f['change'],reverse=True)[:limit]
        return [{'emotion':f['emotion'],'size':'noticeable' if f['change']>=.1 else 'small',
                 'when':time_sense.when_words(time_sense.parse(f['time_utc']),now),'while_they_said':f['about']}
                for f in sorted(rows,key=lambda f:f['time_utc'])]
    @property
    def depth(self):
        stats=self.data['stats']
        evidence=.5*stats['corrections']+stats['feedback']+2*stats['confirmed_transfers']
        education=self.data.get('education',{})
        # Synthetic exposure is disclosed separately from personal conversation.
        # Breadth cap prevents repeating a single lesson from conferring maturity.
        evidence+=sum(min(12.,float(v)) for v in education.get('domain_exposures',{}).values())
        return 1-math.exp(-evidence/20)

    # --- Recall by meaning and the people they mention (M1) ------------------------------------------------------------
    meaning_enabled=False  # turned on by enable_meaning() in the chat and the red-team; tests keep word-overlap recall
    _pending_vectors=None

    SMALL_TALK_WORDS=set("good morning night evening afternoon bored ugh mondays monday same sounds cool nice thanks thank bye later "
                         "sup whats what's there ready tired great fine awesome yeah yep nope sure idk lmao haha omg wow i'm i've it's "
                         "that's you're up".split())

    @staticmethod
    def _worth_indexing(text,minimum=3):
        # Small talk isn't a memory worth recalling, and indexing it pulled "lol ok" toward every short question.
        return len(content_words(text))>=minimum

    def enable_meaning(self,meaning_index=None):
        """Recall stored exchanges by meaning. Exchanges saved without a vector are embedded on a background thread and
        merged in on the next turn, so neither the start nor the first reply waits for them."""
        import os
        import meaning_recall
        if os.environ.get('FRIDAY_MEANING','').lower()=='off':return False  # A/B timing, or to rule it out when debugging
        self.meaning=meaning_index or meaning_recall.index()
        if not self.meaning.available:return False
        self.meaning_enabled=True
        store=self.data.get('meaning')
        if not store or store.get('model')!=meaning_recall.MODEL_TAG:
            store=self.data['meaning']={'model':meaning_recall.MODEL_TAG,'ids':[],'vectors':None}
        known=set(store['ids'])
        missing=[(e['id'],e['input']) for e in self.data['episodes'] if e['id'] not in known and self._worth_indexing(e['input'])]
        if missing:
            def work():
                vectors=self.meaning.embed([t for _,t in missing])
                if vectors is not None:self._pending_vectors=([i for i,_ in missing],vectors)
            threading.Thread(target=work,name='meaning-backfill',daemon=True).start()
        return True

    def _add_vectors(self,ids,vectors):
        import torch
        store=self.data['meaning']
        vectors=vectors.to(torch.float16)
        store['vectors']=vectors if store['vectors'] is None else torch.cat([store['vectors'],vectors])
        store['ids']=store['ids']+list(ids)

    def _sync_vectors(self):
        """Merge a finished background backfill, and drop vectors whose exchanges were dropped. Main thread only."""
        pending,self._pending_vectors=self._pending_vectors,None
        store=self.data.get('meaning')
        if not store:return
        if pending:
            have=set(store['ids']);fresh=[k for k,i in enumerate(pending[0]) if i not in have]
            if fresh:self._add_vectors([pending[0][k] for k in fresh],pending[1][fresh])
        alive={e['id'] for e in self.data['episodes']}
        if store['ids'] and any(i not in alive for i in store['ids']):
            keep=[k for k,i in enumerate(store['ids']) if i in alive]
            store['vectors']=store['vectors'][keep] if keep else None
            store['ids']=[store['ids'][k] for k in keep]

    PEOPLE_RELATIONS=('brother','sister','mom','mum','mother','dad','father','son','daughter','grandson','granddaughter','grandma',
                      'grandmother','grandpa','grandfather','husband','wife','boyfriend','girlfriend','fiance','fiancé','fiancee',
                      'partner','aunt','uncle','cousin','niece','nephew','boss','manager','coworker','roommate','neighbor',
                      'best friend','friend','buddy','therapist','teacher','professor','dog','cat')
    NOT_NAMES=set('I Im The He She It They We You This That There Is Was Has Had And But So Just Really Actually Today Tomorrow Monday '
                  'Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September '
                  'October November December God Mr Mrs Ms Dr'.split())

    def _note_people(self,text,said=None):
        """Who is who, from their own words only: "my sister Anna", "Anna, my sister", "my dog is called Max". Each fact
        keeps the words it came from. Lets a question about "my sister" find a message about Anna (M1)."""
        if re.search(r'(?i)\b(?:pretend|imagine|role.?play|fiction|character)\b',text):return
        clean=text.replace('’',"'")
        relation=r'(?P<rel>'+'|'.join(sorted(map(re.escape,self.PEOPLE_RELATIONS),key=len,reverse=True))+r')'
        name=r'(?P<name>[A-Z][a-z]{1,15})'
        patterns=(r'(?i:\bmy (?:little |big |older |younger |best |new )?'+relation+r')(?:,|\s)\s*(?i:(?:is |was )?(?:named |called ))?'+name+r'\b',
                  r'\b'+name+r',? (?i:(?:is|was) )?(?i:my (?:little |big |older |younger |best )?'+relation+r')\b',
                  r'(?i:\bmy '+relation+r"(?:'s name is| is named| is called| named| called)) (?P<name>[A-Za-z]{2,15})\b")
        people=self.data.setdefault('people',{})
        for pattern in patterns:
            for m in re.finditer(pattern,clean):
                who=m.group('name');who=who[:1].upper()+who[1:]
                if who in self.NOT_NAMES or who.lower() in self.PEOPLE_RELATIONS:continue
                people[who.lower()]={'name':who,'relation':m.group('rel').lower(),'evidence':m.group(0)[:120],
                                     'time_utc':time_sense.stamp(said)}
        if len(people)>60:
            for key in sorted(people,key=lambda k:people[k]['time_utc'])[:len(people)-60]:people.pop(key)

    def expand_for_recall(self,text):
        """Add who's who to a recall query: "how's my sister doing" also looks for Anna, and "Anna" for "sister"."""
        extra=[]
        lower=text.lower()
        for person in self.data.get('people',{}).values():
            if re.search(r'\b'+re.escape(person['relation'])+r'\b',lower) and person['name'].lower() not in lower:extra.append(person['name'])
            elif re.search(r'\b'+re.escape(person['name'].lower())+r'\b',lower) and person['relation'] not in lower:extra.append(person['relation'])
        return text+(' ('+', '.join(extra)+')' if extra else '')

    def people_context(self,text,history=()):
        """The people in this message or the last few, with how they relate to the person, for the writer."""
        people=self.data.get('people',{})
        recent=(' '.join(r['content'] for r in list(history)[-4:] if r.get('role')=='user')+' '+text).lower()
        named={p['name']:'their '+p['relation'] for p in people.values()
               if re.search(r'\b(?:'+re.escape(p['name'].lower())+'|'+re.escape(p['relation'])+r')\b',recent)}
        return dict(list(named.items())[:6])

    def _meaning_rows(self,text,query_vector,limit=3,floor=.25):
        """The stored exchanges closest in meaning to the message (cosine over unit vectors)."""
        store=self.data.get('meaning')
        if query_vector is None or not store or store.get('vectors') is None or not content_words(text):return []
        vectors=store['vectors'].float()
        sims=(vectors@query_vector.float().reshape(-1)).tolist()
        by_id={e['id']:e for e in self.data['episodes']}
        chosen,rows=[],[]
        for k in sorted(range(len(sims)),key=lambda k:sims[k],reverse=True):
            episode=by_id.get(store['ids'][k])
            if sims[k]<floor or len(rows)==limit:break
            if episode is None or episode['interpretation'].get('scope')=='external_fact':continue
            # Never the same thing twice: a message said on many days filled every slot and pushed the answer out.
            if any(float(vectors[k]@vectors[j])>.92 for j in chosen):continue
            chosen.append(k);rows.append(episode)
        return rows

    def retrieve(self,text,limit=2,query_vector=None):
        """Conservative topic retrieval, biased by real emotional significance.

        A matched episode is a recorded exchange, not a verified life event.
        Affect can prioritize a relevant memory; it cannot manufacture one.
        With a query vector (M1), the closest exchanges by meaning come first; word overlap fills in after them.
        """
        self._sync_vectors()
        # "good morning", "i'm bored", "same": a few words of small talk recalled unrelated memories on a single word or a
        # vague mood (recall test). Short messages recall nothing unless they name someone Friday knows about.
        if len(text.split())<4 and not (content_words(text)-self.SMALL_TALK_WORDS) and self.expand_for_recall(text)==text:return []
        meaning=self._meaning_rows(text,query_vector)
        if meaning:limit=max(limit,3)
        text=self.expand_for_recall(text)
        # Greetings and filler matched old exchanges: "hey. long day" recalled "hey friday, finally friday lol" and the
        # writer answered a Monday with "Finally Friday too!" (v33 rerun, 2026-10-29).
        stop=set('i me my mine you your yours we us our the a an is are was were be been it that this those these to of in on for with and or but what how why who when where did do does have has had can could would will please tell remember earlier again about said told mention conversation talking something just '
                 'hey hi hello yo lol haha ok okay yeah yep nah so well oh im its dont got get gonna going know think really still much long since last talk talked day today time back'.split())
        aliases={'died':'loss','death':'loss','die':'loss','lost':'loss','grieving':'loss','grief':'loss','missing':'miss','kitten':'cat','puppy':'dog'}
        def tokens(value):return {aliases.get(v,v) for v in re.findall(r'\b[\w-]+\b',value.lower()) if v not in stop}
        query=tokens(text);ranked=[]
        anchors=query.intersection({'cat','dog','mother','father','brother','sister','school','holiday','coffee'})
        for index,episode in enumerate(self.data['episodes']):
            if episode['interpretation'].get('scope')=='external_fact' or not self._worth_indexing(episode['input'],2):continue
            words=tokens(episode['input']);overlap=query.intersection(words)
            if not overlap or (anchors and not anchors.issubset(words)):continue
            relevance=len(overlap)/max(1,len(query))
            if relevance<.25:continue
            before,after=episode.get('before',{}),episode.get('after',{})
            salience=max((abs(v-before.get(k,0)) for k,v in after.items()),default=0)
            score=relevance+.1*min(1,salience/.2)+.05*(index+1)/max(1,len(self.data['episodes']))
            ranked.append((score,episode))
        rows=[]
        chosen,said=[],set()
        for episode in meaning+[e for _,e in sorted(ranked,key=lambda r:r[0],reverse=True)]:
            if episode['input'].strip().lower() not in said:
                said.add(episode['input'].strip().lower());chosen.append(episode)
        for episode in chosen[:limit]:
            before,after=episode.get('before',{}),episode.get('after',{})
            rows.append({'source_type':'recorded_user_message','user_report':episode['input'][:240],
                'user_report_is_not_verified_world_fact':True,
                'agent_reply':episode['response'][:160],'agent_reply_is_not_verified_world_fact':True,
                'interpretation':{k:episode['interpretation'].get(k) for k in ('kind','scope','subject')},
                'time_utc':episode.get('time_utc'),
                'emotional_changes':[{ 'quality':k,'direction':'increased' if v-before.get(k,0)>0 else 'decreased'}
                    for k,v in sorted(after.items(),key=lambda r:abs(r[1]-before.get(r[0],0)),reverse=True)[:3]
                    if abs(v-before.get(k,0))>.02]})
        return rows

    def context(self,frame=None,query_vector=None):
        # Supply scoped source-backed lessons, not the entire growing biography.
        lessons=[{'scope':v['scope'],'lesson':v['lesson'][:120],'source':v['evidence'][:80]}
                 for v in self.data['lessons'] if v['scope']!='external_fact' and v.get('status')!='tentative_interpretation'][-2:]
        last=self.data['last_significant']
        if last:
            source=last
            last={'summary':source['summary'][:120],'kind':source['kind'],'scope':source['scope'],
                  'source':source.get('input','')[:160],
                  'source_status':'unverified_external_claim' if source['scope']=='external_fact' else 'recorded_user_message'}
            if source['kind']=='correction':last.update(correction_topics(source.get('input','')))
            revision=belief_revision(source.get('input',''))
            if revision:last['belief_revision']=revision
            action_report=interpersonal_report(source.get('input',''))
            if action_report:last['interpersonal_event']=action_report
            before,after=source.get('before',{}),source.get('after',{})
            changes=sorted(((k,before.get(k,0),v) for k,v in after.items()),key=lambda x:abs(x[2]-x[1]),reverse=True)[:3]
            last['recorded_changes']=[{'emotion':k,'before':round(b,3),'after':round(v,3)} for k,b,v in changes]
            event=source.get('appraisal')
            if event:last['estimated_appraisal']={k:round(event[k],2) for k in ('relevance','progress','certainty','safety','support','agency')}
        user={key:value['value'][:100] for key,value in self.data['user'].items()}
        interpretation={key:frame[key] for key in ('kind','scope','summary','subject')} if frame else None
        if frame:
            action_report=interpersonal_report(frame['evidence'])
            if action_report:interpretation['interpersonal_event']=action_report
        if frame and frame['kind']=='correction':
            interpretation.update(correction_topics(frame['evidence']))
            revision=belief_revision(frame['evidence'])
            if revision:interpretation['belief_revision']=revision
        for lesson in lessons:
            lesson.update(correction_topics(lesson['source']))
        education=self.data.get('education',{})
        domain='perspective' if frame and frame['scope']=='intent' else 'accountability' if frame and frame['scope']=='answer' else 'grounding'
        principles=[v['lesson'] for v in education.get('lessons',[]) if v['domain'] in (domain,'ambivalence')][:3]
        return {'self':{'name':self.data['self'].get('preferred_name',{}).get('value',self.data['self']['name']),
                        'nature':self.data['self']['nature']},
                'user':user,'relationship':self.data['relationship']['description'][:120],
                'goals':self.data['goals'],'lessons':lessons,'emotional_depth':round(self.depth,3),
                'last_significant':last,'current_interpretation':interpretation,
                'learned_principles':principles,'education_source':education.get('source'),
                'people_they_mentioned':self.people_context(frame['evidence']) if frame else {},
                'recalled_experiences':self.retrieve(frame['evidence'],query_vector=query_vector) if frame else []}

    def prepare(self,text,proposed,query_vector=None):
        frame=validate_frame(text,proposed)
        kind,scope=frame['kind'],frame['scope']
        previous=self.data['episodes'][-1] if self.data['episodes'] else None
        # Same-user scoped lessons can be retrieved even when wording changes.
        applicable=[v for v in self.data['lessons'] if (v['scope']==scope or (kind=='correction' and v['scope']=='intent')) and scope!='external_fact' and v.get('status')!='tentative_interpretation'][-3:]
        feedback=None
        if previous and not previous.get('feedback_used') and kind in ('correction','feedback') and scope!='external_fact' and not frame.get('scope_uncertain'):
            quality=(.2 if scope in ('intent','relationship','preference') else -.4) if kind=='correction' else frame['valence']
            feedback={'episode_id':previous['id'],'quality':quality,
                      'source':frame['evidence'],'scope':scope,'confidence':frame['confidence']}
        if kind=='correction':
            # Revisable answer/intent, not rejection of the agent's whole identity.
            progress=.35 if scope in ('intent','preference','relationship') else -.3
            event=OwnEvent(cue='conversation:'+scope,relevance=.8,progress=progress,certainty=.75,
                           control=.75,novelty=.4,support=.6 if scope in ('intent','relationship') else .2)
        elif kind=='feedback':
            event=OwnEvent(cue='conversation:'+scope,relevance=.75,progress=frame['valence'],certainty=.8,control=.65,support=max(0,frame['valence']))
        elif kind in ('introduction','relationship','preference'):
            event=OwnEvent(cue='conversation:'+scope,relevance=.5,progress=.2,certainty=.8,control=.6,novelty=.5,support=.4)
        elif kind=='self_question':
            event=OwnEvent(cue='self-understanding',relevance=.25,certainty=.7,control=.6,novelty=.2)
        else:
            # Ordinary turns have modest epistemic significance, not guessed distress.
            event=OwnEvent(cue='conversation:understanding',relevance=.15,certainty=max(.4,frame['confidence']),control=.6,novelty=.15)
        inference=proposed.get('_own_event') if isinstance(proposed,dict) else None
        if inference is not None:
            # Learned text-to-own-event estimates are not measured world facts.
            event=OwnEvent(cue=event.cue,**inference)
            if scope=='external_fact':event=replace(event,progress=0.,safety=0.,agency=0.)
        goal='continuity' if scope=='relationship' else 'understanding' if kind=='correction' else 'usefulness'
        event=replace(event,relevance=event.relevance*(.5+.5*self.data['goals'][goal]))
        if applicable and kind=='correction':
            event=replace(event,certainty=max(event.certainty,.85),novelty=.15,support=max(event.support,.5))
        if frame.get('scope_uncertain'): event=replace(event,certainty=min(event.certainty,.55))
        levels=list(self.data['needs'])
        levels[0]=.35 if kind=='correction' and scope=='answer' else .5
        levels[1]=.35 if frame['confidence']<.65 else .5
        applied=[v['id'] for v in applicable]
        return {'frame':frame,'event':event,'feedback':feedback,'levels':levels,
                'applied_lessons':applied,'context':self.context(frame,query_vector),'depth':self.depth,'query_vector':query_vector,
                'semantic_key':proposed.get('_semantic_key') if isinstance(proposed,dict) else None,
                'semantic_class':proposed.get('_semantic_class') if isinstance(proposed,dict) else None}

    def learn(self,prepared):
        """Commit validated conversational evidence once, before the new appraisal."""
        frame=prepared['frame'];kind,scope=frame['kind'],frame['scope']
        feedback=prepared['feedback']
        if feedback:
            previous=next((v for v in self.data['episodes'] if v['id']==feedback['episode_id']),None)
            if previous and not previous.get('feedback_used'):
                previous['feedback_used']=True
                if kind=='feedback' and previous['interpretation']['kind'] not in ('feedback','self_question'):
                    self.data['stats']['feedback']+=1
                    if feedback['quality']>.3 and previous.get('applied_lessons'):
                        self.data['stats']['confirmed_transfers']+=1
                if kind=='feedback' and feedback['quality']>.3:
                    for lesson in self.data['lessons']:
                        if lesson['status']=='tentative_interpretation' and lesson['evidence']==previous['interpretation']['evidence']:
                            lesson['status']='user_confirmed';self.data['stats']['corrections']+=1
        if kind=='correction':
            # External facts remain assertions needing verification, not accepted truths.
            status='unverified_external_claim' if scope=='external_fact' else 'tentative_interpretation' if frame.get('scope_uncertain') else 'user_report'
            same=next((v for v in self.data['lessons'] if v['scope']==scope and v['lesson']==frame['lesson']),None)
            if not same:
                if scope!='external_fact' and not frame.get('scope_uncertain'): self.data['stats']['corrections']+=1
                entry={'id':max([v['id'] for v in self.data['lessons']],default=0)+1,'scope':scope,'lesson':frame['lesson'],
                       'evidence':frame['evidence'],'confidence':frame['confidence'],'status':status,
                       'semantic_key':prepared['semantic_key'],'semantic_class':prepared['semantic_class']}
                self.data['lessons'].append(entry);self.data['lessons']=self.data['lessons'][-self.lesson_capacity:]
            self.data['goals']['understanding']=min(1.,self.data['goals']['understanding']+.02)
        attribute,value=frame['attribute'],frame['value']
        if kind in ('introduction','correction'):
            for declaration in declarations(frame['evidence'],self.data['user'].get('name',{}).get('value')):
                self.data['user'][declaration['attribute']]={'value':declaration['value'],'evidence':declaration['evidence']}
        if kind=='preference' and attribute in ('reply_style','preferred_agent_name') and value:
            if attribute=='preferred_agent_name': self.data['self']['preferred_name']={'value':value,'evidence':frame['evidence']}
            else: self.data['user']['reply_style']={'value':value,'evidence':frame['evidence']}
        if kind=='relationship' and value:
            self.data['relationship']={'description':value,'source':'user_description','evidence':frame['evidence']}
        self.data['needs']=prepared['levels']
        prepared['depth']=self.depth
        prepared['context']=self.context(frame,prepared.get('query_vector'))

    def record(self,text,response,turn,prepared):
        stats=self.data['stats'];stats['interactions']+=1
        names=prepared.get('emotion_names',())
        before=dict(zip(names,turn.before.emotion.tolist()))
        after=dict(zip(names,turn.state.emotion.tolist()))
        now=time.time()
        episode={'id':stats['interactions'],'time_utc':time_sense.stamp(now),'input':text[:400],'response':response[:400],
                 'interpretation':prepared['frame'],'applied_lessons':prepared['applied_lessons'],
                 'before':before,'after':after,'development':turn.development,'feedback_used':False}
        self.data['episodes'].append(episode);self.data['episodes']=self.data['episodes'][-self.capacity:]
        self._note_conversation(episode,now);self._note_events(text,now);self._note_people(text,now)
        if self.meaning_enabled and self._worth_indexing(text):
            # After the reply is on screen: about 10 ms, while the checkpoint is being saved anyway.
            self._sync_vectors()
            vector=self.meaning.embed([text])
            if vector is not None:self._add_vectors([episode['id']],vector)
        significant=turn.development and turn.development['event']['relevance']>.35
        if prepared['frame']['kind'] in ('correction','feedback','introduction','relationship','preference') or significant:
            # Compact, source-backed narrative for later self explanations.
            self.data['last_significant']={'input':text[:240],'summary':prepared['frame']['summary'],
                'kind':prepared['frame']['kind'],'scope':prepared['frame']['scope'],
                'before':before,'after':after,'strategy':turn.development['strategy'] if turn.development else 'NONE',
                'appraisal':turn.development['event'] if turn.development else None}

    def explanation(self,text,turn,names):
        query=text.lower().strip().rstrip('?! .')
        self_name=self.data['self'].get('preferred_name',{}).get('value',self.data['self']['name'])
        user_name=self.data['user'].get('name',{}).get('value')
        current=turn.experience['frame'] if turn.experience else None
        simple_statement=len(text)<100 and '?' not in text and not re.search(r'\b(?:explain|tell me|help me|can you)\b',query)
        if current and simple_statement:
            if current['kind']=='introduction' and current['attribute']=='name' and user_name:
                shown=user_name[:1].upper()+user_name[1:] if user_name.islower() else user_name
                if re.search(r'(?i)(?<!\w)(?:call me|actually|now|not|instead|always been|go by)(?!\w)',text):
                    return f'Got it, I’ll call you {shown}.'
                return f'Nice to meet you, {shown}.'
            if current['kind']=='relationship' and self.data['relationship']['source']=='user_description':
                return 'That’s how I’ll understand our relationship: '+self.data['relationship']['description']+'. We can revisit that understanding as our shared experience develops.'
        if current and current.get('scope_uncertain') and current['kind']=='correction':
            return 'I can see that you’re correcting something, but I’m not yet sure which interpretation to change. Could you clarify the part you want me to revisit?'
        if re.search(r'\bhow\b.*\b(?:you use|you learn|use|learn from)\b.*\b(?:corrections?|feedback)\b',query):
            return 'When you correct me, I keep that feedback attached to the exchange it concerns. In a similar situation, I can retrieve the lesson and revise my expectations and appraisal. If I’m unsure what you’re correcting, I ask rather than assume. That learning survives saving and restarting; it does not guarantee that every future interpretation will be right.'
        # Bind short learning acknowledgments to recorded speaker/source, avoiding
        # a generator's reversal of "your answer" and "I meant". Questions and
        # requests for explanation still use the open language path.
        short_feedback=len(text)<300 and '?' not in text and not re.search(r'\b(?:explain|tell me|help me|can you|why|how)\b',query)
        if current and short_feedback and current['scope']!='external_fact':
            if current['kind']=='correction':
                distinction=re.search(r'\bi meant\s+(.+?),?\s+not\s+(.+?)[.!]?$' ,text,re.I)
                if distinction:
                    return 'The distinction you’re making is “'+distinction.group(1).rstrip(',')+'” versus “'+distinction.group(2)+'”. I’ll use the first as the focus when interpreting your request.'
                direction='how I understood your intent' if current['scope']=='intent' else 'the answer I gave'
                return 'You’re correcting '+direction+': “'+current['summary'].rstrip('.')+'.” I’ll carry that clarification forward without treating it as a judgment about me as a whole.'
            if current['kind']=='feedback':
                previous=self.data['episodes'][-1] if self.data['episodes'] else None
                if previous and previous['interpretation']['kind']=='correction' and current['valence']>0:
                    return 'That confirms the clarification you gave: “'+previous['interpretation']['summary'].rstrip('.')+'.” I’ll keep it as part of how I understand you.'
                return 'Your feedback on the last exchange is “'+current['summary'].rstrip('.')+'.” I’ll use that when updating my expectations for similar exchanges.'
        if query in ('who are you','what are you','identify yourself'):
            relationship=self.data['relationship']
            context='You’ve described us as '+relationship['description']+'.' if relationship['source']=='user_description' else 'We’re getting to know each other here.'
            return f'I’m {self_name}. '+context
        if query in ('who am i','do you know who i am','what is my name','what’s my name',"what's my name"):
            details=[]
            if 'occupation' in self.data['user']:
                job=self.data['user']['occupation']['value'];article='an' if job[:1].lower() in 'aeiou' else 'a'
                details.append('you work as '+article+' '+job)
            if 'location' in self.data['user']: details.append('you live in '+self.data['user']['location']['value'])
            known=' You also told me '+ ' and '.join(details)+'.' if details else ''
            if query!='who am i':return f'You told me your name is {user_name}.' if user_name else 'You haven’t told me a name yet.'
            return f'You told me your name is {user_name}.'+known if user_name else 'You haven’t told me a name yet.'+known
        if query in ('what are we','what is our relationship','who are we'):
            relation=self.data['relationship']
            if relation['source']=='user_description': return 'You’ve described us as '+relation['description']+'. That’s how I understand our relationship so far.'
            return 'We’re conversation partners building a shared history. I don’t yet have a more specific relationship description from you.'
        feeling=re.search(r'\b(?:you feeling|you feel|your feelings|your emotions|your emotional state|why did you react|why are you feeling|what is going on inside)\b',query)
        import conversation_checks as cc
        if (turn.experience and turn.experience['frame']['scope']=='external_fact'
                and cc.contradicts_prior_claim(text,getattr(turn,'history',()))):
            # Hold the fact, but say it the way a person would (persona red-team, 2026-10-12).
            # Only when they are actually contradicting a claim Friday made (issue #2); a bare
            # assertion or an argument falls through to the open language path.
            from response_monitor import arithmetic_evidence
            calculation=arithmetic_evidence(getattr(turn,'history',()))
            if calculation and calculation['previous_result']==calculation['correct_result']:
                return f"Pretty sure it’s {calculation['correct_result']}. {calculation['expression']} is {calculation['correct_result']}."
            return 'Hm, I don’t think that’s right, so I’m not going to take it as fact. What makes you say that?'
        if not feeling or (' about ' in query and 'our conversation' not in query): return None
        current=dict(zip(names,turn.state.emotion.tolist()))
        unpleasant=sum(current.get(n,0) for n in ('fear','stress','pain'))/3
        pleasant=sum(current.get(n,0) for n in ('joy','calm','connection'))/3
        uncertain=current.get('confusion',0);interest=current.get('interest',0)
        mood='fairly settled' if max(unpleasant,uncertain)<.1 else 'somewhat unsettled' if unpleasant>pleasant else 'engaged, with some uncertainty'
        if interest>.12 and unpleasant>.12: mood='both interested and somewhat unsettled'
        past=self.data['last_significant']
        if turn.experience and turn.experience['frame']['kind']=='correction':
            frame=turn.experience['frame']
            past={'kind':'correction','summary':frame['summary'],
                  'before':dict(zip(names,turn.before.emotion.tolist())),
                  'after':dict(zip(names,turn.state.emotion.tolist()))}
        if past and past['kind']=='correction':
            opening='Your correction gave me something specific to revise: “'+past['summary'].rstrip('.')+'.” '
            if past['before'] and past['after']:
                change=past['after'].get('confusion',0)-past['before'].get('confusion',0)
                opening+='My uncertainty decreased during that appraisal. ' if change<-.02 else 'I’m still working through the uncertainty around that interpretation. '
        elif past: opening='The recent exchange I can connect this to is: '+past['summary'].rstrip('.')+'. '
        else: opening='I don’t have enough recorded experience to attribute my state to a particular event yet. '
        return opening+'Right now I’m '+mood+'. I can describe this internal pattern, but I may need your clarification to understand the situation better.'
