"""Shared conversational preparation and completion used by chat and evaluation."""
import re
import torch

PROFILE_CUE=re.compile(r"(?i:(?<!\w)my name(?!\w)|(?<!\w)name(?:'|’)?s(?!\w)|(?<!\w)call me(?!\w)|(?<!\w)i work(?!\w)|(?<!\w)work(?:ing)? (?:as|at|in)(?!\w)|(?<!\w)i live(?!\w)|(?<!\w)living in(?!\w)|(?<!\w)(?:i'?m|i am|i)(?:\s+\w+)? from(?!\w)|(?<!\w)(?:i'?m|i am) an?(?!\w))|(?<!\w)(?:I'?m|I am|i'?m|i am) [A-Z][a-z]+")

def interpret_turn(agent,native,text):
    frame=agent.interpreter.interpret(agent.decoder,text,agent.experience) if agent.cfg.semantic_interpreter else native.interpret(text,agent.experience.context(),agent.chat_history)
    from conversation_evidence import declarations
    known=agent.experience.data['user'].get('name',{}).get('value')
    # The profile model call costs seconds; only make it when the message could declare a name, job or place.
    if not declarations(text,known) and PROFILE_CUE.search(text):
        profile=native.profile(text)
        if profile:
            frame.update(kind='introduction',scope='identity',subject='user',attribute=profile['attribute'],
                         value=profile['value'],evidence=profile['evidence'],confidence=profile['confidence'],
                         valence=0.,summary=profile['evidence'],_profile_parse=profile)
    return frame

def start_recall(agent,text):
    """Begin embedding the message for recall by meaning (M1) on a worker thread, before the language model is asked
    to interpret it; prepare_experience picks the vector up. None when recall by meaning is off."""
    experience=getattr(agent,'experience',None)
    if not getattr(experience,'meaning_enabled',False):return None
    return experience.meaning.embed_later(experience.expand_for_recall(text))

SELF_CUE='self:short-with-them'

def subject_of(agent,text,history=None):
    """The subject this message is about, for the event's cue: one with a feeling history first, then a person they've
    named, then a subject that has come up before. None when nothing in the message has a record."""
    import emotional_life
    people=agent.experience.data.get('people',{})
    present=emotional_life.topics(text,people)
    store=agent.experience.data.get('topic_feelings',{})
    named=[p['name'].lower() for p in people.values() if p['name'].lower() in present]
    known=sorted((t for t in present if store.get(t,{}).get('times',0)>=2),key=lambda t:-store[t]['times'])
    candidates=[h[0] for h in history or ()]+named+known
    return candidates[0] if candidates else None

def topic_anticipation(agent,state,text,prepared):
    """#20, through the math since v35.2. A subject that matters becomes the event's cue, so the appraisal reads what
    Friday has learned to expect from it: a negative expected progress raises the threat term, and a sore subject puts
    Friday on edge; better news than expected brings surprise. The expectation is learned after the turn from what the
    subject brought (complete_experience). No direct edit of the state: until v35.1 this added up to 0.08 to a feeling."""
    import emotional_life
    from dataclasses import replace
    history=agent.experience.topic_history(text,getattr(agent,'chat_history',[]))
    if history:
        prepared['topic_history']=[{'subject':subject,'it_usually_brings':emotional_life.WORDS.get(name,name),'times_before':times}
                                   for subject,name,_,times in history]
    if not getattr(agent.cfg,'developmental_emotion',False) or prepared.get('frame',{}).get('kind') in ('correction','feedback'):
        return state  # corrections and feedback keep their own cues, which explicit outcomes train
    subject=subject_of(agent,text,history)
    if subject and prepared.get('event') is not None:
        cue='subject:'+subject[:60]
        prepared['subject_cue']=cue
        prepared['event']=replace(prepared['event'],cue=cue)
        if prepared.get('mixed'):
            prepared['mixed']=dict(prepared['mixed'],events=[replace(e,cue=cue) for e in prepared['mixed']['events']])
    return state

def feelings_about_feelings(agent,state,text,prepared,now=None):
    """After a short or guarded reply, the unease about it, through the math since v35.2: "I was short with them" is
    appraised as its own event (a small loss Friday caused and can repair), next to the message. The guilt comes from the
    appraisal (section 2 of docs/MATH.md: loss x Friday's agency); until v35.1 this added 0.04 guilt to the state directly.
    Also: a feeling kept small earlier, with how many exchanges ago, for the runtime to judge the timing."""
    import time
    import emotional_life
    from developmental_emotion import OwnEvent
    now=time.time() if now is None else now
    own=agent.experience.data.get('self_feeling') or {}
    meta=emotional_life.uneasy_after(own.get('last_mood'),text,now)
    if not meta and emotional_life.ASKS_ABOUT_YOU.search(text.replace('’',"'")):
        # "you seemed kind of short with me before" two replies later (v35.1 targeted run): the unease is still there
        # within the hour when they ask about it.
        meta=emotional_life.uneasy_after(own.get('last_short'),text,now)
    if meta:
        prepared['meta_feeling']=meta
        if getattr(agent.cfg,'developmental_emotion',False):
            # Mattered moderately (0.5), clearly Friday's doing (agency -0.9), a small loss (-0.3) it can repair (control 0.7).
            # Probed on the release engine: guilt 0.078 against 0.023 for an ordinary message, with some sadness and tension.
            prepared['self_events']=[OwnEvent(cue=SELF_CUE,relevance=.5,progress=-.3,certainty=.6,control=.7,novelty=.1,effort=.2,agency=-.9)]
    held=own.get('held_back')
    if held:
        prepared['held_back']=dict(held,exchanges_since=agent.experience.data['stats']['interactions']-held.get('exchange',0))
    return state

