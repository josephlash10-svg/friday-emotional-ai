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

def topic_anticipation(agent,state,text,prepared):
    """#20: a subject that came with a feeling before nudges that feeling up a little before the message is appraised,
    the way a sore subject puts a person slightly on edge as soon as it comes up. Bounded (at most +0.12), only for a
    subject coming back (not one already raised in this conversation), and it fades with the normal dynamics."""
    import emotional_life
    from dataclasses import replace
    if not getattr(agent.cfg,'developmental_emotion',False):return state
    history=agent.experience.topic_history(text,getattr(agent,'chat_history',[]))
    if not history:return state
    names=tuple(agent.development.names)
    nudge=emotional_life.topic_nudge(history,names)
    if nudge:
        emotion=state.emotion.clone()
        for name,amount in nudge.items():
            index=names.index(name);emotion[index]=min(1.,float(emotion[index])+amount)
        state=replace(state,emotion=emotion)
    prepared['topic_history']=[{'subject':subject,'it_usually_brings':emotional_life.WORDS.get(name,name),'times_before':times}
                               for subject,name,_,times in history]
    return state

def feelings_about_feelings(agent,state,text,prepared,now=None):
    """v35.1: after a short or guarded reply, a little unease about it (guilt, feeling exposed) before the next message is
    appraised; and a feeling kept small earlier, with how many exchanges ago, for the runtime to judge the timing."""
    import time
    import emotional_life
    from dataclasses import replace
    now=time.time() if now is None else now
    own=agent.experience.data.get('self_feeling') or {}
    meta=emotional_life.uneasy_after(own.get('last_mood'),text,now)
    if meta and getattr(agent.cfg,'developmental_emotion',False):
        names=tuple(agent.development.names);emotion=state.emotion.clone()
        for name,amount in emotional_life.META_NUDGE.items():
            if name in names:index=names.index(name);emotion[index]=min(1.,float(emotion[index])+amount)
        state=replace(state,emotion=emotion)
        prepared['meta_feeling']=meta
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

def explain_experience(agent,turn):
    return agent.experience.explanation(turn.text,turn,agent.development.names)