def prepare_experience(agent,state,text,frame,needs,measured=False,recall=None):
    query_vector=None
    if recall is not None:
        query_vector=recall.result()  # normally done long ago: the interpretation call takes seconds, the embedding ~10 ms
    elif getattr(agent.experience,'meaning_enabled',False):
        vector=agent.experience.meaning.embed([agent.experience.expand_for_recall(text)])
        query_vector=None if vector is None else vector[0]
    prepared=agent.experience.prepare(text,frame,query_vector)
    state=topic_anticipation(agent,state,text,prepared)
    state=feelings_about_feelings(agent,state,text,prepared)
    import emotional_life
    if emotional_life.ASKS_ABOUT_PATTERNS.search(text.replace('’',"'")):
        prepared['emotional_patterns']=agent.experience.emotional_patterns()  # #22: what Friday has learned about itself
    if frame.get('_profile_parse'):prepared['profile_parse']=frame['_profile_parse']
    feedback=prepared['feedback']
    if feedback:
        episode=next((v for v in agent.experience.data['episodes'] if v['id']==feedback['episode_id']),None)
        if episode and episode.get('development'):
            quality=feedback['quality']*feedback['confidence']
            agent.development.observe(episode['development'],quality)
            state=state.detached()
            # Explicit conversational evaluation is a signed own-functioning proxy,
            # distinct from externally measured homeostatic levels.
            state.vitality=.8*state.vitality+.2*state.vitality.new_tensor(quality)
    agent.experience.learn(prepared)
    if not measured: needs=agent.deficits(prepared['levels'])
    prepared['emotion_names']=tuple(agent.development.names)
    # Verify memory claims against the stored record (which survives restarts) before the writer sees them.
    from conversation_evidence import memory_check
    episodes=agent.experience.data['episodes']
    record=[row for e in episodes for row in ({'role':'user','content':e['input'],'time_utc':e.get('time_utc')},
                                              {'role':'assistant','content':e.get('response',''),'time_utc':e.get('time_utc')})]
    current=sum(r['role']=='user' for r in getattr(agent,'chat_history',[]))
    check=memory_check(text,record,earlier_conversations=max(0,len(episodes)-current),experience=agent.experience)
    if check:prepared['memory_check']=check
    # How much history really exists, so a first conversation can't "remember" an earlier one.
    prepared['record_counts']={'exchanges_from_earlier_conversations':max(0,len(episodes)-current),
                               'earlier_messages_in_this_conversation':current}
    prepared['time_context']=time_context(agent.experience,current)
    prepared['feeling_history']=agent.experience.feeling_history()
    prepared['their_words']=[e['input'] for e in episodes]  # whose sister, whose wedding: for the speaker fixes after review
    return state,needs,prepared

def time_context(experience,messages_so_far,now=None):
    """What day it is, when they last talked, and where their announced events stand, for every reply. Without it the
    writer said "tomorrow" on the day of a dinner and "I don't remember our past conversations" (2026-10-29)."""
    import time
    import time_sense
    now=time.time() if now is None else now
    context={'right_now':time_sense.now_words(now)}
    earlier,_=experience.conversation_split(now)
    if earlier:
        ended=time_sense.parse(earlier[-1]['end_utc'])
        context['previous_conversation']={'ended':time_sense.when_words(ended,now),'how_long_ago':time_sense.gap_words(now-ended)}
        if messages_so_far<=3:
            top=sorted(earlier[-1]['highlights'],key=lambda h:h['score'],reverse=True)[:3]
            if top:context['previous_conversation']['they_told_you']=[h['text'][:100] for h in sorted(top,key=lambda h:h['time_utc'])]
    else:context['previous_conversation']='none: this is your first conversation with them'
    events=experience.events_near(now)
    if events:context['their_dated_events']=events
    return context

def complete_experience(agent,turn,prepared,response):
    agent.experience.record(turn.text,response,turn,prepared)
    # v35.2: the subject's cue learns what it usually brings (the appraised progress), for next time it comes up.
    if prepared.get('subject_cue') and turn.development and getattr(agent.cfg,'developmental_emotion',False):
        agent.development.expect(prepared['subject_cue'],float(turn.development['event']['progress']))

def explain_experience(agent,turn):
    return agent.experience.explanation(turn.text,turn,agent.development.names)
